"""
Game Renderer for Football Scoreboard Plugin

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
from typing import Any, ClassVar, Dict, Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont
try:
    import freetype  # noqa: F401
    FREETYPE_AVAILABLE = True
except ImportError:
    FREETYPE_AVAILABLE = False

# Adaptive layout system (opt-in via layout_mode: "adaptive"). Older LEDMatrix
# cores don't ship it — fall back silently to the classic layout.
try:
    from src.adaptive_layout import (
        FitResult,
        FontStep,
        LADDER_ARCADE,
        LayoutContext,
        Region,
        measure_ink,
        scoreboard_regions,
    )
    ADAPTIVE_AVAILABLE = True
    # TTF-only ladders: this renderer outlines text via ImageDraw.text(),
    # which can't take the freetype BDF faces of the core grid ladder.
    #
    # Every rung here is verified crisp (measure_font_crispness == 0.0, see
    # test_adaptive_layout_mode.py::TestLadderCrispness): PressStart2P is a
    # pixel-grid font that PIL only rasterizes without antialiasing at exact
    # multiples of 8px — a 10px or 12px rung (tried in an earlier version,
    # to match classic's fixed 10px score) is 18-30% antialiased and reads
    # as blurry on an LED panel. "5by7.regular" never renders crisp at any
    # size in this range and was dropped entirely; "4x6-font" is crisp only
    # at 7px, not the 6px used previously.
    ADAPTIVE_LADDER_HEADLINE = LADDER_ARCADE + (
        FontStep("4x6-font", 7),
    )
    ADAPTIVE_LADDER_TEXT = (
        FontStep("press_start", 16),
        FontStep("press_start", 8),
        FontStep("4x6-font", 7),
    )
except ImportError:
    ADAPTIVE_AVAILABLE = False

# Shared element-style resolver (newer cores): one implementation of font
# loading and of the "did the user actually override this font?" check,
# referenced against this plugin's own config_schema.json. Older cores fall
# back to the local loader below.
try:
    from src.element_style import ElementStyleResolver, defaults_from_schema_file
    STYLE_AVAILABLE = True
except ImportError:
    STYLE_AVAILABLE = False

logger = logging.getLogger(__name__)

_shared_font_manager = None


def _get_font_manager():
    """Shared FontManager for adaptive font ladders (scans assets/fonts)."""
    global _shared_font_manager
    if _shared_font_manager is None:
        from src.font_manager import FontManager
        _shared_font_manager = FontManager({})
    return _shared_font_manager


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

        # Element-style resolver: schema defaults come from this plugin's own
        # config_schema.json so the user-override check works in every
        # context (production, harness, dev server). None on older cores.
        self._style_resolver = None
        if STYLE_AVAILABLE:
            schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'config_schema.json')
            self._style_resolver = ElementStyleResolver(
                config, defaults_from_schema_file(schema_path))

        # Load fonts
        self.fonts = self._load_fonts()

        # Adaptive layout (beta, opt-in): scales fonts/logos/regions to the
        # card size instead of the classic fixed-pixel layout. Default
        # "classic" renders byte-identically to previous releases.
        self.layout_mode = config.get('layout_mode', 'classic')
        self._adaptive = ADAPTIVE_AVAILABLE and self.layout_mode == 'adaptive'
        if self.layout_mode == 'adaptive' and not ADAPTIVE_AVAILABLE:
            self.logger.warning(
                "layout_mode 'adaptive' requires a LEDMatrix core with the "
                "adaptive layout system; falling back to classic layout"
            )
        if self._adaptive:
            self._ctx = LayoutContext(display_width, display_height,
                                      _get_font_manager(),
                                      design_size=(128, 32))
            self._raw_logo_cache: Dict[str, Image.Image] = {}
        
        # Display options are read dynamically per league (stored in config under league.display_options)
        # These defaults are kept for backward compatibility but should not be used
        self._default_show_odds = config.get("show_odds", False)
        self._default_show_records = config.get("show_records", False)
        self._default_show_ranking = config.get("show_ranking", False)
        
        # Rankings cache (populated externally)
        self._team_rankings_cache: Dict[str, int] = {}
        
    def _load_fonts(self) -> Dict[str, Union[ImageFont.FreeTypeFont, Any]]:
        """
        Load fonts used by the scoreboard from config or use defaults.
        
        Returns:
            Dictionary mapping font names to font objects (ImageFont.FreeTypeFont for TTF/OTF,
            freetype.Face for BDF fonts)
        """
        fonts = {}

        if self._style_resolver is not None:
            for font_key, (loader_font, loader_size) in self._LOADER_DEFAULTS.items():
                element = self._FONT_ELEMENT_KEYS.get(font_key, font_key)
                fonts[font_key] = self._style_resolver.style(
                    element, classic_font=loader_font,
                    classic_size=loader_size).font
            return fonts

        # Older cores (no src.element_style): the original local loader.
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
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, default_font='4x6-font.ttf')
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
    
    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf') -> Union[ImageFont.FreeTypeFont, Any]:
        """
        Load a custom font from an element configuration dictionary.
        
        Supports TTF/OTF fonts via ImageFont.truetype() and BDF fonts via freetype.Face().
        
        Returns:
            ImageFont.FreeTypeFont for TTF/OTF fonts, freetype.Face for BDF fonts, or fallback font
        """
        font_name = element_config.get('font', default_font)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)
        
        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf') or font_path.lower().endswith('.otf'):
                    # TTF/OTF fonts - use ImageFont.truetype()
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    # BDF fonts - ImageFont.truetype() does NOT support BDF files
                    # Option (b): Try to load pre-converted .pil/.pbm file (recommended approach)
                    # Use pilfont.py to convert: pilfont.py font.bdf (creates font.pil and font.pbm)
                    pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                    if os.path.exists(pil_font_path):
                        try:
                            font = ImageFont.load(pil_font_path)
                            self.logger.debug(f"Loaded BDF font from pre-converted PIL file: {pil_font_path}")
                            return font
                        except Exception:
                            # Pre-converted file exists but failed to load - will fall through to fallback
                            pass
                    
                    # If no pre-converted file or loading failed, BDF cannot be loaded directly
                    # Note: PIL.BdfFontFile doesn't exist in standard Pillow, so pre-conversion is required
                    # The warning will be logged only if fallback also fails (see below)
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, trying fallback")
            else:
                self.logger.warning(f"Font file not found: {font_path}, trying fallback")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, trying fallback")
        
        # Fallback to default font
        default_font_path = os.path.join('assets', 'fonts', default_font)
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception as e:
            # Default font also failed - log clear warning about BDF handling failure if this was a BDF font
            if font_path.lower().endswith('.bdf'):
                pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                self.logger.warning(
                    f"BDF font loading failed for {font_name}: "
                    f"No pre-converted .pil file found at {pil_font_path}. "
                    f"Convert BDF to PIL format using: pilfont.py {font_path}. "
                    f"Default font fallback also failed: {e}. Using PIL default font."
                )
            else:
                self.logger.warning(f"Could not load default font: {e}, using PIL default font")
        
        # Final fallback - only log warning for BDF fonts if we haven't already warned above
        if font_path.lower().endswith('.bdf'):
            # Check if we already logged a warning (if default font path didn't exist, we need to warn here)
            if not os.path.exists(default_font_path):
                pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                self.logger.warning(
                    f"BDF font {font_name} could not be loaded (no pre-converted .pil file found at {pil_font_path}). "
                    f"Using PIL default font. To fix: run 'pilfont.py {font_path}' to create {pil_font_path}"
                )
        
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
    
    def _draw_text_with_outline(
        self, 
        draw: ImageDraw.Draw, 
        text: str, 
        position: Tuple[int, int], 
        font: Union[ImageFont.FreeTypeFont, Any], 
        fill: Tuple[int, int, int] = (255, 255, 255), 
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """
        Draw text with a black outline for better readability.
        
        Note: BDF fonts loaded via freetype.Face() are not directly compatible with
        ImageDraw.text(). If a BDF font is passed, it will fall back to default font.
        """
        # Check if this is a freetype.Face (BDF font) - ImageDraw.text() doesn't support it
        if FREETYPE_AVAILABLE and hasattr(font, 'set_char_size'):
            # This is a freetype.Face (BDF font) - ImageDraw.text() won't work
            # Fall back to default font for rendering
            self.logger.warning("BDF font detected but ImageDraw.text() doesn't support freetype.Face - using default font for rendering")
            font = ImageFont.load_default()
        
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
        if self._adaptive:
            return self._render_game_card_adaptive(game, game_type)

        # Create base image
        main_img = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
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
        
        # Draw logos — each centered within a slot on its side, leaving the
        # centre gap clear so the score is never drawn on top of a logo.
        logo_slot = self._logo_slot_width()
        away_x = ((logo_slot - away_logo.width) // 2
                  + self._layout_offset('away_logo', 'x_offset'))
        away_y = (center_y - (away_logo.height // 2)
                  + self._layout_offset('away_logo', 'y_offset'))
        main_img.paste(away_logo, (away_x, away_y), away_logo)

        home_slot_start = self.display_width - logo_slot
        home_x = (home_slot_start + (logo_slot - home_logo.width) // 2
                  + self._layout_offset('home_logo', 'x_offset'))
        home_y = (center_y - (home_logo.height // 2)
                  + self._layout_offset('home_logo', 'y_offset'))
        main_img.paste(home_logo, (home_x, home_y), home_logo)

        # Draw scores (centered) — only once a game has started. Upcoming games
        # have no score, so the extractor's 0-0 was pure noise.
        if game_type in ("live", "recent"):
            home_score = str(game.get("home_score", "0"))
            away_score = str(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts['score'])
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
        
        # Get display options for this game's league
        game_league = game.get("league", "nfl")
        show_odds = self._get_display_option(game_league, "show_odds")
        show_records = self._get_display_option(game_league, "show_records")
        show_ranking = self._get_display_option(game_league, "show_ranking")
        
        # Draw odds if enabled
        if show_odds and 'odds' in game and game['odds']:
            self._draw_dynamic_odds(draw_overlay, game['odds'])
        
        # Draw records or rankings if enabled
        if show_records or show_ranking:
            self._draw_records_or_rankings(draw_overlay, game, show_records, show_ranking)
        
        # Composite the overlay onto main image
        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')
    
    # ------------------------------------------------------------------
    # Adaptive layout path (layout_mode: "adaptive", beta)
    #
    # Same card content as the classic path, but positions come from
    # scoreboard_regions() and fonts/logos scale to the card size. User
    # customization is preserved: an explicitly configured font/font_size
    # wins over the ladder, and customization.layout.<element> x/y offsets
    # translate the computed regions as a final step.
    # ------------------------------------------------------------------

    # fonts-dict key -> customization element key (for user-font detection)
    _FONT_ELEMENT_KEYS = {
        "score": "score_text",
        "time": "period_text",
        "team": "team_name",
        "status": "status_text",
        "detail": "detail_text",
        "rank": "rank_text",
    }

    # Per-element (font, size) the local loader falls back to when a config
    # key is absent — mirrors the _load_custom_font call sites exactly
    # (note status: PressStart, the loader's parameter default, even though
    # the schema declares 4x6 — a long-standing quirk kept for byte-identical
    # bare-config rendering).
    _LOADER_DEFAULTS = {
        'score': ('PressStart2P-Regular.ttf', 10),
        'time': ('PressStart2P-Regular.ttf', 8),
        'team': ('PressStart2P-Regular.ttf', 8),
        'status': ('PressStart2P-Regular.ttf', 6),
        'detail': ('4x6-font.ttf', 6),
        'rank': ('PressStart2P-Regular.ttf', 10),
    }

    # (font filename, size) the config_schema.json declares as each
    # element's default — matching these, not merely a key being *present*,
    # is what "user set it" has to mean, because the web UI's save flow
    # (schema_manager.merge_with_defaults) writes the FULL schema default
    # object into config.json on every save, for every plugin, whether or
    # not the user touched that section. Only used on older cores — with
    # src.element_style available, the resolver reads the schema file itself.
    _CLASSIC_FONT_DEFAULTS = {
        'score': ('PressStart2P-Regular.ttf', 10),
        'time': ('PressStart2P-Regular.ttf', 8),
        'team': ('PressStart2P-Regular.ttf', 8),
        'status': ('4x6-font.ttf', 6),
        'detail': ('4x6-font.ttf', 6),
        'rank': ('PressStart2P-Regular.ttf', 10),
    }

    def _user_font_set(self, font_key: str) -> bool:
        """True when the user's configured font/font_size for this element
        genuinely differs from the schema default — adaptive mode must
        respect a real override, but not a schema default that merely
        happens to be present in a saved config."""
        if self._style_resolver is not None:
            element = self._FONT_ELEMENT_KEYS.get(font_key, font_key)
            loader_font, loader_size = self._LOADER_DEFAULTS.get(
                font_key, ('PressStart2P-Regular.ttf', 8))
            return self._style_resolver.style(
                element, classic_font=loader_font,
                classic_size=loader_size).user_forced
        element = self._FONT_ELEMENT_KEYS.get(font_key, font_key)
        element_config = self.config.get('customization', {}).get(element, {})
        default_font, default_size = self._CLASSIC_FONT_DEFAULTS.get(font_key, (None, None))
        configured_font = element_config.get('font')
        configured_size = element_config.get('font_size')
        font_differs = configured_font is not None and configured_font != default_font
        try:
            size_differs = configured_size is not None and int(configured_size) != default_size
        except (TypeError, ValueError):
            size_differs = False
        return font_differs or size_differs

    def _region_for(self, region: "Region", element: str) -> "Region":
        """Apply the user's customization.layout.<element> x/y offsets as a
        final translation of the computed region."""
        if self._style_resolver is not None:
            dx, dy = self._style_resolver.offset(element)
        else:
            offsets = self.config.get('customization', {}).get('layout', {}).get(element, {})
            try:
                dx = int(offsets.get('x_offset', 0))
                dy = int(offsets.get('y_offset', 0))
            except (TypeError, ValueError):
                dx = dy = 0
        return region.offset(dx, dy) if (dx or dy) else region

    def _fit_element(self, font_key: str, text: str, region: "Region",
                     ladder) -> "FitResult":
        """Crisp font sized proportionally to this element's classic fixed
        size (self.fonts[font_key]'s configured size — the default, e.g.
        score=10/time=8/detail=6, unless the user overrode it) — unless the
        user forced a font, in which case use it as-is.

        Proportional, not "largest that fits": on a big panel the score's
        region has generous room, but the logos next to it scale by a fixed
        geometry factor (px()) — maximizing the score independently would
        let it balloon out of proportion (even overlapping the logos) well
        past what fits the classic composition, even though the pick is
        individually "correct" for its own box.

        Scaled by HEIGHT alone (not LayoutContext's conservative
        min(width_ratio, height_ratio)) to match how the card's own logos
        already scale (``logo_slot = min(height, width // 2)``) — a panel
        that only grows taller (e.g. 128x32 -> 128x64) should still grow
        the text, the same way it already grows the logos, or the text
        reads as under-scaled next to them.
        """
        if self._user_font_set(font_key):
            font = self.fonts[font_key]
            width, height, baseline, y_offset = measure_ink(text, font)
            return FitResult(font, "user", getattr(font, 'size', 0), text,
                             width, height, baseline, y_offset,
                             fits=(width <= region.w and height <= region.h),
                             line_height=height)
        base_size_px = getattr(self.fonts[font_key], 'size', 10)
        height_scale = self.display_height / self._ctx.design_size[1]
        return self._ctx.fit_text_proportional(text, region, base_size_px=base_size_px,
                                               ladder=ladder, scale=height_scale)

    def _draw_fit_outline(self, draw: ImageDraw.Draw, fit: "FitResult",
                          region: "Region", fill: Tuple[int, int, int] = (255, 255, 255),
                          align: str = "center", valign: str = "center") -> Tuple[int, int]:
        """Draw a fitted text ink-aligned in a region, with the classic black
        outline. Returns the ink's top-left position."""
        x, y = region.align_xy(fit.width, fit.height, align, valign)
        self._draw_text_with_outline(draw, fit.text, (x, y - fit.y_offset),
                                     fit.font, fill=fill)
        return (x, y)

    def _load_raw_logo(self, team_abbrev: str, logo_path) -> Optional[Image.Image]:
        """Load a logo unresized (the adaptive path fits it per region;
        results are cached per size by the LayoutContext)."""
        cached = self._raw_logo_cache.get(team_abbrev)
        if cached is not None:
            return cached
        try:
            if logo_path and os.path.exists(logo_path):
                logo = Image.open(logo_path)
                if logo.mode != "RGBA":
                    logo = logo.convert("RGBA")
                self._raw_logo_cache[team_abbrev] = logo
                return logo
        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}")
        return None

    def _render_game_card_adaptive(self, game: Dict[str, Any],
                                   game_type: str) -> Image.Image:
        width, height = self.display_width, self.display_height
        main_img = Image.new('RGBA', (width, height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        regs = scoreboard_regions(Region(0, 0, width, height), ctx=self._ctx)

        away_raw = self._load_raw_logo(game.get("away_abbr", ""), game.get("away_logo_path"))
        home_raw = self._load_raw_logo(game.get("home_abbr", ""), game.get("home_logo_path"))
        if not away_raw or not home_raw:
            draw = ImageDraw.Draw(main_img)
            self._draw_text_with_outline(
                draw,
                f"{game.get('away_abbr', '?')}@{game.get('home_abbr', '?')}",
                (5, 5),
                self.fonts['status']
            )
            return main_img.convert('RGB')

        for raw, slot, element, abbr in (
            (away_raw, regs.away_slot, 'away_logo', game.get("away_abbr", "")),
            (home_raw, regs.home_slot, 'home_logo', game.get("home_abbr", "")),
        ):
            slot = self._region_for(slot, element)
            ifit = self._ctx.fit_image(raw, slot, mode="fill_height",
                                       crop_to_ink=True,
                                       cache_key=f"logo:{abbr}")
            if not ifit.is_empty:
                x, y = slot.align_xy(ifit.width, ifit.height)
                main_img.paste(ifit.image, (x, y), ifit.image)

        # Score — largest crisp font that fits the center region. Only drawn
        # once a game has started: an upcoming game has no score, so the
        # extractor's 0-0 was a placeholder, not a result.
        score_region = self._region_for(regs.score_area, 'score')
        if game_type in ("live", "recent"):
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_fit = self._fit_element('score', score_text, score_region,
                                          ADAPTIVE_LADDER_HEADLINE)
            self._draw_fit_outline(draw_overlay, score_fit, score_region,
                                   fill=self._score_color_for(game, game_type))
        elif game_type == "upcoming" and self._upcoming_center_mode() == "vs":
            vs_text = self._vs_text()
            if vs_text:
                vs_fit = self._fit_element('score', vs_text, score_region,
                                           ADAPTIVE_LADDER_HEADLINE)
                self._draw_fit_outline(draw_overlay, vs_fit, score_region,
                                       fill=self._element_color('score_text'))

        if game_type == "live":
            self._draw_live_status_adaptive(draw_overlay, game, regs)
        elif game_type == "recent":
            top = game.get("period_text") or "Final"
            fit = self._fit_element('time', top,
                                    self._region_for(regs.status_band, 'status_text'),
                                    ADAPTIVE_LADDER_TEXT)
            self._draw_fit_outline(draw_overlay, fit,
                                   self._region_for(regs.status_band, 'status_text'))
            self._draw_bottom_center_adaptive(
                draw_overlay, self._format_game_date(game.get("game_date", ""), game),
                regs, 'date')
        elif game_type == "upcoming":
            game_date = (self._format_game_date(game.get("game_date", ""), game)
                         if self._scroll_card_option("show_date", True) else "")
            game_time = (self._format_game_time(game.get("game_time", ""))
                         if self._scroll_card_option("show_time", True) else "")
            if self._scroll_card_option("swap_date_time", False):
                game_date, game_time = game_time, game_date
            if self._upcoming_center_mode() == "none":
                pass
            elif self._upcoming_center_mode() != "vs":
                # Date and time stacked in the middle instead of top/bottom.
                stacked = " ".join(t for t in (game_date, game_time) if t)
                if stacked:
                    fit = self._fit_element('score', stacked, score_region,
                                            ADAPTIVE_LADDER_TEXT)
                    self._draw_fit_outline(draw_overlay, fit, score_region)
            else:
                if game_time:
                    region = self._region_for(regs.status_band, 'time')
                    fit = self._fit_element('time', game_time, region, ADAPTIVE_LADDER_TEXT)
                    self._draw_fit_outline(draw_overlay, fit, region)
                self._draw_bottom_center_adaptive(draw_overlay, game_date,
                                                  regs, 'date')

        game_league = game.get("league", "nfl")
        if self._get_display_option(game_league, "show_odds") and game.get('odds'):
            self._draw_dynamic_odds(draw_overlay, game['odds'])
        show_records = self._get_display_option(game_league, "show_records")
        show_ranking = self._get_display_option(game_league, "show_ranking")
        if show_records or show_ranking:
            self._draw_records_adaptive(draw_overlay, game, regs,
                                        show_records, show_ranking)

        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')

    def _draw_bottom_center_adaptive(self, draw: ImageDraw.Draw, text: str,
                                     regs, element: str,
                                     fill: Tuple[int, int, int] = (255, 255, 255)):
        """Fit text into the bottom detail band. Returns (x, y, fit) or None."""
        if not text:
            return None
        region = self._region_for(regs.detail_band, element)
        fit = self._fit_element('detail', text, region, ADAPTIVE_LADDER_TEXT)
        x, y = self._draw_fit_outline(draw, fit, region, fill=fill)
        return (x, y, fit)

    def _draw_live_status_adaptive(self, draw: ImageDraw.Draw, game: Dict,
                                   regs) -> None:
        # Period/quarter + clock in the top status band
        period_clock_text = f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
        if game.get("is_halftime"):
            period_clock_text = "Halftime"
        elif game.get("is_period_break"):
            period_clock_text = game.get("status_text", "Period Break")
        if period_clock_text:
            region = self._region_for(regs.status_band, 'status_text')
            fit = self._fit_element('time', period_clock_text, region,
                                    ADAPTIVE_LADDER_TEXT)
            self._draw_fit_outline(draw, fit, region)

        # Scoring event or down & distance in the bottom detail band —
        # semantic colors preserved from the classic layout
        scoring_event = game.get("scoring_event", "")
        down_distance = game.get("down_distance_text", "")
        if self.display_width > 128:
            down_distance = game.get("down_distance_text_long", down_distance)

        if scoring_event and game.get("is_live"):
            color = {
                "TOUCHDOWN": (255, 215, 0),
                "FIELD GOAL": (0, 255, 0),
                "PAT": (255, 165, 0),
            }.get(scoring_event, (255, 255, 255))
            self._draw_bottom_center_adaptive(draw, scoring_event, regs,
                                              'down_distance', fill=color)
        elif down_distance and game.get("is_live"):
            down_color = (255, 0, 0) if game.get("is_redzone", False) else (200, 200, 0)
            drawn = self._draw_bottom_center_adaptive(draw, down_distance, regs,
                                                      'down_distance', fill=down_color)
            if drawn:
                self._draw_possession_adaptive(draw, game, *drawn)

        self._draw_timeouts_adaptive(draw, game, regs)

    def _draw_possession_adaptive(self, draw: ImageDraw.Draw, game: Dict,
                                  dd_x: int, dd_y: int, fit) -> None:
        """Possession football anchored to the fitted down&distance text,
        radii scaled with the card."""
        possession = game.get("possession_indicator")
        if not possession:
            return
        ball_radius_x = self._ctx.px(3, minimum=2)
        ball_radius_y = self._ctx.px(2, minimum=1)
        padding = self._ctx.px(3, minimum=2)
        ball_y_center = dd_y + fit.height // 2
        if possession == "away":
            ball_x_center = dd_x - padding - ball_radius_x
        elif possession == "home":
            ball_x_center = dd_x + fit.width + padding + ball_radius_x
        else:
            return
        if ball_x_center > 0:
            draw.ellipse(
                (ball_x_center - ball_radius_x, ball_y_center - ball_radius_y,
                 ball_x_center + ball_radius_x, ball_y_center + ball_radius_y),
                fill=(139, 69, 19), outline=(0, 0, 0)
            )
            draw.line(
                (ball_x_center - 1, ball_y_center, ball_x_center + 1, ball_y_center),
                fill=(255, 255, 255), width=1
            )

    def _draw_timeouts_adaptive(self, draw: ImageDraw.Draw, game: Dict,
                                regs) -> None:
        """Timeout bars in the bottom corners, sized with the card."""
        bar_w = self._ctx.px(4, minimum=3)
        bar_h = self._ctx.px(2, minimum=2)
        spacing = self._ctx.px(1, minimum=1)
        margin = self._ctx.px(2, minimum=2)
        timeout_y = self.display_height - bar_h - 1

        left = self._region_for(regs.bottom_left, 'timeouts')
        away_timeouts = game.get("away_timeouts", 0)
        for i in range(3):
            to_x = left.x + margin + i * (bar_w + spacing)
            color = (255, 255, 255) if i < away_timeouts else (80, 80, 80)
            draw.rectangle([to_x, timeout_y, to_x + bar_w, timeout_y + bar_h],
                           fill=color, outline=(0, 0, 0))

        right = self._region_for(regs.bottom_right, 'timeouts')
        home_timeouts = game.get("home_timeouts", 0)
        for i in range(3):
            to_x = right.right - margin - bar_w - (2 - i) * (bar_w + spacing)
            color = (255, 255, 255) if i < home_timeouts else (80, 80, 80)
            draw.rectangle([to_x, timeout_y, to_x + bar_w, timeout_y + bar_h],
                           fill=color, outline=(0, 0, 0))

    def _draw_records_adaptive(self, draw: ImageDraw.Draw, game: Dict, regs,
                               show_records: bool, show_ranking: bool) -> None:
        """Records/rankings in the bottom corners, ladder-fitted."""
        for abbr_key, record_key, region, element, align in (
            ('away_abbr', 'away_record', regs.bottom_left, 'records', 'left'),
            ('home_abbr', 'home_record', regs.bottom_right, 'records', 'right'),
        ):
            abbr = game.get(abbr_key, '')
            if not abbr:
                continue
            text = self._get_team_display_text(abbr, game.get(record_key, ''),
                                               show_records, show_ranking)
            if not text:
                continue
            region = self._region_for(region, element).inset(2, 0)
            fit = self._fit_element('detail', text, region, ADAPTIVE_LADDER_TEXT)
            self._draw_fit_outline(draw, fit, region, align=align, valign="bottom")

    def _draw_live_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a live game."""
        # Period/Quarter and Clock (Top center)
        period_clock_text = f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
        if game.get("is_halftime"):
            period_clock_text = "Halftime"
        elif game.get("is_period_break"):
            period_clock_text = game.get("status_text", "Period Break")
        
        status_width = draw.textlength(period_clock_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_clock_text, (status_x, status_y), self.fonts['time'])
        
        # Down & Distance or Scoring Event (Bottom center)
        scoring_event = game.get("scoring_event", "")
        down_distance = game.get("down_distance_text", "")
        if self.display_width > 128:
            down_distance = game.get("down_distance_text_long", down_distance)
        
        if scoring_event and game.get("is_live"):
            # Display scoring event with special formatting
            event_width = draw.textlength(scoring_event, font=self.fonts['detail'])
            event_x = (self.display_width - event_width) // 2
            event_y = self.display_height - 7
            
            # Color coding for different scoring events
            if scoring_event == "TOUCHDOWN":
                event_color = (255, 215, 0)  # Gold
            elif scoring_event == "FIELD GOAL":
                event_color = (0, 255, 0)    # Green
            elif scoring_event == "PAT":
                event_color = (255, 165, 0)  # Orange
            else:
                event_color = (255, 255, 255)  # White
            
            self._draw_text_with_outline(draw, scoring_event, (event_x, event_y), self.fonts['detail'], fill=event_color)
        elif down_distance and game.get("is_live"):
            dd_width = draw.textlength(down_distance, font=self.fonts['detail'])
            dd_x = (self.display_width - dd_width) // 2
            dd_y = self.display_height - 7
            down_color = (200, 200, 0) if not game.get("is_redzone", False) else (255, 0, 0)
            self._draw_text_with_outline(draw, down_distance, (dd_x, dd_y), self.fonts['detail'], fill=down_color)
            
            # Possession indicator
            self._draw_possession_indicator(draw, game, dd_x, dd_width, dd_y)
        
        # Timeouts
        self._draw_timeouts(draw, game)
    
    def _draw_recent_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a recently completed game."""
        # Final status (Top center)
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

    def _draw_possession_indicator(
        self, 
        draw: ImageDraw.Draw, 
        game: Dict, 
        dd_x: int, 
        dd_width: float, 
        dd_y: int
    ) -> None:
        """Draw the possession football indicator."""
        possession = game.get("possession_indicator")
        if not possession:
            return
        
        ball_radius_x = 3
        ball_radius_y = 2
        ball_color = (139, 69, 19)  # Brown
        lace_color = (255, 255, 255)  # White
        
        detail_font_height_approx = 6
        ball_y_center = dd_y + (detail_font_height_approx // 2)
        possession_ball_padding = 3
        
        if possession == "away":
            ball_x_center = dd_x - possession_ball_padding - ball_radius_x
        elif possession == "home":
            ball_x_center = dd_x + int(dd_width) + possession_ball_padding + ball_radius_x
        else:
            return
        
        if ball_x_center > 0:
            # Draw football shape (ellipse)
            draw.ellipse(
                (ball_x_center - ball_radius_x, ball_y_center - ball_radius_y,
                 ball_x_center + ball_radius_x, ball_y_center + ball_radius_y),
                fill=ball_color, outline=(0, 0, 0)
            )
            # Draw simple horizontal lace
            draw.line(
                (ball_x_center - 1, ball_y_center, ball_x_center + 1, ball_y_center),
                fill=lace_color, width=1
            )
    
    def _draw_timeouts(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw timeout indicators at bottom corners."""
        timeout_bar_width = 4
        timeout_bar_height = 2
        timeout_spacing = 1
        timeout_y = self.display_height - timeout_bar_height - 1
        
        # Away Timeouts (Bottom Left)
        away_timeouts_remaining = game.get("away_timeouts", 0)
        for i in range(3):
            to_x = 2 + i * (timeout_bar_width + timeout_spacing)
            color = (255, 255, 255) if i < away_timeouts_remaining else (80, 80, 80)
            draw.rectangle(
                [to_x, timeout_y, to_x + timeout_bar_width, timeout_y + timeout_bar_height],
                fill=color, outline=(0, 0, 0)
            )
        
        # Home Timeouts (Bottom Right)
        home_timeouts_remaining = game.get("home_timeouts", 0)
        for i in range(3):
            to_x = self.display_width - 2 - timeout_bar_width - (2 - i) * (timeout_bar_width + timeout_spacing)
            color = (255, 255, 255) if i < home_timeouts_remaining else (80, 80, 80)
            draw.rectangle(
                [to_x, timeout_y, to_x + timeout_bar_width, timeout_y + timeout_bar_height],
                fill=color, outline=(0, 0, 0)
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
            
            # Show the negative spread
            # customization.layout.odds is declared in this plugin's config
            # schema, so the web UI offers x_offset and y_offset -- but nothing
            # here ever read them, and the odds drew at a fixed 0,0. A control
            # that visibly does nothing is worse than no control, since the
            # user concludes the position is unfixable.
            odds_x_offset = self._layout_offset('odds', 'x_offset')
            odds_y_offset = self._layout_offset('odds', 'y_offset')

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
    
    def _get_display_option(self, league: str, option: str) -> bool:
        """
        Get a display option for a specific league from the nested config structure.
        
        Args:
            league: League identifier ('nfl', 'ncaa_fb', etc.)
            option: Option name ('show_odds', 'show_records', 'show_ranking')
            
        Returns:
            Boolean value of the option, or False if not found
        """
        # Read from nested path: config[league]["display_options"][option]
        league_config = self.config.get(league, {})
        display_options = league_config.get("display_options", {})
        value = display_options.get(option, False)
        
        # Fallback to root-level config for backward compatibility
        if value is False and option in self.config:
            value = self.config.get(option, False)
        
        return bool(value)
    
    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict, show_records: bool, show_ranking: bool) -> None:
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
            away_text = self._get_team_display_text(away_abbr, game.get('away_record', ''), show_records, show_ranking)
            if away_text:
                away_record_x = 3
                self._draw_text_with_outline(draw, away_text, (away_record_x, record_y), record_font)
        
        # Home team info
        if home_abbr:
            home_text = self._get_team_display_text(home_abbr, game.get('home_record', ''), show_records, show_ranking)
            if home_text:
                home_record_bbox = draw.textbbox((0, 0), home_text, font=record_font)
                home_record_width = home_record_bbox[2] - home_record_bbox[0]
                home_record_x = self.display_width - home_record_width - 3
                self._draw_text_with_outline(draw, home_text, (home_record_x, record_y), record_font)
    
    def _get_team_display_text(self, abbr: str, record: str, show_records: bool, show_ranking: bool) -> str:
        """Get the display text for a team (ranking or record)."""
        if show_ranking and show_records:
            # Rankings replace records when both are enabled
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif show_records:
            return record
        return ''




