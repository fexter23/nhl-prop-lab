import json
from datetime import datetime, timezone
from nhlpy import NHLClient
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import uuid

# ====================== FAVICON & PAGE CONFIG ======================
st.set_page_config(
    page_title="NHL Hit Tracker",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

client = NHLClient()

# ─── Helper Functions ────────────────────────────────────────────────────────
def load_json(filename, default=[]):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def get_color(rate):
    if rate >= 70: return "green"
    if rate >= 50: return "orange"
    return "red"

def toi_to_minutes(toi_str):
    if not isinstance(toi_str, str) or ":" not in toi_str:
        return 0.0
    m, s = map(int, toi_str.split(':'))
    return m + s / 60.0

def minutes_to_toi(total_min):
    m = int(total_min)
    s = int(round((total_min - m) * 60))
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}"

def get_parlay_return(odds_list, bet=1.0):
    multiplier = 1.0
    for o in odds_list:
        try:
            val = int(str(o).replace('+', ''))
            if val > 0:
                multiplier *= (val / 100 + 1)
            else:
                multiplier *= (100 / abs(val) + 1)
        except:
            continue
    return multiplier * bet

def get_current_season():
    now = datetime.now()
    return f"{now.year if now.month >= 9 else now.year - 1}{now.year if now.month < 9 else now.year + 1}"

# === UPDATED: Blended logs with manual gameType injection ===
def get_blended_game_logs(client, player_id, season):
    try:
        # Fetch Regular Season (Type 2)
        log_reg_raw = client.stats.player_game_log(player_id=player_id, season_id=season, game_type=2)
        # Fetch Playoffs (Type 3)
        log_ply_raw = client.stats.player_game_log(player_id=player_id, season_id=season, game_type=3)
        
        logs_reg = log_reg_raw if isinstance(log_reg_raw, list) else log_reg_raw.get('gameLog', []) if isinstance(log_reg_raw, dict) else []
        logs_ply = log_ply_raw if isinstance(log_ply_raw, list) else log_ply_raw.get('gameLog', []) if isinstance(log_ply_raw, dict) else []
        
        # Inject gameType because the API response doesn't include it in the game objects
        for g in logs_reg:
            g['gameType'] = 2
        for g in logs_ply:
            g['gameType'] = 3
        
        all_logs = logs_reg + logs_ply
        # Sort by date descending
        all_logs.sort(key=lambda g: g.get('gameDate', ''), reverse=True)
        return all_logs
    except Exception as e:
        st.error(f"Error fetching blended logs for {player_id}: {e}")
        return []

# Session state init
if 'my_dashboard' not in st.session_state:
    st.session_state.my_dashboard = []

# Custom styling
st.markdown("""
    <style>
        [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.9rem !important; margin-bottom: -10px !important; }
        .stMetric { padding: 5px !important; background-color: #1e1e1e; border-radius: 5px; }
        .stCheckbox { margin-bottom: -15px; }
    </style>
""", unsafe_allow_html=True)

# ─── Load All Daily Data ─────────────────────────────────────────────────────
pt_trends = load_json('daily_points.json')
context   = load_json('today_context.json', default={"matchups": [], "players": []})

# Only need season for blending
season = context.get('season') or get_current_season()

# ─── Top Section: High Hit-Rate Clubs ────────────────────────────────────────
with st.expander("🔥 High Hit-Rate Clubs / Trends (click to show)", expanded=False):
    trend_definitions = [
        ("Over 0.5 Points", pt_trends, "🔥", "Over 0.5 Points"),
    ]

    if any(len(data) > 0 for _, data, _, _ in trend_definitions):
        cols = st.columns(len(trend_definitions))
        for col, (title_short, data, emoji, title_long) in zip(cols, trend_definitions):
            with col:
                st.markdown(f"**{emoji} {title_short}**")
                if data and len(data) > 0:
                    lines = [
                        f"<span style='font-size:0.8rem;'>{t['player']} ({t['team']}) <b>{t['hit_rate']}%</b> vs {t['opponent']}</span>"
                        for t in data[:50]
                    ]
                    st.markdown("  \n".join(lines), unsafe_allow_html=True)
                else:
                    st.caption("No players meeting criteria")
    else:
        st.caption("No trending players found today")

