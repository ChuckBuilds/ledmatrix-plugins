import colorsys
import logging
import math
import os
import random
import re
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import pytz
import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS

# Import simplified dependencies for plugin use
from dynamic_team_resolver import DynamicTeamResolver
# The core's downloader, not a bundled copy. The copy this plugin used to ship
# wrote any HTTP 200 body to the .png path (an HTML error page included) and
# saved placeholders without the core's refresh marker, so one failed download
# left a team a grey box forever: _logo_needs_refresh below cannot recognise
# an unmarked placeholder. __init__ already required src.logo_downloader for
# the logo directory, so this adds no new dependency on the core.
from src.logo_downloader import LogoDownloader, download_missing_logo
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
from hockey_espn_dates import ESPN_MAX_LIMIT, fetch_espn_scoreboard
from hockey_timezone import resolve_timezone
from src.common.sports_shared import (
    SportsCoreSharedMixin, SportsLiveSharedMixin, SportsRecentSharedMixin)


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



# ----------------------------------------------------------------------
# Colour helpers for the score/win celebration
#
# Module level rather than methods: they are pure, which is what makes the
# palette testable without standing up a live manager, and they are shared by
# the takeover's backdrop, confetti and text.
# ----------------------------------------------------------------------

#: The crest is sampled at this resolution. Big enough that a secondary
#: colour survives (a helmet stripe, a trim), small enough that the whole
#: sample is ~1600 pixels of pure-Python work, once per team.
_PALETTE_SAMPLE_PX = 40
#: Above this, a colour carries team identity; below it, it is a grey.
_PALETTE_VIVID_SATURATION = 0.22
#: Ignore pixels this dark -- crest outlines, drop shadows, anti-aliasing.
_PALETTE_MIN_CHANNEL = 24
#: How far apart two bins must be to count as a second, different colour.
_PALETTE_DISTINCT_DISTANCE = 90.0
#: Never bleed a lifted colour below this saturation; past it a hue stops
#: being the team's colour and starts being a pastel.
_PALETTE_MIN_SATURATION = 0.42
#: Lift a headline colour until it is at least this luminous. Chosen so
#: midnight navy reaches a blue that reads at 6px on a panel without
#: becoming a different colour.
_PALETTE_HEADLINE_LUMINANCE = 112.0
#: A crest colour this luminous already reads on a panel, so it is preferred
#: over a darker one that would have to be lifted to get there. Lifting is a
#: compromise -- Green Bay's dark green only reaches legibility as a teal --
#: and most teams whose primary is dark carry a bright second colour that is
#: just as much theirs. This is what picks the Packers' gold over that teal.
_PALETTE_LEGIBLE_LUMINANCE = 90.0
#: ...but only from a colour the crest actually means. The pixels where a
#: bright edge is anti-aliased into a dark fill are luminous too, and there is
#: always a band of them: Kansas City's white-on-red outline leaves a pink at
#: luminance 90 that would otherwise be preferred over the red itself. A blend
#: is a mix, so it is markedly less saturated than either colour it sits
#: between -- that pink is 0.48 where the red is 0.96 and the Packers' gold,
#: which this must keep, is 0.89.
_PALETTE_LEGIBLE_SATURATION = 0.65
#: And it has to be a band of the crest, not a speck of one.
_PALETTE_LEGIBLE_AREA = 0.02
#: Cap the backdrop's luminance so the headline stays legible over it,
#: and the scenery's so it stays behind the headline. Both are luminance and
#: not HSV value on purpose: a silver crest -- the Raiders, or the grey
#: placeholder a failed logo download leaves behind -- has a value of ~0.95,
#: and capping that at 0.34 still yields a light grey card that white text
#: then vanishes into. Scaling the channels down is also hue-exact, which is
#: what lets this be the plain arithmetic that lifting a colour cannot be.
_PALETTE_BACKDROP_LUMINANCE = 34.0
_PALETTE_SCENERY_LUMINANCE = 70.0


def _rgb_luminance(color) -> float:
    """Rec. 709 relative luminance, 0-255."""
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _rgb_saturation(color) -> float:
    high = max(color)
    return (high - min(color)) / high if high else 0.0


def _color_distance(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _mix_color(a, b, t):
    """Blend ``a`` towards ``b``; t=0 is all a, t=1 is all b."""
    t = min(max(t, 0.0), 1.0)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _scale_color(color, factor):
    """Scale a colour's brightness, clamped to the panel's range."""
    return tuple(min(255, max(0, int(round(c * factor)))) for c in color)


def _lift_color(color, min_luminance=_PALETTE_HEADLINE_LUMINANCE, cap_saturation=0.92):
    """Raise a colour's brightness until it reads on a panel, keeping its hue.

    Scaling the channels directly is what the obvious version of this does,
    and it shifts hue badly on exactly the colours that need lifting: it turns
    Baltimore's navy-purple into magenta. Working in HSV and raising only the
    value leaves the hue where the team put it.
    """
    if _rgb_luminance(color) >= min_luminance:
        return tuple(int(c) for c in color)
    hue, saturation, value = colorsys.rgb_to_hsv(*[c / 255.0 for c in color])
    if saturation < 0.12:
        # A grey or a silver has no hue to preserve; just make it bright.
        lifted = colorsys.hsv_to_rgb(hue, saturation, max(value, 0.85))
        return tuple(int(round(c * 255)) for c in lifted)
    saturation = min(saturation, cap_saturation)

    def _rgb(s, v):
        return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(hue, s, v))

    out = _rgb(saturation, value)
    while value < 1.0 and _rgb_luminance(out) < min_luminance:
        value = min(1.0, value + 0.05)
        out = _rgb(saturation, value)
    # Blue carries almost no luminance -- pure blue sits at 18 of 255 -- so a
    # navy or a deep purple runs out of value long before it is legible.
    # Bleeding saturation out of it is the only way up, and it keeps the hue
    # (Baltimore stays purple, just a lighter one) where giving up would
    # leave the headline unreadable. Floored so it never washes out to white.
    while saturation > _PALETTE_MIN_SATURATION and _rgb_luminance(out) < min_luminance:
        saturation = max(_PALETTE_MIN_SATURATION, saturation - 0.05)
        out = _rgb(saturation, value)
    return out


def _cap_luminance(color, max_luminance):
    """Darken a colour until it is no brighter than ``max_luminance``.

    A straight channel scale, which is exactly hue-preserving on the way down
    -- unlike lifting, where clamping at 255 is what bends the hue.
    """
    luminance = _rgb_luminance(color)
    if luminance <= max_luminance or luminance <= 0:
        return tuple(int(c) for c in color)
    return _scale_color(color, max_luminance / luminance)


def _dim_rgba(image, factor):
    """Scale an RGBA image's colour channels, leaving its alpha alone.

    ImageEnhance.Brightness would scale the alpha band too, which fades the
    crest out instead of dimming it and leaves its anti-aliased edge looking
    chewed against the backdrop.
    """
    red, green, blue, alpha = image.split()
    lut = [min(255, int(i * factor)) for i in range(256)]
    return Image.merge(
        "RGBA", (red.point(lut), green.point(lut), blue.point(lut), alpha)
    )


def _palette_buckets(logo):
    """Bucket a crest's opaque pixels into coarse colour bins.

    Returns ``(vivid, neutral)``; each maps a 3-bit-per-channel key to
    ``[r_sum, g_sum, b_sum, count]``. Neutral holds the greys, silvers and
    whites that carry no identity on their own but are all a monochrome crest
    -- the Raiders' silver on black -- has to offer.
    """
    sample = logo.convert("RGBA")
    sample.thumbnail((_PALETTE_SAMPLE_PX, _PALETTE_SAMPLE_PX), Image.Resampling.BOX)
    vivid: Dict[Tuple[int, int, int], List[int]] = {}
    neutral: Dict[Tuple[int, int, int], List[int]] = {}
    # tobytes() rather than getdata(): same pixels, no per-pixel Python
    # object, and getdata() is deprecated from Pillow 14.
    raw = sample.tobytes()
    for i in range(0, len(raw) - 3, 4):
        red, green, blue, alpha = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        if alpha < 160:
            continue
        high, low = max(red, green, blue), min(red, green, blue)
        if high < _PALETTE_MIN_CHANNEL:
            continue
        target = vivid if (high - low) / high >= _PALETTE_VIVID_SATURATION else neutral
        acc = target.setdefault((red >> 5, green >> 5, blue >> 5), [0, 0, 0, 0])
        acc[0] += red
        acc[1] += green
        acc[2] += blue
        acc[3] += 1
    return vivid, neutral


