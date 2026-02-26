import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

# --- Helper Functions ---
def get_color(rate):
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
    # Assuming season starts in September
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
    
    stat = st.selectbox("Stat", ["points", "goals", "assists", "shots", "hits", "pim"])
    threshold = st.number_input("Threshold", value=0.5, step=0.5)
    games_back = st.select_slider("Last X Games", options=[5, 10, 15, 20], value=10)

    st.header("📋 My Dashboard")
    if not st.session_state.my_dashboard:
        st.info("No items saved yet.")
    else:
        # Sort dashboard by highest hit rate (Over or Under)
        st.session_state.my_dashboard.sort(key=lambda x: max(x['over'], x['under']), reverse=True)
        for i, entry in enumerate(st.session_state.my_dashboard):
            over_c, under_c = get_color(entry['over']), get_color(entry['under'])
            
            col_text, col_btn = st.columns([0.90, 0.10])
            
            with col_text:
                # Display Hit Rate, TOI, and PP% in a compact sidebar format
                st.markdown(
                    f"**{entry['player']}** | > {entry['stat']} {entry['threshold']}<br>"
                    f"O: :{over_c}[**{entry['over']:.0f}%**] | U: :{under_c}[**{entry['under']:.0f}%**]<br>"
                    f"<small>Avg TOI: {entry.get('avg_toi', 'N/A')} | PP: {entry.get('pp_influence', 0):.1f}%</small>", 
                    unsafe_allow_html=True
                )
            
            with col_btn:
                if st.button("×", key=f"del_{i}", help="Remove"):
                    st.session_state.my_dashboard.pop(i)
                    st.rerun()

# --- Main Analysis ---
if sel_player['id']:
    try:
        log_data = client.stats.player_game_log(player_id=sel_player['id'], season_id=CURRENT_SEASON, game_type=2)
        games = log_data if isinstance(log_data, list) else log_data.get('gameLog', [])
        
        if games:
            # Get last X games (Most recent on top/left)
            df = pd.DataFrame(games).head(games_back)
            df['gameDate'] = pd.to_datetime(df['gameDate']).dt.strftime('%b %d')
            
            # 1. PP Stat Logic
            def get_pp_val(row, current_stat):
                if current_stat == 'goals': return row.get('powerPlayGoals', 0)
                if current_stat == 'points': return row.get('powerPlayPoints', 0)
                if current_stat == 'assists':
                    return max(0, row.get('powerPlayPoints', 0) - row.get('powerPlayGoals', 0))
                return row.get('powerPlayShots', 0) if current_stat == 'shots' else 0

            df['pp_val'] = df.apply(lambda r: get_pp_val(r, stat), axis=1)
            df['pp_pct'] = (df['pp_val'] / df[stat].replace(0, 1)) * 100
            df['toi_min'] = df['toi'].apply(toi_to_minutes)
            
            # 2. Efficiency Logic (Stat per 20 Minutes)
            df['efficiency'] = (df[stat] / df['toi_min'] * 20).round(2)
            avg_eff = df['efficiency'].mean()

            # 3. Hit Rate Summary
            over_hits = (df[stat] > threshold).sum()
            over_rate = (over_hits / len(df)) * 100
            under_rate = 100 - over_rate

            # 4. Metrics for Dashboard Saving
            avg_toi_min = df['toi_min'].mean()
            formatted_avg_toi = minutes_to_toi(avg_toi_min)
            
            total_stat = df[stat].sum()
            total_pp_stat = df['pp_val'].sum()
            overall_pp_influence = (total_pp_stat / total_stat * 100) if total_stat > 0 else 0

            header_col, btn_col = st.columns([4, 1])
            with header_col:
                st.markdown(
                    f"### Stat: **{stat.capitalize()}** | Threshold: **{threshold}** | "
                    f"Over: :{get_color(over_rate)}[**{over_rate:.1f}%**] | "
                    f"Under: :{get_color(under_rate)}[**{under_rate:.1f}%**]"
                )
            with btn_col:
                if st.button("➕ Save to Dashboard"):
                    st.session_state.my_dashboard.append({
                        "player": choice, 
                        "stat": stat.capitalize(), 
                        "threshold": threshold,
                        "over": over_rate, 
                        "under": under_rate,
                        "avg_toi": formatted_avg_toi,
                        "pp_influence": overall_pp_influence
                    })
                    st.rerun()
            
            # --- Visualizations Section ---
            st.markdown("---")
            col1, col2, col3, col4 = st.columns(4)

            # 1. Main Trend Graph
            with col1:
                fig_main = go.Figure(go.Bar(
                    x=df['gameDate'], y=df[stat],
                    marker_color=['#2ecc71' if val > threshold else '#e74c3c' for val in df[stat]],
                    text=df[stat], textposition='inside',
                    textfont=dict(color='white', size=12, family="Arial Black")
                ))
                fig_main.add_hline(y=threshold, line_dash="dash", line_color="#FFFFFF", line_width=2)
                fig_main.update_layout(
                    title=f"Performance", 
                    template="plotly_dark", 
                    xaxis={'type': 'category'},
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig_main, use_container_width=True)

            # 2. TOI Chart
            with col2:
                fig_toi = go.Figure(go.Bar(
                    x=df['gameDate'], y=df['toi_min'],
                    text=df['toi'], textposition='inside',
                    marker_color='#3498db'
                ))
                fig_toi.update_layout(
                    title=f"TOI (Avg: {formatted_avg_toi})",
                    template="plotly_dark", xaxis={'type': 'category'}, 
                    yaxis_title="Minutes",
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig_toi, use_container_width=True)

            # 3. PP Contribution Chart
            with col3:
                fig_pp = go.Figure(go.Bar(
                    x=df['gameDate'], y=df['pp_pct'],
                    text=df['pp_pct'].apply(lambda x: f"{x:.0f}%" if x > 0 else ""),
                    textposition='inside', marker_color='#f1c40f'
                ))
                fig_pp.update_layout(
                    title=f"PP % ({overall_pp_influence:.1f}%)",
                    template="plotly_dark", xaxis={'type': 'category'}, 
                    yaxis_title="% of Total", yaxis_range=[0, 105],
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig_pp, use_container_width=True)

            # 4. Efficiency Chart
            with col4:
                fig_eff = go.Figure(go.Bar(
                    x=df['gameDate'], y=df['efficiency'],
                    text=df['efficiency'], textposition='inside',
                    marker_color='#9b59b6'
                ))
                fig_eff.add_hline(y=avg_eff, line_dash="dot", line_color="#E0E0E0", 
                                  annotation_text=f"Avg", annotation_position="top left")
                fig_eff.update_layout(
                    title=f"Efficiency/20m",
                    template="plotly_dark", xaxis={'type': 'category'},
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig_eff, use_container_width=True)
            
        else:
            st.info("No game logs found for this player.")
    except Exception as e:
        st.error(f"Error fetching data: {e}")
