"""
AFL (Australian Football League) Managers for LEDMatrix

This module provides manager classes for the AFL. AFL is a single-league sport
(ESPN sport slug ``australian-football``, league ``afl``), so unlike the
multi-league soccer plugin this fork was based on, there is exactly one set of
Live/Recent/Upcoming managers.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import pytz

from sports import SportsCore, SportsLive, SportsRecent, SportsUpcoming

# ESPN API base URL for Australian Football (AFL)
ESPN_AFL_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/australian-football"

# ESPN league identifier for the AFL scoreboard endpoint
AFL_LEAGUE_KEY = "afl"

# League display names (single league)
LEAGUE_NAMES = {
    "afl": "AFL",
}


class BaseAflManager(SportsCore):
    """Base class for AFL managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged = False
    _last_warning_time = 0
    _warning_cooldown = 60  # Only log warnings once per minute
    _shared_data = None
    _last_shared_update = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str = AFL_LEAGUE_KEY):
        """
        Initialize base AFL manager.

        Args:
            config: Configuration dictionary
            display_manager: Display manager instance
            cache_manager: Cache manager instance
            league_key: League identifier (always 'afl')
        """
        self.logger = logging.getLogger(f"AFL-{league_key}")
        self.league_key = league_key
        self.league_name = LEAGUE_NAMES.get(league_key, league_key)

        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="afl",  # config key => "afl_scoreboard"
        )

        # Set sport and league for ESPN API (after parent init to avoid overwrite)
        self.sport = "australian-football"
        self.league = league_key

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("afl_recent", False)
        self.upcoming_enabled = display_modes.get("afl_upcoming", False)
        self.live_enabled = display_modes.get("afl_live", False)

        self.logger.info(
            f"Initialized {self.league_name} manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )

    def _fetch_afl_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches game data for the AFL using background threading.
        Returns cached data immediately if available, otherwise starts background fetch.
        """
        now = datetime.now(pytz.utc)

        # Fetch a date range (past 2 weeks to future 2 weeks)
        start_date = now - timedelta(days=14)
        end_date = now + timedelta(days=14)
        date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"

        cache_key = f"afl_schedule_{date_str}"
        url = f"{ESPN_AFL_BASE_URL}/{self.league_key}/scoreboard"

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
                sport="australian-football",
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
        if isinstance(self, AflLiveManager):
            # Live games should fetch only current games, not entire schedule
            return self._fetch_todays_games()
        else:
            # Recent and Upcoming managers should use cached schedule data
            return self._fetch_afl_api_data(use_cache=True)

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from the ESPN AFL API response.

        AFL is played in four quarters (Q1-Q4) with a running clock. ESPN exposes
        the quarter via ``status.period`` (1-4) and the running clock via
        ``status.displayClock``. There is a single running integer ``score`` per
        team (no goals/behinds breakdown for v1).
        """
        details, home_team, away_team, status, situation = self._extract_game_details_common(game_event)
        if details is None or home_team is None or away_team is None or status is None:
            return None

        try:
            period = status.get("period", 0)
            period_text = ""
            status_state = status["type"]["state"]
            status_name = status["type"]["name"]

            if status_state == "halftime" or status_name == "STATUS_HALFTIME":
                # ESPN can set state="in" AND name="STATUS_HALFTIME" together, so
                # this guard precedes the generic "in" branch. AFL halftime is the
                # break after Q2.
                period_text = "HALF"
            elif status_state == "in":
                if period == 0:
                    period_text = "Start"
                elif 1 <= period <= 4:
                    period_text = f"Q{period}"
                elif period >= 5:
                    # Overtime / extra periods (rare, e.g. finals extra time)
                    period_text = f"OT{period - 4}"
                else:
                    period_text = f"Q{period}"
            elif status_state == "post":
                period_text = "Final"
            elif status_state == "pre":
                period_text = details.get("game_time", "")

            # Append the running clock for live games (e.g. "Q3 12:34")
            clock = status.get("displayClock", "")
            if clock and status_state == "in":
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

            self.logger.debug(
                f"Extracted: {details['away_abbr']}@{details['home_abbr']}, "
                f"Status: {status['type']['name']}, Live: {details['is_live']}, "
                f"Final: {details['is_final']}, Upcoming: {details['is_upcoming']}"
            )

            return details
        except Exception as e:
            self.logger.error(
                f"Error extracting game details: {e} from event: {game_event.get('id')}",
                exc_info=True,
            )
            return None


class AflLiveManager(BaseAflManager, SportsLive):
    """Manager for live AFL games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str = AFL_LEAGUE_KEY):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"AFLLive-{league_key}")
        self.logger.info(f"Initialized {self.league_name} LiveManager in live mode")


class AflRecentManager(BaseAflManager, SportsRecent):
    """Manager for recently completed AFL games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str = AFL_LEAGUE_KEY):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"AFLRecent-{league_key}")
        self.logger.info(
            f"Initialized {self.league_name} RecentManager with {len(self.favorite_teams)} favorite teams"
        )


class AflUpcomingManager(BaseAflManager, SportsUpcoming):
    """Manager for upcoming AFL games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str = AFL_LEAGUE_KEY):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"AFLUpcoming-{league_key}")
        self.logger.info(
            f"Initialized {self.league_name} UpcomingManager with {len(self.favorite_teams)} favorite teams"
        )


def create_afl_managers(config, display_manager, cache_manager):
    """Create AFL Live, Recent, and Upcoming managers."""
    return (
        AflLiveManager(config, display_manager, cache_manager, AFL_LEAGUE_KEY),
        AflRecentManager(config, display_manager, cache_manager, AFL_LEAGUE_KEY),
        AflUpcomingManager(config, display_manager, cache_manager, AFL_LEAGUE_KEY),
    )
