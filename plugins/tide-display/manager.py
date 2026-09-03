"""
Tide Display Plugin for LEDMatrix

Four auto-rotating modes across all matrix sizes (64×32 → 256×64):

  1. current  — Full-display animated water background + tide stats overlaid
  2. schedule — Today's H/L schedule in columns with colour-coded tints
  3. chart    — 24-hour filled tide curve with glow + grid + current marker
  4. stats    — Moon phase icon, spring/neap, tidal range + mini tide gauge

Data: NOAA Tides & Currents API (free, no API key, US stations).
Find your station: tidesandcurrents.noaa.gov/stations.html
"""

import math, os, time, logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

NOAA_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

_KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14)
_LUNAR_PERIOD   = 29.53058867

# ── Colour palette ─────────────────────────────────────────────────────────────
C_BG          = (  0,   0,   5)
C_SKY         = (  0,   2,  12)
C_SKY_HORIZON = (  0,  20,  65)  # indigo at horizon — sky and water share this anchor
C_WATER_TOP   = (  0,  30,  90)  # water at surface — matches horizon so no hard edge
C_WATER_DEEP  = (  0,  40, 120)
C_WATER_MID   = (  0,  65, 160)
C_WATER_LIGHT = (  0, 120, 210)
C_WAVE1       = (  0, 140, 220)  # main wave body — rich blue-cyan (not jarring full cyan)
C_WAVE_CREST  = (160, 240, 255)  # sparkle dots at wave peaks only
C_WAVE2       = (  0,  90, 175)  # secondary wave (subtle)
C_CHART_FILL  = (  0,  45, 130)
C_CHART_LINE  = (  0, 215, 255)
C_CHART_GLOW1 = (  0, 110, 185)
C_CHART_GLOW2 = (  0,  65, 135)
C_GRID        = ( 30,  48,  96)
C_NOW_LINE    = (255, 220,  40)
C_HIGH        = (255, 195,  45)
C_LOW         = ( 75, 190, 255)
C_RISING      = ( 45, 230,  95)
C_FALLING     = (255,  75,  75)
C_SLACK       = (255, 210,  60)
C_TEXT        = (205, 225, 255)
C_LABEL       = (120, 150, 200)
C_DIM         = ( 75,  90, 120)
C_MOON        = (245, 238, 200)
C_BAR_OUT     = ( 45,  72, 130)
# Schedule column backgrounds — tinted toward their label colour (12% / 22%)
C_COL_HIGH      = ( 31,  23,  10)  # dark amber  (C_HIGH at 12%)
C_COL_LOW       = (  9,  23,  36)  # dark blue   (C_LOW  at 12%)
C_COL_HIGH_NEXT = ( 56,  43,  15)  # amber       (C_HIGH at 22%)
C_COL_LOW_NEXT  = ( 16,  42,  61)  # blue        (C_LOW  at 22%)


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * max(0.0, min(1.0, t))) for a, b in zip(c1, c2))

