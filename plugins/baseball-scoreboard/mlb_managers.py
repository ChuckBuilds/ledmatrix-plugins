import logging
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional

import pytz

from baseball import Baseball, BaseballLive, BaseballRecent
from sports import SportsUpcoming

# Constants
ESPN_MLB_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
)


class BaseMLBManager(Baseball):
    """Base class for MLB managers with common functionality."""

    # Class variables shared across all MLB manager instances (Live/Recent/Upcoming)
    # so they can share API data and coordinate warning throttling
    _no_data_warning_logged: ClassVar[bool] = False
    _last_warning_time: ClassVar[float] = 0
    _warning_cooldown: ClassVar[int] = 60  # Only log warnings once per minute
    _shared_data: ClassVar[Optional[Dict]] = None
    _last_shared_update: ClassVar[float] = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        self.logger = logging.getLogger("MLB")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="mlb",
        )

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("mlb_recent", False)
        self.upcoming_enabled = display_modes.get("mlb_upcoming", False)
        self.live_enabled = display_modes.get("mlb_live", False)

        self.logger.info(
            f"Initialized MLB manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )
        self.league = "mlb"

    def _fetch_mlb_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches the full season schedule for MLB using background threading.
        Returns cached data immediately if available, otherwise starts background fetch.
        """
        now = datetime.now(pytz.utc)
        season_year = now.year
        # MLB season runs March to November; if before March, use previous year
        if now.month < 3:
            season_year = now.year - 1
        datestring = f"{season_year}0301-{season_year}1101"
        cache_key = f"{self.sport_key}_schedule_{season_year}"

        # Check cache first
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

            # Get background service configuration
            background_config = self.mode_config.get("background_service", {})
            timeout = background_config.get("request_timeout", 30)
            max_retries = background_config.get("max_retries", 3)
            priority = background_config.get("priority", 2)

            # Submit background fetch request
            request_id = self.background_service.submit_fetch_request(
                sport="mlb",
                year=season_year,
                url=ESPN_MLB_SCOREBOARD_URL,
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
                    ESPN_MLB_SCOREBOARD_URL,
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
        return self._fetch_mlb_api_data(use_cache=True)


class MLBLiveManager(BaseMLBManager, BaseballLive):
    """Manager for live MLB games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("MLBLiveManager")

        if self.test_mode:
            # Detailed test game for MLB with baseball-specific fields
            self.current_game = {
                "id": "test001",
                "home_abbr": "NYY",
                "home_id": "123",
                "away_abbr": "BOS",
                "away_id": "456",
                "home_score": "4",
                "away_score": "3",
                "inning": 7,
                "inning_half": "top",
                "balls": 2,
                "strikes": 1,
                "outs": 1,
                "bases_occupied": [True, False, True],
                "home_logo_path": Path(self.logo_dir, "NYY.png"),
                "away_logo_path": Path(self.logo_dir, "BOS.png"),
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
                "is_halftime": False,
                "home_logo_url": "",
                "away_logo_url": "",
                "series_summary": "",
                "status_text": "Top 7th",
            }
            self.live_games = [self.current_game]
            self.logger.info("Initialized MLBLiveManager with test game: BOS @ NYY")
        else:
            self.logger.info("Initialized MLBLiveManager in live mode")

    def _fetch_data(self) -> Optional[Dict]:
        """Live games fetch only today's games, not entire season."""
        return self._fetch_todays_games()


class MLBRecentManager(BaseMLBManager, BaseballRecent):
    """Manager for recently completed MLB games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("MLBRecentManager")
        self.logger.info(
            f"Initialized MLBRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class MLBUpcomingManager(BaseMLBManager, SportsUpcoming):
    """Manager for upcoming MLB games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("MLBUpcomingManager")
        self.logger.info(
            f"Initialized MLBUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )
