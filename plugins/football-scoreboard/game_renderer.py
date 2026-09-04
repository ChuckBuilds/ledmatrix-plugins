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

import dataclasses
import logging
import os
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Tuple, Union
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
    # The down & distance line only -- NOT the clock, status band, records or
    # dates, which keep ADAPTIVE_LADDER_TEXT and the arcade face above.
    #
    # This line is the longest string on the card ("3rd & 8 at KC 42" is 16
    # characters against the score's 5) and the one with the least room, since
    # it shares its row with the timeout bars and the records. On PressStart2P,
    # roughly four times wider per character than the 4x6 face, it rendered
    # 128px wide on a 192x48 panel where the classic layout draws it in 65px,
    # and on a 256x128 it reached 16px = 256px -- the full card, clipped at
    # both ends, with nowhere for the possession ball beside it.
    #
    # Both rungs are verified crisp (measure_font_crispness == 0.0): 4x6-font
    # is a pixel-grid face, exact at 7px and at its 14px double. Going below
    # 7px is not an option -- 6px measures 0.35 antialiased and 5px 0.55, which
    # smears on a real LED panel.
    ADAPTIVE_LADDER_DETAIL = (
        FontStep("4x6-font", 14),
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


# --- Possession indicator -------------------------------------------------
#
# Football-only. The other seven game_renderer.py lineage copies have no
# possession concept, so these have no sibling to be ported to; they live here
# rather than in football.py because game_renderer draws the ball on two of the
# three code paths and football.py on the third, and the three must agree.
#
# The ball used to be a hardcoded 7x5 ellipse placed a fixed 3px from the down
# & distance text, guarded only by `ball_x_center > 0`. On a narrow panel that
# put it on top of the timeout bars and the record text, and it stayed 7x5 on a
# tall panel where it read as a dash rather than a football.

POSSESSION_BALL_COLOR = (139, 69, 19)
POSSESSION_LACE_COLOR = (255, 255, 255)


# The classic ball. Deliberately NOT scaled: the size was never the problem,
# and every pixel it grows is a pixel of down & distance the row has to give
# up -- on a 64x32 the whole free band is only about 30px wide.
POSSESSION_BALL_SIZE = (7, 5)


def draw_possession_football(draw: ImageDraw.Draw, box) -> None:
    """Draw the possession football filling box = (x0, y0, x1, y1) inclusive.

    Same ellipse and centre lace both call sites drew before; only where the
    box comes from has changed.
    """
    x0, y0, x1, y1 = (int(v) for v in box)
    draw.ellipse((x0, y0, x1, y1), fill=POSSESSION_BALL_COLOR, outline=(0, 0, 0))
    cx = x0 + (x1 - x0) // 2
    cy = y0 + (y1 - y0) // 2
    draw.line((cx - 1, cy, cx + 1, cy), fill=POSSESSION_LACE_COLOR, width=1)


def possession_ball_box(text_x, text_width, text_height, text_y,
                        left_limit: int, right_limit: int,
                        possession: Optional[str],
                        icon_size: Tuple[int, int] = POSSESSION_BALL_SIZE,
                        gap: int = 3):
    """Where the possession ball goes beside an already-placed down & distance
    string, or None when there is no room for it clear of the corners.

    The ball never pushes the text around. On a cramped panel -- a 64x32 leaves
    about 30px between the timeout bars and the text alone wants 29 of them --
    the down & distance is worth more than the indicator, so the ball is
    dropped rather than the wording shortened or the timeout bars overdrawn.

    *left_limit* / *right_limit* bound the space the timeout bars and the
    record text leave free.
    """
    if not possession:
        return None
    icon_w, icon_h = icon_size
    # *gap* is the clear space between the text edge and the ball edge, which
    # is what the old centre-and-radius arithmetic worked out to. Keeping it
    # exact means the ball lands on the same pixel it always did wherever it
    # still fits.
    if possession == "away":
        x = int(text_x) - gap - icon_w + 1
    elif possession == "home":
        x = int(text_x + text_width) + gap
    else:
        return None
    if x < left_limit or x + icon_w > right_limit:
        return None
    # Centred on the text exactly as the old fixed-offset arithmetic did
    y = int(text_y) + int(text_height) // 2 - icon_h // 2
    return (x, y, x + icon_w - 1, y + icon_h - 1)


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
        self.fonts = self._unshare_element_fonts(self._load_fonts())

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
        
    #: Panel height the classic font sizes were chosen against.
    _FONT_BASELINE_HEIGHT: ClassVar[int] = 32

    #: Pixel grid each bundled font is drawn on. These are pixel-art faces:
    #: they rasterise cleanly only at whole multiples of their grid, and at
    #: any other size FreeType anti-aliases to fake the in-between stroke
    #: widths. On an LED matrix every pixel is a physical lamp, so a grey
    #: edge pixel is not a soft edge -- it is a dim lamp, and the text reads
    #: as smeared. Measured, not assumed: rendering "01/13 O45.5 17-21" at
    #: 5..40px, these are the only sizes with zero part-lit pixels.
    #: Below this the gap between the logos cannot hold a legible score, so
    #: the original (overlapping) region is kept rather than collapsing it.
    _MIN_ADAPTIVE_SCORE_WIDTH_PX: ClassVar[int] = 16

    _FONT_PIXEL_GRID: ClassVar[Dict[str, int]] = {
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

    def _detail_font_size(self, base: int = 6) -> int:
        """Odds/detail size: one grid step of the detail face, at every height.

        This used to scale with panel height, on the reasoning that 6px odds
        read as an afterthought on a 64-tall panel. Two things were wrong with
        that. The sizes it produced (6px, then 10px) are both off the 4x6
        face's 7px grid, so the glyphs were anti-aliased -- on an LED matrix
        that is a dim lamp, not a soft edge, and it is why the odds looked
        broken rather than small. And the larger size did not fit: the
        over/under is budgeted against the centre text, and at 10px it lost
        that contest and was dropped entirely, so growing the font cost half
        the odds.

        One crisp grid step reads clearly at every height and leaves room for
        both numbers. Kept as a method rather than a constant because a user
        who sets a size explicitly still overrides it.

        Superseded reasoning, for the record:

        The odds are drawn in the detail font, pinned at 6px because that is
        what suited a 32-tall panel. On a 64-tall one everything around them
        doubled -- logos, card, score -- and the odds stayed 6px, which is why
        they read as an afterthought squeezed into the corners rather than
        part of the card.

        Scaled by height and capped, so a 32-tall panel keeps exactly the 6px
        it always had and only taller panels move. A user-configured size is
        untouched; this only moves the default.

        The cap is 1.75x rather than the 2x the height ratio would give. At 2x
        (12px on a 64-tall panel) the over/under no longer fits beside the
        centre text and the collision guard drops it altogether -- the odds
        would get bigger by losing half of themselves. 1.75x (10px) was the
        largest size measured to still render both over/under and spread.
        """
        return self._FONT_PIXEL_GRID.get('4x6-font.ttf', base)

    def _schema_font_size(self, element_key):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.schema_font_size(_SCHEMA_PATH, element_key)

    def _resolve_font_size(self, element_config, element_key, default_size, font_name):
        """Delegates to src.common.sports_card, shared by every scoreboard."""
        return _card.resolve_font_size(_SCHEMA_PATH, element_config, element_key,
                                       default_size, font_name,
                                       self._FONT_NAME_ALIASES, self._FONT_PIXEL_GRID)

    def _snap_resolved_fonts(self, fonts):
        """Re-snap a resolver-supplied font whose SIZE was never really chosen.

        The resolver hands back the configured face and size whenever either
        differs from the schema default. That is right for the face, but it
        lets an unchosen size ride along: a config that changes only the FONT
        (say detail from 4x6-font to PressStart2P) keeps the schema's 6px,
        which is off PressStart2P's 8px grid, so the glyphs anti-alias.

        Where the configured size merely echoes the schema default, snap it to
        whatever face actually ended up in use. A size the user genuinely
        changed is left alone.
        """
        customization = self.config.get('customization', {}) or {}
        for font_key, font in list(fonts.items()):
            element = self._FONT_ELEMENT_KEYS.get(font_key, font_key)
            size = getattr(font, 'size', None)
            path = getattr(font, 'path', None)
            if not size or not isinstance(path, str):
                continue
            configured = (customization.get(element) or {}).get('font_size')
            if configured is None:
                continue
            try:
                if int(configured) != self._schema_font_size(element):
                    continue                      # a real choice: leave it
            except (TypeError, ValueError):
                continue
            face = os.path.basename(path)
            crisp = self._crisp_size(face, size)
            if crisp and crisp != size:
                try:
                    fonts[font_key] = ImageFont.truetype(path, crisp)
                except Exception:
                    self.logger.debug("Could not re-snap %s", font_key, exc_info=True)
        return fonts

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
                if font_key in ('detail', 'odds'):
                    # _detail_font_size already picks a size deliberately --
                    # grid-aligned on tall panels, and off-grid at 6px on 32
                    # tall ones where the over/under would not survive 7px.
                    # Re-snapping here would undo that.
                    loader_size = self._detail_font_size(loader_size)
                else:
                    # Snap the DEFAULT to the font's pixel grid. A size the
                    # user set explicitly is passed through untouched by the
                    # resolver, so this only moves a default we chose.
                    loader_size = self._crisp_size(loader_font, loader_size)
                fonts[font_key] = self._style_resolver.style(
                    element, classic_font=loader_font,
                    classic_size=loader_size).font
            return self._snap_resolved_fonts(fonts)

        # Older cores (no src.element_style): the original local loader.
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
            _ps = 'PressStart2P-Regular.ttf'
            # Sizes resolved first: a _crisp_size() call nested in the argument
            # list put a classmethod call and a keyword argument on one line,
            # which is how element_key ended up passed to the wrong callable
            # once already, and which static analysis still reads that way.
            score_size = self._crisp_size(_ps, 10)
            time_size = self._crisp_size(_ps, 8)
            team_size = self._crisp_size(_ps, 8)
            status_size = self._crisp_size(_ps, 6)
            rank_size = self._crisp_size(_ps, 10)
            fonts["score"] = self._load_custom_font(
                score_config, default_size=score_size, element_key='score_text')
            fonts["time"] = self._load_custom_font(
                period_config, default_size=time_size, element_key='period_text')
            fonts["team"] = self._load_custom_font(
                team_config, default_size=team_size, element_key='team_name')
            fonts["status"] = self._load_custom_font(
                status_config, default_size=status_size, element_key='status_text')
            fonts["detail"] = self._load_custom_font(
                detail_config,
                default_size=self._detail_font_size(), element_key='detail_text',
                default_font='4x6-font.ttf')
            fonts["odds"] = self._load_custom_font(
                odds_config,
                default_size=self._detail_font_size(), element_key='odds_text',
                default_font='4x6-font.ttf')
            fonts["rank"] = self._load_custom_font(
                rank_config, default_size=rank_size, element_key='rank_text')
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
    
    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf', element_key=None) -> Union[ImageFont.FreeTypeFont, Any]:
        """
        Load a custom font from an element configuration dictionary.
        
        Supports TTF/OTF fonts via ImageFont.truetype() and BDF fonts via freetype.Face().
        
        Returns:
            ImageFont.FreeTypeFont for TTF/OTF fonts, freetype.Face for BDF fonts, or fallback font
        """
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
        default_font_path = _resolve_font_path(os.path.join('assets', 'fonts', default_font))
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
        # Look up under the same size-scoped key the entries are stored under.
        # This checked the bare abbreviation while every write used
        # "<abbr>@<slot>x<height>", so the lookup never matched and each card
        # re-opened and re-resized both PNGs -- on the scroll path, once per
        # game per rebuild.
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
        "odds": "odds_text",
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
        font: Union[ImageFont.FreeTypeFont, Any], 
        fill: Optional[Tuple[int, int, int]] = None, 
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
        if self._adaptive:
            return self._render_game_card_adaptive(game, game_type)

        # Create base image
        main_img = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        draw_overlay.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        
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
            draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
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
            self._draw_dynamic_odds(
                draw_overlay, game['odds'],
                centre_text=self._centre_row_text(game, game_type))
        
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
        "odds": "odds_text",
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
        # Same default as detail: odds rendered with the detail font until
        # this setting existed, and the default must not change that.
        'odds': ('4x6-font.ttf', 6),
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
        'odds': ('4x6-font.ttf', 6),
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
                     ladder, *, snap_to_grid: bool = False) -> "FitResult":
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

        ``snap_to_grid`` is opt-in per CALL, not per font key, because the
        score font is used for three different things: the score itself, the
        "VS" separator on an upcoming card, and that card's stacked
        date/time. Only the first is a score. Keying the snap on
        ``font_key == 'score'`` grew the "VS" to 16px on a 192x48 panel --
        a separator sized like a headline, for a card with no result to
        report.

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
        if snap_to_grid:
            # Snap the score's target to the face's pixel grid before the
            # ladder sees it, so it lands ON a rung instead of just under one.
            #
            # fit_text_proportional takes the largest rung <= target, and the
            # arcade ladder's rungs are 8 / 16 / 24 / 32. A 48-tall panel gives
            # 8 * (48/32) = 12, which is short of 16, so the score stayed at 8
            # -- the same size the classic layout was stuck at, and the same
            # size as the clock above it. Snapping 12 to the nearest crisp
            # size first makes the target exactly 16 and the rung reachable,
            # and it uses the same _crisp_size() the classic path does, so the
            # two layouts pick the same score size on the same panel.
            face = os.path.basename(
                getattr(self.fonts[font_key], 'path', '') or '')
            snapped = self._crisp_size(face, base_size_px * height_scale)
            if snapped:
                base_size_px, height_scale = snapped, 1.0
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

    #: Ladder rung the adaptive score should be able to reach. 8 is what fits
    #: a 48px gap and matches classic, but reads thin on a tall card; 24 needs
    #: a 128px gap and buys mostly dead space. 16 doubles the score for 40px
    #: of extra card and costs nothing in logo size.
    _ADAPTIVE_SCORE_TARGET_PX: ClassVar[int] = 16

    def _adaptive_score_gap(self) -> int:
        """Middle width needed for the adaptive score to reach its target rung.

        Only meaningful in adaptive layout, where the score is fitted to the
        strip between the logos from a ladder of crisp sizes. The gap is what
        decides which rung it gets, so this reports the width that rung needs
        plus the same gutter the classic path keeps.

        Returns 0 if the target size cannot be measured, which leaves the
        caller's own gap untouched.
        """
        try:
            probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
            font = ImageFont.truetype(
                _resolve_font_path("assets/fonts/PressStart2P-Regular.ttf"),
                self._ADAPTIVE_SCORE_TARGET_PX)
            needed = (int(probe.textlength("00-00", font=font))
                      + 2 * self._SCORE_LOGO_GUTTER_PX)

            # Ask the fitter whether it would actually use the bigger rung on
            # a card this tall, rather than assume it. The fit is context
            # dependent, not purely a matter of region size: the same 88x31
            # region takes 16px on a 64-tall card and only 8px on a 48-tall
            # one. Widening the gap where the rung is unreachable would buy
            # nothing but dead space either side of an 8px score.
            card = max(128, self.display_height * 2 + needed)
            regs = scoreboard_regions(
                Region(0, 0, card, self.display_height), ctx=self._ctx)
            fit = self._fit_element(
                'score', "00-00",
                self._region_for(self._score_clear_of_logos(regs), 'score'),
                ADAPTIVE_LADDER_HEADLINE, snap_to_grid=True)
            got = getattr(getattr(fit, 'font', None), 'size', 0) or 0
            return needed if got >= self._ADAPTIVE_SCORE_TARGET_PX else 0
        except Exception:
            self.logger.debug("Adaptive score gap probe failed", exc_info=True)
            return 0

    #: Width the adaptive logo slots aim for, as a multiple of the card
    #: height. The core sizes those slots SQUARE (capped at the card height),
    #: which suits the roughly square marks -- Steelers, TCU -- but leaves the
    #: wide ones short, because a logo scaled to fill a square slot runs out
    #: of width long before it runs out of height. 1.54 is the aspect of the
    #: common wide marks (Green Bay's oval, Kansas City's arrowhead), so a
    #: slot this wide lets them reach full height. Wider than this only helps
    #: the rarer ~1.8 marks and costs marquee width for everything else.
    _LOGO_SLOT_ASPECT: ClassVar[float] = 1.54

    def _adaptive_logo_slot_width(self) -> int:
        """Slot width the wide logos need to reach the full card height."""
        return max(1, int(round(self.display_height * self._LOGO_SLOT_ASPECT)))

    def _widen_logo_slots(self, regs):
        """Give the logos slots wide enough to fill the card height.

        scoreboard_regions() caps each slot at the card height, and widening
        the CARD does not change that -- every extra pixel goes to the middle
        instead (a 400px card still gets a 64px slot on a 64-tall panel). So a
        1.54:1 logo renders 64x41 in a square slot: full width, well short of
        full height, which is why the wide marks looked smaller than the
        square ones rather than any difference between leagues.

        The slots are pinned to the outer edges and the middle keeps whatever
        is left, which is the gap _default_game_card_width already sized for
        the score. Narrows nothing: if the core's slot is already at least
        this wide, or the card is too narrow to leave a usable middle, the
        regions are returned untouched.
        """
        slot = self._adaptive_logo_slot_width()
        away, home = regs.away_slot, regs.home_slot
        if slot <= away.w:
            return regs
        # Card width comes from the REGIONS, not from self: the helper must
        # describe whatever layout it was handed, and reading self.display_width
        # made it widen regions belonging to a narrower card.
        card = home.x + home.w
        # The middle has to keep enough room for the score. A bare
        # _MIN_ADAPTIVE_SCORE_WIDTH_PX is not enough of a bar -- an 18px
        # middle clears it and still crushes the score onto the 7px rung --
        # so require the gap the score is actually sized for.
        required = max(self._MIN_ADAPTIVE_SCORE_WIDTH_PX, self._center_gap_width())
        if card - 2 * slot < required:
            return regs
        return dataclasses.replace(
            regs,
            away_slot=dataclasses.replace(away, x=0, w=slot),
            home_slot=dataclasses.replace(home, x=card - slot, w=slot))

    def _score_clear_of_logos(self, regs):
        """Trim the score region back to the strip between the two logos.

        The core's scoreboard_regions() deliberately overlaps score_area with
        BOTH logo slots -- by exactly half the logo's width at every card size
        (128x64: away[0,44] score[22,106] home[84,128]). The score is then
        fitted to that region, so it grows until it spans the logos and is
        drawn on top of them. That is the overlap reported against the Vegas
        ticker, and it is why widening the card never helped: the regions
        scale proportionally and the overlap stays at half the logo.

        Classic already keeps the score on its own strip. Clamping the region
        to the gap between the slots brings adaptive to the same arrangement:
        the ladder simply picks the largest rung that fits the real space, so
        the score lands beside the logos rather than across them, and comes
        out at a comparable size to classic's.

        The region is only ever narrowed, never widened, and a card whose
        logos leave no usable middle keeps the original region rather than
        collapsing to nothing.
        """
        # Deliberately not wrapped in try/except. An earlier version was, and
        # when the constant below was accidentally defined at module scope
        # instead of on the class, the AttributeError went straight into the
        # handler and the clamp silently did nothing -- the overlap looked
        # unfixed, with no error anywhere. A mistake in this arithmetic should
        # be loud.
        area, away, home = regs.score_area, regs.away_slot, regs.home_slot
        left = max(area.x, away.x + away.w)
        right = min(area.x + area.w, home.x)
        if right - left < self._MIN_ADAPTIVE_SCORE_WIDTH_PX:
            return area
        return area.__class__(left, area.y, right - left, area.h)

    def _status_ladder(self):
        """Ladder for the top status band, never coarser than the score.

        The status band spans the FULL card width, while the score is confined
        to the strip between the logos. Once the card is widened so the score
        can reach a bigger rung, the band widens with it -- and on a 96- or
        128-tall card "Final" reached the same 16px rung as the score, so the
        secondary text ended up as large as the headline it sits above.

        Capping the band one rung below whatever the score actually took keeps
        the hierarchy the classic layout has. When there is no score on the
        card (an upcoming game) the full ladder is used unchanged.
        """
        score_px = getattr(self, '_adaptive_score_px', 0) or 0
        if not score_px:
            return ADAPTIVE_LADDER_TEXT
        # Never LARGER than the score, and strictly smaller once the score is
        # above the 8px floor. At the floor itself equal is right: capping
        # below 8 drops the band onto 4x6-font, a different and narrower
        # letterform, on exactly the small panels where nothing was wrong.
        # Allowing "equal" only at the floor also stops the band jumping to
        # 16px when a squeezed card pushes the score down to 8.
        cap = score_px if score_px <= 8 else score_px - 1
        # FontStep's field is size_px, not size. Getting that wrong made the
        # filter match nothing, and the fallback below then silently returned
        # a ladder rather than raising -- so the cap appeared to do nothing.
        allowed = tuple(step for step in ADAPTIVE_LADDER_TEXT
                        if getattr(step, 'size_px', 0) <= cap)
        return allowed or ADAPTIVE_LADDER_TEXT[-1:]

    def _render_game_card_adaptive(self, game: Dict[str, Any],
                                   game_type: str) -> Image.Image:
        width, height = self.display_width, self.display_height
        main_img = Image.new('RGBA', (width, height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        draw_overlay.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        regs = self._widen_logo_slots(
            scoreboard_regions(Region(0, 0, width, height), ctx=self._ctx))
        self._adaptive_score_px = 0

        away_raw = self._load_raw_logo(game.get("away_abbr", ""), game.get("away_logo_path"))
        home_raw = self._load_raw_logo(game.get("home_abbr", ""), game.get("home_logo_path"))
        if not away_raw or not home_raw:
            draw = ImageDraw.Draw(main_img)
            draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
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
        score_region = self._region_for(
            self._score_clear_of_logos(regs), 'score')
        if game_type in ("live", "recent"):
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_fit = self._fit_element('score', score_text, score_region,
                                          ADAPTIVE_LADDER_HEADLINE,
                                          snap_to_grid=True)
            self._adaptive_score_px = getattr(
                getattr(score_fit, 'font', None), 'size', 0) or 0
            self._draw_fit_outline(draw_overlay, score_fit, score_region,
                                   fill=self._score_color_for(game, game_type))
        elif game_type == "upcoming" and self._upcoming_center_mode() == "vs":
            vs_text = self._vs_text()
            if vs_text:
                vs_fit = self._fit_element('score', vs_text, score_region,
                                           ADAPTIVE_LADDER_HEADLINE)
                # The centre element is this card's headline, exactly as the
                # score is on a played game, so the status band is measured
                # against it too. Without this an upcoming card left the band
                # uncapped and the kick-off time came out at the same 16px as
                # the "@" -- twice the size the same band gets on a recent
                # card, and the largest thing on the card.
                self._adaptive_score_px = getattr(
                    getattr(vs_fit, 'font', None), 'size', 0) or 0
                self._draw_fit_outline(draw_overlay, vs_fit, score_region,
                                       fill=self._element_color('score_text'))

        if game_type == "live":
            self._draw_live_status_adaptive(draw_overlay, game, regs)
        elif game_type == "recent":
            top = game.get("period_text") or "Final"
            fit = self._fit_element('time', top,
                                    self._region_for(regs.status_band, 'status_text'),
                                    self._status_ladder())
            # Coloured by the face it is fitted in, same rule as the classic
            # card: this line is set in the period face, so period_text's
            # colour applies. The ladder's fonts are not element-owned, so the
            # identity lookup cannot resolve these -- the fill is named here.
            self._draw_fit_outline(draw_overlay, fit,
                                   self._region_for(regs.status_band, 'status_text'),
                                   fill=self._element_color('period_text'))
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
                    # The stacked centre stands in for the score, set in the
                    # score face, so it takes score_text's colour.
                    self._draw_fit_outline(draw_overlay, fit, score_region,
                                           fill=self._element_color('score_text'))
            else:
                if game_time:
                    region = self._region_for(regs.status_band, 'time')
                    # Same band, same rule as a played game's status line:
                    # never larger than the card's centre element.
                    fit = self._fit_element('time', game_time, region,
                                            self._status_ladder())
                    self._draw_fit_outline(draw_overlay, fit, region,
                                           fill=self._element_color('period_text'))
                self._draw_bottom_center_adaptive(draw_overlay, game_date,
                                                  regs, 'date')

        game_league = game.get("league", "nfl")
        if self._get_display_option(game_league, "show_odds") and game.get('odds'):
            self._draw_dynamic_odds(
                draw_overlay, game['odds'],
                centre_text=self._centre_row_text(game, game_type))
        show_records = self._get_display_option(game_league, "show_records")
        show_ranking = self._get_display_option(game_league, "show_ranking")
        if show_records or show_ranking:
            self._draw_records_adaptive(draw_overlay, game, regs,
                                        show_records, show_ranking)

        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')

    def _draw_bottom_center_adaptive(self, draw: ImageDraw.Draw, text: str,
                                     regs, element: str,
                                     fill: Optional[Tuple[int, int, int]] = None):
        """Fit text into the bottom detail band. Returns (x, y, fit) or None.

        The band is set in the detail face, so an unspecified fill takes
        detail_text's colour; the scoring-event and down-distance callers pass
        their semantic colours explicitly and still win.
        """
        if not text:
            return None
        if fill is None:
            fill = self._element_color('detail_text')
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
                                    self._status_ladder())
            self._draw_fit_outline(draw, fit, region,
                                   fill=self._element_color('period_text'))

        # Scoring event or down & distance in the bottom detail band —
        # semantic colors preserved from the classic layout
        scoring_event = game.get("scoring_event", "")
        down_distance = game.get("down_distance_text", "")

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
            # Fitted here rather than via _draw_bottom_center_adaptive so the
            # detail ladder applies to this line alone -- that helper is also
            # what draws the scoring event, the dates and the status text.
            region = self._region_for(regs.detail_band, 'down_distance')
            left, right = self._bottom_free_band_adaptive(draw, game, regs)

            # Prefer the long form -- it carries the yardage -- whenever it fits
            # the space the timeout bars and the records leave free, the same
            # trade the classic layout makes via _fit_text. The old
            # `display_width > 128` gate was a proxy for "is there room" and got
            # a 128x64 wrong: the long form is 65px in the 4x6 face and the free
            # band there is wider than that, so the yardage was dropped on a
            # panel with room for it.
            band = (Region(left, region.y, right - left, region.h)
                    if right > left else region)
            # Try each wording against a band shortened by the ball first, so
            # that where two rungs both fit the wording we take the one that
            # also leaves room for the indicator. This costs font size, never
            # words -- a smaller rung with the yardage beats a larger one
            # without it.
            slot = 0
            if game.get("possession_indicator"):
                slot = self._possession_icon_size()[0] + self._ctx.px(3, minimum=2)
            narrowed = Region(band.x, band.y, max(0, band.w - slot), band.h)

            fit, fit_region = None, band
            for candidate in (game.get("down_distance_text_long", ""), down_distance):
                if not candidate:
                    continue
                for target in (narrowed, band):
                    if target.w <= 0:
                        continue
                    trial = self._fit_element('detail', candidate, target,
                                              ADAPTIVE_LADDER_DETAIL)
                    # _fit_element truncates to make text fit, so "it fits" has
                    # to mean the string came back whole -- not "3rd & 8 at KC..."
                    if trial.text == candidate and trial.width <= target.w:
                        fit = trial
                        break
                if fit is not None:
                    break
            if fit is None:
                # Nothing fits the free band intact. Fall back to what this
                # card drew before: the short form centred in the full detail
                # band, which on a 64px panel is all there is room for.
                fit = self._fit_element('detail', down_distance, region,
                                        ADAPTIVE_LADDER_DETAIL)
                fit_region = region
            drawn = (*self._draw_fit_outline(draw, fit, fit_region, fill=down_color), fit)
            if drawn:
                dd_x, dd_y, fit = drawn
                icon_box = possession_ball_box(
                    dd_x, fit.width, fit.height, dd_y, left, right,
                    game.get("possession_indicator"),
                    icon_size=self._possession_icon_size(),
                    gap=self._ctx.px(3, minimum=2))
                if icon_box:
                    draw_possession_football(draw, icon_box)

        self._draw_timeouts_adaptive(draw, game, regs)

    def _bottom_free_band_adaptive(self, draw: ImageDraw.Draw, game: Dict,
                                   regs) -> Tuple[int, int]:
        """Span of the detail band the timeout bars and the corner records
        leave free, as (first free x, first occupied x).

        Mirrors those two drawers' own geometry rather than reserving the
        bottom_left/bottom_right regions outright: those regions are far wider
        than what is actually drawn in them (on 128x64 they leave only 40px
        between them), so reserving them would squeeze the down & distance
        text off the card to solve a problem the ball only has at the edges.
        """
        band = regs.detail_band
        left, right = band.x, band.right

        # Mirrors _draw_timeouts_adaptive: margin + 3 bars + 2 gaps + outline
        bar_w = self._ctx.px(4, minimum=3)
        spacing = self._ctx.px(1, minimum=1)
        margin = self._ctx.px(2, minimum=2)
        block = margin + 3 * bar_w + 2 * spacing + 1
        left = max(left, self._region_for(regs.bottom_left, 'timeouts').x + block)
        right = min(right, self._region_for(regs.bottom_right, 'timeouts').right - block)

        # Mirrors _draw_records_adaptive: same region, inset, ladder fit
        league = game.get("league", "nfl")
        show_records = self._get_display_option(league, "show_records")
        show_ranking = self._get_display_option(league, "show_ranking")
        if show_records or show_ranking:
            for abbr_key, record_key, corner, align in (
                ('away_abbr', 'away_record', regs.bottom_left, 'left'),
                ('home_abbr', 'home_record', regs.bottom_right, 'right'),
            ):
                text = self._get_team_display_text(
                    game.get(abbr_key, ''), game.get(record_key, ''),
                    show_records, show_ranking)
                if not text:
                    continue
                r = self._region_for(corner, 'records').inset(2, 0)
                fit = self._fit_element('detail', text, r, ADAPTIVE_LADDER_TEXT)
                if align == 'left':
                    left = max(left, r.x + fit.width)
                else:
                    right = min(right, r.right - fit.width)
        return int(left), int(right)

    def _possession_icon_size(self) -> Tuple[int, int]:
        """Ball size for the adaptive card: the px()-scaled radii it always
        used, unchanged. Only where the ball is placed has changed."""
        return (2 * self._ctx.px(3, minimum=2) + 1,
                2 * self._ctx.px(2, minimum=1) + 1)

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

            # Possession indicator, drawn only where it clears the corners
            left, right = self._bottom_free_band(draw, game)
            icon_box = possession_ball_box(dd_x, dd_width, 6, dd_y, left, right,
                                           game.get("possession_indicator"))
            if icon_box:
                draw_possession_football(draw, icon_box)

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
            # Sit the date on the bottom edge by its own measured height. This
            # was a hardcoded `height - 7`, which fitted the 6px detail font
            # and clipped anything taller -- the same font now scales with the
            # panel, so the offset has to follow it.
            try:
                bbox = draw.textbbox((0, 0), game_date, font=self.fonts['detail'])
                date_h = bbox[3] - bbox[1]
            except (AttributeError, TypeError, ValueError):
                date_h = 6
            date_y = max(0, self.display_height - date_h - 2)
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

    def _get_record_font(self):
        """7px font used for the bottom-corner record/ranking text."""
        record_font = getattr(self, '_record_font', None)
        if record_font is None:
            try:
                record_font = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
            except OSError:
                record_font = ImageFont.load_default()
            self._record_font = record_font
        return record_font

    def _bottom_free_band(self, draw: ImageDraw.Draw, game: Dict) -> Tuple[int, int]:
        """Span of the bottom row the timeout bars and records leave free, as
        (first free x, first occupied x).

        Derived from the same constants those two draw with, so the reservation
        cannot drift away from what is actually on the panel.
        """
        block = 2 + 3 * 4 + 2 * 1 + 1  # margin + 3 bars + 2 gaps + outline
        left, right = block, self.display_width - block

        league = game.get("league", "nfl")
        show_records = self._get_display_option(league, "show_records")
        show_ranking = self._get_display_option(league, "show_ranking")
        if show_records or show_ranking:
            font = self._get_record_font()
            away = self._get_team_display_text(
                game.get('away_abbr', ''), game.get('away_record', ''),
                show_records, show_ranking)
            home = self._get_team_display_text(
                game.get('home_abbr', ''), game.get('home_record', ''),
                show_records, show_ranking)
            if away:
                left = max(left, 3 + draw.textlength(away, font=font))
            if home:
                right = min(right,
                            self.display_width - 3 - draw.textlength(home, font=font))
        return int(left), int(right)

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
    
    #: Clear pixels kept between an odds label and the centre status text.
    _ODDS_CENTRE_GUTTER_PX: ClassVar[int] = 3

    def _centre_row_text(self, game: Dict[str, Any], game_type: str) -> str:
        """What this card draws in the centre of the odds row.

        The odds sit at the outer ends of the top row and the status sits in
        the middle of it, so this is the string they have to share space with.
        Mirrors what the three _draw_*_game_status methods put there.
        """
        if game_type == "live":
            if game.get("is_halftime"):
                return "Halftime"
            return f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
        if game_type == "recent":
            return str(game.get("period_text") or "Final")
        _date, time_text = self._upcoming_date_and_time(game)
        return str(time_text or "")

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

    def _draw_dynamic_odds(self, draw: ImageDraw.Draw, odds: Dict[str, Any],
                           centre_text: str = "") -> None:
        """Draw odds with dynamic positioning.

        *centre_text* is what this card draws on the same row, used to budget
        the space left at the edges. Empty falls back to the old worst case.
        """
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
            
            # Show the negative spread
            # customization.layout.odds is declared in this plugin's config
            # schema, so the web UI offers x_offset and y_offset -- but nothing
            # here ever read them, and the odds drew at a fixed 0,0. A control
            # that visibly does nothing is worse than no control, since the
            # user concludes the position is unfixable.
            odds_x_offset = self._layout_offset('odds', 'x_offset')
            odds_y_offset = self._layout_offset('odds', 'y_offset')

            # Both labels are anchored to the edges of this row, and the card
            # centres the kickoff time on the same row. On a full-width panel
            # there is room for all three; on a Vegas game card, which this
            # plugin pins to 128px whatever the panel width, "O/U: 60.5" runs
            # from x=0 to x=54 while the time occupies 36..92 -- an 18px
            # overprint that renders both unreadable. Budget each side against
            # the widest time string the centre can hold, measured in the same
            # font the renderer will use, so this tracks font changes instead
            # of hard-coding a width.
            font = self.fonts.get("odds") or self.fonts["detail"]
            time_font = self.fonts.get("time", font)
            # Reserve for what this card actually puts in the centre, not the
            # widest string any card could. "12:00 PM" is an upcoming card's
            # kickoff; a finished card says "Final" and costs 24px less. The
            # fixed worst case spent that on every card and pushed the
            # over/under out of cards that had room for it.
            centre_reserve = draw.textlength(centre_text or "12:00 PM",
                                             font=time_font)
            # A gutter either side of the centre text. Without it a label that
            # fits "exactly" ends on the pixel the status starts on, which
            # reads as collided even though nothing is overprinted.
            gutter = self._ODDS_CENTRE_GUTTER_PX
            side_budget = max(
                0.0, (self.display_width - centre_reserve) / 2 - gutter)

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
                # Shed label, then punctuation, before shedding the number.
                # A live card centres "Q4 02:34", which is as wide as the old
                # worst case, so the full label never fit there -- the
                # over/under was dropped on exactly the cards people watch.
                # The bare number still reads as the over/under from position.
                candidates = (f"O/U: {over_under}", f"O/U {over_under}",
                              f"O/U{over_under}", f"{over_under}")
                for candidate in candidates:
                    ou_text = candidate
                    ou_width = draw.textlength(ou_text, font=font)
                    if ou_width <= side_budget:
                        break
                else:
                    # Not even the bare number fits; the spread is the more
                    # useful of the two and keeps the space.
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
        record_font = self._get_record_font()

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