def _safe_iso(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


# ── Layout helper ──────────────────────────────────────────────────────────────

def _layout(dw: int, dh: int) -> Dict:
    c_ml, c_mr, c_mt = 3, 3, 1
    c_axis = max(9, int(dh * 0.20))  # needs 9px min: 1px line + 2px gap + 6px font
    row1 = 1
    row2 = max(9,  int(dh * 0.28))
    row3 = max(18, int(dh * 0.55))
    row4 = max(27, int(dh * 0.78))
    wave_amp = max(2, min(5, dh // 10))
    return dict(
        c_x=c_ml, c_y=c_mt,
        c_w=dw - c_ml - c_mr,
        c_h=dh - c_axis - c_mt - 1,
        c_axis=c_axis,
        wave_amp=wave_amp,
        row1=row1, row2=row2, row3=row3, row4=row4,
        half=dw // 2,
        small=(dw <= 64), medium=(64 < dw <= 128), large=(dw > 128),
    )


# ── Plugin ──────────────────────────────────────────────────────────────────────

class TidePlugin(BasePlugin):
    MODES = ['current', 'schedule', 'chart', 'stats']

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        def _rgb(k, d):
            try:
                return tuple(max(0, min(255, int(c))) for c in config.get(k, list(d)))
            except (TypeError, ValueError):
                return d

        self.station_id   = str(config.get('station_id', '')).strip()
        self.station_name = str(config.get('station_name', '') or '').strip()
        self.units        = config.get('units', 'imperial')
        self.mode_dur     = float(config.get('display_duration', 12))
        self.show_moon    = bool(config.get('show_moon_phase', True))
        self.tide_color   = _rgb('tide_color',      C_WATER_MID)
        self.hi_color     = _rgb('highlight_color', C_WAVE1)

        # Per-element text styling from the optional `customization` block.
        self._font_cache: Dict[Tuple[str, int], Optional[ImageFont.FreeTypeFont]] = {}
        self._apply_customization(config)

        self.show_mode    = {
            'current':  bool(config.get('show_current',  True)),
            'schedule': bool(config.get('show_schedule', True)),
            'chart':    bool(config.get('show_chart',    True)),
            'stats':    bool(config.get('show_stats',    True)),
        }
        self.modes = self._build_enabled_modes()

        self.mode_idx   = 0
        self.mode_start = time.time()
        self.wave_phase = 0.0

        self.hilo:   List[Dict]      = []
        self.hourly: List[float]     = []
        self.live:   Optional[float] = None

    # ── Customization (per-element text styling) ───────────────────────────────

    # Default element face — exactly the display manager's extra-small font
    # (assets/fonts/4x6-font.ttf @ 6), which is what every element used before
    # customization existed. The schema defaults mirror this.
    _DEF_ELEMENT_FONT = ('4x6-font.ttf', 6)

    def _apply_customization(self, config: Dict) -> None:
        """Parse the optional `customization` block.

        Defaults mirror the hardcoded rendering (extra-small font, C_TEXT /
        C_LABEL colours), so a missing block — or one merely filled in with
        schema defaults by the web UI — renders byte-identically.
        """
        def _crgb(value, default):
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                return default
            try:
                return tuple(max(0, min(255, int(c))) for c in value)
            except (TypeError, ValueError):
                return default

        cust      = config.get('customization', {}) or {}
        text_cfg  = cust.get('tide_text', {})  or {}
        label_cfg = cust.get('label_text', {}) or {}
        self.text_color  = _crgb(text_cfg.get('text_color'),  C_TEXT)
        self.label_color = _crgb(label_cfg.get('text_color'), C_LABEL)
        self.text_font   = self._load_element_font(text_cfg)
        self.label_font  = self._load_element_font(label_cfg)

    def _load_element_font(self, element_cfg: Dict):
        """Resolve an element's configured font, or None for the default.

        The schema default (4x6-font.ttf @ 6) is exactly the display manager's
        extra-small font, so a default or merged-defaults config returns None
        and rendering is unchanged. Only a genuine non-default selection loads
        a custom face; load failures fall back to None with a warning.
        """
        name = element_cfg.get('font', self._DEF_ELEMENT_FONT[0])
        try:
            size = int(element_cfg.get('font_size', self._DEF_ELEMENT_FONT[1]))
        except (TypeError, ValueError):
            size = self._DEF_ELEMENT_FONT[1]
        if (name, size) == self._DEF_ELEMENT_FONT:
            return None
        key = (name, size)
        if key not in self._font_cache:
            font = None
            candidates = [
                os.path.join('assets', 'fonts', name),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', name),
            ]
            # Resolve against the core install the display manager was loaded
            # from too, so custom fonts work when the process cwd is not the
            # core root (e.g. the CI safety harness).
            try:
                import inspect
                module_path = os.path.abspath(inspect.getfile(type(self.display_manager)))
                d = os.path.dirname(module_path)
                while True:
                    candidates.append(os.path.join(d, 'assets', 'fonts', name))
                    parent = os.path.dirname(d)
                    if parent == d:
                        break
                    d = parent
            except (OSError, TypeError) as exc:
                self.logger.debug("Module-relative font resolution failed: %s", exc)
            for path in candidates:
                if not os.path.exists(path):
                    continue
                try:
                    # FreeType handles .ttf and (at its native size) .bdf faces.
                    font = ImageFont.truetype(path, size)
                    break
                except Exception as e:
                    # A .bdf exists at exactly one pixel size and FreeType
                    # rejects any other. That made the picker's behaviour depend
                    # on font_size by coincidence: 4x6.bdf loaded because its
                    # native 6 happens to match the default, while 5x7.bdf
                    # silently fell back to the default face. Retry at the size
                    # the file declares.
                    native = self._bdf_pixel_size(path)
                    if native is not None and native != size:
                        try:
                            font = ImageFont.truetype(path, native)
                            self.logger.debug(
                                "Loaded bitmap font %s at its native size %d "
                                "(requested %d)", name, native, size)
                            break
                        except Exception:
                            pass
                    self.logger.warning("Could not load font %s@%d: %s", name, size, e)
            if font is None and not any(os.path.exists(p) for p in candidates):
                self.logger.warning("Font file not found: %s; using default font", name)
            self._font_cache[key] = font
        return self._font_cache[key]

    @staticmethod
    def _bdf_pixel_size(path):
        """The pixel size a .bdf font declares, or None if it does not."""
        try:
            with open(path, "r", encoding="latin-1") as handle:
                for line in handle:
                    if line.startswith("PIXEL_SIZE"):
                        return int(line.split()[1])
                    if line.startswith("CHARS"):
                        break  # past the header
        except (OSError, ValueError, IndexError):
            return None
        return None

    def _element_style(self, color, small: bool):
        """Map a draw call's palette colour to its customization element.

        Call sites pass the module palette constants: C_TEXT-coloured text is
        the 'tide_text' element, C_LABEL-coloured text is 'label_text'. Any
        other colour (state colours like C_HIGH/C_RISING, dimmed variants, …)
        keeps its semantic colour and uses the tide_text font. Returns the
        resolved (color, font) pair.
        """
        is_label = (color == C_LABEL)
        if color == C_TEXT:
            color = self.text_color
        elif is_label:
            color = self.label_color
        font = (self.label_font if is_label else self.text_font) if small else None
        if font is None:
            font = (self.display_manager.extra_small_font if small
                    else self.display_manager.small_font)
        return color, font

    def _tw(self, text: str, label: bool = False) -> int:
        """Pixel width of `text` in its element's active font.

        Uses the historical 4px-per-char estimate when no custom font is set
        (so default layout is byte-identical), and measures the actual font
        otherwise — measurement always matches the face used to draw.
        """
        font = self.label_font if label else self.text_font
        if font is None:
            return len(text) * 4
        try:
            return int(self.display_manager.get_text_width(text, font))
        except Exception:
            # Keep measurement tied to the face that will be drawn: fall back
            # to the font's own metrics before the 4px/char estimate, so a
            # custom font never draws wider than the width we reported.
            try:
                bbox = font.getbbox(text)
                return int(bbox[2] - bbox[0])
            except Exception:
                return len(text) * 4

    # ── BasePlugin ──────────────────────────────────────────────────────────────

    def _build_enabled_modes(self) -> List[str]:
        """Modes the user has toggled on, in MODES order. Falls back to all
        modes if the user disables every screen, so the plugin never goes dark."""
        modes = [m for m in self.MODES if self.show_mode.get(m, True)]
        return modes or list(self.MODES)

    # Serve tide predictions this many days stale (max) when NOAA is unreachable,
    # rather than falling back to the "Loading" screen. Beyond this we'd be showing
    # confidently-wrong times (tides shift ~50 min/day), so a placeholder is safer.
    STALE_MAX_DAYS = 2

    def update(self):
        if not self.station_id: return
        self._prune_legacy_daily_keys()
        today   = date.today().strftime('%Y%m%d')
        u       = 'english' if self.units == 'imperial' else 'metric'

        # Stable, station-scoped keys (no date suffix) so each overwrites in place
        # instead of leaking one cache entry per day. The date the data is *for* is
        # stored inside the payload and drives the daily refresh.
        hilo_key    = f"{self.plugin_id}:hilo:{self.station_id}"
        hourly_key  = f"{self.plugin_id}:hourly:{self.station_id}"
        live_key    = f"{self.plugin_id}:live:{self.station_id}"

        self.hilo   = self._load_daily(hilo_key,   today, 'hilo',   self._fetch_hilo,   u) or []
        self.hourly = self._load_daily(hourly_key, today, 'hourly', self._fetch_hourly, u) or []

        lv = self.cache_manager.get(live_key, max_age=360)
        if lv is None: lv = self._fetch_live(u)
        if lv is not None: self.cache_manager.set(live_key, lv)
        self.live = lv

    def _load_daily(self, key, today, label, fetch, u):
        """Cache-first daily fetch under a *stable* key.

        Refetches when the cached entry is for a different day. On fetch failure,
        falls back to the last-good cached data (even if it is for a prior day,
        up to STALE_MAX_DAYS old) so the screen keeps showing tides instead of a
        perpetual 'Loading' during a transient NOAA outage.
        """
        cached = self.cache_manager.get(key)  # any age
        if isinstance(cached, dict) and cached.get('date') == today and cached.get('data'):
            return cached['data']

        fresh = fetch(u)
        if fresh:
            self.cache_manager.set(key, {'date': today, 'data': fresh})
            return fresh

        # Fetch failed (network error or NOAA error payload) — serve recent stale data.
        if isinstance(cached, dict) and cached.get('data'):
            age = self._days_old(cached.get('date'))
            if age <= self.STALE_MAX_DAYS:
                self.logger.warning("%s: NOAA fetch failed; serving cache from %s (%dd old)",
                                    label, cached.get('date'), age)
                return cached['data']
            self.logger.warning("%s: NOAA fetch failed and cached data is stale (%s, %dd old)",
                                label, cached.get('date'), age)
        return None

    @staticmethod
    def _days_old(d):
        try:
            return (date.today() - datetime.strptime(str(d), '%Y%m%d').date()).days
        except (TypeError, ValueError):
            return 999

    def _cache_delete(self, key):
        """Best-effort cache delete tolerant of core cache-manager API differences."""
        for m in ('delete', 'clear_cache'):
            fn = getattr(self.cache_manager, m, None)
            if callable(fn):
                try:
                    fn(key)
                except Exception as _e:
                    self.logger.debug("cache delete %s failed: %s", key, _e)
                return

    def _prune_legacy_daily_keys(self):
        """One-time cleanup of the pre-1.1.3 date-stamped cache keys that leaked one
        entry per day. Best-effort and idempotent; safe no-op if the cache manager
        exposes no delete method."""
        if getattr(self, '_pruned_legacy', False): return
        self._pruned_legacy = True
        today = date.today()
        for n in range(0, 45):
            d = (today - timedelta(days=n)).strftime('%Y%m%d')
            self._cache_delete(f"{self.plugin_id}:hilo:{self.station_id}:{d}")
            self._cache_delete(f"{self.plugin_id}:hourly:{self.station_id}:{d}")

    def display(self, force_clear=False):
        dw = self.display_manager.matrix.width
        dh = self.display_manager.matrix.height
        canvas = Image.new('RGB', (dw, dh), C_BG)
        # Assign before rendering so _txt() → draw_text() writes to this canvas.
        self.display_manager.image = canvas
        self.display_manager.draw  = ImageDraw.Draw(self.display_manager.image)
        draw = self.display_manager.draw
        L    = _layout(dw, dh)

        if not self.station_id:
            self._no_station(draw, dw, dh, L)
        elif not self.hilo:
            self._loading(draw, dw, dh, L)
        else:
            m = self.modes[self.mode_idx % len(self.modes)]
            if   m == 'current':  self._mode_current(canvas, draw, dw, dh, L)
            elif m == 'schedule': self._mode_schedule(draw, dw, dh, L)
            elif m == 'chart':    self._mode_chart(canvas, draw, dw, dh, L)
            else:                 self._mode_stats(draw, dw, dh, L)

        self.display_manager.update_display()
        self.wave_phase = (self.wave_phase + 1.5) % 360

    def supports_dynamic_duration(self): return True
    def get_display_duration(self):      return self.mode_dur
    def reset_cycle_state(self):         self.mode_start = time.time()

    def is_cycle_complete(self):
        if time.time() - self.mode_start >= self.mode_dur:
            self.mode_idx   = (self.mode_idx + 1) % len(self.modes)
            self.mode_start = time.time()
            return True
        return False

    # ── NOAA ────────────────────────────────────────────────────────────────────

    def _base(self, u):
        return {'format':'json','units':u,'time_zone':'lst_ldt','datum':'MLLW','station':self.station_id}

    def _fetch_hilo(self, u):
        try:
            p  = {**self._base(u), 'product':'predictions','date':'today','interval':'hilo'}
            r  = requests.get(NOAA_BASE, params=p, timeout=10); r.raise_for_status()
            d  = r.json()
            if 'error' in d:
                self.logger.warning("hilo: NOAA API error for station %s: %s",
                                    self.station_id, d.get('error'))
                return None
            out = []
            for x in d.get('predictions', []):
                try:
                    out.append({'dt': datetime.strptime(x['t'], '%Y-%m-%d %H:%M').isoformat(),
                                'height': float(x['v']), 'type': x.get('type', '?')})
                except (KeyError, TypeError, ValueError) as _e:
                    self.logger.debug("hilo entry skip: %s", _e)
            return out or None
        except (requests.exceptions.RequestException, OSError, ValueError) as e:
            self.logger.error("hilo: %s", e, exc_info=True)
            return None

    def _fetch_hourly(self, u):
        try:
            t  = date.today().strftime('%Y%m%d')
            p  = {**self._base(u),'product':'predictions','interval':'h','begin_date':t,'end_date':t}
            r  = requests.get(NOAA_BASE, params=p, timeout=10); r.raise_for_status()
            d  = r.json()
            if 'error' in d:
                self.logger.warning("hourly: NOAA API error for station %s: %s",
                                    self.station_id, d.get('error'))
                return None
            h  = []
            for x in d.get('predictions',[]):
                try:
                    h.append(float(x['v']))
                except (KeyError, TypeError, ValueError):
                    h.append(0.0)
            h = h[:24]
            while len(h) < 24: h.append(h[-1] if h else 0.0)
            return h
        except (requests.exceptions.RequestException, OSError, ValueError) as e:
            self.logger.error("hourly: %s", e, exc_info=True)
            return None

    def _fetch_live(self, u):
        try:
            p = {**self._base(u),'product':'water_level','date':'latest'}
            r = requests.get(NOAA_BASE, params=p, timeout=8); r.raise_for_status()
            d = r.json()
            if 'error' in d:
                # Many stations have no live water-level sensor — expected, keep quiet.
                self.logger.debug("live: NOAA API error for station %s: %s",
                                  self.station_id, d.get('error'))
                return None
            data = d.get('data', [])
            return float(data[-1]['v']) if data else None
        except (requests.exceptions.RequestException, OSError, KeyError, TypeError, ValueError):
            return None

    # ── Derived ─────────────────────────────────────────────────────────────────

    def _current_level(self):
        if self.live is not None: return self.live
        if not self.hourly: return None
        now = datetime.now()
        h0  = self.hourly[min(now.hour, len(self.hourly)-1)]
        h1  = self.hourly[min(now.hour+1, len(self.hourly)-1)]
        return h0 + (h1-h0) * (now.minute/60.0)

    def _fill_ratio(self):
        if not self.hilo: return 0.5
        heights = [e['height'] for e in self.hilo]
        lo, hi  = min(heights), max(heights)
        if hi <= lo: return 0.5
        lv = self._current_level()
        if lv is None: return 0.5
        return max(0.0, min(1.0, (lv-lo)/(hi-lo)))

    def _direction(self):
        if len(self.hourly) < 2: return 'SLACK'
        now = datetime.now()
        idx = min(now.hour, len(self.hourly)-2)
        cur = self.hourly[idx] + (self.hourly[idx+1]-self.hourly[idx])*(now.minute/60.0)
        nxt = self.hourly[min(idx+1, len(self.hourly)-1)]
        diff = nxt - cur
        if diff >  0.05: return 'RISING'
        if diff < -0.05: return 'FALLING'
        return 'SLACK'

    def _next_tides(self, n=2):
        now, out = datetime.now(), []
        for e in self.hilo:
            dt = _safe_iso(e['dt'])
            if dt and dt > now:
                out.append(e);
                if len(out) >= n: break
        return out

    def _moon_phase(self):
        return ((datetime.now()-_KNOWN_NEW_MOON).total_seconds()/(_LUNAR_PERIOD*86400))%1.0

    def _moon_name(self, p):
        for t, n in [(0.063,'New Moon'),(0.188,'Waxing Crescent'),(0.313,'First Quarter'),
                     (0.438,'Waxing Gibbous'),(0.563,'Full Moon'),(0.688,'Waning Gibbous'),
                     (0.813,'Last Quarter'),(0.938,'Waning Crescent'),(1.001,'New Moon')]:
            if p < t: return n
        return 'New Moon'

    def _unit(self): return 'ft' if self.units=='imperial' else 'm'
    def _fmth(self, h): return f"{h:.1f}{self._unit()}"

    def _fmtt(self, iso):
        try:
            dt = datetime.fromisoformat(iso)
            hr = dt.hour%12 or 12
            return f"{hr}:{dt.minute:02d}{'a' if dt.hour<12 else 'p'}"
        except Exception: return '--'

    def _name(self): return (self.station_name or self.station_id)[:14]

    # ── Drawing helpers ─────────────────────────────────────────────────────────

    def _draw_stars(self, draw, dw: int, sky_h: int) -> None:
        """Scatter faint star-like pixels in the sky area for atmosphere.

        Uses a Knuth multiplicative hash for deterministic star positions
        without importing the random module (avoids cryptographic-context warnings).
        """
        n = max(0, (dw * sky_h) // 120)
        h = 2654435761  # Knuth multiplicative hash constant
        for i in range(n):
            h = (h ^ (i * 2246822519 + 1)) & 0xFFFFFFFF
            sx = h % dw
            sy = (h >> 16) % max(1, sky_h - 2)
            b  = 18 + (h >> 8) % 34
            draw.point((sx, sy), fill=(b, b + 8, b + 22))

    def _wave_y(self, px: int) -> float:
        """Composite multi-frequency wave giving a natural, non-mechanical surface."""
        p = self.wave_phase
        y1 = math.sin((px + p)         * 0.28) * 0.85  # primary swell
        y2 = math.sin((px + p * 1.35)  * 0.47) * 0.45  # secondary chop
        y3 = math.sin((px + p * 0.72)  * 0.71) * 0.2   # fine ripple
        return y1 + y2 + y3  # max ≈ ±1.5px

    def _full_wave(self, canvas, draw, dw, dh, fill_ratio, amp):
        """
        Full-display animated water gradient with composite-sine wave surface.

        Sky (C_BG → C_SKY_HORIZON) and water (C_WATER_TOP → C_WATER_DEEP) share
        the same colour at the horizon so there is no luminance jump.
        Wave amplitude is capped at 2 px so it never clips into text above it.
        """
        effective = min(fill_ratio, 0.18)  # cap at 18% — thin water strip, sky for text
        fill_px   = max(4, int(dh * effective))
        surf_y    = dh - fill_px

        # Sky: deep teal-black at zenith → indigo at horizon (ease-out)
        sky_top = (2, 4, 18)
        for py in range(surf_y + 1):
            t = py / max(surf_y, 1)
            draw.line([(0,py),(dw-1,py)], fill=_lerp(sky_top, C_SKY_HORIZON, t*t))

        # Starfield for atmosphere
        self._draw_stars(draw, dw, surf_y)

        # Water: indigo at surface → user tide_color → deep navy
        for py in range(surf_y, dh):
            t = (py - surf_y) / max(fill_px, 1)
            if t < 0.5:
                color = _lerp(C_WATER_TOP, self.tide_color, t * 2)
            else:
                color = _lerp(self.tide_color, C_WATER_DEEP, (t - 0.5) * 2)
            draw.line([(0,py),(dw-1,py)], fill=color)

        # Horizon glow: 1px bright line at the water surface
        horizon_c = _lerp(_lerp(C_SKY_HORIZON, C_WATER_TOP, 0.5), (80, 140, 220), 0.35)
        draw.line([(0, surf_y), (dw-1, surf_y)], fill=horizon_c)

        # Pre-compute composite wave (all offsets ≤ 0 — wave only above surf_y)
        wave_ys = [surf_y + int(self._wave_y(px)) for px in range(dw)]

        # Wave as a thin bright foam line — no fill-to-surface rectangle
        # This avoids the blocky crest look; the flat water body handles depth.
        for px in range(dw):
            wy = wave_ys[px]
            if 0 <= wy < surf_y:
                bt = (math.sin((px + self.wave_phase * 1.3) * 0.11) + 1) * 0.5
                draw.point((px, wy), fill=_lerp(self.hi_color, C_WAVE_CREST, bt * 0.72))
                if wy + 1 < dh:
                    draw.point((px, wy+1), fill=_lerp(C_WATER_TOP, self.hi_color, 0.7))

        # Sparkle dots at true local crests only
        for px in range(0, dw):
            wy_p = wave_ys[max(0, px-2)]
            wy_c = wave_ys[px]
            wy_n = wave_ys[min(dw-1, px+2)]
            if wy_c <= wy_p and wy_c <= wy_n and wy_c < surf_y:
                wy = wy_c - 1
                if 0 <= wy < dh:
                    draw.point((px, wy), fill=(220, 252, 255))

        return surf_y

    def _dir_arrow(self, draw, cx, cy, direction, sz=4):
        c = C_RISING if direction=='RISING' else C_FALLING if direction=='FALLING' else C_SLACK
        if direction == 'RISING':
            draw.polygon([(cx,cy-sz),(cx-sz,cy+sz//2),(cx+sz,cy+sz//2)], fill=c)
        elif direction == 'FALLING':
            draw.polygon([(cx,cy+sz),(cx-sz,cy-sz//2),(cx+sz,cy-sz//2)], fill=c)
        else:
            draw.line([(cx-sz,cy),(cx+sz,cy)], fill=c, width=2)

    def _mini_bar(self, draw, x, y, w, h, ratio, color):
        """Tiny filled progress bar."""
        draw.rectangle([x, y, x+w-1, y+h-1], fill=C_BAR_OUT)
        fill = max(1, int(w * ratio))
        draw.rectangle([x, y, x+fill-1, y+h-1], fill=color)

    def _moon_icon(self, draw, cx, cy, r, phase):
        bbox = [cx-r, cy-r, cx+r, cy+r]
        is_new  = phase < 0.04 or phase > 0.96
        is_full = 0.47 < phase < 0.53
        if is_new:
            draw.ellipse(bbox, outline=C_LABEL, width=1); return
        if is_full:
            draw.ellipse(bbox, fill=C_MOON, outline=C_MOON); return
        draw.ellipse(bbox, fill=C_MOON, outline=C_MOON)
        frac   = abs(phase-0.5)*2
        dark_w = max(0, min(r*2, int(r*2*frac)))
        dx     = (cx-r) if phase < 0.5 else (cx+r-dark_w)
        if dark_w > 0:
            draw.ellipse([dx, cy-r, dx+dark_w, cy+r], fill=C_BG)
        draw.ellipse(bbox, outline=_lerp(C_BG, C_MOON, 0.35), width=1)

    def _raw_txt(self, x, y, text, color, font, centered):
        try:
            self.display_manager.draw_text(text, x=x, y=y, font=font, color=color, centered=centered)
        except Exception as _e:
            self.logger.debug("draw_text: %s", _e)

    def _txt(self, x, y, text, color=C_TEXT, small=True):
        color, font = self._element_style(color, small)
        self._raw_txt(x, y, text, color, font, centered=False)

    def _txtc(self, cx, y, text, color=C_TEXT, small=True):
        color, font = self._element_style(color, small)
        self._raw_txt(cx, y, text, color, font, centered=True)

    def _txt_s(self, x, y, text, color=C_TEXT, small=True):
        """Draw text with a 1-pixel drop shadow for readability over animated backgrounds."""
        color, font = self._element_style(color, small)
        self._raw_txt(x + 1, y + 1, text, (0, 0, 8), font, centered=False)
        self._raw_txt(x, y, text, color, font, centered=False)

    # ── Placeholder screens ─────────────────────────────────────────────────────

    def _no_station(self, draw, dw, dh, L):
        draw.rectangle([0, 0, dw-1, dh-1], outline=C_BAR_OUT)
        header_h, small_h, spacing = 8, 6, 2
        base_y = dh // 2 - 8
        line_y = [base_y + i * (small_h + spacing) + header_h + spacing
                  for i in range(2)]
        line_y = [min(y, dh - small_h - 1) for y in line_y]
        self._txtc(dw//2, base_y, 'TIDE', C_WAVE1, small=False)
        self._txtc(dw//2, line_y[0], 'Set Station ID', C_LABEL)
        self._txtc(dw//2, line_y[1], 'in Settings', C_LABEL)

    def _loading(self, draw, dw, dh, L):
        n = int(self.wave_phase/30)%4
        self._txtc(dw//2, dh//2-4, 'Loading'+'.'*n, C_WAVE1)

    # ── Mode 1: Current ─────────────────────────────────────────────────────────

    def _mode_current(self, canvas, draw, dw, dh, L):
        fill_ratio = self._fill_ratio()
        direction  = self._direction()
        lv         = self._current_level()

        # Full-display animated wave background (amp param unused — internal fixed at 2)
        surf_y = self._full_wave(canvas, draw, dw, dh, fill_ratio, L['wave_amp'])
        sky_h  = surf_y

        # Choose font based on available sky
        use_pixel = sky_h >= 20 and dw >= 128
        # Compute row positions dynamically — nothing must exceed sky_h
        PAD = 2
        r1  = PAD
        r2  = r1 + (10 if use_pixel else 8)
        r3  = r2 + 8 if (r2 + 8) < sky_h - 4 else None
        r4  = r3 + 7 if r3 and (r3 + 7) < sky_h - 4 else None

        dir_c = (C_RISING if direction=='RISING'
                 else C_FALLING if direction=='FALLING' else C_SLACK)

        # LEFT: direction + height
        self._txt_s(3, r1, direction, dir_c)
        arr_x = 3 + self._tw(direction) + 3
        if arr_x < dw // 2 - 6:
            self._dir_arrow(draw, arr_x, r1 + 3, direction, sz=3)
        if lv is not None:
            self._txt_s(3, r2, self._fmth(lv), C_TEXT)

        # Divider
        mid = dw // 2 - 1
        if sky_h > 12:
            draw.line([(mid, PAD), (mid, sky_h - PAD)], fill=C_BAR_OUT)

        # RIGHT: next two tides — combine type+time on one line for compactness
        rx    = dw // 2 + 3
        nexts = self._next_tides(2)

        if nexts:
            t0  = nexts[0]
            tc0 = C_HIGH if t0.get('type','?') == 'H' else C_LOW
            sym = 'HI' if t0.get('type','?') == 'H' else 'LO'
            self._txt_s(rx, r1, f"{sym} {self._fmtt(t0['dt'])}", C_TEXT)
            self._txt_s(rx, r2, self._fmth(t0['height']), tc0)

        if len(nexts) >= 2 and r3 is not None:
            t1  = nexts[1]
            tc1 = C_HIGH if t1.get('type','?') == 'H' else C_LOW
            sym2 = 'HI' if t1.get('type','?') == 'H' else 'LO'
            self._txt_s(rx, r3, f"{sym2} {self._fmtt(t1['dt'])}", C_TEXT)
            if r4 is not None:
                self._txt_s(rx, r4, self._fmth(t1['height']), tc1)

        # Station name + fill % at bottom of sky — only show if name is configured
        last = (r4 or r3 or r2) + 8
        if last + 5 < sky_h:
            name = self.station_name.strip()  # skip raw station IDs (no name set)
            if name:
                self._txt_s(3, last + 2, name[:16], C_LABEL)
            pct = int(fill_ratio * 100)
            pct_str = f"{pct}%"
            pct_w = self._tw(pct_str, label=True) + 2
            self._txt_s(max(0, dw - pct_w - 2), last + 2, pct_str, C_LABEL)

    # ── Mode 2: Schedule ────────────────────────────────────────────────────────

    def _mode_schedule(self, draw, dw, dh, L):
        if not self.hilo: self._loading(draw, dw, dh, L); return
        now    = datetime.now()
        tides  = self.hilo[:4]
        n      = len(tides)
        if n == 0: return

        col_w  = dw // n
        heights = [e['height'] for e in self.hilo]
        lo_h, hi_h = min(heights), max(heights)
        h_range    = max(hi_h-lo_h, 0.01)

        next_idx = next((i for i,t in enumerate(tides)
                        if _safe_iso(t['dt']) and _safe_iso(t['dt']) > now), None)

        for i, tide in enumerate(tides):
            cx      = i*col_w + col_w//2
            is_high = tide.get('type','?') == 'H'
            dt      = _safe_iso(tide['dt'])
            is_past = dt is not None and dt < now
            tc      = C_HIGH if is_high else C_LOW

            # Column background — next tide is noticeably brighter
            if i == next_idx:
                bg = C_COL_HIGH_NEXT if is_high else C_COL_LOW_NEXT
            else:
                bg = C_COL_HIGH if is_high else C_COL_LOW

            draw.rectangle([i*col_w+1, 0, i*col_w+col_w-2, dh-3], fill=bg)
            # Top accent line on the upcoming column
            if i == next_idx:
                draw.line([(i*col_w+1, 0), (i*col_w+col_w-2, 0)], fill=tc)

            # Type label
            label = ('HIGH' if is_high else 'LOW') if not L['small'] else ('H' if is_high else 'L')
            self._txtc(cx, L['row1'], label, tc if not is_past else C_DIM)

            # Time
            self._txtc(cx, L['row2'], self._fmtt(tide['dt']),
                       C_TEXT if not is_past else C_DIM)

            # Height — colour-interpolated across today's range
            ht_color = _lerp(C_LOW, C_HIGH, (tide['height']-lo_h)/h_range)
            self._txtc(cx, L['row3'], self._fmth(tide['height']),
                       ht_color if not is_past else C_DIM)

            # Proportional bar at bottom — leave gap below row3 text height (~8px)
            bar_max  = max(3, dh - L['row3'] - 10)
            bar_h_px = max(2, int((tide['height']-lo_h)/h_range * bar_max))
            bx1, bx2 = i*col_w+3, i*col_w+col_w-4
            bar_color = tc if not is_past else _lerp(C_DIM, tc, 0.3)
            draw.rectangle([bx1, dh-2-bar_h_px, bx2, dh-1], fill=bar_color)
            if i == next_idx:  # highlight border on the next upcoming bar
                draw.rectangle([bx1, dh-2-bar_h_px, bx2, dh-1], outline=C_TEXT)

        # Column dividers — brighter for visible separation
        for i in range(1, n):
            draw.line([(i*col_w, 0),(i*col_w, dh-1)], fill=C_BAR_OUT)

    # ── Mode 3: Chart ────────────────────────────────────────────────────────────

    def _mode_chart(self, canvas, draw, dw, dh, L):
        if not self.hourly: self._loading(draw, dw, dh, L); return

        cx, cy = L['c_x'], L['c_y']
        cw, ch = L['c_w'], L['c_h']

        heights = self.hourly[:24]
        lo, hi  = min(heights), max(heights)
        h_range = hi - lo or 1.0

        def _py(h): return cy + ch - int((h-lo)/h_range*ch)
        def _px(i): return cx + int(i*cw/max(len(heights)-1,1))

        # Background sky gradient
        for py in range(cy, cy+ch+1):
            t = (py-cy)/max(ch,1)
            draw.line([(cx,py),(cx+cw,py)], fill=_lerp((0,3,18),(0,0,0),t))

        # Grid lines
        for pct in (0.25, 0.5, 0.75):
            gy = cy + ch - int(pct*ch)
            draw.line([(cx,gy),(cx+cw,gy)], fill=C_GRID)

        pts = [(_px(i), _py(h)) for i,h in enumerate(heights)]

        # Filled area (water body)
        base_y = cy + ch
        poly   = pts + [(_px(len(pts)-1), base_y), (_px(0), base_y)]
        if len(poly) >= 3:
            draw.polygon(poly, fill=C_CHART_FILL)

        # Glow: three passes (outer → inner → bright; top colour uses user hi_color)
        for dy, gc in [(2, C_CHART_GLOW2),(1, C_CHART_GLOW1),(0, self.hi_color)]:
            for i in range(len(pts)-1):
                x1,y1 = pts[i]; x2,y2 = pts[i+1]
                draw.line([(x1,y1+dy),(x2,y2+dy)], fill=gc, width=1)
                if dy: draw.line([(x1,y1-dy),(x2,y2-dy)], fill=gc, width=1)

        # Current-time marker (draw first so H/L labels paint over it)
        now_frac = datetime.now().hour + datetime.now().minute/60.0
        now_x    = cx + int(now_frac*cw/23)
        draw.line([(now_x,cy),(now_x,cy+ch)], fill=C_NOW_LINE, width=1)
        floor_idx = min(int(now_frac), len(heights) - 1)
        ceil_idx  = min(floor_idx + 1, len(heights) - 1)
        interp_h  = heights[floor_idx] + (heights[ceil_idx] - heights[floor_idx]) * (now_frac - int(now_frac))
        cur_py    = _py(interp_h)
        r = max(1, dh//20)
        draw.ellipse([now_x-r,cur_py-r,now_x+r,cur_py+r], outline=C_NOW_LINE, width=1)
        if r > 1:
            draw.ellipse([now_x-r+1,cur_py-r+1,now_x+r-1,cur_py+r-1],
                         fill=_lerp(C_BG, C_NOW_LINE, 0.4))

        # H / L labels at peaks/troughs — offset away from current-time circle
        for tide in self.hilo:
            try:
                dt      = datetime.fromisoformat(tide['dt'])
                frac    = dt.hour + dt.minute/60.0
                tx      = cx + int(frac*cw/23)
                ty      = _py(tide['height'])
                is_high = tide.get('type','?') == 'H'
                lc      = C_HIGH if is_high else C_LOW
                sym     = 'H' if is_high else 'L'
                # If label would overlap with the current-time circle, nudge it
                nudge = (r + 3) if abs(tx - now_x) <= r + 3 else 0
                lx = max(cx, min(cx+cw-5, tx - 2 + nudge))
                ly = max(cy, min(cy+ch-8, (ty-9) if is_high else (ty+2)))
                self._txt(lx, ly, sym, lc)
                draw.line([(tx,ty-1),(tx,ty+1)], fill=(255,255,255))
            except Exception as _e: self.logger.debug("chart label: %s", _e)

        # Time axis — center each label at its tick mark, clamp both edges
        ax_y   = min(dh - 7, cy + ch + 2)  # guarantee 7px room to bottom of display
        labels = [(0,'12a'),(6,'6a'),(12,'12p'),(18,'6p')]
        if L['small']: labels = [(0,'0'),(12,'12')]
        for lh, lt in labels:
            lx   = cx + int(lh * cw / 23)
            tw   = self._tw(lt, label=True)  # ~4px/char at default extra-small font
            label_x = max(0, min(dw - tw - 1, lx - tw // 2))
            self._txt(label_x, ax_y, lt, C_LABEL)

        draw.line([(cx,cy+ch+1),(cx+cw,cy+ch+1)], fill=C_BAR_OUT)

    # ── Mode 4: Stats ────────────────────────────────────────────────────────────

    def _mode_stats(self, draw, dw, dh, L):
        if not self.hilo: self._loading(draw, dw, dh, L); return

        heights     = [e['height'] for e in self.hilo]
        lo_h, hi_h  = min(heights), max(heights)
        tidal_range = hi_h - lo_h

        phase       = self._moon_phase()
        phase_name  = self._moon_name(phase)
        is_spring   = phase < 0.10 or phase > 0.90 or 0.42 < phase < 0.58
        spring_lbl  = 'SPRING' if is_spring else 'NEAP'
        spring_c    = (255,145,40) if is_spring else C_LOW

        # Cycle progress
        now  = datetime.now()
        past = [e for e in self.hilo if _safe_iso(e['dt']) and _safe_iso(e['dt']) <= now]
        fut  = [e for e in self.hilo if _safe_iso(e['dt']) and _safe_iso(e['dt']) > now]
        cycle_pct = None
        if past and fut:
            try:
                p_dt = datetime.fromisoformat(past[-1]['dt'])
                n_dt = datetime.fromisoformat(fut[0]['dt'])
                tot  = (n_dt-p_dt).total_seconds()
                ela  = (now-p_dt).total_seconds()
                if tot > 0: cycle_pct = max(0, min(100, int(ela/tot*100)))
            except Exception as _e: self.logger.debug("cycle_pct: %s", _e)

        # Gauge bar width scales with display height
        gw = max(5, min(10, dh // 6)) if (L['large'] or L['medium']) else 0
        gx = dw - gw - 3 if gw else dw

        # Left side: moon icon + text
        moon_r  = max(4, min(10, dh//5))
        moon_cx = moon_r + 3
        moon_cy = dh//2 - (5 if L['small'] else 8)

        if self.show_moon:
            self._moon_icon(draw, moon_cx, moon_cy, moon_r, phase)
            txt_x = moon_cx + moon_r + 5
        else:
            txt_x = 4

        # When moon is hidden, skip moon phase name and use that row for tide type
        if self.show_moon:
            short = phase_name.replace(' Moon','').replace(' Quarter',' Qtr')
            if L['small']: short = short[:6]
            self._txt(txt_x, L['row1'], short, C_MOON)
            self._txt(txt_x, L['row2'], spring_lbl, spring_c)
            self._txt(txt_x, L['row3'], f"Rng {tidal_range:.1f}{self._unit()}", C_LOW)
            if not L['small']:
                self._txt(txt_x, L['row4'], f"H {hi_h:.1f}  L {lo_h:.1f}", C_TEXT)
        else:
            # Moon hidden: shift tide stats up to row1, use freed row for current level
            self._txt(txt_x, L['row1'], spring_lbl, spring_c)
            self._txt(txt_x, L['row2'], f"Rng {tidal_range:.1f}{self._unit()}", C_LOW)
            if not L['small']:
                self._txt(txt_x, L['row3'], f"H {hi_h:.1f}  L {lo_h:.1f}", C_TEXT)
                lv = self._current_level()
                if lv is not None and L['row4'] < dh - 8:
                    dir_c = (C_RISING if self._direction()=='RISING'
                             else C_FALLING if self._direction()=='FALLING' else C_SLACK)
                    self._txt(txt_x, L['row4'], f"Now {self._fmth(lv)}", dir_c)

        # Right side: vertical tide gauge bar (scaled to display height)
        if gw:
            gy      = 3
            gh      = dh - max(14, dh // 3)
            fr      = self._fill_ratio()
            fh      = max(1, int(gh * fr))
            fy0     = gy + gh - fh

            draw.rectangle([gx, gy, gx+gw-1, gy+gh], fill=(0,8,25), outline=C_BAR_OUT)
            for py in range(fy0, gy+gh):
                t2 = (gy+gh - py) / max(fh, 1)
                draw.line([(gx+1, py),(gx+gw-2, py)],
                           fill=_lerp(self.tide_color, self.hi_color, t2*0.6))
            # Micro wave on fill surface
            for px in range(gw-2):
                wy = fy0 + int(math.sin((px+self.wave_phase)*0.8))
                wy = max(gy+1, min(gy+gh-1, wy))
                draw.point((gx+1+px, wy), fill=C_WAVE_CREST)
            # Tick marks
            for pct2 in (0.25, 0.5, 0.75):
                ty2 = gy + gh - int(gh*pct2)
                draw.line([(gx-2, ty2),(gx, ty2)], fill=C_LABEL)
            # % label right-aligned under gauge — always inside display bounds
            pct_g = int(fr*100)
            pct_str_g = f"{pct_g}%"
            g_lx = max(0, min(gx, dw - self._tw(pct_str_g, label=True) - 1))
            self._txt(g_lx, gy+gh+2, pct_str_g, C_LABEL)

        # Cycle progress bar — gradient fill, height-scaled thickness
        if cycle_pct is not None:
            bar_h  = max(2, dh // 16)
            bar_y  = dh - bar_h - 1
            bar_x0 = txt_x
            bar_x1 = gx - 6 if gw else dw - 3
            blen   = max(1, bar_x1 - bar_x0)
            flen   = int(blen * cycle_pct / 100)
            draw.rectangle([bar_x0, bar_y, bar_x1, bar_y+bar_h], fill=(0,8,25))
            for px in range(flen):
                t2 = px / max(flen, 1)
                draw.line([(bar_x0+px, bar_y),(bar_x0+px, bar_y+bar_h)],
                           fill=_lerp(C_LOW, C_HIGH, t2))
            # Cycle % label — above the bar so it can't clip past display bottom
            pct_str = f"{cycle_pct}%"
            pct_w   = self._tw(pct_str, label=True) + 1
            lx      = max(0, min(dw - pct_w - 1, bar_x0 + flen - pct_w // 2))
            self._txt(lx, max(1, bar_y - 7), pct_str, C_LABEL)

    # ── Config change ────────────────────────────────────────────────────────────

    def on_config_change(self, new_config):
        super().on_config_change(new_config)
        def _rgb(k, d):
            try:   return tuple(max(0, min(255, int(c))) for c in self.config.get(k, list(d)))
            except Exception: return d
        self.station_id   = str(self.config.get('station_id',   '')).strip()
        self.station_name = str(self.config.get('station_name', '') or '').strip()
        self.units        = self.config.get('units', 'imperial')
        self.mode_dur     = float(self.config.get('display_duration', 12))
        self.show_moon    = bool(self.config.get('show_moon_phase', True))
        self.tide_color   = _rgb('tide_color',      C_WATER_MID)
        self.hi_color     = _rgb('highlight_color', C_WAVE1)
        self._apply_customization(self.config)
        self.show_mode    = {
            'current':  bool(self.config.get('show_current',  True)),
            'schedule': bool(self.config.get('show_schedule', True)),
            'chart':    bool(self.config.get('show_chart',    True)),
            'stats':    bool(self.config.get('show_stats',    True)),
        }
        self.modes   = self._build_enabled_modes()
        self.mode_idx = self.mode_idx % len(self.modes)
        self.hilo = []; self.hourly = []; self.live = None
        self.update()
