"""
Soccer League Managers for LEDMatrix

This module provides manager classes for various soccer leagues including
Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Champions League, and Europa League.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import pytz

from sports import SportsCore, SportsLive, SportsRecent, SportsUpcoming

# ESPN API base URL for soccer
ESPN_SOCCER_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# League display names
LEAGUE_NAMES = {
    'eng.1': 'Premier League',
    'esp.1': 'La Liga',
    'ger.1': 'Bundesliga',
    'ita.1': 'Serie A',
    'fra.1': 'Ligue 1',
    'usa.1': 'MLS',
    'por.1': 'Liga Portugal',
    'uefa.champions': 'Champions League',
    'uefa.europa': 'Europa League'
}


class BaseSoccerManager(SportsCore):
    """Base class for soccer league managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged = False
    _last_warning_time = 0
    _warning_cooldown = 60  # Only log warnings once per minute
    _shared_data = None
    _last_shared_update = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        """
        Initialize base soccer manager.
        
        Args:
            config: Configuration dictionary
            display_manager: Display manager instance
            cache_manager: Cache manager instance
            league_key: League identifier (e.g., 'eng.1', 'esp.1')
        """
        self.logger = logging.getLogger(f"Soccer-{league_key}")
        self.league_key = league_key
        self.league_name = LEAGUE_NAMES.get(league_key, league_key)
        
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key=f"soccer_{league_key}",  # Use league-specific sport_key
        )
        
        # Set sport and league for ESPN API (after parent init to avoid overwrite)
        self.sport = "soccer"
        self.league = league_key

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get(f"soccer_{league_key}_recent", False)
        self.upcoming_enabled = display_modes.get(f"soccer_{league_key}_upcoming", False)
        self.live_enabled = display_modes.get(f"soccer_{league_key}_live", False)

        self.logger.info(
            f"Initialized {self.league_name} manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )

    def _fetch_soccer_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches game data for the soccer league using background threading.
        Returns cached data immediately if available, otherwise starts background fetch.
        """
        now = datetime.now(pytz.utc)
        
        # For soccer, fetch a date range (past 2 weeks to future 2 weeks)
        start_date = now - timedelta(days=14)
        end_date = now + timedelta(days=14)
        date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
        
        cache_key = f"soccer_{self.league_key}_schedule_{date_str}"
        url = f"{ESPN_SOCCER_BASE_URL}/{self.league_key}/scoreboard"

        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                # Validate cached data structure
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info(f"Using cached schedule for {self.league_name}")
                    return cached_data
                elif isinstance(cached_data, list):
                    # Handle old cache format (list of events)
                    self.logger.info(
                        f"Using cached schedule for {self.league_name} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {self.league_name}: {type(cached_data)}"
                    )
                    # Clear invalid cache
                    self.cache_manager.delete(cache_key)

        # Start background fetch if service is available
        if self.background_service and self.background_enabled:
            self.logger.info(
                f"Starting background fetch for {self.league_name} schedule..."
            )

            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for {self.league_name}: {len(result.data.get('events', []))} events"
                    )
                else:
                    self.logger.error(
                        f"Background fetch failed for {self.league_name}: {result.error}"
                    )

            # Get background service configuration
            background_config = self.mode_config.get("background_service", {})
            timeout = background_config.get("request_timeout", 30)
            max_retries = background_config.get("max_retries", 3)
            priority = background_config.get("priority", 2)

            # Submit background fetch request
            request_id = self.background_service.submit_fetch_request(
                sport="soccer",
                year=now.year,
                url=url,
                cache_key=cache_key,
                params={"dates": date_str, "limit": 1000},
                headers=self.headers,
                timeout=timeout,
                max_retries=max_retries,
                priority=priority,
                callback=fetch_callback,
            )

            # Track the request
            if not hasattr(self, 'background_fetch_requests'):
                self.background_fetch_requests = {}
            self.background_fetch_requests[date_str] = request_id

            # For immediate response, try to get partial data
            partial_data = self._get_weeks_data()
            if partial_data:
                return partial_data
        else:
            # Fallback to synchronous fetch if background service not available
            self.logger.warning(
                "Background service not available, using synchronous fetch"
            )
            try:
                response = self.session.get(
                    url,
                    params={"dates": date_str, "limit": 1000},
                    headers=self.headers,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

                # Cache the data
                self.cache_manager.set(cache_key, data)
                self.logger.info(f"Synchronously fetched {self.league_name} schedule")
                return data

            except Exception as e:
                self.logger.error(f"Failed to fetch {self.league_name} schedule: {e}")
                return None

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data using shared data mechanism or direct fetch for live."""
        if isinstance(self, SoccerLiveManager):
            # Live games should fetch only current games, not entire schedule
            return self._fetch_todays_games()
        else:
            # Recent and Upcoming managers should use cached schedule data
            return self._fetch_soccer_api_data(use_cache=True)

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN Soccer API response."""
        details, home_team, away_team, status, situation = self._extract_game_details_common(game_event)
        if details is None or home_team is None or away_team is None or status is None:
            return None
        
        try:
            # Format period/half for soccer
            period = status.get("period", 0)
            period_text = ""
            status_state = status["type"]["state"]
            
            if status_state == "in":
                if period == 0:
                    period_text = "Start"
                elif period == 1:
                    period_text = "1H"
                elif period == 2:
                    period_text = "2H"
                else:
                    period_text = f"{period}H"
            elif status_state == "halftime" or status["type"]["name"] == "STATUS_HALFTIME":
                period_text = "HALF"
            elif status_state == "post":
                period_text = "Final"
            elif status_state == "pre":
                period_text = details.get("game_time", "")

            # Get clock/time for live games
            clock = status.get("displayClock", "")
            if clock and status_state == "in":
                # Format clock for soccer (e.g., "45'" or "90+3'")
                period_text = f"{period_text} {clock}" if period_text else clock

            details.update({
                "period": period,
                "period_text": period_text,
                "clock": clock,
                "league": self.league_key,  # Add league field for scroll display
            })

            # Basic validation
            if not details['home_abbr'] or not details['away_abbr']:
                self.logger.warning(f"Missing team abbreviation in event: {details['id']}")
                return None

            self.logger.debug(f"Extracted: {details['away_abbr']}@{details['home_abbr']}, Status: {status['type']['name']}, Live: {details['is_live']}, Final: {details['is_final']}, Upcoming: {details['is_upcoming']}")

            return details
        except Exception as e:
            self.logger.error(f"Error extracting game details: {e} from event: {game_event.get('id')}", exc_info=True)
            return None


class SoccerLiveManager(BaseSoccerManager, SportsLive):
    """Manager for live soccer games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"SoccerLive-{league_key}")
        
        # Test mode removed - always use live data
        if False:
            # Test game for soccer
            self.current_game = {
                "id": "test001",
                "home_abbr": "MCI",
                "home_id": "123",
                "away_abbr": "LIV",
                "away_id": "456",
                "home_score": "2",
                "away_score": "1",
                "period": 2,
                "period_text": "2H",
                "clock": "75'",
                "home_logo_path": Path(self.logo_dir, "MCI.png"),
                "away_logo_path": Path(self.logo_dir, "LIV.png"),
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
                "is_halftime": False,
                "status_text": "75'",
            }
            self.live_games = [self.current_game]
            self.logger.info(f"Initialized {self.league_name} LiveManager with test game: LIV vs MCI")
        else:
            self.logger.info(f"Initialized {self.league_name} LiveManager in live mode")

    def _test_mode_update(self) -> None:
        """Simulate clock running down in test mode."""
        if self.current_game and "clock" in self.current_game:
            # Simulate clock counting down
            clock_str = self.current_game["clock"]
            if "'" in clock_str:
                try:
                    minutes = int(clock_str.replace("'", ""))
                    if minutes > 0:
                        minutes -= 1
                        self.current_game["clock"] = f"{minutes}'"
                        self.current_game["status_text"] = f"{minutes}'"
                except ValueError:
                    pass


