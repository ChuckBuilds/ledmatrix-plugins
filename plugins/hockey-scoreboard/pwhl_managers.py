import logging
from pathlib import Path
from typing import Any, Dict

from hockey import HockeyLive
from hockeytech_managers import BaseHockeyTechManager
from sports import SportsRecent, SportsUpcoming


class BasePWHLManager(BaseHockeyTechManager):
    """Base class for Professional Women's Hockey League managers (HockeyTech feed)."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        self.logger = logging.getLogger("PWHL")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="pwhl",
        )
        self.logger.info(
            f"Initialized PWHL manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")


class PWHLLiveManager(BasePWHLManager, HockeyLive):
    """Manager for live PWHL games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("PWHLLiveManager")

        if self.test_mode:
            self.current_game = {
                "id": "pwhl-test",
                "home_abbr": "OTT",
                "away_abbr": "BOS",
                "home_score": "2",
                "away_score": "1",
                "period": 2,
                "period_text": "P2",
                "home_id": "5",
                "away_id": "1",
                "clock": "12:34",
                "home_logo_path": Path(self.logo_dir, "OTT.png"),
                "away_logo_path": Path(self.logo_dir, "BOS.png"),
                "game_time": "7:00 PM",
                "game_date": "Nov 21",
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
            }
            self.live_games = [self.current_game]
            self.logger.info("Initialized PWHLLiveManager with test game: BOS vs OTT")
        else:
            self.logger.info("Initialized PWHLLiveManager in live mode")


class PWHLRecentManager(BasePWHLManager, SportsRecent):
    """Manager for recently completed PWHL games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("PWHLRecentManager")
        self.logger.info(
            f"Initialized PWHLRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class PWHLUpcomingManager(BasePWHLManager, SportsUpcoming):
    """Manager for upcoming PWHL games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
    ):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("PWHLUpcomingManager")
        self.logger.info(
            f"Initialized PWHLUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )
