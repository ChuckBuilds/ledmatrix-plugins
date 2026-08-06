"""
Scroll Display Handler for Baseball Scoreboard Plugin.

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

try:
    from game_renderer import GameRenderer
except ImportError:
    GameRenderer = None

logger = logging.getLogger(__name__)

try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS

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
        "baseball-scoreboard: core src.common.sports_scroll not available; "
        "using the bundled legacy scroll display"
    )
else:

    class ScrollDisplay(_ScrollDisplayBase):
        """Baseball game cards and separator icons on the core scroll engine."""

        # The ladder the legacy _get_scroll_settings walked, same order.
        SCROLL_LEAGUE_KEYS = ("mlb", "milb", "ncaa_baseball")

        # Paths to league separator icons
        MLB_SEPARATOR_ICON = "assets/sports/mlb_logos/MLB.png"
        MILB_SEPARATOR_ICON = "assets/sports/milb_logos/MiLB.png"
        NCAA_BASEBALL_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_baseball.png"

        def __init__(self, *args, **kwargs):
            # Set before super(): the base calls _load_separator_icons() from
            # its __init__, and this plugin's renderer cache must already exist.
            self._game_renderer = None
            super().__init__(*args, **kwargs)

        def _get_game_renderer(self, game_card_width: int = 128) -> Optional[GameRenderer]:
            """Get or create the cached GameRenderer instance.

            Args:
                game_card_width: Width for each game card. Cached renderer is recreated
                                 if this differs from the current renderer's width.
            """
            if GameRenderer is None:
                self.logger.error("GameRenderer not available")
                return None

            # Recreate renderer if card width changed (e.g. config update)
            if self._game_renderer is None or getattr(self._game_renderer, "display_width", None) != game_card_width:
                self._game_renderer = GameRenderer(
                    game_card_width,
                    self.display_height,
                    self.config,
                    logo_cache=self._logo_cache,
                    custom_logger=self.logger
                )
            return self._game_renderer

        def _load_separator_icon(self, icon_path: str, league_key: str, target_height: int) -> None:
            """
            Load and resize a single league separator icon.

            Args:
                icon_path: Path to the icon file
                league_key: Key to store the icon under in _separator_icons
                target_height: Target height for the resized icon
            """
            if not os.path.exists(icon_path):
                self.logger.warning(f"{league_key.upper()} separator icon not found at {icon_path}")
                return

            try:
                with Image.open(icon_path) as icon:
                    if icon.mode != "RGBA":
                        icon = icon.convert("RGBA")
                    # Resize to fit height while maintaining aspect ratio
                    aspect = icon.width / icon.height
                    new_width = int(target_height * aspect)
                    icon = icon.resize((new_width, target_height), resample=RESAMPLE_FILTER)
                    self._separator_icons[league_key] = icon.copy()
                self.logger.debug(f"Loaded {league_key.upper()} separator icon: {new_width}x{target_height}")
            except OSError:
                self.logger.exception(f"Error loading {league_key.upper()} separator icon")

        def _load_separator_icons(self) -> None:
            """Load and resize league separator icons."""
            separator_height = self.display_height - 4  # Leave some padding

            # Load all league separator icons
            icons_to_load = [
                (self.MLB_SEPARATOR_ICON, "mlb"),
                (self.MILB_SEPARATOR_ICON, "milb"),
                (self.NCAA_BASEBALL_SEPARATOR_ICON, "ncaa_baseball"),
            ]
            for icon_path, league_key in icons_to_load:
                self._load_separator_icon(icon_path, league_key, separator_height)

        def _determine_game_type(self, game: Dict) -> str:
            """
            Determine the game type from the game's status.

            Args:
                game: Game dictionary

            Returns:
                Game type: 'live', 'recent', or 'upcoming'
            """
            if game.get('is_live'):
                return 'live'
            elif game.get('is_final'):
                return 'recent'
            elif game.get('is_upcoming'):
                return 'upcoming'
            else:
                # Default to upcoming if state is unknown
                return 'upcoming'

        def prepare_scroll_content(
            self,
            games: List[Dict],
            game_type: str,
            leagues: List[str],
            rankings_cache: Optional[Dict[str, int]] = None
        ) -> bool:
            """
            Prepare scrolling content from a list of games.

            Args:
                games: List of game dictionaries with league info
                game_type: Type hint ('live', 'recent', 'upcoming', or 'mixed' for mixed types)
                leagues: List of leagues in order (e.g., ['mlb', 'milb', 'ncaa_baseball'])
                rankings_cache: Optional team rankings cache for displaying team rankings

            Returns:
                True if content was prepared successfully, False otherwise
            """
            if not self.scroll_helper:
                self.logger.error("ScrollHelper not available")
                return False

            if not games:
                self.logger.debug("No games to prepare for scrolling")
                self.scroll_helper.clear_cache()
                self._current_games = []
                self._vegas_content_items = []
                self._is_scrolling = False
                return False

            self._current_games = games
            self._current_game_type = game_type
            self._current_leagues = leagues

            # Get scroll settings
            scroll_settings = self._get_scroll_settings()
            gap_between_games = scroll_settings.get("gap_between_games", 48)
            show_separators = scroll_settings.get("show_league_separators", True)
            game_card_width = scroll_settings.get("game_card_width", self.display_width)

            # Get or create cached game renderer; default card width is the full display width
            # so each game card fills the viewport and logos sit at the display edges
            renderer = self._get_game_renderer(game_card_width)

            # Pass rankings cache to renderer if available
            if renderer and rankings_cache:
                renderer.set_rankings_cache(rankings_cache)

            # Pre-render all game cards
            content_items: List[Image.Image] = []
            current_league = None
            game_count = 0
            league_counts: Dict[str, int] = {}

            for game in games:
                game_league = game.get("league", "mlb")  # Default to MLB if not specified

                # Add league separator when entering a new league (first or switching)
                if show_separators and game_league != current_league:
                    separator = self._separator_icons.get(game_league)
                    if separator:
                        # Create a separator image with proper background
                        sep_img = Image.new('RGB', (separator.width + 8, self.display_height), (0, 0, 0))
                        # Center the separator vertically
                        y_offset = (self.display_height - separator.height) // 2
                        sep_img.paste(separator, (4, y_offset), separator)
                        content_items.append(sep_img)
                        context = "at start" if current_league is None else ""
                        self.logger.debug(f"Added {game_league} separator icon {context}".strip())

                current_league = game_league

                # Render game card - determine type from game state
                try:
                    individual_game_type = self._determine_game_type(game)
                    game_img = renderer.render_game_card(game, individual_game_type)

                    # Only pad when card is narrower than the viewport; full-width cards
                    # need no padding or the card becomes wider than the display.
                    # Half the gap each side so Vegas, which stitches its own
                    # items, separates cards by exactly gap_between_games.
                    padding = (0 if game_img.width >= self.display_width
                               else max(4, gap_between_games // 2))
                    padded_width = game_img.width + (padding * 2)
                    padded_img = Image.new('RGB', (padded_width, game_img.height), (0, 0, 0))
                    padded_img.paste(game_img, (padding, 0))

                    content_items.append(padded_img)
                    game_count += 1
                    league_counts[game_league] = league_counts.get(game_league, 0) + 1
                except Exception:
                    self.logger.exception("Error rendering game card")
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
                f"[Baseball Scroll] Prepared {game_count} games for scrolling: {league_summary}"
            )
            self.logger.info(
                f"[Baseball Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
                f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
            )

            # Reset tracking state
            self._is_scrolling = True
            self._scroll_start_time = time.time()
            self._frame_count = 0
            self._fps_sample_start = time.time()

            return True


    class ScrollDisplayManager(_ScrollDisplayManagerBase):
        """Baseball scroll manager -- everything but the extras below is core."""

        display_class = ScrollDisplay

        def prepare_content(
            self,
            games: List[Dict],
            game_type: str,
            leagues: List[str],
            rankings_cache: Dict[str, int] = None
        ) -> bool:
            """
            Render content for one scroll display without making it the active one.

            Vegas mode builds its own combined slate in the background while the
            standalone rotation may be mid-scroll on a different game type. Going
            through prepare_and_display() for that would repoint
            ``_current_game_type``, so the next display_frame() would render the
            Vegas slate instead of the mode the rotation is actually showing.

            Args:
                games: List of game dictionaries
                game_type: Scroll display key to render into
                leagues: List of leagues
                rankings_cache: Optional team rankings cache

            Returns:
                True if content was prepared successfully
            """
            scroll_display = self.get_scroll_display(game_type)
            return scroll_display.prepare_scroll_content(
                games, game_type, leagues, rankings_cache
            )

        def get_dynamic_duration(self, game_type: Optional[str] = None) -> int:
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
                True if any scroll display has a cached image, False otherwise
            """
            for scroll_display in self._scroll_displays.values():
                if hasattr(scroll_display, 'scroll_helper') and scroll_display.scroll_helper:
                    if scroll_display.scroll_helper.cached_image is not None:
                        return True
            return False

        def get_vegas_content_items_for(self, game_type: str) -> list:
            """
            Return the Vegas item list for a single scroll display.

            Vegas mode needs the items from one specific display (the combined
            live/recent/upcoming set), not the union across all of them.
            get_all_vegas_content_items() returns whatever the standalone display
            modes happen to have rendered, which both under-reports (only the last
            rendered mode's games) and can double-count a game that appears in two
            displays.

            Args:
                game_type: Scroll display key, e.g. 'mixed'

            Returns:
                Copy of that display's Vegas items, or an empty list if absent.
            """
            scroll_display = self._scroll_displays.get(game_type)
            if scroll_display is None:
                return []
            return list(getattr(scroll_display, '_vegas_content_items', None) or [])