class SoccerRecentManager(BaseSoccerManager, SportsRecent):
    """Manager for recently completed soccer games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"SoccerRecent-{league_key}")
        self.logger.info(
            f"Initialized {self.league_name} RecentManager with {len(self.favorite_teams)} favorite teams"
        )


class SoccerUpcomingManager(BaseSoccerManager, SportsUpcoming):
    """Manager for upcoming soccer games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"SoccerUpcoming-{league_key}")
        self.logger.info(
            f"Initialized {self.league_name} UpcomingManager with {len(self.favorite_teams)} favorite teams"
        )


# Factory functions to create league-specific managers
def create_premier_league_managers(config, display_manager, cache_manager):
    """Create Premier League (eng.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'eng.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'eng.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'eng.1'),
    )


def create_la_liga_managers(config, display_manager, cache_manager):
    """Create La Liga (esp.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'esp.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'esp.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'esp.1'),
    )


def create_bundesliga_managers(config, display_manager, cache_manager):
    """Create Bundesliga (ger.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'ger.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'ger.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'ger.1'),
    )


def create_serie_a_managers(config, display_manager, cache_manager):
    """Create Serie A (ita.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'ita.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'ita.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'ita.1'),
    )


def create_ligue_1_managers(config, display_manager, cache_manager):
    """Create Ligue 1 (fra.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'fra.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'fra.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'fra.1'),
    )


def create_mls_managers(config, display_manager, cache_manager):
    """Create MLS (usa.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'usa.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'usa.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'usa.1'),
    )


