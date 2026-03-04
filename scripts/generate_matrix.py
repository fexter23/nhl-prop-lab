import pandas as pd
import os
from datetime import datetime
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

def get_current_season_string():
    """Returns the current season string (e.g., '20252026')."""
    now = datetime.now()
    start_year = now.year if now.month >= 9 else now.year - 1
    return f"{start_year}{start_year + 1}"

def get_all_active_players(season_str):
    """Fetches all active players from the NHL API."""
    all_players = []
    try:
        teams_data = client.teams.teams()
        for team in teams_data:
            abbr = team.get('abbr')
            # Using team_roster to get player IDs and names
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
    """Calculates Over hit rate for a player for a given stat/threshold."""
    try:
        # Fetching game log for the player
        log_data = client.stats.player_game_log(
            player_id=player_id, 
            season_id=get_current_season_string(), 
            game_type=2
        )
        games_log = log_data.get('gameLog', []) if isinstance(log_data, dict) else log_data
        
        if not games_log: 
            return ""
        
        df = pd.DataFrame(games_log).head(games_back)
        
        # Calculate percentage of games where stat > threshold
        if stat in df.columns:
            rate = ((df[stat] > thresh).sum() / len(df)) * 100
            # Return formatted string if rate >= 80%
            return f"O {rate:.0f}%" if rate >= 80 else ""
        return ""
    except Exception: 
        return ""

def generate_matrix():
    print("Generating Hit Rate Matrix...")
    season = get_current_season_string()
    players_df = get_all_active_players(season)
    games_back = 10  # Standard look-back window
    
    matrix_data = []
    
    # Iterate through all players to build the matrix
    for _, p in players_df.iterrows():
        row = {"Player": p['name'], "Team": p['team']}
        # Process Points and Shots across standard thresholds
        for stat in ["points", "shots"]:
            for t in [0.5, 1.5, 2.5, 3.5]:
                row[f"{stat}_{t}"] = get_hit_rate(p['id'], stat, t, games_back)
        matrix_data.append(row)
    
    final_df = pd.DataFrame(matrix_data)
    
    # Save to data directory
    os.makedirs("data", exist_ok=True)
    final_df.to_parquet("data/hit_rate_matrix.parquet")
    print("Matrix successfully saved to data/hit_rate_matrix.parquet")

if __name__ == "__main__":
    generate_matrix()
