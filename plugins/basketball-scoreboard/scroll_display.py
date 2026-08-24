"""
Scroll Display Handler for Basketball Scoreboard.

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

try:
    from game_renderer import GameRenderer
except ImportError:
    GameRenderer = None

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    ScrollHelper = None


logger = logging.getLogger(__name__)

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
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
        "basketball-scoreboard: core src.common.sports_scroll not available; "
        "using the bundled legacy scroll display"
    )
else:

    class ScrollDisplay(_ScrollDisplayBase):
        """Basketball Scoreboard content on the core scroll engine."""

        # The ladder the legacy _get_scroll_settings walked, same order.
        SCROLL_LEAGUE_KEYS = ("nba", "wnba", "ncaam", "ncaaw")

        # Paths to league separator icons. These must live on THIS class, not
        # only on the legacy one: _load_separator_icons below was lifted verbatim
        # and reads them off self, and the core base calls it from __init__ --
        # so a missing constant is not a degraded icon, it is an AttributeError
        # that stops the scroll display being constructed at all.
        NBA_SEPARATOR_ICON = "assets/sports/nba_logos/NBA.png"
        WNBA_SEPARATOR_ICON = "assets/sports/wnba_logos/WNBA.png"
        NCAA_SEPARATOR_ICON = "assets/sports/ncaa_logos/NCAA.png"  # Generic NCAA logo, or use league-specific if available
        MARCH_MADNESS_SEPARATOR_ICON = "assets/sports/ncaa_logos/MARCH_MADNESS.png"


        def _default_game_card_width(self) -> int:
            """Card width that fits two full-height logos and the score.

            The card was a flat 128px whatever the panel was, so each logo got
            (128 - gap) / 2 = 46px and stayed there -- 46px of logo in a
            128-tall card, with the rest dead space. Sizing the card as "two
            full-height logos plus the measured gap" makes the height the
            binding constraint instead.

            The gap is measured with a throwaway renderer because the score's
            font comes from config, not from the card size, so asking for it
            before the width is settled is not circular. A 32-tall panel keeps
            the 128 it has always had.
            """
            try:
                probe = GameRenderer(128, self.display_height, self.config)
                gap = probe._center_gap_width()
            except Exception:
                self.logger.debug("Card width probe failed; keeping 128",
                                  exc_info=True)
                return 128
            return max(128, self.display_height * 2 + gap)


        #: The schema declares game_card_width: 128 for every league, and the
        #: web UI writes the whole schema block on every save, so nearly every
        #: real config carries it whether or not anyone chose it. Honouring it
        #: as an override pins the card at 128 forever -- and since the centre
        #: gap is now sized from the score, that SHRINKS the logos rather than
        #: just declining the improvement. Equal to the schema default means
        #: unchosen, the same rule the fonts use.
        _SCHEMA_CARD_WIDTH = 128

        def _get_scroll_settings(self, league=None):
            settings = super()._get_scroll_settings(league)
            if settings.get("game_card_width") == self._SCHEMA_CARD_WIDTH:
                settings = {**settings,
                            "game_card_width": self._default_game_card_width()}
            return settings

        def scroll_settings_defaults(self):
            # Where this plugin's defaults differ from core's.
            return {
                **super().scroll_settings_defaults(),
                "game_card_width": self._default_game_card_width(),
            }

        def _load_separator_icon(
            self,
            icon_path: str,
            league_keys: List[str],
            separator_height: int,
            display_name: str
        ) -> None:
            """
            Load and resize a single separator icon.

            Args:
                icon_path: Path to the icon file
                league_keys: List of league keys to associate with this icon
                separator_height: Target height for the icon
                display_name: Name for logging purposes
            """
            if not os.path.exists(icon_path):
                self.logger.warning(f"{display_name} separator icon not found at {icon_path}")
                return

            try:
                with Image.open(icon_path) as icon:
                    if icon.mode != "RGBA":
                        icon = icon.convert("RGBA")
                    # Resize to fit height while maintaining aspect ratio
                    aspect = icon.width / icon.height
                    new_width = int(separator_height * aspect)
                    resized_icon = icon.resize((new_width, separator_height), resample=RESAMPLE_FILTER)
                    # Store for each league key
                    for key in league_keys:
                        self._separator_icons[key] = resized_icon
                    self.logger.debug(f"Loaded {display_name} separator icon: {new_width}x{separator_height}")
            except Exception:
                self.logger.exception(f"Error loading {display_name} separator icon")

        def _load_separator_icons(self) -> None:
            """Load and resize league separator icons."""
            separator_height = self.display_height - 4  # Leave some padding

            # Load all separator icons using helper
            self._load_separator_icon(
                self.NBA_SEPARATOR_ICON, ["nba"], separator_height, "NBA"
            )
            self._load_separator_icon(
                self.WNBA_SEPARATOR_ICON, ["wnba"], separator_height, "WNBA"
            )
            self._load_separator_icon(
                self.NCAA_SEPARATOR_ICON, ["ncaam", "ncaaw"], separator_height, "NCAA"
            )
            # March Madness tournament separator (used when tournament games are detected)
            self._load_separator_icon(
                self.MARCH_MADNESS_SEPARATOR_ICON,
                ["ncaam_tournament", "ncaaw_tournament"],
                separator_height,
                "March Madness",
            )

        def _determine_game_type(self, game: Dict) -> str:
            """
            Determine the game type from the game's status.

            Args:
                game: Game dictionary (flat format from sports.py)

            Returns:
                Game type: 'live', 'recent', or 'upcoming'
            """
            # Use flat game dict flags from sports.py
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
            rankings_cache: Dict[str, int] = None
        ) -> bool:
            """
            Prepare scrolling content from a list of games.

            Args:
                games: List of game dictionaries with league info
                game_type: Type hint ('live', 'recent', 'upcoming', or 'mixed' for mixed types)
                leagues: List of leagues in order (e.g., ['nba', 'wnba', 'ncaam'])
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

            # Verify GameRenderer is available
            if GameRenderer is None:
                self.logger.error("GameRenderer not available - cannot prepare scroll content")
                return False

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
                game_league = game.get("league", "nba")  # Default to NBA if not specified

                # Use March Madness separator for tournament games
                separator_key = game_league
                if game.get("is_tournament") and game_league in ("ncaam", "ncaaw"):
                    tournament_key = f"{game_league}_tournament"
                    if tournament_key in self._separator_icons:
                        separator_key = tournament_key

                # Add league separator if switching leagues OR if this is the first league
                if show_separators:
                    if current_league is None:
                        # First league - add separator at the start
                        separator = self._separator_icons.get(separator_key)
                        if separator:
                            # Create a separator image with proper background
                            sep_img = Image.new('RGB', (separator.width + sep_pad * 2, self.display_height), (0, 0, 0))
                            # Center the separator vertically
                            y_offset = (self.display_height - separator.height) // 2
                            sep_img.paste(separator, (sep_pad, y_offset), separator)
                            content_items.append(sep_img)
                            self.logger.debug(f"Added {separator_key} separator icon at start")
                    elif separator_key != current_league:
                        # Switching leagues or switching between regular/tournament - add separator
                        separator = self._separator_icons.get(separator_key)
                        if separator:
                            # Create a separator image with proper background
                            sep_img = Image.new('RGB', (separator.width + sep_pad * 2, self.display_height), (0, 0, 0))
                            # Center the separator vertically
                            y_offset = (self.display_height - separator.height) // 2
                            sep_img.paste(separator, (sep_pad, y_offset), separator)
                            content_items.append(sep_img)
                            self.logger.debug(f"Added {separator_key} separator icon")

                current_league = separator_key

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
                f"[Basketball Scroll] Prepared {game_count} games for scrolling: {league_summary}"
            )
            self.logger.info(
                f"[Basketball Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
                f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
            )
        
            # Reset tracking state
            self._is_scrolling = True
            self._scroll_start_time = time.time()
            self._frame_count = 0
            self._fps_sample_start = time.time()
        
            return True


    class ScrollDisplayManager(_ScrollDisplayManagerBase):
        """Basketball Scoreboard scroll manager -- everything but the extras below is core."""

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