# ─── Lineups Section ────────────────────────────────────────────────────────
with st.expander("📋 View Daily Projected Lineups (Rotowire)", expanded=False):
    st.caption("Live updates from Rotowire. Scroll within the frame to see all matchups.")
    lineups_url = "https://www.rotowire.com/hockey/nhl-lineups.php"
    st.components.v1.iframe(lineups_url, height=600, scrolling=True)

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    game_col, player_col = st.columns(2)
    
    with game_col:
        game_opts = ["All Today's Teams"] + [m['label'] for m in context['matchups']]
        selected_game = st.selectbox("Filter Today's Games", game_opts)

    players_df = pd.DataFrame(context['players'])

    if players_df.empty:
        st.error("No player data found. Run full_setup.py first.")
        st.stop()

    if selected_game != "All Today's Teams":
        teams = next((m['teams'] for m in context['matchups'] if m['label'] == selected_game), [])
        players_df = players_df[players_df['team'].isin(teams)]

    player_labels = players_df.apply(
        lambda x: f"{x['name']} ({x['team']} – {x['pos']})", axis=1
    ).tolist()

    with player_col:
        choice = st.selectbox("Select Player", options=player_labels if player_labels else ["No players available"])
    
    sel_player = None
    if player_labels:
        sel_idx = player_labels.index(choice)
        sel_player = players_df.iloc[sel_idx].to_dict()

    c1, c2, c3 = st.columns([1.5, 1, 1])
    with c1:
        stat = st.selectbox("Stat", ["points", "shots", "assists", "goals", "hits", "pim", "PPPoints"], label_visibility="collapsed")
    with c2:
        threshold = st.number_input("Threshold", min_value=0.0, value=0.5, step=0.5, label_visibility="collapsed")
    with c3:
        market_odds = st.selectbox(
            "Market Odds",
            options=[f"+{x}" for x in range(100, 305, 5)] + [str(x) for x in range(-300, -95, 5)],
            index=20,
            label_visibility="collapsed"
        )

    # Forced to 10 games per user requirements
    games_back = 10

    # ── Player data caching ──────────────────────────────────────────────────
    cache_key = f"player_cache_{sel_player.get('id', 'none')}_{stat}_{threshold}"
    cached_data = st.session_state.get(cache_key, None)

    if sel_player and sel_player.get('id') and cached_data is None:
        try:
            team_sched = client.schedule.team_weekly_schedule(team_abbr=sel_player['team'])
            games_list = team_sched if isinstance(team_sched, list) else team_sched.get('games', [])

            next_game = {"opponent": "N/A", "location": "N/A"}
            now_utc = datetime.now(timezone.utc)
            for g in games_list:
                game_time = datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00'))
                if game_time > now_utc:
                    is_home = g['homeTeam']['abbrev'] == sel_player['team']
                    next_game = {
                        "opponent": g['awayTeam']['abbrev'] if is_home else g['homeTeam']['abbrev'],
                        "location": "Home" if is_home else "Road"
                    }
                    break

            logs = get_blended_game_logs(client, sel_player['id'], season)
            df_recent = pd.DataFrame(logs).copy() if logs else pd.DataFrame()

            streak_label = "N/A"
            if not df_recent.empty:
                df_recent['toi_min'] = df_recent['toi'].apply(toi_to_minutes)
                is_over = df_recent[stat].iloc[0] > threshold
                streak_count = 0
                for val in df_recent[stat]:
                    if (val > threshold) == is_over:
                        streak_count += 1
                    else:
                        break
                streak_label = f"{'O' if is_over else 'U'}{streak_count}"

            cached_data = {
                'next_game': next_game,
                'streak_label': streak_label,
                'df_recent': df_recent,
            }
            st.session_state[cache_key] = cached_data

        except Exception as e:
            st.warning(f"Could not cache player data: {e}")
            cached_data = {
                'next_game': {"opponent": "N/A", "location": "N/A"},
                'streak_label': "N/A",
                'df_recent': pd.DataFrame(),
            }
            st.session_state[cache_key] = cached_data
    else:
        cached_data = cached_data or {
            'next_game': {"opponent": "N/A", "location": "N/A"},
            'streak_label': "N/A",
            'df_recent': pd.DataFrame(),
        }

    next_game = cached_data['next_game']
    streak_label_temp = cached_data['streak_label']
    df_recent = cached_data['df_recent']

    # ── Save Prop Button ─────────────────────────────────────────────────────
    if st.button("➕ Save Prop", use_container_width=True):
        if sel_player and sel_player.get('id'):
            try:
                df_for_prop = df_recent.head(games_back).copy() if not df_recent.empty else pd.DataFrame()

                if not df_for_prop.empty:
                    df_5  = df_for_prop.head(5)
                    df_10 = df_for_prop.head(10)
                    hit_5  = (df_5[stat] > threshold).mean() * 100 if not df_5.empty else 0.0
                    hit_10 = (df_10[stat] > threshold).mean() * 100 if not df_10.empty else 0.0
                    over_rate = (hit_5 + hit_10) / 2
                    under_rate = 100 - over_rate
                else:
                    over_rate = under_rate = 0.0

                new_prop = {
                    "unique_id": str(uuid.uuid4()),
                    "player": f"{sel_player['name']} ({sel_player.get('pos', '?')})",
                    "team": sel_player['team'],
                    "opponent": next_game['opponent'],
                    "stat": stat.capitalize(),
                    "threshold": threshold,
                    "over": round(over_rate, 1),
                    "under": round(under_rate, 1),
                    "avg_shifts": round(df_for_prop['shifts'].mean(), 1) if not df_for_prop.empty else 0,
                    "avg_toi": minutes_to_toi(df_for_prop['toi_min'].mean()) if not df_for_prop.empty else "0:00",
                    "odds": market_odds,
                    "streak": streak_label_temp,
                    "location": next_game["location"]
                }

                exists = any(
                    d['player'] == new_prop['player'] and
                    d['stat'] == new_prop['stat'] and
                    d['threshold'] == new_prop['threshold']
                    for d in st.session_state.my_dashboard
                )
                if not exists:
                    st.session_state.my_dashboard.append(new_prop)
                    st.success("Prop added!")
                    st.rerun()
                else:
                    st.info("This prop is already in your dashboard.")
            except Exception as e:
                st.error(f"Could not save prop: {e}")
        else:
            st.warning("Select a player first.")

    # Download Dashboard
    if st.session_state.my_dashboard:
        now = datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"nhl_props_{now}.json"
        st.download_button(
            label="📥 Download Dashboard (JSON)",
            data=json.dumps(st.session_state.my_dashboard, indent=4),
            file_name=filename,
            mime="application/json",
            use_container_width=True
        )
    else:
        st.caption("No props saved yet — add some using 'Save Prop'")

    # My Dashboard
    st.header("📋 My Dashboard")
    if st.session_state.my_dashboard:
        dash_df = pd.DataFrame(st.session_state.my_dashboard)
        dash_df['match_key'] = dash_df.apply(lambda r: " vs ".join(sorted([r['team'], r['opponent']])), axis=1)
        unique_matches = dash_df['match_key'].unique()[::-1]

        for match in unique_matches:
            group = dash_df[dash_df['match_key'] == match]
            prop_count = len(group)
            total_ret = get_parlay_return(group['odds'].tolist())
            header_text = f"🆚 {match} | {prop_count} prop{'s' if prop_count != 1 else ''} | :green[Return ${total_ret:.2f}]"

            h_col1, h_col2, h_col3 = st.columns([0.1, 0.8, 0.1])
            with h_col1:
                st.checkbox("", key=f"check_{match}", label_visibility="collapsed")
            with h_col2:
                with st.expander(header_text, expanded=True):
                    for _, entry in group.iterrows():
                        over_c, under_c = get_color(entry['over']), get_color(entry['under'])
                        c_t, c_d = st.columns([0.8, 0.2])
                        with c_t:
                            st.markdown(
                                f"**{entry['player']}** {'🏠' if entry.get('location') == 'Home' else '✈️'}  \n"
                                f"**{entry['stat']} {entry['threshold']} @ {entry['odds']}** \n"
                                f"**O**: :{over_c}[**{entry['over']:.0f}%**]  **|** "
                                f"**U**: :{under_c}[**{entry['under']:.0f}%**]  **|** "
                                f"**Streak**: {entry['streak']}  **|** "
                                f"**Shifts**: {entry['avg_shifts']}  **|** "
                                f"**TOI**: {entry['avg_toi']}",
                                unsafe_allow_html=True
                            )
                        with c_d:
                            if st.button("🗑️", key=f"del_{entry['unique_id']}"):
                                st.session_state.my_dashboard = [d for d in st.session_state.my_dashboard if d['unique_id'] != entry['unique_id']]
                                st.rerun()
            with h_col3:
                if st.button("x", key=f"del_group_{match}"):
                    st.session_state.my_dashboard = [
                        d for d in st.session_state.my_dashboard 
                        if " vs ".join(sorted([d['team'], d['opponent']])) != match
                    ]
                    st.rerun()

    uploaded_file = st.file_uploader("Upload Saved Dashboard", type=["json"])
    if uploaded_file:
        try:
            new_data = json.load(uploaded_file)
            if st.button("Confirm Load", type="primary", use_container_width=True):
                st.session_state.my_dashboard = new_data
                st.rerun()
        except:
            st.error("Invalid JSON file.")

