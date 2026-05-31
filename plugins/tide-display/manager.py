"""
Tide Display Plugin for LEDMatrix

Coastal tide information with four rotating display modes:
  1. current  — Animated wave-level bar + current height + next tide info
  2. schedule — Today's high/low tide schedule in columns
  3. chart    — 24-hour filled tide curve with current-time marker
  4. stats    — Moon phase, tidal range, spring/neap indicator

Data source: NOAA Tides & Currents API (free, no API key required).
Configure your nearest station at: tidesandcurrents.noaa.gov/stations.html
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

# Moon phase reference (known new moon)
_KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14)
_LUNAR_PERIOD_DAYS = 29.53058867


class TidePlugin(BasePlugin):
    """
    Tide display plugin showing animated tide conditions and predictions.

    Configuration options:
        station_id (str): 7-digit NOAA station ID (required)
        station_name (str): Display name (optional override)
        units (str): 'imperial' (feet) or 'metric' (meters)
        display_duration (float): Seconds per display mode (default: 12)
        show_moon_phase (bool): Show moon icon on stats screen (default: true)
        tide_color (list): RGB water fill color (default: [0, 100, 200])
        highlight_color (list): RGB wave/chart line color (default: [0, 220, 255])
    """

    MODES = ['current', 'schedule', 'chart', 'stats']

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        def _rgb(key: str, default: Tuple) -> Tuple[int, int, int]:
            raw = config.get(key, list(default))
            try:
                return tuple(int(c) for c in raw)
            except (TypeError, ValueError):
                return default

        # Config
        self.station_id: str = str(config.get('station_id', '')).strip()
        self.station_name: str = str(config.get('station_name', '') or '').strip()
        self.units: str = config.get('units', 'imperial')
        self.mode_duration: float = float(config.get('display_duration', 12))
        self.show_moon: bool = bool(config.get('show_moon_phase', True))
        self.tide_color: Tuple = _rgb('tide_color', (0, 100, 200))
        self.highlight_color: Tuple = _rgb('highlight_color', (0, 220, 255))

        # Display state
        self.mode_idx: int = 0
        self.mode_start: float = time.time()
        self.wave_offset: int = 0

        # Data
        self.hilo: List[Dict] = []       # [{dt, height, type}]
        self.hourly: List[float] = []    # 24 floats (hour 0–23)
        self.live_level: Optional[float] = None

        self.logger.info(
            "TidePlugin init: station=%s units=%s", self.station_id or '(none)', self.units
        )

    # ─── BasePlugin interface ────────────────────────────────────────────────

    def update(self) -> None:
        if not self.station_id:
            return

        today_str = date.today().strftime('%Y%m%d')
        unit_param = 'english' if self.units == 'imperial' else 'metric'

        # High/low predictions — valid for the whole day, cache 24 h
        hilo_key = f"{self.plugin_id}:hilo:{self.station_id}:{today_str}"
        hilo_cached = self.cache_manager.get(hilo_key, max_age=86400)
        if not hilo_cached:
            hilo_cached = self._fetch_hilo(unit_param)
            if hilo_cached:
                self.cache_manager.set(hilo_key, hilo_cached)
        self.hilo = hilo_cached or []

        # Hourly heights for chart — cache 6 h
        hourly_key = f"{self.plugin_id}:hourly:{self.station_id}:{today_str}"
        hourly_cached = self.cache_manager.get(hourly_key, max_age=21600)
        if not hourly_cached:
            hourly_cached = self._fetch_hourly(unit_param)
            if hourly_cached:
                self.cache_manager.set(hourly_key, hourly_cached)
        self.hourly = hourly_cached or []

        # Live water level — cache 6 min (NOAA updates every 6 min)
        live_key = f"{self.plugin_id}:live:{self.station_id}"
        live_cached = self.cache_manager.get(live_key, max_age=360)
        if live_cached is None:
            live_cached = self._fetch_live(unit_param)
            if live_cached is not None:
                self.cache_manager.set(live_key, live_cached)
        self.live_level = live_cached

    def display(self, force_clear: bool = False) -> None:
        dw = self.display_manager.matrix.width
        dh = self.display_manager.matrix.height
        canvas = Image.new('RGB', (dw, dh), (0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        if not self.station_id:
            self._screen_no_station(draw, dw, dh)
        elif not self.hilo:
            self._screen_loading(draw, dw, dh)
        else:
            mode = self.MODES[self.mode_idx]
            if mode == 'current':
                self._screen_current(draw, dw, dh)
            elif mode == 'schedule':
                self._screen_schedule(draw, dw, dh)
            elif mode == 'chart':
                self._screen_chart(draw, dw, dh)
            else:
                self._screen_stats(draw, dw, dh)

        self.display_manager.image = canvas
        self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
        self.display_manager.update_display()
        self.wave_offset = (self.wave_offset + 1) % 360

    def supports_dynamic_duration(self) -> bool:
        return True

    def is_cycle_complete(self) -> bool:
        if time.time() - self.mode_start >= self.mode_duration:
            self.mode_idx = (self.mode_idx + 1) % len(self.MODES)
            self.mode_start = time.time()
            return True
        return False

    def reset_cycle_state(self) -> None:
        self.mode_start = time.time()

    def get_display_duration(self) -> float:
        return self.mode_duration

    # ─── NOAA API fetchers ───────────────────────────────────────────────────

    def _noaa_params(self, unit_param: str) -> Dict:
        return {
            'format': 'json',
            'units': unit_param,
            'time_zone': 'lst_ldt',
            'datum': 'MLLW',
            'station': self.station_id,
        }

    def _fetch_hilo(self, unit_param: str) -> Optional[List[Dict]]:
        """Fetch today's high/low tide predictions."""
        try:
            params = self._noaa_params(unit_param)
            params.update({'product': 'predictions', 'date': 'today', 'interval': 'hilo'})
            resp = requests.get(NOAA_BASE, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if 'error' in data:
                self.logger.warning("NOAA hilo error: %s", data['error'].get('message'))
                return None
            result = []
            for p in data.get('predictions', []):
                try:
                    dt = datetime.strptime(p['t'], '%Y-%m-%d %H:%M')
                    result.append({
                        'dt': dt.isoformat(),
                        'height': float(p['v']),
                        'type': p.get('type', '?'),
                    })
                except (ValueError, KeyError):
                    continue
            self.logger.debug("Fetched %d hilo predictions", len(result))
            return result or None
        except Exception as e:
            self.logger.error("Failed to fetch hilo: %s", e)
            return None

    def _fetch_hourly(self, unit_param: str) -> Optional[List[float]]:
        """Fetch hourly tide heights (24 values) for today's tide curve."""
        try:
            today = date.today()
            params = self._noaa_params(unit_param)
            params.update({
                'product': 'predictions',
                'interval': 'h',
                'begin_date': today.strftime('%Y%m%d'),
                'end_date': today.strftime('%Y%m%d'),
            })
            resp = requests.get(NOAA_BASE, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if 'error' in data:
                self.logger.warning("NOAA hourly error: %s", data['error'].get('message'))
                return None
            preds = data.get('predictions', [])
            heights = []
            for p in preds:
                try:
                    heights.append(float(p['v']))
                except (ValueError, KeyError):
                    heights.append(0.0)
            heights = heights[:24]
            while len(heights) < 24:
                heights.append(heights[-1] if heights else 0.0)
            self.logger.debug("Fetched %d hourly heights", len(heights))
            return heights
        except Exception as e:
            self.logger.error("Failed to fetch hourly: %s", e)
            return None

    def _fetch_live(self, unit_param: str) -> Optional[float]:
        """Fetch current observed water level (not all stations support this)."""
        try:
            params = self._noaa_params(unit_param)
            params.update({'product': 'water_level', 'date': 'latest'})
            resp = requests.get(NOAA_BASE, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            if 'error' in data:
                return None  # Station may not have live observations — silent fallback
            readings = data.get('data', [])
            if readings:
                return float(readings[-1]['v'])
            return None
        except Exception:
            return None  # Live level is optional — don't log errors

    # ─── Derived data helpers ────────────────────────────────────────────────

    def _current_level(self) -> Optional[float]:
        """Return live observed level, or interpolate from hourly predictions."""
        if self.live_level is not None:
            return self.live_level
        if not self.hourly:
            return None
        hour = datetime.now().hour
        minute = datetime.now().minute
        # Linear interpolation between current and next hour
        h0 = self.hourly[min(hour, len(self.hourly) - 1)]
        h1 = self.hourly[min(hour + 1, len(self.hourly) - 1)]
        return h0 + (h1 - h0) * (minute / 60.0)

    def _fill_ratio(self) -> float:
        """Current tide as fraction 0–1 between today's lowest and highest."""
        if not self.hilo:
            return 0.5
        heights = [e['height'] for e in self.hilo]
        lo, hi = min(heights), max(heights)
        if hi <= lo:
            return 0.5
        level = self._current_level()
        if level is None:
            return 0.5
        return max(0.0, min(1.0, (level - lo) / (hi - lo)))

    def _tide_direction(self) -> str:
        """Determine rising / falling / slack from hourly data."""
        if len(self.hourly) < 2:
            return 'SLACK'
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        frac = minute / 60.0
        idx = min(hour, len(self.hourly) - 2)
        current = self.hourly[idx] + (self.hourly[idx + 1] - self.hourly[idx]) * frac
        next_val = self.hourly[min(idx + 1, len(self.hourly) - 1)]
        diff = next_val - current
        if diff > 0.05:
            return 'RISING'
        if diff < -0.05:
            return 'FALLING'
        return 'SLACK'

    def _next_tides(self, count: int = 2) -> List[Dict]:
        """Return the next N upcoming high/low tides."""
        now = datetime.now()
        upcoming = []
        for entry in self.hilo:
            try:
                dt = datetime.fromisoformat(entry['dt'])
                if dt > now:
                    upcoming.append(entry)
                    if len(upcoming) >= count:
                        break
            except ValueError:
                continue
        return upcoming

    def _moon_phase(self) -> float:
        """Return current moon phase as 0.0 (new) → 0.5 (full) → 1.0 (new)."""
        delta_sec = (datetime.now() - _KNOWN_NEW_MOON).total_seconds()
        return (delta_sec / (_LUNAR_PERIOD_DAYS * 86400)) % 1.0

    def _moon_phase_name(self, phase: float) -> str:
        names = [
            (0.0625, 'New Moon'),
            (0.1875, 'Waxing Crescent'),
            (0.3125, 'First Quarter'),
            (0.4375, 'Waxing Gibbous'),
            (0.5625, 'Full Moon'),
            (0.6875, 'Waning Gibbous'),
            (0.8125, 'Last Quarter'),
            (0.9375, 'Waning Crescent'),
            (1.0001, 'New Moon'),
        ]
        for threshold, name in names:
            if phase < threshold:
                return name
        return 'New Moon'

    def _unit_label(self) -> str:
        return 'ft' if self.units == 'imperial' else 'm'

    def _fmt_height(self, h: float) -> str:
        return f"{h:.1f}{self._unit_label()}"

    def _fmt_time(self, dt_iso: str) -> str:
        try:
            dt = datetime.fromisoformat(dt_iso)
            hour = dt.hour % 12 or 12
            return f"{hour}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"
        except ValueError:
            return '?:??'

    # ─── Drawing primitives ──────────────────────────────────────────────────

    def _draw_wave_bar(self, draw: ImageDraw.Draw, x: int, y_bottom: int,
                       bar_w: int, bar_h: int, fill_ratio: float) -> None:
        """Animated tide-level bar with sine-wave surface."""
        fill_px = max(2, int(bar_h * fill_ratio))
        fill_top = y_bottom - fill_px

        # Solid water fill
        draw.rectangle([x, fill_top + 2, x + bar_w - 1, y_bottom], fill=self.tide_color)

        # Wavy animated surface (2-px amplitude sine)
        for px in range(bar_w):
            wy = fill_top + int(2 * math.sin((px + self.wave_offset) * 0.45))
            wy = max(0, min(y_bottom - 1, wy))
            draw.line([(x + px, wy), (x + px, min(y_bottom, wy + 2))],
                      fill=self.highlight_color)

    def _draw_arrow(self, draw: ImageDraw.Draw, cx: int, cy: int,
                    direction: str, size: int = 5) -> None:
        """Draw a direction arrow (up / down / right for slack)."""
        c = (0, 255, 100) if direction == 'RISING' else \
            (255, 80, 80) if direction == 'FALLING' else (255, 220, 0)
        if direction == 'RISING':
            pts = [(cx, cy - size), (cx - size // 2, cy), (cx + size // 2, cy)]
        elif direction == 'FALLING':
            pts = [(cx, cy + size), (cx - size // 2, cy), (cx + size // 2, cy)]
        else:  # SLACK — horizontal double-headed dash
            draw.line([(cx - size, cy), (cx + size, cy)], fill=c, width=2)
            return
        draw.polygon(pts, fill=c)

    def _draw_moon_icon(self, draw: ImageDraw.Draw, cx: int, cy: int,
                        radius: int, phase: float) -> None:
        """Draw a small moon phase icon at (cx, cy)."""
        # Full circle outline
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.ellipse(bbox, outline=(200, 200, 200), width=1)

        if phase < 0.03 or phase > 0.97:
            return  # New moon — just the outline

        if 0.48 < phase < 0.52:
            # Full moon — filled
            draw.ellipse(bbox, fill=(240, 240, 200), outline=(200, 200, 200))
            return

        # Crescent / gibbous using two overlapping ellipses
        # Lit side: phase < 0.5 = waxing (right lit), > 0.5 = waning (left lit)
        draw.ellipse(bbox, fill=(240, 240, 200), outline=(200, 200, 200))

        # Dark overlay: an ellipse whose horizontal radius varies with phase
        if phase < 0.5:
            # Waxing: dark covers left, shrinks as phase → 0.5
            dark_w = int(radius * 2 * abs(0.5 - phase) * 2)
        else:
            # Waning: dark covers right, grows as phase → 1.0
            dark_w = int(radius * 2 * abs(phase - 0.5) * 2)

        dark_w = max(0, min(radius * 2, dark_w))
        if phase < 0.5:
            dark_x = cx - radius
        else:
            dark_x = cx + radius - dark_w

        dark_bbox = [dark_x, cy - radius, dark_x + dark_w, cy + radius]
        draw.ellipse(dark_bbox, fill=(0, 0, 0))

        # Redraw circle outline on top
        draw.ellipse(bbox, outline=(200, 200, 200), width=1)

    def _get_font(self):
        try:
            return self.display_manager.extra_small_font
        except AttributeError:
            return None

    def _get_small_font(self):
        try:
            return self.display_manager.small_font
        except AttributeError:
            return None

    def _text(self, draw: ImageDraw.Draw, x: int, y: int, text: str,
              color: Tuple = (255, 255, 255), small: bool = True) -> None:
        font = self._get_font() if small else self._get_small_font()
        if font:
            self.display_manager.draw_text(text, x=x, y=y, font=font,
                                           color=color, centered=False)
        else:
            draw.text((x, y), text, fill=color)

    def _text_c(self, draw: ImageDraw.Draw, cx: int, y: int, text: str,
                color: Tuple = (255, 255, 255), small: bool = True) -> None:
        """Draw text centered on cx."""
        font = self._get_font() if small else self._get_small_font()
        if font:
            self.display_manager.draw_text(text, x=cx, y=y, font=font,
                                           color=color, centered=True)
        else:
            w = len(text) * 6
            draw.text((cx - w // 2, y), text, fill=color)

    # ─── Display screens ─────────────────────────────────────────────────────

    def _screen_no_station(self, draw: ImageDraw.Draw, dw: int, dh: int) -> None:
        self._text_c(draw, dw // 2, dh // 2 - 8, 'TIDE DISPLAY', (0, 180, 255))
        self._text_c(draw, dw // 2, dh // 2 + 2, 'Set station ID', (180, 180, 180))

    def _screen_loading(self, draw: ImageDraw.Draw, dw: int, dh: int) -> None:
        self._text_c(draw, dw // 2, dh // 2 - 4, 'Loading tides...', (100, 180, 255))

    def _screen_current(self, draw: ImageDraw.Draw, dw: int, dh: int) -> None:
        """Mode 1: Animated wave bar + direction + current height + next two tides."""
        bar_w = min(28, dw // 6)
        bar_x = 3
        bar_h = dh - 4
        bar_y_bottom = dh - 2

        # Background bar outline
        draw.rectangle([bar_x - 1, bar_y_bottom - bar_h - 1,
                        bar_x + bar_w, bar_y_bottom + 1],
                       outline=(40, 60, 80))

        # Animated water fill
        self._draw_wave_bar(draw, bar_x, bar_y_bottom, bar_w, bar_h,
                            self._fill_ratio())

        # Tide direction label + arrow
        direction = self._tide_direction()
        dir_color = (0, 255, 100) if direction == 'RISING' else \
                    (255, 80, 80) if direction == 'FALLING' else (255, 220, 0)
        text_x = bar_x + bar_w + 5
        self._text(draw, text_x, 2, direction, dir_color)

        # Arrow next to label
        arrow_x = text_x + len(direction) * 4 + 6
        self._draw_arrow(draw, arrow_x, 5, direction, size=4)

        # Current height
        level = self._current_level()
        if level is not None:
            self._text(draw, text_x, 12, self._fmt_height(level), (200, 230, 255))

        # Next two tides
        nexts = self._next_tides(2)
        label_y = 22
        for tide in nexts:
            tide_type = tide.get('type', '?')
            color = (255, 200, 0) if tide_type == 'H' else (100, 200, 255)
            label = f"{'HI' if tide_type == 'H' else 'LO'} {self._fmt_time(tide['dt'])}"
            self._text(draw, text_x, label_y, label, color)
            label_y += 10
            if label_y + 8 > dh:
                break
            self._text(draw, text_x + 4, label_y, self._fmt_height(tide['height']),
                       (180, 180, 180))
            label_y += 12

        # Station name at bottom
        name = self.station_name or self.station_id
        if name:
            self._text(draw, text_x, dh - 8, name[:14], (60, 80, 100))

    def _screen_schedule(self, draw: ImageDraw.Draw, dw: int, dh: int) -> None:
        """Mode 2: Today's tide schedule in up-to-4 columns."""
        if not self.hilo:
            self._screen_loading(draw, dw, dh)
            return

        now = datetime.now()
        tides = self.hilo[:4]  # At most 4 tides per day
        n = len(tides)
        if n == 0:
            return

        col_w = dw // n
        level = self._current_level()
        heights = [e['height'] for e in self.hilo]
        lo_h = min(heights) if heights else 0
        hi_h = max(heights) if heights else 1

        for i, tide in enumerate(tides):
            cx = i * col_w + col_w // 2
            tide_type = tide.get('type', '?')
            is_high = tide_type == 'H'
            try:
                dt = datetime.fromisoformat(tide['dt'])
                is_past = dt < now
            except ValueError:
                is_past = False

            # Color: past tides dimmed
            base_c = (255, 200, 0) if is_high else (100, 200, 255)
            if is_past:
                base_c = tuple(c // 3 for c in base_c)

            # Highlight current/active column with subtle background
            if not is_past:
                try:
                    next_dt = datetime.fromisoformat(tides[i + 1]['dt']) \
                              if i + 1 < n else None
                except (ValueError, IndexError):
                    next_dt = None
                try:
                    this_dt = datetime.fromisoformat(tide['dt'])
                except ValueError:
                    this_dt = None
                if this_dt and now < this_dt:
                    # Next upcoming tide — light glow background
                    if i == next(
                        (j for j, t in enumerate(tides)
                         if not (datetime.fromisoformat(t['dt']) < now
                                 if _safe_isoparse(t['dt']) else True)),
                        None
                    ):
                        draw.rectangle([i * col_w + 1, 0,
                                        i * col_w + col_w - 2, dh - 1],
                                       fill=(0, 20, 40))

            # Type label (HIGH / LOW)
            type_label = 'HIGH' if is_high else 'LOW'
            self._text_c(draw, cx, 1, type_label, base_c)

            # Time
            time_str = self._fmt_time(tide['dt'])
            self._text_c(draw, cx, 11, time_str, (200, 200, 200) if not is_past else (60, 60, 60))

            # Height
            h_str = self._fmt_height(tide['height'])
            self._text_c(draw, cx, 21, h_str, (180, 220, 255) if not is_past else (60, 60, 60))

            # Mini bar at bottom showing relative height
            bar_h_px = int((tide['height'] - lo_h) / max(hi_h - lo_h, 0.01) * 8)
            bar_x1 = i * col_w + 4
            bar_x2 = i * col_w + col_w - 5
            draw.rectangle([bar_x1, dh - 1 - bar_h_px, bar_x2, dh - 1],
                            fill=base_c)

        # Dividers between columns
        for i in range(1, n):
            draw.line([(i * col_w, 0), (i * col_w, dh - 1)], fill=(30, 30, 50))

    def _screen_chart(self, draw: ImageDraw.Draw, dw: int, dh: int) -> None:
        """Mode 3: 24-hour filled tide curve with current-time marker."""
        if not self.hourly:
            self._screen_loading(draw, dw, dh)
            return

        axis_h = 8    # pixels for time axis at bottom
        margin_l = 4
        margin_r = 4
        margin_t = 2

        cx = margin_l
        cy = margin_t
        cw = dw - margin_l - margin_r
        ch = dh - axis_h - margin_t - 1

        heights = self.hourly[:24]
        lo = min(heights)
        hi = max(heights)
        h_range = hi - lo or 1

        def _py(h: float) -> int:
            return cy + ch - int((h - lo) / h_range * ch)

        def _px(hour: int) -> int:
            return cx + int(hour * cw / max(len(heights) - 1, 1))

        # Build chart points
        pts = [(_px(i), _py(h)) for i, h in enumerate(heights)]

        # Filled polygon (area under curve)
        base_y = cy + ch
        poly = pts + [(_px(len(pts) - 1), base_y), (_px(0), base_y)]
        if len(poly) >= 3:
            draw.polygon(poly, fill=(0, 50, 130))

        # Bright line on top of curve
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=self.highlight_color, width=1)

        # High/low labels at peaks and troughs from hilo predictions
        for tide in self.hilo:
            try:
                dt = datetime.fromisoformat(tide['dt'])
                frac_hour = dt.hour + dt.minute / 60.0
                tx = cx + int(frac_hour * cw / 23)
                ty = _py(tide['height'])
                is_high = tide.get('type', '?') == 'H'
                label_color = (255, 220, 0) if is_high else (100, 220, 255)
                sym = 'H' if is_high else 'L'
                lx = max(margin_l, min(dw - 6, tx - 2))
                ly = (ty - 9) if is_high else (ty + 1)
                ly = max(cy, min(cy + ch - 8, ly))
                draw.text((lx, ly), sym, fill=label_color)
                # Small tick at peak/trough
                draw.line([(tx, ty - 1), (tx, ty + 1)], fill=(255, 255, 255))
            except (ValueError, KeyError):
                continue

        # Current time vertical marker (yellow)
        now_frac = datetime.now().hour + datetime.now().minute / 60.0
        now_x = cx + int(now_frac * cw / 23)
        draw.line([(now_x, cy), (now_x, cy + ch)], fill=(255, 230, 0), width=1)

        # Time axis labels at 0h, 6h, 12h, 18h, (24h)
        axis_y = dh - axis_h + 1
        for label_hour, label_text in [(0, '12a'), (6, '6a'), (12, '12p'), (18, '6p')]:
            lx = cx + int(label_hour * cw / 23)
            draw.text((max(0, lx - 5), axis_y), label_text, fill=(100, 120, 150))

        # Thin separator line above axis
        draw.line([(cx, cy + ch + 1), (cx + cw, cy + ch + 1)], fill=(30, 40, 60))

    def _screen_stats(self, draw: ImageDraw.Draw, dw: int, dh: int) -> None:
        """Mode 4: Tidal stats — range, moon phase, spring/neap, station."""
        if not self.hilo:
            self._screen_loading(draw, dw, dh)
            return

        heights = [e['height'] for e in self.hilo]
        lo_h = min(heights)
        hi_h = max(heights)
        tidal_range = hi_h - lo_h
        unit = self._unit_label()

        phase = self._moon_phase()
        phase_name = self._moon_phase_name(phase)

        # Spring vs neap (spring = within 3 days of full/new moon)
        is_spring = phase < 0.1 or phase > 0.9 or 0.4 < phase < 0.6
        tide_type_label = 'SPRING' if is_spring else 'NEAP'
        tide_type_color = (255, 150, 50) if is_spring else (100, 200, 255)

        # Current tidal cycle progress
        now = datetime.now()
        past = [e for e in self.hilo
                if _safe_isoparse(e['dt']) and _safe_isoparse(e['dt']) <= now]
        future = [e for e in self.hilo
                  if _safe_isoparse(e['dt']) and _safe_isoparse(e['dt']) > now]
        cycle_pct = None
        if past and future:
            try:
                prev_dt = datetime.fromisoformat(past[-1]['dt'])
                next_dt = datetime.fromisoformat(future[0]['dt'])
                total_sec = (next_dt - prev_dt).total_seconds()
                elapsed_sec = (now - prev_dt).total_seconds()
                if total_sec > 0:
                    cycle_pct = int(elapsed_sec / total_sec * 100)
            except (ValueError, KeyError):
                pass

        # Layout: moon icon left, stats right
        moon_r = 7
        moon_cx = moon_r + 4
        moon_cy = dh // 2

        if self.show_moon:
            self._draw_moon_icon(draw, moon_cx, moon_cy, moon_r, phase)
            text_x = moon_cx + moon_r + 6
        else:
            text_x = 4

        # Moon phase name
        short_name = phase_name.replace(' Moon', '').replace(' Quarter', ' Qtr')
        self._text(draw, text_x, 2, short_name, (200, 200, 150))

        # Spring / neap
        self._text(draw, text_x, 11, tide_type_label, tide_type_color)

        # Range
        self._text(draw, text_x, 20,
                   f"Range {tidal_range:.1f}{unit}", (150, 200, 255))

        # Today's high and low
        hi_str = f"H:{hi_h:.1f} L:{lo_h:.1f}{unit}"
        self._text(draw, text_x, 29, hi_str, (180, 180, 200))

        # Cycle progress bar at bottom
        if cycle_pct is not None:
            bar_y = dh - 4
            bar_x0 = text_x
            bar_x1 = dw - 4
            bar_len = bar_x1 - bar_x0
            fill_len = int(bar_len * cycle_pct / 100)
            draw.rectangle([bar_x0, bar_y, bar_x1, bar_y + 2], fill=(30, 40, 60))
            draw.rectangle([bar_x0, bar_y, bar_x0 + fill_len, bar_y + 2],
                           fill=(0, 150, 255))
            self._text(draw, bar_x0, bar_y - 9, f"Cycle {cycle_pct}%",
                       (80, 100, 130))

    # ─── on_config_change ─────────────────────────────────────────────────────

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)

        def _rgb(key, default):
            raw = self.config.get(key, list(default))
            try:
                return tuple(int(c) for c in raw)
            except (TypeError, ValueError):
                return default

        self.station_id = str(self.config.get('station_id', '')).strip()
        self.station_name = str(self.config.get('station_name', '') or '').strip()
        self.units = self.config.get('units', 'imperial')
        self.mode_duration = float(self.config.get('display_duration', 12))
        self.show_moon = bool(self.config.get('show_moon_phase', True))
        self.tide_color = _rgb('tide_color', (0, 100, 200))
        self.highlight_color = _rgb('highlight_color', (0, 220, 255))

        # Clear cached data so new station is fetched immediately
        self.hilo = []
        self.hourly = []
        self.live_level = None
        self.update()
        self.logger.info("TidePlugin config updated: station=%s", self.station_id)


# ─── Utility ─────────────────────────────────────────────────────────────────

def _safe_isoparse(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
