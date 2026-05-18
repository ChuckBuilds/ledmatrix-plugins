"""
Data Fetcher for Hockey Scoreboard Plugin

Handles all data fetching operations for the hockey scoreboard plugin,
including ESPN API calls, caching, and data processing.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List

import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HockeyDataFetcher:
    """Handles data fetching for hockey scoreboard plugin."""
    
    # ESPN API base endpoints for each league
    ESPN_API_BASE_URLS = {
        'nhl': 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard',
        'ncaa_mens': 'https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/scoreboard',
        'ncaa_womens': 'https://site.api.espn.com/apis/site/v2/sports/hockey/womens-college-hockey/scoreboard'
    }
    
    def __init__(self, cache_manager, logger: logging.Logger):
        """Initialize the data fetcher."""
        self.cache_manager = cache_manager
        self.logger = logger
        
        # Set up session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Set up headers
        self.headers = {
            'User-Agent': 'LEDMatrix-HockeyPlugin/1.0 (https://github.com/yourusername/LEDMatrix)',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
    
    def _get_season_date_range(self, league_key: str) -> str:
        """Get the date range for the current season."""
        from datetime import datetime
        
        now = datetime.now()

        # For 2025, we want the 2025-26 season (October 2025 to end of season 2026)
        if league_key == 'nhl':
            # NHL 2025-26 season: October 2025 to June 2026
            season_start = datetime(2025, 10, 1)
            season_end = datetime(2026, 6, 30)
        elif league_key in ['ncaa_mens', 'ncaa_womens']:
            # NCAA 2025-26 season: October 2025 to March 2026
            season_start = datetime(2025, 10, 1)
            season_end = datetime(2026, 3, 31)
        else:
            # Default to 2025-26 season
            season_start = datetime(2025, 10, 1)
            season_end = datetime(2026, 6, 30)
        
        # Format as YYYYMMDD-YYYYMMDD
        start_str = season_start.strftime('%Y%m%d')
        end_str = season_end.strftime('%Y%m%d')
        return f"{start_str}-{end_str}"
    
    def fetch_league_data(self, league_key: str, league_config: Dict, 
                         last_update: float = 0) -> List[Dict]:
        """
        Fetch game data for a specific league.
        
        Args:
            league_key: League identifier (nhl, ncaa_mens, ncaa_womens)
            league_config: League-specific configuration
            last_update: Timestamp of last update
            
        Returns:
            List of game dictionaries
        """
        cache_key = f"hockey_{league_key}_{datetime.now().strftime('%Y%m%d')}"
        update_interval = league_config.get('update_interval_seconds', 60)
        
        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - last_update) < update_interval:
            self.logger.debug(f"Using cached data for {league_key}")
            return cached_data
        
        # Fetch from API
        try:
            base_url = self.ESPN_API_BASE_URLS.get(league_key)
            if not base_url:
                self.logger.error(f"Unknown league key: {league_key}")
                return []
            
            # Get the season date range
            date_range = self._get_season_date_range(league_key)
            url = f"{base_url}?dates={date_range}"
            
            self.logger.info(f"Fetching {league_key} data from ESPN API for season {date_range}...")
            response = self.session.get(
                url, 
                timeout=league_config.get('request_timeout', 30),
                headers=self.headers
            )
            response.raise_for_status()
            
            data = response.json()
            games = self._process_api_response(data, league_key, league_config)
            
            # Cache for league-specific interval
            self.cache_manager.set(cache_key, games)
            
            return games
            
        except requests.RequestException as e:
            self.logger.error(f"Error fetching {league_key} data: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error processing {league_key} data: {e}")
            return []
    
    def _process_api_response(self, data: Dict, league_key: str, 
                            league_config: Dict) -> List[Dict]:
        """Process ESPN API response into standardized game format."""
        games = []
        
        try:
            events = data.get('events', [])
            
            for event in events:
                try:
                    game = self._extract_game_info(event, league_key, league_config)
                    if game:
                        games.append(game)
                except Exception as e:
                    self.logger.error(f"Error extracting game info: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Error processing API response: {e}")
            
        return games
    
    def _extract_game_info(self, event: Dict, league_key: str, 
                          league_config: Dict) -> Optional[Dict]:
        """Extract game information from ESPN event."""
        try:
            competition = event.get('competitions', [{}])[0]
            status = competition.get('status', {})
            competitors = competition.get('competitors', [])
            
            if len(competitors) < 2:
                return None
            
            # Find home and away teams
            home_team = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_team = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            if not home_team or not away_team:
                return None
            
            # Extract game details
            game = {
                'league': league_key,
                'league_config': league_config,
                'game_id': event.get('id'),
                'home_team': {
                    'name': home_team.get('team', {}).get('displayName', 'Unknown'),
                    'abbrev': home_team.get('team', {}).get('abbreviation', 'UNK'),
                    'score': int(home_team.get('score', 0)),
                    'logo': home_team.get('team', {}).get('logo'),
                    'id': home_team.get('team', {}).get('id'),
                    'statistics': home_team.get('statistics', [])
                },
                'away_team': {
                    'name': away_team.get('team', {}).get('displayName', 'Unknown'),
                    'abbrev': away_team.get('team', {}).get('abbreviation', 'UNK'),
                    'score': int(away_team.get('score', 0)),
                    'logo': away_team.get('team', {}).get('logo'),
                    'id': away_team.get('team', {}).get('id'),
                    'statistics': away_team.get('statistics', [])
                },
                'status': {
                    'state': status.get('type', {}).get('state', 'unknown'),
                    'detail': status.get('type', {}).get('detail', ''),
                    'short_detail': status.get('type', {}).get('shortDetail', ''),
                    'period': status.get('period', 0),
                    'display_clock': status.get('displayClock', '')
                },
                'start_time': event.get('date', ''),
                'venue': competition.get('venue', {}).get('fullName', 'Unknown Venue')
            }
            
            # Add powerplay info if available
            situation = competition.get('situation', {})
            if situation:
                game['powerplay'] = situation.get('isPowerPlay', False)
                game['penalties'] = situation.get('penalties', '')
            
            # Add shots on goal if available
            home_stats = home_team.get('statistics', [])
            away_stats = away_team.get('statistics', [])
            
            # Extract shots on goal
            home_shots = next(
                (int(s.get('displayValue', 0)) for s in home_stats if s.get('name') == 'shots'),
                0
            )
            away_shots = next(
                (int(s.get('displayValue', 0)) for s in away_stats if s.get('name') == 'shots'),
                0
            )
            
            game['home_team']['shots'] = home_shots
            game['away_team']['shots'] = away_shots
            
            # Add records if available
            home_record = home_team.get('records', [{}])[0].get('summary', '') if home_team.get('records') else ''
            away_record = away_team.get('records', [{}])[0].get('summary', '') if away_team.get('records') else ''
            
            # Don't show "0-0" records
            if home_record in {"0-0", "0-0-0"}:
                home_record = ''
            if away_record in {"0-0", "0-0-0"}:
                away_record = ''
                
            game['home_team']['record'] = home_record
            game['away_team']['record'] = away_record
            
            return game
            
        except Exception as e:
            self.logger.error(f"Error extracting game info: {e}")
            return None
    
    def fetch_todays_games(self, league_key: str) -> Optional[Dict]:
        """Fetch only today's games for live updates."""
        try:
            now = datetime.now()
            formatted_date = now.strftime("%Y%m%d")
            
            url = self.ESPN_API_URLS.get(league_key)
            if not url:
                return None
                
            response = self.session.get(
                url, 
                params={"dates": formatted_date, "limit": 1000}, 
                headers=self.headers, 
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            events = data.get('events', [])
            
            self.logger.info(f"Fetched {len(events)} today's games for {league_key}")
            return {'events': events}
            
        except requests.RequestException as e:
            self.logger.error(f"API error fetching today's games for {league_key}: {e}")
            return None
    
    def fetch_weeks_data(self, league_key: str) -> Optional[Dict]:
        """Get partial data for immediate display while background fetch is in progress."""
        try:
            # Fetch current week and next few days for immediate display
            now = datetime.now(pytz.utc)
            start_date = now - timedelta(weeks=2)
            end_date = now + timedelta(weeks=1)
            date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
            
            url = self.ESPN_API_URLS.get(league_key)
            if not url:
                return None
                
            response = self.session.get(
                url, 
                params={"dates": date_str, "limit": 1000},
                headers=self.headers, 
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            immediate_events = data.get('events', [])
            
            if immediate_events:
                self.logger.info(f"Fetched {len(immediate_events)} events {date_str}")
                return {'events': immediate_events}
                
        except requests.RequestException as e:
            self.logger.warning(f"Error fetching this week's games for {league_key}: {e}")
        return None
