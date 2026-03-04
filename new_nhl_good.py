import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import uuid
import os
from datetime import datetime, timezone
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

# --- Cached Data Loading ---
@st.cache_data(ttl=3600)
def load_hit_rate_matrix():
    """Loads the pre-calculated matrix from the local data folder."""
    if os.path.exists("data/hit_rate_matrix.parquet"):
        return pd.read_parquet("data/hit_rate_matrix.parquet")
    return pd.DataFrame()

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

@st.cache_data(ttl=3600)
def get_todays_games():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        data = client.schedule.daily_schedule(date=today)
        game_list = data.get('games', []) if isinstance(data, dict) else data
        return [{"label": f"{g['awayTeam']['abbrev']} @ {g['homeTeam']['abbrev']}", 
                 "teams": [g['awayTeam']['abbrev'], g['homeTeam']['abbrev']]} for g in game_list]
    except: return []

# --- Helpers ---
def get_current_season_string():
    now = datetime.now()
    start_year = now.year if now.month >= 9 else now.year - 1
    return f"{start_year}{start_year + 1}"

def toi_to_minutes(toi_str):
    if not isinstance(toi_str, str) or ":" not in toi_str: return 0.0
    m, s = map(int, toi_str.split(':'))
    return m + s / 60.0

# --- UI Setup ---
st.set_page_config(page_title="NHL Hit Rate Tracker", layout="wide")
CURRENT_SEASON = get_current_season_string()
players_df = get_all_active_players(CURRENT_SEASON)

st.title("🏒 NHL Hit Rate Tracker")

with st.sidebar:
    st.header("Settings")
    if st.button("🔄 Refresh All Data"):
        st.cache_data.clear()
        st.rerun()

    todays_games = get_todays_games()
    game_options = [g['label'] for g in todays_games]
    selected_game_label = st.selectbox("Filter by Today's Games", options=game_options, index=None, placeholder="Select a Game...")
    
    filtered_df = players_df
    if selected_game_label:
        game_info = next(g for g in todays_games if g['label'] == selected_game_label)
        filtered_df = players_df[players_df['team'].isin(game_info['teams'])]
    
    labels = filtered_df.apply(lambda x: f"{x['name']} ({x['team']})", axis=1).tolist()
    sel_player = filtered_df.iloc[labels.index(st.selectbox("Select Player", options=labels))] if labels else None
    
    stat = st.selectbox("Stat", ["points", "goals", "assists", "shots", "hits", "pim", "powerPlayPoints"])
    threshold = st.number_input("Threshold", value=0.5, step=0.5)
    games_back = st.select_slider("Last X Games", options=[5, 10, 15, 20, 30, 50], value=10)

# --- Team Hit Rate Matrix ---
if selected_game_label:
    st.divider()
    st.subheader(f"📊 Team Hit Rate Matrix (>= 80% Over) - {selected_game_label}")
    matrix_df = load_hit_rate_matrix()
    
    if not matrix_df.empty:
        # Filter matrix by teams in selected game
        game_info = next(g for g in todays_games if g['label'] == selected_game_label)
        team_matrix = matrix_df[matrix_df['Team'].isin(game_info['teams'])]
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Points**")
            # Select columns corresponding to points
            pts_cols = ['Player'] + [c for c in team_matrix.columns if 'points_' in c]
            st.dataframe(team_matrix[pts_cols].set_index('Player').dropna(how='all'), use_container_width=True)
        with c2:
            st.markdown("**Shots**")
            sht_cols = ['Player'] + [c for c in team_matrix.columns if 'shots_' in c]
            st.dataframe(team_matrix[sht_cols].set_index('Player').dropna(how='all'), use_container_width=True)
    else:
        st.warning("Matrix data not found. Please ensure the generation script has run.")

# --- Analysis ---
if sel_player:
    log_data = client.stats.player_game_log(player_id=sel_player['id'], season_id=CURRENT_SEASON, game_type=2)
    games_log = log_data.get('gameLog', [])
    if games_log:
        df = pd.DataFrame(games_log).head(games_back)
        df['gameDateFormatted'] = pd.to_datetime(df['gameDate']).dt.strftime('%b %d')
        
        fig = go.Figure(go.Bar(x=df['gameDateFormatted'], y=df[stat], marker_color=['#2ecc71' if v > threshold else '#e74c3c' for v in df[stat]]))
        st.plotly_chart(fig, use_container_width=True)
