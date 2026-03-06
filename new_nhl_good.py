import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import uuid
import json
from datetime import datetime, timezone, timedelta
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

# --- Helper Functions ---
def get_color(rate):
    if rate >= 70: return "green"
    if rate >= 50: return "orange"
    return "red"

def toi_to_minutes(toi_str):
    if not isinstance(toi_str, str) or ":" not in toi_str: return 0.0
    m, s = map(int, toi_str.split(':'))
    return m + s / 60.0

def minutes_to_toi(total_min):
    m = int(total_min)
    s = int(round((total_min - m) * 60))
    if s == 60: m += 1; s = 0
    return f"{m}:{s:02d}"

def get_parlay_return(odds_list, bet=1.0):
    multiplier = 1.0
    for o in odds_list:
        try:
            val = int(str(o).replace('+', ''))
            if val > 0: multiplier *= (val / 100) + 1
            else: multiplier *= (100 / abs(val)) + 1
        except: continue
    return multiplier * bet

# --- Dashboard Storage ---
if 'my_dashboard' not in st.session_state:
    st.session_state.my_dashboard = []

def get_current_season_string():
    now = datetime.now()
    return f"{now.year if now.month >= 9 else now.year - 1}{now.year if now.month < 9 else now.year + 1}"

@st.cache_data(ttl=86400)
def get_all_active_players(season_str):
    all_players = []
    try:
        teams = client.teams.teams()
        for team in teams:
            abbr = team.get('abbr')
            roster = client.teams.team_roster(team_abbr=abbr, season=season_str)
            for group in ['forwards', 'defensemen', 'goalies']:
                for p in roster.get(group, []):
                    all_players.append({"id": p['id'], "name": f"{p['firstName']['default']} {p['lastName']['default']}", "team": abbr})
    except: pass
    return pd.DataFrame(all_players).sort_values("name")

@st.cache_data(ttl=3600)
def get_todays_games():
    try:
        data = client.schedule.daily_schedule(date=datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        return [{"label": f"{g['awayTeam']['abbrev']} @ {g['homeTeam']['abbrev']}", "teams": [g['awayTeam']['abbrev'], g['homeTeam']['abbrev']]} for g in data.get('games', [])]
    except: return []

# --- UI Setup ---
st.set_page_config(page_title="NHL Hit Rate Tracker", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; margin-bottom: -10px !important; }
    [data-testid="column"] { padding: 0px 5px !important; }
    .stMetric { padding: 5px !important; }
    </style>
    """, unsafe_allow_html=True)

CURRENT_SEASON = get_current_season_string()
players_df = get_all_active_players(CURRENT_SEASON)

with st.sidebar:
    st.header("Settings")
    todays_games = get_todays_games()
    game_options = ["All Teams"] + [g['label'] for g in todays_games]
    selected_game = st.selectbox("Filter by Today's Games", options=game_options)
    
    if selected_game != "All Teams":
        teams = next(g['teams'] for g in todays_games if g['label'] == selected_game)
        filtered_df = players_df[players_df['team'].isin(teams)]
    else: 
        filtered_df = players_df

    labels = filtered_df.apply(lambda x: f"{x['name']} ({x['team']})", axis=1).tolist()
    choice = st.selectbox("Select Player", options=labels)
    sel_player = filtered_df.iloc[labels.index(choice)]
    
    stat = st.selectbox("Stat", ["points", "goals", "assists", "shots", "hits", "pim", "powerPlayPoints"])
    threshold = st.number_input("Threshold", value=0.5, step=0.5)
    market_odds = st.selectbox("Market Odds", options=[str(x) for x in range(-300, -95, 5)] + [f"+{x}" for x in range(100, 305, 5)], index=41)
    games_back = st.select_slider("Last X Games", options=[5, 10, 15, 20, 30, 50], value=10)

    st.header("📋 My Dashboard")
    if st.session_state.my_dashboard:
        dash_df = pd.DataFrame(st.session_state.my_dashboard)
        dash_df['match_key'] = dash_df.apply(lambda r: " vs ".join(sorted([r['team'], r['opponent']])), axis=1)
        
        for match, group in dash_df.groupby("match_key"):
            total_ret = get_parlay_return(group['odds'].tolist())
            with st.expander(f"🆚 {match} | :green[Return ${total_ret:.2f}]", expanded=True):
                # Order props by highest value of either over or under
                group['max_rate'] = group[['over', 'under']].max(axis=1)
                sorted_group = group.sort_values(by='max_rate', ascending=False)
                
                for _, entry in sorted_group.iterrows():
                    over_c, under_c = get_color(entry['over']), get_color(entry['under'])
                    col_t, col_d = st.columns([0.8, 0.2])
                    with col_t:
                        st.markdown(
                            f"**{entry['player']}** {'🏠' if entry.get('location') == 'Home' else '✈️'}<br>"
                            f"> {entry['stat']} {entry['threshold']} @ **{entry['odds']}**<br>"
                            f"O: :{over_c}[**{entry['over']:.0f}%**] | U: :{under_c}[**{entry['under']:.0f}%**]<br>"
                            f"<small>Streak: {entry['streak']} | Shifts: {entry['avg_shifts']} | TOI: {entry['avg_toi']}</small>", 
                            unsafe_allow_html=True
                        )
                    with col_d:
                        if st.button("🗑️", key=f"del_{entry['unique_id']}"):
                            st.session_state.my_dashboard = [d for d in st.session_state.my_dashboard if d['unique_id'] != entry['unique_id']]
                            st.rerun()

    # --- JSON Save/Load Logic ---
    st.divider()
    st.subheader("💾 Backup & Restore")
    
    if st.session_state.my_dashboard:
        json_data = json.dumps(st.session_state.my_dashboard, indent=4)
        # Calculate EST (UTC-5)
        est_now = datetime.now(timezone.utc) - timedelta(hours=5)
        timestamp = est_now.strftime('%Y-%m-%d_%H-%M')
        
        st.download_button(
            label="Download Dashboard (JSON)",
            data=json_data,
            file_name=f"nhl_props_{timestamp}_EST.json",
            mime="application/json",
            use_container_width=True
        )

    uploaded_file = st.file_uploader("Upload Saved Dashboard", type=["json"])
    if uploaded_file is not None:
        try:
            new_data = json.load(uploaded_file)
            if isinstance(new_data, list):
                if st.button("Confirm Load (Overwrites Current)", type="primary", use_container_width=True):
                    st.session_state.my_dashboard = new_data
                    st.rerun()
            else:
                st.error("Invalid JSON format.")
        except Exception as e:
            st.error(f"Error loading file: {e}")

# --- Analysis Logic ---
if sel_player['id']:
    try:
        team_sched = client.schedule.team_weekly_schedule(team_abbr=sel_player['team'])
        games_list = team_sched if isinstance(team_sched, list) else team_sched.get('games', [])
        next_game = {"opponent": "N/A", "location": "N/A", "date": None}
        for g in games_list:
            if datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')) > datetime.now(timezone.utc):
                is_home = g['homeTeam']['abbrev'] == sel_player['team']
                next_game = {
                    "opponent": g['awayTeam']['abbrev'] if is_home else g['homeTeam']['abbrev'],
                    "location": "Home" if is_home else "Road",
                    "date": datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).date()
                }
                break

        full_log_data = client.stats.player_game_log(player_id=sel_player['id'], season_id=CURRENT_SEASON, game_type=2)
        full_games_log = full_log_data if isinstance(full_log_data, list) else full_log_data.get('gameLog', [])
        recent_df = pd.DataFrame(full_games_log).head(games_back).copy() if full_games_log else pd.DataFrame()

        if not full_games_log:
            st.warning("No game log data available.")
        else:
            recent_df['gameDateFormatted'] = pd.to_datetime(recent_df['gameDate']).dt.strftime('%b %d')
            recent_df['toi_min'] = recent_df['toi'].apply(toi_to_minutes)
            
            df = recent_df
            df['efficiency'] = (df[stat] / df['toi_min'] * 20).round(2)
            df['pp_val'] = df.apply(lambda r: r.get('powerPlayPoints', 0) if stat in ['points','powerPlayPoints'] else (r.get('powerPlayGoals', 0) if stat=='goals' else 0), axis=1)
            df['pp_pct'] = (df['pp_val'] / df[stat].replace(0, 1) * 100).round(0)
            
            over_rate = ((df[stat] > threshold).sum() / len(df)) * 100
            under_rate = 100 - over_rate
            avg_shifts = round(df['shifts'].mean(), 1) if 'shifts' in df.columns else "N/A"
            avg_toi = minutes_to_toi(df['toi_min'].mean())
            pp_influence = (df['pp_val'].sum() / df[stat].sum() * 100) if df[stat].sum() > 0 else 0

            streak_count = 0
            is_over = df[stat].iloc[0] > threshold if not df.empty else False
            for val in df[stat]:
                if (val > threshold) == is_over: streak_count += 1
                else: break
            streak_label = f"{'O' if is_over else 'U'}{streak_count}"

            st.markdown(f"### {sel_player['name']} | {stat.capitalize()} > {threshold} | **Hit Rate (last {games_back}):** Over: :{get_color(over_rate)}[**{over_rate:.0f}%**] | Under: :{get_color(under_rate)}[**{under_rate:.0f}%**]")

            if st.button("➕ Save Prop"):
                st.session_state.my_dashboard.append({
                    "unique_id": str(uuid.uuid4()), "player": sel_player['name'], "team": sel_player['team'], 
                    "opponent": next_game['opponent'], "stat": stat.capitalize(), "threshold": threshold, 
                    "over": over_rate, "under": under_rate, "avg_shifts": avg_shifts, "avg_toi": avg_toi, 
                    "odds": market_odds, "streak": streak_label, "location": next_game["location"]
                })
                st.rerun()

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            with c1:
                st.write(f"**Stat ({streak_label})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df[stat], text=df[stat], textposition='auto', marker_color=['#2ecc71' if v > threshold else '#e74c3c' for v in df[stat]]))
                fig.add_hline(y=threshold, line_dash="dash", line_color="white")
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.write(f"**TOI ({avg_toi})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['toi_min'], text=df['toi'], textposition='auto', marker_color='#3498db'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c3:
                st.write(f"**Shifts ({avg_shifts})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['shifts'], text=df['shifts'], textposition='auto', marker_color='#1abc9c'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c4:
                st.write(f"**PP % ({pp_influence:.0f}%)**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['pp_pct'], text=df['pp_pct'].astype(str) + '%', textposition='auto', marker_color='#f1c40f'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, yaxis_range=[0, 105], margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c5:
                st.write("**Eff/20m**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['efficiency'], text=df['efficiency'], textposition='auto', marker_color='#9b59b6'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c6:
                st.write("**PP Pts**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['powerPlayPoints'], text=df['powerPlayPoints'], textposition='auto', marker_color='#e67e22'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.dataframe(df.drop(columns=['gameId', 'toi_min', 'pp_val', 'pp_pct','commonName','opponentCommonName', 'plusMinus','gameWinningGoals', 'otGoals', 'shorthandedGoals','shorthandedPoints'], errors='ignore'), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error: {e}")import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import uuid
import json
from datetime import datetime, timezone, timedelta
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

# --- Helper Functions ---
def get_color(rate):
    if rate >= 70: return "green"
    if rate >= 50: return "orange"
    return "red"

def toi_to_minutes(toi_str):
    if not isinstance(toi_str, str) or ":" not in toi_str: return 0.0
    m, s = map(int, toi_str.split(':'))
    return m + s / 60.0

def minutes_to_toi(total_min):
    m = int(total_min)
    s = int(round((total_min - m) * 60))
    if s == 60: m += 1; s = 0
    return f"{m}:{s:02d}"

def get_parlay_return(odds_list, bet=1.0):
    multiplier = 1.0
    for o in odds_list:
        try:
            val = int(str(o).replace('+', ''))
            if val > 0: multiplier *= (val / 100) + 1
            else: multiplier *= (100 / abs(val)) + 1
        except: continue
    return multiplier * bet

# --- Dashboard Storage ---
if 'my_dashboard' not in st.session_state:
    st.session_state.my_dashboard = []

def get_current_season_string():
    now = datetime.now()
    return f"{now.year if now.month >= 9 else now.year - 1}{now.year if now.month < 9 else now.year + 1}"

@st.cache_data(ttl=86400)
def get_all_active_players(season_str):
    all_players = []
    try:
        teams = client.teams.teams()
        for team in teams:
            abbr = team.get('abbr')
            roster = client.teams.team_roster(team_abbr=abbr, season=season_str)
            for group in ['forwards', 'defensemen', 'goalies']:
                for p in roster.get(group, []):
                    all_players.append({"id": p['id'], "name": f"{p['firstName']['default']} {p['lastName']['default']}", "team": abbr})
    except: pass
    return pd.DataFrame(all_players).sort_values("name")

@st.cache_data(ttl=3600)
def get_todays_games():
    try:
        data = client.schedule.daily_schedule(date=datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        return [{"label": f"{g['awayTeam']['abbrev']} @ {g['homeTeam']['abbrev']}", "teams": [g['awayTeam']['abbrev'], g['homeTeam']['abbrev']]} for g in data.get('games', [])]
    except: return []

# --- UI Setup ---
st.set_page_config(page_title="NHL Hit Rate Tracker", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; margin-bottom: -10px !important; }
    [data-testid="column"] { padding: 0px 5px !important; }
    .stMetric { padding: 5px !important; }
    </style>
    """, unsafe_allow_html=True)

CURRENT_SEASON = get_current_season_string()
players_df = get_all_active_players(CURRENT_SEASON)

with st.sidebar:
    st.header("Settings")
    todays_games = get_todays_games()
    game_options = ["All Teams"] + [g['label'] for g in todays_games]
    selected_game = st.selectbox("Filter by Today's Games", options=game_options)
    
    if selected_game != "All Teams":
        teams = next(g['teams'] for g in todays_games if g['label'] == selected_game)
        filtered_df = players_df[players_df['team'].isin(teams)]
    else: 
        filtered_df = players_df

    labels = filtered_df.apply(lambda x: f"{x['name']} ({x['team']})", axis=1).tolist()
    choice = st.selectbox("Select Player", options=labels)
    sel_player = filtered_df.iloc[labels.index(choice)]
    
    stat = st.selectbox("Stat", ["points", "goals", "assists", "shots", "hits", "pim", "powerPlayPoints"])
    threshold = st.number_input("Threshold", value=0.5, step=0.5)
    market_odds = st.selectbox("Market Odds", options=[str(x) for x in range(-300, -95, 5)] + [f"+{x}" for x in range(100, 305, 5)], index=41)
    games_back = st.select_slider("Last X Games", options=[5, 10, 15, 20, 30, 50], value=10)

    st.header("📋 My Dashboard")
    if st.session_state.my_dashboard:
        dash_df = pd.DataFrame(st.session_state.my_dashboard)
        dash_df['match_key'] = dash_df.apply(lambda r: " vs ".join(sorted([r['team'], r['opponent']])), axis=1)
        
        for match, group in dash_df.groupby("match_key"):
            total_ret = get_parlay_return(group['odds'].tolist())
            with st.expander(f"🆚 {match} | :green[Return ${total_ret:.2f}]", expanded=True):
                # Order props by highest value of either over or under
                group['max_rate'] = group[['over', 'under']].max(axis=1)
                sorted_group = group.sort_values(by='max_rate', ascending=False)
                
                for _, entry in sorted_group.iterrows():
                    over_c, under_c = get_color(entry['over']), get_color(entry['under'])
                    col_t, col_d = st.columns([0.8, 0.2])
                    with col_t:
                        st.markdown(
                            f"**{entry['player']}** {'🏠' if entry.get('location') == 'Home' else '✈️'}<br>"
                            f"> {entry['stat']} {entry['threshold']} @ **{entry['odds']}**<br>"
                            f"O: :{over_c}[**{entry['over']:.0f}%**] | U: :{under_c}[**{entry['under']:.0f}%**]<br>"
                            f"<small>Streak: {entry['streak']} | Shifts: {entry['avg_shifts']} | TOI: {entry['avg_toi']}</small>", 
                            unsafe_allow_html=True
                        )
                    with col_d:
                        if st.button("🗑️", key=f"del_{entry['unique_id']}"):
                            st.session_state.my_dashboard = [d for d in st.session_state.my_dashboard if d['unique_id'] != entry['unique_id']]
                            st.rerun()

    # --- JSON Save/Load Logic ---
    st.divider()
    st.subheader("💾 Backup & Restore")
    
    if st.session_state.my_dashboard:
        json_data = json.dumps(st.session_state.my_dashboard, indent=4)
        # Added timestamp to filename
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        st.download_button(
            label="Download Dashboard (JSON)",
            data=json_data,
            file_name=f"nhl_props_{timestamp}.json",
            mime="application/json",
            use_container_width=True
        )

    uploaded_file = st.file_uploader("Upload Saved Dashboard", type=["json"])
    if uploaded_file is not None:
        try:
            new_data = json.load(uploaded_file)
            if isinstance(new_data, list):
                if st.button("Confirm Load (Overwrites Current)", type="primary", use_container_width=True):
                    st.session_state.my_dashboard = new_data
                    st.rerun()
            else:
                st.error("Invalid JSON format.")
        except Exception as e:
            st.error(f"Error loading file: {e}")

