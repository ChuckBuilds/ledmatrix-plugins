"""
Baseball Data Manager

Handles all data fetching and API interactions for MLB, MiLB, and NCAA Baseball.
Supports ESPN API (MLB, NCAA Baseball) and MLB Stats API (MiLB).
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ESPN API URLs
ESPN_MLB_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
ESPN_NCAA_BASEBALL_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard"

# MLB Stats API base URL
MLB_STATS_BASE_URL = "http://statsapi.mlb.com/api/v1"
MLB_STATS_LIVE_FEED_URL = "http://statsapi.mlb.com/api/v1.1/game"


class BaseballDataManager:
    """Handles all data fetching and API interactions for baseball leagues."""

    def __init__(self, cache_manager, logger: logging.Logger):
        """
        Initialize the data manager.

        Args:
            cache_manager: Cache manager instance
            logger: Logger instance
        """
        self.cache_manager = cache_manager
        self.logger = logger

        # Initialize background service for ESPN leagues
        self.background_service = None
        self.background_fetch_requests = {}
        try:
            from src.background_data_service import get_background_service
            self.background_service = get_background_service(cache_manager, max_workers=1)
            self.background_enabled = True
            self.logger.info("Background service enabled for ESPN leagues")
        except ImportError:
            self.background_enabled = False
            self.logger.warning("Background service not available")

        # Set up HTTP session with retry logic
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
            'User-Agent': 'LEDMatrix/1.0 (https://github.com/yourusername/LEDMatrix; contact@example.com)',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }

        # MiLB team mapping
        self.milb_team_mapping = {}
        self.milb_team_name_to_abbr = {}

    def load_milb_team_mapping(self, mapping_path: str = None) -> bool:
        """
        Load MiLB team mapping from JSON file.

        Args:
            mapping_path: Path to team mapping JSON file

        Returns:
            True if loaded successfully, False otherwise
        """
        if mapping_path is None:
            mapping_path = os.path.join('assets', 'sports', 'milb_logos', 'milb_team_mapping.json')

        try:
            with open(mapping_path, 'r') as f:
                self.milb_team_mapping = json.load(f)
            self.milb_team_name_to_abbr = {
                name: data['abbreviation'] for name, data in self.milb_team_mapping.items()
            }
            self.logger.info(f"Loaded {len(self.milb_team_name_to_abbr)} MiLB team mappings")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load MiLB team mapping: {e}")
            return False

    def fetch_season_data(self, league_key: str, league_config: Dict, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetch full season data for ESPN leagues (MLB, NCAA Baseball).

        Args:
            league_key: League identifier (mlb, ncaa_baseball)
            league_config: League-specific configuration
            use_cache: Whether to use cached data

        Returns:
            Dictionary with events list, or None if fetch failed
        """
        if league_key == 'milb':
            # MiLB uses different API - call fetch_milb_games instead
            return None

        # Determine API URL
        if league_key == 'mlb':
            url = ESPN_MLB_SCOREBOARD_URL
        elif league_key == 'ncaa_baseball':
            url = ESPN_NCAA_BASEBALL_SCOREBOARD_URL
        else:
            self.logger.error(f"Unknown ESPN league key: {league_key}")
            return None

        # Calculate date range (last month to next month)
        now = datetime.now(pytz.utc)
        start_of_last_month = now.replace(day=1, month=now.month - 1)
        last_day_of_next_month = now.replace(day=1, month=now.month + 2) - timedelta(days=1)
        start_of_last_month_str = start_of_last_month.strftime("%Y%m%d")
        last_day_of_next_month_str = last_day_of_next_month.strftime("%Y%m%d")
        datestring = f"{start_of_last_month_str}-{last_day_of_next_month_str}"
        cache_key = f"{league_key}_schedule_{datestring}"

        # Check cache
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info(f"Using cached schedule for {league_key} ({datestring})")
                    return cached_data
                elif isinstance(cached_data, list):
                    self.logger.info(f"Using cached schedule for {league_key} ({datestring}) (legacy format)")
                    return {"events": cached_data}
                else:
                    self.logger.warning(f"Invalid cached data format for {league_key}: {type(cached_data)}")
                    self.cache_manager.clear_cache(cache_key)

        self.logger.info(f"Fetching full {datestring} season schedule from ESPN API for {league_key}...")

        # Start background fetch if enabled
        if self.background_service and self.background_enabled:
            background_config = league_config.get("background_service", {})
            timeout = background_config.get("request_timeout", 30)
            max_retries = background_config.get("max_retries", 3)
            priority = background_config.get("priority", 2)

            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for {league_key} {datestring}: "
                        f"{len(result.data.get('events', []))} events"
                    )
                else:
                    self.logger.error(f"Background fetch failed for {league_key} {datestring}: {result.error}")

                if datestring in self.background_fetch_requests:
                    del self.background_fetch_requests[datestring]

            request_id = self.background_service.submit_fetch_request(
                sport=league_key,
                year=now.year,
                url=url,
                cache_key=cache_key,
                params={"dates": datestring, "limit": 1000},
                headers=self.headers,
                timeout=timeout,
                max_retries=max_retries,
                priority=priority,
                callback=fetch_callback,
            )

            self.background_fetch_requests[datestring] = request_id

            # Return partial data immediately
            partial_data = self._get_weeks_data(league_key, url)
            if partial_data:
                return partial_data
            return None
        else:
            # Fallback to direct fetch
            try:
                response = self.session.get(
                    url,
                    params={"dates": datestring, "limit": 1000},
                    headers=self.headers,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()

                # Cache the data
                if isinstance(data, dict) and "events" in data:
                    self.cache_manager.set(cache_key, data)
                    return data

            except requests.RequestException as e:
                self.logger.error(f"Error fetching {league_key} season data: {e}")
                return None

        return None

    def fetch_todays_games(self, league_key: str, league_config: Dict) -> Optional[Dict]:
        """
        Fetch today's games for live updates (ESPN leagues only).

        Args:
            league_key: League identifier
            league_config: League-specific configuration

        Returns:
            Dictionary with events list, or None if fetch failed
        """
        if league_key == 'milb':
            # MiLB uses different method
            return None

        # Determine API URL
        if league_key == 'mlb':
            url = ESPN_MLB_SCOREBOARD_URL
        elif league_key == 'ncaa_baseball':
            url = ESPN_NCAA_BASEBALL_SCOREBOARD_URL
        else:
            self.logger.error(f"Unknown ESPN league key: {league_key}")
            return None

        try:
            now = datetime.now()
            formatted_date = now.strftime("%Y%m%d")
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

    def _get_weeks_data(self, league_key: str, url: str) -> Optional[Dict]:
        """
        Get partial data for immediate display while background fetch is in progress.

        Args:
            league_key: League identifier
            url: API URL

        Returns:
            Dictionary with events list, or None if fetch failed
        """
        try:
            now = datetime.now(pytz.utc)
            start_date = now + timedelta(weeks=-2)
            end_date = now + timedelta(weeks=1)
            date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"

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
                self.logger.info(f"Fetched {len(immediate_events)} events for {league_key} ({date_str})")
                return {'events': immediate_events}

        except requests.RequestException as e:
            self.logger.warning(f"Error fetching partial data for {league_key}: {e}")

        return None

    def fetch_milb_games(self, league_config: Dict, date_range: int = 7, sport_ids: List[int] = None) -> Dict[str, Dict]:
        """
        Fetch MiLB game data from MLB Stats API.

        Args:
            league_config: MiLB configuration
            date_range: Days to look ahead/behind (default 7)
            sport_ids: List of sport IDs to fetch (default: all MiLB levels)

        Returns:
            Dictionary of game data keyed by game_pk
        """
        if sport_ids is None:
            sport_ids = league_config.get('sport_ids', [10, 11, 12, 13, 14, 15])

        # Check test mode
        if league_config.get('test_mode', False):
            self.logger.info("Using test mode data for MiLB")
            return {
                'test_game_1': {
                    'id': 'test_game_1',
                    'away_team': 'TOL',
                    'home_team': 'BUF',
                    'away_score': 3,
                    'home_score': 2,
                    'status': 'status_in_progress',
                    'status_state': 'in',
                    'inning': 7,
                    'inning_half': 'bottom',
                    'balls': 2,
                    'strikes': 1,
                    'outs': 1,
                    'bases_occupied': [True, False, True],
                    'start_time': datetime.now(timezone.utc).isoformat()
                }
            }

        # Season detection (April-September)
        now = datetime.now()
        current_month = now.month
        in_season = 4 <= current_month <= 9

        if not in_season:
            self.logger.info("MiLB is currently in offseason (October-March). No games expected.")
            return {}

        # Load team mapping if not already loaded
        if not self.milb_team_mapping:
            mapping_path = league_config.get('team_mapping_path')
            self.load_milb_team_mapping(mapping_path)

        # Calculate date range
        now_utc = datetime.now(timezone.utc)
        dates = [(now_utc + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(-1, date_range)]

        all_games = {}

        for date in dates:
            for sport_id in sport_ids:
                url = f"{MLB_STATS_BASE_URL}/schedule?sportId={sport_id}&date={date}"
                try:
                    self.logger.debug(f"Fetching MiLB games from MLB Stats API: {url}")
                    response = self.session.get(url, headers=self.headers, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                except requests.RequestException as e:
                    self.logger.error(f"Error fetching data from {url}: {e}")
                    continue

                if not data.get('dates') or not data['dates'][0].get('games'):
                    continue

                for event in data['dates'][0]['games']:
                    game_pk = event.get('gamePk')
                    if not game_pk:
                        continue

                    # Convert to string for consistency
                    if not isinstance(game_pk, (int, str)):
                        game_pk = str(game_pk)

                    home_team_name = event['teams']['home']['team']['name']
                    away_team_name = event['teams']['away']['team']['name']

                    # Resolve team abbreviations
                    home_abbr = self.milb_team_name_to_abbr.get(home_team_name)
                    away_abbr = self.milb_team_name_to_abbr.get(away_team_name)

                    if not home_abbr:
                        home_abbr = event['teams']['home']['team'].get('abbreviation', home_team_name[:3].upper())
                    if not away_abbr:
                        away_abbr = event['teams']['away']['team'].get('abbreviation', away_team_name[:3].upper())

                    # Get team records
                    away_record_data = event['teams']['away'].get('record', {})
                    home_record_data = event['teams']['home'].get('record', {})
                    away_record = away_record_data.get('wins')
                    away_losses = away_record_data.get('losses')
                    home_record = home_record_data.get('wins')
                    home_losses = home_record_data.get('losses')

                    if away_record is not None and away_losses is not None and (away_record != 0 or away_losses != 0):
                        away_record_str = f"{away_record}-{away_losses}"
                    else:
                        away_record_str = ''

                    if home_record is not None and home_losses is not None and (home_record != 0 or home_losses != 0):
                        home_record_str = f"{home_record}-{home_losses}"
                    else:
                        home_record_str = ''

                    if not event.get('gameDate'):
                        self.logger.warning(f"Skipping game {game_pk} due to missing 'gameDate'.")
                        continue

                    status_obj = event['status']
                    status_state = status_obj.get('abstractGameState', 'Preview')
                    detailed_state = status_obj.get('detailedState', '')

                    # Map status to consistent format
                    mapped_status = 'status_other'
                    mapped_status_state = 'pre'

                    if status_state == 'Live':
                        mapped_status = 'status_in_progress'
                        mapped_status_state = 'in'
                    elif status_state == 'Final':
                        mapped_status = 'status_final'
                        mapped_status_state = 'post'
                    elif status_state in ['Preview', 'Scheduled']:
                        mapped_status = 'status_scheduled'
                        mapped_status_state = 'pre'

                    game_data = {
                        'id': str(game_pk),
                        'away_team': away_abbr,
                        'home_team': home_abbr,
                        'away_score': event['teams']['away'].get('score', 0),
                        'home_score': event['teams']['home'].get('score', 0),
                        'status': mapped_status,
                        'status_state': mapped_status_state,
                        'detailed_state': detailed_state,
                        'start_time': event.get('gameDate'),
                        'away_record': away_record_str,
                        'home_record': home_record_str,
                        'game_pk': game_pk  # Keep for live feed probing
                    }

                    # Extract live game details if applicable
                    if status_state == 'Live':
                        linescore = event.get('linescore', {})
                        game_data['inning'] = linescore.get('currentInning', 1)
                        inning_state = linescore.get('inningState', 'Top').lower()
                        game_data['inning_half'] = 'bottom' if 'bottom' in inning_state else 'top'
                        game_data['balls'] = linescore.get('balls', 0)
                        game_data['strikes'] = linescore.get('strikes', 0)
                        game_data['outs'] = linescore.get('outs', 0)
                        offense = linescore.get('offense', {})
                        game_data['bases_occupied'] = [
                            'first' in offense,
                            'second' in offense,
                            'third' in offense
                        ]
                    else:
                        game_data.update({
                            'inning': 1,
                            'inning_half': 'top',
                            'balls': 0,
                            'strikes': 0,
                            'outs': 0,
                            'bases_occupied': [False] * 3
                        })

                    all_games[str(game_pk)] = game_data

        self.logger.info(f"Fetched {len(all_games)} MiLB games from API")
        return all_games

    def probe_milb_live_feed(self, game_pk: str, game_data: Dict[str, Any]) -> bool:
        """
        Probe MLB Stats live feed for a game and update game_data in-place if live.

        Args:
            game_pk: Game primary key
            game_data: Game data dictionary to update

        Returns:
            True if the feed indicates the game is in progress, False otherwise
        """
        try:
            live_url = f"{MLB_STATS_LIVE_FEED_URL}/{game_pk}/feed/live"
            self.logger.debug(f"[MiLB] Probing live feed for game {game_pk}: {live_url}")
            resp = self.session.get(live_url, headers=self.headers, timeout=6)
            resp.raise_for_status()
            payload = resp.json()

            game_data_obj = payload.get('gameData', {})
            status_obj = game_data_obj.get('status', {})
            status_code = str(status_obj.get('statusCode', '')).upper()
            abstract_state = str(status_obj.get('abstractGameState', '')).lower()

            is_live = (status_code == 'I') or (abstract_state == 'live')

            if not is_live:
                return False

            # Update primary fields from live feed
            live_data = payload.get('liveData', {})
            linescore = live_data.get('linescore', {})

            # Scores
            away_runs = linescore.get('teams', {}).get('away', {}).get('runs')
            home_runs = linescore.get('teams', {}).get('home', {}).get('runs')
            if away_runs is not None:
                game_data['away_score'] = away_runs
            if home_runs is not None:
                game_data['home_score'] = home_runs

            # Inning and half
            inning = linescore.get('currentInning')
            if inning is not None:
                game_data['inning'] = inning
            inning_state_live = str(linescore.get('inningState', '')).lower()
            if inning_state_live:
                game_data['inning_half'] = 'bottom' if 'bottom' in inning_state_live else 'top'

            # Count and outs
            balls = linescore.get('balls')
            strikes = linescore.get('strikes')
            outs = linescore.get('outs')
            if balls is not None:
                game_data['balls'] = balls
            if strikes is not None:
                game_data['strikes'] = strikes
            if outs is not None:
                game_data['outs'] = outs

            offense = linescore.get('offense', {})
            game_data['bases_occupied'] = [
                'first' in offense,
                'second' in offense,
                'third' in offense
            ]

            # Set status to in-progress
            game_data['status'] = 'status_in_progress'
            game_data['status_state'] = 'in'
            game_data['_status_code'] = status_code
            return True
        except Exception as e:
            self.logger.debug(f"[MiLB] Live feed probe failed for {game_pk}: {e}")
            return False

    def extract_game_details(self, event: Dict, league_key: str, league_config: Dict, 
                            favorite_teams: List[str] = None) -> Optional[Dict]:
        """
        Extract game details from API response (ESPN or MLB Stats).

        Args:
            event: Event/game data from API
            league_key: League identifier
            league_config: League-specific configuration
            favorite_teams: List of favorite team abbreviations

        Returns:
            Extracted game details dictionary, or None if extraction failed
        """
        if league_key == 'milb':
            return self._extract_milb_game_details(event, league_config)
        else:
            return self._extract_espn_game_details(event, league_key, favorite_teams or [])

    def _extract_espn_game_details(self, game_event: Dict, league_key: str, 
                                   favorite_teams: List[str]) -> Optional[Dict]:
        """
        Extract game details from ESPN API response.

        This replicates the logic from Baseball._extract_game_details()
        """
        try:
            pass

            # Create a minimal sports core instance for game extraction
            # We'll use the common extraction method
            competition = game_event.get("competitions", [{}])[0]
            status = competition.get("status", {})
            competitors = competition.get("competitors", [])
            game_date_str = game_event.get("date")
            situation = competition.get("situation")

            if not competitors or len(competitors) < 2:
                return None

            home_team = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_team = next((c for c in competitors if c.get("homeAway") == "away"), None)

            if not home_team or not away_team:
                return None

            try:
                home_abbr = home_team["team"]["abbreviation"]
            except KeyError:
                home_abbr = home_team["team"]["name"][:3]
            try:
                away_abbr = away_team["team"]["abbreviation"]
            except KeyError:
                away_abbr = away_team["team"]["name"][:3]

            # Check if this is a favorite team game
            (home_abbr in favorite_teams or away_abbr in favorite_teams)

            game_status = status.get("type", {}).get("name", "").lower()
            status_state = status.get("type", {}).get("state", "").lower()

            # Parse game time
            start_time_utc = None
            try:
                start_time_utc = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

            # Get records
            home_record = home_team.get('records', [{}])[0].get('summary', '') if home_team.get('records') else ''
            away_record = away_team.get('records', [{}])[0].get('summary', '') if away_team.get('records') else ''

            # Don't show "0-0" records
            if home_record in {"0-0", "0-0-0"}:
                home_record = ''
            if away_record in {"0-0", "0-0-0"}:
                away_record = ''

            details = {
                "id": game_event.get("id"),
                "game_time": "",
                "game_date": "",
                "start_time_utc": start_time_utc,
                "status_text": status.get("type", {}).get("shortDetail", ""),
                "is_live": status_state == "in",
                "is_final": status_state == "post",
                "is_upcoming": (status_state == "pre" or game_status in ['scheduled', 'pre-game', 'status_scheduled']),
                "is_halftime": False,
                "is_period_break": False,
                "home_abbr": home_abbr,
                "home_id": home_team.get("id"),
                "home_score": home_team.get("score", "0"),
                "home_logo_path": Path("assets/sports/ncaa_logos" if league_key == "ncaa_baseball" else "assets/sports/mlb_logos") / f"{home_abbr}.png",
                "home_logo_url": home_team["team"].get("logo"),
                "home_record": home_record,
                "away_record": away_record,
                "away_abbr": away_abbr,
                "away_id": away_team.get("id"),
                "away_score": away_team.get("score", "0"),
                "away_logo_path": Path("assets/sports/ncaa_logos" if league_key == "ncaa_baseball" else "assets/sports/mlb_logos") / f"{away_abbr}.png",
                "away_logo_url": away_team["team"].get("logo"),
                "is_within_window": True,
                "status": game_status,
                "status_state": status_state,
            }

            # Extract baseball-specific details if live
            if status_state == "in":
                inning = game_event.get("status", {}).get("period", 1)
                status_detail = status.get("type", {}).get("detail", "").lower()
                status_short = status.get("type", {}).get("shortDetail", "").lower()

                # Determine inning half
                inning_half = "top"
                if "end" in status_detail or "end" in status_short:
                    inning_half = "top"
                    inning = game_event.get("status", {}).get("period", 1) + 1
                elif "mid" in status_detail or "mid" in status_short:
                    inning_half = "bottom"
                elif "bottom" in status_detail or "bot" in status_detail or "bottom" in status_short or "bot" in status_short:
                    inning_half = "bottom"
                elif "top" in status_detail or "top" in status_short:
                    inning_half = "top"

                # Get count and bases from situation
                count = situation.get("count", {}) if situation else {}
                balls = count.get("balls", 0)
                strikes = count.get("strikes", 0)
                outs = situation.get("outs", 0) if situation else 0

                # Try alternative locations for count data
                if balls == 0 and strikes == 0 and situation:
                    if "summary" in situation:
                        try:
                            count_summary = situation["summary"]
                            balls, strikes = map(int, count_summary.split("-"))
                        except (ValueError, AttributeError):
                            pass
                    else:
                        balls = situation.get("balls", 0)
                        strikes = situation.get("strikes", 0)

                bases_occupied = [
                    situation.get("onFirst", False) if situation else False,
                    situation.get("onSecond", False) if situation else False,
                    situation.get("onThird", False) if situation else False,
                ]

                details.update({
                    "inning": inning,
                    "inning_half": inning_half,
                    "balls": balls,
                    "strikes": strikes,
                    "outs": outs,
                    "bases_occupied": bases_occupied,
                })
            else:
                details.update({
                    "inning": 1,
                    "inning_half": "top",
                    "balls": 0,
                    "strikes": 0,
                    "outs": 0,
                    "bases_occupied": [False, False, False],
                })

            # Get series summary if available
            series = game_event.get("competitions", [{}])[0].get("series")
            if series:
                details["series_summary"] = series.get("summary", "")

            details["start_time"] = game_date_str

            return details

        except Exception as e:
            self.logger.error(f"Error extracting ESPN game details: {e} from event: {game_event.get('id')}", exc_info=True)
            return None

    def _extract_milb_game_details(self, game_data: Dict, league_config: Dict) -> Optional[Dict]:
        """
        Extract game details from MiLB game data (already processed from MLB Stats API).

        Args:
            game_data: Game data dictionary from fetch_milb_games
            league_config: League-specific configuration

        Returns:
            Standardized game details dictionary
        """
        try:
            # MiLB data is already in a standardized format from fetch_milb_games
            # Just ensure all required fields are present
            game_id = game_data.get('id')
            if not game_id:
                return None

            # Determine if live/final/upcoming
            status_state = game_data.get('status_state', 'pre')
            is_live = status_state == 'in'
            is_final = status_state in ['post', 'final', 'completed']
            is_upcoming = status_state == 'pre' and not is_final

            details = {
                "id": game_id,
                "game_time": "",
                "game_date": "",
                "start_time_utc": None,
                "status_text": game_data.get('detailed_state', ''),
                "is_live": is_live,
                "is_final": is_final,
                "is_upcoming": is_upcoming,
                "is_halftime": False,
                "is_period_break": False,
                "home_abbr": game_data.get('home_team', ''),
                "home_id": game_data.get('game_pk'),  # Use game_pk as ID
                "home_score": str(game_data.get('home_score', 0)),
                "home_logo_path": Path(league_config.get('logo_dir', 'assets/sports/milb_logos')) / f"{game_data.get('home_team', '')}.png",
                "home_logo_url": None,
                "home_record": game_data.get('home_record', ''),
                "away_record": game_data.get('away_record', ''),
                "away_abbr": game_data.get('away_team', ''),
                "away_id": game_data.get('game_pk'),
                "away_score": str(game_data.get('away_score', 0)),
                "away_logo_path": Path(league_config.get('logo_dir', 'assets/sports/milb_logos')) / f"{game_data.get('away_team', '')}.png",
                "away_logo_url": None,
                "is_within_window": True,
                "status": game_data.get('status', ''),
                "status_state": status_state,
                "inning": game_data.get('inning', 1),
                "inning_half": game_data.get('inning_half', 'top'),
                "balls": game_data.get('balls', 0),
                "strikes": game_data.get('strikes', 0),
                "outs": game_data.get('outs', 0),
                "bases_occupied": game_data.get('bases_occupied', [False, False, False]),
                "start_time": game_data.get('start_time', ''),
                "series_summary": "",
            }

            # Parse start time if available
            start_time_str = game_data.get('start_time')
            if start_time_str:
                try:
                    details["start_time_utc"] = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass

            return details

        except Exception as e:
            self.logger.error(f"Error extracting MiLB game details: {e}", exc_info=True)
            return None

