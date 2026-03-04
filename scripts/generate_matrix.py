import pandas as pd
from datetime import datetime
from nhlpy import NHLClient
import os

# Initialize the NHL Client
client = NHLClient()

def get_current_season_string():
    now = datetime.now()
    start_year = now.year if now.month >= 9 else now.year - 1
    return f"{start_year}{start_year + 1}"

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
                        "team": abbr
                    })
    except Exception as e:
        print(f"Error fetching players: {e}")
    return pd.DataFrame(all_players)

def get_hit_rate(player_id, stat, thresh, games_back):
    """Calculates Over hit rate for a player."""
    try:
        log_data = client.stats.player_game_log(player_id=player_id, season_id=get_current_season_string(), game_type=2)
        games_log = log_data.get('gameLog', []) if isinstance(log_data, dict) else log_data
        if not games_log: return ""
        
        df = pd.DataFrame(games_log).head(games_back)
        rate = ((df[stat] > thresh).sum() / len(df)) * 100
        
        # Only return string if Over rate is >= 80%
        return f"O {rate:.0f}%" if rate >= 80 else ""
    except: 
        return ""

def generate_matrix():
    print("Generating matrix...")
    season = get_current_season_string()
    players_df = get_all_active_players(season)
    games_back = 10 # Standardizing this for the daily run
    
    matrix_data = []
    
    # Calculate for all players
    for _, p in players_df.iterrows():
        row = {"Player": p['name'], "Team": p['team']}
        # We process both Points and Shots
        for stat in ["points", "shots"]:
            for t in [0.5, 1.5, 2.5, 3.5]:
                row[f"{stat}_{t}"] = get_hit_rate(p['id'], stat, t, games_back)
        matrix_data.append(row)
    
    final_df = pd.DataFrame(matrix_data)
    
    # Ensure directory exists
    os.makedirs("data", exist_ok=True)
    
    # Save to parquet
    final_df.to_parquet("data/hit_rate_matrix.parquet")
    print("Matrix saved to data/hit_rate_matrix.parquet")

if __name__ == "__main__":
    generate_matrix()
