"""
Tide Display Plugin for LEDMatrix

Four auto-rotating display modes, each designed to look great across
32×64, 48×128, 48×192 and larger RGB matrix configurations:

  1. current  — Two-layer animated gradient wave bar + direction + height + next tides
  2. schedule — Today's H/L schedule with column highlights and mini tide bars
  3. chart    — 24-hour filled tide curve with glow line, grid, and current-time marker
  4. stats    — Moon phase icon, spring/neap indicator, tidal range, cycle progress

Data source: NOAA Tides & Currents API (free, no API key, US stations).
Find your station at: tidesandcurrents.noaa.gov/stations.html
"""

import math
import time
import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

NOAA_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

_KNOWN_NEW_MOON  = datetime(2000, 1, 6, 18, 14)
_LUNAR_PERIOD    = 29.53058867  # days

# ── Colour palette ────────────────────────────────────────────────────────────
C_BG           = (0,   0,   0)
C_WATER_DEEP   = (0,  50, 140)   # solid fill bottom
C_WATER_MID    = (0,  90, 180)   # fill mid-section
C_WATER_LIGHT  = (0, 130, 210)   # fill near surface
C_WAVE1        = (0, 210, 255)   # primary wave crest
C_WAVE2        = (0, 140, 200)   # secondary wave crest
C_CHART_FILL   = (0,  40, 110)   # 24h chart polygon
C_CHART_LINE   = (0, 210, 255)   # chart top line
C_CHART_GLOW1  = (0, 100, 180)   # inner glow band
C_CHART_GLOW2  = (0,  60, 130)   # outer glow band
C_GRID         = (15,  25,  50)  # subtle chart grid
C_NOW_LINE     = (255, 220,  40) # current-time marker
C_HIGH         = (255, 200,  50) # HIGH tide accent
C_LOW          = ( 80, 190, 255) # LOW  tide accent
C_RISING       = ( 50, 230, 100) # rising direction
C_FALLING      = (255,  80,  80) # falling direction
C_SLACK        = (255, 210,  60) # slack / unknown
C_TEXT         = (200, 225, 255) # primary data text
C_LABEL        = (100, 130, 180) # secondary label text
C_DIM          = ( 50,  60,  80) # past / inactive
C_MOON         = (240, 235, 200) # moon glow
C_BAR_OUTLINE  = ( 30,  50,  90) # wave-bar border
C_COL_BG       = (  0,  15,  40) # schedule column bg


def _lerp_color(c1: Tuple, c2: Tuple, t: float) -> Tuple[int, int, int]:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _safe_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ── Layout helper ──────────────────────────────────────────────────────────────

