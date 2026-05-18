#!/usr/bin/env python3
"""
Debug script to check what TB Lightning games are in the data
"""

import sys
sys.path.append('/home/chuck/Github/LEDMatrix/src')

from data_fetcher import HockeyDataFetcher
from cache_manager import CacheManager
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize components
cache_manager = CacheManager()
data_fetcher = HockeyDataFetcher(cache_manager, logger)

# Fetch NHL data
print("Fetching NHL data...")
nhl_config = {
    'enabled': True,
    'update_interval_seconds': 60,
    'request_timeout': 30
}

games = data_fetcher.fetch_league_data('nhl', nhl_config)
print(f"Total NHL games: {len(games)}")

# Filter for TB games
tb_games = []
for game in games:
    home_team = game.get('home_team', {}).get('abbrev', '')
    away_team = game.get('away_team', {}).get('abbrev', '')
    if 'TB' in [home_team, away_team]:
        tb_games.append(game)

print(f"TB games found: {len(tb_games)}")

# Show all TB games
for i, game in enumerate(tb_games):
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {i+1}. {away_team} @ {home_team} ({start_time[:10]}) - {status}")

# Look specifically for 10/18/2025
oct_18_games = [g for g in tb_games if '2025-10-18' in g.get('start_time', '')]
print(f"\nGames on 2025-10-18: {len(oct_18_games)}")
for game in oct_18_games:
    home_team = game.get('home_team', {}).get('abbrev', 'UNK')
    away_team = game.get('away_team', {}).get('abbrev', 'UNK')
    start_time = game.get('start_time', '')
    status = game.get('status', {}).get('state', '')
    print(f"  {away_team} @ {home_team} ({start_time}) - {status}")