# ─── Player Analysis ─────────────────────────────────────────────────────────
if sel_player and sel_player.get('id'):
    try:
        next_game_display = cached_data['next_game']
        streak_label = cached_data['streak_label']
        df = df_recent.head(games_back).copy()

        if not df.empty:
            df['gameDateFormatted'] = pd.to_datetime(df['gameDate']).dt.strftime('%b %d')
            df['toi_min'] = df['toi'].apply(toi_to_minutes)

            # Identification of regular season vs playoff games using injected gameType
            if 'gameType' in df.columns:
                df['Game Type'] = df['gameType'].map({
                    2: 'Regular Season',
                    3: 'Playoffs'
                }).fillna('Unknown')
            else:
                df['Game Type'] = 'Unknown'

            df_5  = df.head(5)
            df_10 = df.head(10)
            hit_5  = (df_5[stat] > threshold).mean() * 100 if not df_5.empty else 0.0
            hit_10 = (df_10[stat] > threshold).mean() * 100 if not df_10.empty else 0.0
            over_rate  = (hit_5 + hit_10) / 2
            under_rate = 100 - over_rate

            avg_toi    = minutes_to_toi(df['toi_min'].mean())
            avg_shifts = round(df['shifts'].mean(), 1)

            st.markdown(
                f"### {sel_player['name']} ({sel_player.get('pos', '?')})  \n"
                f"**Over**: :{get_color(over_rate)}[**{over_rate:.0f}%**]  "
                f"**Under**: :{get_color(under_rate)}[**{under_rate:.0f}%**]"
            )

            r1c1, r1c2, r1c3 = st.columns(3)
            with r1c1:
                st.caption(f"**Stat ({streak_label})**")
                fig = go.Figure(go.Bar(
                    x=df['gameDateFormatted'], y=df[stat],
                    text=df[stat], textposition='auto',
                    marker_color=['#2ecc71' if v > threshold else '#e74c3c' for v in df[stat]]
                ))
                fig.add_hline(y=threshold, line_dash="dash", line_color="white")
                fig.update_layout(template="plotly_dark", margin=dict(t=5,b=5,l=5,r=5), height=160)
                st.plotly_chart(fig, use_container_width=True)

            with r1c2:
                st.caption(f"**TOI ({avg_toi})**")
                fig = go.Figure(go.Bar(
                    x=df['gameDateFormatted'], y=df['toi_min'],
                    text=df['toi'], textposition='auto',
                    marker_color='#3498db'
                ))
                fig.update_layout(template="plotly_dark", margin=dict(t=5,b=5,l=5,r=5), height=160)
                st.plotly_chart(fig, use_container_width=True)

            with r1c3:
                st.caption(f"**Shifts ({avg_shifts})**")
                fig = go.Figure(go.Bar(
                    x=df['gameDateFormatted'], y=df['shifts'],
                    text=df['shifts'], textposition='auto',
                    marker_color='#1abc9c'
                ))
                fig.update_layout(template="plotly_dark", margin=dict(t=5,b=5,l=5,r=5), height=160)
                st.plotly_chart(fig, use_container_width=True)

            st.divider()
            # Added Game Type to the visible dataframe
            st.dataframe(
                df.drop(columns=['gameId', 'toi_min', 'commonName', 'opponentCommonName', 'gameDate', 'gameType','shorthandedGoals', 'shorthandedPoints', 'gameWinningGoals','homeRoadFlag'], errors='ignore'),
                use_container_width=True, hide_index=True
            )
        else:
            st.warning("No recent game logs found.")
    except Exception as e:
        st.error(f"Error loading player data: {e}")

else:
    st.info("Select a player to view stats.")
