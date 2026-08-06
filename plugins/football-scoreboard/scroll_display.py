"""
Scroll Display Handler for Football Scoreboard Plugin.

Orchestration (scroll-helper configuration, frame pumping, completion,
settings resolution, `global_config['target_fps']`) comes from the core's
`src.common.sports_scroll`, shipped in LEDMatrix 3.2.0. Only the *content*
half lives here: building this sport's game cards and separator icons.

On a core that predates that module we fall back to `scroll_display_legacy`,
the previous self-contained implementation, so the plugin keeps working
unchanged. That fallback is why this plugin is safe to adopt core code ahead
of the B6 sunset -- the version floor alone does not protect users whose core
misreports its version (the v3.1.0 release reports "1.0.0"), and they would
otherwise get a plugin that fails to load.

The content methods below are duplicated in the legacy module by design: it is
frozen, and deleting it at B6 leaves this file as the only copy. Fix bugs
here, not there.
"""

import logging
import os
import time
from typing import Dict, Any, List, Optional

from PIL import Image

from game_renderer import GameRenderer

logger = logging.getLogger(__name__)

_USING_CORE_SCROLL = False
try:
    from src.common.sports_scroll import (
        SportsScrollDisplay as _ScrollDisplayBase,
        SportsScrollDisplayManager as _ScrollDisplayManagerBase,
    )
    _USING_CORE_SCROLL = True
except ModuleNotFoundError as exc:
    # Fall back only when the CORE module is absent. A bare `except
    # ImportError` would also swallow a failure raised *inside* a core module
    # that is present, silently loading the legacy copy and hiding a broken
    # core install.
    if exc.name not in {"src", "src.common", "src.common.sports_scroll"}:
        raise
    _ScrollDisplayBase = None
    _ScrollDisplayManagerBase = None


if not _USING_CORE_SCROLL:
    # Pre-3.2.0 core: use the previous implementation wholesale.
    from scroll_display_legacy import (  # noqa: F401
        LegacyScrollDisplay as ScrollDisplay,
        LegacyScrollDisplayManager as ScrollDisplayManager,
    )
    logger.info(
        "football-scoreboard: core src.common.sports_scroll not available; "
        "using the bundled legacy scroll display"
    )