# --- Analysis Logic ---
if sel_player['id']:
    try:
        team_sched = client.schedule.team_weekly_schedule(team_abbr=sel_player['team'])
        games_list = team_sched if isinstance(team_sched, list) else team_sched.get('games', [])
        next_game = {"opponent": "N/A", "location": "N/A", "date": None}
        for g in games_list:
            if datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')) > datetime.now(timezone.utc):
                is_home = g['homeTeam']['abbrev'] == sel_player['team']
                next_game = {
                    "opponent": g['awayTeam']['abbrev'] if is_home else g['homeTeam']['abbrev'],
                    "location": "Home" if is_home else "Road",
                    "date": datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')).date()
                }
                break

        full_log_data = client.stats.player_game_log(player_id=sel_player['id'], season_id=CURRENT_SEASON, game_type=2)
        full_games_log = full_log_data if isinstance(full_log_data, list) else full_log_data.get('gameLog', [])
        recent_df = pd.DataFrame(full_games_log).head(games_back).copy() if full_games_log else pd.DataFrame()

        if not full_games_log:
            st.warning("No game log data available.")
        else:
            recent_df['gameDateFormatted'] = pd.to_datetime(recent_df['gameDate']).dt.strftime('%b %d')
            recent_df['toi_min'] = recent_df['toi'].apply(toi_to_minutes)
            
            df = recent_df
            df['efficiency'] = (df[stat] / df['toi_min'] * 20).round(2)
            df['pp_val'] = df.apply(lambda r: r.get('powerPlayPoints', 0) if stat in ['points','powerPlayPoints'] else (r.get('powerPlayGoals', 0) if stat=='goals' else 0), axis=1)
            df['pp_pct'] = (df['pp_val'] / df[stat].replace(0, 1) * 100).round(0)
            
            over_rate = ((df[stat] > threshold).sum() / len(df)) * 100
            under_rate = 100 - over_rate
            avg_shifts = round(df['shifts'].mean(), 1) if 'shifts' in df.columns else "N/A"
            avg_toi = minutes_to_toi(df['toi_min'].mean())
            pp_influence = (df['pp_val'].sum() / df[stat].sum() * 100) if df[stat].sum() > 0 else 0

            streak_count = 0
            is_over = df[stat].iloc[0] > threshold if not df.empty else False
            for val in df[stat]:
                if (val > threshold) == is_over: streak_count += 1
                else: break
            streak_label = f"{'O' if is_over else 'U'}{streak_count}"

            st.markdown(f"### {sel_player['name']} | {stat.capitalize()} > {threshold} | **Hit Rate (last {games_back}):** Over: :{get_color(over_rate)}[**{over_rate:.0f}%**] | Under: :{get_color(under_rate)}[**{under_rate:.0f}%**]")

            if st.button("➕ Save Prop"):
                st.session_state.my_dashboard.append({
                    "unique_id": str(uuid.uuid4()), "player": sel_player['name'], "team": sel_player['team'], 
                    "opponent": next_game['opponent'], "stat": stat.capitalize(), "threshold": threshold, 
                    "over": over_rate, "under": under_rate, "avg_shifts": avg_shifts, "avg_toi": avg_toi, 
                    "odds": market_odds, "streak": streak_label, "location": next_game["location"]
                })
                st.rerun()

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            with c1:
                st.write(f"**Stat ({streak_label})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df[stat], text=df[stat], textposition='auto', marker_color=['#2ecc71' if v > threshold else '#e74c3c' for v in df[stat]]))
                fig.add_hline(y=threshold, line_dash="dash", line_color="white")
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.write(f"**TOI ({avg_toi})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['toi_min'], text=df['toi'], textposition='auto', marker_color='#3498db'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c3:
                st.write(f"**Shifts ({avg_shifts})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['shifts'], text=df['shifts'], textposition='auto', marker_color='#1abc9c'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c4:
                st.write(f"**PP % ({pp_influence:.0f}%)**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['pp_pct'], text=df['pp_pct'].astype(str) + '%', textposition='auto', marker_color='#f1c40f'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, yaxis_range=[0, 105], margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c5:
                st.write("**Eff/20m**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['efficiency'], text=df['efficiency'], textposition='auto', marker_color='#9b59b6'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)
            with c6:
                st.write("**PP Pts**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['powerPlayPoints'], text=df['powerPlayPoints'], textposition='auto', marker_color='#e67e22'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5), height=160); st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.dataframe(df.drop(columns=['gameId', 'toi_min', 'pp_val', 'pp_pct','commonName','opponentCommonName', 'plusMinus','gameWinningGoals', 'otGoals', 'shorthandedGoals','shorthandedPoints'], errors='ignore'), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error: {e}")
