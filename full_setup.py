import json
from datetime import datetime, timezone
from nhlpy import NHLClient

# Initialize the NHL Client
client = NHLClient()

def get_current_season():
    now = datetime.now()
    # NHL season format: 20252026 for 2025-26 season
    return f"{now.year if now.month >= 9 else now.year - 1}{now.year if now.month < 9 else now.year + 1}"

def generate_all_daily_data():
    print("Fetching today's schedule...")
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    schedule = client.schedule.daily_schedule(date=today_str)
    games = schedule.get('games', [])
    
    if not games:
        print("No games scheduled for today.")
        # Clear files if no games to avoid showing old data
        for f_name in ['daily_points.json', 'daily_shots.json', 'daily_shots_under.json', 'today_context.json']:
            with open(f_name, 'w') as f:
                if 'context' in f_name:
                    json.dump({"matchups": [], "players": [], "is_playoff_day": False, "game_type": 2, "season": get_current_season()}, f, indent=4)
                else:
                    json.dump([], f, indent=4)
        return

    season = get_current_season()
    
    # === NEW: Detect playoff day from the schedule ===
    game_types = {g.get('gameType') for g in games if g.get('gameType') is not None}
    is_playoff_day = 3 in game_types
    game_type_for_logs = 3 if is_playoff_day else 2
    print(f"Detected {'PLAYOFF' if is_playoff_day else 'regular season'} games today → using game_type={game_type_for_logs} for player logs.")

    points_trends = []
    points_under_trends = []
    points_over_trends = []
    shots_trends = []
    shots_under_trends = []
    matchups = []
    all_today_players = []
    
    # Map matchups and active teams
    matchup_map = {}
    active_teams = []
    for g in games:
        away = g['awayTeam']['abbrev']
        home = g['homeTeam']['abbrev']
        matchup_map[away] = home
        matchup_map[home] = away
        active_teams.extend([away, home])
        matchups.append({"label": f"{away} @ {home}", "teams": [away, home]})

    print(f"Teams playing today: {', '.join(active_teams)}")

    for team_abbr in active_teams:
        print(f"Processing {team_abbr}...")
        try:
            roster = client.teams.team_roster(team_abbr=team_abbr, season=season)
            players = roster.get('forwards', []) + roster.get('defensemen', [])
            
            for p in players:
                p_id = p['id']
                p_name = f"{p['firstName']['default']} {p['lastName']['default']}"
                p_pos = p.get('positionCode', 'N/A')
                
                all_today_players.append({
                    "id": p_id, 
                    "name": p_name, 
                    "team": team_abbr, 
                    "pos": p_pos
                })
                
                # === CHANGED: Use detected game_type for logs ===
                log_data = client.stats.player_game_log(
                    player_id=p_id, 
                    season_id=season, 
                    game_type=game_type_for_logs
                )
                logs = log_data if isinstance(log_data, list) else log_data.get('gameLog', [])
                
                if len(logs) >= 10:
                    recent_10 = logs[:10]
                    
                    # Points > 0.5
                    p_hits = sum(1 for g in recent_10 if g.get('points', 0) > 0.5)
                    if p_hits >= 8:
                        points_trends.append({
                            "player": p_name, 
                            "team": team_abbr, 
                            "opponent": matchup_map[team_abbr],
                            "hit_rate": p_hits * 10, 
                            "last_10": p_hits
                        })
                    
                    # Points < 1.5 (under)
                    p_hits_under = sum(1 for g in recent_10 if g.get('points', 0) < 1.5)
                    if p_hits_under >= 8:
                        points_under_trends.append({
                            "player": p_name, 
                            "team": team_abbr, 
                            "opponent": matchup_map[team_abbr],
                            "hit_rate": p_hits_under * 10, 
                            "last_10": p_hits_under
                        })
                    
                    # Points > 1.5 (over)
                    p_hits_over = sum(1 for g in recent_10 if g.get('points', 0) > 1.5)
                    if p_hits_over >= 8:
                        points_over_trends.append({
                            "player": p_name, 
                            "team": team_abbr, 
                            "opponent": matchup_map[team_abbr],
                            "hit_rate": p_hits_over * 10, 
                            "last_10": p_hits_over
                        })

                    # Shots > 1.5
                    s_hits_over = sum(1 for g in recent_10 if g.get('shots', 0) > 1.5)
                    if s_hits_over >= 8:
                        shots_trends.append({
                            "player": p_name, 
                            "team": team_abbr, 
                            "opponent": matchup_map[team_abbr],
                            "hit_rate": s_hits_over * 10, 
                            "last_10": s_hits_over
                        })

                    # Shots ≤ 1.5 (under)
                    s_hits_under = sum(1 for g in recent_10 if g.get('shots', 0) <= 1.5)
                    if s_hits_under >= 8:
                        shots_under_trends.append({
                            "player": p_name, 
                            "team": team_abbr, 
                            "opponent": matchup_map[team_abbr],
                            "hit_rate": s_hits_under * 10, 
                            "last_10": s_hits_under
                        })

        except Exception as e:
            print(f"Error processing {team_abbr}: {e}")

    # Save Trends
    with open('daily_points.json', 'w') as f:
        json.dump(sorted(points_trends, key=lambda x: x['hit_rate'], reverse=True), f, indent=4)
    with open('daily_points_under.json', 'w') as f:
        json.dump(sorted(points_under_trends, key=lambda x: x['hit_rate'], reverse=True), f, indent=4)
    with open('daily_points_over.json', 'w') as f:
        json.dump(sorted(points_over_trends, key=lambda x: x['hit_rate'], reverse=True), f, indent=4)
    with open('daily_shots.json', 'w') as f:
        json.dump(sorted(shots_trends, key=lambda x: x['hit_rate'], reverse=True), f, indent=4)
    with open('daily_shots_under.json', 'w') as f:
        json.dump(sorted(shots_under_trends, key=lambda x: x['hit_rate'], reverse=True), f, indent=4)
    
    # Save Context (now includes playoff detection)
    context_data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matchups": matchups,
        "players": all_today_players,
        "is_playoff_day": is_playoff_day,
        "game_type": game_type_for_logs,
        "season": season
    }
    with open('today_context.json', 'w') as f:
        json.dump(context_data, f, indent=4)
    
    print(f"All daily data files updated successfully (playoff mode: {is_playoff_day}).")

if __name__ == "__main__":
    generate_all_daily_data()
