"""
Game Card Renderer for Baseball Scoreboard Plugin

Renders individual baseball game cards as PIL Images for use in scroll mode.
Returns images instead of updating display directly.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
import os
from typing import Any, ClassVar, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from baseball_timezone import resolve_timezone


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


# Maps the core FontManager's common-font family aliases (src/font_manager.py
# `common_fonts`) to the real files in assets/fonts. A font config value may be
# either one of these family names or a literal filename; aliases resolve here,
# filenames pass through unchanged.
FONT_ALIASES = {
    "press_start": "PressStart2P-Regular.ttf",
    "four_by_six": "4x6-font.ttf",
    "five_by_seven": "5x7.bdf",
}


def resolve_font_name(font_name: str) -> str:
    """Resolve a font family alias to its filename, leaving filenames as-is."""
    return FONT_ALIASES.get(font_name, font_name)


# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


# Distinguishes "the caller did not say" from "the caller says the top row is
# empty". Both were None, so a card that genuinely centres nothing up there
# fell back to measuring an inning it does not draw.
_DERIVE_TOP_SPAN = object()


class GameRenderer:
    """Renders individual baseball game cards as PIL Images."""

    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict,
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the game renderer.

        Args:
            display_width: Display width in pixels
            display_height: Display height in pixels
            config: Plugin configuration dictionary
            logo_cache: Optional shared logo cache
            custom_logger: Optional custom logger
        """
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logging.getLogger(__name__)

        # Use provided logo cache or create new one
        self._logo_cache = logo_cache if logo_cache is not None else {}

        # Rankings cache (populated externally via set_rankings_cache)
        self._team_rankings_cache: Dict[str, int] = {}

        # Load fonts
        self.fonts = self._load_fonts()

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
            fonts["score"] = self._load_custom_font(score_config, default_size=10, element_key='score_text')
            fonts["time"] = self._load_custom_font(period_config, default_size=8, element_key='period_text')
            fonts["team"] = self._load_custom_font(team_config, default_size=8, element_key='team_name')
            fonts["status"] = self._load_custom_font(status_config, default_size=6, element_key='status_text')
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, default_font='4x6-font.ttf', element_key='detail_text')
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10, element_key='rank_text')
            self.logger.debug("Successfully loaded fonts from config")
        except Exception:
            self.logger.exception("Error loading fonts, using defaults")
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
        """Snap *desired* to the nearest size *font_file* renders crisply at.

        A face with no known grid is returned unchanged, so a user-supplied
        font is never second-guessed.
        """
        font_file = cls._FONT_NAME_ALIASES.get(font_file, font_file)
        grid = cls._FONT_PIXEL_GRID.get(font_file)
        if not grid or not desired or desired <= 0:
            return desired
        return max(grid, int(round(float(desired) / grid)) * grid)

    def _schema_font_size(self, element_key):
        """The font_size this plugin's config_schema.json declares, or None."""
        if not element_key:
            return None
        cache = getattr(self.__class__, '_SCHEMA_FONT_SIZES', None)
        if cache is None:
            cache = {}
            try:
                import json
                schema_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 'config_schema.json')
                with open(schema_path) as fh:
                    schema = json.load(fh)
                props = (schema.get('properties', {})
                               .get('customization', {})
                               .get('properties', {}))
                for key, spec in props.items():
                    size = spec.get('properties', {}).get('font_size', {}).get('default')
                    if size is not None:
                        cache[key] = int(size)
            except Exception:
                cache = {}
            self.__class__._SCHEMA_FONT_SIZES = cache
        return cache.get(element_key)

    def _resolve_font_size(self, element_config, element_key, default_size, font_name):
        """Size to render at: the user's choice, or a grid-snapped default.

        A configured size counts as a real choice only when it differs from
        the schema default. The web UI writes the whole schema default block
        on every save, so "font_size == schema default" carries no intent and
        would otherwise pin every install to an anti-aliased size forever.
        """
        configured = (element_config or {}).get('font_size')
        if configured is not None:
            try:
                configured = int(configured)
                if configured != self._schema_font_size(element_key):
                    return configured
            except (TypeError, ValueError):
                pass
        return self._crisp_size(font_name, default_size)

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
        # Resolve family aliases (e.g. "press_start") to real filenames, then build path
        font_path = _resolve_font_path(os.path.join('assets', 'fonts', resolve_font_name(font_name)))

        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf') or font_path.lower().endswith('.otf'):
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    # BDF fonts require pre-conversion: pilfont.py font.bdf -> font.pil + font.pbm
                    pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                    if os.path.exists(pil_font_path):
                        try:
                            return ImageFont.load(pil_font_path)
                        except Exception as e:
                            self.logger.warning(f"Failed to load pre-converted BDF font {pil_font_path}: {e}")
                    else:
                        self.logger.warning(
                            f"BDF font {font_name} requires conversion. "
                            f"Run: pilfont.py {font_path}"
                        )
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}")
            else:
                self.logger.warning(f"Font file not found: {font_path}")
        except Exception as e:
            self.logger.warning(f"Error loading font {font_name}: {e}")

        # Fallback to default font
        default_font_path = _resolve_font_path(os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf'))
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception as e:
            self.logger.warning(f"Error loading default font {default_font_path}: {e}")

        return ImageFont.load_default()

    def _get_logo_path(self, league: str, team_abbrev: str) -> Path:
        """Get the logo path for a team based on league."""
        if league == 'mlb':
            return Path("assets/sports/mlb_logos") / f"{team_abbrev}.png"
        elif league == 'milb':
            return Path("assets/sports/milb_logos") / f"{team_abbrev}.png"
        elif league == 'ncaa_baseball':
            return Path("assets/sports/ncaa_logos") / f"{team_abbrev}.png"
        else:
            return Path("assets/sports/mlb_logos") / f"{team_abbrev}.png"

    def _load_and_resize_logo(self, league: str, team_abbrev: str) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching."""
        cache_key = f"{league}_{team_abbrev}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        logo_path = self._get_logo_path(league, team_abbrev)

        if not logo_path.exists():
            self.logger.warning(f"Logo not found for {team_abbrev} at {logo_path}")
            return None

        try:
            with Image.open(logo_path) as logo:
                if logo.mode != 'RGBA':
                    logo = logo.convert('RGBA')

                # Crop transparent padding so scaling operates on actual content.
                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                # MiLB logos are landscape banner art (1.2–2.7:1 aspect ratio) —
                # cap width at 1/3 of display width and height at full display height
                # so they stay in their corner and never overlap center score text.
                # All other leagues use the compact slot sizing.
                if league == 'milb':
                    max_logo_w = self.display_width // 3
                    max_logo_h = self.display_height
                else:
                    max_logo_w = self._logo_slot_width()
                    # Full card height, as football-scoreboard's card already
                    # does. The 0.75 factor left every baseball mark a quarter
                    # short of the height its slot allows -- and because the
                    # slot is square (min(height, available)), a tall-ish mark
                    # ran out of height first and so came out narrower too.
                    # The slot already keeps the centre gap clear, so nothing
                    # here can reach the score.
                    max_logo_h = self.display_height
                logo.thumbnail((max_logo_w, max_logo_h), RESAMPLE_FILTER)

                # Copy before exiting context manager
                cached_logo = logo.copy()

            self._logo_cache[cache_key] = cached_logo
            return cached_logo

        except OSError:
            self.logger.exception(f"Error loading logo for {team_abbrev}")
            return None

    def _draw_text_with_outline(self, draw, text, position, font,
                               fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        # Disable anti-aliasing: pixel/bitmap fonts (e.g. PressStart2P) get
        # anti-aliased into dim partial-lit pixels on a 1:1 LED matrix, muddying
        # glyphs. 1-bit mode keeps strokes crisp. See _draw_text_with_outline in
        # sports.py for the same fix on the switch-mode renderer.
        draw.fontmode = "1"
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        """Set the team rankings cache for display."""
        self._team_rankings_cache = rankings

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

    def render_game_card(self, game: Dict, game_type: str) -> Image.Image:
        """
        Render a game card as a PIL Image.

        Args:
            game: Game dictionary
            game_type: Type of game ('live', 'recent', 'upcoming')

        Returns:
            PIL Image of the rendered game card
        """
        if game_type == 'live':
            return self._render_live_game(game)
        elif game_type == 'recent':
            return self._render_recent_game(game)
        elif game_type == 'upcoming':
            return self._render_upcoming_game(game)
        else:
            self.logger.error(f"Unknown game type: {game_type}")
            return self._render_error_card("Unknown type")

    def _render_live_game(self, game: Dict) -> Image.Image:
        """Render a live baseball game card with full scorebug elements."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos
            logo_slot = self._logo_slot_width()
            away_x = ((logo_slot - away_logo.width) // 2
                  + self._layout_offset('away_logo', 'x_offset'))
            main_img.paste(away_logo, (away_x, center_y - away_logo.height // 2), away_logo)
            home_x = ((self.display_width - logo_slot) + (logo_slot - home_logo.width) // 2
                  + self._layout_offset('home_logo', 'x_offset'))
            main_img.paste(home_logo, (home_x, center_y - home_logo.height // 2), home_logo)

            # Inning indicator (top center)
            inning_half = game.get('inning_half', 'top')
            inning_num = game.get('inning', 1)
            if game.get('is_final'):
                inning_text = "FINAL"
            elif inning_half == 'end':
                inning_text = f"E{inning_num}"
            elif inning_half == 'mid':
                inning_text = f"M{inning_num}"
            else:
                symbol = "▲" if inning_half == 'top' else "▼"
                inning_text = f"{symbol}{inning_num}"

            inning_font = self.fonts['time']
            inning_bbox = draw.textbbox((0, 0), inning_text, font=inning_font)
            inning_width = inning_bbox[2] - inning_bbox[0]
            inning_x = (self.display_width - inning_width) // 2
            inning_y = 1
            self._draw_text_with_outline(draw, inning_text, (inning_x, inning_y), inning_font)

            # Bases diamond + Outs circles
            bases_occupied = game.get('bases_occupied', [False, False, False])
            outs = game.get('outs', 0)

            # Read configurable game display settings
            customization = self.config.get('customization', {})
            bases_cfg = customization.get('bases', {})
            outs_cfg = customization.get('outs', {})
            count_cfg = customization.get('count', {})

            base_diamond_size = bases_cfg.get('diamond_size', 7)
            out_circle_diameter = outs_cfg.get('circle_diameter', 3)
            out_vertical_spacing = outs_cfg.get('spacing', 2)
            spacing_between_bases_outs = outs_cfg.get('distance_from_bases', 3)
            base_vert_spacing = 1
            base_horiz_spacing = 1

            base_cluster_height = base_diamond_size + base_vert_spacing + base_diamond_size
            base_cluster_width = base_diamond_size + base_horiz_spacing + base_diamond_size

            overall_start_y = inning_bbox[3] + 1 + bases_cfg.get('y_offset', 0)
            bases_origin_x = (self.display_width - base_cluster_width) // 2 + bases_cfg.get('x_offset', 0)

            # Outs column position (only needed when count data is available)
            has_count_data = game.get('has_count_data', True)
            out_cluster_height = 3 * out_circle_diameter + 2 * out_vertical_spacing
            if has_count_data:
                if inning_half == 'top':
                    outs_column_x = bases_origin_x - spacing_between_bases_outs - out_circle_diameter
                else:
                    outs_column_x = bases_origin_x + base_cluster_width + spacing_between_bases_outs
                outs_column_start_y = overall_start_y + (base_cluster_height // 2) - (out_cluster_height // 2)

            # Draw bases as diamond polygons
            h_d = base_diamond_size // 2
            base_fill = tuple(bases_cfg.get('occupied_color', [255, 255, 255]))
            base_outline = tuple(bases_cfg.get('empty_color', [255, 255, 255]))

            # 2nd base (top center)
            c2x = bases_origin_x + base_cluster_width // 2
            c2y = overall_start_y + h_d
            poly2 = [(c2x, overall_start_y), (c2x + h_d, c2y), (c2x, c2y + h_d), (c2x - h_d, c2y)]
            draw.polygon(poly2, fill=base_fill if bases_occupied[1] else None, outline=base_outline)

            base_bottom_y = c2y + h_d

            # 3rd base (bottom left)
            c3x = bases_origin_x + h_d
            c3y = base_bottom_y + base_vert_spacing + h_d
            poly3 = [(c3x, base_bottom_y + base_vert_spacing), (c3x + h_d, c3y), (c3x, c3y + h_d), (c3x - h_d, c3y)]
            draw.polygon(poly3, fill=base_fill if bases_occupied[2] else None, outline=base_outline)

            # 1st base (bottom right)
            c1x = bases_origin_x + base_cluster_width - h_d
            c1y = base_bottom_y + base_vert_spacing + h_d
            poly1 = [(c1x, base_bottom_y + base_vert_spacing), (c1x + h_d, c1y), (c1x, c1y + h_d), (c1x - h_d, c1y)]
            draw.polygon(poly1, fill=base_fill if bases_occupied[0] else None, outline=base_outline)

            # Outs circles (only when count data is available)
            if has_count_data:
                outs_fill = tuple(outs_cfg.get('counted_color', [255, 255, 255]))
                outs_empty = tuple(outs_cfg.get('empty_color', [100, 100, 100]))
                for i in range(3):
                    cx = outs_column_x
                    cy = outs_column_start_y + i * (out_circle_diameter + out_vertical_spacing)
                    coords = [cx, cy, cx + out_circle_diameter, cy + out_circle_diameter]
                    if i < outs:
                        draw.ellipse(coords, fill=outs_fill)
                    else:
                        draw.ellipse(coords, outline=outs_empty)

            # Balls-strikes count (below bases, only when count data is available)
            if has_count_data:
                balls = game.get('balls', 0)
                strikes = game.get('strikes', 0)
                count_text = f"{balls}-{strikes}"
                count_font = self.fonts['detail']
                count_width = draw.textlength(count_text, font=count_font)
                count_y = overall_start_y + base_cluster_height + count_cfg.get('y_offset', 2)
                count_x = bases_origin_x + (base_cluster_width - count_width) // 2
                count_text_color = tuple(count_cfg.get('text_color', [255, 255, 255]))
                self._draw_text_with_outline(draw, count_text, (int(count_x), count_y), count_font, fill=count_text_color)

            # Score (centered between logos, below bases/count cluster)
            score_font = self.fonts['score']
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_width = draw.textlength(score_text, font=score_font)
            score_x = ((self.display_width - score_width) // 2
                       + self._layout_offset('score', 'x_offset'))
            try:
                font_height = score_font.getbbox("A")[3] - score_font.getbbox("A")[1]
            except AttributeError:
                font_height = 8
            cluster_bottom = overall_start_y + base_cluster_height
            if has_count_data:
                cluster_bottom += 2 + 6  # count spacing + detail font height
            bottom_limit = self.display_height - font_height - 2
            score_y = max(0, min(cluster_bottom + 1, bottom_limit))
            self._draw_text_with_outline(draw, score_text, (int(score_x), score_y), score_font)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(
                    draw, game['odds'], game=game,
                    top_span=self._top_row_span(draw, inning_text, inning_font))

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering live game")
            return self._render_error_card("Display error")

    def _render_recent_game(self, game: Dict) -> Image.Image:
        """Render a recent baseball game card."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos (tighter fit for recent)
            logo_slot = self._logo_slot_width()
            away_x = ((logo_slot - away_logo.width) // 2
                  + self._layout_offset('away_logo', 'x_offset'))
            main_img.paste(away_logo, (away_x, center_y - away_logo.height // 2), away_logo)
            home_x = ((self.display_width - logo_slot) + (logo_slot - home_logo.width) // 2
                  + self._layout_offset('home_logo', 'x_offset'))
            main_img.paste(home_logo, (home_x, center_y - home_logo.height // 2), home_logo)

            # "Final" (top center)
            status_text = "Final"
            status_width = draw.textlength(status_text, font=self.fonts['time'])
            self._draw_text_with_outline(draw, status_text, ((self.display_width - status_width) // 2, 1), self.fonts['time'])

            # Score (centered). White, matching the switch-mode recent scorebug
            # and every other scoreboard; this card used to be alone in drawing
            # the final score gold.
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_width = draw.textlength(score_text, font=self.fonts['score'])
            score_x = ((self.display_width - score_width) // 2
                       + self._layout_offset('score', 'x_offset'))
            score_y = self.display_height - 14
            self._draw_text_with_outline(draw, score_text, (score_x, score_y),
                                        self.fonts['score'],
                                        fill=self._recent_score_color(game, (255, 255, 255)))

            # Records at bottom corners
            self._draw_records(draw, game)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(
                    draw, game['odds'], game=game,
                    top_span=self._top_row_span(draw, "Final", self.fonts['time']))

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering recent game")
            return self._render_error_card("Display error")

    # ------------------------------------------------------------------
    # Card options -- config["scroll_card"], plus the shared
    # customization.layout offsets and per-element colours.
    #
    # The center-gap keys size this renderer's cards alone. The rest --
    # upcoming_center, vs_text, the date and time formats -- are also read by
    # sports.py's full-screen scorebug (SportsCore._draw_upcoming_center_switch
    # and friends, gated there on switch_upcoming_center), so those two copies
    # have to stay in step: a change to the formatting rules here needs the
    # same change there, or the ticker and the scoreboard disagree.
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

    #: Clear pixels kept between the score and each logo, so the score's
    #: outermost column cannot land on the logo's first lit column.
    _SCORE_LOGO_GUTTER_PX: ClassVar[int] = 4

    #: Widest score the centre strip is sized to hold. Two digits a side covers this sport's realistic range.
    #: The reserve is a fixed width so the strip does not jitter between
    #: cards, so it has to assume the worst case rather than measure the
    #: score in hand.
    _SCORE_PROBE: ClassVar[str] = "00-00"

    def _score_reserve_width(self) -> int:
        """Centre strip the score actually needs, measured rather than assumed.

        The gap was derived from the card width alone (width x
        CENTER_GAP_RATIO, clamped to CENTER_GAP_MAX_PX) while the score's size
        comes from config and the element-style resolver. Nothing compared the
        two, so any score wider than the clamp was drawn over the logos.
        Measuring it keeps the strip wide enough for whatever font is in play.
        """
        try:
            probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
            width = probe.textlength(self._SCORE_PROBE, font=self.fonts['score'])
            return int(width) + 2 * self._SCORE_LOGO_GUTTER_PX
        except Exception:
            self.logger.debug("Score reserve measurement failed", exc_info=True)
            return 0

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
            derived = int(max(int(low), min(int(high), scaled)))
            # A strip narrower than the score is the bug, not a style choice.
            # An explicit ``center_gap`` is still honoured above, including 0.
            return max(derived, self._score_reserve_width())
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

    def _upcoming_date_time_texts(self, game: Dict):
        """The date and time strings an upcoming card would draw."""
        date_raw, time_raw = self._upcoming_date_and_time(game)
        date_text = (self._format_game_date(date_raw, game)
                     if self._scroll_card_option("show_date", True) else "")
        time_text = (self._format_game_time(time_raw)
                     if self._scroll_card_option("show_time", True) else "")
        return date_text, time_text


    def _draw_upcoming_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw the date and time around an upcoming card.

        Time top and date bottom by default; scroll_card.swap_date_time puts
        the date on top instead. Skipped when the pair is stacked in the
        middle, which would otherwise print them twice.
        """
        if self._upcoming_center_mode() == "date_time":
            return

        date_text, time_text = self._upcoming_date_time_texts(game)

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

    def _render_upcoming_game(self, game: Dict) -> Image.Image:
        """Render an upcoming baseball game card."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos (tighter fit)
            logo_slot = self._logo_slot_width()
            away_x = ((logo_slot - away_logo.width) // 2
                  + self._layout_offset('away_logo', 'x_offset'))
            main_img.paste(away_logo, (away_x, center_y - away_logo.height // 2), away_logo)
            home_x = ((self.display_width - logo_slot) + (logo_slot - home_logo.width) // 2
                  + self._layout_offset('home_logo', 'x_offset'))
            main_img.paste(home_logo, (home_x, center_y - home_logo.height // 2), home_logo)

            # Game time/date from start_time
            start_time = game.get('start_time', '')
            game_date = ''
            game_time = ''
            if start_time:
                try:
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    local_tz = resolve_timezone(config=self.config, log=self.logger)
                    dt_local = dt.astimezone(local_tz)
                    # Numeric here; _format_game_date turns it into "Sep 19"
                    # unless the user asked for the numeric form.
                    game_date = dt_local.strftime('%-m/%-d')
                    game_time = dt_local.strftime('%-I:%M%p')
                except (ValueError, AttributeError):
                    game_time = start_time[:10] if len(start_time) > 10 else start_time

            # Same card as the other sports: the middle (VS, or the date and
            # time stacked), then the surrounding date/time. Both honour the
            # scroll_card settings and the customization.layout offsets.
            upcoming = dict(game, game_date=game_date, game_time=game_time)
            self._draw_upcoming_center(draw, upcoming)
            self._draw_upcoming_game_status(draw, upcoming)

            # Records at bottom corners
            self._draw_records(draw, game)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(
                    draw, game['odds'], game=game,
                    top_span=self._upcoming_top_row_span(draw, upcoming))

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering upcoming game")
            return self._render_error_card("Display error")

    def _get_team_display_text(self, abbr: str, record: str, show_records: bool, show_ranking: bool) -> str:
        """Get display text for a team (ranking or record)."""
        if show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            if not show_records:
                return ''
        if show_records:
            return record
        return ''

    def _draw_records(self, draw, game: Dict):
        """Draw team records or rankings at bottom corners if enabled by config."""
        league = game.get('league', 'mlb')
        league_config = self.config.get(league, {})
        display_options = league_config.get('display_options', {})
        show_records = display_options.get('show_records', self.config.get('show_records', False))
        show_ranking = display_options.get('show_ranking', self.config.get('show_ranking', False))

        if not show_records and not show_ranking:
            return

        record_font = self.fonts['detail']
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height

        # Away team (bottom left)
        away_text = self._get_team_display_text(
            game.get('away_abbr', ''), game.get('away_record', ''),
            show_records, show_ranking
        )
        if away_text:
            self._draw_text_with_outline(draw, away_text, (0, record_y), record_font)

        # Home team (bottom right)
        home_text = self._get_team_display_text(
            game.get('home_abbr', ''), game.get('home_record', ''),
            show_records, show_ranking
        )
        if home_text:
            home_bbox = draw.textbbox((0, 0), home_text, font=record_font)
            home_w = home_bbox[2] - home_bbox[0]
            self._draw_text_with_outline(draw, home_text, (self.display_width - home_w, record_y), record_font)

    def _get_layout_offset(self, element: str, axis: str, default: int = 0) -> int:
        """Get layout offset for a specific element and axis from config."""
        try:
            layout_config = self.config.get('customization', {}).get('layout', {})
            element_config = layout_config.get(element, {})
            offset_value = element_config.get(axis, default)
            if offset_value is None:
                return default
            if isinstance(offset_value, (int, float)):
                return int(offset_value)
            # Handle string values (e.g. "2.0" from config)
            try:
                return int(float(offset_value))
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid layout offset for {element}.{axis}: '{offset_value}', using default {default}")
                return default
        except (TypeError, ValueError):
            return default

    def _inning_text(self, game: Optional[Dict]) -> str:
        """The centred top-row text, built exactly as the scorebug draws it."""
        if not game:
            return ""
        inning_half = game.get('inning_half', 'top')
        inning_num = game.get('inning', 1)
        if game.get('is_final'):
            return "FINAL"
        if inning_half == 'end':
            return f"E{inning_num}"
        if inning_half == 'mid':
            return f"M{inning_num}"
        symbol = "\u25b2" if inning_half == 'top' else "\u25bc"
        return f"{symbol}{inning_num}"

    def _top_row_span(self, draw, text: str, font, x_offset: int = 0):
        """The horizontal span a centred top-row string occupies, or None.

        Mirrors how the cards place that text: centred, then nudged by the
        element's configured x_offset. Returned as pixels rather than derived
        from the text again later, because the three cards do not agree on the
        font either -- an upcoming card with swap_date_time draws the date in
        `detail`, not `time`.
        """
        if not text:
            return None
        try:
            width = draw.textlength(text, font=font)
        except Exception:
            return None
        left = int((self.display_width - width) // 2 + x_offset)
        return left, int(left + width)

    def _upcoming_top_row_span(self, draw, game: Dict):
        """The span an upcoming card's top-row text occupies, or None.

        Font and offset are chosen exactly as _draw_upcoming_game_status does,
        so the odds are measured against what is really on the panel.
        """
        if self._upcoming_center_mode() == "date_time":
            return None      # both are stacked in the middle; the top row is free
        date_text, time_text = self._upcoming_date_time_texts(game)
        if self._scroll_card_option("swap_date_time", False):
            text, element = date_text, 'date'
            font = self.fonts.get('detail') or self.fonts['time']
        else:
            text, element = time_text, 'time'
            font = self.fonts['time']
        return self._top_row_span(draw, text, font,
                                  self._layout_offset(element, 'x_offset'))

    def _odds_would_hit_top_row(self, span, placements) -> bool:
        """Whether any odds text overlaps the centred text on the top row.

        Baseball is the only scoreboard with something centred on that row, so
        it is the only one that can collide. Deciding by measurement rather
        than by panel size keeps the rule honest: what matters is whether these
        particular strings fit beside each other, and a two-digit over/under is
        several pixels wider than a one-digit one.

        The text is passed in rather than derived, because the three cards do
        not draw the same thing there: a live card shows the inning, a recent
        card "Final", and an upcoming card a time or a date. Measuring the
        inning for all three checked a string that was not on the panel.
        """
        if not span:
            return False
        left, right = span
        # One pixel of breathing room either side, so glyphs do not touch.
        return any(x < right + 1 and x + width > left - 1
                   for _text, x, width in placements)

    def _draw_dynamic_odds(self, draw, odds: Dict, game: Optional[Dict] = None,
                           top_span=_DERIVE_TOP_SPAN) -> None:
        """Draw odds with dynamic positioning based on favored team.

        `top_span` is the (left, right) the card's own top-row text occupies,
        so the odds can step down a row when they would not fit beside it.
        Callers pass the span they actually drew rather than a string, because
        the three cards agree on neither the text, the font, nor the centring:
        a recent card draws "Final" in `time`, an upcoming card a time in
        `time` or -- with swap_date_time -- a date in `detail`, shifted by
        that element's configured x_offset. When omitted it falls back to
        measuring the live card's inning indicator, which is what `game` is
        for; passing neither simply skips the check.
        """
        try:
            if not odds:
                return

            home_team_odds = odds.get('home_team_odds', {})
            away_team_odds = odds.get('away_team_odds', {})
            home_spread = home_team_odds.get('spread_odds')
            away_spread = away_team_odds.get('spread_odds')

            # Get top-level spread as fallback (only when individual spread is truly missing)
            top_level_spread = odds.get('spread')
            if top_level_spread is not None:
                if home_spread is None:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = -top_level_spread if isinstance(
                        top_level_spread, (int, float)) else None

            # Determine favored team
            home_favored = isinstance(home_spread, (int, float)) and home_spread < 0
            away_favored = isinstance(away_spread, (int, float)) and away_spread < 0

            favored_spread = None
            favored_side = None

            if home_favored:
                favored_spread = home_spread
                favored_side = 'home'
            elif away_favored:
                favored_spread = away_spread
                favored_side = 'away'

            # Get user-configurable layout offsets for odds
            odds_x_offset = self._get_layout_offset('odds', 'x_offset')
            odds_y_offset = self._get_layout_offset('odds', 'y_offset')

            # Top edge, matching every other scoreboard. This used to sit a
            # whole text row lower (status_bbox[3] + 2, which measured 8-10px
            # depending on the detail font) to clear the centred inning text,
            # but that made baseball the odd one out: the same element landed a
            # third of a 32px card lower here than on football, basketball,
            # soccer and the rest. Odds are drawn hard left and hard right
            # while the inning sits centred, so they only meet on a narrow
            # panel -- and odds_y_offset is there to nudge it when they do.
            font = self.fonts['detail']

            # Work out both texts and their spans before drawing either, so the
            # row can be chosen once with full knowledge of what has to fit.
            placements = []
            if favored_spread is not None:
                spread_text = str(favored_spread)
                spread_width = draw.textlength(spread_text, font=font)
                if favored_side == 'home':
                    spread_x = self.display_width - spread_width + odds_x_offset
                else:
                    spread_x = 0 + odds_x_offset
                placements.append((spread_text, spread_x, spread_width))

            over_under = odds.get('over_under')
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                ou_width = draw.textlength(ou_text, font=font)
                if favored_side == 'home':
                    ou_x = 0 + odds_x_offset
                elif favored_side == 'away':
                    ou_x = self.display_width - ou_width + odds_x_offset
                else:
                    # No favourite: anchor to the same left edge the
                    # home-favoured case uses. Centring put it on top of the
                    # status text, which the card also centres on this row --
                    # "Final" and "O/U: 47.5" rendered through each other. It
                    # is also the assumption the side budget above is measured
                    # against, which only holds for an edge-anchored label.
                    ou_x = 0 + odds_x_offset
                placements.append((ou_text, ou_x, ou_width))

            if not placements:
                return

            odds_y = 0 + odds_y_offset
            obstacle = top_span
            if obstacle is _DERIVE_TOP_SPAN:
                obstacle = self._top_row_span(
                    draw, self._inning_text(game), self.fonts['time'])
            if self._odds_would_hit_top_row(obstacle, placements):
                # Step down one text row, which is where these used to live
                # unconditionally. Measured rather than keyed to a panel size:
                # it is the text widths that decide, and a two-digit over/under
                # ("O/U: 12.5") overlaps on a 64px panel where "O/U: 8.5" clears
                # it by 2px. Wider panels never reach the centre and never move.
                row = draw.textbbox((0, 0), "A", font=font)[3] + 2
                odds_y += row

            for text, x, _width in placements:
                self._draw_text_with_outline(draw, text, (x, odds_y), font, fill=(0, 255, 0))

        except Exception:
            self.logger.exception("Error drawing odds")

    def _render_error_card(self, message: str) -> Image.Image:
        """Render an error message card."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_text_with_outline(draw, message, (5, 5), self.fonts['status'])
        return img
