import pandas as pd
from datetime import datetime, timezone
from nhlpy import NHLClient
import json

client = NHLClient()

def get_current_season():
    now = datetime.now()
    return f"{now.year if now.month >= 9 else now.year - 1}{now.year if now.month < 9 else now.year + 1}"

def calculate_daily_trends():
    season = get_current_season()
    # 1. Get Today's Games
    schedule = client.schedule.daily_schedule(date=datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    games = schedule.get('games', [])
    
    playing_teams = []
    for g in games:
        playing_teams.append({'team': g['awayTeam']['abbrev'], 'opp': g['homeTeam']['abbrev']})
        playing_teams.append({'team': g['homeTeam']['abbrev'], 'opp': g['awayTeam']['abbrev']})
    
    playing_abbrs = [t['team'] for t in playing_teams]
    high_hit_rates = []

    # 2. Process players from those teams
    for entry in playing_teams:
        try:
            roster = client.teams.team_roster(team_abbr=entry['team'], season=season)
            # Combine forwards and defensemen
            players = roster.get('forwards', []) + roster.get('defensemen', [])
            
            for p in players:
                p_id = p['id']
                name = f"{p['firstName']['default']} {p['lastName']['default']}"
                
                # Fetch last 10 games
                log_data = client.stats.player_game_log(player_id=p_id, season_id=season, game_type=2)
                games_log = log_data.get('gameLog', [])[:10]
                
                if len(games_log) < 5: continue # Skip if not enough data
                
                hits = sum(1 for g in games_log if g.get('points', 0) > 0.5)
                rate = (hits / len(games_log)) * 100
                
                if rate >= 80:
                    high_hit_rates.append({
                        "player": name,
                        "team": entry['team'],
                        "opponent": entry['opp'],
                        "hit_rate": rate,
                        "last_10": hits
                    })
        except:
            continue

    # 3. Save to JSON
    with open('daily_trends.json', 'w') as f:
        json.dump(high_hit_rates, f, indent=4)

if __name__ == "__main__":
    calculate_daily_trends()
