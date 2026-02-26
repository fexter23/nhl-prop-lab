import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

# --- Helper Functions ---
def get_color(rate):
    """Returns green/orange/red based on hit percentage."""
    if rate >= 70: return "green"
    if rate >= 50: return "orange"
    return "red"

def toi_to_minutes(toi_str):
    """Converts MM:SS string to float minutes."""
    if not isinstance(toi_str, str) or ":" not in toi_str:
        return 0.0
    m, s = map(int, toi_str.split(':'))
    return m + s / 60.0

def minutes_to_toi(total_min):
    """Converts float minutes back to MM:SS string."""
    m = int(total_min)
    s = int(round((total_min - m) * 60))
    if s == 60: m += 1; s = 0
    return f"{m}:{s:02d}"

# --- Initialize Dashboard Storage ---
if 'my_dashboard' not in st.session_state:
    st.session_state.my_dashboard = []

def get_current_season_string():
    now = datetime.now()
    start_year = now.year if now.month >= 9 else now.year - 1
    return f"{start_year}{start_year + 1}"

@st.cache_data(ttl=86400)
def get_all_active_players(season_str):
    all_players = []
    try:
        teams_data = client.teams.teams()
        for team in teams_data:
            abbr = team.get('abbr')
            roster = client.teams.team_roster(team_abbr=abbr, season=season_str)
            for group in ['forwards', 'defensemen', 'goalies']:
                for p in roster.get(group, []):
                    all_players.append({
                        "id": p['id'],
                        "name": f"{p['firstName']['default']} {p['lastName']['default']}",
                        "team": abbr,
                        "pos": p['positionCode']
                    })
    except Exception: pass
    return pd.DataFrame(all_players).sort_values("name")

# --- UI Setup ---
st.set_page_config(page_title="NHL Hit Rate Tracker", layout="wide")
CURRENT_SEASON = get_current_season_string()
players_df = get_all_active_players(CURRENT_SEASON)

st.title("🏒 NHL Hit Rate Tracker")

with st.sidebar:
    st.header("Settings")
    labels = players_df.apply(lambda x: f"{x['name']} ({x['team']})", axis=1).tolist()
    choice = st.selectbox("Select Player", options=labels)
    sel_player = players_df.iloc[labels.index(choice)]
    
    stat = st.selectbox("Stat", ["points", "goals", "assists", "shots", "hits", "pim", "powerPlayPoints"])
    threshold = st.number_input("Threshold", value=0.5, step=0.5)
    
    neg_odds = [str(x) for x in range(-300, -95, 5)]
    pos_odds = [f"+{x}" for x in range(100, 305, 5)]
    odds_options = neg_odds + pos_odds
    
    default_idx = odds_options.index("-110") if "-110" in odds_options else 0
    market_odds = st.selectbox("Market Odds (American)", options=odds_options, index=default_idx)
    
    games_back = st.select_slider("Last X Games", options=[5, 10, 15, 20, 30, 50], value=10)

    # --- Grouped Dashboard ---
    st.header("📋 My Dashboard")
    if not st.session_state.my_dashboard:
        st.info("No items saved yet.")
    else:
        # Convert to DF for easy grouping
        dash_df = pd.DataFrame(st.session_state.my_dashboard)
        
        # Group by Opponent to cluster games together
        for opponent, group in dash_df.groupby("opponent"):
            with st.expander(f"🆚 vs {opponent}", expanded=True):
                # Sort players within the game by hit rate
                group = group.sort_values(by="over", ascending=False)
                
                for idx, entry in group.iterrows():
                    over_c, under_c = get_color(entry['over']), get_color(entry['under'])
                    col_text, col_btn = st.columns([0.85, 0.15])
                    
                    with col_text:
                        loc_icon = "🏠" if entry.get('location') == "Home" else "✈️"
                        st.markdown(
                            f"**{entry['player']}** {loc_icon}<br>"
                            f"> {entry['stat']} {entry['threshold']} @ **{entry.get('odds', 'N/A')}**<br>"
                            f"O: :{over_c}[**{entry['over']:.0f}%**] | U: :{under_c}[**{entry['under']:.0f}%**]<br>"
                            f"<small>Avg TOI: {entry.get('avg_toi', 'N/A')} | PP: {entry.get('pp_influence', 0):.0f}%</small>", 
                            unsafe_allow_html=True
                        )
                    with col_btn:
                        # Use the original index (idx) for correct deletion
                        if st.button("×", key=f"del_{idx}"):
                            st.session_state.my_dashboard.pop(idx)
                            st.rerun()

