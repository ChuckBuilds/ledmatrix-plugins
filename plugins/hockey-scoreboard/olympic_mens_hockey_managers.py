import logging
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional

import pytz

from hockey import Hockey, HockeyLive
from sports import SportsRecent, SportsUpcoming

# Constants
ESPN_OLYMPIC_MENS_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/olympics-mens-ice-hockey/scoreboard"


class BaseOlympicMensHockeyManager(Hockey):
    """Base class for Olympic Men's Ice Hockey managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged: ClassVar[bool] = False
    _last_warning_time: ClassVar[float] = 0
    _warning_cooldown: ClassVar[int] = 60  # Only log warnings once per minute
    _shared_data: ClassVar[Optional[Dict]] = None
    _last_shared_update: ClassVar[float] = 0
    _processed_games_cache: ClassVar[Dict] = {}  # Cache for processed game data
    _processed_games_timestamp: ClassVar[float] = 0

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        self.logger = logging.getLogger("OlympicMensHockey")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="olympic_mens_hockey",
        )

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("hockey_recent", False)
        self.upcoming_enabled = display_modes.get("hockey_upcoming", False)
        self.live_enabled = display_modes.get("hockey_live", False)
        self.league = "olympics-mens-ice-hockey"

        self.logger.info(
            f"Initialized OlympicMensHockey manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )

    def _fetch_olympic_hockey_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches the Olympic Men's hockey schedule, caches it, and then filters
        for relevant games based on the current configuration.
        """
        now = datetime.now(pytz.utc)
        year = now.year
        # Olympic hockey window: early Feb to late Feb
        datestring = f"{year}0201-{year}0301"
        cache_key = f"olympic_mens_hockey_schedule_{year}"

        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info(f"Using cached Olympic Men's schedule for {year}")
                    return cached_data
                elif isinstance(cached_data, list):
                    self.logger.info(
                        f"Using cached Olympic Men's schedule for {year} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {year}: {type(cached_data)}"
                    )
                    self.cache_manager.clear_cache(cache_key)

        self.logger.info(f"Fetching Olympic Men's {year} schedule from ESPN API...")

        def fetch_callback(result):
            """Callback when background fetch completes."""
            if result.success:
                self.logger.info(
                    f"Background fetch completed for Olympic Men's {year}: {len(result.data.get('events', []))} events"
                )
            else:
                self.logger.error(
                    f"Background fetch failed for Olympic Men's {year}: {result.error}"
                )
            if year in self.background_fetch_requests:
                del self.background_fetch_requests[year]

        background_config = self.mode_config.get("background_service", {})
        timeout = background_config.get("request_timeout", 30)
        max_retries = background_config.get("max_retries", 3)
        priority = background_config.get("priority", 2)

        request_id = self.background_service.submit_fetch_request(
            sport="olympic_mens_hockey",
            year=year,
            url=ESPN_OLYMPIC_MENS_SCOREBOARD_URL,
            cache_key=cache_key,
            params={"dates": datestring, "limit": 1000},
            headers=self.headers,
            timeout=timeout,
            max_retries=max_retries,
            priority=priority,
            callback=fetch_callback,
        )

        self.background_fetch_requests[year] = request_id

        partial_data = self._get_weeks_data()
        if partial_data:
            return partial_data
        return None

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data using shared data mechanism or direct fetch for live."""
        if isinstance(self, OlympicMensHockeyLiveManager):
            return self._fetch_todays_games()
        else:
            return self._fetch_olympic_hockey_api_data(use_cache=True)


class OlympicMensHockeyLiveManager(BaseOlympicMensHockeyManager, HockeyLive):
    """Manager for live Olympic Men's Ice Hockey games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("OlympicMensHockeyLiveManager")

        if self.test_mode:
            self.current_game = {
                "id": "401845663",
                "home_abbr": "USA",
                "away_abbr": "CAN",
                "home_score": "3",
                "away_score": "2",
                "period": 2,
                "period_text": "P2",
                "home_id": "1",
                "away_id": "16",
                "clock": "12:34",
                "home_logo_path": Path(self.logo_dir, "USA.png"),
                "away_logo_path": Path(self.logo_dir, "CAN.png"),
                "game_time": "7:30 PM",
                "game_date": "Feb 18",
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
            }
            self.live_games = [self.current_game]
            self.logger.info(
                "Initialized OlympicMensHockeyLiveManager with test game: USA vs CAN"
            )
        else:
            self.logger.info("Initialized OlympicMensHockeyLiveManager in live mode")


class OlympicMensHockeyRecentManager(BaseOlympicMensHockeyManager, SportsRecent):
    """Manager for recently completed Olympic Men's Ice Hockey games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("OlympicMensHockeyRecentManager")
        self.logger.info(
            f"Initialized OlympicMensHockeyRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class OlympicMensHockeyUpcomingManager(BaseOlympicMensHockeyManager, SportsUpcoming):
    """Manager for upcoming Olympic Men's Ice Hockey games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("OlympicMensHockeyUpcomingManager")
        self.logger.info(
            f"Initialized OlympicMensHockeyUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )
