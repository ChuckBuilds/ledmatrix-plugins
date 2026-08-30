import logging
import os
import re
import secrets
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import pytz
import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Import simplified dependencies for plugin use
from dynamic_team_resolver import DynamicTeamResolver
# Prefer the core-shipped odds manager (adds cache_ttl support); fall back to
# the bundled copy for cores that don't ship src.base_odds_manager yet.
# Both branches are module-level imports, so they are collision-safe under the
# loader's bare-name isolation rules (see docs/plugin-development/08-*.md).
try:
    from src.base_odds_manager import BaseOddsManager
except ModuleNotFoundError as exc:
    # Fall back only when the CORE module is absent; an import failure from
    # inside it (missing dependency) should surface, not be masked.
    if exc.name not in {"src", "src.base_odds_manager"}:
        raise
    from base_odds_manager import BaseOddsManager
from data_sources import ESPNDataSource
from soccer_timezone import resolve_timezone

# Import main logo downloader (same as football plugin)
import sys
from pathlib import Path
# Add parent directory to path to import from src
plugin_dir = Path(__file__).resolve().parent
project_root = plugin_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from src.logo_downloader import LogoDownloader, download_missing_logo


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



# How far either side of now the schedule is fetched, now configurable. The
# partial fetch that serves the display until the background fetch lands must
# not be narrower than the fetch it substitutes for, or a game inside the real
# window is missing from the panel until that completes -- so both are driven
# from these same two values.
_DEFAULT_LOOKBACK_DAYS = 14
_DEFAULT_LOOKAHEAD_DAYS = 14
_MIN_WINDOW_DAYS = 1
_MAX_WINDOW_DAYS = 60


def _clamp_window(value: Any, fallback: int) -> int:
    """Days for one side of the schedule window, or the default if unusable."""
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: json parses bare Infinity by default, and int(inf) raises.
        return fallback
    return max(_MIN_WINDOW_DAYS, min(_MAX_WINDOW_DAYS, days))


# Backing off the live poll while a league has nothing on. Gentle at first --
# a gap between games in a live season should cost little -- then firmer, so a
# league months out of season stops polling on a live cadence altogether.
_IDLE_SHORT_STREAK = 6
_IDLE_SHORT_FACTOR = 2
_IDLE_LONG_STREAK = 24
_IDLE_LONG_FACTOR = 6
_DEFAULT_LIVE_IDLE_MAX_SECONDS = 900


def _clamp_seconds(value: Any, fallback: int, low: int = 5,
                   high: int = 86400) -> int:
    """An interval in seconds, or the fallback when the value is unusable."""
    try:
        seconds = int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: json parses bare Infinity by default and int(inf)
        # raises -- the same gap _clamp_window above already covers.
        return fallback
    return max(low, min(high, seconds))


class SportsCore(ABC):
    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        self.logger = logger
        self.config = config
        self.cache_manager = cache_manager
        self.config_manager = getattr(cache_manager, "config_manager", None)
        # Initialize odds manager
        self.odds_manager = BaseOddsManager(self.cache_manager, self.config_manager)
        self.display_manager = display_manager
        # Get display dimensions from matrix (same as base SportsCore class)
        # This ensures proper scaling for different display sizes
        if hasattr(display_manager, 'matrix') and display_manager.matrix is not None:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            # Fallback to width/height properties (which also check matrix)
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)

        self.sport_key = sport_key
        self.sport = None
        self.league = None

        # Initialize new architecture components (will be overridden by sport-specific classes)
        self.sport_config = None
        # Initialize data source
        self.data_source = ESPNDataSource(logger)
        # How far either side of now the schedule is fetched, in days.
        # Advanced: a league that plays weekly can have a whole matchweek fall
        # just outside a short horizon, which reads on the panel as "my team
        # never appears" while other clubs do. Bounded so a stray value cannot
        # turn one refresh into a season-wide request against the API.
        self.schedule_lookback_days: int = _clamp_window(
            config.get("schedule_lookback_days"), _DEFAULT_LOOKBACK_DAYS)
        self.schedule_lookahead_days: int = _clamp_window(
            config.get("schedule_lookahead_days"), _DEFAULT_LOOKAHEAD_DAYS)
        self.mode_config = config.get(
            f"{sport_key}_scoreboard", {}
        )  # Changed config key
        self.is_enabled: bool = self.mode_config.get("enabled", False)
        self.show_odds: bool = self.mode_config.get("show_odds", False)
        # Use LogoDownloader to get the correct default logo directory for soccer
        default_logo_dir = Path(LogoDownloader().get_logo_directory("soccer_eng.1"))  # Use eng.1 as default
        self.logo_dir = self._initialize_logo_dir(default_logo_dir)
        self.update_interval: int = self.mode_config.get("update_interval_seconds", 60)
        self.show_records: bool = self.mode_config.get("show_records", False)
        self.show_ranking: bool = self.mode_config.get("show_ranking", False)
        # Number of games to show (instead of time-based windows)
        self.recent_games_to_show: int = self.mode_config.get(
            "recent_games_to_show", 5
        )  # Show last 5 games
        self.upcoming_games_to_show: int = self.mode_config.get(
            "upcoming_games_to_show", 10
        )  # Show next 10 games
        # How many NON-favourite games to add when favourites are set but
        # show_favorite_teams_only is off. 0 makes that mode favourites-only.
        # Defaults match the league-wide counts above, so a board that upgrades
        # keeps every game it was already showing and simply gains its
        # favourites -- the change is additive, never a removal.
        self.other_upcoming_games_to_show: int = self.mode_config.get(
            "other_upcoming_games_to_show", self.upcoming_games_to_show
        )
        self.other_recent_games_to_show: int = self.mode_config.get(
            "other_recent_games_to_show", self.recent_games_to_show
        )
        # Variety comes from turnover, not from a bigger pool. Enlarging the
        # pool makes a lap longer -- roughly one card per visit -- so a wide
        # selection makes any given game RARER. Instead the pool stays short
        # and the non-favourite slice advances on this interval, so over a day
        # the board works through the schedule while a lap still takes minutes.
        # 0 pins the window, restoring the fixed "next N others".
        self.other_rotation_interval_seconds: int = self.mode_config.get(
            "other_rotation_interval_seconds", 1800
        )
        self._other_window_start: int = 0
        self._other_window_rotated_at: float = 0.0
        filtering_config = self.mode_config.get("filtering", {})
        self.show_favorite_teams_only: bool = self.mode_config.get(
            "show_favorite_teams_only",
            filtering_config.get("show_favorite_teams_only", False),
        )
        self.show_all_live: bool = self.mode_config.get(
            "show_all_live",
            filtering_config.get("show_all_live", False),
        )
        try:
            self.favorite_live_boost: int = max(1, min(5, int(self.mode_config.get(
                "favorite_live_boost",
                filtering_config.get("favorite_live_boost", 2),
            ))))
        except (TypeError, ValueError):
            self.favorite_live_boost = 2

        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,  # increased number of retries
            backoff_factor=1,  # increased backoff factor
            # added 429 to retry list
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._logo_cache = {}

        # Set up headers
        self.headers = {
            "User-Agent": "LEDMatrix/1.0 (https://github.com/yourusername/LEDMatrix; contact@example.com)",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        self.last_update = 0
        self.current_game = None
        self._last_rendered_game_id: Optional[str] = None  # Skip redundant redraws
        # Thread safety lock for shared game state
        self._games_lock = threading.RLock()
        self.fonts = self._load_fonts()

        # Initialize dynamic team resolver and resolve favorite teams
        self.dynamic_resolver = DynamicTeamResolver()
        raw_favorite_teams = self.mode_config.get("favorite_teams", [])
        self.favorite_teams = self.dynamic_resolver.resolve_teams(
            raw_favorite_teams, sport_key
        )
        raw_exclude_teams = self.mode_config.get("exclude_teams", [])
        self.exclude_teams = self.dynamic_resolver.resolve_teams(
            raw_exclude_teams, sport_key
        )

        # Log dynamic team resolution
        if raw_favorite_teams != self.favorite_teams:
            self.logger.info(
                f"Resolved dynamic teams: {raw_favorite_teams} -> {self.favorite_teams}"
            )
        else:
            self.logger.info(f"Favorite teams: {self.favorite_teams}")
        if self.exclude_teams:
            self.logger.info(f"Excluded teams: {self.exclude_teams}")

        self.logger.setLevel(logging.INFO)

        # Initialize team rankings cache
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        self._rankings_cache_duration = 3600  # Cache rankings for 1 hour
        
        # Initialize warning tracking
        self._last_warning_time = 0

        # Initialize background data service with optimized settings
        # Hardcoded for memory optimization: 1 worker, 30s timeout, 3 retries
        try:
            from src.background_data_service import get_background_service

            self.background_service = get_background_service(
                self.cache_manager, max_workers=1
            )
            self.background_fetch_requests = {}  # Track background fetch requests
            self.background_enabled = True
            self.logger.info(
                "Background service enabled with 1 worker (memory optimized)"
            )
        except ImportError:
            # Fallback if background service is not available
            self.background_service = None
            self.background_fetch_requests = {}
            self.background_enabled = False
            self.logger.warning(
                "Background service not available - using synchronous fetching"
            )

    def _is_favorite_game(self, game: Dict) -> bool:
        return bool(self.favorite_teams) and (
            game.get("home_abbr") in self.favorite_teams
            or game.get("away_abbr") in self.favorite_teams
        )

    def _effective_live_duration(self, game):
        """How long the given live game should stay on screen before rotating.

        Non-favorite live games use non_favorite_live_game_duration, but only
        when it is set (> 0) AND favorite teams are configured. With no favorites
        (or the knob at 0) every live game uses game_display_duration - identical
        to the prior single-duration behavior. When show_favorite_teams_only is
        on, non-favorite games are never shown, so this naturally never fires."""
        non_fav = getattr(self, "non_favorite_live_game_duration", 0) or 0
        if (
            non_fav > 0
            and self.favorite_teams
            and game is not None
            and not self._is_favorite_game(game)
        ):
            return non_fav
        return self.game_display_duration

    def _classify_live_game(self, home_abbr, away_abbr) -> bool:
        """Whether a live game should be included in the live rotation.

        Priority: excluded team (never shown, overrides everything) >
        show_all_live > show_favorite_teams_only disabled > no favorites
        configured (fallback: show all) > favorite-teams-only membership.
        """
        if home_abbr in self.exclude_teams or away_abbr in self.exclude_teams:
            return False
        if self.show_all_live:
            return True
        if not self.show_favorite_teams_only:
            return True
        if not self.favorite_teams:
            return True
        return home_abbr in self.favorite_teams or away_abbr in self.favorite_teams

    def _swrr_advance(self, games: List[Dict]) -> Optional[Dict]:
        """Pick the next live game to display via Smooth Weighted Round-Robin.

        Favorite-team games get weight ``favorite_live_boost`` (shown that many
        turns for every 1 turn other live games get); everything else gets
        weight 1. Per-game weight state (``self._swrr_weights``) persists
        across calls so spacing stays even indefinitely - no fixed-length
        cycle, so no clustering seam at a cycle boundary. A brand-new game
        (including a favorite's game that just went live) starts at weight 0
        and gets its full weight added on the very next call, so a live
        favorite naturally wins the first pick after it appears ("queued
        first" on refresh) without any special-cased branch.

        With ``favorite_live_boost == 1`` (or no favorite live), every game
        has weight 1, so this always just returns games in their existing
        order - identical behavior to the plain round-robin it replaces.
        """
        if not games:
            return None
        weights = {}
        for g in games:
            gid = g.get("id")
            if gid is None:
                continue
            weights[gid] = self.favorite_live_boost if self._is_favorite_game(g) else 1
        if not weights:
            return None

        if not hasattr(self, "_swrr_weights"):
            self._swrr_weights = {}
        # Drop state for games no longer live; keep it for games still live.
        self._swrr_weights = {gid: w for gid, w in self._swrr_weights.items() if gid in weights}

        for gid, w in weights.items():
            self._swrr_weights[gid] = self._swrr_weights.get(gid, 0) + w

        total_weight = sum(weights.values())
        ids_in_order = [g.get("id") for g in games if g.get("id") in weights]
        best_gid = max(ids_in_order, key=lambda gid: self._swrr_weights[gid])
        self._swrr_weights[best_gid] -= total_weight
        return next(g for g in games if g.get("id") == best_gid)

    def _initialize_logo_dir(self, configured_path: Path) -> Path:
        """Resolve and ensure a writable logo directory, falling back when necessary."""
        downloader = LogoDownloader()
        resolved_configured = self._resolve_project_path(configured_path)
        candidates = [resolved_configured] + self._get_logo_directory_fallbacks(resolved_configured)

        for candidate in candidates:
            candidate_path = self._resolve_project_path(candidate)
            if downloader.ensure_logo_directory(str(candidate_path)):
                if candidate_path != resolved_configured:
                    self.logger.warning(
                        "Configured logo directory '%s' is not writable; using fallback '%s'",
                        resolved_configured,
                        candidate_path,
                    )
                return candidate_path

        self.logger.error(
            "Unable to find a writable logo directory. Logos may fail to download (last attempted: %s)",
            resolved_configured,
        )
        return resolved_configured

    def _resolve_project_path(self, path: Path) -> Path:
        """Convert relative paths to absolute ones rooted at the project directory."""
        if path.is_absolute():
            return path
        # For plugin, go up 2 levels: plugin_dir -> plugins -> project_root
        plugin_dir = Path(__file__).resolve().parent
        project_root = plugin_dir.parent.parent
        return (project_root / path).resolve()

    def _get_logo_directory_fallbacks(self, configured_dir: Path) -> List[Path]:
        """Return fallback directories to try when the configured directory is not writable."""
        import tempfile
        fallbacks: List[Path] = []

        env_override = os.environ.get("LEDMATRIX_LOGO_DIR")
        if env_override:
            env_path = Path(env_override)
            if not env_path.is_absolute():
                env_path = self._resolve_project_path(env_path)
            fallbacks.append(env_path / "soccer_logos")

        cache_dir = getattr(self.cache_manager, "cache_dir", None)
        if cache_dir:
            fallbacks.append(Path(cache_dir) / "logos" / "soccer")

        try:
            fallbacks.append(Path.home() / ".ledmatrix" / "logos" / "soccer")
        except Exception:
            pass

        fallbacks.append(Path(tempfile.gettempdir()) / "ledmatrix_logos" / "soccer")

        unique_fallbacks: List[Path] = []
        seen = set()
        for candidate in fallbacks:
            if candidate == configured_dir:
                continue
            if candidate not in seen:
                unique_fallbacks.append(candidate)
                seen.add(candidate)

        return unique_fallbacks

    def _get_season_schedule_dates(self) -> tuple[str, str]:
        return "", ""

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Placeholder draw method - subclasses should override."""
        # This base method will be simple, subclasses provide specifics
        try:
            img = Image.new("RGB", (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            status = game.get("status_text", "N/A")
            self._draw_text_with_outline(draw, status, (2, 2), self.fonts["status"])
            self.display_manager.image.paste(img, (0, 0))
            # Don't call update_display here, let subclasses handle it after drawing
        except Exception as e:
            self.logger.error(
                f"Error in base _draw_scorebug_layout: {e}", exc_info=True
            )

    def display(self, force_clear: bool = False) -> bool:
        """Render the current game. Returns False when nothing can be shown."""
        if not self.is_enabled:  # Check if module is enabled
            return False

        if not self.current_game:
            # Don't clear the display when returning False - let the caller handle skipping
            # Clearing here would show a blank screen before the next mode is displayed
            current_time = time.time()
            if not hasattr(self, "_last_warning_time"):
                self._last_warning_time = 0
            if current_time - getattr(self, "_last_warning_time", 0) > 300:
                self.logger.warning(
                    f"No game data available to display in {self.__class__.__name__}"
                )
                setattr(self, "_last_warning_time", current_time)
            return False

        try:
            self._draw_scorebug_layout(self.current_game, force_clear)
            # display_manager.update_display() should be called within subclass draw methods
            # or after calling display() in the main loop. Let's keep it out of the base display.
            return True
        except Exception as e:
            self.logger.error(
                f"Error during display call in {self.__class__.__name__}: {e}",
                exc_info=True,
            )
            return False


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

    def _load_custom_font_from_element_config(self, element_config: Dict[str, Any], default_size: int = 8, element_key=None, default_font: Optional[str] = None) -> ImageFont.FreeTypeFont:
        """
        Load a custom font from an element configuration dictionary.
        
        Args:
            element_config: Configuration dict for a single element containing 'font' and 'font_size' keys
            default_size: Default font size if not specified in config
            
        Returns:
            PIL ImageFont object
        """
        # Get font name and size, with defaults
        # Falls back to the caller's face, not always PressStart2P: the
        # schema declares 4x6-font for the detail element, so without this
        # a bare config rendered detail in the wrong face.
        base_default = default_font or 'PressStart2P-Regular.ttf'
        font_name = element_config.get('font', base_default)
        # Resolve a family alias to its filename BEFORE the path is built.
        # The grid table understands aliases, so a configured
        # "four_by_six" was sized on the 4x6 grid (7px) while the path
        # lookup used the raw alias, missed, and fell back to
        # PressStart2P -- rendering 7px on an 8px grid, anti-aliased.
        font_name = self._FONT_NAME_ALIASES.get(font_name, font_name)
        font_size = self._resolve_font_size(
            element_config, element_key, default_size, font_name)
        
        # Build font path
        font_path = _resolve_font_path(os.path.join('assets', 'fonts', font_name))
        
        # Try to load the font
        try:
            if os.path.exists(font_path):
                # Try loading as TTF first (works for both TTF and some BDF files with PIL)
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    self.logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    # PIL's ImageFont.truetype() can sometimes handle BDF files
                    # If it fails, we'll fall through to the default font
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        self.logger.debug(f"Loaded BDF font: {font_name} at size {font_size}")
                        return font
                    except Exception:
                        self.logger.warning(f"Could not load BDF font {font_name} with PIL, using default")
                        # Fall through to default
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, using default")
        
        # Fall back to default font
        default_font_path = _resolve_font_path(os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf'))
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                self.logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()

    def _get_layout_offset(self, element: str, axis: str, default: int = 0) -> int:
        """
        Get layout offset for a specific element and axis.

        Args:
            element: Element name (e.g., 'home_logo', 'score', 'status_text')
            axis: 'x_offset' or 'y_offset' (or 'away_x_offset', 'home_x_offset' for records)
            default: Default value if not configured (default: 0)

        Returns:
            Offset value from config or default (always returns int)
        """
        try:
            layout_config = self.config.get('customization', {}).get('layout', {})
            element_config = layout_config.get(element, {})
            offset_value = element_config.get(axis, default)

            # Ensure we return an integer (handle float/string from config)
            if isinstance(offset_value, (int, float)):
                return int(offset_value)
            elif isinstance(offset_value, str):
                try:
                    return int(float(offset_value))
                except ValueError:
                    self.logger.warning(f"Invalid offset value '{offset_value}' for {element}.{axis}, using default {default}")
                    return default
            return default
        except Exception as e:
            self.logger.debug(f"Error getting layout offset for {element}.{axis}: {e}, using default {default}")
            return default

    # ------------------------------------------------------------------
    # Favorite-team result colors for finished games.
    #
    # In scroll and Vegas modes the same two logos cycle past over and over --
    # a four-game series against a division rival is four near-identical cards
    # -- and picking out which side is yours from the digits alone is the whole
    # problem. Tinting the final score by how the favorite did makes it
    # readable at a glance. Off by default, so an existing install keeps the
    # score color it has today until the user opts in.
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

    @staticmethod
    def _side_is_favorite(game: Dict, side: str, favorites: set) -> bool:
        """Is the home/away side of this game a favorite team?

        Both the abbreviation and the ESPN id are checked, because a couple of
        leagues (NRL) match favorites by id where abbreviations collide.
        """
        for key in (f"{side}_abbr", f"{side}_id"):
            value = game.get(key)
            if value is not None and str(value).strip().upper() in favorites:
                return True
        return False

    def _favorite_result(self, game: Dict) -> Optional[str]:
        """Say how the favorite team did in a finished game.

        Returns 'win', 'loss' or 'tie', or None when there is no single team
        to root for: no favorites configured, neither side is a favorite, or
        *both* are -- a favorite-vs-favorite game has no losing side worth
        flagging in red. Also None when the scores are not usable numbers.
        """
        favorites = getattr(self, "favorite_teams", None) or []
        favorites = {str(team).strip().upper() for team in favorites if str(team).strip()}
        if not favorites:
            return None

        home_fav = self._side_is_favorite(game, "home", favorites)
        away_fav = self._side_is_favorite(game, "away", favorites)
        if home_fav == away_fav:
            return None

        try:
            # int(float(...)) to match GameRenderer._side_score exactly -- the
            # two paths must agree on what counts as a usable score.
            home_score = int(float(str(game.get("home_score", "")).strip()))
            away_score = int(float(str(game.get("away_score", "")).strip()))
        except (TypeError, ValueError):
            return None

        if home_score == away_score:
            return "tie"
        favorite_score, other_score = (
            (home_score, away_score) if home_fav else (away_score, home_score)
        )
        return "win" if favorite_score > other_score else "loss"

    def _recent_score_color(self, game: Dict, default):
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

    #: How far each logo is shifted outward, off the panel edge, by the
    #: scorebug layouts (they paste at -2 and width - logo_width + 2). Kept
    #: here because the logo sizing has to know it.
    _LOGO_EDGE_BLEED_PX: ClassVar[int] = 2

    #: How far the score may cross onto each logo. Held fixed rather than as a
    #: fraction of the score, so the crossing stays what it was tuned for as
    #: the score grows with the panel.
    _SCORE_LOGO_OVERLAP_PX: ClassVar[int] = 10

    def _scorebug_centre_gap(self) -> int:
        """Width the centre keeps clear for the score, in the scorebug layout.

        Not the score's full width: reserving all of it on a narrow panel
        leaves two slivers where the logos should be, and trading a crowded
        card for one with no identifiable team is not a fix. The reserve lets
        the score's outer edge cross onto each logo by a fixed
        _SCORE_LOGO_OVERLAP_PX, and the digits are drawn with an outline, so
        the crossing reads as a score in front of a logo rather than two
        things fighting.

        Measured from the score font so it tracks the panel-scaled size (and a
        user who sets a larger one), and from a fixed five-character string
        rather than the live score, because the logo cache is keyed on team
        and must not resize when a side passes 9 points.
        """
        # No reserve until the score has actually grown. The cap below costs
        # logo width, and on a panel where the score is still 8px there is no
        # benefit to pay for it with: a 64x32 board would have watched a
        # square logo drop from 48x48 to 24x24 in a change about score size.
        # Gating here keeps every panel whose score did not move byte-identical
        # -- the same thing _scale_headline_fonts does by returning early at or
        # below the design height.
        if not getattr(self, '_score_grew', False):
            return 0

        try:
            probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
            width = int(probe.textlength(
                self._SCORE_PROBE_TEXT, font=self.fonts["score"]))
            return max(width // 2, width - 2 * self._SCORE_LOGO_OVERLAP_PX)
        except Exception:
            return 22

    #: Most the score may grow, as a multiple of its design size. The same
    #: ceiling football's adaptive layout settled on and for the same measured
    #: reason (_ADAPTIVE_SCORE_TARGET_PX): "8 reads thin on a tall card; 24
    #: needs a 128px gap and buys mostly dead space. 16 doubles the score for
    #: 40px of extra card and costs nothing in logo size." Without it a
    #: 256x128 board takes a 32px score, whose reserve leaves each logo 60px
    #: of a 256-wide panel -- a postage stamp in a 128-tall slot.
    _SCORE_MAX_GROWTH: ClassVar[int] = 2

    #: Score may occupy this share of the panel width before the layout reaches
    #: for a narrower face. Football's long-standing value, ported here with the
    #: mechanism it belongs to.
    _SCORE_WIDTH_BUDGET: ClassVar[float] = 0.55

    #: Narrower crisp rungs to fall back through, widest first. 4x6-font renders
    #: cleanly at multiples of 7 and is about half the width of PressStart2P per
    #: character.
    _NARROW_SCORE_RUNGS = (("4x6-font.ttf", 14), ("4x6-font.ttf", 7))

    def _fit_score_font(self, fonts):
        """Swap in a narrower face where the score would swamp the panel.

        Ported from football-scoreboard, which has had it for a while and is the
        only reason its logos read larger than every other scoreboard's at the
        same panel size. Measured on a 128x64 board, all else equal: football
        reserves 28px for a 4x6 score at 14px and gets 60x60 logos; the same card
        with PressStart2P at 16px reserves 60px and gets 36x36 -- two small
        badges adrift in a mostly black panel.

        The trade is a good one because the two faces are nothing like the same
        shape. PressStart2P is square: 16px tall costs 16px per character.
        4x6-font at 14px is nearly as tall and about half as wide, so the score
        keeps its size in the dimension that carries legibility and gives back
        the dimension the logos actually need.

        Only swaps above the design height, and only when the current face
        genuinely overflows the budget, so every 32-tall panel -- where the
        score does not grow at all -- keeps the face it has.
        """
        if getattr(self, 'display_height', 0) <= self._FONT_DESIGN_HEIGHT:
            return fonts
        try:
            from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont
            probe = _ImageDraw.Draw(_Image.new("RGB", (4, 4)))
            budget = self.display_width * self._SCORE_WIDTH_BUDGET
            if probe.textlength(getattr(self, "_SCORE_PROBE_TEXT", "00-00"), font=fonts["score"]) <= budget:
                return fonts
            for name, size in self._NARROW_SCORE_RUNGS:
                candidate = _ImageFont.truetype(
                    _resolve_font_path(f"assets/fonts/{name}"), size)
                if probe.textlength(getattr(self, "_SCORE_PROBE_TEXT", "00-00"), font=candidate) <= budget:
                    # The clock moves with the score so the two stay visually
                    # related, exactly as football does it.
                    fonts["score"] = candidate
                    fonts["time"] = candidate
                    self._score_grew = True
                    return fonts
            name, size = self._NARROW_SCORE_RUNGS[-1]
            narrowest = _ImageFont.truetype(
                _resolve_font_path(f"assets/fonts/{name}"), size)
            fonts["score"] = narrowest
            fonts["time"] = narrowest
            self._score_grew = True
        except Exception:
            self.logger.debug("Score font fitting skipped", exc_info=True)
        return fonts

    #: Share of the panel width the score may take once it is allowed to grow.
    #: Deliberately not football's _SCORE_WIDTH_BUDGET (0.55), which answers a
    #: different question -- when to swap PressStart for a narrower FACE -- and
    #: is tuned for a 32-tall panel where the logos have no spare height. 0.55
    #: cannot fit a 16px score under 146px of panel, so a 128-wide board could
    #: never reach one no matter how tall it got: 128x64 paid for the change
    #: and got nothing back. A taller panel can afford a wider score because
    #: its logos have height to spend instead, and 0.65 is what a 16px score
    #: needs at 128 wide (80px of 128 is 0.625).
    _SCORE_GROWTH_BUDGET: ClassVar[float] = 0.65

    #: Widest score this sport realistically shows, used to size the centre
    #: reserve and the score's width budget. A fixed string rather than the
    #: live score, because the logo cache is keyed on team and must not
    #: resize when a side passes 9 points -- but it has to be wide enough for
    #: the sport: basketball and AFL run to three digits a side, so measuring
    #: them against "00-00" reserved two characters less than the score
    #: actually needs and it was drawn onto the logos either side.
    _SCORE_PROBE_TEXT: ClassVar[str] = "00-00"

    #: Panel height the fixed font sizes below were chosen against. Everything
    #: else on the card is sized from display_height -- the logos most of all
    #: -- so on a taller panel they grew and the score did not.
    _FONT_DESIGN_HEIGHT: ClassVar[int] = 32

    def _score_font_size(self) -> int:
        """Pixel size the score is currently drawn at."""
        return getattr(self.fonts.get("score"), "size", 8) or 8

    def _time_font_size(self) -> int:
        """Pixel size the clock/date face is currently drawn at."""
        return getattr(self.fonts.get("time"), "size", 8) or 8

    def _user_chose_size(self, element_key: str) -> bool:
        """True when customization.<element>.font_size is a real choice.

        The web UI's save flow writes the whole schema default block into
        config.json on every save, whether or not the user touched that
        section, so a size merely being PRESENT carries no intent. Only one
        that differs from the schema default does.
        """
        element = (self.config.get('customization', {}) or {}).get(element_key) or {}
        configured = element.get('font_size')
        if configured is None:
            return False
        try:
            return int(configured) != self._schema_font_size(element_key)
        except (TypeError, ValueError):
            return False

    def _grid_scaled_size(self, font):
        """(path, grid, size) for *font* regrown to this panel's height.

        None when the panel is at or below the design height (nothing to do),
        or when the face has no known pixel grid -- a user-supplied font is
        never second-guessed, because we do not know what it renders crisply
        at.
        """
        path = getattr(font, 'path', None)
        base = getattr(font, 'size', None)
        if not base or not isinstance(path, str):
            return None
        face = os.path.basename(path)
        grid = self._FONT_PIXEL_GRID.get(self._FONT_NAME_ALIASES.get(face, face))
        if not grid:
            return None
        scale = float(self.display_height) / (self._FONT_DESIGN_HEIGHT or 32)
        if scale <= 1.0:
            return None
        return path, grid, max(int(base), int(self._crisp_size(face, base * scale)))

    def _scale_headline_fonts(self, fonts):
        """Grow the score with the panel, and hold the clock/date below it.

        The score is the one number the card exists to show, and it was the
        only element not sized from the panel. Worse, it was not even bigger
        than its neighbours: PressStart2P renders crisply on an 8px grid, so
        the 10px default snapped to 8 -- the same 8 the period/clock above it
        and the game date below it are drawn at. Three lines of identical
        type, none of them the headline, which is what makes the score read as
        lower priority than the time and the date rather than the point of the
        card.

        So the score is sized from display_height and snapped to its face's
        pixel grid (off the grid FreeType anti-aliases the strokes, and on an
        LED matrix a part-lit pixel is a dim lamp rather than a soft edge),
        then stepped back down that grid until it fits its share of the width.
        The clock/date face is regrown the same way but held at least one grid
        step below the score, so the ranking between them is visible rather
        than implied.

        A 32-tall panel scales by exactly 1.0 and is left byte-identical; a
        size the user set explicitly is never overridden.
        """
        self._score_grew = False
        try:
            scaled = None if self._user_chose_size('score_text') else \
                self._grid_scaled_size(fonts.get('score'))
            if scaled is not None:
                path, grid, size = scaled
                base = getattr(fonts['score'], 'size', size) or size
                size = min(size, base * self._SCORE_MAX_GROWTH)
                probe = ImageDraw.Draw(Image.new('RGB', (4, 4)))
                budget = self.display_width * self._SCORE_GROWTH_BUDGET
                # Measured from a fixed five-character score rather than the
                # live one, so the card does not resize when a side passes 9.
                while size > grid:
                    if probe.textlength(
                            self._SCORE_PROBE_TEXT,
                            font=ImageFont.truetype(path, size)) <= budget:
                        break
                    size -= grid
                if size != getattr(fonts['score'], 'size', size):
                    fonts['score'] = ImageFont.truetype(path, size)
                    self._score_grew = True

            if not self._score_grew and not self._user_chose_size('score_text') \
                    and self.display_height > self._FONT_DESIGN_HEIGHT:
                # PressStart2P could not grow inside the budget -- its next crisp
                # size is simply too wide for this panel. A narrower face still
                # can: 4x6-font at 14px is nearly as tall as PressStart2P at 16
                # and about half as wide. This matters beyond the score itself,
                # because a card whose score never grows never reserves the
                # centre either, so its logos stay at the uncapped 1.5x and are
                # drawn straight over the score -- which is what a three-digit
                # basketball score does on a 128x64 board.
                probe = ImageDraw.Draw(Image.new('RGB', (4, 4)))
                budget = self.display_width * self._SCORE_GROWTH_BUDGET
                current = getattr(fonts.get('score'), 'size', 0) or 0
                for _name, _size in self._NARROW_SCORE_RUNGS:
                    if _size <= current:
                        continue
                    _path = _resolve_font_path(f"assets/fonts/{_name}")
                    _candidate = ImageFont.truetype(_path, _size)
                    if probe.textlength(self._SCORE_PROBE_TEXT,
                                        font=_candidate) <= budget:
                        fonts['score'] = _candidate
                        self._score_grew = True
                        break

            scaled = None if self._user_chose_size('period_text') else \
                self._grid_scaled_size(fonts.get('time'))
            if scaled is not None:
                path, grid, size = scaled
                ceiling = getattr(fonts.get('score'), 'size', 0) or 0
                if ceiling and size >= ceiling:
                    size = max(grid, ceiling - grid)
                if size != getattr(fonts['time'], 'size', size):
                    fonts['time'] = ImageFont.truetype(path, size)
        except Exception:
            self.logger.debug("Headline font scaling skipped", exc_info=True)
        return fonts

    def _load_fonts(self):
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}
        
        # Get customization config, with backward compatibility
        customization = self.config.get('customization', {})
        
        # Load fonts from config with defaults for backward compatibility
        score_config = customization.get('score_text', {})
        period_config = customization.get('period_text', {})
        team_config = customization.get('team_name', {})
        status_config = customization.get('status_text', {})
        detail_config = customization.get('detail_text', {})
        rank_config = customization.get('rank_text', {})
        
        try:
            fonts["score"] = self._load_custom_font_from_element_config(score_config, default_size=10, element_key='score_text')
            fonts["time"] = self._load_custom_font_from_element_config(period_config, default_size=8, element_key='period_text')
            fonts["team"] = self._load_custom_font_from_element_config(team_config, default_size=8, element_key='team_name')
            fonts["status"] = self._load_custom_font_from_element_config(status_config, default_size=6, element_key='status_text')
            fonts["detail"] = self._load_custom_font_from_element_config(detail_config, default_size=6, element_key='detail_text', default_font='4x6-font.ttf')
            fonts["rank"] = self._load_custom_font_from_element_config(rank_config, default_size=10, element_key='rank_text')
            self.logger.info("Successfully loaded fonts from config")
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
                fonts["score"] = ImageFont.load_default()
                fonts["time"] = ImageFont.load_default()
                fonts["team"] = ImageFont.load_default()
                fonts["status"] = ImageFont.load_default()
                fonts["detail"] = ImageFont.load_default()
                fonts["rank"] = ImageFont.load_default()
        # Record/ranking annotations always use the small 4x6 face; cached here
        # (after both branches, so it is set on every path) so the scorebug
        # draw paths don't reload it from disk every frame.
        try:
            fonts["record"] = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
        except OSError:
            fonts["record"] = ImageFont.load_default()
        # Grow first, then fit: _scale_headline_fonts sizes the score from
        # the panel height, and _fit_score_font is the guard that swaps in a
        # narrower FACE rather than let a grown score crowd out the logos.
        return self._fit_score_font(self._scale_headline_fonts(fonts))

    def _draw_dynamic_odds(
        self, draw: ImageDraw.Draw, odds: Dict[str, Any], width: int, height: int
    ) -> None:
        """Draw odds with dynamic positioning - only show negative spread and position O/U based on favored team."""
        try:
            # Skip odds rendering in test mode or if odds data is invalid
            if (
                not odds
                or isinstance(odds, dict)
                and any(
                    isinstance(v, type) and hasattr(v, "__call__")
                    for v in odds.values()
                )
            ):
                self.logger.debug("Skipping odds rendering - test mode or invalid data")
                return

            self.logger.debug(f"Drawing odds with data: {odds}")

            home_team_odds = odds.get("home_team_odds", {})
            away_team_odds = odds.get("away_team_odds", {})
            home_spread = home_team_odds.get("spread_odds")
            away_spread = away_team_odds.get("spread_odds")

            # Get top-level spread as fallback
            top_level_spread = odds.get("spread")

            # If we have a top-level spread and the individual spreads are None or 0, use the top-level
            if top_level_spread is not None:
                if home_spread is None or home_spread == 0.0:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = -top_level_spread

            # Determine which team is favored (has negative spread)
            # Add type checking to handle Mock objects in test environment
            home_favored = False
            away_favored = False

            if home_spread is not None and isinstance(home_spread, (int, float)):
                home_favored = home_spread < 0
            if away_spread is not None and isinstance(away_spread, (int, float)):
                away_favored = away_spread < 0

            # Only show the negative spread (favored team)
            favored_spread = None
            favored_side = None

            if home_favored:
                favored_spread = home_spread
                favored_side = "home"
                self.logger.debug(f"Home team favored with spread: {favored_spread}")
            elif away_favored:
                favored_spread = away_spread
                favored_side = "away"
                self.logger.debug(f"Away team favored with spread: {favored_spread}")
            else:
                self.logger.debug(
                    "No clear favorite - spreads: home={home_spread}, away={away_spread}"
                )

            # Show the negative spread on the appropriate side
            if favored_spread is not None:
                spread_text = str(favored_spread)
                font = self.fonts["detail"]  # Use detail font for odds

                if favored_side == "home":
                    # Home team is favored, show spread on right side
                    spread_width = draw.textlength(spread_text, font=font)
                    spread_x = width - spread_width  # Top right
                    spread_y = 0
                    self._draw_text_with_outline(
                        draw, spread_text, (spread_x, spread_y), font, fill=(0, 255, 0)
                    )
                    self.logger.debug(
                        f"Showing home spread '{spread_text}' on right side"
                    )
                else:
                    # Away team is favored, show spread on left side
                    spread_x = 0  # Top left
                    spread_y = 0
                    self._draw_text_with_outline(
                        draw, spread_text, (spread_x, spread_y), font, fill=(0, 255, 0)
                    )
                    self.logger.debug(
                        f"Showing away spread '{spread_text}' on left side"
                    )

            # Show over/under on the opposite side of the favored team
            over_under = odds.get("over_under")
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                font = self.fonts["detail"]  # Use detail font for odds
                ou_width = draw.textlength(ou_text, font=font)

                if favored_side == "home":
                    # Home favored, show O/U on left side (opposite of spread)
                    ou_x = 0  # Top left
                    ou_y = 0
                    self.logger.debug(
                        f"Showing O/U '{ou_text}' on left side (home favored)"
                    )
                elif favored_side == "away":
                    # Away favored, show O/U on right side (opposite of spread)
                    ou_x = width - ou_width  # Top right
                    ou_y = 0
                    self.logger.debug(
                        f"Showing O/U '{ou_text}' on right side (away favored)"
                    )
                else:
                    # No clear favorite, show O/U in center
                    ou_x = (width - ou_width) // 2
                    ou_y = 0
                    self.logger.debug(
                        f"Showing O/U '{ou_text}' in center (no clear favorite)"
                    )

                self._draw_text_with_outline(
                    draw, ou_text, (ou_x, ou_y), font, fill=(0, 255, 0)
                )

        except Exception as e:
            self.logger.error(f"Error drawing odds: {e}", exc_info=True)

    def _draw_text_with_outline(
        self, draw, text, position, font, fill=(255, 255, 255), outline_color=(0, 0, 0)
    ):
        """Draw text with a black outline for better readability."""
        # Disable anti-aliasing: pixel/bitmap fonts (e.g. PressStart2P) get
        # anti-aliased into dim partial-lit pixels on a 1:1 LED matrix, muddying
        # glyphs. 1-bit mode keeps strokes crisp.
        draw.fontmode = "1"
        x, y = position
        for dx, dy in [
            (-1, -1),
            (-1, 0),
            (-1, 1),
            (0, -1),
            (0, 1),
            (1, -1),
            (1, 0),
            (1, 1),
        ]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def _load_and_resize_logo(
        self, team_id: str, team_abbrev: str, logo_path: Path, logo_url: str | None
    ) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching and automatic download if missing."""
        self.logger.debug(f"Logo path: {logo_path}")
        if team_abbrev in self._logo_cache:
            self.logger.debug(f"Using cached logo for {team_abbrev}")
            return self._logo_cache[team_abbrev]

        try:
            # Try different filename variations first (for cases like TA&M vs TAANDM)
            actual_logo_path = None
            filename_variations = LogoDownloader.get_logo_filename_variations(team_abbrev)
            
            for filename in filename_variations:
                test_path = logo_path.parent / filename
                if test_path.exists():
                    actual_logo_path = test_path
                    self.logger.debug(f"Found logo at alternative path: {actual_logo_path}")
                    break
            
            # If no variation found, try to download missing logo
            if not actual_logo_path and not logo_path.exists():
                self.logger.info(f"Logo not found for {team_abbrev} at {logo_path}. Attempting to download.")
                
                # Map sport_key/league to logo downloader format
                # LogoDownloader uses format "soccer_{league_code}" for soccer leagues
                # sport_key might be like "eng.1", "esp.1", etc. or a full league identifier
                if hasattr(self, 'league') and self.league:
                    # Use the league attribute if available (e.g., "eng.1")
                    league = f"soccer_{self.league}"
                elif self.sport_key and '.' in self.sport_key:
                    # If sport_key is already a league code (e.g., "eng.1")
                    league = f"soccer_{self.sport_key}"
                else:
                    # Fallback: try to use sport_key directly or default to eng.1
                    league = f"soccer_{self.sport_key}" if self.sport_key else "soccer_eng.1"
                
                # Use main logo downloader (same as football plugin) - handles path resolution and permissions
                download_missing_logo(league, team_id, team_abbrev, logo_path, logo_url)
                actual_logo_path = logo_path

            # Use the original path if no alternative was found
            if not actual_logo_path:
                actual_logo_path = logo_path

            # Only try to open the logo if the file exists
            if os.path.exists(actual_logo_path):
                logo = Image.open(actual_logo_path)
            else:
                self.logger.error(f"Logo file still doesn't exist at {actual_logo_path} after download attempt")
                return None
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')

            # 1.5x the panel so the logo bleeds off the outer edge -- the look
            # this layout is built around. The height stays at 1.5x
            # unconditionally, but the WIDTH is capped by what the panel can
            # spare: the centre has to keep room for the score, and each logo
            # may reach inward only as far as the edge of that gap plus the
            # couple of pixels it is already shifted outward by.
            #
            # Without the cap this was 1.5x the panel WIDTH -- 288px on a
            # 192-wide panel -- so a wide mark ran most of the way to the
            # centre from both sides and the score was drawn on top of it.
            max_height = int(self.display_height * 1.5)
            max_width = int(self.display_width * 1.5)
            centre_gap = self._scorebug_centre_gap()
            if centre_gap > 0:
                # Only once the score has grown into the middle -- see
                # _scorebug_centre_gap. Otherwise the 1.5x sizing above stands
                # exactly as it always has.
                reach = ((self.display_width - centre_gap) // 2
                         + self._LOGO_EDGE_BLEED_PX)
                max_width = max(8, min(max_width, reach))
            logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            self._logo_cache[team_abbrev] = logo
            return logo

        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}", exc_info=True)
            return None

    def _fetch_odds(self, game: Dict) -> None:
        """Fetch odds for a specific game using async threading to prevent blocking."""
        try:
            if not self.show_odds:
                return

            # Determine update interval based on game state
            is_live = game.get("is_live", False)
            update_interval = (
                self.mode_config.get("live_odds_update_interval", 60)
                if is_live
                else self.mode_config.get("odds_update_interval", 3600)
            )

            # For upcoming games, use async fetch with short timeout to avoid blocking
            # For live games, we want odds more urgently, but still use async to prevent blocking
            import threading
            import queue
            
            result_queue = queue.Queue()
            
            def fetch_odds():
                try:
                    odds_result = self.odds_manager.get_odds(
                        sport=self.sport,
                        league=self.league,
                        event_id=game["id"],
                        update_interval_seconds=update_interval,
                    )
                    result_queue.put(('success', odds_result))
                except Exception as e:
                    result_queue.put(('error', e))
            
            # Start odds fetch in a separate thread
            odds_thread = threading.Thread(target=fetch_odds)
            odds_thread.daemon = True
            odds_thread.start()
            
            # Wait for result with timeout (shorter for upcoming games)
            timeout = 2.0 if is_live else 1.5  # Live games get slightly longer timeout
            try:
                result_type, result_data = result_queue.get(timeout=timeout)
                if result_type == 'success':
                    odds_data = result_data
                    if odds_data:
                        game["odds"] = odds_data
                        self.logger.debug(
                            f"Successfully fetched and attached odds for game {game['id']}"
                        )
                    else:
                        self.logger.debug(f"No odds data returned for game {game['id']}")
                else:
                    self.logger.debug(f"Odds fetch failed for game {game['id']}: {result_data}")
            except queue.Empty:
                # Timeout - odds will be fetched on next update if needed
                # This prevents blocking the entire update() method
                self.logger.debug(f"Odds fetch timed out for game {game['id']} (non-blocking)")

        except Exception as e:
            self.logger.error(
                f"Error fetching odds for game {game.get('id', 'N/A')}: {e}"
            )

    def _get_timezone(self):
        """Timezone event start times are rendered in.

        Normally the plugin manager has already resolved this and passed it down
        in ``config['timezone']``; the shared resolver re-derives it from the
        core config or the host system if it hasn't.
        """
        return resolve_timezone(
            config=self.config,
            cache_manager=getattr(self, "cache_manager", None),
            log=self.logger,
        )

    def _should_log(self, warning_type: str, cooldown: int = 60) -> bool:
        """Check if we should log a warning based on cooldown period."""
        current_time = time.time()
        if current_time - self._last_warning_time > cooldown:
            self._last_warning_time = current_time
            return True
        return False

    def _fetch_team_rankings(self) -> Dict[str, int]:
        """Fetch team rankings/standings using the new architecture components."""
        current_time = time.time()

        # Check if we have cached rankings that are still valid
        if (
            self._team_rankings_cache
            and current_time - self._rankings_cache_timestamp
            < self._rankings_cache_duration
        ):
            return self._team_rankings_cache

        try:
            data = self.data_source.fetch_standings(self.sport, self.league)

            rankings = {}
            
            # Check if this is standings data (professional leagues like NBA, WNBA)
            # Standings structure: data['children'] -> child['standings']['entries'] -> entry['team']
            if "children" in data:
                # This is standings data (NBA, WNBA, etc.)
                # Extract teams from all conferences/divisions
                rank = 1
                for child in data.get("children", []):
                    standings = child.get("standings", {})
                    entries = standings.get("entries", [])
                    
                    # Sort entries by win percentage or record (standings are already ordered)
                    for entry in entries:
                        team_info = entry.get("team", {})
                        team_abbr = team_info.get("abbreviation", "")
                        
                        if team_abbr:
                            rankings[team_abbr] = rank
                            rank += 1
                
                self.logger.debug(f"Fetched standings for {len(rankings)} teams")
            
            # Check if this is rankings data (college sports)
            # Rankings structure: data['rankings'] -> ranking['ranks'] -> rank['team']
            elif "rankings" in data:
                rankings_data = data.get("rankings", [])
                
                if rankings_data:
                    # Use the first ranking (usually AP Top 25)
                    first_ranking = rankings_data[0]
                    teams = first_ranking.get("ranks", [])

                    for team_data in teams:
                        team_info = team_data.get("team", {})
                        team_abbr = team_info.get("abbreviation", "")
                        current_rank = team_data.get("current", 0)

                        if team_abbr and current_rank > 0:
                            rankings[team_abbr] = current_rank
                
                self.logger.debug(f"Fetched rankings for {len(rankings)} teams")

            # Cache the results
            self._team_rankings_cache = rankings
            self._rankings_cache_timestamp = current_time

            return rankings

        except Exception as e:
            self.logger.error(f"Error fetching team rankings/standings: {e}")
            return {}

    def _extract_game_details_common(
        self, game_event: Dict
    ) -> tuple[Dict | None, Dict | None, Dict | None, Dict | None, Dict | None]:
        if not game_event:
            return None, None, None, None, None
        try:
            # Safe access to competitions array
            competitions = game_event.get("competitions", [])
            if not competitions:
                self.logger.warning(f"No competitions data for game {game_event.get('id', 'unknown')}")
                return None, None, None, None, None
            competition = competitions[0]
            status = competition.get("status")
            if not status:
                self.logger.warning(f"No status data for game {game_event.get('id', 'unknown')}")
                return None, None, None, None, None
            competitors = competition.get("competitors", [])
            game_date_str = game_event["date"]
            situation = competition.get("situation")
            start_time_utc = None
            try:
                # Parse the datetime string
                if game_date_str.endswith('Z'):
                    game_date_str = game_date_str.replace('Z', '+00:00')
                dt = datetime.fromisoformat(game_date_str)
                # Ensure the datetime is UTC-aware (fromisoformat may create timezone-aware but not pytz.UTC)
                if dt.tzinfo is None:
                    # If naive, assume it's UTC
                    start_time_utc = dt.replace(tzinfo=pytz.UTC)
                else:
                    # Convert to pytz.UTC for consistency
                    start_time_utc = dt.astimezone(pytz.UTC)
            except ValueError:
                self.logger.warning(f"Could not parse game date: {game_date_str}")

            home_team = next(
                (c for c in competitors if c.get("homeAway") == "home"), None
            )
            away_team = next(
                (c for c in competitors if c.get("homeAway") == "away"), None
            )

            if not home_team or not away_team:
                self.logger.warning(
                    f"Could not find home or away team in event: {game_event.get('id')}"
                )
                return None, None, None, None, None

            try:
                home_abbr = home_team["team"]["abbreviation"]
            except KeyError:
                home_abbr = home_team["team"]["name"][:3]
            try:
                away_abbr = away_team["team"]["abbreviation"]
            except KeyError:
                away_abbr = away_team["team"]["name"][:3]

            # Check if this is a favorite team game BEFORE doing expensive logging
            is_favorite_game = self.favorite_teams and (
                home_abbr in self.favorite_teams or away_abbr in self.favorite_teams
            )

            # Only log debug info for favorite team games
            if is_favorite_game:
                self.logger.debug(
                    f"Processing favorite team game: {game_event.get('id')}"
                )
                self.logger.debug(
                    f"Found teams: {away_abbr}@{home_abbr}, Status: {status['type']['name']}, State: {status['type']['state']}"
                )

            game_time, game_date = "", ""
            if start_time_utc:
                local_time = start_time_utc.astimezone(self._get_timezone())
                game_time = local_time.strftime("%I:%M%p").lstrip("0")

                # Check date format from config
                use_short_date_format = self.config.get("display", {}).get(
                    "use_short_date_format", False
                )
                if use_short_date_format:
                    game_date = local_time.strftime("%-m/%-d")
                else:
                    # Note: display_manager.format_date_with_ordinal will be handled by plugin wrapper
                    game_date = local_time.strftime("%m/%d")  # Simplified for plugin

            home_record = (
                home_team.get("records", [{}])[0].get("summary", "")
                if home_team.get("records")
                else ""
            )
            away_record = (
                away_team.get("records", [{}])[0].get("summary", "")
                if away_team.get("records")
                else ""
            )

            # Don't show "0-0" records - set to blank instead
            if home_record in {"0-0", "0-0-0"}:
                home_record = ""
            if away_record in {"0-0", "0-0-0"}:
                away_record = ""

            # Extract scores, handling both dict and direct value formats
            def extract_score(team_data):
                """Extract score from team data, handling dict or direct value."""
                score = team_data.get("score")
                if score is None:
                    return "0"
                
                # If score is a dict (e.g., {"value": 75}), extract the value
                if isinstance(score, dict):
                    score_value = score.get("value", 0)
                    # Also check for other possible keys
                    if score_value == 0:
                        score_value = score.get("displayValue", score.get("score", 0))
                else:
                    score_value = score
                
                # Convert to integer to remove decimal points, then to string
                try:
                    # Handle string scores - check if it's a string representation of a dict first
                    if isinstance(score_value, str):
                        # Try to parse as float/int first
                        try:
                            score_value = float(score_value)
                        except ValueError:
                            # If it's not a number, try to extract number from string
                            numbers = re.findall(r'\d+', score_value)
                            if numbers:
                                score_value = float(numbers[0])
                            else:
                                self.logger.warning(f"Could not extract score from string: {score_value}")
                                return "0"
                    # Convert to int to remove decimals, then to string
                    return str(int(float(score_value)))
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Error extracting score: {e}, score type: {type(score)}, score value: {score}")
                    return "0"
            
            home_score = extract_score(home_team)
            away_score = extract_score(away_team)

            # Extract logo URLs from ESPN API structure (logos is an array)
            def extract_logo_url(team_data):
                """Extract logo URL from team data."""
                team_info = team_data.get("team", {})
                logos = team_info.get("logos", [])
                if logos and len(logos) > 0:
                    return logos[0].get("href")
                # Fallback to direct logo field if logos array doesn't exist
                return team_info.get("logo")
            
            home_logo_url = extract_logo_url(home_team)
            away_logo_url = extract_logo_url(away_team)
            
            details = {
                "id": game_event.get("id"),
                "game_time": game_time,
                "game_date": game_date,
                "start_time_utc": start_time_utc,
                "status_text": status["type"][
                    "shortDetail"
                ],  # e.g., "Final", "7:30 PM", "Q1 12:34"
                "is_live": status["type"]["state"] == "in",
                "is_final": status["type"]["state"] == "post",
                "is_upcoming": (
                    status["type"]["state"] == "pre"
                    or status["type"]["name"].lower()
                    in ["scheduled", "pre-game", "status_scheduled"]
                ),
                "is_halftime": status["type"]["state"] == "halftime"
                or status["type"]["name"] == "STATUS_HALFTIME",  # Added halftime check
                "is_period_break": status["type"]["name"]
                == "STATUS_END_PERIOD",  # Added Period Break check
                "home_abbr": home_abbr,
                "home_id": home_team["id"],
                "home_score": home_score,
                "home_logo_path": self.logo_dir
                / Path(f"{LogoDownloader.normalize_abbreviation(home_abbr)}.png"),
                "home_logo_url": home_logo_url,
                "home_record": home_record,
                "away_record": away_record,
                "away_abbr": away_abbr,
                "away_id": away_team["id"],
                "away_score": away_score,
                "away_logo_path": self.logo_dir
                / Path(f"{LogoDownloader.normalize_abbreviation(away_abbr)}.png"),
                "away_logo_url": away_logo_url,
                "is_within_window": True,  # Whether game is within display window
                # The resolved favorites for this league (dynamic groups such
                # as AP_TOP_25 already expanded). Carried on the game so the
                # scroll/Vegas renderer, which only ever sees the game dict and
                # the raw config, can color a final score by the result.
                "favorite_teams": list(self.favorite_teams or []),
            }
            return details, home_team, away_team, status, situation
        except Exception as e:
            # Log the problematic event structure if possible
            self.logger.error(
                f"Error extracting game details: {e} from event: {game_event.get('id')}",
                exc_info=True,
            )
            return None, None, None, None, None

    @abstractmethod
    def _extract_game_details(self, game_event: dict) -> dict | None:
        details, _, _, _, _ = self._extract_game_details_common(game_event)
        return details

    @abstractmethod
    def _fetch_data(self) -> Optional[Dict]:
        pass

    def _fetch_todays_games(self) -> Optional[Dict]:
        """Fetch current/today's games for live updates (not entire season)."""
        try:
            # For NCAA Basketball, use no dates parameter to get current games
            # This works around the date range limitation
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/scoreboard"
            
            # Check cache first (short TTL for live data)
            cache_key = f"{self.sport_key}_scoreboard_current"
            cached_data = self.cache_manager.get(cache_key, max_age=30)   # 30s cache for live data
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.debug(f"Using cached current scoreboard for {self.sport}/{self.league}")
                    return cached_data
            
            # ESPN API anchors its schedule calendar to Eastern US time.
            # Always query using the Eastern date + 1-day lookback to catch
            # late-night games still in progress from the previous Eastern day.
            tz = pytz.timezone("America/New_York")
            now = datetime.now(tz)
            yesterday = now - timedelta(days=1)
            formatted_date = now.strftime("%Y%m%d")
            formatted_date_yesterday = yesterday.strftime("%Y%m%d")
            params = {"dates": f"{formatted_date_yesterday}-{formatted_date}", "limit": 1000}
            self.logger.debug(f"Fetching today's games for {self.sport}/{self.league} on date {formatted_date}")
            
            response = self.session.get(
                url,
                params=params,
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            events = data.get("events", [])

            self.logger.info(
                f"Fetched {len(events)} current games for {self.sport} - {self.league}"
            )
            
            # Log status of each game for debugging
            if events:
                for event in events:
                    status = event.get("competitions", [{}])[0].get("status", {})
                    status_type = status.get("type", {})
                    state = status_type.get("state", "unknown")
                    name = status_type.get("name", "unknown")
                    self.logger.debug(
                        f"Event {event.get('id', 'unknown')}: state={state}, name={name}, "
                        f"shortDetail={status_type.get('shortDetail', 'N/A')}"
                    )
            
            # Cache the result (short TTL for live data)
            self.cache_manager.set(cache_key, data)
            return {"events": events}
        except requests.exceptions.RequestException as e:
            self.logger.error(
                f"API error fetching current games for {self.sport} - {self.league}: {e}"
            )
            return None

    def _get_weeks_data(self) -> Optional[Dict]:
        """
        Get partial data for immediate display while background fetch is in progress.
        This fetches current/recent games only for quick response.
        """
        try:
            # Fetch current week and next few days for immediate display
            now = datetime.now(pytz.utc)
            immediate_events = []

            # Same horizon as the full fetch this stands in for
            # (_fetch_soccer_api_data, -14d..+14d). It used to end a week
            # earlier, which is invisible in a league that plays daily and
            # severe in one that plays weekly: on 2026-08-14 the Premier
            # League's opening matchweek was 21-24 August, so a +7d horizon
            # returned exactly one fixture (COV @ ARS on the 21st) and hid the
            # other nine, including Man Utd on the 22nd. Reported as a
            # favourite team never appearing while other clubs did.
            start_date = now - timedelta(days=self.schedule_lookback_days)
            end_date = now + timedelta(days=self.schedule_lookahead_days)
            date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/scoreboard"
            response = self.session.get(
                url,
                params={"dates": date_str, "limit": 1000},
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            immediate_events = data.get("events", [])

            if immediate_events:
                self.logger.info(f"Fetched {len(immediate_events)} events {date_str}")
                return {"events": immediate_events}

        except requests.exceptions.RequestException as e:
            self.logger.warning(
                f"Error fetching this weeks games for {self.sport} - {self.league} - {date_str}: {e}"
            )
        return None

    def _custom_scorebug_layout(self, game: dict, draw_overlay: ImageDraw.ImageDraw):
        pass

    def _get_team_record_text(self, abbr: str, record: str) -> str:
        """Return the corner text for a team: ranking (if enabled/available) or record.

        When rankings are enabled they take precedence; unranked teams show
        nothing rather than falling back to a record, matching the behavior of
        the recent/upcoming layouts.
        """
        if self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            return f"#{rank}" if rank > 0 else ""
        if self.show_records:
            return record
        return ""

    def cleanup(self):
        """Clean up resources when plugin is unloaded."""
        # Close HTTP session
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception as e:
                self.logger.warning(f"Error closing session: {e}")

        # Clear caches
        if hasattr(self, '_logo_cache'):
            self._logo_cache.clear()

        self.logger.info(f"{self.__class__.__name__} cleanup completed")


class SportsUpcoming(SportsCore):
    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.upcoming_games = []  # Store all fetched upcoming games initially
        self.games_list = []  # Filtered list for display (favorite teams)
        self.current_game_index = 0
        self.last_update = 0
        self.update_interval = self.mode_config.get(
            "upcoming_update_interval", 3600
        )  # Check for recent games every hour
        self.last_log_time = 0
        self.log_interval = 300
        self.last_warning_time = 0
        self.warning_cooldown = 300
        self.last_game_switch = 0
        self.game_display_duration = 15  # Display each upcoming game for 15 seconds

    def _is_favorite_game(self, game: Dict) -> bool:
        """Does either side of this game belong to a favourite team?"""
        if not self.favorite_teams:
            return False
        return (
            game.get("home_abbr") in self.favorite_teams
            or game.get("away_abbr") in self.favorite_teams
        )

    def _other_games_window(self, others: List[Dict], limit: int) -> List[Dict]:
        """A rotating slice of the non-favourite games.

        The window advances by its own width, so consecutive windows are
        disjoint and the board walks the schedule rather than resampling the
        same front of it. It wraps, so a short list still cycles.

        Advancing is time-based, not per-update. update() runs every 30s; if
        the window moved with it the games list would change identity on every
        pass, reset the display index, and no card past the first would ever be
        reached.
        """
        if limit <= 0 or not others:
            return []
        if len(others) <= limit:
            return others[:limit]

        interval = self.other_rotation_interval_seconds
        if interval > 0:
            now = time.monotonic()
            if not self._other_window_rotated_at:
                self._other_window_rotated_at = now
            elapsed = now - self._other_window_rotated_at
            if elapsed >= interval:
                # Advance by however many intervals actually passed. The board
                # is not guaranteed to be running -- or this mode displayed --
                # for every one of them, and stepping once would let a plugin
                # that sat idle crawl a step at a time.
                steps = int(elapsed // interval)
                self._other_window_start += steps * limit
                self._other_window_rotated_at = now

        start = self._other_window_start % len(others)
        window = others[start:start + limit]
        if len(window) < limit:
            window += others[:limit - len(window)]
        return window

    def _favorites_first(
        self,
        processed_games: List[Dict],
        favorite_limit: int,
        other_limit: int,
        newest_first: bool = False,
    ) -> List[Dict]:
        """Favourite games first, then a bounded number of everything else.

        This is the middle setting the plugin was missing. `show_favorite_teams_only`
        used to be the whole story: on, and you saw nothing but your teams; off,
        and your teams were ignored entirely -- the selection just took the next
        N games league-wide, so a UGA fan with 946 upcoming college games in the
        window saw UGA about as often as chance allowed.

        Both counts are TOTALS here, not per-team. In favourites-only mode
        `upcoming_games_to_show` is a per-team budget, which is reasonable when
        the list is your own teams; applied to a dynamic group it is not. With
        AP_TOP_10 resolving to a dozen teams, three games each is 28 distinct
        cards before a single non-favourite is added. A total keeps the rotation
        the length the user asked for.
        """
        if newest_first:
            def key(g):
                return g.get("start_time_utc") or datetime.min.replace(tzinfo=timezone.utc)
            ordered = sorted(processed_games, key=key, reverse=True)
        else:
            def key(g):
                return g.get("start_time_utc") or datetime.max.replace(tzinfo=timezone.utc)
            ordered = sorted(processed_games, key=key)

        favorites, others = [], []
        for game in ordered:
            (favorites if self._is_favorite_game(game) else others).append(game)

        selected = favorites[:max(0, favorite_limit)]
        selected.extend(self._other_games_window(others, max(0, other_limit)))
        # Re-sort so the card order still reads as a schedule. Selection decides
        # WHICH games; it should not reorder them into favourites-then-others,
        # which would show next week's UGA game before tonight's.
        selected.sort(key=key, reverse=newest_first)
        return selected

    def _select_games_for_display(
        self, processed_games: List[Dict], favorite_teams: List[str]
    ) -> List[Dict]:
        """
        Single-pass game selection with proper deduplication and counting.

        When a game involves two favorite teams, it counts toward BOTH teams' limits.
        This prevents unexpected game counts from the multi-pass algorithm.
        """
        sorted_games = sorted(
            processed_games,
            key=lambda g: g.get("start_time_utc")
            or datetime.max.replace(tzinfo=timezone.utc),
        )

        if not favorite_teams:
            return sorted_games

        selected_games = []
        selected_ids = set()
        team_counts = {team: 0 for team in favorite_teams}

        for game in sorted_games:
            game_id = game.get("id")
            if game_id in selected_ids:
                continue

            home = game.get("home_abbr")
            away = game.get("away_abbr")

            home_fav = home in favorite_teams
            away_fav = away in favorite_teams

            if not home_fav and not away_fav:
                continue

            home_needs = home_fav and team_counts[home] < self.upcoming_games_to_show
            away_needs = away_fav and team_counts[away] < self.upcoming_games_to_show

            if home_needs or away_needs:
                selected_games.append(game)
                selected_ids.add(game_id)
                if home_fav:
                    team_counts[home] += 1
                if away_fav:
                    team_counts[away] += 1

                self.logger.debug(
                    f"Selected game {away}@{home}: team_counts={team_counts}"
                )

            if all(c >= self.upcoming_games_to_show for c in team_counts.values()):
                self.logger.debug("All favorite teams satisfied, stopping selection")
                break

        self.logger.info(
            f"Selected {len(selected_games)} games for {len(favorite_teams)} "
            f"favorite teams: {team_counts}"
        )
        return selected_games

    def update(self):
        """Update upcoming games data."""
        if not self.is_enabled:
            return
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        self.last_update = current_time

        # Fetch rankings if enabled
        if self.show_ranking:
            self._fetch_team_rankings()

        try:
            data = self._fetch_data()  # Uses shared cache
            if not data or "events" not in data:
                self.logger.warning(
                    "No events found in shared data."
                )  # Changed log prefix
                if not self.games_list:
                    self.current_game = None
                return

            events = data["events"]
            # self.logger.info(f"Processing {len(events)} events from shared data.") # Changed log prefix

            processed_games = []
            favorite_games_found = 0
            all_upcoming_games = 0  # Count all upcoming games regardless of favorites

            for event in events:
                game = self._extract_game_details(event)
                # Count all upcoming games for debugging
                if game and game["is_upcoming"]:
                    all_upcoming_games += 1

                # Filter criteria: must be upcoming ('pre' state)
                if game and game["is_upcoming"]:
                    # Only fetch odds for games that will be displayed
                    # If show_favorite_teams_only is True but no favorites configured, show all
                    if self.show_favorite_teams_only and self.favorite_teams:
                        if (
                            game["home_abbr"] not in self.favorite_teams
                            and game["away_abbr"] not in self.favorite_teams
                        ):
                            continue
                    processed_games.append(game)
                    # Count favorite team games for logging
                    if self.favorite_teams and (
                        game["home_abbr"] in self.favorite_teams
                        or game["away_abbr"] in self.favorite_teams
                    ):
                        favorite_games_found += 1

            # Enhanced logging for debugging
            self.logger.info(f"Found {all_upcoming_games} total upcoming games in data")
            self.logger.info(
                f"Found {len(processed_games)} upcoming games after filtering"
            )

            if processed_games:
                for game in processed_games[:3]:  # Show first 3
                    self.logger.info(
                        f"  {game['away_abbr']}@{game['home_abbr']} - {game['start_time_utc']}"
                    )

            if self.favorite_teams and all_upcoming_games > 0:
                self.logger.info(f"Favorite teams: {self.favorite_teams}")
                self.logger.info(
                    f"Found {favorite_games_found} favorite team upcoming games"
                )

            # Use single-pass algorithm for game selection
            # This properly handles games between two favorite teams (counts for both)
            if self.show_favorite_teams_only and self.favorite_teams:
                team_games = self._select_games_for_display(
                    processed_games, self.favorite_teams
                )
            elif self.favorite_teams:
                # Favourites set, but not exclusively: show them first, then
                # top up with other games so the board still has variety.
                team_games = self._favorites_first(
                    processed_games,
                    self.upcoming_games_to_show,
                    self.other_upcoming_games_to_show,
                )
                shown_favs = sum(1 for g in team_games if self._is_favorite_game(g))
                self.logger.info(
                    "Favorites %s: showing %d favorite and %d other upcoming games. "
                    "Set other_upcoming_games_to_show to 0 for favorites only.",
                    self.favorite_teams, shown_favs, len(team_games) - shown_favs
                )
            else:
                # No favourites at all: the next N upcoming games league-wide.
                team_games = sorted(
                    processed_games,
                    key=lambda g: g.get("start_time_utc")
                    or datetime.max.replace(tzinfo=timezone.utc),
                )[:self.upcoming_games_to_show]
                self.logger.info(
                    "No favorites configured: showing %d total upcoming games",
                    len(team_games)
                )

            # Odds are fetched here, for the games that survived selection,
            # rather than inside the loop that collects them. That loop runs
            # over every upcoming game in the schedule window, and the window
            # for a college league is enormous: a live rig logged 946 upcoming
            # games in one cycle and displayed 1 of them, having requested odds
            # for all 946. The comment there already claimed odds were fetched
            # "only for games that will be displayed", but the filter above it
            # applies only when show_favorite_teams_only is set AND favourites
            # are configured -- neither is the default -- so in the usual case
            # nothing narrowed it. Each request is a separate ESPN call on a Pi
            # that is also driving the panel.
            if self.show_odds:
                for game in team_games:
                    self._fetch_odds(game)

            # Log changes or periodically
            should_log = (
                current_time - self.last_log_time >= self.log_interval
                or len(team_games) != len(self.games_list)
                or any(
                    g1["id"] != g2.get("id")
                    for g1, g2 in zip(self.games_list, team_games)
                )
                or (not self.games_list and team_games)
            )

            # Check if the list of games to display has changed (protected by lock for thread safety)
            with self._games_lock:
                new_game_ids = {g["id"] for g in team_games}
                current_game_ids = {g["id"] for g in self.games_list}

                if new_game_ids != current_game_ids:
                    self.logger.info(
                        f"Found {len(team_games)} upcoming games within window for display."
                    )  # Changed log prefix
                    self.games_list = team_games
                    self._last_rendered_game_id = None  # Force redraw with new data
                    if (
                        not self.current_game
                        or not self.games_list
                        or self.current_game["id"] not in new_game_ids
                    ):
                        self.current_game_index = 0
                        self.current_game = self.games_list[0] if self.games_list else None
                        self.last_game_switch = current_time
                    else:
                        try:
                            self.current_game_index = next(
                                i
                                for i, g in enumerate(self.games_list)
                                if g["id"] == self.current_game["id"]
                            )
                            self.current_game = self.games_list[self.current_game_index]
                        except StopIteration:
                            self.current_game_index = 0
                            self.current_game = self.games_list[0]
                            self.last_game_switch = current_time

                elif self.games_list:
                    # Same IDs but payload may have changed — update data and
                    # force a redraw so corrected scores/times appear.
                    self.current_game = self.games_list[
                        self.current_game_index
                    ]
                    self._last_rendered_game_id = None

                if not self.games_list:
                    self.logger.info(
                        "No relevant upcoming games found to display."
                    )
                    self.current_game = None

            if should_log and not self.games_list:
                # Log favorite teams only if no games are found and logging is needed
                self.logger.debug(
                    f"Favorite teams: {self.favorite_teams}"
                )  # Changed log prefix
                self.logger.debug(
                    f"Total upcoming games before filtering: {len(processed_games)}"
                )  # Changed log prefix
                self.last_log_time = current_time
            elif should_log:
                self.last_log_time = current_time

        except Exception as e:
            self.logger.error(
                f"Error updating upcoming games: {e}", exc_info=True
            )  # Changed log prefix
            # self.current_game = None # Decide if clear on error

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the layout for an upcoming NCAA FB game."""  # Updated docstring
        try:
            # Clear the display first to ensure full coverage (like weather plugin does)
            if force_clear:
                self.display_manager.clear()
            
            # Use display_manager.matrix dimensions directly to ensure full display coverage
            display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_width
            display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_height
            
            main_img = Image.new(
                "RGBA", (display_width, display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (display_width, display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(overlay)

            home_logo = self._load_and_resize_logo(
                game["home_id"],
                game["home_abbr"],
                game["home_logo_path"],
                game.get("home_logo_url"),
            )
            away_logo = self._load_and_resize_logo(
                game["away_id"],
                game["away_abbr"],
                game["away_logo_path"],
                game.get("away_logo_url"),
            )

            if not home_logo or not away_logo:
                missing_logos = []
                if not home_logo:
                    missing_logos.append(f"home ({game.get('home_abbr', 'N/A')})")
                if not away_logo:
                    missing_logos.append(f"away ({game.get('away_abbr', 'N/A')})")
                
                self.logger.error(
                    f"Failed to load logos for game {game.get('id')}: {', '.join(missing_logos)}. "
                    f"Home logo path: {game.get('home_logo_path')}, "
                    f"Away logo path: {game.get('away_logo_path')}, "
                    f"Home logo URL: {game.get('home_logo_url')}, "
                    f"Away logo URL: {game.get('away_logo_url')}"
                )
                draw_final = ImageDraw.Draw(main_img.convert("RGB"))
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image = main_img.convert("RGB")
                self.display_manager.update_display()
                return

            center_y = display_height // 2

            # MLB-style logo positions with layout offsets
            home_x = display_width - home_logo.width + 2 + self._get_layout_offset('home_logo', 'x_offset')
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -2 + self._get_layout_offset('away_logo', 'x_offset')
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Draw Text Elements on Overlay
            game_date = game.get("game_date", "")
            game_time = game.get("game_time", "")

            # Note: Rankings are now handled in the records/rankings section below

            # League name at the top so the competition is identifiable (falls back
            # to "Next Game" when the manager didn't set one). The small status font
            # keeps long names like "Scottish Premiership" on a single line.
            status_font = self.fonts["status"]
            if display_width > 128:
                status_font = self.fonts["time"]
            status_text = getattr(self, "league_name", "") or "Next Game"
            status_width = draw_overlay.textlength(status_text, font=status_font)
            status_x = (display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
            status_y = 1 + self._get_layout_offset('status_text', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, status_text, (status_x, status_y), status_font
            )

            # Date text (centered, below "Next Game") with layout offsets
            date_width = draw_overlay.textlength(game_date, font=self.fonts["time"])
            date_x = (display_width - date_width) // 2 + self._get_layout_offset('date', 'x_offset')
            # Adjust Y position to stack date and time nicely
            date_y = center_y - max(7, self._time_font_size() - 1) + self._get_layout_offset('date', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, game_date, (date_x, date_y), self.fonts["time"]
            )

            # Time text (centered, below Date) with layout offsets
            time_width = draw_overlay.textlength(game_time, font=self.fonts["time"])
            time_x = (display_width - time_width) // 2 + self._get_layout_offset('time', 'x_offset')
            time_y = date_y + max(9, self._time_font_size() + 1) + self._get_layout_offset('time', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, game_time, (time_x, time_y), self.fonts["time"]
            )

            # Draw odds if available
            if "odds" in game and game["odds"]:
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], display_width, display_height
                )

            # Draw records or rankings if enabled
            if self.show_records or self.show_ranking:
                record_font = self.fonts.get("record") or self.fonts.get("status") or ImageFont.load_default()

                # Get team abbreviations
                away_abbr = game.get("away_abbr", "")
                home_abbr = game.get("home_abbr", "")

                record_bbox = draw_overlay.textbbox((0, 0), "0-0", font=record_font)
                record_height = record_bbox[3] - record_bbox[1]
                record_y = self.display_height - record_height + self._get_layout_offset('records', 'y_offset')
                self.logger.debug(
                    f"Record positioning: height={record_height}, record_y={record_y}, display_height={self.display_height}"
                )

                # Display away team info
                if away_abbr:
                    if self.show_ranking and self.show_records:
                        # When both rankings and records are enabled, rankings replace records completely
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            # Show nothing for unranked teams when rankings are prioritized
                            away_text = ""
                    elif self.show_ranking:
                        # Show ranking only if available
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            away_text = ""
                    elif self.show_records:
                        # Show record only when rankings are disabled
                        away_text = game.get("away_record", "")
                    else:
                        away_text = ""

                    if away_text:
                        away_record_x = 0 + self._get_layout_offset('records', 'away_x_offset')
                        self.logger.debug(
                            f"Drawing away ranking '{away_text}' at ({away_record_x}, {record_y}) with font size {record_font.size if hasattr(record_font, 'size') else 'unknown'}"
                        )
                        self._draw_text_with_outline(
                            draw_overlay,
                            away_text,
                            (away_record_x, record_y),
                            record_font,
                        )

                # Display home team info
                if home_abbr:
                    if self.show_ranking and self.show_records:
                        # When both rankings and records are enabled, rankings replace records completely
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            # Show nothing for unranked teams when rankings are prioritized
                            home_text = ""
                    elif self.show_ranking:
                        # Show ranking only if available
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            home_text = ""
                    elif self.show_records:
                        # Show record only when rankings are disabled
                        home_text = game.get("home_record", "")
                    else:
                        home_text = ""

                    if home_text:
                        home_record_bbox = draw_overlay.textbbox(
                            (0, 0), home_text, font=record_font
                        )
                        home_record_width = home_record_bbox[2] - home_record_bbox[0]
                        home_record_x = self.display_width - home_record_width + self._get_layout_offset('records', 'home_x_offset')
                        self.logger.debug(
                            f"Drawing home ranking '{home_text}' at ({home_record_x}, {record_y}) with font size {record_font.size if hasattr(record_font, 'size') else 'unknown'}"
                        )
                        self._draw_text_with_outline(
                            draw_overlay,
                            home_text,
                            (home_record_x, record_y),
                            record_font,
                        )

            # Composite and display
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()  # Update display here

        except Exception as e:
            self.logger.error(
                f"Error displaying upcoming game: {e}", exc_info=True
            )  # Changed log prefix

    def display(self, force_clear=False) -> bool:
        """Display upcoming games, handling switching."""
        if not self.is_enabled:
            return False

        if not self.games_list:
            # Clear the display so old content doesn't persist
            if force_clear:
                self.display_manager.clear()
                self.display_manager.update_display()
            if self.current_game:
                self.current_game = None  # Clear state if list empty
            current_time = time.time()
            # Log warning periodically if no games found
            if current_time - self.last_warning_time > self.warning_cooldown:
                self.logger.info(
                    "No upcoming games found for favorite teams to display."
                )  # Changed log prefix
                self.last_warning_time = current_time
            return False  # Skip display update

        try:
            current_time = time.time()

            # Check if it's time to switch games (protected by lock for thread safety)
            with self._games_lock:
                if (
                    len(self.games_list) > 1
                    and current_time - self.last_game_switch >= self.game_display_duration
                ):
                    self.current_game_index = (self.current_game_index + 1) % len(
                        self.games_list
                    )
                    self.current_game = self.games_list[self.current_game_index]
                    self.last_game_switch = current_time
                    force_clear = True  # Force redraw on switch

                    # Log team switching with sport prefix
                    if self.current_game:
                        away_abbr = self.current_game.get("away_abbr", "UNK")
                        home_abbr = self.current_game.get("home_abbr", "UNK")
                        sport_prefix = (
                            self.sport_key.upper()
                            if hasattr(self, "sport_key")
                            else "SPORT"
                        )
                        self.logger.info(
                            f"[{sport_prefix} Upcoming] Showing {away_abbr} vs {home_abbr}"
                        )
                    else:
                        self.logger.debug(
                            f"Switched to game index {self.current_game_index}"
                        )

            if self.current_game:
                # Skip redundant redraws when nothing changed
                game_id = self.current_game.get("id")
                if not force_clear and game_id == self._last_rendered_game_id:
                    return True  # Already showing this game, no redraw needed
                self._draw_scorebug_layout(self.current_game, force_clear)
                self._last_rendered_game_id = game_id

        except Exception as e:
            self.logger.error(
                f"Error in display loop: {e}", exc_info=True
            )
            return False

        return True


class SportsRecent(SportsCore):

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.recent_games = []  # Store all fetched recent games initially
        self.games_list = []  # Filtered list for display (favorite teams)
        self.current_game_index = 0
        self.last_update = 0
        self.update_interval = self.mode_config.get(
            "recent_update_interval", 3600
        )  # Check for recent games every hour
        self.last_game_switch = 0
        self.game_display_duration = self.mode_config.get("recent_game_duration", 15)
        self._zero_clock_timestamps: Dict[str, float] = {}  # Track games at 0:00

    def _get_zero_clock_duration(self, game_id: str) -> float:
        """Track how long a game has been at 0:00 clock."""
        current_time = time.time()
        if game_id not in self._zero_clock_timestamps:
            self._zero_clock_timestamps[game_id] = current_time
            return 0.0
        return current_time - self._zero_clock_timestamps[game_id]

    def _clear_zero_clock_tracking(self, game_id: str) -> None:
        """Clear tracking when game clock moves away from 0:00 or game ends."""
        if game_id in self._zero_clock_timestamps:
            del self._zero_clock_timestamps[game_id]

    def _select_recent_games_for_display(
        self, processed_games: List[Dict], favorite_teams: List[str]
    ) -> List[Dict]:
        """
        Single-pass game selection for recent games with proper deduplication.

        When a game involves two favorite teams, it counts toward BOTH teams' limits.
        Games are sorted by most recent first.
        """
        sorted_games = sorted(
            processed_games,
            key=lambda g: g.get("start_time_utc")
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        if not favorite_teams:
            return sorted_games

        selected_games = []
        selected_ids = set()
        team_counts = {team: 0 for team in favorite_teams}

        for game in sorted_games:
            game_id = game.get("id")
            if game_id in selected_ids:
                continue

            home = game.get("home_abbr")
            away = game.get("away_abbr")

            home_fav = home in favorite_teams
            away_fav = away in favorite_teams

            if not home_fav and not away_fav:
                continue

            home_needs = home_fav and team_counts[home] < self.recent_games_to_show
            away_needs = away_fav and team_counts[away] < self.recent_games_to_show

            if home_needs or away_needs:
                selected_games.append(game)
                selected_ids.add(game_id)
                if home_fav:
                    team_counts[home] += 1
                if away_fav:
                    team_counts[away] += 1

                self.logger.debug(
                    f"Selected recent game {away}@{home}: team_counts={team_counts}"
                )

            if all(c >= self.recent_games_to_show for c in team_counts.values()):
                self.logger.debug("All favorite teams satisfied, stopping selection")
                break

        self.logger.info(
            f"Selected {len(selected_games)} recent games for {len(favorite_teams)} "
            f"favorite teams: {team_counts}"
        )
        return selected_games

    def update(self):
        """Update recent games data."""
        if not self.is_enabled:
            return
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        self.last_update = current_time  # Update time even if fetch fails

        # Fetch rankings if enabled
        if self.show_ranking:
            self._fetch_team_rankings()

        try:
            data = self._fetch_data()  # Uses shared cache
            if not data or "events" not in data:
                self.logger.warning(
                    "No events found in shared data."
                )  # Changed log prefix
                if not self.games_list:
                    self.current_game = None  # Clear display if no games were showing
                return

            events = data["events"]
            self.logger.info(
                f"Processing {len(events)} events from shared data."
            )  # Changed log prefix

            # How far back the Recent screen looks. This used to be a fixed 21
            # days, which quietly capped schedule_lookback_days: the schema
            # allows up to 60 and tells the user to "raise it if finished games
            # disappear sooner than you want", but anything above 21 only
            # enlarged the ESPN payload and changed nothing on screen.
            now = datetime.now(timezone.utc)
            # getattr, because managers are also built without __init__ (the
            # plugin tests do exactly that) and a missing attribute here would
            # raise into the surrounding except and silently skip the filter.
            lookback_days = getattr(
                self, "schedule_lookback_days", _DEFAULT_LOOKBACK_DAYS)
            recent_cutoff = now - timedelta(days=lookback_days)
            self.logger.info(
                f"Current time: {now}, Recent cutoff: {recent_cutoff} "
                f"({lookback_days} days ago)"
            )

            # Process games and filter for final games, date range & favorite teams
            processed_games = []
            for event in events:
                game = self._extract_game_details(event)
                if not game:
                    continue

                # Check if game appears finished even if not marked as "post" yet
                game_id = game.get("id")
                appears_finished = False
                if not game.get("is_final", False):
                    period_text = game.get("period_text", "").lower()
                    if "final" in period_text:
                        appears_finished = True
                        self._clear_zero_clock_tracking(game_id)
                else:
                    self._clear_zero_clock_tracking(game_id)

                # Filter criteria: must be final OR appear finished, AND within recent date range
                is_eligible = game.get("is_final", False) or appears_finished
                if is_eligible:
                    game_time = game.get("start_time_utc")
                    if game_time and game_time >= recent_cutoff:
                        # Excluded teams are hidden from final/recent scores too
                        # (spoiler protection), regardless of every other filter.
                        if (
                            game.get("home_abbr") in self.exclude_teams
                            or game.get("away_abbr") in self.exclude_teams
                        ):
                            continue
                        processed_games.append(game)
            # Use single-pass algorithm for game selection
            # This properly handles games between two favorite teams (counts for both)
            if self.show_favorite_teams_only and self.favorite_teams:
                team_games = self._select_recent_games_for_display(
                    processed_games, self.favorite_teams
                )
                self.logger.info(
                    f"Filtering to favorites: {len(team_games)} games for teams {self.favorite_teams}"
                )
                # Debug: Show which games are selected for display
                for i, game in enumerate(team_games):
                    self.logger.info(
                        f"Game {i+1} for display: {game['away_abbr']} @ {game['home_abbr']} - {game.get('start_time_utc')} - Score: {game['away_score']}-{game['home_score']}"
                    )
            elif self.favorite_teams:
                # Favourites set, but not exclusively: theirs first, then fill.
                team_games = self._favorites_first(
                    processed_games,
                    self.recent_games_to_show,
                    self.other_recent_games_to_show,
                    newest_first=True,
                )
                shown_favs = sum(1 for g in team_games if self._is_favorite_game(g))
                self.logger.info(
                    "Favorites %s: showing %d favorite and %d other recent games. "
                    "Set other_recent_games_to_show to 0 for favorites only.",
                    self.favorite_teams, shown_favs, len(team_games) - shown_favs
                )
            else:
                # No favourites at all: the most recent N league-wide.
                team_games = sorted(
                    processed_games,
                    key=lambda g: g.get("start_time_utc")
                    or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )[:self.recent_games_to_show]
                self.logger.info(
                    "No favorites configured: showing %d total recent games",
                    len(team_games)
                )

            # Check if the list of games to display has changed (protected by lock for thread safety)
            with self._games_lock:
                new_game_ids = {g["id"] for g in team_games}
                current_game_ids = {g["id"] for g in self.games_list}

                if new_game_ids != current_game_ids:
                    self.logger.info(
                        f"Found {len(team_games)} final games within window for display."
                    )  # Changed log prefix
                    self.games_list = team_games
                    self._last_rendered_game_id = None  # Force redraw with new data
                    # Reset index if list changed or current game removed
                    if (
                        not self.current_game
                        or not self.games_list
                        or self.current_game["id"] not in new_game_ids
                    ):
                        self.current_game_index = 0
                        self.current_game = self.games_list[0] if self.games_list else None
                        self.last_game_switch = current_time  # Reset switch timer
                    else:
                        # Try to maintain position if possible
                        try:
                            self.current_game_index = next(
                                i
                                for i, g in enumerate(self.games_list)
                                if g["id"] == self.current_game["id"]
                            )
                            self.current_game = self.games_list[
                                self.current_game_index
                            ]  # Update data just in case
                        except StopIteration:
                            self.current_game_index = 0
                            self.current_game = self.games_list[0]
                            self.last_game_switch = current_time

                elif self.games_list:
                    # Same IDs but payload may have changed — update data and
                    # force a redraw so corrected scores/times appear.
                    self.current_game = self.games_list[self.current_game_index]
                    self._last_rendered_game_id = None

                if not self.games_list:
                    self.logger.info(
                        "No relevant recent games found to display."
                    )
                    self.current_game = None

        except Exception as e:
            self.logger.error(
                f"Error updating recent games: {e}", exc_info=True
            )  # Changed log prefix
            # Don't clear current game on error, keep showing last known state
            # self.current_game = None # Decide if we want to clear display on error

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the layout for a recently completed NCAA FB game."""  # Updated docstring
        try:
            # Clear the display first to ensure full coverage (like weather plugin does)
            if force_clear:
                self.display_manager.clear()
            
            # Use display_manager.matrix dimensions directly to ensure full display coverage
            display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_width
            display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_height
            
            main_img = Image.new(
                "RGBA", (display_width, display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (display_width, display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(overlay)

            home_logo = self._load_and_resize_logo(
                game["home_id"],
                game["home_abbr"],
                game["home_logo_path"],
                game.get("home_logo_url"),
            )
            away_logo = self._load_and_resize_logo(
                game["away_id"],
                game["away_abbr"],
                game["away_logo_path"],
                game.get("away_logo_url"),
            )

            if not home_logo or not away_logo:
                self.logger.error(
                    f"Failed to load logos for game: {game.get('id')}"
                )  # Changed log prefix
                # Draw placeholder text if logos fail (similar to live)
                draw_final = ImageDraw.Draw(main_img.convert("RGB"))
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image = main_img.convert("RGB")
                self.display_manager.update_display()
                return

            center_y = display_height // 2

            # MLB-style logo positioning (closer to edges) with layout offsets
            home_x = display_width - home_logo.width + 2 + self._get_layout_offset('home_logo', 'x_offset')
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -2 + self._get_layout_offset('away_logo', 'x_offset')
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Draw Text Elements on Overlay
            # Note: Rankings are now handled in the records/rankings section below

            # Final Scores (Centered, same position as live) with layout offsets
            # Convert scores to integers to remove decimal points
            def format_score(score):
                """Format score as integer string, removing decimals."""
                try:
                    # Handle None or empty values
                    if score is None:
                        return "0"

                    # If it's already a string, try to parse it
                    if isinstance(score, str):
                        # Remove any whitespace
                        score = score.strip()
                        # If empty, return 0
                        if not score:
                            return "0"
                        # Try to extract number from string (handles cases where score might be a string representation of something else)
                        try:
                            return str(int(float(score)))
                        except ValueError:
                            # Try to extract first number from string
                            import re
                            numbers = re.findall(r'\d+', score)
                            if numbers:
                                return str(int(numbers[0]))
                            self.logger.warning(f"Could not parse score string: {score}")
                            return "0"

                    # Handle dict (shouldn't happen if extraction worked, but be safe)
                    if isinstance(score, dict):
                        score_value = score.get("value", score.get("displayValue", 0))
                        return str(int(float(score_value)))

                    # Handle numeric types
                    return str(int(float(score)))
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Error formatting score: {e}, score type: {type(score)}, score value: {score}")
                    return "0"

            home_score = format_score(game.get("home_score", "0"))
            away_score = format_score(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (display_width - score_width) // 2 + self._get_layout_offset('score', 'x_offset')
            # Centered vertically (matches the baseball recent layout) so the game
            # date fits on the bottom line without colliding with the score.
            score_y = (display_height // 2) - max(3, self._score_font_size() // 2 - 1) + self._get_layout_offset('score', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay,
                score_text,
                (score_x, score_y),
                self.fonts["score"],
                fill=self._recent_score_color(game, (255, 255, 255)),
            )

            # "Final" text (Top center) with layout offsets
            status_text = game.get(
                "period_text", "Final"
            )  # Use formatted period text (e.g., "Final/OT") or default "Final"
            status_width = draw_overlay.textlength(status_text, font=self.fonts["time"])
            status_x = (display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
            status_y = 1 + self._get_layout_offset('status_text', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, status_text, (status_x, status_y), self.fonts["time"]
            )

            # Game date (bottom center, one line above the edge) — when the game was
            # played. Matches the baseball recent layout.
            game_date = game.get("game_date", "")
            if game_date:
                date_width = draw_overlay.textlength(game_date, font=self.fonts["time"])
                date_x = (display_width - date_width) // 2 + self._get_layout_offset('date', 'x_offset')
                date_y = display_height - max(7, self._time_font_size() - 1) + self._get_layout_offset('date', 'y_offset')
                self._draw_text_with_outline(
                    draw_overlay, game_date, (date_x, date_y), self.fonts["time"]
                )

            # Draw odds if available
            if "odds" in game and game["odds"]:
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], display_width, display_height
                )

            # Draw records or rankings if enabled
            if self.show_records or self.show_ranking:
                record_font = self.fonts.get("record") or self.fonts.get("status") or ImageFont.load_default()

                # Get team abbreviations
                away_abbr = game.get("away_abbr", "")
                home_abbr = game.get("home_abbr", "")

                record_bbox = draw_overlay.textbbox((0, 0), "0-0", font=record_font)
                record_height = record_bbox[3] - record_bbox[1]
                record_y = self.display_height - record_height + self._get_layout_offset('records', 'y_offset')
                self.logger.debug(
                    f"Record positioning: height={record_height}, record_y={record_y}, display_height={self.display_height}"
                )

                # Display away team info
                if away_abbr:
                    if self.show_ranking and self.show_records:
                        # When both rankings and records are enabled, rankings replace records completely
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            # Show nothing for unranked teams when rankings are prioritized
                            away_text = ""
                    elif self.show_ranking:
                        # Show ranking only if available
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            away_text = ""
                    elif self.show_records:
                        # Show record only when rankings are disabled
                        away_text = game.get("away_record", "")
                    else:
                        away_text = ""

                    if away_text:
                        away_record_x = 0 + self._get_layout_offset('records', 'away_x_offset')
                        self.logger.debug(
                            f"Drawing away ranking '{away_text}' at ({away_record_x}, {record_y}) with font size {record_font.size if hasattr(record_font, 'size') else 'unknown'}"
                        )
                        self._draw_text_with_outline(
                            draw_overlay,
                            away_text,
                            (away_record_x, record_y),
                            record_font,
                        )

                # Display home team info
                if home_abbr:
                    if self.show_ranking and self.show_records:
                        # When both rankings and records are enabled, rankings replace records completely
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            # Show nothing for unranked teams when rankings are prioritized
                            home_text = ""
                    elif self.show_ranking:
                        # Show ranking only if available
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            home_text = ""
                    elif self.show_records:
                        # Show record only when rankings are disabled
                        home_text = game.get("home_record", "")
                    else:
                        home_text = ""

                    if home_text:
                        home_record_bbox = draw_overlay.textbbox(
                            (0, 0), home_text, font=record_font
                        )
                        home_record_width = home_record_bbox[2] - home_record_bbox[0]
                        home_record_x = display_width - home_record_width + self._get_layout_offset('records', 'home_x_offset')
                        self.logger.debug(
                            f"Drawing home ranking '{home_text}' at ({home_record_x}, {record_y}) with font size {record_font.size if hasattr(record_font, 'size') else 'unknown'}"
                        )
                        self._draw_text_with_outline(
                            draw_overlay,
                            home_text,
                            (home_record_x, record_y),
                            record_font,
                        )

            self._custom_scorebug_layout(game, draw_overlay)
            # Composite and display
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")
            # Assign directly like weather plugin does for full display coverage
            self.display_manager.image = main_img
            self.display_manager.update_display()  # Update display here

        except Exception as e:
            self.logger.error(
                f"Error displaying recent game: {e}", exc_info=True
            )  # Changed log prefix

    def display(self, force_clear=False) -> bool:
        """Display recent games, handling switching."""
        if not self.is_enabled or not self.games_list:
            # If disabled or no games, clear the display so old content doesn't persist
            if force_clear or not self.games_list:
                self.display_manager.clear()
                self.display_manager.update_display()
            if not self.games_list and self.current_game:
                self.current_game = None  # Clear internal state if list becomes empty
            return False

        try:
            current_time = time.time()

            # Check if it's time to switch games (protected by lock for thread safety)
            with self._games_lock:
                if (
                    len(self.games_list) > 1
                    and current_time - self.last_game_switch >= self.game_display_duration
                ):
                    self.current_game_index = (self.current_game_index + 1) % len(
                        self.games_list
                    )
                    self.current_game = self.games_list[self.current_game_index]
                    self.last_game_switch = current_time
                    force_clear = True  # Force redraw on switch

                    # Log team switching with sport prefix
                    if self.current_game:
                        away_abbr = self.current_game.get("away_abbr", "UNK")
                        home_abbr = self.current_game.get("home_abbr", "UNK")
                        sport_prefix = (
                            self.sport_key.upper()
                            if hasattr(self, "sport_key")
                            else "SPORT"
                        )
                        self.logger.info(
                            f"[{sport_prefix} Recent] Showing {away_abbr} vs {home_abbr}"
                        )
                    else:
                        self.logger.debug(
                            f"Switched to game index {self.current_game_index}"
                        )

            if self.current_game:
                # Skip redundant redraws when nothing changed
                game_id = self.current_game.get("id")
                if not force_clear and game_id == self._last_rendered_game_id:
                    return True  # Already showing this game, no redraw needed
                self._draw_scorebug_layout(self.current_game, force_clear)
                self._last_rendered_game_id = game_id

        except Exception as e:
            self.logger.error(
                f"Error in display loop: {e}", exc_info=True
            )
            return False

        return True


class SportsLive(SportsCore):

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.update_interval = self.mode_config.get("live_update_interval", 15)
        # Read from the config root, where the schema declares them and the web
        # UI writes them -- not from mode_config, which is the per-league block
        # ({sport}_scoreboard) and never carries these keys. Looking them up
        # there meant the saved value was invisible and every user silently kept
        # the default. mode_config is still consulted as a fallback so a
        # hand-placed per-league value keeps working.
        self.no_data_interval = _clamp_seconds(
            self.config.get("no_data_interval_seconds",
                            self.mode_config.get("no_data_interval_seconds")), 300)
        self.live_idle_max_interval = _clamp_seconds(
            self.config.get("live_idle_max_interval_seconds",
                            self.mode_config.get("live_idle_max_interval_seconds")),
            _DEFAULT_LIVE_IDLE_MAX_SECONDS)
        self._empty_live_streak = 0
        # Log the configured interval for debugging
        self.logger.info(
            f"SportsLive initialized: live_update_interval={self.update_interval}s, "
            f"no_data_interval={self.no_data_interval}s, "
            f"mode_config keys={list(self.mode_config.keys())}"
        )
        self.last_update = 0
        self.live_games = []
        self.current_game_index = 0
        self.last_game_switch = 0
        self.game_display_duration = self.mode_config.get("live_game_duration", 20)
        # Optional shorter dwell for live games that involve NO favorite team.
        # 0 (default) means "use game_display_duration for every live game" -
        # i.e. today's behavior. Only bites when favorites are configured and
        # show_favorite_teams_only is off (so non-favorite games are on screen).
        try:
            self.non_favorite_live_game_duration = int(
                self.mode_config.get("non_favorite_live_game_duration", 0) or 0
            )
        except (TypeError, ValueError):
            self.non_favorite_live_game_duration = 0
        self.last_display_update = 0
        self.last_log_time = 0
        self.log_interval = 300
        self.last_count_log_time = 0  # Track when we last logged count data
        self.count_log_interval = 5  # Only log count data every 5 seconds
        # Initialize test_mode - defaults to False (live mode)
        self.test_mode = self.mode_config.get("test_mode", False)
        # Track game update timestamps for stale data detection
        self.game_update_timestamps = {}
        self.stale_game_timeout = self.mode_config.get("stale_game_timeout", 300)  # 5 minutes default

        # Goal/win celebration takeover
        self.celebration_enabled = self.mode_config.get("celebration_enabled", True)
        self.celebration_duration = self.mode_config.get("celebration_duration", 8)
        self.celebrate_opponent_goals = self.mode_config.get(
            "celebrate_opponent_goals", False
        )
        # Per-game score baselines for goal detection: {game_id: {"away": int, "home": int}}
        self._score_baselines: Dict[str, Dict[str, int]] = {}
        # Active celebration dict (a snapshot, so a win survives the game leaving
        # live_games) or None. See _start_celebration for the shape.
        self.active_celebration: Optional[Dict[str, Any]] = None

    def _get_live_status_text(self, game: Dict) -> str:
        """Build the top status string for a live game (period + clock)."""
        if game.get("is_halftime"):
            return "HALF"
        if game.get("is_period_break"):
            return game.get("status_text", "BREAK")
        # period_text already combines period + clock (e.g. "2H 75'") in the
        # soccer managers; fall back to the raw clock, then a generic "LIVE".
        period_text = game.get("period_text", "")
        if period_text:
            return period_text
        clock = game.get("clock", "")
        if clock:
            return clock
        return "LIVE"

    # ------------------------------------------------------------------
    # Goal / win celebration
    # ------------------------------------------------------------------
    @staticmethod
    def _score_to_int(score) -> Optional[int]:
        """Coerce an ESPN score value (str / int / dict) to an int, or None."""
        try:
            if score is None:
                return None
            if isinstance(score, str):
                s = score.strip()
                if not s:
                    return None
                try:
                    return int(float(s))
                except ValueError:
                    import re
                    numbers = re.findall(r"\d+", s)
                    return int(numbers[0]) if numbers else None
            if isinstance(score, dict):
                return int(float(score.get("value", score.get("displayValue", 0))))
            return int(float(score))
        except (ValueError, TypeError):
            return None

    def _is_favorite(self, abbr: Optional[str]) -> bool:
        return bool(self.favorite_teams) and abbr in self.favorite_teams

    def _should_celebrate_goal_for(self, abbr: Optional[str]) -> bool:
        """Whether a goal by ``abbr`` should trigger a celebration."""
        if self._is_favorite(abbr):
            return True
        if not self.favorite_teams:
            # No favorites configured: the user opted to show this game, so
            # celebrate any goal in it.
            return True
        # Favorites exist but this team isn't one -> it's the opponent.
        return self.celebrate_opponent_goals

    def has_active_celebration(self) -> bool:
        """True while a celebration is within its display window."""
        c = self.active_celebration
        return bool(c) and (time.time() - c["started_at"] < self.celebration_duration)

    def _start_celebration(
        self,
        game: Dict,
        kind: str,
        scored_side: str,
        team_abbr: str,
        away_score: int,
        home_score: int,
    ) -> None:
        """Arm a goal or win celebration. ``scored_side`` is the side whose
        score digit gets highlighted ('away' or 'home')."""
        if kind == "win":
            phrase = f"{team_abbr} WINS!"
        else:
            phrase = secrets.choice(("GOOOOAAALLL!", f"{team_abbr} SCORES!"))

        self.active_celebration = {
            "kind": kind,
            "game": dict(game),  # snapshot: survives the game leaving live_games
            "scored_side": scored_side,
            "team_abbr": team_abbr,
            "away_score": away_score,
            "home_score": home_score,
            "started_at": time.time(),
            "phrase": phrase,
        }
        # Pin focus to the involved game so the post-celebration scorebug
        # resumes on it.
        self.current_game = dict(game)
        self.logger.info(
            f"Celebration ({kind}) armed: {phrase} "
            f"[{game.get('away_abbr')} {away_score}-{home_score} {game.get('home_abbr')}]"
        )

    def _check_for_goal(self, game: Dict) -> None:
        """Compare a live game's score against the stored baseline and arm a
        goal celebration when a celebratable team's score increments."""
        if not self.celebration_enabled:
            return
        game_id = game.get("id")
        if not game_id:
            return
        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        if away is None or home is None:
            return

        baseline = self._score_baselines.get(game_id)
        # Always refresh the baseline; a first sighting must never celebrate
        # (a match already in progress at boot would false-fire otherwise),
        # and a decrement (VAR / disallowed goal) just re-bases silently.
        self._score_baselines[game_id] = {"away": away, "home": home}
        if baseline is None:
            return

        away_scored = away > baseline["away"]
        home_scored = home > baseline["home"]
        if not (away_scored or home_scored):
            return

        scored_side = None
        if away_scored and self._should_celebrate_goal_for(game.get("away_abbr")):
            scored_side = "away"
        if scored_side is None and home_scored and self._should_celebrate_goal_for(
            game.get("home_abbr")
        ):
            scored_side = "home"
        if scored_side is None:
            return

        self._start_celebration(
            game,
            "goal",
            scored_side=scored_side,
            team_abbr=game.get(f"{scored_side}_abbr", ""),
            away_score=away,
            home_score=home,
        )

    def _check_for_win(self, game: Dict) -> None:
        """When a game we were tracking live goes final, arm a win celebration
        if a favorite team won. Only fires once per game."""
        if not self.celebration_enabled:
            return
        game_id = game.get("id")
        if not game_id:
            return
        # Only celebrate wins for games we actually watched go live; a game seen
        # for the first time already-final (Pi started after full time) has no
        # baseline and must not fire.
        if game_id not in self._score_baselines:
            return
        # Consume the baseline so this can only fire once.
        self._score_baselines.pop(game_id, None)

        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        if away is None or home is None:
            return

        if away > home:
            winner_side, winner_abbr = "away", game.get("away_abbr")
        elif home > away:
            winner_side, winner_abbr = "home", game.get("home_abbr")
        else:
            return  # draw -> no win celebration

        # Wins are gated strictly on favorites (every game ends, so the
        # "no favorites -> celebrate all" goal fallback would be too noisy).
        if not self._is_favorite(winner_abbr):
            return

        self._start_celebration(
            game,
            "win",
            scored_side=winner_side,
            team_abbr=winner_abbr,
            away_score=away,
            home_score=home,
        )

    def _fit_font(self, draw, text: str, max_width: int, fonts: list):
        """Return the first font whose rendered ``text`` fits ``max_width``,
        falling back to the last (smallest) font."""
        for font in fonts:
            if draw.textlength(text, font=font) <= max_width - 2:
                return font
        return fonts[-1]

    def _draw_celebration_layout(self, celebration: Dict, force_clear: bool = False) -> None:
        """Render the full-screen goal/win takeover."""
        if force_clear:
            self.display_manager.clear()

        display_width = (
            self.display_manager.matrix.width
            if hasattr(self.display_manager, "matrix") and self.display_manager.matrix
            else self.display_width
        )
        display_height = (
            self.display_manager.matrix.height
            if hasattr(self.display_manager, "matrix") and self.display_manager.matrix
            else self.display_height
        )

        elapsed = time.time() - celebration["started_at"]
        game = celebration["game"]

        # Background: a brief color flash for the first ~1.2s, then black.
        bg = (0, 0, 0, 255)
        if elapsed < 1.2 and int(elapsed / 0.2) % 2 == 0:
            bg = (12, 12, 48, 255)
        main_img = Image.new("RGBA", (display_width, display_height), bg)
        overlay = Image.new("RGBA", (display_width, display_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Logos at the edges (best-effort: a logo failure must not blank the
        # celebration).
        try:
            center_y = display_height // 2
            home_logo = self._load_and_resize_logo(
                game.get("home_id"), game.get("home_abbr"),
                game.get("home_logo_path"), game.get("home_logo_url"),
            )
            away_logo = self._load_and_resize_logo(
                game.get("away_id"), game.get("away_abbr"),
                game.get("away_logo_path"), game.get("away_logo_url"),
            )
            if home_logo:
                main_img.paste(
                    home_logo,
                    (display_width - home_logo.width + 2, center_y - home_logo.height // 2),
                    home_logo,
                )
            if away_logo:
                main_img.paste(
                    away_logo, (-2, center_y - away_logo.height // 2), away_logo
                )
        except Exception as e:
            self.logger.debug(f"Celebration logo load failed: {e}")

        # Phrase across the top, shrunk to fit the panel width.
        phrase = celebration["phrase"]
        phrase_font = self._fit_font(
            draw, phrase, display_width, [self.fonts["time"], self.fonts["status"]]
        )
        phrase_width = draw.textlength(phrase, font=phrase_font)
        self._draw_text_with_outline(
            draw, phrase, ((display_width - phrase_width) // 2, 1), phrase_font
        )

        # Score centered low, with the scoring/winning side's digit pulsing in a
        # highlight color so the change reads at a glance.
        away_text = str(celebration["away_score"])
        home_text = str(celebration["home_score"])
        score_font = self.fonts["score"]
        segments = [
            (away_text, celebration["scored_side"] == "away"),
            ("-", False),
            (home_text, celebration["scored_side"] == "home"),
        ]
        total_width = sum(draw.textlength(seg, font=score_font) for seg, _ in segments)
        highlight = (255, 255, 0) if int(elapsed * 4) % 2 == 0 else (255, 170, 0)
        x = (display_width - total_width) // 2
        y = display_height - 14
        for seg, is_highlight in segments:
            color = highlight if is_highlight else (255, 255, 255)
            self._draw_text_with_outline(draw, seg, (int(x), y), score_font, fill=color)
            x += draw.textlength(seg, font=score_font)

        main_img = Image.alpha_composite(main_img, overlay).convert("RGB")
        self.display_manager.image = main_img
        self.display_manager.update_display()

    def display(self, force_clear: bool = False) -> bool:
        """Render an active celebration as a full-screen takeover; otherwise
        defer to the normal live scorebug."""
        if not self.is_enabled:
            return False
        celebration = self.active_celebration
        if celebration:
            if time.time() - celebration["started_at"] < self.celebration_duration:
                try:
                    self._draw_celebration_layout(celebration, force_clear)
                    return True
                except Exception as e:
                    self.logger.error(
                        f"Error drawing celebration: {e}", exc_info=True
                    )
            else:
                self.active_celebration = None
                # Reset the dwell so the scorebug resumes on the scoring/winning
                # game for a full duration before rotation can move on.
                self.last_game_switch = time.time()
        # After the celebration branch: a celebration owns the
        # screen, and rotating out of it would undo the dwell reset
        # that gives the scoring game its full turn.
        self._advance_live_game_if_due()
        return super().display(force_clear)

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the switch-mode scorebug for a live soccer game.

        Mirrors the recent-game layout (logos at the edges, score centered low)
        but shows the live period/clock at the top instead of "Final".
        """
        try:
            if force_clear:
                self.display_manager.clear()

            display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_width
            display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_height

            main_img = Image.new("RGBA", (display_width, display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (display_width, display_height), (0, 0, 0, 0))
            draw_overlay = ImageDraw.Draw(overlay)

            home_logo = self._load_and_resize_logo(
                game["home_id"],
                game["home_abbr"],
                game["home_logo_path"],
                game.get("home_logo_url"),
            )
            away_logo = self._load_and_resize_logo(
                game["away_id"],
                game["away_abbr"],
                game["away_logo_path"],
                game.get("away_logo_url"),
            )

            if not home_logo or not away_logo:
                self.logger.error(f"Failed to load logos for live game: {game.get('id')}")
                draw_final = ImageDraw.Draw(main_img.convert("RGB"))
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image = main_img.convert("RGB")
                self.display_manager.update_display()
                return

            center_y = display_height // 2

            # Logos at the edges (matches recent/upcoming layouts)
            home_x = display_width - home_logo.width + 2 + self._get_layout_offset('home_logo', 'x_offset')
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -2 + self._get_layout_offset('away_logo', 'x_offset')
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Score (centered, low — same position as recent games)
            def format_score(score):
                try:
                    if score is None:
                        return "0"
                    if isinstance(score, str):
                        score = score.strip()
                        if not score:
                            return "0"
                        try:
                            return str(int(float(score)))
                        except ValueError:
                            import re
                            numbers = re.findall(r'\d+', score)
                            return str(int(numbers[0])) if numbers else "0"
                    if isinstance(score, dict):
                        score_value = score.get("value", score.get("displayValue", 0))
                        return str(int(float(score_value)))
                    return str(int(float(score)))
                except (ValueError, TypeError):
                    return "0"

            home_score = format_score(game.get("home_score", "0"))
            away_score = format_score(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (display_width - score_width) // 2 + self._get_layout_offset('score', 'x_offset')
            score_y = display_height - (6 + self._score_font_size()) + self._get_layout_offset('score', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts["score"]
            )

            # Live status (period + clock) at the top center
            status_text = self._get_live_status_text(game)
            status_width = draw_overlay.textlength(status_text, font=self.fonts["time"])
            status_x = (display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
            status_y = 1 + self._get_layout_offset('status_text', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, status_text, (status_x, status_y), self.fonts["time"]
            )

            # Draw odds if available
            if "odds" in game and game["odds"]:
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], display_width, display_height
                )

            # Draw records or rankings if enabled
            if self.show_records or self.show_ranking:
                record_font = self.fonts.get("record") or self.fonts.get("status") or ImageFont.load_default()

                away_abbr = game.get("away_abbr", "")
                home_abbr = game.get("home_abbr", "")

                record_bbox = draw_overlay.textbbox((0, 0), "0-0", font=record_font)
                record_height = record_bbox[3] - record_bbox[1]
                record_y = self.display_height - record_height + self._get_layout_offset('records', 'y_offset')

                if away_abbr:
                    away_text = self._get_team_record_text(away_abbr, game.get("away_record", ""))
                    if away_text:
                        away_record_x = 0 + self._get_layout_offset('records', 'away_x_offset')
                        self._draw_text_with_outline(
                            draw_overlay, away_text, (away_record_x, record_y), record_font
                        )

                if home_abbr:
                    home_text = self._get_team_record_text(home_abbr, game.get("home_record", ""))
                    if home_text:
                        home_record_bbox = draw_overlay.textbbox((0, 0), home_text, font=record_font)
                        home_record_width = home_record_bbox[2] - home_record_bbox[0]
                        home_record_x = display_width - home_record_width + self._get_layout_offset('records', 'home_x_offset')
                        self._draw_text_with_outline(
                            draw_overlay, home_text, (home_record_x, record_y), record_font
                        )

            self._custom_scorebug_layout(game, draw_overlay)
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")
            self.display_manager.image = main_img
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying live game: {e}", exc_info=True)

    def _is_game_really_over(self, game: Dict) -> bool:
        """Check if a game appears to be over even if API says it's live.

        Soccer-specific: clock counts UP (e.g., 75', 90+3'), so we check for
        'final' in period_text. The 0:00 clock check used in countdown-clock
        sports doesn't apply here.
        """
        game_str = f"{game.get('away_abbr')}@{game.get('home_abbr')}"

        # Check if period_text indicates final
        period_text = game.get("period_text", "").lower()
        if "final" in period_text:
            self.logger.debug(
                f"_is_game_really_over({game_str}): "
                f"returning True - 'final' in period_text='{period_text}'"
            )
            return True

        self.logger.debug(
            f"_is_game_really_over({game_str}): returning False "
            f"(period_text='{period_text}', period={game.get('period', 0)})"
        )
        return False

    def _detect_stale_games(self, games: List[Dict]) -> None:
        """Remove games that appear stale or haven't updated."""
        current_time = time.time()

        for game in games[:]:  # Copy list to iterate safely
            game_id = game.get("id")
            if not game_id:
                continue

            # Check if game data is stale
            timestamps = self.game_update_timestamps.get(game_id, {})
            last_seen = timestamps.get("last_seen", 0)

            if last_seen > 0 and current_time - last_seen > self.stale_game_timeout:
                self.logger.warning(
                    f"Removing stale game {game.get('away_abbr')}@{game.get('home_abbr')} "
                    f"(last seen {int(current_time - last_seen)}s ago)"
                )
                games.remove(game)
                if game_id in self.game_update_timestamps:
                    del self.game_update_timestamps[game_id]
                continue

            # Also check if game appears to be over
            if self._is_game_really_over(game):
                self.logger.debug(
                    f"Removing game that appears over: {game.get('away_abbr')}@{game.get('home_abbr')} "
                    f"(clock={game.get('clock')}, period={game.get('period')}, period_text={game.get('period_text')})"
                )
                games.remove(game)
                if game_id in self.game_update_timestamps:
                    del self.game_update_timestamps[game_id]

    def _idle_live_interval(self) -> int:
        """How long to wait before looking for live games again, when there are none.

        Escalates the longer nothing turns up, and any live game resets it, so
        an in-season gap between games costs at most one escalated wait while
        an out-of-season league stops polling on a live cadence entirely.

        Capped rather than unbounded: the cost of backing off is how late the
        first game after a quiet spell is noticed, and past the cap the saving
        stops being worth that.
        """
        streak = getattr(self, "_empty_live_streak", 0)
        base = self.no_data_interval
        ceiling = getattr(self, "live_idle_max_interval",
                          _DEFAULT_LIVE_IDLE_MAX_SECONDS)
        # The ceiling bounds the un-escalated interval too. The two settings are
        # independent integers with no cross-validation, so base > ceiling is a
        # reachable config -- and returning base unclamped there made the wait
        # *shrink* as the streak grew (3600s at streak 0, 900s at streak 24),
        # the opposite of what the setting named "maximum" promises.
        if streak >= _IDLE_LONG_STREAK:
            return min(int(base * _IDLE_LONG_FACTOR), ceiling)
        if streak >= _IDLE_SHORT_STREAK:
            return min(int(base * _IDLE_SHORT_FACTOR), ceiling)
        return min(base, ceiling)

    def _note_live_fetch(self, found_live: bool) -> None:
        """Record whether a look for live games found any."""
        if found_live:
            if getattr(self, "_empty_live_streak", 0):
                self.logger.info(
                    "Live games found after %d empty check(s); back to the "
                    "live update interval", self._empty_live_streak)
            self._empty_live_streak = 0
        else:
            self._empty_live_streak = getattr(self, "_empty_live_streak", 0) + 1

    def update(self):
        """Update live game data and handle game switching."""
        if not self.is_enabled:
            return

        # Define current_time and interval before the problematic line (originally line 455)
        # Ensure 'import time' is present at the top of the file.
        current_time = time.time()

        # Define interval using a pattern similar to NFLLiveManager's update method.
        # Uses getattr for robustness, assuming attributes for live_games,
        # no_data_interval, and update_interval are available on self.
        _live_games_attr = self.live_games
        _no_data_interval_attr = (
            self.no_data_interval
        )  # Default similar to NFLLiveManager
        _update_interval_attr = (
            self.update_interval
        )  # Default similar to NFLLiveManager

        # For live managers, always use the configured live_update_interval when checking for updates.
        # Only use no_data_interval if we've recently checked and confirmed there are no live games.
        # This ensures we check for live games frequently even if the list is temporarily empty.
        # Only use no_data_interval if we have no live games AND we've checked recently (within last 5 minutes)
        # Whether the last look found anything, tracked explicitly rather than
        # inferred from how long ago it was. The old form asked "did we check
        # within the last 300s?" and only then used no_data_interval -- but
        # once 300s had elapsed the answer became no, the interval dropped
        # back to live_update_interval, and it fetched. no_data_interval could
        # therefore never delay anything past 300s whatever it was set to.
        # Measured on a live rig: an out-of-season NHL polled every ~5.5
        # minutes around the clock, returning nothing every time.
        if _live_games_attr:
            interval = _update_interval_attr
        else:
            interval = self._idle_live_interval()

        # Original line from traceback (line 455), now with variables defined:
        if current_time - self.last_update >= interval:
            # What the previous look found, recorded before this one
            # replaces it. The streak is what drives the back-off, and
            # any live game resets it.
            self._note_live_fetch(bool(_live_games_attr))
            self.last_update = current_time

            # Fetch rankings if enabled
            if self.show_ranking:
                self._fetch_team_rankings()

            # Fetch live game data
            data = self._fetch_data()
            new_live_games = []
            if not data:
                self.logger.debug(f"No data returned from _fetch_data() for {self.sport_key}")
            elif "events" not in data:
                self.logger.debug(f"Data returned but no 'events' key for {self.sport_key}: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            elif data and "events" in data:
                total_events = len(data["events"])
                self.logger.debug(f"Fetched {total_events} total events from API for {self.sport_key}")
                
                live_or_halftime_count = 0
                filtered_out_count = 0
                
                for game in data["events"]:
                    details = self._extract_game_details(game)
                    if details:
                        # Log game status for debugging
                        status_state = game.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("state", "unknown")
                        self.logger.debug(
                            f"Game {details.get('away_abbr', '?')}@{details.get('home_abbr', '?')}: "
                            f"state={status_state}, is_live={details.get('is_live')}, "
                            f"is_halftime={details.get('is_halftime')}, is_final={details.get('is_final')}"
                        )

                        # Filter out final games and games that appear to be over.
                        # A game we were tracking live going final may earn a win
                        # celebration before it drops out of the live list.
                        if details.get("is_final", False):
                            self._check_for_win(details)
                            continue

                        if self._is_game_really_over(details):
                            self._check_for_win(details)
                            self.logger.info(
                                f"Skipping game that appears final: {details.get('away_abbr')}@{details.get('home_abbr')} "
                                f"(clock={details.get('clock')}, period={details.get('period')}, period_text={details.get('period_text')})"
                            )
                            continue

                        if details["is_live"] or details["is_halftime"]:
                            live_or_halftime_count += 1
                            
                            # Filtering logic (see _classify_live_game for the
                            # full precedence order: exclude > show_all_live >
                            # favorites-only membership; matches SportsUpcoming).
                            should_include = self._classify_live_game(
                                details["home_abbr"], details["away_abbr"]
                            )

                            if not should_include:
                                filtered_out_count += 1
                                self.logger.debug(
                                    f"Filtered out live game {details.get('away_abbr')}@{details.get('home_abbr')}: "
                                    f"show_all_live={self.show_all_live}, "
                                    f"show_favorite_teams_only={self.show_favorite_teams_only}, "
                                    f"favorite_teams={self.favorite_teams}"
                                )
                            
                            if should_include:
                                # Track game timestamps for stale detection
                                game_id = details.get("id")
                                if game_id:
                                    current_clock = details.get("clock", "")
                                    current_score = f"{details.get('away_score', '0')}-{details.get('home_score', '0')}"

                                    if game_id not in self.game_update_timestamps:
                                        self.game_update_timestamps[game_id] = {}

                                    timestamps = self.game_update_timestamps[game_id]
                                    timestamps["last_seen"] = time.time()

                                    if timestamps.get("last_clock") != current_clock:
                                        timestamps["last_clock"] = current_clock
                                        timestamps["clock_changed_at"] = time.time()
                                    if timestamps.get("last_score") != current_score:
                                        timestamps["last_score"] = current_score
                                        timestamps["score_changed_at"] = time.time()

                                # Detect goals (per-side score increments) and arm
                                # a celebration when a celebratable team scores.
                                self._check_for_goal(details)

                                if self.show_odds:
                                    self._fetch_odds(details)
                                new_live_games.append(details)

                # Detect and remove stale games from persisted list
                # (new_live_games has fresh last_seen, so stale check must
                # run against the previous self.live_games)
                with self._games_lock:
                    self._detect_stale_games(self.live_games)

                self.logger.info(
                    f"Live game filtering: {total_events} total events, "
                    f"{live_or_halftime_count} live/halftime, "
                    f"{filtered_out_count} filtered out, "
                    f"{len(new_live_games)} included | "
                    f"show_all_live={self.show_all_live}, "
                    f"show_favorite_teams_only={self.show_favorite_teams_only}, "
                    f"favorite_teams={self.favorite_teams if self.favorite_teams else '[] (showing all)'}"
                )
                # Log changes or periodically
                current_time_for_log = (
                    time.time()
                )  # Use a consistent time for logging comparison
                should_log = (
                    current_time_for_log - self.last_log_time >= self.log_interval
                    or len(new_live_games) != len(self.live_games)
                    or any(
                        g1["id"] != g2.get("id")
                        for g1, g2 in zip(self.live_games, new_live_games)
                    )  # Check if game IDs changed
                    or (
                        not self.live_games and new_live_games
                    )  # Log if games appeared
                )

                if should_log:
                    if new_live_games:
                        filter_text = (
                            "favorite teams"
                            if self.show_favorite_teams_only or self.show_all_live
                            else "all teams"
                        )
                        self.logger.info(
                            f"Found {len(new_live_games)} live/halftime games for {filter_text}."
                        )
                        for (
                            game_info
                        ) in new_live_games:  # Renamed game to game_info
                            self.logger.info(
                                f"  - {game_info['away_abbr']}@{game_info['home_abbr']} ({game_info.get('status_text', 'N/A')})"
                            )
                    else:
                        filter_text = (
                            "favorite teams"
                            if self.show_favorite_teams_only or self.show_all_live
                            else "criteria"
                        )
                        self.logger.info(
                            f"No live/halftime games found for {filter_text}."
                        )
                    self.last_log_time = current_time_for_log

                # Update game list and current game (protected by lock for thread safety)
                with self._games_lock:
                    if new_live_games:
                        # Check if the games themselves changed, not just scores/time
                        new_game_ids = {g["id"] for g in new_live_games}
                        current_game_ids = {g["id"] for g in self.live_games}

                        if new_game_ids != current_game_ids:
                            self.live_games = sorted(
                                new_live_games,
                                key=lambda g: g.get("start_time_utc")
                                or datetime.now(timezone.utc),
                            )  # Sort by start time
                            # Reset index if current game is gone or list is new.
                            # Pick via weighted round-robin so a live favorite is
                            # queued first (see _swrr_advance).
                            if (
                                not self.current_game
                                or self.current_game["id"] not in new_game_ids
                            ):
                                self.current_game = (
                                    self._swrr_advance(self.live_games)
                                    if self.live_games else None
                                )
                                self.current_game_index = next(
                                    (i for i, g in enumerate(self.live_games)
                                     if self.current_game and g["id"] == self.current_game["id"]),
                                    0,
                                )
                                self.last_game_switch = current_time
                            else:
                                # Find current game's new index if it still exists
                                try:
                                    self.current_game_index = next(
                                        i
                                        for i, g in enumerate(self.live_games)
                                        if g["id"] == self.current_game["id"]
                                    )
                                    self.current_game = self.live_games[
                                        self.current_game_index
                                    ]  # Update current_game with fresh data
                                except (
                                    StopIteration
                                ):  # Should not happen if check above passed, but safety first
                                    self.current_game_index = 0
                                    self.current_game = self.live_games[0]
                                    self.last_game_switch = current_time

                        else:
                            # Just update the data for the existing games
                            temp_game_dict = {g["id"]: g for g in new_live_games}
                            self.live_games = [
                                temp_game_dict.get(g["id"], g) for g in self.live_games
                            ]  # Update in place
                            if self.current_game:
                                self.current_game = temp_game_dict.get(
                                    self.current_game["id"], self.current_game
                                )

                        # Display update handled by main loop based on interval

                    else:
                        # No live games found
                        if self.live_games:  # Were there games before?
                            self.logger.info(
                                "Live games previously showing have ended or are no longer live."
                            )  # Changed log prefix
                        self.live_games = []
                        self.current_game = None
                        self.current_game_index = 0

                    # Prune game_update_timestamps for games no longer tracked
                    active_ids = {g["id"] for g in self.live_games}
                    self.game_update_timestamps = {
                        gid: ts for gid, ts in self.game_update_timestamps.items()
                        if gid in active_ids
                    }
                    # Prune goal baselines the same way. A game that vanishes
                    # without going final is re-based on reappearance (treated as
                    # a first sighting), which avoids a false goal.
                    self._score_baselines = {
                        gid: v for gid, v in self._score_baselines.items()
                        if gid in active_ids
                    }

            else:
                # Error fetching data or no events
                if self.live_games:  # Were there games before?
                    self.logger.warning(
                        "Could not fetch update; keeping existing live game data for now."
                    )  # Changed log prefix
                else:
                    self.logger.warning(
                        "Could not fetch data and no existing live games."
                    )  # Changed log prefix
                    self.current_game = None  # Clear current game if fetch fails and no games were active

            # Handle game switching (protected by lock for thread safety).
            # Hold the current game while a celebration is pending so the view
            # doesn't rotate away mid-celebration — or in the window between the
            # duration expiring and display() clearing it (display() resets the
            # dwell timer when it clears, so the scoring game resumes first).
            # Rotation is driven from display() -- see
            # _advance_live_game_if_due().
    def _advance_live_game_if_due(self) -> None:
        """Rotate to the next live game once the current one has had its time.

        Driven from display() rather than update(). How long a game stays on
        screen is a display concern, and update() runs on live_update_interval
        -- 30s by default -- so gating the dwell there quantised every
        configured duration to the refresh rate. Measured on a live rig with
        four NFL games, live_game_duration=45 and
        non_favorite_live_game_duration=10 both produced a flat 30s rotation;
        only changing live_update_interval changed anything.

        The body below is this sport's own rotation, moved verbatim: the
        sports differ in how they choose the next game and that part worked.

        Cheap enough for the render loop -- a clock comparison, with work only
        on the frame that switches.
        """
        if getattr(self, "test_mode", False):
            return
        # Zero means no game has been shown yet. Without this the first frame
        # sees an elapsed time of `now - 0` and rotates immediately: nearly
        # invisible at one check per 30s, a flicker at one per frame.
        if getattr(self, "last_game_switch", 0) <= 0:
            return
        current_time = time.time()
        with self._games_lock:
            if (
                len(self.live_games) > 1
                and self.active_celebration is None
                and (current_time - self.last_game_switch)
                >= self._effective_live_duration(self.current_game)
            ):
                # Weighted pick (see _swrr_advance) instead of plain +1 index -
                # gives a live favorite's game extra turns per
                # favorite_live_boost while everything else still rotates
                # fairly (boost==1 reproduces the old flat round robin).
                self.current_game = self._swrr_advance(self.live_games)
                self.current_game_index = next(
                    (i for i, g in enumerate(self.live_games)
                     if self.current_game and g["id"] == self.current_game["id"]),
                    0,
                )
                self.last_game_switch = current_time
                self.logger.info(
                    f"Switched live view to: {self.current_game['away_abbr']}@{self.current_game['home_abbr']}"
                )  # Changed log prefix

                    # Force display update via flag or direct call if needed, but usually let main loop handle
