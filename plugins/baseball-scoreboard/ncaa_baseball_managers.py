import logging
from typing import ClassVar, Dict, Any, Optional
from datetime import datetime
import pytz
from baseball import Baseball, BaseballLive, BaseballRecent
from sports import SportsUpcoming
from pathlib import Path

# Constants
ESPN_NCAA_BASEBALL_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard"


class BaseNCAABaseballManager(Baseball):
    """Base class for NCAA Baseball managers with common functionality."""

    # Class variables shared across all NCAA Baseball manager instances (Live/Recent/Upcoming)
    # so they can share API data and coordinate warning throttling
    _no_data_warning_logged: ClassVar[bool] = False
    _last_warning_time: ClassVar[float] = 0
    _warning_cooldown: ClassVar[int] = 60  # Only log warnings once per minute
    _shared_data: ClassVar[Optional[Dict]] = None
    _last_shared_update: ClassVar[float] = 0
    _processed_games_cache: ClassVar[Dict] = {}  # Cache for processed game data
    _processed_games_timestamp: ClassVar[float] = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        self.logger = logging.getLogger("NCAABaseball")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="ncaa_baseball",
        )

        # Configuration is already set in base class
        # self.logo_dir and self.update_interval are already configured

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("ncaa_baseball_recent", False)
        self.upcoming_enabled = display_modes.get("ncaa_baseball_upcoming", False)
        self.live_enabled = display_modes.get("ncaa_baseball_live", False)
        self.league = "college-baseball"

        self.logger.info(
            f"Initialized NCAA Baseball manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )

    def _fetch_ncaa_baseball_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches the full season schedule for NCAA Baseball using date range approach to ensure
        we get all games, then caches the complete dataset.

        This method now uses background threading to prevent blocking the display.
        """
        now = datetime.now(pytz.utc)
        season_year = now.year
        if now.month < 2:
            season_year = now.year - 1
        datestring = f"{season_year}0201-{season_year}0701"
        cache_key = f"ncaa_baseball_schedule_{season_year}"

        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                # Validate cached data structure
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.debug(f"Using cached schedule for {season_year}")
                    return cached_data
                elif isinstance(cached_data, list):
                    # Handle old cache format (list of events)
                    self.logger.debug(
                        f"Using cached schedule for {season_year} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {season_year}: {type(cached_data)}"
                    )
                    # Clear invalid cache
                    self.cache_manager.clear_cache(cache_key)

        self.logger.info(
            f"Fetching full {season_year} season schedule from ESPN API..."
        )

        # Get background service configuration
        background_config = self.mode_config.get("background_service", {})
        timeout = background_config.get("request_timeout", 30)
        max_retries = background_config.get("max_retries", 3)
        priority = background_config.get("priority", 2)

        # Start background fetch if service is available
        if self.background_service and self.background_enabled:
            # Skip if a fetch is already in progress for this season
            if season_year in self.background_fetch_requests:
                self.logger.debug(
                    f"Background fetch already in progress for {season_year}"
                )
                partial_data = self._get_weeks_data()
                return partial_data

            self.logger.info(
                f"Starting background fetch for {season_year} season schedule..."
            )

            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for {season_year}: {len(result.data.get('events', []))} events"
                    )
                else:
                    self.logger.error(
                        f"Background fetch failed for {season_year}: {result.error}"
                    )

                # Clean up request tracking
                if season_year in self.background_fetch_requests:
                    del self.background_fetch_requests[season_year]

            # Submit background fetch request
            request_id = self.background_service.submit_fetch_request(
                sport="ncaa_baseball",
                year=season_year,
                url=ESPN_NCAA_BASEBALL_SCOREBOARD_URL,
                cache_key=cache_key,
                params={"dates": datestring, "limit": 1000},
                headers=self.headers,
                timeout=timeout,
                max_retries=max_retries,
                priority=priority,
                callback=fetch_callback,
            )

            # Track the request
            self.background_fetch_requests[season_year] = request_id

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
                    ESPN_NCAA_BASEBALL_SCOREBOARD_URL,
                    params={"dates": datestring, "limit": 1000},
                    headers=self.headers,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

                # Cache the data with 4-hour TTL so it refreshes periodically
                self.cache_manager.set(cache_key, data, ttl=14400)
                self.logger.info(f"Synchronously fetched {season_year} season schedule")
                return data

            except Exception as e:
                self.logger.error(f"Failed to fetch {season_year} season schedule: {e}")
                return None

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch cached season data. Subclasses may override."""
        return self._fetch_ncaa_baseball_api_data(use_cache=True)


class NCAABaseballLiveManager(BaseNCAABaseballManager, BaseballLive):
    """Manager for live NCAA Baseball games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(
            config=config, display_manager=display_manager, cache_manager=cache_manager
        )
        self.logger = logging.getLogger("NCAABaseballLiveManager")

        if self.test_mode:
            # More detailed test game for NCAA Baseball
            self.current_game = {
                "id": "testNCAABB001",
                "home_id": "2633",
                "away_id": "2579",
                "home_abbr": "LSU",
                "away_abbr": "MISS",
                "home_score": "5",
                "away_score": "3",
                "inning": 7,
                "inning_half": "bottom",
                "balls": 2,
                "strikes": 1,
                "outs": 1,
                "bases_occupied": [True, False, True],
                "home_logo_path": Path(self.logo_dir, "LSU.png"),
                "away_logo_path": Path(self.logo_dir, "MISS.png"),
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
                "is_halftime": False,
                "home_logo_url": "",
                "away_logo_url": "",
                "status_text": "Bot 7th",
                "series_summary": "",
                "has_count_data": False,
            }
            self.live_games = [self.current_game]
            self.logger.info(
                "Initialized NCAABaseballLiveManager with test game: MISS vs LSU"
            )
        else:
            self.logger.info(
                "Initialized NCAABaseballLiveManager in live mode"
            )

    def _fetch_data(self) -> Optional[Dict]:
        """Live games fetch only today's games, not entire season."""
        return self._fetch_todays_games()


class NCAABaseballRecentManager(BaseNCAABaseballManager, BaseballRecent):
    """Manager for recently completed NCAA Baseball games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NCAABaseballRecentManager")
        self.logger.info(
            f"Initialized NCAABaseballRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class NCAABaseballUpcomingManager(BaseNCAABaseballManager, SportsUpcoming):
    """Manager for upcoming NCAA Baseball games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NCAABaseballUpcomingManager")
        self.logger.info(
            f"Initialized NCAABaseballUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )
