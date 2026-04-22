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
    try:
        m, s = map(int, toi_str.split(':'))
        return m + s / 60.0
    except:
        return 0.0

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

def get_blended_game_logs(client, player_id, season):
    """Fetches regular and playoff logs and injects gameType manually."""
    try:
        log_reg_raw = client.stats.player_game_log(player_id=player_id, season_id=season, game_type=2)
        log_ply_raw = client.stats.player_game_log(player_id=player_id, season_id=season, game_type=3)
        
        logs_reg = log_reg_raw if isinstance(log_reg_raw, list) else log_reg_raw.get('gameLog', []) if isinstance(log_reg_raw, dict) else []
        logs_ply = log_ply_raw if isinstance(log_ply_raw, list) else log_ply_raw.get('gameLog', []) if isinstance(log_ply_raw, dict) else []
        
        # Manual injection to fix 'Unknown' game types
        for g in logs_reg:
            g['gameType'] = 2
        for g in logs_ply:
            g['gameType'] = 3
        
        all_logs = logs_reg + logs_ply
        all_logs.sort(key=lambda g: g.get('gameDate', ''), reverse=True)
        return all_logs
    except Exception as e:
        st.error(f"Error fetching logs: {e}")
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
    </style>
""", unsafe_allow_html=True)

# ─── Data Loading ────────────────────────────────────────────────────────────
pt_trends = load_json('daily_points.json')
context   = load_json('today_context.json', default={"matchups": [], "players": []})
season    = context.get('season') or get_current_season()

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    
    game_opts = ["All Today's Teams"] + [m['label'] for m in context['matchups']]
    selected_game = st.selectbox("Filter Today's Games", game_opts)

    players_df = pd.DataFrame(context['players'])
    if not players_df.empty and selected_game != "All Today's Teams":
        teams = next((m['teams'] for m in context['matchups'] if m['label'] == selected_game), [])
        players_df = players_df[players_df['team'].isin(teams)]

    player_labels = players_df.apply(lambda x: f"{x['name']} ({x['team']} – {x['pos']})", axis=1).tolist() if not players_df.empty else []
    choice = st.selectbox("Select Player", options=player_labels if player_labels else ["No players available"])
    
    sel_player = None
    if player_labels and "No players" not in choice:
        sel_idx = player_labels.index(choice)
        sel_player = players_df.iloc[sel_idx].to_dict()

    c1, c2, c3 = st.columns([1.5, 1, 1])
    with c1:
        stat = st.selectbox("Stat", ["points", "shots", "assists", "goals", "hits", "pim", "PPPoints"], label_visibility="collapsed")
    with c2:
        threshold = st.number_input("Goal", min_value=0.0, value=0.5, step=0.5, label_visibility="collapsed")
    with c3:
        market_odds = st.selectbox("Odds", [f"+{x}" for x in range(100, 305, 5)] + [str(x) for x in range(-300, -95, 5)], index=20, label_visibility="collapsed")

    # Hardcoded to 10 games per user requirements
    games_back = 10

    if sel_player:
        if st.button("➕ Save Prop", use_container_width=True):
            # (Logic for saving to dashboard would go here - simplified for brevity)
            pass

# ─── Player Analysis ─────────────────────────────────────────────────────────
if sel_player:
    try:
        logs = get_blended_game_logs(client, sel_player['id'], season)
        df = pd.DataFrame(logs).head(games_back).copy()

        if not df.empty:
            df['gameDateFormatted'] = pd.to_datetime(df['gameDate']).dt.strftime('%b %d')
            df['toi_min'] = df['toi'].apply(toi_to_minutes)

            # Hit Rate Logic
            df_5 = df.head(5)
            hit_5 = (df_5[stat] > threshold).mean() * 100 if not df_5.empty else 0.0
            hit_10 = (df[stat] > threshold).mean() * 100
            over_rate = (hit_5 + hit_10) / 2
            under_rate = 100 - over_rate

            st.markdown(f"### {sel_player['name']} Analysis (Last 10 Games)")
            col1, col2 = st.columns(2)
            col1.metric("Over Rate", f"{over_rate:.0f}%")
            col2.metric("Under Rate", f"{under_rate:.0f}%")

            # Charts
            fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df[stat], marker_color=['#2ecc71' if v > threshold else '#e74c3c' for v in df[stat]]))
            fig.add_hline(y=threshold, line_dash="dash", line_color="white")
            fig.update_layout(template="plotly_dark", height=200, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

            st.divider()
            
            # ─── CUSTOM TABLE ORDERING ───
            rename_map = {
                'gameDateFormatted': 'Date',
                'opponentAbbrev': 'VS',
                'plusMinus': '+/-',
                'powerPlayGoals': 'PPG',
                'powerPlayPoints': 'PPP'
            }

            column_order = [
                'Date', 'VS', 'points', 'shots', 'shifts', 'toi', 
                'goals', 'assists', '+/-', 'PPG', 'PPP', 
                'otGoals', 'pim'
            ]

            df_display = df.rename(columns=rename_map)
            df_final = df_display[[col for col in column_order if col in df_display.columns]]

            st.dataframe(df_final, use_container_width=True, hide_index=True)
        else:
            st.warning("No logs found.")
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Select a player from the sidebar.")
