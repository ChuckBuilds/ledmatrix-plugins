#!/usr/bin/env python3
"""
Test script to verify recent games filtering is working correctly
"""

import sys
sys.path.append('/home/chuck/Github/LEDMatrix/src')

from data_fetcher import HockeyDataFetcher
from cache_manager import CacheManager
from game_filter import HockeyGameFilter
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize components
cache_manager = CacheManager()
data_fetcher = HockeyDataFetcher(cache_manager, logger)
game_filter = HockeyGameFilter(logger)

# Fetch NHL data
print("Fetching NHL data...")
nhl_config = {
    'enabled': True,
    'update_interval_seconds': 60,
    'request_timeout': 30,
    'recent_games_to_show': 50,
    'favorite_teams': ['TB'],
    'favorite_teams_only': True,
    'display_modes': {
        'live': True,
        'recent': True,
        'upcoming': True
    }
}

games = data_fetcher.fetch_league_data('nhl', nhl_config)
print(f"Total NHL games: {len(games)}")

# Add league config to games
for game in games:
    game['league_config'] = nhl_config
    game['league'] = 'nhl'  # Set the league field

# Debug: Check the league config
print(f"League config: {nhl_config}")
print(f"Display modes: {nhl_config.get('display_modes', {})}")
print(f"Mode enabled check: {nhl_config.get('display_modes', {}).get('recent', False)}")

# Debug: Check what games have post status
post_games = [g for g in games if g.get('status', {}).get('state') == 'post']
print(f"Games with post status: {len(post_games)}")

# Debug: Check TB games with post status
tb_post_games = [g for g in games if g.get('status', {}).get('state') == 'post' and 'TB' in [g.get('home_team', {}).get('abbrev', ''), g.get('away_team', {}).get('abbrev', '')]]
print(f"TB games with post status: {len(tb_post_games)}")

# Show first few TB post games
for i, game in enumerate(tb_post_games[:5]):
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {i+1}. {away_team} @ {home_team} ({start_time[:10]}) - {status}")

# Filter for recent games (using granular mode name)
recent_games = game_filter.filter_games_by_mode(games, 'recent')  # Updated to use mode type
print(f"Recent games after mode filtering: {len(recent_games)}")

# Apply favorite teams filter
favorite_games = game_filter.filter_favorite_teams_only(recent_games, True)
print(f"Favorite teams games: {len(favorite_games)}")

# Sort games (updated to use mode type)
sorted_games = game_filter.sort_games(favorite_games, 'recent')
print(f"Final sorted games: {len(sorted_games)}")

# Show the first few recent TB games
print("\nRecent TB games (should show most recent first):")
for i, game in enumerate(sorted_games[:5]):
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {i+1}. {away_team} @ {home_team} ({start_time[:10]}) - {status}")

# Show all recent games before favorite teams filter
print(f"\nAll recent games before favorite teams filter: {len(recent_games)}")
for i, game in enumerate(recent_games[:10]):
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {i+1}. {away_team} @ {home_team} ({start_time[:10]}) - {status}")

# Check if 10/18/2025 game is in recent games
oct_18_in_recent = [g for g in recent_games if '2025-10-18' in g.get('start_time', '')]
print(f"\n10/18/2025 games in recent: {len(oct_18_in_recent)}")
for game in oct_18_in_recent:
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {away_team} @ {home_team} ({start_time}) - {status}")

# Check specifically for 10/18/2025 game
oct_18_games = [g for g in sorted_games if '2025-10-18' in g.get('start_time', '')]
print(f"\nGames on 2025-10-18: {len(oct_18_games)}")
for game in oct_18_games:
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {away_team} @ {home_team} ({start_time}) - {status}")