else:

    class ScrollDisplay(_ScrollDisplayBase):
        """Football game cards and separator icons on the core scroll engine."""

        # The ladder the legacy _get_scroll_settings walked, same order.
        SCROLL_LEAGUE_KEYS = ("nfl", "ncaa_fb")

        NFL_SEPARATOR_ICON = "assets/sports/nfl_logos/NFL.png"
        NCAA_FB_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_fb.png"

        def scroll_settings_defaults(self):
            # Core sizes game cards to the panel; this plugin has always
            # pinned them at 128px, and the byte-identical harness gate
            # depends on keeping that.
            return {**super().scroll_settings_defaults(), "game_card_width": 128}

        def _load_separator_icons(self) -> None:
            """Load and resize league separator icons."""
            separator_height = self.display_height - 4  # Leave some padding
        
            # Load NFL icon
            if os.path.exists(self.NFL_SEPARATOR_ICON):
                try:
                    nfl_icon = Image.open(self.NFL_SEPARATOR_ICON)
                    if nfl_icon.mode != "RGBA":
                        nfl_icon = nfl_icon.convert("RGBA")
                    # Resize to fit height while maintaining aspect ratio
                    aspect = nfl_icon.width / nfl_icon.height
                    new_width = int(separator_height * aspect)
                    nfl_icon = nfl_icon.resize((new_width, separator_height), Image.Resampling.LANCZOS)
                    self._separator_icons["nfl"] = nfl_icon
                    self.logger.debug(f"Loaded NFL separator icon: {new_width}x{separator_height}")
                except Exception as e:
                    self.logger.error(f"Error loading NFL separator icon: {e}")
            else:
                self.logger.warning(f"NFL separator icon not found at {self.NFL_SEPARATOR_ICON}")
        
            # Load NCAA FB icon
            if os.path.exists(self.NCAA_FB_SEPARATOR_ICON):
                try:
                    ncaa_icon = Image.open(self.NCAA_FB_SEPARATOR_ICON)
                    if ncaa_icon.mode != "RGBA":
                        ncaa_icon = ncaa_icon.convert("RGBA")
                    # Resize to fit height while maintaining aspect ratio
                    aspect = ncaa_icon.width / ncaa_icon.height
                    new_width = int(separator_height * aspect)
                    ncaa_icon = ncaa_icon.resize((new_width, separator_height), Image.Resampling.LANCZOS)
                    self._separator_icons["ncaa_fb"] = ncaa_icon
                    self.logger.debug(f"Loaded NCAA FB separator icon: {new_width}x{separator_height}")
                except Exception as e:
                    self.logger.error(f"Error loading NCAA FB separator icon: {e}")
            else:
                self.logger.warning(f"NCAA FB separator icon not found at {self.NCAA_FB_SEPARATOR_ICON}")

        def _determine_game_type(self, game: Dict) -> str:
            """
            Determine the game type from the game's status.

            Args:
                game: Game dictionary

            Returns:
                Game type: 'live', 'recent', or 'upcoming'
            """
            # Guard against status being None or non-dict
            status = game.get('status')
            if not isinstance(status, dict):
                status = {}
            state = status.get('state', '')
            if state == 'in':
                return 'live'
            elif state == 'post':
                return 'recent'
            elif state == 'pre':
                return 'upcoming'
            else:
                # Default to upcoming if state is unknown
                return 'upcoming'

        def prepare_scroll_content(
            self,
            games: List[Dict],
            game_type: str,
            leagues: List[str],
            rankings_cache: Dict[str, int] = None
        ) -> bool:
            """
            Prepare scrolling content from a list of games.

            Args:
                games: List of game dictionaries with league info
                game_type: Type hint ('live', 'recent', 'upcoming', or 'mixed' for mixed types)
                leagues: List of leagues in order (e.g., ['nfl', 'ncaa_fb'])
                rankings_cache: Optional team rankings cache

            Returns:
                True if content was prepared successfully, False otherwise
            """
            if not self.scroll_helper:
                self.logger.error("ScrollHelper not available")
                return False

            if not games:
                self.logger.debug("No games to prepare for scrolling")
                self.scroll_helper.clear_cache()
                self._vegas_content_items = []
                return False

            self._current_games = games
            self._current_game_type = game_type
            self._current_leagues = leagues

            # Get scroll settings
            scroll_settings = self._get_scroll_settings()
            gap_between_games = scroll_settings.get("gap_between_games", 48)
            show_separators = scroll_settings.get("show_league_separators", True)
            # Match the gap used between game cards so the leading league
            # icon sits in the same rhythm as the cards that follow it.
            sep_pad = max(4, gap_between_games // 2)
            game_card_width = scroll_settings.get("game_card_width", 128)

            # Create game renderer using game_card_width so cards are a fixed size
            # regardless of the full chain width (display_width may span multiple panels)
            renderer = GameRenderer(
                game_card_width,
                self.display_height,
                self.config,
                logo_cache=self._logo_cache,
                custom_logger=self.logger
            )
            if rankings_cache:
                renderer.set_rankings_cache(rankings_cache)

            # Pre-render all game cards
            content_items: List[Image.Image] = []
            current_league = None
            game_count = 0
            league_counts: Dict[str, int] = {}

            for game in games:
                game_league = game.get("league", "nfl")  # Default to NFL if not specified

                # Add league separator if switching leagues OR if this is the first league
                if show_separators:
                    if current_league is None:
                        # First league - add separator at the start
                        separator = self._separator_icons.get(game_league)
                        if separator:
                            # Create a separator image with proper background
                            sep_img = Image.new('RGB', (separator.width + sep_pad * 2, self.display_height), (0, 0, 0))
                            # Center the separator vertically
                            y_offset = (self.display_height - separator.height) // 2
                            sep_img.paste(separator, (sep_pad, y_offset), separator)
                            content_items.append(sep_img)
                            self.logger.debug(f"Added {game_league} separator icon at start")
                    elif game_league != current_league:
                        # Switching leagues - add separator
                        separator = self._separator_icons.get(game_league)
                        if separator:
                            # Create a separator image with proper background
                            sep_img = Image.new('RGB', (separator.width + sep_pad * 2, self.display_height), (0, 0, 0))
                            # Center the separator vertically
                            y_offset = (self.display_height - separator.height) // 2
                            sep_img.paste(separator, (sep_pad, y_offset), separator)
                            content_items.append(sep_img)
                            self.logger.debug(f"Added {game_league} separator icon")

                current_league = game_league

                # Render game card - determine type from game state
                try:
                    individual_game_type = self._determine_game_type(game)
                    game_img = renderer.render_game_card(game, individual_game_type)
                
                    # Add horizontal padding to prevent logos from being cut off at edges
                    # Logos are positioned at -10 and display_width+10, so we need padding
                    # Half the gap each side, so adjacent cards are separated by exactly
                    # gap_between_games. Baking it into the card matters for Vegas, which
                    # stitches its own items and never sees the scroll helper item_gap.
                    padding = max(4, gap_between_games // 2)
                    padded_width = game_img.width + (padding * 2)
                    padded_img = Image.new('RGB', (padded_width, game_img.height), (0, 0, 0))
                    padded_img.paste(game_img, (padding, 0))
                
                    content_items.append(padded_img)
                    game_count += 1
                    league_counts[game_league] = league_counts.get(game_league, 0) + 1
                except Exception as e:
                    self.logger.error(f"Error rendering game card: {e}")
                    continue
        
            if not content_items:
                self.logger.warning("No game cards rendered")
                return False
        
            # Store individual items for Vegas mode (avoids scroll_helper padding)
            self._vegas_content_items = list(content_items)

            # Create scrolling image using ScrollHelper
            self.scroll_helper.create_scrolling_image(
                content_items,
                item_gap=0,  # spacing already baked into each card
                element_gap=0  # No element gap - each item is a complete game card
            )

            # Log what we loaded
            league_summary = ", ".join([f"{league.upper()}({count})" for league, count in league_counts.items()])
            self.logger.info(
                f"[Football Scroll] Prepared {game_count} games for scrolling: {league_summary}"
            )
            self.logger.info(
                f"[Football Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
                f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
            )
        
            # Reset tracking state
            self._is_scrolling = True
            self._scroll_start_time = time.time()
            self._frame_count = 0
            self._fps_sample_start = time.time()
        
            return True


    class ScrollDisplayManager(_ScrollDisplayManagerBase):
        """Football scroll manager -- everything but the extras below is core."""

        display_class = ScrollDisplay

        def get_dynamic_duration(self, game_type: str = None) -> int:
            """Get the dynamic duration for the current scroll."""
            if game_type is None:
                game_type = self._current_game_type

            if game_type is None:
                return 60

            scroll_display = self._scroll_displays.get(game_type)
            if scroll_display is None:
                return 60

            return scroll_display.get_dynamic_duration()

        def has_cached_content(self) -> bool:
            """
            Check if any scroll display has cached content.

            Returns:
                True if at least one scroll display has a cached image
            """
            for scroll_display in self._scroll_displays.values():
                if hasattr(scroll_display, 'scroll_helper') and scroll_display.scroll_helper:
                    if scroll_display.scroll_helper.cached_image is not None:
                        return True
            return False

