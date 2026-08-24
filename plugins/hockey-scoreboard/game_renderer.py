"""
Game Renderer for Hockey Scoreboard Plugin

Extracts game rendering logic into a reusable component for scroll display mode.
Returns PIL Images instead of updating display directly.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont


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

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


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

        # Get logo directories from config
        self.logo_dirs = {
            'nhl': config.get('nhl', {}).get('logo_dir', 'assets/sports/nhl_logos'),
            'ncaa_mens': config.get('ncaa_mens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaa_womens': config.get('ncaa_womens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaam_hockey': config.get('ncaa_mens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaaw_hockey': config.get('ncaa_womens', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
        }

        # Display options
        defaults = config.get('defaults', {})
        self.show_records = defaults.get('show_records', config.get('show_records', False))
        self.show_ranking = defaults.get('show_ranking', config.get('show_ranking', False))

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
            fonts["score"] = self._load_custom_font(score_config, default_size=10, element_key='score_text')
            fonts["time"] = self._load_custom_font(period_config, default_size=8, element_key='period_text')
            fonts["team"] = self._load_custom_font(team_config, default_size=8, element_key='team_name')
            fonts["status"] = self._load_custom_font(status_config, default_size=6, element_key='status_text')
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, element_key='detail_text')
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

    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, element_key=None) -> ImageFont.FreeTypeFont:
        """Load a custom font from an element configuration dictionary."""
        font_name = element_config.get('font', 'PressStart2P-Regular.ttf')
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
        default_font_path = _resolve_font_path(os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf'))
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception:
            self.logger.debug(f"Could not load fallback font from {default_font_path}")

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
            league = game.get('league', 'nhl')
            for team_key in ['home_abbr', 'away_abbr']:
                abbr = game.get(team_key, '')
                # Use league-aware cache key to avoid collisions across leagues
                cache_key = f"{league}_{abbr}"
                if abbr and cache_key not in self._logo_cache:
                    # Get logo path from game or resolve from logo_dir
                    logo_path_str = game.get(f'{team_key.replace("abbr", "logo_path")}')
                    if logo_path_str:
                        # Resolve relative paths using logo_dir
                        logo_path = Path(logo_path_str) if os.path.isabs(logo_path_str) else logo_dir / logo_path_str
                    else:
                        logo_path = logo_dir / f"{abbr}.png"

                    # _load_and_resize_logo handles caching with league-aware key internally
                    self._load_and_resize_logo(abbr, logo_path, league)

        self.logger.debug(f"Preloaded {len(self._logo_cache)} team logos")

    def _get_logo_path(self, league: str, team_abbrev: str) -> Path:
        """Get the logo path for a team based on league."""
        logo_dir = self.logo_dirs.get(league, 'assets/sports/nhl_logos')
        return Path(logo_dir) / f"{team_abbrev}.png"

    def _load_and_resize_logo(
        self,
        team_abbrev: str,
        logo_path: Optional[Path] = None,
        league: str = 'nhl',
        max_width: Optional[int] = None
    ) -> Optional[Image.Image]:
        """Load and resize a team logo with caching.

        max_width bounds the logo horizontally so it stays inside its slot and
        clear of the center gap; it is part of the cache key because the same
        cache dict is shared by renderers built for different card sizes.
        """
        box_w = int(max_width) if max_width else self.display_height
        box_h = self.display_height
        cache_key = f"{league}_{team_abbrev}_{box_w}x{box_h}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        try:
            # Use provided path or get from league config
            if logo_path is None or not os.path.exists(logo_path):
                logo_path = self._get_logo_path(league, team_abbrev)

            if logo_path and os.path.exists(logo_path):
                # Use context manager to ensure file handle is closed
                with Image.open(logo_path) as logo_file:
                    # Convert creates a copy; if already RGBA, use copy() to detach from file
                    if logo_file.mode != "RGBA":
                        logo = logo_file.convert("RGBA")
                    else:
                        logo = logo_file.copy()

                # Crop transparent padding, then thumbnail into the slot box so
                # the logo keeps its aspect ratio and never spills past its slot.
                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                logo.thumbnail((box_w, box_h), RESAMPLE_FILTER)

                self._logo_cache[cache_key] = logo
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
        font: ImageFont.FreeTypeFont,
        fill: Tuple[int, int, int] = (255, 255, 255),
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """Draw text with a black outline for better readability."""
        # Disable anti-aliasing: pixel/bitmap fonts (e.g. PressStart2P) get
        # anti-aliased into dim partial-lit pixels on a 1:1 LED matrix, muddying
        # glyphs. 1-bit mode keeps strokes crisp.
        draw.fontmode = "1"
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def _normalize_game_payload(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize flat game payload fields into nested structure.

        This allows render_game_card to work with both flat payloads
        (home_abbr, home_score, away_abbr, away_score at top level) and
        nested payloads (home_team/away_team/status dicts).

        Args:
            game: Game dictionary (flat or nested format)

        Returns:
            Game dictionary with normalized nested structure
        """
        # Create a copy to avoid mutating the original
        normalized = dict(game)

        # Check if we have flat fields that need normalization
        has_flat_fields = any(
            key in normalized for key in [
                'home_abbr', 'home_score', 'away_abbr', 'away_score',
                'home_name', 'away_name', 'home_record', 'away_record'
            ]
        )

        if not has_flat_fields:
            # Already in nested format or empty, return as-is
            return normalized

        # Normalize home_team
        home_team = normalized.get('home_team', {})
        if not isinstance(home_team, dict):
            home_team = {}
        # Only set values if they exist at top level and not already in nested dict
        if 'home_abbr' in normalized and not home_team.get('abbrev'):
            home_team['abbrev'] = normalized.get('home_abbr', '')
        if 'home_score' in normalized and 'score' not in home_team:
            home_team['score'] = normalized.get('home_score', '0')
        if 'home_name' in normalized and not home_team.get('name'):
            home_team['name'] = normalized.get('home_name', '')
        if 'home_record' in normalized and not home_team.get('record'):
            home_team['record'] = normalized.get('home_record', '')
        normalized['home_team'] = home_team

        # Normalize away_team
        away_team = normalized.get('away_team', {})
        if not isinstance(away_team, dict):
            away_team = {}
        if 'away_abbr' in normalized and not away_team.get('abbrev'):
            away_team['abbrev'] = normalized.get('away_abbr', '')
        if 'away_score' in normalized and 'score' not in away_team:
            away_team['score'] = normalized.get('away_score', '0')
        if 'away_name' in normalized and not away_team.get('name'):
            away_team['name'] = normalized.get('away_name', '')
        if 'away_record' in normalized and not away_team.get('record'):
            away_team['record'] = normalized.get('away_record', '')
        normalized['away_team'] = away_team

        # Normalize status
        status = normalized.get('status', {})
        if not isinstance(status, dict):
            status = {}
        if 'status_text' in normalized and not status.get('detail'):
            status['detail'] = normalized.get('status_text', '')
        # The extractor's status_text ("P2 12:34", "Final", "7:30 PM") is the
        # same value data_fetcher.py stores as short_detail.
        if 'status_text' in normalized and not status.get('short_detail'):
            status['short_detail'] = normalized.get('status_text', '')
        if 'period' in normalized and not status.get('period'):
            status['period'] = normalized.get('period', '')
        # display_clock is the canonical nested key (data_fetcher.py builds it,
        # _draw_live_game_status reads it). Writing only 'clock' here left live
        # scroll/Vegas cards rendering "P2" with the game clock silently
        # dropped; 'clock' is kept alongside it for any external consumer.
        if 'clock' in normalized:
            if not status.get('clock'):
                status['clock'] = normalized.get('clock', '')
            if not status.get('display_clock'):
                status['display_clock'] = normalized.get('clock', '')
        if 'display_clock' in normalized and not status.get('display_clock'):
            status['display_clock'] = normalized.get('display_clock', '')
        if 'state' in normalized and not status.get('state'):
            status['state'] = normalized.get('state', '')
        # Fall back to the extractor's booleans so a card rendered outside
        # _collect_games_for_scroll (which injects state from the mode) still
        # picks the right live/final branch instead of drawing nothing.
        if not status.get('state'):
            if normalized.get('is_live'):
                status['state'] = 'in'
            elif normalized.get('is_final'):
                status['state'] = 'post'
            elif normalized.get('is_upcoming'):
                status['state'] = 'pre'
        normalized['status'] = status

        return normalized

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
        # Normalize flat payload fields into nested structure if needed
        # This allows render_game_card to work with both flat and nested game dicts
        game = self._normalize_game_payload(game)

        # Create base image
        main_img = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        # Get league for logo directory
        league = game.get('league', 'nhl')
        logo_dir = Path(self.logo_dirs.get(league, 'assets/sports/nhl_logos'))

        # Get team info (hockey uses home_team/away_team dicts)
        home_team = game.get('home_team', {})
        away_team = game.get('away_team', {})
        home_abbr = home_team.get('abbrev', '')
        away_abbr = away_team.get('abbrev', '')

        # Reserve a strip down the middle for the score/"VS" before sizing the
        # logos, so the two never share pixels.
        logo_slot = self._logo_slot_width()

        # Load logos
        home_logo = self._load_and_resize_logo(
            home_abbr,
            logo_dir / f"{home_abbr}.png",
            league,
            max_width=logo_slot
        )
        away_logo = self._load_and_resize_logo(
            away_abbr,
            logo_dir / f"{away_abbr}.png",
            league,
            max_width=logo_slot
        )

        if not home_logo or not away_logo:
            return self._render_error_card(f"{away_abbr or '?'}@{home_abbr or '?'}")

        center_y = self.display_height // 2

        # Draw logos — each centered within its slot on its side.
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

        # Draw scores (centered) - only for live and recent games
        if game_type in ("live", "recent"):
            home_score = str(home_team.get("score", "0"))
            away_score = str(away_team.get("score", "0"))
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

        # Draw records or rankings if enabled
        if self.show_records or self.show_ranking:
            self._draw_records_or_rankings(draw_overlay, game)

        # Composite the overlay onto main image
        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')

    def _render_error_card(self, message: str) -> Image.Image:
        """Render an error message card."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_text_with_outline(draw, message, (5, 5), self.fonts['status'])
        return img

    def _draw_live_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a live hockey game."""
        # Period and Clock (Top center)
        status = game.get('status', {})
        period = status.get('period', 0)
        clock = status.get('display_clock', '')
        state = status.get('state', '')

        if state == 'in':
            period_clock_text = f"P{period} {clock}".strip()
        elif state == 'post':
            period_clock_text = "Final"
        else:
            period_clock_text = status.get('short_detail', '')

        status_width = draw.textlength(period_clock_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_clock_text, (status_x, status_y), self.fonts['time'])

        # Draw shots on goal (optional)
        league = game.get('league', 'nhl')
        show_shots = self.config.get(league, {}).get('show_shots', False)
        if show_shots:
            shots_font = self.fonts['detail']
            home_shots = str(game.get("home_shots", "0"))
            away_shots = str(game.get("away_shots", "0"))
            shots_text = f"{away_shots}   SHOTS   {home_shots}"
            shots_bbox = draw.textbbox((0, 0), shots_text, font=shots_font)
            shots_height = shots_bbox[3] - shots_bbox[1]
            shots_y = self.display_height - shots_height - 1
            shots_width = draw.textlength(shots_text, font=shots_font)
            shots_x = (self.display_width - shots_width) // 2
            self._draw_text_with_outline(draw, shots_text, (shots_x, shots_y), shots_font)

    def _draw_recent_game_status(self, draw: ImageDraw.Draw, _game: Dict) -> None:
        """Draw status elements for a recently completed hockey game.

        Note: _game parameter reserved for future enhancements (e.g., OT indicator).
        """
        # Final status (Top center)
        status_text = "Final"
        status_width = draw.textlength(status_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, status_text, (status_x, status_y), self.fonts['time'])

    def _upcoming_date_and_time(self, game: Dict) -> Tuple[str, str]:
        """Resolve (date, time) text for an upcoming game from any payload shape.

        The scroll/Vegas path feeds cards straight from the sports extractor,
        which emits flat ``game_date``/``game_time`` (already localized) and a
        ``start_time_utc`` datetime -- it has no ``status.short_detail`` and no
        ``start_time``. Reading only the nested keys is what left these cards
        showing a bare "VS": both lookups missed and each branch drew nothing.
        Prefer the flat keys, then the nested payload built by data_fetcher.py,
        then parse the raw start time as a last resort.
        """
        date_text = str(game.get("game_date", "") or "")
        time_text = str(game.get("game_time", "") or "")
        if date_text or time_text:
            return date_text, time_text

        # Nested shape (data_fetcher.py): "9/19 - 7:00 PM EDT" carries both
        # halves in one string, which overflows the card if drawn as-is.
        short_detail = str(game.get("status", {}).get("short_detail", "") or "")
        if short_detail:
            head, sep, tail = short_detail.partition(" - ")
            date_part, time_part = (head, tail) if sep else ("", head)
            return date_part.strip(), self._compact_time(time_part)

        raw_start = game.get("start_time_utc") or game.get("start_time") or ""
        if not raw_start:
            return "", ""
        try:
            if isinstance(raw_start, datetime):
                start_dt = raw_start
            else:
                start_dt = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            local_dt = start_dt.astimezone(self._display_tzinfo())
            return local_dt.strftime("%m/%d").lstrip("0"), local_dt.strftime("%I:%M%p").lstrip("0")
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Failed to parse start time '{raw_start}': {e}")
            return "", ""

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

        No longer capped at display_height: the card is sized as two
        full-height logos plus the measured gap, so what is left after the gap
        is exactly the logo's share. The cap was what froze the logos at 46px
        on the old flat 128px card.
        """
        available = (self.display_width - self._center_gap_width()) // 2
        # No height cap: the card is sized as "two full-height logos plus the
        # measured gap", so what is left after the gap is exactly the logo's
        # share. The cap is what froze the logos at 46px on a 128px card.
        return max(8, available)

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

    @staticmethod
    def _compact_time(text: str) -> str:
        """Trim "7:00 PM EDT" to "7:00PM" so it fits a 64px-wide half-card."""
        tokens = text.split()
        if not tokens:
            return ""
        # Drop a trailing timezone abbreviation ("EDT"), keeping the meridiem.
        if len(tokens) > 1 and tokens[-1].upper() not in {"AM", "PM"}:
            tokens = tokens[:-1]
        if len(tokens) >= 2 and tokens[-1].upper() in {"AM", "PM"}:
            return "".join(tokens[-2:])
        return tokens[-1]

    def _display_tzinfo(self):
        """Timezone for rendering raw start times; falls back to UTC."""
        configured = (self.config or {}).get("timezone")
        if configured:
            try:
                return ZoneInfo(configured)
            except (KeyError, ValueError, TypeError, OSError) as exc:
                # KeyError covers ZoneInfoNotFoundError. A bad zone name in
                # config should fall back to UTC, not blank the card.
                self.logger.debug("Unusable timezone %r: %s", configured, exc)
        return timezone.utc

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

    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw team records or rankings."""
        # Use configurable detail font, with fallback to hardcoded default
        record_font = self.fonts.get('detail')
        if record_font is None:
            record_font = getattr(self, '_record_font', None)
            if record_font is None:
                try:
                    record_font = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
                except OSError:
                    record_font = ImageFont.load_default()
                self._record_font = record_font

        # Get team info (hockey uses home_team/away_team dicts)
        home_team = game.get('home_team', {})
        away_team = game.get('away_team', {})
        away_abbr = away_team.get('abbrev', '')
        home_abbr = home_team.get('abbrev', '')
        away_record = away_team.get('record', '')
        home_record = home_team.get('record', '')

        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - 4

        # Away team info
        if away_abbr:
            away_text = self._get_team_display_text(away_abbr, away_record)
            if away_text:
                away_record_x = 3
                self._draw_text_with_outline(draw, away_text, (away_record_x, record_y), record_font)

        # Home team info
        if home_abbr:
            home_text = self._get_team_display_text(home_abbr, home_record)
            if home_text:
                home_record_bbox = draw.textbbox((0, 0), home_text, font=record_font)
                home_record_width = home_record_bbox[2] - home_record_bbox[0]
                home_record_x = self.display_width - home_record_width - 3
                self._draw_text_with_outline(draw, home_text, (home_record_x, record_y), record_font)

    def _get_team_display_text(self, abbr: str, record: str) -> str:
        """Get the display text for a team (ranking or record).

        Rankings take precedence over records when both are enabled.
        """
        if self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        if self.show_records:
            return record
        return ''
