"""
Game Renderer for Soccer Scoreboard Plugin

Extracts game rendering logic into a reusable component that can be used by both
switch mode (one game at a time) and scroll mode (all games scrolling horizontally).

This module provides:
- GameRenderer class for rendering individual game cards as PIL Images
- Pre-loading of team logos for performance
- Support for live, recent, and upcoming game layouts
- Consistent rendering across all display modes
"""

import logging
import os
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from src.common import sports_card as _card
from src.common.sports_game_renderer import SportsGameRendererMixin

#: This plugin's own schema, for the shared font-size resolver.
_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'config_schema.json')


def _resolve_font_path(path: str) -> str:
    """Resolve a bundled font path without depending on the process cwd.

    These fonts ship with the LEDMatrix core, and every call site here named
    them relative to the working directory. That holds under the packaged
    systemd unit, whose WorkingDirectory is the install root, and breaks
    everywhere else -- the plugin safety harness, a manual run from $HOME, a
    unit file written without WorkingDirectory. The failure is quiet: the
    load raises, the caller falls back, and the scoreboard renders in PIL's
    default face instead of the pixel font it was laid out for.

    Resolution order matches the core's own resolver: the path as given
    first, so behaviour is unchanged wherever it already worked and a
    configured absolute path is returned untouched, then the core install
    root, then the original string so callers still raise and fall back
    exactly as they do today.
    """
    if os.path.exists(path):
        return path
    try:
        import src.font_manager as _core_fonts

        # The core grew this resolver in ChuckBuilds/LEDMatrix#425. Use it
        # when it is there so both repos stay on one definition of "install
        # root"; older cores fall through to the equivalent derivation below.
        manager = getattr(_core_fonts, "FontManager", None)
        resolver = getattr(manager, "_resolve_asset_path", None)
        if resolver is not None:
            resolved = resolver(path)
            if resolved and os.path.exists(resolved):
                return resolved
        root = os.path.dirname(os.path.dirname(os.path.abspath(_core_fonts.__file__)))
        candidate = os.path.join(root, path)
        if os.path.exists(candidate):
            return candidate
    except (ImportError, AttributeError, OSError):
        # No core on the path (standalone tooling), a core laid out
        # differently, or an unreadable install. Returning the original keeps
        # the caller's existing fallback intact.
        return path
    return path


logger = logging.getLogger(__name__)


