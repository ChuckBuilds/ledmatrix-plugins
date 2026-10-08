import logging
from pathlib import Path
from typing import Any, Dict

from hockey import HockeyLive
from hockeytech_managers import BaseHockeyTechManager
from sports import SportsRecent, SportsUpcoming


class BaseOHLManager(BaseHockeyTechManager):
    """Base class for Ontario Hockey League managers (HockeyTech feed)."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        self.logger = logging.getLogger("OHL")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="ohl",
        )
        self.logger.info(
            f"Initialized OHL manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")


class OHLLiveManager(BaseOHLManager, HockeyLive):
    """Manager for live OHL games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("OHLLiveManager")

        if self.test_mode:
            self.current_game = {
                "id": "ohl-test",
                "home_abbr": "LDN",
                "away_abbr": "OS",
                "home_score": "3",
                "away_score": "2",
                "period": 2,
                "period_text": "P2",
                "home_id": "14",
                "away_id": "11",
                "clock": "12:34",
                "home_logo_path": Path(self.logo_dir, "LDN.png"),
                "away_logo_path": Path(self.logo_dir, "OS.png"),
                "game_time": "7:00 PM",
                "game_date": "Oct 9",
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
            }
            self.live_games = [self.current_game]
            self.logger.info("Initialized OHLLiveManager with test game: OS vs LDN")
        else:
            self.logger.info("Initialized OHLLiveManager in live mode")


class OHLRecentManager(BaseOHLManager, SportsRecent):
    """Manager for recently completed OHL games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("OHLRecentManager")
        self.logger.info(
            f"Initialized OHLRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class OHLUpcomingManager(BaseOHLManager, SportsUpcoming):
    """Manager for upcoming OHL games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("OHLUpcomingManager")
        self.logger.info(
            f"Initialized OHLUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )
