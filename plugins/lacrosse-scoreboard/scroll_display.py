"""
Scroll Display Handler for Lacrosse Scoreboard.

Orchestration (scroll-helper configuration, frame pumping, completion,
settings resolution, `global_config['target_fps']`) comes from the core's
`src.common.sports_scroll`, shipped in LEDMatrix 3.2.0. Only the *content*
half lives here: building this sport's game cards and separator icons.

The import below is deliberately unguarded, and the manifest floors at 3.2.0
to match. B5 shipped it wrapped in a try/except with a bundled
`scroll_display_legacy` behind it, so the plugin kept working on an older
core; B6 removed that copy. Keeping the guard with nothing to fall back to
would be worse than not having it -- the failure would name the missing
`scroll_display_legacy` instead of the core module that is actually absent,
which is the one line the user gets before the scoreboard silently stops
appearing.
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


from src.common.sports_scroll import (
    SportsScrollDisplay as _ScrollDisplayBase,
    SportsScrollDisplayManager as _ScrollDisplayManagerBase,
)

class ScrollDisplay(_ScrollDisplayBase):
    """Lacrosse Scoreboard content on the core scroll engine."""

    # The ladder the legacy _get_scroll_settings walked, same order.
    SCROLL_LEAGUE_KEYS = ("ncaa_mens", "ncaam_lacrosse", "ncaa_womens", "ncaaw_lacrosse")

    # Paths to league separator icons. Lacrosse uses a single NCAA lacrosse
    # logo for both men's and women's since ESPN does not ship separate
    # gendered marks for the sport. These must live on THIS class, not only
    # on the legacy one: _load_separator_icons below was lifted verbatim and
    # reads them off self, and the core base calls it from __init__ -- so a
    # missing constant is not a degraded icon, it is an AttributeError that
    # stops the scroll display being constructed at all.
    NCAA_SEPARATOR_ICON = "assets/sports/ncaa_logos/NCAA.png"
    NCAA_LACROSSE_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_lacrosse.png"


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
            # The gap has to be measured at the width we are going to
            # USE, not at the probe width. When center_gap_ratio drives
            # the gap (rather than the score reserve) it scales with the
            # card, so a gap measured at 128px underestimates the gap at
            # the final width, and the logos silently get less than the
            # full height the card was sized to give them. Settle the two
            # together; a couple of rounds is plenty, and the loop is
            # bounded so a pathological config cannot spin.
            # A ratio-driven gap converges geometrically rather than at
            # once, so allow enough rounds to settle: with the default
            # score-driven gap the width does not depend on the card and
            # this breaks on the second pass.
            width = 128
            for _ in range(12):
                probe = GameRenderer(width, self.display_height, self.config)
                candidate = max(128, self.display_height * 2
                                + probe._center_gap_width())
                if candidate == width:
                    break
                width = candidate
        except Exception:
            self.logger.debug("Card width probe failed; keeping 128",
                              exc_info=True)
            return 128
        return width


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

    def _load_separator_icons(self) -> None:
        """Load and resize league separator icons."""
        separator_height = self.display_height - 4  # Leave some padding

        # Load NCAA icon (try sport-specific first, then generic). Both
        # entries register under the lacrosse league keys so the generic
        # NCAA.png acts as a real fallback when ncaa_lacrosse.png is missing —
        # otherwise separator lookups for "ncaam_lacrosse" / "ncaaw_lacrosse"
        # would silently return None.
        lacrosse_keys = ["ncaam_lacrosse", "ncaa_mens",
                         "ncaaw_lacrosse", "ncaa_womens"]
        ncaa_icon_paths = [
            (self.NCAA_LACROSSE_SEPARATOR_ICON, lacrosse_keys),
            (self.NCAA_SEPARATOR_ICON, [*lacrosse_keys, "ncaa"]),
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
                    # Only populate keys that haven't been set yet so the
                    # sport-specific icon (iterated first) always wins over
                    # the generic NCAA fallback.
                    for key in league_keys:
                        self._separator_icons.setdefault(key, ncaa_icon)
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
            leagues: List of leagues in order (e.g., ['ncaam_lacrosse', 'ncaaw_lacrosse'])
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
            game_league = game.get("league", "ncaam_lacrosse")  # Default to NCAA Men's Lacrosse if not specified

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
            f"[Lacrosse Scroll] Prepared {game_count} games for scrolling: {league_summary}"
        )
        self.logger.info(
            f"[Lacrosse Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
            f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
        )

        # Reset tracking state
        self._is_scrolling = True
        self._scroll_start_time = time.time()
        self._frame_count = 0
        self._fps_sample_start = time.time()

        return True


class ScrollDisplayManager(_ScrollDisplayManagerBase):
    """Lacrosse Scoreboard scroll manager -- everything but the extras below is core."""

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
