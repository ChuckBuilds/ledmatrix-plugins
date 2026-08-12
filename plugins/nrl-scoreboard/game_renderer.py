"""
Game Renderer for NRL Scoreboard Plugin

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

logger = logging.getLogger(__name__)


class GameRenderer:
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
        self.fonts = self._load_fonts()
        
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
        rank_config = customization.get('rank_text', {})
        
        try:
            fonts["score"] = self._load_custom_font(score_config, default_size=10)
            fonts["time"] = self._load_custom_font(period_config, default_size=8)
            fonts["team"] = self._load_custom_font(team_config, default_size=8)
            fonts["status"] = self._load_custom_font(status_config, default_size=6)
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, default_font='4x6.ttf')
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10)
            self.logger.debug("Successfully loaded fonts from config")
        except Exception as e:
            self.logger.error(f"Error loading fonts: {e}, using defaults")
            # Fallback to hardcoded defaults
            try:
                fonts["score"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
                fonts["time"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["team"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["status"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["detail"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["rank"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            except IOError:
                self.logger.warning("Fonts not found, using default PIL font.")
                default_font = ImageFont.load_default()
                fonts = {k: default_font for k in ["score", "time", "team", "status", "detail", "rank"]}
        
        return fonts
    
    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf') -> ImageFont.FreeTypeFont:
        """Load a custom font from an element configuration dictionary."""
        font_name = element_config.get('font', default_font)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)
        
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
        default_font_path = os.path.join('assets', 'fonts', default_font)
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception as e:
            self.logger.warning(f"Could not load default font {default_font_path}: {e}")

        return ImageFont.load_default()
    
    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        """Set the team rankings cache for display."""
        self._team_rankings_cache = rankings
    
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
                if abbr and abbr not in self._logo_cache:
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
        if team_abbrev in self._logo_cache:
            return self._logo_cache[self._logo_cache_key(team_abbrev)]
        
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
    
    def _draw_text_with_outline(
        self, 
        draw: ImageDraw.Draw, 
        text: str, 
        position: Tuple[int, int], 
        font: ImageFont.FreeTypeFont, 
        fill: Tuple[int, int, int] = (255, 255, 255), 
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """Draw text with a black outline for better readability."""
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
        """Turn a configured [R, G, B] list into a clamped (r, g, b) tuple."""
        # Checked before unpacking: a 3-character string ("123") would otherwise
        # iterate into three digits and yield a colour rather than the fallback.
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return fallback
        try:
            r, g, b = (max(0, min(255, int(channel))) for channel in value)
        except (TypeError, ValueError):
            return fallback
        return (r, g, b)

    def _favorite_teams_for(self, game: Dict[str, Any]) -> list:
        """Favorite teams that apply to this game.

        Both sources are used. Games carry the league manager's *resolved*
        favorites, which is the only place dynamic groups such as AP_TOP_25
        appear expanded; the config is read as well so an edit takes effect on
        already-fetched games, and so hand-built game dicts (tests, other
        callers) still work.
        """
        favorites = list(game.get("favorite_teams") or [])
        league_config = self.config.get(str(game.get("league", "") or ""))
        if isinstance(league_config, dict):
            favorites += list(league_config.get("favorite_teams") or [])
        else:
            favorites += list(self.config.get("favorite_teams") or [])
        return favorites

    @staticmethod
    def _side_is_favorite(game: Dict[str, Any], side: str, favorites: set) -> bool:
        """Is the home/away side of this game a favorite team?

        Reads both the flat (``home_abbr``) and nested (``home_team.abbrev``)
        payload shapes, and matches on the ESPN id too, because a couple of
        leagues (NRL) key favorites by id where abbreviations collide.
        """
        candidates = [game.get(f"{side}_abbr"), game.get(f"{side}_id")]
        team = game.get(f"{side}_team")
        if isinstance(team, dict):
            candidates += [team.get("abbrev"), team.get("abbreviation"), team.get("id")]
        for value in candidates:
            if value is not None and str(value).strip().upper() in favorites:
                return True
        return False

    @staticmethod
    def _side_score(game: Dict[str, Any], side: str) -> Optional[int]:
        """Numeric score for one side, from either payload shape."""
        raw = None
        team = game.get(f"{side}_team")
        if isinstance(team, dict) and team.get("score") is not None:
            raw = team.get("score")
        if raw is None:
            raw = game.get(f"{side}_score")
        try:
            return int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return None

    def _favorite_result(self, game: Dict[str, Any]) -> Optional[str]:
        """Say how the favorite team did in a finished game.

        Returns 'win', 'loss' or 'tie', or None when there is no single team
        to root for: no favorites configured, neither side is a favorite, or
        *both* are -- a favorite-vs-favorite game has no losing side worth
        flagging in red. Also None when the scores are not usable numbers.
        """
        favorites = {
            str(team).strip().upper()
            for team in self._favorite_teams_for(game)
            if str(team).strip()
        }
        if not favorites:
            return None

        home_fav = self._side_is_favorite(game, "home", favorites)
        away_fav = self._side_is_favorite(game, "away", favorites)
        if home_fav == away_fav:
            return None

        home_score = self._side_score(game, "home")
        away_score = self._side_score(game, "away")
        if home_score is None or away_score is None:
            return None

        if home_score == away_score:
            return "tie"
        favorite_score, other_score = (
            (home_score, away_score) if home_fav else (away_score, home_score)
        )
        return "win" if favorite_score > other_score else "loss"

    def _score_color_for(self, game: Dict[str, Any], game_type: str, default=(255, 255, 255)):
        """Fill color for a game card's score. Only finished games are tinted."""
        if game_type != "recent":
            return default
        return self._recent_score_color(game, default)

    def _recent_score_color(self, game: Dict[str, Any], default):
        """Fill color for a finished game's score, per favorite_result_colors."""
        try:
            settings = (self.config.get("customization") or {}).get(
                "favorite_result_colors"
            ) or {}
            if not settings.get("enabled", False):
                return default
            result = self._favorite_result(game)
            if result is None:
                return default
            return self._coerce_rgb(
                settings.get(f"{result}_color"),
                self.FAVORITE_RESULT_COLOR_DEFAULTS[result],
            )
        except Exception:
            self.logger.debug(
                "Could not resolve favorite result color", exc_info=True
            )
            return default

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
        """Draw status elements for a live NRL game."""
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
        """Draw status elements for a recently completed NRL game."""
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
    # Scroll/Vegas card options -- config["scroll_card"], plus the shared
    # customization.layout offsets and per-element colours.
    #
    # These only affect the cards this renderer builds, which are used by
    # scroll_display.py and scroll_display_legacy.py alone. The full-screen
    # scorebug is drawn elsewhere and is deliberately left untouched.
    # ------------------------------------------------------------------
    CENTER_GAP_RATIO: ClassVar[float] = 0.28
    CENTER_GAP_MIN_PX: ClassVar[int] = 22
    CENTER_GAP_MAX_PX: ClassVar[int] = 40
    _MONTH_ABBR: ClassVar[Tuple[str, ...]] = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    _WEEKDAY_ABBR: ClassVar[Tuple[str, ...]] = (
        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
    )

    def _logo_cache_key(self, name: str) -> str:
        """Cache key scoped to the logo slot.

        One cache dict is shared by renderers built for different card widths,
        so a logo sized for a wide slot must not be handed to a narrow one.
        """
        return f"{name}@{self._logo_slot_width()}x{self.display_height}"

    def _scroll_card_option(self, key: str, default: Any = None) -> Any:
        """Read one key from the scroll_card config block."""
        block = (self.config or {}).get("scroll_card")
        if isinstance(block, dict) and block.get(key) is not None:
            return block.get(key)
        return default

    def _layout_offset(self, element: str, axis: str, default: int = 0) -> int:
        """X/Y nudge for one element, from customization.layout.

        Same block the full-screen scorebug reads (sports.py
        _get_layout_offset), so a nudge configured in the web UI now moves
        the element on the scroll/Vegas card too -- previously the schema
        advertised these offsets but this renderer ignored them.
        """
        try:
            layout = (self.config or {}).get("customization", {}).get("layout", {})
            value = (layout.get(element) or {}).get(axis, default)
            if isinstance(value, bool):
                return default
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                return int(float(value))
        except (TypeError, ValueError):
            pass
        return default

    def _element_color(self, element: str, default: Tuple[int, int, int] = (255, 255, 255)):
        """Per-element text colour from customization.<element>.text_color."""
        try:
            cfg = (self.config or {}).get("customization", {}).get(element, {})
            value = cfg.get("text_color")
            if isinstance(value, (list, tuple)) and len(value) == 3:
                return tuple(max(0, min(255, int(c))) for c in value)
            if isinstance(value, str) and value.startswith("#") and len(value) == 7:
                return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        except (TypeError, ValueError):
            pass
        return default

    def _center_gap_width(self) -> int:
        """Width of the middle strip kept clear of logos.

        ``scroll_card.center_gap`` pins it outright; otherwise it scales with
        the card width between the configurable min and max. 0 restores
        edge-to-edge logos.
        """
        configured = self._scroll_card_option("center_gap")
        if isinstance(configured, (int, float)) and configured >= 0:
            return int(configured)
        ratio = self._scroll_card_option("center_gap_ratio", self.CENTER_GAP_RATIO)
        low = self._scroll_card_option("center_gap_min", self.CENTER_GAP_MIN_PX)
        high = self._scroll_card_option("center_gap_max", self.CENTER_GAP_MAX_PX)
        try:
            scaled = round(self.display_width * float(ratio))
            return int(max(int(low), min(int(high), scaled)))
        except (TypeError, ValueError):
            return self.CENTER_GAP_MIN_PX

    def _logo_slot_width(self) -> int:
        """Per-side logo slot, leaving the center gap clear.

        Capped at display_height, so wide/short cards (128x32, 256x32) already
        have a large middle and come out unchanged -- only the sizes where the
        logos used to meet (128x64, 64x32) shrink.
        """
        available = (self.display_width - self._center_gap_width()) // 2
        return max(8, min(self.display_height, available))

    def _upcoming_center_mode(self) -> str:
        """Middle of an upcoming card: 'vs', 'date_time' or 'none'."""
        mode = str(self._scroll_card_option("upcoming_center", "vs") or "vs").lower()
        return mode if mode in ("vs", "date_time", "none") else "vs"

    def _vs_text(self) -> str:
        """Separator drawn between the teams -- "VS", "@", "at", anything."""
        return str(self._scroll_card_option("vs_text", "VS"))

    def _format_game_date(self, date_text: str, game: Optional[Dict] = None) -> str:
        """Format an upcoming card's date per scroll_card.date_format."""
        raw = str(date_text or "").strip()
        if not raw:
            return ""
        fmt = str(self._scroll_card_option("date_format", "abbrev") or "abbrev")
        if fmt == "numeric":
            return raw
        parts = raw.replace("-", "/").split("/")
        if not (len(parts) >= 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit()):
            return raw
        month, day = int(parts[0]), int(parts[1])
        if not 1 <= month <= 12:
            return raw
        name = self._MONTH_ABBR[month - 1]
        if fmt == "numeric_day_first":
            return f"{day}/{month}"
        if fmt == "day_first":
            return f"{day} {name}"
        if fmt == "weekday":
            weekday = self._weekday_for(game)
            return f"{weekday} {name} {day}" if weekday else f"{name} {day}"
        return f"{name} {day}"

    def _weekday_for(self, game: Optional[Dict]) -> str:
        """Weekday abbreviation from the game's start time, or ''."""
        if not game:
            return ""
        raw = game.get("start_time_utc") or game.get("start_time")
        if not raw:
            return ""
        try:
            start = raw if isinstance(raw, datetime) else datetime.fromisoformat(
                str(raw).replace("Z", "+00:00"))
            return self._WEEKDAY_ABBR[start.astimezone(self._card_tzinfo()).weekday()]
        except (ValueError, TypeError):
            return ""

    def _card_tzinfo(self):
        """Timezone for weekday/24h conversions; falls back to UTC."""
        configured = (self.config or {}).get("timezone")
        if configured:
            try:
                return ZoneInfo(configured)
            except (KeyError, ValueError, TypeError, OSError) as exc:
                # KeyError covers ZoneInfoNotFoundError. A bad zone name in
                # config should fall back to UTC, not blank the card.
                self.logger.debug("Unusable timezone %r: %s", configured, exc)
        return timezone.utc

    def _format_game_time(self, time_text: str) -> str:
        """Return the time as-is (12h) or converted to 24h."""
        raw = str(time_text or "").strip()
        if not raw or str(self._scroll_card_option("time_format", "12h")) != "24h":
            return raw
        cleaned = raw.upper().replace(" ", "")
        meridiem = "AM" if cleaned.endswith("AM") else "PM" if cleaned.endswith("PM") else ""
        if not meridiem:
            return raw
        try:
            hh, _, mm = cleaned[:-2].partition(":")
            hour, minute = int(hh), int(mm or 0)
        except ValueError:
            return raw
        if not (0 <= hour <= 12 and 0 <= minute <= 59):
            return raw
        hour = hour % 12 + (12 if meridiem == "PM" else 0)
        return f"{hour:02d}:{minute:02d}"

    def _draw_upcoming_center(self, draw: "ImageDraw.ImageDraw", game: Dict) -> None:
        """Draw the middle of an upcoming card.

        Never a score: an upcoming game has not started, so the extractor's
        0-0 is noise. Either the VS text (default), the date and time stacked,
        or nothing at all.
        """
        mode = self._upcoming_center_mode()
        if mode == "none":
            return

        if mode == "vs":
            vs_text = self._vs_text()
            if not vs_text:
                return
            vs_width = draw.textlength(vs_text, font=self.fonts['score'])
            vs_x = (self.display_width - vs_width) // 2 + self._layout_offset('score', 'x_offset')
            vs_y = (self.display_height // 2) - 3 + self._layout_offset('score', 'y_offset')
            self._draw_text_with_outline(
                draw, vs_text, (vs_x, vs_y), self.fonts['score'],
                fill=self._element_color('score_text')
            )
            return

        date_text, time_text = self._upcoming_date_and_time(game)
        lines = []
        if self._scroll_card_option("show_date", True):
            lines.append(self._format_game_date(date_text, game))
        if self._scroll_card_option("show_time", True):
            lines.append(self._format_game_time(time_text))
        lines = [t for t in lines if t]
        if not lines:
            return
        font = self.fonts.get('detail') or self.fonts['time']
        line_h = 7
        top = (self.display_height // 2) - (len(lines) * line_h) // 2
        top += self._layout_offset('score', 'y_offset')
        for i, line in enumerate(lines):
            width = draw.textlength(line, font=font)
            x = (self.display_width - width) // 2 + self._layout_offset('score', 'x_offset')
            self._draw_text_with_outline(
                draw, line, (x, top + i * line_h), font,
                fill=self._element_color('detail_text')
            )

    def _upcoming_date_and_time(self, game: Dict) -> Tuple[str, str]:
        """(date, time) for an upcoming card, from the extractor's flat keys."""
        return (
            str(game.get("game_date", "") or ""),
            str(game.get("game_time", "") or ""),
        )

    def _draw_upcoming_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw the date and time around an upcoming card.

        Time top and date bottom by default; scroll_card.swap_date_time puts
        the date on top instead. Skipped when the pair is stacked in the
        middle, which would otherwise print them twice.
        """
        if self._upcoming_center_mode() == "date_time":
            return

        date_raw, time_raw = self._upcoming_date_and_time(game)
        date_text = (self._format_game_date(date_raw, game)
                     if self._scroll_card_option("show_date", True) else "")
        time_text = (self._format_game_time(time_raw)
                     if self._scroll_card_option("show_time", True) else "")

        if self._scroll_card_option("swap_date_time", False):
            top_text, top_el, bottom_text, bottom_el = (
                date_text, 'date', time_text, 'time')
            top_font = self.fonts.get('detail') or self.fonts['time']
            bottom_font = self.fonts['time']
            top_color, bottom_color = 'detail_text', 'period_text'
        else:
            top_text, top_el, bottom_text, bottom_el = (
                time_text, 'time', date_text, 'date')
            top_font = self.fonts['time']
            bottom_font = self.fonts.get('detail') or self.fonts['time']
            top_color, bottom_color = 'period_text', 'detail_text'

        if top_text:
            top_width = draw.textlength(top_text, font=top_font)
            top_x = (self.display_width - top_width) // 2 + self._layout_offset(top_el, 'x_offset')
            top_y = 1 + self._layout_offset(top_el, 'y_offset')
            self._draw_text_with_outline(
                draw, top_text, (top_x, top_y), top_font,
                fill=self._element_color(top_color)
            )

        if bottom_text:
            bottom_width = draw.textlength(bottom_text, font=bottom_font)
            bottom_x = ((self.display_width - bottom_width) // 2
                        + self._layout_offset(bottom_el, 'x_offset'))
            # Measured, not a fixed -7: the detail font is 6px in most plugins
            # but 10px in soccer and nrl, where "Sep 19" ran past the card.
            ink_bottom = draw.textbbox((0, 0), bottom_text, font=bottom_font)[3]
            bottom_y = (max(0, self.display_height - ink_bottom - 1)
                        + self._layout_offset(bottom_el, 'y_offset'))
            self._draw_text_with_outline(
                draw, bottom_text, (bottom_x, bottom_y), bottom_font,
                fill=self._element_color(bottom_color)
            )

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
                    away_spread = -top_level_spread
            
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
            if favored_spread is not None:
                spread_text = str(favored_spread)
                font = self.fonts["detail"]

                if favored_side == "home":
                    spread_width = draw.textlength(spread_text, font=font)
                    spread_x = self.display_width - spread_width + odds_x_offset
                else:
                    spread_x = 0 + odds_x_offset
                spread_y = 0 + odds_y_offset
                
                self._draw_text_with_outline(draw, spread_text, (spread_x, spread_y), font, fill=(0, 255, 0))
            
            # Show over/under on opposite side
            over_under = odds.get("over_under")
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                font = self.fonts["detail"]
                ou_width = draw.textlength(ou_text, font=font)
                
                if favored_side == "home":
                    ou_x = 0 + odds_x_offset
                elif favored_side == "away":
                    ou_x = self.display_width - ou_width + odds_x_offset
                else:
                    ou_x = (self.display_width - ou_width) // 2 + odds_x_offset
                ou_y = 0 + odds_y_offset
                
                self._draw_text_with_outline(draw, ou_text, (ou_x, ou_y), font, fill=(0, 255, 0))
                
        except Exception as e:
            self.logger.error(f"Error drawing odds: {e}")
    
    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw team records or rankings."""
        record_font = getattr(self, '_record_font', None)
        if record_font is None:
            try:
                record_font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
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