def _bucket_mean(acc):
    count = acc[3]
    return (acc[0] // count, acc[1] // count, acc[2] // count)


def _bucket_headline_score(acc):
    """How well a colour bin would serve as 6px of text on a panel.

    Area alone picks the biggest block of colour, which on a lot of crests is
    a dark navy fill -- correct as a backdrop, invisible as text. Weighting
    area by saturation and by luminance picks the colour the team is loud in:
    Chicago's orange over its navy, Baltimore's gold over its purple.
    """
    color = _bucket_mean(acc)
    return (
        acc[3]
        * (0.30 + 0.70 * _rgb_saturation(color))
        * (0.20 + 0.80 * min(1.0, _rgb_luminance(color) / 120.0))
    )


def _logo_palette(logo):
    """Pick a celebration palette out of a team crest, or None.

    Two rankings, because a crest's largest colour and its most legible one
    are usually not the same and the takeover needs both:

    * ``deep`` -- the largest vivid area, darkened into the background wash.
      This is what the team reads as at a glance: Chicago navy, Dallas navy,
      Baltimore purple.
    * ``headline`` -- the vivid area that best survives being shrunk to text,
      then lifted until it is legible: Chicago orange, Baltimore gold.
    * ``accent`` -- the next vivid colour far enough away from the headline to
      be told apart, for confetti. Falls back to the headline.

    A crest with no vivid pixels at all falls back to its brightest neutral,
    which for the Raiders' silver-on-black is exactly the right answer.
    """
    try:
        vivid, neutral = _palette_buckets(logo)
    except Exception:  # noqa: BLE001 - a crest is never worth the takeover
        return None

    pool = list(vivid.values())
    if not pool and neutral:
        pool = [
            max(
                neutral.values(),
                key=lambda acc: acc[3]
                * (0.2 + 0.8 * min(1.0, _rgb_luminance(_bucket_mean(acc)) / 160.0)),
            )
        ]
    if not pool:
        return None

    deep_base = _bucket_mean(max(pool, key=lambda acc: acc[3]))
    ranked = sorted(pool, key=_bucket_headline_score, reverse=True)
    headline_base = _bucket_mean(ranked[0])
    vivid_pixels = sum(acc[3] for acc in pool)
    for acc in ranked:
        candidate = _bucket_mean(acc)
        if (
            _rgb_luminance(candidate) >= _PALETTE_LEGIBLE_LUMINANCE
            and _rgb_saturation(candidate) >= _PALETTE_LEGIBLE_SATURATION
            and acc[3] >= max(3, vivid_pixels * _PALETTE_LEGIBLE_AREA)
        ):
            headline_base = candidate
            break
    headline = _lift_color(headline_base)

    accent = headline
    for acc in ranked[1:]:
        candidate = _bucket_mean(acc)
        if _color_distance(candidate, headline_base) > _PALETTE_DISTINCT_DISTANCE:
            accent = _lift_color(candidate)
            break

    deep = _cap_luminance(deep_base, _PALETTE_BACKDROP_LUMINANCE)
    return {
        "deep": deep,
        # Scenery is the backdrop carried a little way towards the headline:
        # tied to the team's colours, and guaranteed to be visible even when
        # the backdrop is nearly black.
        "glow": _cap_luminance(
            _mix_color(deep, headline, 0.22), _PALETTE_SCENERY_LUMINANCE
        ),
        "headline": headline,
        "accent": accent,
    }


_DEFAULT_LOOKBACK_DAYS = 14
_DEFAULT_LOOKAHEAD_DAYS = 7
_MIN_WINDOW_DAYS = 1
_MAX_WINDOW_DAYS = 60


def _clamp_window(value: Any, fallback: int) -> int:
    """Days for one side of the schedule window, or the default if unusable."""
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: json parses bare Infinity by default and int(inf)
        # raises it, which would otherwise crash manager construction.
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


def _bdf_pixel_size(path):
    """The pixel size a .bdf font declares, or None if it does not."""
    try:
        with open(path, "r", encoding="latin-1") as handle:
            for line in handle:
                if line.startswith("PIXEL_SIZE"):
                    return int(line.split()[1])
                if line.startswith("CHARS"):
                    break  # past the header; no point reading the glyphs
    except (OSError, ValueError, IndexError):
        return None
    return None


def _logo_needs_refresh(logo_file) -> bool:
    """True if this file is a placeholder stale enough to retry the real logo.

    A failed logo download is cached as a placeholder wearing the real logo's
    filename, so "the file exists" is not proof the logo was ever fetched.
    Without this check one transient failure leaves a team a grey box forever.

    Returns False on a core that predates placeholder marking, which keeps the
    previous behaviour rather than breaking the load.
    """
    # Imported from the core by its full path, never as a bare name: a
    # deferred bare-name import can bind another plugin's vendored
    # logo_downloader once the core isolates top-level plugin modules.
    try:
        from src.logo_downloader import (
            PLACEHOLDER_RETRY_SECONDS,
            is_placeholder_logo,
            placeholder_age_seconds,
        )
    except ImportError:
        return False

    try:
        if not is_placeholder_logo(logo_file):
            return False
        age = placeholder_age_seconds(logo_file)
        return age is None or age >= PLACEHOLDER_RETRY_SECONDS
    except Exception:
        return False


class SportsCore(SportsCoreSharedMixin, ABC):
    #: Absolute path of this plugin, handed to the shared mixin. It cannot
    #: deduce it: __file__ there is src/common/, and inferring the directory
    #: from the MRO returns None under the real plugin loader, which silently
    #: disabled the schema lookup and shrank every grid-snapped font by a
    #: pixel. See SportsCoreSharedMixin._plugin_dir.
    _PLUGIN_DIR: ClassVar[str] = os.path.dirname(os.path.abspath(__file__))

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
        # Use LogoDownloader to get the correct default logo directory for this sport
        # Import from src to ensure we get the full LogoDownloader with get_logo_directory
        from src.logo_downloader import LogoDownloader as MainLogoDownloader
        try:
            logo_downloader = MainLogoDownloader()
            default_logo_dir = Path(logo_downloader.get_logo_directory(sport_key))
            self.logger.info(f"Logo directory for sport_key='{sport_key}': {default_logo_dir}")
        except Exception as e:
            # Fallback to default directory structure
            self.logger.warning(f"Failed to get logo directory for sport_key='{sport_key}': {e}, using fallback")
            default_logo_dir = Path(f"assets/sports/{sport_key}_logos")
        self.logo_dir = default_logo_dir
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
        self.other_upcoming_games_to_show: int = self._setting_int(
            "other_upcoming_games_to_show", self.upcoming_games_to_show, 0, 20
        )
        self.other_recent_games_to_show: int = self._setting_int(
            "other_recent_games_to_show", self.recent_games_to_show, 0, 20
        )
        # Variety comes from turnover, not from a bigger pool. Enlarging the
        # pool makes a lap longer -- roughly one card per visit -- so a wide
        # selection makes any given game RARER. Instead the pool stays short
        # and the non-favourite slice advances on this interval, so over a day
        # the board works through the schedule while a lap still takes minutes.
        # 0 pins the window, restoring the fixed "next N others".
        self.other_rotation_interval_seconds: int = self._setting_int(
            "other_rotation_interval_seconds", 1800, 0, 86400
        )
        # Turns a favourite's card gets in the recent/upcoming switch rotation
        # for every one turn any other card gets. 1 walks games_list in order.
        self.favorite_rotation_boost: int = self._setting_int(
            "favorite_rotation_boost", 1, 1, 5
        )
        self._other_window_start: int = 0
        self._other_window_rotated_at: float = 0.0
        # Monotonic stamp of the previous display() call. display() only runs
        # while this manager's mode is on the panel, so a large gap between
        # two calls means the mode just took (or retook) the screen -- see
        # _reset_dwell_on_reentry.
        self._last_display_call_monotonic: float = 0.0
        # Which non-favourite games are worth a slot. Selection is otherwise
        # purely chronological, and on a college slate two thirds of what that
        # returns is filler nobody asked for: rotating harder just serves more
        # of it. Favourites are NEVER filtered by these -- follow a Division II
        # school and its games always show; this only decides what fills the
        # remaining slots.
        self.other_games_min_quality: str = self._normalise_quality(
            self.mode_config.get("other_games_min_quality", "ranked")
        ).strip().lower()
        self.other_games_divisions: List[str] = self._normalise_divisions(
            self.mode_config.get("other_games_divisions", ["fbs"])
        )
        self._division_team_ids: Optional[Dict[str, set]] = None
        self._division_loaded_at: float = 0.0
        self.show_favorite_teams_only: bool = self.mode_config.get(
            "show_favorite_teams_only", False
        )
        self.show_all_live: bool = self.mode_config.get("show_all_live", False)
        try:
            self.favorite_live_boost: int = max(
                1, min(5, int(self.mode_config.get("favorite_live_boost", 2)))
            )
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

        # Decoded, resized logos, least recently used first. Bounded: a
        # college league's rotation reaches hundreds of teams over a season
        # and each entry is a full RGBA image (core #559).
        self._logo_cache: "OrderedDict[str, Image.Image]" = OrderedDict()

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
        # Thread safety lock for shared game state
        self._games_lock = threading.RLock()
        self.fonts = self._unshare_element_fonts(self._load_fonts())

        # Initialize dynamic team resolver and resolve favorite teams
        self.dynamic_resolver = DynamicTeamResolver()
        raw_favorite_teams = self.mode_config.get("favorite_teams", [])
        self.favorite_teams = self.dynamic_resolver.resolve_teams(
            raw_favorite_teams, sport_key
        )

        # Log dynamic team resolution
        if raw_favorite_teams != self.favorite_teams:
            self.logger.info(
                f"Resolved dynamic teams: {raw_favorite_teams} -> {self.favorite_teams}"
            )
        else:
            self.logger.info(f"Favorite teams: {self.favorite_teams}")

        # Teams to always hide from live rotation and recent/final scores (spoiler protection)
        raw_exclude_teams = self.mode_config.get("exclude_teams", [])
        self.exclude_teams = self.dynamic_resolver.resolve_teams(
            raw_exclude_teams, sport_key
        )
        if self.exclude_teams:
            self.logger.info(f"Excluded teams: {self.exclude_teams}")

        self.logger.setLevel(logging.INFO)

        # Initialize team rankings cache
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        self._rankings_cache_duration = 3600  # Cache rankings for 1 hour

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

    def display(self, force_clear: bool = False) -> bool:
        """
        Common display method for all managers.

        Returns True when a game was drawn and False when there was nothing to
        show. The caller uses that to skip an empty mode: returning None here
        left the display controller unable to tell "drew a game" from "drew
        nothing", so an out-of-season league held a blank panel for its whole
        display duration instead of being rotated past.
        """
        if not self.is_enabled:  # Check if module is enabled
            return False

        if not self.current_game:
            # Clear the display so old content doesn't persist
            if force_clear:
                self.display_manager.clear()
                self.display_manager.update_display()
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

    def _load_custom_font_from_element_config(
        self,
        element_config: Dict[str, Any],
        default_size: int = 8,
        default_font: Optional[str] = None,
        element_key=None,
    ) -> ImageFont.FreeTypeFont:
        """
        Load a custom font from an element configuration dictionary.

        Args:
            element_config: Configuration dict for a single element containing 'font' and 'font_size' keys
            default_size: Default font size if not specified in config
            default_font: Default font filename when not specified in config (e.g. '4x6-font.ttf' for odds)

        Returns:
            PIL ImageFont object
        """
        base_default = default_font or "PressStart2P-Regular.ttf"
        font_name = element_config.get("font", base_default)
        # Resolve a family alias to its filename BEFORE the path is built.
        # The grid table understands aliases, so a configured
        # "four_by_six" was sized on the 4x6 grid (7px) while the path
        # lookup used the raw alias, missed, and fell back to
        # PressStart2P -- rendering 7px on an 8px grid, anti-aliased.
        font_name = self._FONT_NAME_ALIASES.get(font_name, font_name)
        font_size = self._resolve_font_size(
            element_config, element_key, default_size, font_name)

        # Build font path
        font_path = _resolve_font_path(os.path.join("assets", "fonts", font_name))
        
        # Try to load the font
        try:
            if os.path.exists(font_path):
                # Try loading as TTF first (works for both TTF and some BDF files with PIL)
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    self.logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    # FreeType reads BDF, so truetype() handles a .bdf directly
                    # -- the core's FontManager and several plugins already do
                    # this. The old note here claimed otherwise and pointed at
                    # pilfont.py, so every .bdf face in the picker warned and
                    # fell back to the default font.
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        self.logger.debug(f"Loaded BDF font: {font_name} at size {font_size}")
                        return font
                    except OSError:
                        # A bitmap face exists at exactly the size it was drawn
                        # at; FreeType rejects any other with "invalid pixel
                        # size". Retry at the size the file declares.
                        native = _bdf_pixel_size(font_path)
                        if native is not None and native != font_size:
                            try:
                                font = ImageFont.truetype(font_path, native)
                                self.logger.debug(
                                    f"Loaded BDF font {font_name} at its native size {native} "
                                    f"(requested {font_size})")
                                return font
                            except OSError:
                                pass
                        self.logger.warning(
                            f"Could not load BDF font '{font_name}' at {font_size} "
                            "or its native size; falling back to default font.")
                    # Fall through to default
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, using default")

        # Fall back to default font
        default_font_path = _resolve_font_path(os.path.join("assets", "fonts", base_default))
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                self.logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()
    
    # ------------------------------------------------------------------
    # Upcoming-card center options -- config["scroll_card"].
    #
    # The same block game_renderer.py reads for the scroll and Vegas cards.
    # It used to stop there, so a user who set the matchup separator to "@"
    # got it on the ticker and never on the full-screen scoreboard. These
    # helpers mirror the renderer's so one setting drives every display mode;
    # the two copies have to stay in step.
    #
    # ``switch_upcoming_center`` exists because the shared ``upcoming_center``
    # defaults to "vs" while this display has always drawn the date and time
    # stacked. Defaulting the switch-mode key to "date_time" keeps every
    # existing panel rendering exactly what it rendered before the setting
    # reached it; "inherit" opts into the shared value.
    #
    # The center-gap keys are deliberately not read here: they size the
    # scroll card's middle strip, while this layout pins the logos to the
    # panel edges.
    # ------------------------------------------------------------------
    _MONTH_ABBR: ClassVar[Tuple[str, ...]] = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    _WEEKDAY_ABBR: ClassVar[Tuple[str, ...]] = (
        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
    )

    def _upcoming_date_and_time_text(self, game_date: str, game_time: str,
                                     game: Optional[Dict] = None) -> Tuple[str, str]:
        """The formatted (date, time) pair, blanked by switch_show_date/_time.

        Deliberately not the shared show_date/show_time: those governed only
        the scroll and Vegas cards before this display read the block, so a
        config that had turned them off there would silently blank a scorebug
        that has always drawn both lines. The switch keys default to True for
        the same reason switch_upcoming_center defaults to "date_time" -- an
        untouched panel keeps rendering exactly what it rendered before.
        Same fix as football-scoreboard #342.
        """
        date_text = (self._format_game_date(game_date, game)
                     if self._card_option("switch_show_date", True) else "")
        time_text = (self._format_game_time(game_time)
                     if self._card_option("switch_show_time", True) else "")
        return date_text, time_text

    def _mode_customization(self) -> dict:
        """``customization`` with this mode's overrides merged over it.

        SportsUpcoming / SportsRecent / SportsLive are separate instances
        with their own SKIN_MODE, so merging once here makes every
        per-element lookup mode-aware without changing one of them.

        ``None`` in a mode block means "inherit", which is what lets a user
        restyle one element on live cards and leave everything else
        following the settings above. It has to stay distinct from 0: a mode
        y_offset of 0 means "sit at the base position", not "no preference".
        """
        customization = self.config.get('customization', {})
        if not isinstance(customization, dict):
            return {}
        mode = getattr(self, 'SKIN_MODE', None)
        if not mode:
            return customization
        modes = customization.get('modes')
        block = modes.get(mode) if isinstance(modes, dict) else None
        if not isinstance(block, dict):
            return customization

        merged = dict(customization)
        for element, override in block.items():
            if element == 'layout' or not isinstance(override, dict):
                continue
            base = merged.get(element)
            base = dict(base) if isinstance(base, dict) else {}
            base.update({k: v for k, v in override.items() if v is not None})
            merged[element] = base

        mode_layout = block.get('layout')
        if isinstance(mode_layout, dict):
            base_layout = merged.get('layout')
            new_layout = dict(base_layout) if isinstance(base_layout, dict) else {}
            for element, axes in mode_layout.items():
                if not isinstance(axes, dict):
                    continue
                current = new_layout.get(element)
                current = dict(current) if isinstance(current, dict) else {}
                current.update({k: v for k, v in axes.items() if v is not None})
                new_layout[element] = current
            merged['layout'] = new_layout
        return merged

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
            layout_config = self._mode_customization().get('layout', {})
            element_config = layout_config.get(element, {})
            offset_value = element_config.get(axis, default)
            
            # Ensure we return an integer (handle float/string from config)
            if isinstance(offset_value, (int, float)):
                return int(offset_value)
            elif isinstance(offset_value, str):
                # Try to convert string to int
                try:
                    return int(float(offset_value))
                except (ValueError, TypeError):
                    self.logger.warning(
                        f"Invalid layout offset value for {element}.{axis}: '{offset_value}', using default {default}"
                    )
                    return default
            else:
                return default
        except Exception as e:
            # Gracefully handle any config access errors
            self.logger.debug(f"Error reading layout offset for {element}.{axis}: {e}, using default {default}")
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
        if not self._DRAWS_SCORE:
            return fonts
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

    #: Whether this screen actually draws a score. Everything below that sizes
    #: the score, reserves the middle for it, or trades face width to fit it is
    #: work done ON BEHALF of the score -- and SportsUpcoming draws no score at
    #: all. It uses fonts["time"] five times and fonts["score"] not once, so
    #: before this flag the upcoming card inherited a narrower face and a bigger
    #: size chosen for a number it never shows: "Next Game / 01/16 / 12:00AM"
    #: silently changed typeface on a 128x64 panel.
    _DRAWS_SCORE: ClassVar[bool] = True

    #: Panel height the fixed font sizes below were chosen against. Everything
    #: else on the card is sized from display_height -- the logos most of all
    #: -- so on a taller panel they grew and the score did not.
    _FONT_DESIGN_HEIGHT: ClassVar[int] = 32

    def _load_fonts(self):
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}
        
        # Get customization config, with backward compatibility.
        # Mode-merged, so a per-mode font or size reaches the right card.
        customization = self._mode_customization()
        
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
            fonts["score"] = self._load_custom_font_from_element_config(score_config, default_size=10, element_key='score_text')
            fonts["time"] = self._load_custom_font_from_element_config(period_config, default_size=8, element_key='period_text')
            fonts["team"] = self._load_custom_font_from_element_config(team_config, default_size=8, element_key='team_name')
            fonts["status"] = self._load_custom_font_from_element_config(status_config, default_size=6, element_key='status_text', default_font='4x6-font.ttf')
            fonts["detail"] = self._load_custom_font_from_element_config(
                detail_config, default_size=6, default_font="4x6-font.ttf"
            , element_key='detail_text')
            fonts["odds"] = self._load_custom_font_from_element_config(
                odds_config, default_size=6, default_font="4x6-font.ttf"
            , element_key='odds_text')
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
        # so the scorebug draw paths don't reload it from disk every frame.
        try:
            fonts["record"] = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
        except OSError:
            fonts["record"] = ImageFont.load_default()
        # Shots-on-goal line in the live scorebug uses the same small face;
        # cached here so it isn't reloaded from disk every frame.
        try:
            fonts["shots"] = ImageFont.truetype(_resolve_font_path("assets/fonts/4x6-font.ttf"), 7)
        except OSError:
            fonts["shots"] = ImageFont.load_default()
        # Grow first, then fit: _scale_headline_fonts sizes the score from
        # the panel height, and _fit_score_font is the guard that swaps in a
        # narrower FACE rather than let a grown score crowd out the logos.
        return self._fit_score_font(self._scale_headline_fonts(fonts))

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

    @staticmethod
    def _top_row_span(draw, text: str, font, width: int, x_offset: int = 0):
        """The (left, right) pixels of text centred on the top row, or None.

        Mirrors how the scorebugs place it: centred, then nudged by the
        element's configured x_offset.
        """
        if not text:
            return None
        try:
            text_width = draw.textlength(text, font=font)
        except Exception:
            return None
        left = int((width - text_width) // 2 + x_offset)
        return left, int(left + text_width)

    @staticmethod
    def _odds_would_hit_top_row(span, placements) -> bool:
        """Whether any odds text overlaps the centred text on the top row.

        Decided by measurement rather than panel size, the rule
        baseball-scoreboard's game_renderer uses: what matters is whether
        these particular strings fit beside each other, and a two-digit
        over/under is several pixels wider than a one-digit one.
        """
        if not span:
            return False
        left, right = span
        # One pixel of breathing room either side, so glyphs do not touch.
        return any(x < right + 1 and x + w > left - 1
                   for _text, x, w in placements)

    def _draw_dynamic_odds(
        self, draw: ImageDraw.Draw, odds: Dict[str, Any], width: int, height: int,
        top_span=None,
    ) -> None:
        """Draw odds with dynamic positioning - only show negative spread and position O/U based on favored team.

        `top_span` is the (left, right) the scorebug's own top-centre text
        occupies (the period and clock, "Final", "Next Game"). The odds sit on
        that same row, so when they would run through it they step down one
        text row instead. Omitted, no collision check is made.
        """
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

            # Fall back to the top-level spread only when a side's own spread
            # is truly missing. A home spread of 0.0 is a pick'em line, not an
            # absent one -- the scroll renderer already treats only None as
            # missing -- and the top-level value is negated only when it is a
            # number, so a malformed payload cannot raise out of the draw.
            if top_level_spread is not None:
                if home_spread is None:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = (-top_level_spread
                                   if isinstance(top_level_spread, (int, float))
                                   else None)

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

            font = self.fonts.get("odds") or self.fonts["detail"]

            # Work out both texts and their spans before drawing either, so
            # the row is chosen once with full knowledge of what has to fit.
            placements = []

            # Show the negative spread on the appropriate side
            if favored_spread is not None:
                spread_text = str(favored_spread)
                spread_width = draw.textlength(spread_text, font=font)
                if favored_side == "home":
                    # Home team is favored, show spread on right side
                    spread_x = width - spread_width  # Top right
                else:
                    # Away team is favored, show spread on left side
                    spread_x = 0  # Top left
                placements.append((spread_text, spread_x, spread_width))
                self.logger.debug(
                    f"Showing {favored_side} spread '{spread_text}'"
                )

            # Show over/under on the opposite side of the favored team
            over_under = odds.get("over_under")
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                ou_width = draw.textlength(ou_text, font=font)

                if favored_side == "away":
                    # Away favored, show O/U on right side (opposite of spread)
                    ou_x = width - ou_width  # Top right
                else:
                    # Home favored: left, opposite the spread. No favourite:
                    # also the left edge. Centring it put "O/U: 5.5" straight
                    # through the period and clock, "Final" or "Next Game",
                    # which every scorebug centres on this same row.
                    ou_x = 0  # Top left
                placements.append((ou_text, ou_x, ou_width))

            if not placements:
                return

            odds_y = 0
            if self._odds_would_hit_top_row(top_span, placements):
                # Step down one text row. Measured, not keyed to a panel size:
                # wide panels never reach the centre and never move.
                odds_y = draw.textbbox((0, 0), "A", font=font)[3] + 2

            for text, x, _w in placements:
                self._draw_text_with_outline(
                    draw, text, (x, odds_y), font, fill=self._odds_color()
                )

        except Exception as e:
            self.logger.error(f"Error drawing odds: {e}", exc_info=True)

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

    #: Most decoded logos kept at once, the cap core #559 set.
    _LOGO_CACHE_MAX: ClassVar[int] = 64

    def _load_and_resize_logo(
        self, team_id: str, team_abbrev: str, logo_path: Path, logo_url: str | None
    ) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching and automatic download if missing."""
        self.logger.debug(f"Logo path: {logo_path}")
        if team_abbrev in self._logo_cache:
            self.logger.debug(f"Using cached logo for {team_abbrev}")
            if hasattr(self._logo_cache, "move_to_end"):
                self._logo_cache.move_to_end(team_abbrev)
            return self._logo_cache[team_abbrev]

        try:
            # Try different filename variations first (for cases like TA&M vs TAANDM)
            actual_logo_path = None
            filename_variations = LogoDownloader.get_logo_filename_variations(
                team_abbrev
            )

            for filename in filename_variations:
                test_path = logo_path.parent / filename
                if test_path.exists() and not _logo_needs_refresh(test_path):
                    actual_logo_path = test_path
                    self.logger.debug(
                        f"Found logo at alternative path: {actual_logo_path}"
                    )
                    break

            # If no variation found, try to download missing logo
            if not actual_logo_path:
                self.logger.info(
                    f"Logo not found for {team_abbrev} at {logo_path}. Attempting to download."
                )

                # Try to download the logo from ESPN API (this will create placeholder if download fails)
                download_missing_logo(
                    self.sport_key, team_id, team_abbrev, logo_path, logo_url
                )
                actual_logo_path = logo_path

            # Use the original path if no alternative was found
            if not actual_logo_path:
                actual_logo_path = logo_path

            # Only try to open the logo if the file exists
            if os.path.exists(actual_logo_path):
                logo = Image.open(actual_logo_path)
            else:
                self.logger.error(
                    f"Logo file still doesn't exist at {actual_logo_path} after download attempt"
                )
                return None
            if logo.mode != "RGBA":
                logo = logo.convert("RGBA")

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
            logo.thumbnail((max_width, max_height), RESAMPLE_FILTER)
            self._logo_cache[team_abbrev] = logo
            # Insertion order is recency order (hits move_to_end above), so
            # the first key is always the least recently used.
            while len(self._logo_cache) > self._LOGO_CACHE_MAX:
                self._logo_cache.pop(next(iter(self._logo_cache)))
            return logo

        except Exception as e:
            self.logger.error(
                f"Error loading logo for {team_abbrev}: {e}", exc_info=True
            )
            return None

    def _fetch_odds(self, game: Dict) -> None:
        """Fetch odds for a specific game using the new architecture."""
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

            # Fetch odds using OddsManager
            odds_data = self.odds_manager.get_odds(
                sport=self.sport,
                league=self.league,
                event_id=game["id"],
                update_interval_seconds=update_interval,
            )

            if odds_data:
                game["odds"] = odds_data
                self.logger.debug(
                    f"Successfully fetched and attached odds for game {game['id']}"
                )
            else:
                self.logger.debug(f"No odds data returned for game {game['id']}")

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

    # Which ranking block the badge reads. ESPN answers /rankings with more
    # than one block for several leagues, and the FIRST is not always a poll:
    # men's and women's college hockey front "NCAA Men's/Women's Hockey
    # Tournament Seedings", so the badge drew a 16-team bracket seed where a
    # viewer expects a poll position, and college lacrosse publishes seedings
    # beside its Inside Lacrosse poll. College football fronts the AP Top 25
    # today but also carries the FCS and Division II polls and gains the CFP
    # rankings in November. Nothing in the payload promises the order.
    #
    # An EXCLUDE list, not an allow list, so a poll ESPN invents still counts
    # while seedings and the divisions below the top one never do.
    _NON_TOP_POLL_TYPES = frozenset({"tournament", "fcs"})
    _NON_TOP_POLL_NAMES = ("tournament", "seedings", "fcs",
                           "division ii", "division iii", "div ii", "div iii")

    def _choose_poll(self, rankings_data):
        """The first block ESPN lists that is an actual top-division poll.

        ESPN's own order is otherwise kept, so whichever poll it fronts is the
        one that drives the badge.
        """
        for block in rankings_data or []:
            name = str(block.get("name") or "").lower()
            kind = str(block.get("type") or "").lower()
            if kind in self._NON_TOP_POLL_TYPES or any(
                marker in name for marker in self._NON_TOP_POLL_NAMES
            ):
                self.logger.debug(
                    "%s: skipping %s -- not a top-division poll",
                    getattr(self, "league", "?"), block.get("name") or kind)
                continue
            return block
        return {}

    def _fetch_team_rankings(self) -> Dict[str, int]:
        """Fetch team rankings using the new architecture components."""
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
            rankings_data = data.get("rankings", [])

            first_ranking = self._choose_poll(rankings_data)
            if first_ranking:
                teams = first_ranking.get("ranks", [])

                for team_data in teams:
                    team_info = team_data.get("team", {})
                    team_abbr = team_info.get("abbreviation", "")
                    current_rank = team_data.get("current", 0)

                    if team_abbr and current_rank > 0:
                        rankings[team_abbr] = current_rank

            # Cache the results
            self._team_rankings_cache = rankings
            self._rankings_cache_timestamp = current_time

            self.logger.debug(f"Fetched rankings for {len(rankings)} teams")
            return rankings

        except Exception as e:
            self.logger.error(f"Error fetching team rankings: {e}")
            return {}

    #: ESPN statuses that arrive with state "post" but are not a result. A
    #: postponed game reports state "post" with both scores "0", so reading
    #: state alone put a rained-off -- iced-off -- game on the Recent screen as
    #: "Final 0-0".
    _NOT_A_RESULT_STATUSES: ClassVar[frozenset] = frozenset({
        "STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED",
        "STATUS_SUSPENDED", "STATUS_DELAYED", "STATUS_ABANDONED",
    })

    @classmethod
    def _status_is_final(cls, status_type: Dict) -> bool:
        """Whether an ESPN status.type describes a game that was played out.

        state "post" is necessary but not sufficient: ESPN also files
        postponed, cancelled and suspended games there. Requires the
        completed flag ESPN sets on every real final, and excludes those
        statuses by name as well in case a feed marks one completed.
        """
        if not isinstance(status_type, dict):
            return False
        if status_type.get("state") != "post":
            return False
        if not status_type.get("completed"):
            return False
        return str(status_type.get("name") or "").upper() not in cls._NOT_A_RESULT_STATUSES

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
                    # If naive, ESPN API typically returns times in Eastern Time for NHL/NFL
                    # Assume Eastern Time and convert to UTC
                    eastern = pytz.timezone('America/New_York')
                    start_time_utc = eastern.localize(dt).astimezone(pytz.UTC)
                else:
                    # Convert to pytz.UTC for consistency
                    start_time_utc = dt.astimezone(pytz.UTC)
            except ValueError:
                self.logger.warning("Could not parse game date: %s", game_date_str)

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
                    # %-m/%-d are glibc extensions: strftime raises ValueError on
                    # Windows and musl. Build the same text portably instead.
                    game_date = f"{local_time.month}/{local_time.day}"
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

            details = {
                "id": game_event.get("id"),
                "game_time": game_time,
                "game_date": game_date,
                "start_time_utc": start_time_utc,
                "status_text": status["type"][
                    "shortDetail"
                ],  # e.g., "Final", "7:30 PM", "Q1 12:34"
                "is_live": status["type"]["state"] == "in",
                "is_final": self._status_is_final(status["type"]),
                "is_upcoming": (
                    status["type"]["state"] == "pre"
                    or status["type"]["name"].lower()
                    in ["scheduled", "pre-game", "status_scheduled"]
                ),
                "is_halftime": status["type"]["state"] == "halftime"
                or status["type"]["name"] == "STATUS_HALFTIME",  # Added halftime check
                "is_period_break": status["type"]["name"]
                == "STATUS_END_PERIOD",  # Added Period Break check
                "broadcast": (competition.get("broadcast") or ""),
                "home_abbr": home_abbr,
                "home_id": home_team["id"],
                "home_score": home_team.get("score", "0"),
                "home_logo_path": self.logo_dir
                / Path(f"{LogoDownloader.normalize_abbreviation(home_abbr)}.png"),
                "home_logo_url": home_team["team"].get("logo"),
                "home_record": home_record,
                "away_record": away_record,
                "away_abbr": away_abbr,
                "away_id": away_team["id"],
                "away_score": away_team.get("score", "0"),
                "away_logo_path": self.logo_dir
                / Path(f"{LogoDownloader.normalize_abbreviation(away_abbr)}.png"),
                "away_logo_url": away_team["team"].get("logo"),
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
        """Fetch only today's games for live updates (not entire season)."""
        try:
            # ESPN API anchors its schedule calendar to Eastern US time.
            # Always query using the Eastern date + 1-day lookback to catch
            # late-night games still in progress from the previous Eastern day.
            tz = pytz.timezone("America/New_York")
            now = datetime.now(tz)
            yesterday = now - timedelta(days=1)
            formatted_date = now.strftime("%Y%m%d")
            formatted_date_yesterday = yesterday.strftime("%Y%m%d")
            # Fetch todays games only
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/scoreboard"
            data = fetch_espn_scoreboard(
                self.session,
                url,
                params={"dates": f"{formatted_date_yesterday}-{formatted_date}", "limit": ESPN_MAX_LIMIT},
                headers=self.headers,
                timeout=10,
                logger=self.logger,
            )
            events = data.get("events", [])

            self.logger.info(
                f"Fetched {len(events)} games for the last 2 days for {self.sport} - {self.league}"
            )
            return {"events": events}
        except requests.exceptions.RequestException as e:
            self.logger.error(
                f"API error fetching todays games for {self.sport} - {self.league}: {e}"
            )
            return None

    def _get_weeks_data(self) -> Optional[Dict]:
        """Games in the lookback/lookahead window, shown while the season loads.

        Overrides the core mixin's copy, which asks ESPN for this window as a
        date range. ESPN has answered ranges with 400 since 2026-09-15 and cores
        from before that fix have no fallback, so without this override the
        window fails whenever the season schedule is not cached yet.
        """
        date_str = ""
        try:
            now = datetime.now(pytz.utc)
            start_date = now - timedelta(days=self.schedule_lookback_days)
            end_date = now + timedelta(days=self.schedule_lookahead_days)
            date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/scoreboard"
            data = fetch_espn_scoreboard(
                self.session,
                url,
                params={"dates": date_str, "limit": ESPN_MAX_LIMIT},
                headers=self.headers,
                timeout=10,
                logger=self.logger,
            )
            immediate_events = data.get("events", [])

            if immediate_events:
                self.logger.info(f"Fetched {len(immediate_events)} events {date_str}")
                return {"events": immediate_events}

        except requests.exceptions.RequestException as e:
            self.logger.warning(
                f"Error fetching this weeks games for {self.sport} - {self.league} - {date_str}: {e}"
            )
        return None

    def _background_fetches_espn_ranges(self) -> bool:
        """Can the core's background service fetch an ESPN date range?

        Cores from before the 2026-09-15 fix send a season range to ESPN as-is,
        which now answers 400 for every sport. On those cores the managers fetch
        the season themselves with _fetch_season_directly instead.
        """
        service = getattr(self, "background_service", None)
        return bool(getattr(service, "handles_espn_date_ranges", False))

    def _fetch_season_directly(
        self,
        url: str,
        datestring: str,
        cache_key: str,
        label: str,
        ttl: Optional[int] = None,
    ) -> Optional[Dict]:
        """Fetch a season schedule on this thread, in chunks ESPN accepts, and cache it.

        ``label`` names the schedule in log lines, e.g. ``"2026 season"``.
        """
        try:
            data = fetch_espn_scoreboard(
                self.session,
                url,
                params={"dates": datestring, "limit": ESPN_MAX_LIMIT},
                headers=self.headers,
                timeout=30,
                logger=self.logger,
            )
        except Exception as e:
            self.logger.error(f"Failed to fetch {label} schedule: {e}")
            return None
        if ttl is None:
            self.cache_manager.set(cache_key, data)
        else:
            self.cache_manager.set(cache_key, data, ttl=ttl)
        self.logger.info(
            f"Fetched {label} schedule: {len(data.get('events', []))} events"
        )
        return data

    def _is_favorite_game(self, game: Dict) -> bool:
        """Does either side of this game belong to a favourite team?"""
        if not self.favorite_teams:
            return False
        return (
            game.get("home_abbr") in self.favorite_teams
            or game.get("away_abbr") in self.favorite_teams
        )

    # Class-level defaults for everything the selection path reads. __init__
    # sets all of these from config; these exist so a missing one can never
    # raise. That failure is invisible where it matters: the read happens
    # inside update()'s own try/except, so the exception is swallowed and the
    # board simply goes blank with no explanation.
    #
    # They deliberately fail OPEN -- no quality bar, no division restriction --
    # matching the filters themselves, so the degraded state shows too much
    # rather than nothing.
    other_upcoming_games_to_show: ClassVar[int] = 0
    other_recent_games_to_show: ClassVar[int] = 0
    other_rotation_interval_seconds: ClassVar[int] = 0
    other_games_min_quality: ClassVar[str] = "any"
    other_games_divisions: ClassVar[tuple] = ()
    _other_window_start: ClassVar[int] = 0
    _other_window_rotated_at: ClassVar[float] = 0.0
    _division_team_ids: ClassVar[Optional[Dict[str, set]]] = None
    _division_loaded_at: ClassVar[float] = 0.0
    _team_rankings_cache: ClassVar[Dict[str, int]] = {}

    # ESPN group ids for the college divisions. Derived from its own group
    # rosters, which are disjoint (148 FBS team ids, 130 FCS, no overlap).
    # conferenceId is NOT usable for this: cross-division games put an FBS
    # conference on an FCS slate, so the id sets overlap and a game like
    # Merrimack at Delaware classifies as FBS.
    #
    # Keyed by league, because FBS/FCS is a college FOOTBALL taxonomy and ESPN
    # publishes those group rosters for that league alone. Every other college
    # league was asked for the same two groups and answered with nothing
    # usable -- college-baseball and both college-lacrosse leagues return HTTP
    # 500, and men's and women's college basketball and college hockey return
    # 200 with an empty item list. An empty roster fails open, so the setting
    # never filtered anything there; it only cost two requests a day and a
    # warning in the log, on every league that cannot have divisions at all.
    _DIVISION_GROUPS_BY_LEAGUE: ClassVar[Dict[str, Dict[str, int]]] = {
        "college-football": {"fbs": 80, "fcs": 81},
    }
    _DIVISION_CACHE_TTL: ClassVar[int] = 24 * 60 * 60
    _RANKING_COVERAGE_SECONDS: ClassVar[int] = 60 * 60
    _ranking_coverage_logged_at: ClassVar[float] = 0.0
    # A lookup that came back empty is retried on this shorter clock.
    _DIVISION_RETRY_SECONDS: ClassVar[int] = 10 * 60

    def _load_division_team_ids(self) -> Dict[str, set]:
        """Team ids per college division. Two requests a day, one league.

        Returns empty sets on any failure -- the caller treats "unknown" as
        "allowed", because a division lookup that fails must not blank the
        board.

        The in-memory copy expires like the stored one. Holding it for the life
        of the process meant two things, both silent: a board that happened to
        be offline for the first lookup had division filtering disabled until
        someone restarted the service, which on a display running for weeks is
        indefinitely; and a roster that changed between seasons was never
        picked up. A failed lookup is retried sooner than a good one, so a
        blip costs minutes rather than a day, without retrying per frame.
        """
        now = time.monotonic()
        if self._division_team_ids is not None:
            resolved = any(self._division_team_ids.values())
            age_limit = self._DIVISION_CACHE_TTL if resolved else self._DIVISION_RETRY_SECONDS
            if now - self._division_loaded_at < age_limit:
                return self._division_team_ids
        self._division_team_ids = {}
        self._division_loaded_at = now
        groups = self._DIVISION_GROUPS_BY_LEAGUE.get((self.league or "").lower())
        if not groups:
            return self._division_team_ids     # no divisions to speak of
        for name, group in groups.items():
            ids = set()
            key = f"{self.league}_division_teams_{group}"
            try:
                cached = self.cache_manager.get(key) if self.cache_manager else None
                if cached:
                    ids = {int(i) for i in cached}
                else:
                    url = (
                        "https://sports.core.api.espn.com/v2/sports/"
                        f"{self.sport}/leagues/{self.league}/seasons/"
                        f"{datetime.now().year}/types/2/groups/{group}/teams"
                    )
                    resp = self.session.get(url, params={"limit": 300}, timeout=15)
                    resp.raise_for_status()
                    for item in resp.json().get("items", []):
                        found = re.search(r"/teams/(\d+)", item.get("$ref", ""))
                        if found:
                            ids.add(int(found.group(1)))
                    if ids and self.cache_manager:
                        self.cache_manager.set(
                            key, sorted(ids), ttl=self._DIVISION_CACHE_TTL
                        )
            except Exception as exc:
                self.logger.warning(
                    "Could not resolve %s teams for %s (%s); division filtering "
                    "will allow everything", name, self.league, exc
                )
            self._division_team_ids[name] = ids
        return self._division_team_ids

    def _setting_int(self, key: str, default: int, low: int, high: int) -> int:
        """A count from config, clamped to the range its schema declares.

        The schema constrains these, but config.json can be hand-edited or
        written by an older tool, and a string or a negative here does not
        raise where anyone would see it -- it raises inside update()'s own
        try/except, which shows up as a mode that silently renders nothing.
        Same shape as the favorite_live_boost clamp above.
        """
        try:
            return max(low, min(high, int(self.mode_config.get(key, default))))
        except (TypeError, ValueError, OverflowError):
            # OverflowError: a config Infinity -- int(inf) raises it.
            self.logger.warning(
                "%s: ignoring unusable %s=%r, using %s",
                getattr(self, "league", "?"), key,
                self.mode_config.get(key), default,
            )
            return default

    def _is_ranked_game(self, game: Dict) -> bool:
        rankings = getattr(self, "_team_rankings_cache", None) or {}
        if not rankings:
            return False
        return bool(
            rankings.get(game.get("home_abbr"), 0)
            or rankings.get(game.get("away_abbr"), 0)
        )

    def _best_rank(self, game: Dict) -> int:
        """The better of the two sides' poll positions, or 99 if neither ranks."""
        rankings = getattr(self, "_team_rankings_cache", None) or {}
        if not rankings:
            return 99
        ranked = [r for r in (rankings.get(game.get("home_abbr"), 0),
                              rankings.get(game.get("away_abbr"), 0)) if r]
        return min(ranked) if ranked else 99

    def _by_importance(self, games: List[Dict], newest_first: bool = False) -> List[Dict]:
        """Non-favourite games, best matchup first.

        The quality filter already declares the poll to be the thing worth
        showing -- and then selection ignored the number entirely. #1 against #2
        and #25 against an unranked side were interchangeable, and whichever
        kicked off sooner took the slot, so the biggest game of the week had no
        better chance of being seen than any other.

        The rotation still walks the entire pool, so nothing is lost and
        coverage is unchanged; it now walks DOWN the ladder instead of along the
        clock. The first window after a restart holds the best games available
        rather than the earliest ones, which is the case that matters -- a board
        is far more often freshly started or freshly updated than three hours
        into a lap.

        Ties fall back to kickoff order, and a league with no poll keeps the
        chronological order it had, because there is nothing to sort on.

        One game per team, which is the part rank ordering cannot do without.
        The upcoming pool is not a week of fixtures -- for college football it
        is the whole season, 947 games on a real board -- so ordering by rank
        alone put all twelve of the #1 team's games above the #2 team's first
        one, and the board walked one team's season. Measured on ledpi the
        moment this shipped: KENT@OSU, ILL@OSU, then OSU@IOWA, MD@OSU. Keeping
        only the soonest game per team makes the pool "what each team has
        next", which is both what an upcoming board means and inherently
        near-term, since a team's next game is by definition the closest one.
        """
        rankings = getattr(self, "_team_rankings_cache", None) or {}
        if not rankings:
            return games
        if newest_first:
            def key(game):
                when = game.get("start_time_utc") or datetime.min.replace(tzinfo=timezone.utc)
                return (self._best_rank(game), -when.timestamp())
        else:
            def key(game):
                when = game.get("start_time_utc") or datetime.max.replace(tzinfo=timezone.utc)
                return (self._best_rank(game), when.timestamp())

        # Soonest-first so "one per team" keeps each team's NEXT game, then
        # re-ordered by rank. Doing it the other way round would keep whichever
        # of a team's games happened to sort first by rank, which for a game
        # between two ranked sides is not necessarily the next one.
        soonest_first = sorted(
            games,
            key=lambda g: (g.get("start_time_utc")
                           or datetime.max.replace(tzinfo=timezone.utc)).timestamp(),
            reverse=newest_first,
        )
        seen, once_each = set(), []
        for game in soonest_first:
            sides = (game.get("home_abbr"), game.get("away_abbr"))
            if any(side in seen for side in sides):
                continue
            seen.update(s for s in sides if s)
            once_each.append(game)
        return sorted(once_each, key=key)

    #: What other_games_min_quality may be. "broadcast" is retired and
    #: migrates to "ranked" -- see _normalise_quality.
    _QUALITY_CHOICES: ClassVar[frozenset] = frozenset({"any", "ranked"})

    def _passes_other_filters(self, game: Dict) -> bool:
        """Is this non-favourite game worth one of the remaining slots?

        Every check fails OPEN. If rankings could not be fetched or the
        division rosters did not resolve, the game is allowed: a board showing
        filler is a poor board, but a board showing nothing is a broken one.
        """
        if self.other_games_min_quality == "ranked":
            if getattr(self, "_team_rankings_cache", None) and \
                    not self._is_ranked_game(game):
                return False

        wanted = self.other_games_divisions
        if wanted:
            present = self._game_divisions(game)
            if present is not None and not (present & set(wanted)):
                return False
        return True

    def _filtered_or_all(self, games: List[Dict]) -> List[Dict]:
        """The games worth watching, or all of them if that leaves none.

        With no favourites configured every game selected is a non-favourite
        game, so the quality and division settings have to apply here too. They
        governed only the top-up slice, which this branch never uses, so a
        board with an empty favourites list had both settings silently inert --
        it could ask for ranked games only and still get the next N kickoffs.

        Fails open as a whole, not just per check. `_passes_other_filters`
        allows a game whose data could not be resolved, but a filter working
        exactly as asked can still match nothing on a given day, and here there
        is no favourite left to carry the mode -- an empty list is a blank
        panel rather than a short one.
        """
        kept = [g for g in games if self._passes_other_filters(g)]
        self._check_ranking_coverage(games)
        return kept or games


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

    def _rotate_other_games_on_display(self) -> bool:
        """Swap in a freshly cut slice when the rotation interval has passed.

        Returns True when the list changed, so the caller forces a redraw.

        The card currently on screen keeps its place if it survived the cut:
        rotating the pool should change what comes NEXT, not interrupt whatever
        someone is reading. Only when it is gone does the index reset, and then
        the dwell resets with it so the replacement gets a full turn rather than
        the tail of its predecessor's.
        """
        rebuilt = self._advance_other_games_if_due()
        if not rebuilt:
            return False
        with self._games_lock:
            if [g.get("id") for g in rebuilt] == [g.get("id") for g in self.games_list]:
                return False
            current_id = (self.current_game or {}).get("id")
            self.games_list = rebuilt
            for index, game in enumerate(rebuilt):
                if game.get("id") == current_id:
                    self.current_game_index = index
                    self.current_game = game
                    break
            else:
                self.current_game_index = 0
                self.current_game = rebuilt[0]
                self.last_game_switch = time.time()
            self.logger.info(
                "Rotated the other-games slice to: %s",
                ", ".join("%s@%s" % (g.get("away_abbr"), g.get("home_abbr"))
                          for g in rebuilt),
            )
        self._attach_odds_to_rotated_games(rebuilt)
        return True

    def _attach_odds_to_rotated_games(self, games: List[Dict]) -> None:
        """Fetch odds for freshly rotated-in games off the display path.

        The rotation deliberately does no network work, but odds are only
        attached in update(), and for an upcoming list that runs hourly --
        far longer than any rotated-in card stays on screen. Every slice cut
        between updates therefore rendered without a line even though ESPN
        had one, while the favourites, which survive every cut, kept the
        odds update() gave them. Same fix as football-scoreboard #343.

        One daemon thread per rotation, bounded by the slice size rather
        than the pool's: only games actually going on screen are asked
        about, and get_odds caches per game, so one re-entering the window
        inside its TTL costs a cache lookup rather than a request. The
        thread mutates each game dict in place; the renderer re-reads
        game["odds"] every frame, so a line appears as soon as its fetch
        lands, mid-dwell included.
        """
        if not getattr(self, "show_odds", False):
            return
        pending = [g for g in games if not g.get("odds")]
        if not pending:
            return
        interval = self.mode_config.get("odds_update_interval", 3600)

        def fetch() -> None:
            for game in pending:
                try:
                    odds = self.odds_manager.get_odds(
                        sport=self.sport,
                        league=self.league,
                        event_id=game["id"],
                        update_interval_seconds=interval,
                    )
                    if odds:
                        game["odds"] = odds
                except Exception as exc:
                    self.logger.debug(
                        "Odds fetch for rotated-in game %s failed: %s",
                        game.get("id"), exc)

        threading.Thread(
            target=fetch, daemon=True,
            name="%s-rotated-odds" % self.sport_key).start()

    #: Longest gap between two display() calls that still counts as one
    #: on-screen stint. Frames arrive many times a second while a mode is on
    #: the panel; between mode blocks the gap is the length of every other
    #: mode's block -- a minute or more. Anything past a few seconds can only
    #: be a block boundary, or the very first frame after startup.
    _DWELL_REENTRY_GAP_SECONDS: ClassVar[float] = 5.0

    def _reset_dwell_on_reentry(self) -> bool:
        """Give the current card a full turn when this mode (re)takes the panel.

        The dwell clock (last_game_switch) keeps running while the mode is off
        screen, so on re-entry it was always long expired and the first
        display() call advanced immediately: the card cut off by the end of
        the previous block was skipped instead of shown, and after a service
        restart the clock started at manager construction, seconds before the
        first frame, shaving that much off the first card. Same fix as
        football-scoreboard #345.

        Returns True when the dwell was reset, so the caller forces a redraw.
        """
        # getattr, and zero treated as "never displayed": the managers are
        # constructed in several places -- the plugin tests among them -- not
        # all of which set every attribute, and a freshly booted Pi can reach
        # the first frame while time.monotonic() itself is still under the
        # gap threshold, which would make `now - 0.0` look like one stint.
        last = getattr(self, "_last_display_call_monotonic", 0.0)
        now = time.monotonic()
        self._last_display_call_monotonic = now
        if last > 0.0 and now - last < self._DWELL_REENTRY_GAP_SECONDS:
            return False
        if getattr(self, "last_game_switch", 0) <= 0:
            # Zero is the live screen's "no game shown yet" sentinel with its
            # own handling; overwriting it here would hide the first game's
            # arrival from that logic.
            return False
        self.last_game_switch = time.time()
        return True

    @staticmethod
    def _spread_weighted_order(weights: List[int]) -> List[int]:
        """Indices into ``weights``, each repeated by its weight and spread out.

        Each index keeps its own slot and places its extra turns at even
        fractions of the rotation after it, wrapping round. That keeps the
        list's schedule order for everything else and spaces a favourite's
        repeats evenly *around the loop* -- the live rotation's smooth
        weighted round-robin schedules a boosted game first and last, so a
        rotation that wraps shows it back to back. Equal weights come back in
        plain order, so a boost that applies to no card changes nothing.

        Repeats are kept apart only where the ratio leaves room: once one
        weight exceeds all the others combined, no cyclic order can separate
        its turns ([3, 1, 1] gives [0, 1, 0, 2, 0]). Each index still gets
        exactly its weight in turns -- the configured ratio wins over spacing.
        """
        count = len(weights)
        slots = []
        for index, weight in enumerate(weights):
            for turn in range(weight):
                slots.append(((index + turn * count / weight) % count, turn > 0, index))
        return [index for _, _, index in sorted(slots)]

    def _next_switch_index(self) -> int:
        """The games_list index switch mode shows next.

        favorite_rotation_boost gives a favourite's card that many turns for
        every one turn another card gets, spread through the rotation and kept
        apart wherever the other cards leave room (a boost above the number of
        other cards makes some repeats adjacent; the ratio is kept either way).
        games_list itself stays one entry per game -- the
        cycle-duration count, the scroll strip and the other-games re-cut all
        read it -- so the weighting is an order walked over it instead.

        The order is rebuilt whenever the list's games change, and the walk
        resyncs from current_game_index whenever the two disagree: update()
        and the other-games rotation both set the index directly when they
        swap a list in, and the card on screen is where the walk resumes.

        Called with _games_lock held and games_list non-empty.
        """
        count = len(self.games_list)
        boost = getattr(self, "favorite_rotation_boost", 1)
        if boost <= 1 or count < 2:
            return (self.current_game_index + 1) % count
        key = (boost, tuple(g.get("id") for g in self.games_list))
        if getattr(self, "_switch_order_key", None) != key:
            self._switch_order = self._spread_weighted_order(
                [boost if self._is_favorite_game(g) else 1 for g in self.games_list]
            )
            self._switch_order_key = key
            self._switch_position = -1
        order = self._switch_order
        position = getattr(self, "_switch_position", -1)
        if not 0 <= position < len(order) or order[position] != self.current_game_index:
            position = (order.index(self.current_game_index)
                        if self.current_game_index in order else -1)
        position = (position + 1) % len(order)
        self._switch_position = position
        return order[position]

    def _advance_other_games_if_due(self) -> List[Dict]:
        """Re-cut the non-favourite slice on the display path, or [] if not due.

        Costs one list slice and a sort of at most a few games -- no fetch, no
        parsing, no network. Returns the new list rather than assigning it,
        because the two callers keep different bookkeeping around games_list
        and both hold their own lock while they swap it in.
        """
        pools = getattr(self, "_selection_pools", None)
        if not pools:
            return []
        interval = self.other_rotation_interval_seconds
        others, limit = pools["others"], max(0, pools["other_limit"])
        if interval <= 0 or limit <= 0 or len(others) <= limit:
            return []       # pinned, favourites-only, or nothing to rotate through
        if not self._other_window_rotated_at:
            return []       # no window has been cut yet; update() does the first
        if time.monotonic() - self._other_window_rotated_at < interval:
            return []
        return self._compose_selection()


class SportsUpcoming(SportsCore):
    SKIN_MODE = "upcoming"
    #: This screen shows the date and the time, never a score.
    _DRAWS_SCORE: ClassVar[bool] = False

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
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

        # Rankings drive the rank badge AND, when the quality filter is set to
        # "ranked", which games are eligible at all. Fetching them only for the
        # badge left the filter with an empty table and emptied the board.
        if self.show_ranking or (
            self.other_games_min_quality == "ranked" and self._league_has_rankings()
        ):
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

            # How far ahead this screen looks. The ranged fetch already uses
            # this horizon, but selection reads the season-wide cache, so
            # without a cutoff here every fixture ESPN has published was
            # eligible and Upcoming could show games weeks out. Mirrors the
            # lookback cutoff on the Recent screen; favourites obey it too,
            # since it is a window, not a filter.
            now = datetime.now(timezone.utc)
            lookahead_days = getattr(
                self, "schedule_lookahead_days", _DEFAULT_LOOKAHEAD_DAYS)
            upcoming_cutoff = now + timedelta(days=lookahead_days)

            for event in events:
                game = self._extract_game_details(event)
                # Count all upcoming games for debugging
                if game and game["is_upcoming"]:
                    all_upcoming_games += 1

                # Filter criteria: must be upcoming ('pre' state)
                if game and game["is_upcoming"]:
                    start_time = game.get("start_time_utc")
                    if start_time and start_time > upcoming_cutoff:
                        continue
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
                    self._filtered_or_all(processed_games),
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
                    self.current_game = self.games_list[
                        self.current_game_index
                    ]  # Update data

                if not self.games_list:
                    self.logger.info(
                        "No relevant upcoming games found to display."
                    )  # Changed log prefix
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
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
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
                # Draw on the image that gets pasted. Drawing on a throwaway
                # .convert("RGB") copy and pasting main_img left a black panel.
                error_img = main_img.convert("RGB")
                draw_final = ImageDraw.Draw(error_img)
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image.paste(error_img, (0, 0))
                self.display_manager.update_display()
                return

            center_y = self.display_height // 2

            # MLB-style logo positions with layout offsets
            home_x = self.display_width - home_logo.width + 2 + self._get_layout_offset('home_logo', 'x_offset')
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -2 + self._get_layout_offset('away_logo', 'x_offset')
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Draw Text Elements on Overlay
            game_date = game.get("game_date", "")
            game_time = game.get("game_time", "")

            # Note: Rankings are now handled in the records/rankings section below

            # The middle of an upcoming scorebug -- the matchup separator, the
            # date and time stacked, or nothing -- is config-driven now, so the
            # one scroll_card setting drives switch, scroll and Vegas alike
            # instead of stopping at the ticker. "vs" and "none" move the date
            # and time out to the top and bottom rows, and the top row is where
            # the header sits, so the helper reports whether it still has a slot.
            top_span = None
            if self._draw_upcoming_center_switch(
                    draw_overlay, game, center_y, game_date, game_time,
                    display_width=self.display_width, display_height=self.display_height):
                # "Next Game" at the top (use smaller status font) with layout offsets
                status_font = self.fonts["status"]
                if self.display_width > 128:
                    status_font = self.fonts["time"]
                status_text = "Next Game"
                status_width = draw_overlay.textlength(status_text, font=status_font)
                status_x = (self.display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
                status_y = 1 + self._get_layout_offset('status_text', 'y_offset')  # Changed from 2
                self._draw_text_with_outline(
                    draw_overlay, status_text, (status_x, status_y), status_font
                )
                top_span = self._top_row_span(
                    draw_overlay, status_text, status_font, self.display_width,
                    self._get_layout_offset('status_text', 'x_offset'))

            # Draw odds if available
            if "odds" in game and game["odds"]:
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height,
                    top_span=top_span,
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
        """
        Display upcoming games, handling switching.

        Returns True when a game was drawn, False when there was nothing to
        show, so the caller can rotate past an empty mode instead of holding a
        blank panel for its full display duration.
        """
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

        # The mode just took the panel: the current card gets its full turn
        # before the dwell check below is allowed to advance.
        if self._reset_dwell_on_reentry():
            force_clear = True

        # Before the dwell check, so a fresh slice is on screen for a full
        # duration rather than for whatever was left of the previous card's.
        if self._rotate_other_games_on_display():
            force_clear = True

        try:
            current_time = time.time()

            # Check if it's time to switch games (protected by lock for thread safety)
            with self._games_lock:
                if (
                    len(self.games_list) > 1
                    and current_time - self.last_game_switch >= self.game_display_duration
                ):
                    self.current_game_index = self._next_switch_index()
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
                self._draw_scorebug_layout(self.current_game, force_clear)
                # update_display() is called within _draw_scorebug_layout
                return True
            return False

        except Exception as e:
            self.logger.error(
                f"Error in display loop: {e}", exc_info=True
            )  # Changed log prefix
            return False


class SportsRecent(SportsRecentSharedMixin, SportsCore):
    SKIN_MODE = "recent"

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

        # Rankings drive the rank badge AND, when the quality filter is set to
        # "ranked", which games are eligible at all. Fetching them only for the
        # badge left the filter with an empty table and emptied the board.
        if self.show_ranking or (
            self.other_games_min_quality == "ranked" and self._league_has_rankings()
        ):
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
                    clock = game.get("clock", "")
                    period = game.get("period", 0)
                    period_text = game.get("period_text", "").lower()

                    if "final" in period_text:
                        appears_finished = True
                        self._clear_zero_clock_tracking(game_id)
                    elif period >= 3:  # Hockey: 3 periods (P3 or OT)
                        clock_normalized = clock.replace(":", "").strip() if isinstance(clock, str) else ""
                        if clock_normalized in ("000", "00", "") or clock in ("0:00", ":00"):
                            zero_clock_duration = self._get_zero_clock_duration(game_id)
                            if zero_clock_duration >= 120:
                                appears_finished = True
                                self.logger.debug(
                                    f"Game {game.get('away_abbr')}@{game.get('home_abbr')} "
                                    f"appears finished after {zero_clock_duration:.0f}s at 0:00"
                                )
                        else:
                            self._clear_zero_clock_tracking(game_id)
                else:
                    self._clear_zero_clock_tracking(game_id)

                # Excluded teams are hidden from recent/final scores too (spoiler protection)
                if self.exclude_teams and (
                    game.get("home_abbr") in self.exclude_teams
                    or game.get("away_abbr") in self.exclude_teams
                ):
                    continue

                # Filter criteria: must be final OR appear finished, AND within recent date range
                is_eligible = game.get("is_final", False) or appears_finished
                if is_eligible:
                    game_time = game.get("start_time_utc")
                    if game_time and game_time >= recent_cutoff:
                        processed_games.append(game)
            
            # Use single-pass algorithm for game selection
            # This properly handles games between two favorite teams (counts for both)
            if self.show_favorite_teams_only and self.favorite_teams:
                team_games = self._select_recent_games_for_display(
                    processed_games, self.favorite_teams
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
                # No favourites at all: the next N recent games league-wide.
                team_games = sorted(
                    self._filtered_or_all(processed_games),
                    key=lambda g: g.get("start_time_utc")
                    or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )[:self.recent_games_to_show]
                self.logger.info(
                    "No favorites configured: showing %d total recent games",
                    len(team_games)
                )

            # Odds are fetched for the games that survived selection, same as
            # SportsUpcoming does -- this class never fetched them at all, so
            # the Recent screen drew its "odds if available" without anything
            # ever attaching them, and every final rendered bare. ESPN keeps a
            # completed game's closing line on the same endpoint, so a final
            # is as answerable as an upcoming game. Same fix as
            # football-scoreboard 2.29.3.
            if self.show_odds:
                for game in team_games:
                    self._fetch_odds(game)

            # Check if the list of games to display has changed (protected by lock for thread safety)
            with self._games_lock:
                new_game_ids = {g["id"] for g in team_games}
                current_game_ids = {g["id"] for g in self.games_list}

                if new_game_ids != current_game_ids:
                    self.logger.info(
                        f"Found {len(team_games)} final games within window for display."
                    )  # Changed log prefix
                    self.games_list = team_games
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
                    # List content is same, just update data for current game
                    self.current_game = self.games_list[self.current_game_index]

                if not self.games_list:
                    self.logger.info(
                        "No relevant recent games found to display."
                    )  # Changed log prefix
                    self.current_game = None  # Ensure display clears if no games

        except Exception as e:
            self.logger.error(
                f"Error updating recent games: {e}", exc_info=True
            )  # Changed log prefix
            # Don't clear current game on error, keep showing last known state
            # self.current_game = None # Decide if we want to clear display on error

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the layout for a recently completed NCAA FB game."""  # Updated docstring
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
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
                # Draw placeholder text if logos fail (similar to live). Draw
                # on the image that gets pasted: drawing on a throwaway
                # .convert("RGB") copy and pasting main_img left a black panel.
                error_img = main_img.convert("RGB")
                draw_final = ImageDraw.Draw(error_img)
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image.paste(error_img, (0, 0))
                self.display_manager.update_display()
                return

            center_y = self.display_height // 2

            # MLB-style logo positioning (closer to edges) with layout offsets
            home_x = self.display_width - home_logo.width + 2 + self._get_layout_offset('home_logo', 'x_offset')
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -2 + self._get_layout_offset('away_logo', 'x_offset')
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Draw Text Elements on Overlay
            # Note: Rankings are now handled in the records/rankings section below

            # Final Scores (Centered, same position as live) with layout offsets
            home_score = str(game.get("home_score", "0"))
            away_score = str(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2 + self._get_layout_offset('score', 'x_offset')
            score_y = self.display_height - (6 + self._score_font_size()) + self._get_layout_offset('score', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay,
                score_text,
                (score_x, score_y),
                self.fonts["score"],
                fill=self._recent_score_color(game, self._element_color('score_text')),
            )

            # "Final" text (Top center) with layout offsets
            status_text = game.get(
                "period_text", "Final"
            )  # Use formatted period text (e.g., "Final/OT") or default "Final"
            status_width = draw_overlay.textlength(status_text, font=self.fonts["time"])
            status_x = (self.display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
            status_y = 1 + self._get_layout_offset('status_text', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, status_text, (status_x, status_y), self.fonts["time"]
            )

            # Draw odds if available
            if "odds" in game and game["odds"]:
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height,
                    top_span=self._top_row_span(
                        draw_overlay, status_text, self.fonts["time"],
                        self.display_width,
                        self._get_layout_offset('status_text', 'x_offset')),
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

            self._custom_scorebug_layout(game, draw_overlay)
            # Composite and display
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()  # Update display here

        except Exception as e:
            self.logger.error(
                f"Error displaying recent game: {e}", exc_info=True
            )  # Changed log prefix

    def display(self, force_clear=False) -> bool:
        """
        Display recent games, handling switching.

        Returns True when a game was drawn, False when there was nothing to
        show, so the caller can rotate past an empty mode instead of holding a
        blank panel for its full display duration.
        """
        if not self.is_enabled or not self.games_list:
            # If disabled or no games, clear the display so old content doesn't persist
            if force_clear or not self.games_list:
                self.display_manager.clear()
                self.display_manager.update_display()
            if not self.games_list and self.current_game:
                self.current_game = None  # Clear internal state if list becomes empty
            return False

        # The mode just took the panel: the current card gets its full turn
        # before the dwell check below is allowed to advance.
        if self._reset_dwell_on_reentry():
            force_clear = True

        # Before the dwell check, so a fresh slice is on screen for a full
        # duration rather than for whatever was left of the previous card's.
        if self._rotate_other_games_on_display():
            force_clear = True

        try:
            current_time = time.time()

            # Check if it's time to switch games (protected by lock for thread safety)
            with self._games_lock:
                if (
                    len(self.games_list) > 1
                    and current_time - self.last_game_switch >= self.game_display_duration
                ):
                    self.current_game_index = self._next_switch_index()
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
                self._draw_scorebug_layout(self.current_game, force_clear)
                # update_display() is called within _draw_scorebug_layout
                return True
            return False

        except Exception as e:
            self.logger.error(
                f"Error in display loop: {e}", exc_info=True
            )  # Changed log prefix
            return False


class SportsLive(SportsLiveSharedMixin, SportsCore):
    SKIN_MODE = "live"

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
        try:
            mode_config_keys = list(self.mode_config.keys()) if isinstance(self.mode_config, dict) else "N/A"
            self.logger.info(
                f"SportsLive initialized: live_update_interval={self.update_interval}s, "
                f"no_data_interval={self.no_data_interval}s, "
                f"mode_config keys={mode_config_keys}"
            )
        except Exception as e:
            self.logger.warning(f"Error logging SportsLive initialization: {e}")
        self.last_update = 0
        self.live_games = []
        self._rotation_schedule = []
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
        # Draw the takeover in the scoring team's colours, read off its crest.
        # Off falls back to the navy-and-amber palette.
        self.celebration_team_colors = self.mode_config.get(
            "celebration_team_colors", True
        )
        self.celebration_confetti = self.mode_config.get(
            "celebration_confetti", True
        )
        # Per-game score baselines for goal detection:
        # {game_id: {"away": int, "home": int}}
        self._score_baselines: Dict[str, Dict[str, int]] = {}
        # Active celebration dict (a snapshot, so a win survives the game
        # leaving live_games) or None. See _start_celebration for the shape.
        self.active_celebration: Optional[Dict[str, Any]] = None

    def _is_favorite_game(self, game) -> bool:
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

    def _is_live_game_included(self, home_abbr: str, away_abbr: str) -> bool:
        """Decide whether a live game should be included in the rotation.

        Filtering logic matching SportsUpcoming:
        - Excluded teams are always hidden, regardless of every other setting
        - If show_all_live = True -> show all games
        - If show_favorite_teams_only = False -> show all games
        - If show_favorite_teams_only = True but favorite_teams is empty -> show all games (fallback)
        - If show_favorite_teams_only = True and favorite_teams has teams -> only show games with those teams
        """
        if self.exclude_teams and (
            home_abbr in self.exclude_teams or away_abbr in self.exclude_teams
        ):
            return False
        if self.show_all_live:
            return True
        if not self.show_favorite_teams_only:
            return True
        if not self.favorite_teams:
            return True
        return home_abbr in self.favorite_teams or away_abbr in self.favorite_teams

    def _build_rotation_schedule(self, games: List[Dict]) -> List[str]:
        """Build a Smooth Weighted Round-Robin schedule of game IDs.

        Favorite-team games get `favorite_live_boost` slots per cycle,
        evenly spaced (not clumped); every other live game gets 1 slot.
        When favorite_live_boost == 1 (or no favorite is live) this
        degenerates to a single pass over `games` in order - identical
        to today's plain round robin.
        """
        weights = []
        for g in games:
            is_favorite = bool(self.favorite_teams) and (
                g.get("home_abbr") in self.favorite_teams
                or g.get("away_abbr") in self.favorite_teams
            )
            weights.append((g["id"], self.favorite_live_boost if is_favorite else 1))

        total_weight = sum(w for _, w in weights)
        if not weights or total_weight <= 0:
            return [g["id"] for g in games]

        current_weights = {gid: 0 for gid, _ in weights}
        schedule: List[str] = []
        for _ in range(total_weight):
            best_id, best_current = None, None
            for gid, w in weights:
                current_weights[gid] += w
                if best_current is None or current_weights[gid] > best_current:
                    best_id, best_current = gid, current_weights[gid]
            current_weights[best_id] -= total_weight
            schedule.append(best_id)
        return schedule

    def _is_game_really_over(self, game: Dict) -> bool:
        """Check if a game appears to be over even if API says it's live.

        Hockey: Games end in P3 or OT when clock hits 0:00 (period >= 3).
        """
        game_str = f"{game.get('away_abbr')}@{game.get('home_abbr')}"

        # Check if period_text indicates final
        # ESPN can send the key as null, and .get()'s default only covers a
        # missing key, so a None here crashed the whole live update.
        raw_period_text = game.get("period_text")
        period_text = raw_period_text.lower() if isinstance(raw_period_text, str) else ""
        if "final" in period_text:
            self.logger.debug(
                f"_is_game_really_over({game_str}): "
                f"returning True - 'final' in period_text='{period_text}'"
            )
            return True

        # Check if clock is 0:00 in P3 or OT (period >= 3)
        raw_clock = game.get("clock")
        # Same for a null or non-numeric period: treat it as period 0.
        try:
            period = int(game.get("period") or 0)
        except (TypeError, ValueError, OverflowError):
            period = 0

        # Only check clock-based finish if we have a valid clock string
        if isinstance(raw_clock, str) and raw_clock.strip() and period >= 3:
            clock = raw_clock
            clock_normalized = clock.replace(":", "").strip()
            if clock_normalized in ("000", "00") or clock in ("0:00", ":00"):
                self.logger.debug(
                    f"_is_game_really_over({game_str}): "
                    f"returning True - clock at 0:00 (clock='{clock}', period={period})"
                )
                return True

        self.logger.debug(
            f"_is_game_really_over({game_str}): returning False"
        )
        return False

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

        # Debug logging for interval selection (log every 5 minutes or when interval changes)
        if current_time - self.last_log_time >= 300:  # Log every 5 minutes
            self.logger.info(
                f"Update check: live_games={len(_live_games_attr) if _live_games_attr else 0}, "
                f"update_interval={_update_interval_attr}, no_data_interval={_no_data_interval_attr}, "
                f"selected_interval={interval}, "
                f"time_since_last_update={current_time - self.last_update:.1f}s, "
                f"empty_live_streak={getattr(self, '_empty_live_streak', 0)}"
            )
            self.last_log_time = current_time

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

            if self.test_mode:
                # Simulate clock running down in test mode
                self._test_mode_update()
            else:
                # Fetch live game data
                data = self._fetch_data()
                new_live_games = []
                if data and "events" in data:
                    live_or_halftime_count = 0
                    filtered_out_count = 0
                    
                    for game in data["events"]:
                        details = self._extract_game_details(game)
                        if details:
                            # Filter out final games and games that appear to
                            # be over. A game we were tracking live going final
                            # may earn a win celebration on the way out.
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

                            if not (details["is_live"] or details["is_halftime"]):
                                continue

                            live_or_halftime_count += 1

                            should_include = self._is_live_game_included(
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

                                # Detect goals (per-side score increments) and
                                # arm a celebration when a celebratable team
                                # scores.
                                self._check_for_goal(details)
                                if self.show_odds:
                                    self._fetch_odds(details)
                                new_live_games.append(details)

                    # Detect and remove stale games from persisted list
                    # (new_live_games has fresh last_seen, so stale check must
                    # run against the previous self.live_games)
                    with self._games_lock:
                        self._detect_stale_games(self.live_games)

                    # Log filtering configuration
                    self.logger.info(
                        f"Live game filtering: {len(data['events'])} total events, "
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
                                # Sort with favorites first, then by start time (display order)
                                def sort_key(g):
                                    is_favorite = self.favorite_teams and (g["home_abbr"] in self.favorite_teams or g["away_abbr"] in self.favorite_teams)
                                    start_time = g.get("start_time_utc") or datetime.now(timezone.utc)
                                    # Favorites first (0), non-favorites second (1), then by start time
                                    return (0 if is_favorite else 1, start_time)

                                self.live_games = sorted(new_live_games, key=sort_key)
                                # Weighted rotation order (favorite gets favorite_live_boost
                                # slots per cycle, evenly spaced) - what current_game_index
                                # actually cycles through.
                                self._rotation_schedule = self._build_rotation_schedule(
                                    self.live_games
                                )
                                # Reset index if current game is gone or list is new
                                if (
                                    not self.current_game
                                    or self.current_game["id"] not in new_game_ids
                                ):
                                    self.current_game_index = 0
                                    game_by_id = {g["id"]: g for g in self.live_games}
                                    first_id = (
                                        self._rotation_schedule[0]
                                        if self._rotation_schedule
                                        else None
                                    )
                                    self.current_game = game_by_id.get(first_id)
                                    self.last_game_switch = current_time
                                else:
                                    # Find current game's new index in the schedule if it still exists
                                    try:
                                        self.current_game_index = self._rotation_schedule.index(
                                            self.current_game["id"]
                                        )
                                        game_by_id = {g["id"]: g for g in self.live_games}
                                        self.current_game = game_by_id[
                                            self.current_game["id"]
                                        ]  # Update current_game with fresh data
                                    except (
                                        ValueError,
                                        KeyError,
                                    ):  # Should not happen if check above passed, but safety first
                                        self.current_game_index = 0
                                        game_by_id = {g["id"]: g for g in self.live_games}
                                        first_id = (
                                            self._rotation_schedule[0]
                                            if self._rotation_schedule
                                            else None
                                        )
                                        self.current_game = game_by_id.get(first_id)
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
                            self._rotation_schedule = []
                            self.current_game = None
                            self.current_game_index = 0

                        # Prune game_update_timestamps for games no longer tracked
                        active_ids = {g["id"] for g in self.live_games}
                        self.game_update_timestamps = {
                            gid: ts for gid, ts in self.game_update_timestamps.items()
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
            phrase = secrets.choice(("GOAL!", f"{team_abbr} GOAL!"))

        self.active_celebration = {
            "kind": kind,
            # The net is hockey's scenery. _draw_celebration_motif ships the
            # same set in every lineage so the renderer stays identical across
            # them; which one a sport reaches for is the part that differs.
            "motif": "win" if kind == "win" else "net",
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
        # (a game already in progress at boot would false-fire otherwise),
        # and a decrement -- a goal waved off after review, which hockey does
        # more than most -- just re-bases silently.
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
        # for the first time already-final (the board started after the final
        # horn) has no baseline and must not fire.
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
            # A regular-season game cannot end level, but the feed can show a
            # tie mid-transition before the shootout winner lands. Waiting for
            # a decided score costs nothing; celebrating a tie would be wrong.
            return

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

    # ------------------------------------------------------------------
    # Celebration palette
    #
    # The takeover is drawn in the scoring team's own colours, taken from the
    # pixels of its crest.
    #
    # ESPN does serve team.color / team.alternateColor, but only inside
    # _extract_game_details_common -- a function all eleven scoreboard
    # lineages share byte-for-byte (scripts/check_sports_drift.py), so
    # reading it there would drag every one of them into this change. The
    # crest is already downloaded, decoded and sitting in _logo_cache by the
    # time a celebration draws, so the colours come from it instead: no extra
    # request, no per-league colour table to maintain, and it works for any
    # team ESPN can name -- including the FCS opponents no table would list.
    #
    # Checked against ESPN's own values for all 32 NFL clubs: the crest's
    # dominant colour matches the official primary or alternate for 30 of
    # them, and where it differs it differs usefully. Pittsburgh's official
    # primary is #000000 and Denver's is near-black navy; the crest yields
    # gold and orange, which are what actually read on an LED panel.
    # ------------------------------------------------------------------

    #: Used when the crest yields nothing (no logo on disk yet, or the grey
    #: placeholder a failed download leaves) or team colours are switched
    #: off -- the navy and amber the celebration wore before it had a palette.
    _DEFAULT_CELEBRATION_PALETTE: ClassVar[Dict[str, Tuple[int, int, int]]] = {
        "deep": (10, 10, 40),
        "glow": (30, 30, 86),
        "headline": (255, 208, 56),
        "accent": (255, 255, 255),
    }

    def _celebration_palette(self, celebration: Dict) -> Dict[str, Tuple[int, int, int]]:
        """The scoring team's colours, derived once per celebration."""
        cached = celebration.get("_palette")
        if cached is not None:
            return cached

        palette = dict(self._DEFAULT_CELEBRATION_PALETTE)
        if getattr(self, "celebration_team_colors", True):
            try:
                game = celebration["game"]
                side = celebration.get("scored_side") or "home"
                logo = self._load_and_resize_logo(
                    game.get("%s_id" % side),
                    game.get("%s_abbr" % side),
                    game.get("%s_logo_path" % side),
                    game.get("%s_logo_url" % side),
                )
                derived = _logo_palette(logo) if logo is not None else None
                if derived:
                    palette = derived
            except Exception as e:  # noqa: BLE001 - never lose a takeover to a crest
                self.logger.debug(f"Celebration palette fell back to the default: {e}")

        celebration["_palette"] = palette
        return palette

    # ------------------------------------------------------------------
    # Celebration choreography
    #
    # Every frame is a finished card. The beats below shift the emphasis --
    # an opening colour hit, confetti, a breathing score -- but none of them
    # leaves the panel mid-wipe, because on a switch-mode board the core
    # drives this plugin at 1 FPS (LEDMatrix display_controller reserves its
    # high-FPS loop for plugins that scroll or declare needs_high_fps), so
    # any single frame may be the only one a viewer ever sees of it.
    # ------------------------------------------------------------------

    #: Fraction of the celebration spent on the opening colour hit.
    _CELEBRATION_IMPACT: ClassVar[float] = 0.11
    #: Fraction of it after which the takeover eases back down.
    _CELEBRATION_SETTLE: ClassVar[float] = 0.80
    #: Seconds per breath of the scoring side's digits. Deliberately a
    #: continuous sine rather than an on/off toggle: the 4 Hz flash this
    #: replaced was sampled once a second on a switch-mode board, which
    #: aliases into a colour that changes at random. A ramp degrades into a
    #: slow glow instead, and still reads as a pulse at 125 FPS.
    _CELEBRATION_BREATH_SECONDS: ClassVar[float] = 1.7

    def _celebration_backdrop(
        self,
        celebration: Dict,
        width: int,
        height: int,
        palette: Dict[str, Tuple[int, int, int]],
    ) -> Image.Image:
        """The static half of the takeover: a team-colour gradient with the
        scenery for this kind of score painted into it.

        Built once per celebration per panel size and copied per frame, so the
        per-pixel work never lands on the render path.
        """
        cached = celebration.get("_backdrop")
        if cached is not None and cached[0] == (width, height):
            return cached[1]

        # One column, then stretched: filling the panel pixel by pixel would
        # be `width` times the work for the same image.
        column = Image.new("RGB", (1, max(height, 1)))
        pixels = column.load()
        for y in range(height):
            k = y / max(height - 1, 1)
            pixels[0, y] = _mix_color(palette["deep"], (0, 0, 0), 0.18 + 0.82 * k)
        backdrop = column.resize((width, height)).convert("RGBA")

        try:
            self._draw_celebration_motif(
                ImageDraw.Draw(backdrop),
                celebration.get("motif") or "score",
                width,
                height,
                palette,
            )
        except Exception as e:  # noqa: BLE001 - scenery is never worth a blank panel
            self.logger.debug(f"Celebration motif skipped: {e}")

        celebration["_backdrop"] = ((width, height), backdrop)
        return backdrop

    def _draw_celebration_motif(
        self,
        draw,
        motif: str,
        width: int,
        height: int,
        palette: Dict[str, Tuple[int, int, int]],
    ) -> None:
        """Paint the scenery for one kind of score, dim enough to stay behind
        the headline and the score instead of competing with them."""
        glow = palette["glow"]
        if motif == "kick":
            # The uprights a field goal or an extra point went through,
            # spread wide enough to frame the score rather than sit beside it.
            half = max(8, min(width // 3, height))
            mid = width // 2
            crossbar = int(height * 0.60)
            draw.line([(mid - half, int(height * 0.08)), (mid - half, crossbar)], fill=glow)
            draw.line([(mid + half, int(height * 0.08)), (mid + half, crossbar)], fill=glow)
            draw.line([(mid - half, crossbar), (mid + half, crossbar)], fill=glow)
            draw.line([(mid, crossbar), (mid, height - 1)], fill=glow)
        elif motif == "touchdown":
            # The goal line, with its hash marks.
            line_y = int(height * 0.36)
            draw.line([(0, line_y), (width, line_y)], fill=glow)
            for x in range(3, width, 9):
                draw.line([(x, line_y - 2), (x, line_y + 2)], fill=glow)
        elif motif == "net":
            # The goal a puck just went into: frame, posts and mesh, sized to
            # frame the score the way the uprights do.
            half = max(7, min(width // 4, height))
            mid = width // 2
            top = int(height * 0.34)
            draw.rectangle([(mid - half, top), (mid + half, height - 1)], outline=glow)
            step = max(3, (half * 2) // 6)
            for x in range(mid - half + step, mid + half, step):
                draw.line([(x, top + 1), (x, height - 2)], fill=glow)
            for y in range(top + step, height - 1, step):
                draw.line([(mid - half + 1, y), (mid + half - 1, y)], fill=glow)
        elif motif == "win":
            # A sunburst behind the winner.
            cx, cy = width // 2, height // 2
            reach = max(width, height)
            for i in range(10):
                angle = (math.pi * 2 * i / 10) + math.pi / 20
                draw.line(
                    [
                        (cx, cy),
                        (cx + math.cos(angle) * reach, cy + math.sin(angle) * reach),
                    ],
                    fill=glow,
                )
        else:
            for x in range(-height, width + height, 11):
                draw.line([(x, height), (x + height, 0)], fill=glow)

    def _celebration_confetti(
        self,
        celebration: Dict,
        width: int,
        height: int,
        palette: Dict[str, Tuple[int, int, int]],
    ) -> List[Tuple[float, float, float, float, int, Tuple[int, int, int]]]:
        """Seed the confetti once per celebration.

        Seeded from the game rather than the clock, so the same score always
        produces the same fall -- which is what lets a golden screen lock the
        effect down instead of having to tolerate it.
        """
        cached = celebration.get("_confetti")
        if cached is not None and cached[0] == (width, height):
            return cached[1]

        # Sparse on purpose. At one flake per 170 square pixels a 128x32
        # panel carried 24 single-pixel specks over the headline and the
        # score, which reads as a dead-pixel problem rather than as confetti.
        count = max(6, min(22, (width * height) // 260))
        seed = "%s/%s" % (
            (celebration.get("game") or {}).get("id", "?"),
            celebration.get("phrase", ""),
        )
        rng = random.Random(seed)
        # Team colours, plus a pale tint of the headline rather than a flat
        # white, so the fall still belongs to the team that scored.
        colors = [
            palette["headline"],
            palette["accent"],
            _mix_color(palette["headline"], (255, 255, 255), 0.55),
        ]
        flakes = [
            (
                float(rng.randrange(max(width, 1))),  # column
                rng.uniform(0.0, float(height)),      # start height
                rng.uniform(0.40, 1.15),              # fall speed
                rng.uniform(0.0, math.pi * 2),        # sway phase
                2 if rng.random() < 0.6 else 1,       # size in pixels
                colors[rng.randrange(len(colors))],
            )
            for _ in range(count)
        ]
        celebration["_confetti"] = ((width, height), flakes)
        return flakes

    def _draw_celebration_confetti(
        self,
        draw,
        celebration: Dict,
        width: int,
        height: int,
        palette: Dict[str, Tuple[int, int, int]],
        elapsed: float,
        progress: float,
    ) -> None:
        """Draw the confetti for this instant, thinning it out as the
        celebration eases back towards the scorebug."""
        flakes = self._celebration_confetti(celebration, width, height, palette)
        fade = 1.0
        if progress > self._CELEBRATION_SETTLE:
            fade = max(
                0.0,
                1.0
                - (progress - self._CELEBRATION_SETTLE)
                / (1.0 - self._CELEBRATION_SETTLE),
            )
        if fade <= 0.02:
            return
        alpha = int(235 * fade)
        for column, start, speed, phase, size, color in flakes:
            y = (start + speed * elapsed * height * 0.42) % (height + 4) - 2
            x = column + math.sin(elapsed * 2.1 + phase) * 2.4
            draw.rectangle(
                [(int(x), int(y)), (int(x) + size - 1, int(y) + size - 1)],
                fill=tuple(color) + (alpha,),
            )

    def _celebration_crests(
        self, celebration: Dict, height: int
    ) -> Dict[str, Optional[Image.Image]]:
        """The two crests for the takeover, with the side that did not score
        dimmed so the scoring team reads at a glance."""
        cached = celebration.get("_crests")
        if cached is not None and cached[0] == height:
            return cached[1]

        game = celebration["game"]
        scored = celebration.get("scored_side")
        crests: Dict[str, Optional[Image.Image]] = {}
        for side in ("away", "home"):
            logo = None
            try:
                logo = self._load_and_resize_logo(
                    game.get("%s_id" % side),
                    game.get("%s_abbr" % side),
                    game.get("%s_logo_path" % side),
                    game.get("%s_logo_url" % side),
                )
            except Exception as e:  # noqa: BLE001 - a crest is never worth the panel
                self.logger.debug(f"Celebration logo load failed: {e}")
            if logo is not None and side != scored:
                logo = _dim_rgba(logo, 0.40)
            crests[side] = logo

        celebration["_crests"] = (height, crests)
        return crests

    def _draw_celebration_layout(self, celebration: Dict, force_clear: bool = False) -> None:
        """Render the full-screen score/win takeover."""
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

        elapsed = max(0.0, time.time() - celebration["started_at"])
        # getattr throughout the render path: the golden-screen tests build a
        # live manager through __new__ and set only what they draw with, and a
        # celebration must never be lost to a missing knob.
        duration = max(float(getattr(self, "celebration_duration", 8) or 8), 0.5)
        progress = min(elapsed / duration, 1.0)
        palette = self._celebration_palette(celebration)

        main_img = self._celebration_backdrop(
            celebration, display_width, display_height, palette
        ).copy()

        # Crests at the edges, bleeding off as the scorebug's do.
        crests = self._celebration_crests(celebration, display_height)
        center_y = display_height // 2
        home_logo, away_logo = crests.get("home"), crests.get("away")
        if home_logo is not None:
            main_img.paste(
                home_logo,
                (display_width - home_logo.width + 2, center_y - home_logo.height // 2),
                home_logo,
            )
        if away_logo is not None:
            main_img.paste(away_logo, (-2, center_y - away_logo.height // 2), away_logo)

        # The opening hit: the team's headline colour washes the panel and
        # decays out of it. Held below opaque so the outlined text drawn on
        # top still reads in whichever frame happens to catch it.
        impact = max(0.0, 1.0 - progress / self._CELEBRATION_IMPACT)
        if impact > 0.0:
            # Scaled by how colourful the team is. A saturated crest gets the
            # full hit; a silver one -- the Raiders, or the grey placeholder a
            # failed logo download leaves -- would otherwise wash the whole
            # panel out to the same flat grey as its own headline colour.
            punch = 0.45 + 0.55 * _rgb_saturation(palette["headline"])
            alpha = int(140 * punch * (impact ** 1.5))
            if alpha > 0:
                main_img = Image.alpha_composite(
                    main_img,
                    Image.new(
                        "RGBA",
                        (display_width, display_height),
                        tuple(palette["headline"]) + (alpha,),
                    ),
                )

        overlay = Image.new("RGBA", (display_width, display_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        if getattr(self, "celebration_confetti", True):
            try:
                self._draw_celebration_confetti(
                    draw,
                    celebration,
                    display_width,
                    display_height,
                    palette,
                    elapsed,
                    progress,
                )
            except Exception as e:  # noqa: BLE001
                self.logger.debug(f"Celebration confetti skipped: {e}")

        # Headline across the top, shrunk to fit the panel width, struck
        # white on the opening hit and settling into the team's colour.
        phrase = celebration["phrase"]
        phrase_font = self._fit_font(
            draw, phrase, display_width, [self.fonts["time"], self.fonts["status"]]
        )
        phrase_width = draw.textlength(phrase, font=phrase_font)
        # Eased in by colour rather than by position. Sliding it down into
        # place put the first frame at y=-3 with its top row cut off, and on a
        # 1 FPS board that clipped frame can be the only one anyone sees.
        self._draw_text_with_outline(
            draw,
            phrase,
            ((display_width - phrase_width) // 2, 1),
            phrase_font,
            fill=_mix_color(palette["headline"], (255, 255, 255), impact),
        )

        # Score centred low, the scoring side's digits breathing in the team's
        # headline colour so the change reads at a glance.
        away_text = str(celebration["away_score"])
        home_text = str(celebration["home_score"])
        score_font = self.fonts["score"]
        segments = [
            (away_text, celebration["scored_side"] == "away"),
            ("-", False),
            (home_text, celebration["scored_side"] == "home"),
        ]
        total_width = sum(draw.textlength(seg, font=score_font) for seg, _ in segments)
        breath = 0.72 + 0.28 * (
            0.5
            + 0.5 * math.sin(2 * math.pi * elapsed / self._CELEBRATION_BREATH_SECONDS)
        )
        highlight = _scale_color(palette["headline"], breath)
        x = (display_width - total_width) // 2
        # display_height - 14 was sized for the old fixed 8px score. #338
        # scales the score with the panel (16px at 48 and 64 tall), which put
        # the bottom of the digits off the panel. Lift it by the measured ink
        # (+1 for the outline stroke) only when it would clip, so panels where
        # it always fitted render exactly as before.
        score_text = "".join(seg for seg, _ in segments)
        ink_bottom = draw.textbbox((0, 0), score_text, font=score_font)[3]
        y = min(display_height - 14, display_height - ink_bottom - 2)
        for seg, is_highlight in segments:
            color = highlight if is_highlight else (216, 216, 216)
            self._draw_text_with_outline(draw, seg, (int(x), y), score_font, fill=color)
            x += draw.textlength(seg, font=score_font)

        main_img = Image.alpha_composite(main_img, overlay).convert("RGB")
        self.display_manager.image = main_img
        self.display_manager.update_display()

    def display(self, force_clear: bool = False) -> bool:
        """Render an active celebration as a full-screen takeover; otherwise
        advance the live rotation and render as usual.

        This class has no scorebug of its own; the rotation has to be driven
        from the display path rather than update(), so the override exists to
        do that and delegate.
        """
        if not self.is_enabled:
            return False
        # Same re-entry rule as the other screens: retaking the panel gives
        # the current game a full dwell instead of an instant advance. The
        # advance itself lives in _advance_live_game_if_due, so the reset has
        # to land first.
        self._reset_dwell_on_reentry()
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
                # Reset the dwell so the scorebug resumes on the scoring or
                # winning game for a full duration before rotation moves on.
                self.last_game_switch = time.time()
        # After the celebration branch: a celebration owns the screen, and
        # rotating out of it would undo the dwell reset just above, which
        # exists to give the scoring game its full turn.
        self._advance_live_game_if_due()
        return super().display(force_clear)


            # Handle game switching (protected by lock for thread safety)
            # Fix: Don't check for switching if last_game_switch is still 0 (games haven't been loaded yet)
            # This prevents immediate switching when the system has been running for a while before games load
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
                not self.test_mode
                and len(self._rotation_schedule) > 1
                and self.last_game_switch > 0
                and (current_time - self.last_game_switch)
                >= self._effective_live_duration(self.current_game)
            ):
                self.current_game_index = (self.current_game_index + 1) % len(
                    self._rotation_schedule
                )
                next_id = self._rotation_schedule[self.current_game_index]
                game_by_id = {g["id"]: g for g in self.live_games}
                self.current_game = game_by_id.get(next_id, self.current_game)
                self.last_game_switch = current_time
                self.logger.info(
                    f"Switched live view to: {self.current_game['away_abbr']}@{self.current_game['home_abbr']}"
                )  # Changed log prefix

                    # Force display update via flag or direct call if needed, but usually let main loop handle