def create_liga_portugal_managers(config, display_manager, cache_manager):
    """Create Liga Portugal (por.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'por.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'por.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'por.1'),
    )


def create_champions_league_managers(config, display_manager, cache_manager):
    """Create Champions League (uefa.champions) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'uefa.champions'),
        SoccerRecentManager(config, display_manager, cache_manager, 'uefa.champions'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'uefa.champions'),
    )


def create_europa_league_managers(config, display_manager, cache_manager):
    """Create Europa League (uefa.europa) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'uefa.europa'),
        SoccerRecentManager(config, display_manager, cache_manager, 'uefa.europa'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'uefa.europa'),
    )


def create_custom_league_managers(
    league_code: str,
    league_name: str,
    config: Dict[str, Any],
    display_manager,
    cache_manager
):
    """
    Create managers for a custom soccer league.

    This factory function creates Live, Recent, and Upcoming managers for any
    ESPN-supported soccer league. Custom leagues use the same manager classes
    as predefined leagues but with a custom league code.

    Args:
        league_code: ESPN league code (e.g., 'por.1', 'mex.1', 'arg.1')
        league_name: Display name for the league (e.g., 'Liga Portugal')
        config: Configuration dictionary for the managers
        display_manager: Display manager instance
        cache_manager: Cache manager instance

    Returns:
        Tuple of (SoccerLiveManager, SoccerRecentManager, SoccerUpcomingManager)

    Example usage:
        live, recent, upcoming = create_custom_league_managers(
            'por.1', 'Liga Portugal', config, display_manager, cache_manager
        )
    """
    # Register the custom league name in the module's LEAGUE_NAMES dict
    # This allows the managers to get the proper display name
    LEAGUE_NAMES[league_code] = league_name

    logger = logging.getLogger(f"Soccer-{league_code}")
    logger.info(f"Creating managers for custom league: {league_name} ({league_code})")

    # Create manager instances with the custom league code
    live = SoccerLiveManager(config, display_manager, cache_manager, league_code)
    recent = SoccerRecentManager(config, display_manager, cache_manager, league_code)
    upcoming = SoccerUpcomingManager(config, display_manager, cache_manager, league_code)

    # Store the league_code on managers for identification
    live.league_code = league_code
    live.league_name = league_name
    recent.league_code = league_code
    recent.league_name = league_name
    upcoming.league_code = league_code
    upcoming.league_name = league_name

    return (live, recent, upcoming)

