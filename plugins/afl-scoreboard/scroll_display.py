"""
Scroll Display Handler for Afl Scoreboard.

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
from pathlib import Path
from typing import Dict, Any, List, Optional

from PIL import Image

LEAGUE_NAMES = {
    'afl': 'AFL',
}

from game_renderer import GameRenderer

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    ScrollHelper = None

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
        "afl-scoreboard: core src.common.sports_scroll not available; "
        "using the bundled legacy scroll display"
    )
else:

    class ScrollDisplay(_ScrollDisplayBase):
        """Afl Scoreboard content on the core scroll engine."""

        # The ladder the legacy _get_scroll_settings walked, same order.
        SCROLL_LEAGUE_KEYS = ()
        SCROLL_CONFIG_KEY = "scroll_mode"

        def scroll_settings_defaults(self):
            # Where this plugin's defaults differ from core's.
            return {
                **super().scroll_settings_defaults(),
                "gap_between_games": 24,
                "min_duration": 30,
                "max_duration": 300,
                "game_card_width": 128,
            }

        def __init__(self, *args, **kwargs):
            # Set before super(): the base calls
            # _load_separator_icons() from its __init__.
            self.plugin_dir = kwargs.pop('plugin_dir', None) or str(Path(__file__).parent)
            super().__init__(*args, **kwargs)
            # The renderer cache the legacy __init__ seeded. prepare_scroll_content
            # was lifted verbatim and opens with `if self._game_renderer is None`,
            # so without these it raises AttributeError on the very first call --
            # and the core base catches exceptions out of prepare_scroll_content,
            # so the only symptom was scroll mode silently rendering nothing.
            self._game_renderer: Optional[GameRenderer] = None
            self._game_renderer_card_width: Optional[int] = None

        def _load_separator_icons(self) -> None:
            """Load league separator icons from assets directory."""
            separator_dir = Path(self.plugin_dir) / "assets" / "separators"

            # Map league keys to separator icon filenames. AFL is single-league,
            # so this never has more than one entry to look up -- if this plugin
            # ships an afl.png under assets/separators/ it'll load below;
            # otherwise the existence check just skips it, same as any other
            # missing icon.
            separator_files = {
                'afl': 'afl.png',
            }

            for league_key, filename in separator_files.items():
                icon_path = separator_dir / filename
                if icon_path.exists():
                    try:
                        icon = Image.open(icon_path).convert('RGBA')
                        # Scale to fit display height if needed
                        if icon.height > self.display_height - 4:
                            scale = (self.display_height - 4) / icon.height
                            new_width = int(icon.width * scale)
                            new_height = int(icon.height * scale)
                            icon = icon.resize((new_width, new_height), Image.LANCZOS)
                        self._separator_icons[league_key] = icon
                        self.logger.debug(f"Loaded {LEAGUE_NAMES[league_key]} separator icon: {icon.size}")
                    except Exception as e:
                        self.logger.error(f"Error loading {LEAGUE_NAMES[league_key]} separator icon: {e}")
                else:
                    self.logger.debug(f"{LEAGUE_NAMES[league_key]} separator icon not found at {icon_path} (will skip separator)")

        def _determine_game_type(self, game: Dict, game_type: str = 'upcoming') -> str:
            """
            Determine the game type from the game's status or flags.

            Checks in order:
            1. Boolean flags (is_live, is_final/is_recent, is_upcoming)
            2. Status state mapping (in/post/pre)
            3. Explicit game_type hint from game dict
            4. Provided game_type parameter as fallback

            Args:
                game: Game dictionary
                game_type: Fallback game type if status is missing or unknown

            Returns:
                Game type: 'live', 'recent', or 'upcoming'
            """
            # First check boolean flags (pipeline game dicts)
            if game.get('is_live'):
                return 'live'
            if game.get('is_final') or game.get('is_recent'):
                return 'recent'
            if game.get('is_upcoming'):
                return 'upcoming'

            # Fall back to status.state mapping (with normalization)
            status = game.get('status')
            if isinstance(status, dict):
                state = status.get('state', '')
                if state == 'in':
                    return 'live'
                elif state == 'post':
                    return 'recent'
                elif state == 'pre':
                    return 'upcoming'

            # Check for explicit game_type hint from game dict
            game_type_hint = game.get('game_type')
            if game_type_hint in ('live', 'recent', 'upcoming'):
                return game_type_hint

            # Return provided fallback if type cannot be determined
            return game_type

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
                leagues: List of leagues in order (e.g., ['eng.1', 'esp.1'])
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
            game_card_width = scroll_settings.get("game_card_width", 128)

            # Reuse the cached renderer (rebuilding it -- and reloading its
            # fonts from disk -- on every call is wasteful); only rebuild if the
            # card width changed, since GameRenderer bakes it in at construction.
            if self._game_renderer is None or self._game_renderer_card_width != game_card_width:
                self._game_renderer = GameRenderer(
                    game_card_width,
                    self.display_height,
                    self.config,
                    logo_cache=self._logo_cache,
                    custom_logger=self.logger
                )
                self._game_renderer_card_width = game_card_width
            renderer = self._game_renderer
            if rankings_cache:
                renderer.set_rankings_cache(rankings_cache)

            # Pre-render all game cards
            content_items: List[Image.Image] = []
            current_league = None
            game_count = 0
            league_counts: Dict[str, int] = {}

            for game in games:
                game_league = game.get("league", "afl")  # Default to AFL if not specified

                # Add league separator if switching leagues OR if this is the first league
                if show_separators:
                    if current_league is None:
                        # First league - add separator
                        separator = self._separator_icons.get(game_league)
                        if separator:
                            sep_img = Image.new('RGB', (separator.width + 8, self.display_height), (0, 0, 0))
                            y_offset = (self.display_height - separator.height) // 2
                            sep_img.paste(separator, (4, y_offset), separator)
                            content_items.append(sep_img)
                            self.logger.debug(f"Added {LEAGUE_NAMES.get(game_league, game_league)} separator icon (first league)")
                    elif game_league != current_league:
                        # Switching leagues - add separator
                        separator = self._separator_icons.get(game_league)
                        if separator:
                            # Create a separator image with proper background
                            sep_img = Image.new('RGB', (separator.width + 8, self.display_height), (0, 0, 0))
                            # Center the separator vertically
                            y_offset = (self.display_height - separator.height) // 2
                            sep_img.paste(separator, (4, y_offset), separator)
                            content_items.append(sep_img)
                            self.logger.debug(f"Added {LEAGUE_NAMES.get(game_league, game_league)} separator icon")

                current_league = game_league

                # Render game card - determine type from game state
                # Use caller's game_type as fallback (if valid), otherwise 'upcoming'
                try:
                    fallback_type = game_type if game_type in ('live', 'recent', 'upcoming') else 'upcoming'
                    individual_game_type = self._determine_game_type(game, fallback_type)
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

            # Set cache_type marker for Vegas mode detection
            # This allows manager to verify the cache is Vegas mixed content vs. single-type
            self.scroll_helper.cache_type = game_type

            # Log what we loaded
            league_summary = ", ".join([f"{LEAGUE_NAMES.get(league, league)}({count})" for league, count in league_counts.items()])
            self.logger.info(
                f"[AFL Scroll] Prepared {game_count} games for scrolling: {league_summary}"
            )
            self.logger.info(
                f"[AFL Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
                f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
            )

            # Reset tracking state
            self._is_scrolling = True
            self._scroll_start_time = time.time()
            self._frame_count = 0
            self._fps_sample_start = time.time()

            return True

        def clear_cache(self) -> None:
            """Clear the scroll cache."""
            if self.scroll_helper:
                self.scroll_helper.clear_cache()
            self._current_games = []
            self._current_game_type = ""
            self._current_leagues = []
            self._vegas_content_items = []
            self._is_scrolling = False


    class ScrollDisplayManager(_ScrollDisplayManagerBase):
        """Afl Scoreboard scroll manager -- everything but the extras below is core."""

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
                True if any scroll display has a cached image ready for display
            """
            for scroll_display in self._scroll_displays.values():
                if hasattr(scroll_display, 'scroll_helper') and scroll_display.scroll_helper:
                    if scroll_display.scroll_helper.cached_image is not None:
                        return True
            return False

