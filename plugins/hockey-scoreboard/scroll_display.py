"""
Scroll Display Handler for Hockey Scoreboard.

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

from game_renderer import GameRenderer

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
        "hockey-scoreboard: core src.common.sports_scroll not available; "
        "using the bundled legacy scroll display"
    )
else:

    class ScrollDisplay(_ScrollDisplayBase):
        """Hockey Scoreboard content on the core scroll engine."""

        # The ladder the legacy _get_scroll_settings walked, same order.
        SCROLL_LEAGUE_KEYS = ("nhl", "ncaa_mens", "ncaam_hockey", "ncaa_womens", "ncaaw_hockey")

        # Paths to league separator icons. These must live on THIS class, not
        # only on the legacy one: _load_separator_icons below was lifted verbatim
        # and reads them off self, and the core base calls it from __init__ --
        # so a missing constant is not a degraded icon, it is an AttributeError
        # that stops the scroll display being constructed at all.
        NHL_SEPARATOR_ICON = "assets/sports/nhl_logos/NHL.png"
        NCAA_SEPARATOR_ICON = "assets/sports/ncaa_logos/NCAA.png"
        NCAAM_HOCKEY_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_hockey.png"
        NCAAW_HOCKEY_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_hockey.png"


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

        def scroll_settings_defaults(self):
            # Where this plugin's defaults differ from core's.
            return {
                **super().scroll_settings_defaults(),
                "game_card_width": self._default_game_card_width(),
            }

        def _load_separator_icons(self) -> None:
            """Load and resize league separator icons."""
            separator_height = self.display_height - 4  # Leave some padding

            # Load NHL icon
            if os.path.exists(self.NHL_SEPARATOR_ICON):
                try:
                    # Use context manager to ensure file handle is closed
                    with Image.open(self.NHL_SEPARATOR_ICON) as nhl_file:
                        # Convert creates a copy; if already RGBA, use copy() to detach from file
                        if nhl_file.mode != "RGBA":
                            nhl_icon = nhl_file.convert("RGBA")
                        else:
                            nhl_icon = nhl_file.copy()
                    # Resize to fit height while maintaining aspect ratio (after file is closed)
                    aspect = nhl_icon.width / nhl_icon.height
                    new_width = int(separator_height * aspect)
                    nhl_icon = nhl_icon.resize((new_width, separator_height), resample=RESAMPLE_FILTER)
                    self._separator_icons["nhl"] = nhl_icon
                    self.logger.debug(f"Loaded NHL separator icon: {new_width}x{separator_height}")
                except Exception:
                    self.logger.exception("Error loading NHL separator icon")
            else:
                self.logger.warning(f"NHL separator icon not found at {self.NHL_SEPARATOR_ICON}")

            # Load NCAA icon (try sport-specific first, then generic)
            ncaa_icon_paths = [
                (self.NCAAM_HOCKEY_SEPARATOR_ICON, ["ncaam_hockey", "ncaa_mens"]),
                (self.NCAAW_HOCKEY_SEPARATOR_ICON, ["ncaaw_hockey", "ncaa_womens"]),
                (self.NCAA_SEPARATOR_ICON, ["ncaa"]),
            ]

            for icon_path, league_keys in ncaa_icon_paths:
                if os.path.exists(icon_path):
                    try:
                        # Use context manager to ensure file handle is closed
                        with Image.open(icon_path) as ncaa_file:
                            # Convert creates a copy; if already RGBA, use copy() to detach from file
                            if ncaa_file.mode != "RGBA":
                                ncaa_icon = ncaa_file.convert("RGBA")
                            else:
                                ncaa_icon = ncaa_file.copy()
                        # Resize to fit height while maintaining aspect ratio (after file is closed)
                        aspect = ncaa_icon.width / ncaa_icon.height
                        new_width = int(separator_height * aspect)
                        ncaa_icon = ncaa_icon.resize((new_width, separator_height), resample=RESAMPLE_FILTER)
                        for key in league_keys:
                            self._separator_icons[key] = ncaa_icon
                        self.logger.debug(f"Loaded NCAA separator icon from {icon_path}: {new_width}x{separator_height}")
                    except Exception:
                        self.logger.exception(f"Error loading NCAA separator icon from {icon_path}")

        def _determine_game_type(self, game: Dict) -> str:
            """
            Determine the game type from the game's status.

            Args:
                game: Game dictionary

            Returns:
                Game type: 'live', 'recent', or 'upcoming'
            """
            state = game.get('status', {}).get('state', '')
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
            rankings_cache: Optional[Dict[str, int]] = None
        ) -> bool:
            """
            Prepare scrolling content from a list of games.

            Args:
                games: List of game dictionaries with league info
                game_type: Type hint ('live', 'recent', 'upcoming', or 'mixed' for mixed types)
                leagues: List of leagues in order (e.g., ['nhl', 'ncaam_hockey', 'ncaaw_hockey'])
                rankings_cache: Optional team rankings cache

            Returns:
                True if content was prepared successfully, False otherwise
            """
            if not self.scroll_helper:
                self.logger.error("ScrollHelper not available")
                return False

            if not games:
                self.logger.debug("No games to prepare for scrolling")
                self.clear()  # Reset all scroll state, not just cache
                return False

            self._current_games = games
            self._current_game_type = game_type
            self._current_leagues = leagues

            # Get scroll settings using primary league from the provided leagues list
            primary_league = leagues[0] if leagues else None
            scroll_settings = self._get_scroll_settings(primary_league)
            # 48 matches the legacy scroll path's default and gives the cards
            # visible separation; 24 read as one continuous run of logos.
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
                game_league = game.get("league", "nhl")  # Default to NHL if not specified

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

                # Render game card
                # Only determine type from game state when in 'mixed' mode; otherwise use the passed game_type
                try:
                    if game_type == 'mixed':
                        individual_game_type = self._determine_game_type(game)
                    else:
                        individual_game_type = game_type
                    game_img = renderer.render_game_card(game, individual_game_type)

                    # Half the gap on each side, so adjacent cards are separated
                    # by exactly gap_between_games. Baking it into the card
                    # matters for Vegas, which stitches _vegas_content_items
                    # itself and never sees the scroll helper's item_gap -- that
                    # is why Vegas used to run cards close together regardless
                    # of the setting. (The old fixed 12px padding here was
                    # compensating for logos drawn at -10/display_width+10, a
                    # layout this renderer no longer uses.)
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
                # Spacing already baked into each card above, so both this path
                # and Vegas separate cards by the same gap_between_games.
                item_gap=0,
                element_gap=0  # No element gap - each item is a complete game card
            )

            # Log what we loaded
            league_summary = ", ".join([f"{league.upper()}({count})" for league, count in league_counts.items()])
            self.logger.info(
                f"[Hockey Scroll] Prepared {game_count} games for scrolling: {league_summary}"
            )
            self.logger.info(
                f"[Hockey Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
                f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
            )

            # Reset tracking state
            self._is_scrolling = True
            self._scroll_start_time = time.time()
            self._frame_count = 0
            self._fps_sample_start = time.time()

            return True


    class ScrollDisplayManager(_ScrollDisplayManagerBase):
        """Hockey Scoreboard scroll manager -- everything but the extras below is core."""

        display_class = ScrollDisplay

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