class GameRenderer(SportsGameRendererMixin):
    """
    Renders individual game cards as PIL Images for display.
    
    This class extracts the rendering logic from the sports manager classes
    to provide a reusable component for both switch and scroll display modes.
    """
    
    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict[str, Any],
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the GameRenderer.
        
        Args:
            display_width: Width of the display/game card
            display_height: Height of the display/game card
            config: Configuration dictionary
            logo_cache: Optional shared logo cache dictionary
            custom_logger: Optional custom logger instance
        """
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logger
        
        # Shared logo cache for performance
        self._logo_cache = logo_cache if logo_cache is not None else {}
        
        # Load fonts
        self.fonts = self._unshare_element_fonts(self._load_fonts())
        
        # Display options
        self.show_odds = config.get("show_odds", False)
        self.show_records = config.get("show_records", False)
        self.show_ranking = config.get("show_ranking", False)
        
        # Rankings cache (populated externally)
        self._team_rankings_cache: Dict[str, int] = {}
        
    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}
        
        # Get customization config
        customization = self.config.get('customization', {})
        
        # Load fonts from config with defaults for backward compatibility
        score_config = customization.get('score_text', {})
        period_config = customization.get('period_text', {})
        team_config = customization.get('team_name', {})
        status_config = customization.get('status_text', {})
        detail_config = customization.get('detail_text', {})
        # Falls back to detail_text so a config written before this
        # setting existed keeps rendering odds exactly as it did.
        odds_config = customization.get('odds_text') or detail_config
        rank_config = customization.get('rank_text', {})
        
        try:
            fonts["score"] = self._load_custom_font(score_config, default_size=10, element_key='score_text')
            fonts["time"] = self._load_custom_font(period_config, default_size=8, element_key='period_text')
            fonts["team"] = self._load_custom_font(team_config, default_size=8, element_key='team_name')
            fonts["status"] = self._load_custom_font(status_config, default_size=6, element_key='status_text')
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, default_font='4x6-font.ttf', element_key='detail_text')
            fonts["odds"] = self._load_custom_font(odds_config, default_size=6, default_font='4x6-font.ttf', element_key='odds_text')
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10, element_key='rank_text')
            self.logger.debug("Successfully loaded fonts from config")
        except Exception as e:
            self.logger.error(f"Error loading fonts: {e}, using defaults")
            # Fallback to hardcoded defaults
            try:
                fonts["score"] = ImageFont.truetype(_resolve_font_path("assets/fonts/PressStart2P-Regular.ttf"), 8)
                fonts["time"] = ImageFont.truetype(_resolve_font_path("assets/fonts/PressStart2P-Regular.ttf"), 8)
                fonts["team"] = ImageFont.truetype(_resolve_font_path("assets/fonts/PressStart2P-Regular.ttf"), 8)
                fonts["status"] = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
                fonts["detail"] = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
                fonts["rank"] = ImageFont.truetype(_resolve_font_path("assets/fonts/PressStart2P-Regular.ttf"), 8)
            except IOError:
                self.logger.warning("Fonts not found, using default PIL font.")
                default_font = ImageFont.load_default()
                fonts = {k: default_font for k in ["score", "time", "team", "status", "detail", "rank"]}
        
        return fonts
    

    #: Sizes each pixel font renders crisply at. Off the grid the glyphs are
    #: anti-aliased, and on an LED matrix a part-lit pixel reads as a dim
    #: lamp rather than a soft edge.
    _FONT_PIXEL_GRID = {
        'PressStart2P-Regular.ttf': 8,   # crisp at 8, 16, 24, 32, 40
        '4x6-font.ttf': 7,               # crisp at 7, 14, 21, 28, 35
    }

    #: baseball-scoreboard's schema offers font FAMILY ALIASES rather than
    #: filenames, and a config saved through the web UI stores the alias. Kept
    #: out of _FONT_PIXEL_GRID so that table stays a map of real files.
    _FONT_NAME_ALIASES = {
        'press_start': 'PressStart2P-Regular.ttf',
        'four_by_six': '4x6-font.ttf',
    }

    @classmethod
    def _crisp_size(cls, font_file, desired):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.crisp_size(font_file, desired,
                                cls._FONT_NAME_ALIASES, cls._FONT_PIXEL_GRID)

    def _schema_font_size(self, element_key):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.schema_font_size(_SCHEMA_PATH, element_key)

    def _resolve_font_size(self, element_config, element_key, default_size, font_name):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.resolve_font_size(_SCHEMA_PATH, element_config, element_key,
                                       default_size, font_name,
                                       self._FONT_NAME_ALIASES, self._FONT_PIXEL_GRID)

    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf', element_key=None) -> ImageFont.FreeTypeFont:
        """Load a custom font from an element configuration dictionary."""
        font_name = element_config.get('font', default_font)
        # Resolve a family alias to its filename BEFORE the path is built.
        # The grid table understands aliases, so a configured
        # "four_by_six" was sized on the 4x6 grid (7px) while the path
        # lookup used the raw alias, missed, and fell back to
        # PressStart2P -- rendering 7px on an 8px grid, anti-aliased.
        font_name = self._FONT_NAME_ALIASES.get(font_name, font_name)
        font_size = self._resolve_font_size(
            element_config, element_key, default_size, font_name)
        font_path = _resolve_font_path(os.path.join('assets', 'fonts', font_name))
        
        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf'):
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    try:
                        return ImageFont.truetype(font_path, font_size)
                    except Exception:
                        self.logger.warning(f"Could not load BDF font {font_name}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}")
        
        # Fallback to default font
        default_font_path = _resolve_font_path(os.path.join('assets', 'fonts', default_font))
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception as e:
            # Say so. Reaching PIL's built-in face means this element will
            # not match the panel's pixel grid, which reads as a rendering
            # bug rather than a missing font file.
            self.logger.warning(
                "Fallback font %s failed to load (%s: %s)",
                default_font_path, type(e).__name__, e)
        
        self.logger.warning(
            "No usable font found; using PIL's built-in face, which will "
            "not be pixel-crisp")
        return ImageFont.load_default()
    
    def preload_logos(self, games: list, logo_dir: Path) -> None:
        """
        Pre-load team logos for all games to improve scroll performance.
        
        Args:
            games: List of game dictionaries
            logo_dir: Path to logo directory
        """
        for game in games:
            for team_key in ['home_abbr', 'away_abbr']:
                abbr = game.get(team_key, '')
                if abbr and self._logo_cache_key(abbr) not in self._logo_cache:
                    logo_path = game.get(f'{team_key.replace("abbr", "logo_path")}')
                    if logo_path:
                        logo = self._load_and_resize_logo(
                            game.get(team_key.replace('abbr', 'id'), ''),
                            abbr,
                            logo_path,
                            game.get(f'{team_key.replace("abbr", "logo_url")}')
                        )
                        if logo:
                            self._logo_cache[self._logo_cache_key(abbr)] = logo
        
        self.logger.debug(f"Preloaded {len(self._logo_cache)} team logos")
    
    def _load_and_resize_logo(
        self, 
        team_id: str, 
        team_abbrev: str, 
        logo_path: Path, 
        logo_url: Optional[str] = None
    ) -> Optional[Image.Image]:
        """Load and resize a team logo with caching."""
        # Look up under the same size-scoped key the writes use. This tested
        # the bare abbreviation while every store used "<abbr>@<slot>x<height>",
        # so the lookup never matched and each card re-decoded and re-resized
        # the source PNG. Some shipped logos are 4096x4096, which is most of a
        # second per logo on a Pi.
        cache_key = self._logo_cache_key(team_abbrev)
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]
        
        try:
            # Try to load from path
            if os.path.exists(logo_path):
                logo = Image.open(logo_path)
                if logo.mode != "RGBA":
                    logo = logo.convert("RGBA")
                
                # Crop transparent padding then scale so ink fills display_height.
                # thumbnail into a display_height square box preserves aspect ratio
                # and prevents wide logos from exceeding their half-card slot.
                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                logo.thumbnail((self._logo_slot_width(), self.display_height), Image.Resampling.LANCZOS)

                self._logo_cache[self._logo_cache_key(team_abbrev)] = logo
                return logo
            else:
                self.logger.debug(f"Logo not found at {logo_path}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}")
            return None
    
    def _resize_logo_to_fit(
        self, 
        logo: Image.Image, 
        max_width: int, 
        max_height: int
    ) -> Image.Image:
        """
        Resize a logo to fit within given dimensions while maintaining aspect ratio.
        
        Args:
            logo: PIL Image of the logo
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels
            
        Returns:
            Resized logo image
        """
        if logo.width <= max_width and logo.height <= max_height:
            return logo
        
        # Create a copy to avoid modifying the cached version
        resized_logo = logo.copy()
        resized_logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        return resized_logo
    
    def _calculate_max_logo_dimensions(
        self, 
        score_width: int, 
        side: str
    ) -> Tuple[int, int]:
        """
        Calculate maximum logo dimensions based on available space.
        
        Args:
            score_width: Width of the score text in pixels
            side: 'home' or 'away' to determine which side of the display
            
        Returns:
            Tuple of (max_width, max_height) in pixels
        """
        # Padding around score text and edges
        score_padding = 8  # Space between logo and score text
        edge_padding = 10  # Space from display edges
        
        # Calculate available width for each logo
        center_x = self.display_width // 2
        score_left = center_x - (score_width // 2)
        score_right = center_x + (score_width // 2)
        
        if side == 'away':
            # Away logo on the left side
            available_width = score_left - score_padding - edge_padding
        else:  # home
            # Home logo on the right side
            available_width = self.display_width - score_right - score_padding - edge_padding
        
        # Ensure minimum width (at least 20% of display width)
        min_width = int(self.display_width * 0.2)
        available_width = max(available_width, min_width)
        
        # Max height is slightly less than display height to leave room for status text
        max_height = int(self.display_height * 0.85)
        
        return (available_width, max_height)
    
    #: Which customization element owns each loaded face. The font loader
    #: already picks each face from exactly that element (element_key=), so
    #: resolving the colour from the face keeps the two in step by
    #: construction, rather than by every draw site remembering to agree.
    _ELEMENT_FOR_FONT: ClassVar[Dict[str, str]] = {
        "odds": "odds_text",
        "score": "score_text",
        "time": "period_text",
        "team": "team_name",
        "status": "status_text",
        "detail": "detail_text",
        "rank": "rank_text",
    }

    def _unshare_element_fonts(self, fonts):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.unshare_element_fonts(self.logger, fonts)

    def _font_color(self, font, default: Tuple[int, int, int] = (255, 255, 255)):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.font_color(self.config, getattr(self, "fonts", None), font, default)

    def _draw_text_with_outline(
        self, 
        draw: ImageDraw.Draw, 
        text: str, 
        position: Tuple[int, int], 
        font: ImageFont.FreeTypeFont, 
        fill: Optional[Tuple[int, int, int]] = None, 
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """Draw text with a black outline for better readability."""
        # Disable anti-aliasing: pixel/bitmap fonts (e.g. PressStart2P) get
        # anti-aliased into dim partial-lit pixels on a 1:1 LED matrix, muddying
        # glyphs. 1-bit mode keeps strokes crisp.
        # Defaults to the configured colour for whichever element owns
        # this face rather than to white, so customization.<element>.text_color
        # reaches every draw. The schema has offered those pickers all along
        # and they only ever changed the font. An explicit fill still wins:
        # the odds colours and the favourite-result score tint mean something
        # the palette does not.
        if fill is None:
            fill = self._font_color(font)
        draw.fontmode = "1"
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)
    
    # ------------------------------------------------------------------
    # Favorite-team result colors for finished games.
    #
    # This is the scroll/Vegas path, and it is where the setting earns its
    # keep: a series against the same opponent scrolls past as several
    # near-identical cards, so tinting the final score green or red is the
    # only quick way to tell a win from a loss. Off by default -- the score
    # keeps the color it has today until the user opts in.
    # ------------------------------------------------------------------

    FAVORITE_RESULT_COLOR_DEFAULTS: ClassVar[Dict[str, Tuple[int, int, int]]] = {
        "win": (0, 255, 0),
        "loss": (255, 0, 0),
        "tie": (255, 200, 0),
    }

    @staticmethod
    def _coerce_rgb(value, fallback):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.coerce_rgb(value, fallback)

    def _favorite_teams_for(self, game: Dict[str, Any]) -> list:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.favorite_teams_for(self.config, game)

    @staticmethod
    def _side_is_favorite(game: Dict[str, Any], side: str, favorites: set) -> bool:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.side_is_favorite(game, side, favorites)

    @staticmethod
    def _side_score(game: Dict[str, Any], side: str) -> Optional[int]:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.side_score(game, side)

    def _favorite_result(self, game: Dict[str, Any]) -> Optional[str]:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.favorite_result(self.config, game)

    def _score_color_for(self, game: Dict[str, Any], game_type: str, default=None):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.score_color_for(self.config, self.logger, game, game_type, default)

    def _recent_score_color(self, game: Dict[str, Any], default):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.recent_score_color(self.config, self.logger, game, default)

    def render_game_card(
        self, 
        game: Dict[str, Any], 
        game_type: str = "live"
    ) -> Image.Image:
        """
        Render a single game card as a PIL Image.
        
        Args:
            game: Game dictionary with team info, scores, status, etc.
            game_type: Type of game - 'live', 'recent', or 'upcoming'
            
        Returns:
            PIL Image of the rendered game card
        """
        # Create base image
        main_img = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        # Calculate score text width first to determine available space for logos
        home_score = str(game.get("home_score", "0"))
        away_score = str(game.get("away_score", "0"))
        score_text = f"{away_score}-{home_score}"
        score_width = draw_overlay.textlength(score_text, font=self.fonts['score'])
        
        # Load logos
        home_logo = self._load_and_resize_logo(
            game.get("home_id", ""),
            game.get("home_abbr", ""),
            game.get("home_logo_path"),
            game.get("home_logo_url")
        )
        away_logo = self._load_and_resize_logo(
            game.get("away_id", ""),
            game.get("away_abbr", ""),
            game.get("away_logo_path"),
            game.get("away_logo_url")
        )
        
        if not home_logo or not away_logo:
            # Draw placeholder text if logos fail
            draw = ImageDraw.Draw(main_img)
            self._draw_text_with_outline(
                draw, 
                f"{game.get('away_abbr', '?')}@{game.get('home_abbr', '?')}", 
                (5, 5), 
                self.fonts['status']
            )
            return main_img.convert('RGB')
        
        center_y = self.display_height // 2

        # Place logos — each centered within a slot on its side; cap at half the card
        # width so home_slot_start stays non-negative on square/tall displays
        logo_slot = self._logo_slot_width()
        away_x = ((logo_slot - away_logo.width) // 2
                  + self._layout_offset('away_logo', 'x_offset'))
        away_y = (center_y - (away_logo.height // 2)
                  + self._layout_offset('away_logo', 'y_offset'))

        home_slot_start = self.display_width - logo_slot
        home_x = (home_slot_start + (logo_slot - home_logo.width) // 2
                  + self._layout_offset('home_logo', 'x_offset'))
        home_y = (center_y - (home_logo.height // 2)
                  + self._layout_offset('home_logo', 'y_offset'))
        
        # Draw logos
        main_img.paste(home_logo, (home_x, home_y), home_logo)
        main_img.paste(away_logo, (away_x, away_y), away_logo)
        
        # Draw scores (centered) — only once a game has started. Upcoming games
        # have no score, so the extractor's 0-0 was pure noise.
        if game_type in ("live", "recent"):
            score_x = ((self.display_width - score_width) // 2
                       + self._layout_offset('score', 'x_offset'))
            score_y = ((self.display_height // 2) - 3
                       + self._layout_offset('score', 'y_offset'))
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts['score'],
                fill=self._score_color_for(game, game_type)
            )
        elif game_type == "upcoming":
            self._draw_upcoming_center(draw_overlay, game)
        
        # Draw period/status based on game type
        if game_type == "live":
            self._draw_live_game_status(draw_overlay, game)
        elif game_type == "recent":
            self._draw_recent_game_status(draw_overlay, game)
        elif game_type == "upcoming":
            self._draw_upcoming_game_status(draw_overlay, game)
        
        # Draw odds if enabled
        if self.show_odds and 'odds' in game and game['odds']:
            self._draw_dynamic_odds(draw_overlay, game['odds'])
        
        # Draw records or rankings if enabled
        if self.show_records or self.show_ranking:
            self._draw_records_or_rankings(draw_overlay, game)
        
        # Composite the overlay onto main image
        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')
    
    def _draw_live_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a live soccer game."""
        # Period/Clock (Top center) - e.g., "1H 45'", "HALF", "2H 90+3'"
        period_clock_text = game.get('period_text', '')
        if not period_clock_text:
            # Fallback to clock if period_text not available
            clock = game.get('clock', '')
            if clock:
                period_clock_text = clock
            else:
                period_clock_text = "LIVE"
        
        # Handle halftime
        if game.get("is_halftime"):
            period_clock_text = "HALF"
        elif game.get("is_period_break"):
            period_clock_text = game.get("status_text", "BREAK")
        
        status_width = draw.textlength(period_clock_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_clock_text, (status_x, status_y), self.fonts['time'])

        # No bottom date line for live games: the period/clock already conveys the
        # game is in progress, and a third stacked line overflows the bottom on
        # short panels (e.g. 128x32). Matches the baseball live scorebug.

    def _draw_recent_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a recently completed soccer game."""
        # Final status (Top center) - e.g., "Final", "Final/OT"
        period_text = game.get("period_text", "Final")
        if not period_text:
            period_text = "Final"
        status_width = draw.textlength(period_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_text, (status_x, status_y), self.fonts['time'])
        
        # Game date (Bottom center)
        game_date = game.get("game_date", "")
        if game_date:
            date_width = draw.textlength(game_date, font=self.fonts['detail'])
            date_x = (self.display_width - date_width) // 2
            date_y = self.display_height - 7
            self._draw_text_with_outline(draw, game_date, (date_x, date_y), self.fonts['detail'])
    
    # ------------------------------------------------------------------
    # Card options -- config["scroll_card"], plus the shared
    # customization.layout offsets and per-element colours.
    #
    # The center-gap keys size this renderer's cards alone; they are read by
    # SportsGameRendererMixin, which owns the geometry those keys drive. The
    # rest -- upcoming_center, vs_text, the date and time formats -- are also
    # read by
    # sports.py's full-screen scorebug (SportsCore._draw_upcoming_center_switch
    # and friends, gated there on switch_upcoming_center), so those two copies
    # have to stay in step: a change to the formatting rules here needs the
    # same change there, or the ticker and the scoreboard disagree.
    # ------------------------------------------------------------------
    _MONTH_ABBR: ClassVar[Tuple[str, ...]] = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    _WEEKDAY_ABBR: ClassVar[Tuple[str, ...]] = (
        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
    )

    def _scroll_card_option(self, key: str, default: Any = None) -> Any:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.scroll_card_option(self.config, key, default)

    def _element_color(self, element: str, default: Tuple[int, int, int] = (255, 255, 255)):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.element_color(self.config, element, default)

    def _upcoming_center_mode(self) -> str:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.upcoming_center_mode(self.config)

    def _vs_text(self) -> str:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.vs_text(self.config)

    def _format_game_date(self, date_text: str, game: Optional[Dict] = None) -> str:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.format_game_date(self.config, self.logger, date_text, game)

    def _weekday_for(self, game: Optional[Dict]) -> str:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.weekday_for(self.config, self.logger, game)

    def _card_tzinfo(self):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.card_tzinfo(self.config, self.logger)

    def _format_game_time(self, time_text: str) -> str:
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.format_game_time(self.config, time_text)

    def _odds_color(self) -> Tuple[int, int, int]:
        """Colour for the odds text; the green it always drew unless configured.

        Guarded with getattr because not every class that reaches
        _draw_dynamic_odds carries the element-colour helper -- the plugins'
        own test harnesses build minimal manager objects, and a bare
        AttributeError here is swallowed by the surrounding except, which
        drops the odds off the card instead of failing loudly.
        """
        getter = getattr(self, "_element_color", None)
        if getter is None:
            return (0, 255, 0)
        try:
            return getter("odds_text", (0, 255, 0))
        except Exception:
            return (0, 255, 0)

    def _draw_dynamic_odds(self, draw: ImageDraw.Draw, odds: Dict[str, Any]) -> None:
        """Draw odds with dynamic positioning."""
        try:
            if not odds:
                return
            
            home_team_odds = odds.get("home_team_odds", {})
            away_team_odds = odds.get("away_team_odds", {})
            home_spread = home_team_odds.get("spread_odds")
            away_spread = away_team_odds.get("spread_odds")
            
            # Get top-level spread as fallback
            top_level_spread = odds.get("spread")
            if top_level_spread is not None:
                if home_spread is None or home_spread == 0.0:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = -top_level_spread if isinstance(
                        top_level_spread, (int, float)) else None
            
            # Determine favored team
            home_favored = home_spread is not None and isinstance(home_spread, (int, float)) and home_spread < 0
            away_favored = away_spread is not None and isinstance(away_spread, (int, float)) and away_spread < 0
            
            favored_spread = None
            favored_side = None
            
            if home_favored:
                favored_spread = home_spread
                favored_side = "home"
            elif away_favored:
                favored_spread = away_spread
                favored_side = "away"
            
            # Read once, before either branch. These used to be read inside
            # the spread branch, but the over/under below uses them too -- so
            # a game with a total and no spread raised UnboundLocalError, and
            # the except swallowed it, drawing no odds at all.
            odds_x_offset = self._layout_offset('odds', 'x_offset')
            odds_y_offset = self._layout_offset('odds', 'y_offset')

            # Show the negative spread
            # Both labels are anchored to the edges of this row, and the card
            # centres the kickoff time on the same row. On a full-width panel
            # there is room for all three; on a Vegas game card, which this
            # plugin pins to 128px whatever the panel width, the O/U label can
            # run straight through the time. Budget each side against the
            # widest time string the centre can hold, measured in the font the
            # renderer will actually use, so this tracks font changes instead
            # of hard-coding a width.
            font = self.fonts.get("odds") or self.fonts["detail"]
            time_font = self.fonts.get("time", font)
            centre_reserve = draw.textlength("12:00 PM", font=time_font)
            side_budget = max(0.0, (self.display_width - centre_reserve) / 2)

            if favored_spread is not None:
                spread_text = str(favored_spread)
                spread_width = draw.textlength(spread_text, font=font)

                if spread_width <= side_budget:
                    if favored_side == "home":
                        # -1 so the outline stroke stays inside the canvas
                        # rather than being clipped by the right edge.
                        spread_x = (self.display_width - spread_width - 1
                                    + odds_x_offset)
                    else:
                        spread_x = 0 + odds_x_offset
                    spread_y = 0 + odds_y_offset

                    self._draw_text_with_outline(draw, spread_text, (spread_x, spread_y), font, fill=self._odds_color())
            
            # Show over/under on opposite side
            over_under = odds.get("over_under")
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                ou_width = draw.textlength(ou_text, font=font)

                # The longer of the two labels, so on a narrow card it is
                # the one that gives way. The spread is the more useful
                # number, and it is kept.
                if ou_width > side_budget:
                    return
                
                if favored_side == "home":
                    ou_x = 0 + odds_x_offset
                elif favored_side == "away":
                    ou_x = self.display_width - ou_width + odds_x_offset
                else:
                    # No favourite: anchor to the same left edge the
                    # home-favoured case uses. Centring put it on top of the
                    # status text, which the card also centres on this row --
                    # "Final" and "O/U: 47.5" rendered through each other. It
                    # is also the assumption the side budget above is measured
                    # against, which only holds for an edge-anchored label.
                    ou_x = 0 + odds_x_offset
                ou_y = 0 + odds_y_offset
                
                self._draw_text_with_outline(draw, ou_text, (ou_x, ou_y), font, fill=self._odds_color())
                
        except Exception as e:
            self.logger.error(f"Error drawing odds: {e}")
    
    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw team records or rankings."""
        record_font = getattr(self, '_record_font', None)
        if record_font is None:
            try:
                record_font = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
            except OSError:
                record_font = ImageFont.load_default()
            self._record_font = record_font

        away_abbr = game.get('away_abbr', '')
        home_abbr = game.get('home_abbr', '')
        
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - 4
        
        # Away team info
        if away_abbr:
            away_text = self._get_team_display_text(away_abbr, game.get('away_record', ''))
            if away_text:
                away_record_x = 3
                self._draw_text_with_outline(draw, away_text, (away_record_x, record_y), record_font)
        
        # Home team info
        if home_abbr:
            home_text = self._get_team_display_text(home_abbr, game.get('home_record', ''))
            if home_text:
                home_record_bbox = draw.textbbox((0, 0), home_text, font=record_font)
                home_record_width = home_record_bbox[2] - home_record_bbox[0]
                home_record_x = self.display_width - home_record_width - 3
                self._draw_text_with_outline(draw, home_text, (home_record_x, record_y), record_font)
    
    def _get_team_display_text(self, abbr: str, record: str) -> str:
        """Get the display text for a team (ranking or record)."""
        if self.show_ranking and self.show_records:
            # Rankings replace records when both are enabled
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif self.show_records:
            return record
        return ''