def _layout(dw: int, dh: int) -> Dict:
    """Return all scaled sizing constants for the current display dimensions."""
    # bar width: ≈13 % of width, clamped for sensible extremes
    bar_w    = max(8, min(32, int(dw * 0.13)))
    bar_x    = 2
    bar_h    = dh - 4
    bar_ybot = dh - 2

    # text area starts just after the bar
    txt_x    = bar_x + bar_w + 4

    # chart margins
    c_ml, c_mr, c_mt, c_axis = 3, 3, 1, max(7, int(dh * 0.16))
    c_x  = c_ml
    c_y  = c_mt
    c_w  = dw - c_ml - c_mr
    c_h  = dh - c_axis - c_mt - 1

    # wave amplitude: 2 px on tiny displays, up to 4 on large
    wave_amp = max(1, min(4, dh // 12))

    # vertical text positions
    row1 = 1
    row2 = max(9,  int(dh * 0.28))
    row3 = max(18, int(dh * 0.55))
    row4 = max(27, int(dh * 0.78))

    return dict(
        bar_w=bar_w, bar_x=bar_x, bar_h=bar_h, bar_ybot=bar_ybot,
        txt_x=txt_x,
        c_x=c_x, c_y=c_y, c_w=c_w, c_h=c_h, c_axis=c_axis,
        wave_amp=wave_amp,
        row1=row1, row2=row2, row3=row3, row4=row4,
        small=(dw <= 64),
        medium=(64 < dw <= 128),
        large=(dw > 128),
    )


# ── Plugin ─────────────────────────────────────────────────────────────────────

class TidePlugin(BasePlugin):
    """
    Tide display with four rotating visual modes.

    Required config: station_id (7-digit NOAA station ID).
    Optional: station_name, units (imperial/metric), display_duration,
              show_moon_phase, tide_color, highlight_color.
    """

    MODES = ['current', 'schedule', 'chart', 'stats']

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        def _rgb(key, default):
            raw = config.get(key, list(default))
            try:
                return tuple(max(0, min(255, int(c))) for c in raw)
            except (TypeError, ValueError):
                return default

        self.station_id   = str(config.get('station_id', '')).strip()
        self.station_name = str(config.get('station_name', '') or '').strip()
        self.units        = config.get('units', 'imperial')
        self.mode_dur     = float(config.get('display_duration', 12))
        self.show_moon    = bool(config.get('show_moon_phase', True))
        # User-overridable colours (fall back to palette defaults)
        self.tide_color   = _rgb('tide_color',      C_WATER_MID)
        self.hi_color     = _rgb('highlight_color', C_WAVE1)

        self.mode_idx   = 0
        self.mode_start = time.time()
        self.wave_phase = 0.0      # incremented each frame

        self.hilo:  List[Dict]   = []
        self.hourly: List[float] = []
        self.live:  Optional[float] = None

        self.logger.info("TidePlugin init station=%s units=%s",
                         self.station_id or '(none)', self.units)

    # ── BasePlugin ─────────────────────────────────────────────────────────────

    def update(self) -> None:
        if not self.station_id:
            return
        today    = date.today().strftime('%Y%m%d')
        u_param  = 'english' if self.units == 'imperial' else 'metric'

        key_hilo    = f"{self.plugin_id}:hilo:{self.station_id}:{today}"
        key_hourly  = f"{self.plugin_id}:hourly:{self.station_id}:{today}"
        key_live    = f"{self.plugin_id}:live:{self.station_id}"

        cached = self.cache_manager.get(key_hilo, max_age=86400)
        if not cached:
            cached = self._fetch_hilo(u_param)
            if cached:
                self.cache_manager.set(key_hilo, cached)
        self.hilo = cached or []

        ch = self.cache_manager.get(key_hourly, max_age=21600)
        if not ch:
            ch = self._fetch_hourly(u_param)
            if ch:
                self.cache_manager.set(key_hourly, ch)
        self.hourly = ch or []

        lv = self.cache_manager.get(key_live, max_age=360)
        if lv is None:
            lv = self._fetch_live(u_param)
            if lv is not None:
                self.cache_manager.set(key_live, lv)
        self.live = lv

    def display(self, force_clear: bool = False) -> None:
        dw = self.display_manager.matrix.width
        dh = self.display_manager.matrix.height
        canvas = Image.new('RGB', (dw, dh), C_BG)
        draw   = ImageDraw.Draw(canvas)
        L      = _layout(dw, dh)

        if not self.station_id:
            self._no_station(draw, dw, dh, L)
        elif not self.hilo:
            self._loading(draw, dw, dh, L)
        else:
            m = self.MODES[self.mode_idx]
            if   m == 'current':  self._mode_current(canvas, draw, dw, dh, L)
            elif m == 'schedule': self._mode_schedule(draw, dw, dh, L)
            elif m == 'chart':    self._mode_chart(canvas, draw, dw, dh, L)
            else:                 self._mode_stats(draw, dw, dh, L)

        self.display_manager.image = canvas
        self.display_manager.draw  = ImageDraw.Draw(self.display_manager.image)
        self.display_manager.update_display()
        self.wave_phase = (self.wave_phase + 1.5) % 360

    def supports_dynamic_duration(self) -> bool: return True
    def get_display_duration(self) -> float:      return self.mode_dur
    def reset_cycle_state(self) -> None:          self.mode_start = time.time()

    def is_cycle_complete(self) -> bool:
        if time.time() - self.mode_start >= self.mode_dur:
            self.mode_idx   = (self.mode_idx + 1) % len(self.MODES)
            self.mode_start = time.time()
            return True
        return False

    # ── NOAA fetchers ──────────────────────────────────────────────────────────

    def _base_params(self, u: str) -> Dict:
        return {'format': 'json', 'units': u, 'time_zone': 'lst_ldt',
                'datum': 'MLLW', 'station': self.station_id}

    def _fetch_hilo(self, u: str) -> Optional[List[Dict]]:
        try:
            p = {**self._base_params(u), 'product': 'predictions',
                 'date': 'today', 'interval': 'hilo'}
            r = requests.get(NOAA_BASE, params=p, timeout=10); r.raise_for_status()
            d = r.json()
            if 'error' in d:
                self.logger.warning("NOAA hilo: %s", d['error'].get('message')); return None
            out = []
            for p2 in d.get('predictions', []):
                try:
                    out.append({'dt': datetime.strptime(p2['t'], '%Y-%m-%d %H:%M').isoformat(),
                                'height': float(p2['v']), 'type': p2.get('type', '?')})
                except (ValueError, KeyError):
                    pass
            return out or None
        except Exception as e:
            self.logger.error("hilo fetch: %s", e); return None

    def _fetch_hourly(self, u: str) -> Optional[List[float]]:
        try:
            today = date.today().strftime('%Y%m%d')
            p = {**self._base_params(u), 'product': 'predictions', 'interval': 'h',
                 'begin_date': today, 'end_date': today}
            r = requests.get(NOAA_BASE, params=p, timeout=10); r.raise_for_status()
            d = r.json()
            if 'error' in d:
                return None
            heights = []
            for item in d.get('predictions', []):
                try:    heights.append(float(item['v']))
                except: heights.append(0.0)
            heights = heights[:24]
            while len(heights) < 24:
                heights.append(heights[-1] if heights else 0.0)
            return heights
        except Exception as e:
            self.logger.error("hourly fetch: %s", e); return None

    def _fetch_live(self, u: str) -> Optional[float]:
        try:
            p = {**self._base_params(u), 'product': 'water_level', 'date': 'latest'}
            r = requests.get(NOAA_BASE, params=p, timeout=8); r.raise_for_status()
            d = r.json()
            if 'error' in d: return None
            data = d.get('data', [])
            return float(data[-1]['v']) if data else None
        except:
            return None  # live level is optional — silent fallback

    # ── Derived helpers ────────────────────────────────────────────────────────

    def _current_level(self) -> Optional[float]:
        if self.live is not None:
            return self.live
        if not self.hourly:
            return None
        now    = datetime.now()
        h, m   = now.hour, now.minute
        h0     = self.hourly[min(h, len(self.hourly) - 1)]
        h1     = self.hourly[min(h + 1, len(self.hourly) - 1)]
        return h0 + (h1 - h0) * (m / 60.0)

    def _fill_ratio(self) -> float:
        if not self.hilo: return 0.5
        heights = [e['height'] for e in self.hilo]
        lo, hi  = min(heights), max(heights)
        if hi <= lo: return 0.5
        lv = self._current_level()
        if lv is None: return 0.5
        return max(0.0, min(1.0, (lv - lo) / (hi - lo)))

    def _direction(self) -> str:
        if len(self.hourly) < 2: return 'SLACK'
        now   = datetime.now()
        idx   = min(now.hour, len(self.hourly) - 2)
        frac  = now.minute / 60.0
        cur   = self.hourly[idx] + (self.hourly[idx + 1] - self.hourly[idx]) * frac
        nxt   = self.hourly[min(idx + 1, len(self.hourly) - 1)]
        diff  = nxt - cur
        if diff >  0.05: return 'RISING'
        if diff < -0.05: return 'FALLING'
        return 'SLACK'

    def _next_tides(self, n: int = 2) -> List[Dict]:
        now, out = datetime.now(), []
        for e in self.hilo:
            dt = _safe_iso(e['dt'])
            if dt and dt > now:
                out.append(e)
                if len(out) >= n: break
        return out

    def _moon_phase(self) -> float:
        return ((datetime.now() - _KNOWN_NEW_MOON).total_seconds()
                / (_LUNAR_PERIOD * 86400)) % 1.0

    def _moon_name(self, phase: float) -> str:
        names = [(0.063,'New Moon'),(0.188,'Waxing Crescent'),(0.313,'First Quarter'),
                 (0.438,'Waxing Gibbous'),(0.563,'Full Moon'),(0.688,'Waning Gibbous'),
                 (0.813,'Last Quarter'),(0.938,'Waning Crescent'),(1.001,'New Moon')]
        for t, n in names:
            if phase < t: return n
        return 'New Moon'

    def _unit(self) -> str: return 'ft' if self.units == 'imperial' else 'm'

    def _fmth(self, h: float) -> str:
        return f"{h:.1f}{self._unit()}"

    def _fmtt(self, iso: str) -> str:
        try:
            dt   = datetime.fromisoformat(iso)
            hr   = dt.hour % 12 or 12
            ampm = 'a' if dt.hour < 12 else 'p'
            return f"{hr}:{dt.minute:02d}{ampm}"
        except ValueError:
            return '--'

    def _name_or_id(self) -> str:
        return (self.station_name or self.station_id)[:14]

    # ── Drawing primitives ─────────────────────────────────────────────────────

    def _wave_bar(self, canvas: Image.Image, draw: ImageDraw.Draw,
                  x: int, ybot: int, bw: int, bh: int,
                  fill_ratio: float, amp: int) -> None:
        """
        Animated gradient tide-level bar with two-layer wave surface.
        Gradient transitions from deep blue at bottom to lighter blue near surface.
        """
        fill_px  = max(2, int(bh * fill_ratio))
        fill_top = ybot - fill_px

        # Border (draw outline before fill so fill covers inner edge)
        draw.rectangle([x - 1, ybot - bh - 1, x + bw, ybot + 1],
                       outline=C_BAR_OUTLINE)

        # Gradient fill: three bands
        band1 = fill_px * 2 // 3
        band2 = fill_px - band1
        if band1 > 0:
            draw.rectangle([x, fill_top + band2, x + bw - 1, ybot],
                           fill=C_WATER_DEEP)
        if band2 > 0:
            draw.rectangle([x, fill_top, x + bw - 1,
                            fill_top + band2 + 1], fill=C_WATER_MID)

        # Thin bright band near surface
        surf_band = max(1, fill_px // 4)
        if fill_px > surf_band:
            draw.rectangle([x, fill_top, x + bw - 1,
                            fill_top + surf_band], fill=C_WATER_LIGHT)

        # Tick marks on right edge at 25 / 50 / 75 %
        for pct in (0.25, 0.5, 0.75):
            ty = ybot - int(bh * pct)
            draw.line([(x + bw - 2, ty), (x + bw, ty)], fill=C_LABEL)

        # Layer 2 (subtle, higher frequency)
        for px in range(bw):
            wy = fill_top - 1 + int((amp - 1) *
                 math.sin((px + self.wave_phase * 1.8 + 25) * 0.55))
            wy = max(0, min(ybot, wy))
            draw.point((x + px, wy), fill=C_WAVE2)

        # Layer 1 (main wave, 2-3 px thick for visibility)
        for px in range(bw):
            wy = fill_top + int(amp * math.sin((px + self.wave_phase) * 0.42))
            wy = max(0, min(ybot, wy))
            draw.line([(x + px, wy), (x + px, min(ybot, wy + 2))], fill=C_WAVE1)

        # Foam dot highlight every ~6px at the crest
        for px in range(0, bw, max(3, bw // 5)):
            wy = fill_top + int(amp * math.sin((px + self.wave_phase) * 0.42))
            wy = max(0, min(ybot - 1, wy - 1))
            draw.point((x + px, wy), fill=(255, 255, 255))

    def _direction_arrow(self, draw: ImageDraw.Draw,
                         cx: int, cy: int, direction: str, sz: int = 4) -> None:
        c = C_RISING if direction == 'RISING' else \
            C_FALLING if direction == 'FALLING' else C_SLACK
        if direction == 'RISING':
            draw.polygon([(cx, cy - sz), (cx - sz, cy + sz // 2),
                          (cx + sz, cy + sz // 2)], fill=c)
        elif direction == 'FALLING':
            draw.polygon([(cx, cy + sz), (cx - sz, cy - sz // 2),
                          (cx + sz, cy - sz // 2)], fill=c)
        else:
            # Bidirectional horizontal dash
            draw.line([(cx - sz, cy), (cx + sz, cy)], fill=c, width=2)
            draw.point((cx - sz - 1, cy), fill=c)
            draw.point((cx + sz + 1, cy), fill=c)

    def _moon_icon(self, draw: ImageDraw.Draw,
                   cx: int, cy: int, r: int, phase: float) -> None:
        """Draw a scaled moon phase icon. r is the radius in pixels."""
        bbox = [cx - r, cy - r, cx + r, cy + r]
        is_new  = phase < 0.04 or phase > 0.96
        is_full = 0.47 < phase < 0.53

        if is_new:
            draw.ellipse(bbox, outline=C_LABEL, width=1)
            return
        if is_full:
            draw.ellipse(bbox, fill=C_MOON, outline=C_MOON)
            return

        # Draw lit side, then dark overlay
        draw.ellipse(bbox, fill=C_MOON, outline=C_MOON)

        # Dark overlay: an ellipse narrowed by phase
        # phase < 0.5 → waxing (left in darkness, shrinks)
        # phase > 0.5 → waning (right goes dark, grows)
        frac = abs(phase - 0.5) * 2   # 0 = full, 1 = new
        dark_w = int(r * 2 * frac)
        dark_w = max(0, min(r * 2, dark_w))

        if phase < 0.5:  # waxing — dark overlay on left
            dx = cx - r
        else:            # waning — dark overlay on right
            dx = cx + r - dark_w

        if dark_w > 0:
            dbbox = [dx, cy - r, dx + dark_w, cy + r]
            draw.ellipse(dbbox, fill=C_BG)

        # Redraw outline
        draw.ellipse(bbox, outline=_lerp_color(C_BG, C_MOON, 0.4), width=1)

    def _txt(self, x: int, y: int, text: str,
             color: Tuple = C_TEXT, small: bool = True) -> None:
        """Draw text via display_manager (respects font system)."""
        font = (self.display_manager.extra_small_font
                if small else self.display_manager.small_font)
        try:
            self.display_manager.draw_text(
                text, x=x, y=y, font=font, color=color, centered=False)
        except Exception:
            pass  # font not available — skip silently

    def _txt_c(self, cx: int, y: int, text: str,
               color: Tuple = C_TEXT, small: bool = True) -> None:
        """Draw text centered on cx."""
        font = (self.display_manager.extra_small_font
                if small else self.display_manager.small_font)
        try:
            self.display_manager.draw_text(
                text, x=cx, y=y, font=font, color=color, centered=True)
        except Exception:
            pass

    # ── Placeholder screens ────────────────────────────────────────────────────

    def _no_station(self, draw, dw, dh, L):
        draw.rectangle([0, 0, dw - 1, dh - 1], outline=C_BAR_OUTLINE)
        self._txt_c(dw // 2, L['row1'], 'TIDE', C_WAVE1)
        self._txt_c(dw // 2, L['row2'], 'Set station ID', C_LABEL)
        if not L['small']:
            self._txt_c(dw // 2, L['row3'], 'in plugin config', C_DIM)

    def _loading(self, draw, dw, dh, L):
        # Animated dots
        n_dots = int(self.wave_phase / 30) % 4
        self._txt_c(dw // 2, dh // 2 - 4, 'Loading' + '.' * n_dots, C_WAVE1)

    # ── Mode 1: Current ────────────────────────────────────────────────────────

    def _mode_current(self, canvas, draw, dw, dh, L):
        bx   = L['bar_x']
        bw   = L['bar_w']
        bh   = L['bar_h']
        ybot = L['bar_ybot']
        tx   = L['txt_x']
        amp  = L['wave_amp']

        # Animated gradient wave bar
        self._wave_bar(canvas, draw, bx, ybot, bw, bh, self._fill_ratio(), amp)

        direction = self._direction()
        dir_color = (C_RISING if direction == 'RISING'
                     else C_FALLING if direction == 'FALLING' else C_SLACK)

        # Direction label + arrow
        dir_short = direction if L['large'] else direction[:4]
        self._txt(tx, L['row1'], dir_short, dir_color)
        arr_x = tx + len(dir_short) * 4 + 4
        if arr_x < dw - 6:
            self._direction_arrow(draw, arr_x, L['row1'] + 3, direction, sz=3)

        # Current height
        lv = self._current_level()
        if lv is not None:
            self._txt(tx, L['row2'], self._fmth(lv), C_TEXT)

        # Decorative separator
        sep_y = L['row2'] + 9
        if sep_y < dh - 12:
            draw.line([(tx, sep_y), (dw - 3, sep_y)], fill=C_BAR_OUTLINE)

        # Next two tides
        nexts  = self._next_tides(2)
        row    = sep_y + 2
        for tide in nexts:
            if row + 8 > dh:
                break
            is_high = tide.get('type', '?') == 'H'
            tc = C_HIGH if is_high else C_LOW
            sym = '▲' if is_high else '▼'
            label = f"{sym} {self._fmtt(tide['dt'])}  {self._fmth(tide['height'])}"
            self._txt(tx, row, label, tc)
            row += 10

        # Station name (bottom-right, very dim)
        name = self._name_or_id()
        if name and row + 1 < dh:
            self._txt(tx, dh - 8, name, C_DIM)

    # ── Mode 2: Schedule ───────────────────────────────────────────────────────

    def _mode_schedule(self, draw, dw, dh, L):
        if not self.hilo:
            self._loading(draw, dw, dh, L); return

        now    = datetime.now()
        tides  = self.hilo[:4]
        n      = len(tides)
        if n == 0: return

        col_w  = dw // n
        heights = [e['height'] for e in self.hilo]
        lo_h, hi_h = min(heights), max(heights)
        h_range = max(hi_h - lo_h, 0.01)

        # Find first upcoming tide index
        next_idx = next(
            (i for i, t in enumerate(tides) if _safe_iso(t['dt'])
             and _safe_iso(t['dt']) > now), None)

        for i, tide in enumerate(tides):
            cx      = i * col_w + col_w // 2
            is_high = tide.get('type', '?') == 'H'
            dt      = _safe_iso(tide['dt'])
            is_past = dt is not None and dt < now

            tc  = C_HIGH if is_high else C_LOW
            dim = is_past

            # Column background for next upcoming tide
            if i == next_idx:
                draw.rectangle([i * col_w + 1, 0,
                                i * col_w + col_w - 2, dh - 4],
                                fill=C_COL_BG)

            # Type badge
            type_label = ('HIGH' if is_high else 'LOW') if not L['small'] else ('H' if is_high else 'L')
            self._txt_c(cx, L['row1'], type_label, tc if not dim else C_DIM)

            # Time
            t_str = self._fmtt(tide['dt'])
            self._txt_c(cx, L['row2'], t_str, C_TEXT if not dim else C_DIM)

            # Height
            h_str = self._fmth(tide['height'])
            self._txt_c(cx, L['row3'], h_str,
                        _lerp_color(C_LOW, C_HIGH,
                                    (tide['height'] - lo_h) / h_range)
                        if not dim else C_DIM)

            # Mini proportional bar at very bottom of column
            bar_h_px = max(1, int((tide['height'] - lo_h) / h_range * 4))
            bx1, bx2 = i * col_w + 3, i * col_w + col_w - 4
            draw.rectangle([bx1, dh - 1 - bar_h_px, bx2, dh - 1],
                           fill=tc if not dim else C_DIM)

        # Column dividers
        for i in range(1, n):
            draw.line([(i * col_w, 1), (i * col_w, dh - 5)], fill=C_BAR_OUTLINE)

    # ── Mode 3: Chart ──────────────────────────────────────────────────────────

    def _mode_chart(self, canvas, draw, dw, dh, L):
        if not self.hourly:
            self._loading(draw, dw, dh, L); return

        cx, cy = L['c_x'], L['c_y']
        cw, ch = L['c_w'], L['c_h']
        axis_y = cy + ch + 1

        heights = self.hourly[:24]
        lo = min(heights);  hi = max(heights)
        h_range = hi - lo or 1.0

        def _py(h: float) -> int:
            return cy + ch - int((h - lo) / h_range * ch)

        def _px(hour: int) -> int:
            return cx + int(hour * cw / max(len(heights) - 1, 1))

        # Subtle horizontal grid lines
        for pct in (0.25, 0.5, 0.75):
            gy = cy + ch - int(pct * ch)
            draw.line([(cx, gy), (cx + cw, gy)], fill=C_GRID)

        pts = [(_px(i), _py(h)) for i, h in enumerate(heights)]

        # Filled polygon (water body)
        base_y = cy + ch
        poly   = pts + [(_px(len(pts) - 1), base_y), (_px(0), base_y)]
        if len(poly) >= 3:
            draw.polygon(poly, fill=C_CHART_FILL)

        # Glow layers on top of curve (outer → inner → bright)
        for dy, gc in [(2, C_CHART_GLOW2), (1, C_CHART_GLOW1), (0, C_CHART_LINE)]:
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                draw.line([(x1, y1 + dy), (x2, y2 + dy)], fill=gc, width=1)
                if dy > 0:
                    draw.line([(x1, y1 - dy), (x2, y2 - dy)], fill=gc, width=1)

        # H / L labels at peaks and troughs
        for tide in self.hilo:
            try:
                dt       = datetime.fromisoformat(tide['dt'])
                frac_hr  = dt.hour + dt.minute / 60.0
                tx       = cx + int(frac_hr * cw / 23)
                ty       = _py(tide['height'])
                is_high  = tide.get('type', '?') == 'H'
                lc       = C_HIGH if is_high else C_LOW
                sym      = 'H' if is_high else 'L'
                lx = max(cx, min(cx + cw - 5, tx - 2))
                ly = max(cy, min(cy + ch - 8, (ty - 9) if is_high else (ty + 2)))
                draw.text((lx, ly), sym, fill=lc)
                # Tick at peak/trough
                draw.line([(tx, ty - 1), (tx, ty + 1)], fill=(255, 255, 255))
            except (ValueError, KeyError):
                continue

        # Current-time marker (bright gold vertical line + circle)
        now_frac = datetime.now().hour + datetime.now().minute / 60.0
        now_x    = cx + int(now_frac * cw / 23)
        draw.line([(now_x, cy), (now_x, cy + ch)], fill=C_NOW_LINE, width=1)
        # Small circle at the intersection with the curve
        cur_hour_idx = min(int(now_frac), len(heights) - 1)
        cur_py       = _py(heights[cur_hour_idx])
        r = max(1, dh // 20)
        draw.ellipse([now_x - r, cur_py - r, now_x + r, cur_py + r],
                     outline=C_NOW_LINE, width=1)
        # Fill with dim gold
        if r > 1:
            draw.ellipse([now_x - r + 1, cur_py - r + 1,
                          now_x + r - 1, cur_py + r - 1],
                         fill=_lerp_color(C_BG, C_NOW_LINE, 0.45))

        # Time axis labels
        ax_y = axis_y + 1
        ax_labels = [(0, '12a'), (6, '6a'), (12, '12p'), (18, '6p')]
        if L['small']:
            ax_labels = [(0, '0'), (12, '12')]
        for lh, lt in ax_labels:
            lx = cx + int(lh * cw / 23)
            draw.text((max(0, lx - 4), ax_y), lt, fill=C_LABEL)

        # Separator above axis
        draw.line([(cx, cy + ch + 1), (cx + cw, cy + ch + 1)], fill=C_BAR_OUTLINE)

    # ── Mode 4: Stats ──────────────────────────────────────────────────────────

    def _mode_stats(self, draw, dw, dh, L):
        if not self.hilo:
            self._loading(draw, dw, dh, L); return

        heights      = [e['height'] for e in self.hilo]
        lo_h, hi_h   = min(heights), max(heights)
        tidal_range  = hi_h - lo_h
        phase        = self._moon_phase()
        phase_name   = self._moon_name(phase)
        is_spring    = phase < 0.1 or phase > 0.9 or 0.42 < phase < 0.58
        spring_label = 'SPRING' if is_spring else 'NEAP'
        spring_color = (255, 150, 50) if is_spring else C_LOW

        # Cycle progress
        now  = datetime.now()
        past = [e for e in self.hilo if _safe_iso(e['dt']) and _safe_iso(e['dt']) <= now]
        fut  = [e for e in self.hilo if _safe_iso(e['dt']) and _safe_iso(e['dt']) > now]
        cycle_pct = None
        if past and fut:
            try:
                p_dt = datetime.fromisoformat(past[-1]['dt'])
                n_dt = datetime.fromisoformat(fut[0]['dt'])
                tot  = (n_dt - p_dt).total_seconds()
                ela  = (now - p_dt).total_seconds()
                if tot > 0: cycle_pct = max(0, min(100, int(ela / tot * 100)))
            except (ValueError, KeyError): pass

        # Moon icon left side
        moon_r  = max(4, min(10, dh // 5))
        moon_cx = moon_r + 3
        moon_cy = dh // 2 - (4 if L['small'] else 6)

        if self.show_moon:
            self._moon_icon(draw, moon_cx, moon_cy, moon_r, phase)
            txt_x = moon_cx + moon_r + 5
        else:
            txt_x = 4

        # Moon phase name (short on small displays)
        short_name = (phase_name.replace(' Moon', '').replace(' Quarter', ' Qtr')
                      if not L['small'] else phase_name[:6])
        self._txt(txt_x, L['row1'], short_name, C_MOON)

        # Spring / Neap badge
        self._txt(txt_x, L['row2'], spring_label, spring_color)

        # Tidal range
        self._txt(txt_x, L['row3'],
                  f"Range {tidal_range:.1f}{self._unit()}", C_LOW)

        # Today's extremes
        if not L['small']:
            self._txt(txt_x, L['row4'],
                      f"H {hi_h:.1f}  L {lo_h:.1f}{self._unit()}", C_LABEL)

        # Cycle progress bar (bottom)
        if cycle_pct is not None:
            bar_y  = dh - 4
            bar_x0 = txt_x
            bar_x1 = dw - 3
            blen   = bar_x1 - bar_x0
            flen   = int(blen * cycle_pct / 100)

            # Background track
            draw.rectangle([bar_x0, bar_y, bar_x1, bar_y + 2], fill=C_COL_BG)

            # Gradient progress fill: low-tide blue → high-tide gold
            t = cycle_pct / 100.0
            prog_color = _lerp_color(C_LOW, C_HIGH, t)
            if flen > 0:
                draw.rectangle([bar_x0, bar_y,
                                bar_x0 + flen, bar_y + 2], fill=prog_color)

            # Percentage label above bar
            pct_x = max(txt_x, min(dw - 26, bar_x0 + flen - 8))
            draw.text((pct_x, bar_y - 8), f"{cycle_pct}%", fill=C_LABEL)

    # ── Config change ──────────────────────────────────────────────────────────

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)

        def _rgb(key, default):
            raw = self.config.get(key, list(default))
            try:   return tuple(max(0, min(255, int(c))) for c in raw)
            except: return default

        self.station_id   = str(self.config.get('station_id', '')).strip()
        self.station_name = str(self.config.get('station_name', '') or '').strip()
        self.units        = self.config.get('units', 'imperial')
        self.mode_dur     = float(self.config.get('display_duration', 12))
        self.show_moon    = bool(self.config.get('show_moon_phase', True))
        self.tide_color   = _rgb('tide_color',      C_WATER_MID)
        self.hi_color     = _rgb('highlight_color', C_WAVE1)

        self.hilo = []; self.hourly = []; self.live = None
        self.update()
        self.logger.info("TidePlugin config updated: station=%s", self.station_id)