# --- Main Analysis ---
if sel_player['id']:
    try:
        # Next Game Logic
        team_sched_data = client.schedule.team_weekly_schedule(team_abbr=sel_player['team'])
        games_list = team_sched_data if isinstance(team_sched_data, list) else team_sched_data.get('games', [])
        
        now = datetime.now(timezone.utc)
        next_game_info = {"opponent": "N/A", "location": "N/A", "venue": "N/A"}
        
        for g in games_list:
            start_str = g['startTimeUTC'].replace('Z', '+00:00')
            if datetime.fromisoformat(start_str) > now:
                is_home = g['homeTeam']['abbrev'] == sel_player['team']
                next_game_info = {
                    "opponent": g['awayTeam']['abbrev'] if is_home else g['homeTeam']['abbrev'],
                    "location": "Home" if is_home else "Road",
                    "venue": g.get('venue', {}).get('default', 'Unknown')
                }
                break

        if next_game_info["opponent"] != "N/A":
            loc_label = "🏠 Home" if next_game_info["location"] == "Home" else "✈️ Road"
            st.info(f"**Next Matchup:** {sel_player['team']} vs **{next_game_info['opponent']}** | {loc_label} | Venue: {next_game_info['venue']}")

        # Stat Processing
        log_data = client.stats.player_game_log(player_id=sel_player['id'], season_id=CURRENT_SEASON, game_type=2)
        games_log = log_data if isinstance(log_data, list) else log_data.get('gameLog', [])
        
        if games_log:
            df = pd.DataFrame(games_log).head(games_back).copy()
            df['gameDateFormatted'] = pd.to_datetime(df['gameDate']).dt.strftime('%b %d')
            df['toi_min'] = df['toi'].apply(toi_to_minutes)
            
            def get_pp_val(row, current_stat):
                if current_stat == 'goals': return row.get('powerPlayGoals', 0)
                if current_stat == 'points': return row.get('powerPlayPoints', 0)
                if current_stat == 'assists': return max(0, row.get('powerPlayPoints', 0) - row.get('powerPlayGoals', 0))
                if current_stat == 'powerPlayPoints': return row.get('powerPlayPoints', 0)
                return 0

            df['pp_val'] = df.apply(lambda r: get_pp_val(r, stat), axis=1)
            df['pp_pct'] = (df['pp_val'] / df[stat].replace(0, 1)) * 100
            df['efficiency'] = (df[stat] / df['toi_min'] * 20).round(2)
            
            avg_shifts = df['shifts'].mean() if 'shifts' in df.columns else 0
            avg_eff = df['efficiency'].mean()
            over_rate = ((df[stat] > threshold).sum() / len(df)) * 100
            under_rate = 100 - over_rate
            formatted_avg_toi = minutes_to_toi(df['toi_min'].mean())
            pp_influence = (df['pp_val'].sum() / df[stat].sum() * 100) if df[stat].sum() > 0 else 0

            # --- Header & Save Button ---
            header_col, btn_col = st.columns([4, 1])
            with header_col:
                st.markdown(f"### {stat.capitalize()} > {threshold} | O: :{get_color(over_rate)}[{over_rate:.0f}%] U: :{get_color(under_rate)}[{under_rate:.0f}%]")
            with btn_col:
                if st.button("➕ Save to Board"):
                    st.session_state.my_dashboard.append({
                        "player": choice, "stat": stat.capitalize(), "threshold": threshold,
                        "over": over_rate, "under": under_rate, 
                        "avg_toi": formatted_avg_toi, 
                        "avg_shifts": avg_shifts, 
                        "pp_influence": pp_influence,
                        "odds": market_odds, 
                        "location": next_game_info["location"],
                        "opponent": next_game_info["opponent"] # Added for grouping
                    })
                    st.rerun()

            # --- Visualizations ---
            st.markdown("---")
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            
            with c1:
                st.write("**Performance**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df[stat], marker_color=['#2ecc71' if v > threshold else '#e74c3c' for v in df[stat]], text=df[stat]))
                fig.add_hline(y=threshold, line_dash="dash", line_color="white")
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5))
                st.plotly_chart(fig, use_container_width=True)

            with c2:
                st.write(f"**TOI ({formatted_avg_toi})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['toi_min'], marker_color='#3498db', text=df['toi']))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5))
                st.plotly_chart(fig, use_container_width=True)

            with c3:
                st.write(f"**Shifts (Avg: {avg_shifts:.1f})**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['shifts'], marker_color='#1abc9c', text=df['shifts']))
                fig.add_hline(y=avg_shifts, line_dash="dot", line_color="#ecf0f1")
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5))
                st.plotly_chart(fig, use_container_width=True)

            with c4:
                st.markdown(f"**PP % ({pp_influence:.0f}%)**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['pp_pct'], marker_color='#f1c40f'))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, yaxis_range=[0, 105], margin=dict(t=5, b=5, l=5, r=5))
                st.plotly_chart(fig, use_container_width=True)

            with c5:
                st.markdown("**Eff / 20m**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['efficiency'], marker_color='#9b59b6', text=df['efficiency']))
                fig.add_hline(y=avg_eff, line_dash="dot")
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5))
                st.plotly_chart(fig, use_container_width=True)

            with c6:
                st.write("**PP Points**")
                fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df['powerPlayPoints'], marker_color='#e67e22', text=df['powerPlayPoints']))
                fig.update_layout(template="plotly_dark", xaxis={'type': 'category'}, margin=dict(t=5, b=5, l=5, r=5))
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader("📊 Detailed Game Log")
            cols_ex = ['gameId', 'commonName', 'opponentCommonName', 'gameDateFormatted', 'pp_val', 'pp_pct', 'toi_min', 'efficiency']
            st.dataframe(df.drop(columns=cols_ex, errors='ignore'), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error fetching data: {e}")
