import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from basketball import Basketball, BasketballLive
from sports import SportsRecent, SportsUpcoming

# Constants
ESPN_NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)


class BaseNBAManager(Basketball):
    """Base class for NBA managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged = False
    _last_warning_time = 0
    _warning_cooldown = 60  # Only log warnings once per minute
    _shared_data = None
    _last_shared_update = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        self.logger = logging.getLogger("NBA")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="nba",
        )

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("nba_recent", False)
        self.upcoming_enabled = display_modes.get("nba_upcoming", False)
        self.live_enabled = display_modes.get("nba_live", False)

        self.logger.info(
            f"Initialized NBA manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )
        self.league = "nba"

    def _fetch_nba_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches the full season schedule for NBA using background threading.
        Returns cached data immediately if available, otherwise starts background fetch.
        """
        now = datetime.now(pytz.utc)
        season_year = now.year
        # NBA season typically runs from October to June
        if now.month < 10:
            season_year = now.year - 1
        datestring = f"{season_year}1001-{season_year+1}0630"
        cache_key = f"{self.sport_key}_schedule_{season_year}"

        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                # Validate cached data structure
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info(f"Using cached schedule for {season_year}")
                    return cached_data
                elif isinstance(cached_data, list):
                    # Handle old cache format (list of events)
                    self.logger.info(
                        f"Using cached schedule for {season_year} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {season_year}: {type(cached_data)}"
                    )
                    # Clear invalid cache
                    self.cache_manager.delete(cache_key)

        # Start background fetch if service is available
        if self.background_service and self.background_enabled:
            self.logger.info(
                f"Starting background fetch for {season_year} season schedule..."
            )

            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for {season_year}: {len(result.data.get('events'))} events"
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
                sport="basketball",
                year=season_year,
                url=ESPN_NBA_SCOREBOARD_URL,
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
                    ESPN_NBA_SCOREBOARD_URL,
                    params={"dates": datestring, "limit": 1000},
                    headers=self.headers,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

                # Cache the data
                self.cache_manager.set(cache_key, data)
                self.logger.info(f"Synchronously fetched {season_year} season schedule")
                return data

            except Exception as e:
                self.logger.error(f"Failed to fetch {season_year} season schedule: {e}")
                return None

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data using shared data mechanism or direct fetch for live."""
        if isinstance(self, NBALiveManager):
            # Live games should fetch only current games, not entire season
            return self._fetch_todays_games()
        else:
            # Recent and Upcoming managers should use cached season data
            return self._fetch_nba_api_data(use_cache=True)


class NBALiveManager(BaseNBAManager, BasketballLive):
    """Manager for live NBA games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NBALiveManager")
        self.logger.info("Initialized NBALiveManager in live mode")


class NBARecentManager(BaseNBAManager, SportsRecent):
    """Manager for recently completed NBA games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NBARecentManager")
        self.logger.info(
            f"Initialized NBARecentManager with {len(self.favorite_teams)} favorite teams"
        )


class NBAUpcomingManager(BaseNBAManager, SportsUpcoming):
    """Manager for upcoming NBA games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NBAUpcomingManager")
        self.logger.info(
            f"Initialized NBAUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )

