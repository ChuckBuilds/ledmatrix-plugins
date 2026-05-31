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

import math, time, logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw

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
C_GRID        = ( 14,  24,  52)
C_NOW_LINE    = (255, 220,  40)
C_HIGH        = (255, 195,  45)
C_LOW         = ( 75, 190, 255)
C_RISING      = ( 45, 230,  95)
C_FALLING     = (255,  75,  75)
C_SLACK       = (255, 210,  60)
C_TEXT        = (205, 225, 255)
C_LABEL       = ( 95, 125, 180)
C_DIM         = ( 45,  55,  80)
C_MOON        = (245, 238, 200)
C_BAR_OUT     = ( 25,  45,  90)
C_COL_BG      = (  0,  14,  40)
# Schedule column tints
C_HIGH_TINT   = ( 30,  20,   5)  # warm amber hint
C_LOW_TINT    = (  0,  10,  30)  # cool blue hint


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * max(0.0, min(1.0, t))) for a, b in zip(c1, c2))

def _safe_iso(s):
    try:    return datetime.fromisoformat(s)
    except: return None


# ── Layout helper ──────────────────────────────────────────────────────────────

def _layout(dw: int, dh: int) -> Dict:
    c_ml, c_mr, c_mt = 3, 3, 1
    c_axis = max(7, int(dh * 0.16))
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
            try:   return tuple(max(0, min(255, int(c))) for c in config.get(k, list(d)))
            except: return d

        self.station_id   = str(config.get('station_id', '')).strip()
        self.station_name = str(config.get('station_name', '') or '').strip()
        self.units        = config.get('units', 'imperial')
        self.mode_dur     = float(config.get('display_duration', 12))
        self.show_moon    = bool(config.get('show_moon_phase', True))
        self.tide_color   = _rgb('tide_color',      C_WATER_MID)
        self.hi_color     = _rgb('highlight_color', C_WAVE1)

        self.mode_idx   = 0
        self.mode_start = time.time()
        self.wave_phase = 0.0

        self.hilo:   List[Dict]      = []
        self.hourly: List[float]     = []
        self.live:   Optional[float] = None

    # ── BasePlugin ──────────────────────────────────────────────────────────────

    def update(self):
        if not self.station_id: return
        today   = date.today().strftime('%Y%m%d')
        u       = 'english' if self.units == 'imperial' else 'metric'

        hilo_key    = f"{self.plugin_id}:hilo:{self.station_id}:{today}"
        hourly_key  = f"{self.plugin_id}:hourly:{self.station_id}:{today}"
        live_key    = f"{self.plugin_id}:live:{self.station_id}"

        c = self.cache_manager.get(hilo_key, max_age=86400)
        if not c: c = self._fetch_hilo(u)
        if c: self.cache_manager.set(hilo_key, c)
        self.hilo = c or []

        ch = self.cache_manager.get(hourly_key, max_age=21600)
        if not ch: ch = self._fetch_hourly(u)
        if ch: self.cache_manager.set(hourly_key, ch)
        self.hourly = ch or []

        lv = self.cache_manager.get(live_key, max_age=360)
        if lv is None: lv = self._fetch_live(u)
        if lv is not None: self.cache_manager.set(live_key, lv)
        self.live = lv

    def display(self, force_clear=False):
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

    def supports_dynamic_duration(self): return True
    def get_display_duration(self):      return self.mode_dur
    def reset_cycle_state(self):         self.mode_start = time.time()

    def is_cycle_complete(self):
        if time.time() - self.mode_start >= self.mode_dur:
            self.mode_idx   = (self.mode_idx + 1) % len(self.MODES)
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
            if 'error' in d: return None
            out = []
            for x in d.get('predictions', []):
                try: out.append({'dt':datetime.strptime(x['t'],'%Y-%m-%d %H:%M').isoformat(),
                                 'height':float(x['v']),'type':x.get('type','?')})
                except: pass
            return out or None
        except Exception as e: self.logger.error("hilo: %s", e); return None

    def _fetch_hourly(self, u):
        try:
            t  = date.today().strftime('%Y%m%d')
            p  = {**self._base(u),'product':'predictions','interval':'h','begin_date':t,'end_date':t}
            r  = requests.get(NOAA_BASE, params=p, timeout=10); r.raise_for_status()
            d  = r.json()
            if 'error' in d: return None
            h  = []
            for x in d.get('predictions',[]):
                try: h.append(float(x['v']))
                except: h.append(0.0)
            h = h[:24]
            while len(h) < 24: h.append(h[-1] if h else 0.0)
            return h
        except Exception as e: self.logger.error("hourly: %s", e); return None

    def _fetch_live(self, u):
        try:
            p = {**self._base(u),'product':'water_level','date':'latest'}
            r = requests.get(NOAA_BASE, params=p, timeout=8); r.raise_for_status()
            d = r.json()
            if 'error' in d: return None
            data = d.get('data',[])
            return float(data[-1]['v']) if data else None
        except: return None

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
        except: return '--'

    def _name(self): return (self.station_name or self.station_id)[:14]

    # ── Drawing helpers ─────────────────────────────────────────────────────────

    def _draw_stars(self, draw, dw: int, sky_h: int) -> None:
        """Scatter faint star-like pixels in the sky area for atmosphere."""
        import random
        rng = random.Random(42)  # fixed seed = stable starfield
        n   = max(0, (dw * sky_h) // 120)
        for _ in range(n):
            sx = rng.randint(0, dw-1)
            sy = rng.randint(0, sky_h-2)
            b  = rng.randint(18, 50)
            draw.point((sx, sy), fill=(b, b+8, b+22))

    def _wave_y(self, px: int) -> float:
        """Composite multi-frequency wave giving a natural, non-mechanical surface."""
        p = self.wave_phase
        y1 = math.sin((px + p)         * 0.28) * 1.3   # primary swell
        y2 = math.sin((px + p * 1.35)  * 0.47) * 0.7   # secondary chop
        y3 = math.sin((px + p * 0.72)  * 0.71) * 0.35  # fine ripple
        return y1 + y2 + y3  # max ≈ ±2.35px, stays within 3px amplitude

    def _full_wave(self, canvas, draw, dw, dh, fill_ratio, amp):
        """
        Full-display animated water gradient with composite-sine wave surface.

        Sky (C_BG → C_SKY_HORIZON) and water (C_WATER_TOP → C_WATER_DEEP) share
        the same colour at the horizon so there is no luminance jump.
        Wave amplitude is capped at 2 px so it never clips into text above it.
        """
        effective = min(fill_ratio, 0.45)
        fill_px   = max(4, int(dh * effective))
        surf_y    = dh - fill_px

        # Sky: deep teal-black at zenith → indigo at horizon (ease-out)
        sky_top = (2, 4, 18)
        for py in range(surf_y + 1):
            t = py / max(surf_y, 1)
            draw.line([(0,py),(dw-1,py)], fill=_lerp(sky_top, C_SKY_HORIZON, t*t))

        # Starfield for atmosphere
        self._draw_stars(draw, dw, surf_y)

        # Water: indigo at surface → rich mid-blue → deep navy
        for py in range(surf_y, dh):
            t = (py - surf_y) / max(fill_px, 1)
            if t < 0.5:
                color = _lerp(C_WATER_TOP, C_WATER_MID, t * 2)
            else:
                color = _lerp(C_WATER_MID, C_WATER_DEEP, (t - 0.5) * 2)
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
                draw.point((px, wy), fill=_lerp(C_WAVE1, C_WAVE_CREST, bt * 0.72))
                if wy + 1 < dh:
                    draw.point((px, wy+1), fill=_lerp(C_WATER_TOP, C_WAVE1, 0.7))

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

    def _txt(self, x, y, text, color=C_TEXT, small=True):
        font = self.display_manager.extra_small_font if small else self.display_manager.small_font
        try: self.display_manager.draw_text(text, x=x, y=y, font=font, color=color, centered=False)
        except: pass

    def _txtc(self, cx, y, text, color=C_TEXT, small=True):
        font = self.display_manager.extra_small_font if small else self.display_manager.small_font
        try: self.display_manager.draw_text(text, x=cx, y=y, font=font, color=color, centered=True)
        except: pass

    # ── Placeholder screens ─────────────────────────────────────────────────────

    def _no_station(self, draw, dw, dh, L):
        draw.rectangle([0,0,dw-1,dh-1], outline=C_BAR_OUT)
        self._txtc(dw//2, L['row1'], 'TIDE DISPLAY', C_WAVE1)
        self._txtc(dw//2, L['row2'], 'Set station ID', C_LABEL)

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
        r3  = r2 + 8 if (r2 + 8) < sky_h - 7 else None
        r4  = r3 + 7 if r3 and (r3 + 7) < sky_h - 7 else None

        dir_c = (C_RISING if direction=='RISING'
                 else C_FALLING if direction=='FALLING' else C_SLACK)

        # LEFT: direction + height
        self._txt(3, r1, direction, dir_c)  # extra_small_font
        # Inline arrow to the right of the direction label
        arr_x = 3 + len(direction) * 4 + 3
        if arr_x < dw // 2 - 6:
            self._dir_arrow(draw, arr_x, r1 + 3, direction, sz=3)
        if lv is not None:
            self._txt(3, r2, self._fmth(lv), C_TEXT)

        # Divider
        mid = dw // 2 - 1
        if sky_h > 12:
            draw.line([(mid, PAD), (mid, sky_h - PAD)], fill=C_BAR_OUT)

        # RIGHT: next two tides
        rx    = dw // 2 + 3
        nexts = self._next_tides(2)

        if nexts:
            t0  = nexts[0]
            tc0 = C_HIGH if t0.get('type','?') == 'H' else C_LOW
            sym = 'HI' if t0.get('type','?') == 'H' else 'LO'
            self._txt(rx, r1, sym, tc0)
            self._txt(rx + 14, r1, self._fmtt(t0['dt']), C_TEXT)
            self._txt(rx + 14, r2, self._fmth(t0['height']), tc0)

        if len(nexts) >= 2 and r3 is not None:
            t1  = nexts[1]
            tc1 = C_HIGH if t1.get('type','?') == 'H' else C_LOW
            sym2 = 'HI' if t1.get('type','?') == 'H' else 'LO'
            self._txt(rx, r3, sym2, tc1)
            self._txt(rx + 14, r3, self._fmtt(t1['dt']), C_TEXT)
            if r4 is not None:
                self._txt(rx + 14, r4, self._fmth(t1['height']), tc1)

        # Station + % at bottom of sky, clear of wave
        last = (r4 or r3 or r2) + 8
        if last + 5 < sky_h:
            self._txt(3, last + 2, self._name(), C_DIM)
            pct = int(fill_ratio * 100)
            self._txt(dw - len(f"{pct}%") * 4 - 3, last + 2, f"{pct}%", C_LABEL)

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

            # Column background: warm tint for HIGH, cool for LOW
            bg = _lerp(C_COL_BG, C_HIGH_TINT if is_high else C_LOW_TINT, 0.5)
            if i == next_idx:
                bg = _lerp(bg, tc, 0.08)  # subtle glow for next upcoming

            draw.rectangle([i*col_w+1, 0, i*col_w+col_w-2, dh-3], fill=bg)

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

            # Mini proportional bar at bottom
            bar_h_px = max(1, int((tide['height']-lo_h)/h_range * 5))
            bx1, bx2 = i*col_w+3, i*col_w+col_w-4
            draw.rectangle([bx1, dh-2-bar_h_px, bx2, dh-1],
                           fill=tc if not is_past else C_DIM)

        # Column dividers
        for i in range(1, n):
            draw.line([(i*col_w, 1),(i*col_w, dh-4)], fill=C_BAR_OUT)

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

        # Glow: three passes (outer → inner → bright)
        for dy, gc in [(2, C_CHART_GLOW2),(1, C_CHART_GLOW1),(0, C_CHART_LINE)]:
            for i in range(len(pts)-1):
                x1,y1 = pts[i]; x2,y2 = pts[i+1]
                draw.line([(x1,y1+dy),(x2,y2+dy)], fill=gc, width=1)
                if dy: draw.line([(x1,y1-dy),(x2,y2-dy)], fill=gc, width=1)

        # H / L labels at peaks/troughs
        for tide in self.hilo:
            try:
                dt      = datetime.fromisoformat(tide['dt'])
                frac    = dt.hour + dt.minute/60.0
                tx      = cx + int(frac*cw/23)
                ty      = _py(tide['height'])
                is_high = tide.get('type','?') == 'H'
                lc      = C_HIGH if is_high else C_LOW
                sym     = 'H' if is_high else 'L'
                lx = max(cx, min(cx+cw-5, tx-2))
                ly = max(cy, min(cy+ch-8, (ty-9) if is_high else (ty+2)))
                draw.text((lx,ly), sym, fill=lc)
                draw.line([(tx,ty-1),(tx,ty+1)], fill=(255,255,255))
            except: pass

        # Current-time marker
        now_frac = datetime.now().hour + datetime.now().minute/60.0
        now_x    = cx + int(now_frac*cw/23)
        draw.line([(now_x,cy),(now_x,cy+ch)], fill=C_NOW_LINE, width=1)
        cur_py = _py(heights[min(int(now_frac), len(heights)-1)])
        r = max(1, dh//20)
        draw.ellipse([now_x-r,cur_py-r,now_x+r,cur_py+r], outline=C_NOW_LINE, width=1)
        if r > 1:
            draw.ellipse([now_x-r+1,cur_py-r+1,now_x+r-1,cur_py+r-1],
                         fill=_lerp(C_BG, C_NOW_LINE, 0.4))

        # Time axis
        ax_y   = cy + ch + 2
        labels = [(0,'12a'),(6,'6a'),(12,'12p'),(18,'6p')]
        if L['small']: labels = [(0,'0'),(12,'12')]
        for lh, lt in labels:
            lx = cx + int(lh*cw/23)
            draw.text((max(0,lx-4), ax_y), lt, fill=C_LABEL)

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
            except: pass

        # Left side: moon + text
        moon_r  = max(4, min(10, dh//5))
        moon_cx = moon_r + 3
        moon_cy = dh//2 - (5 if L['small'] else 8)

        if self.show_moon:
            self._moon_icon(draw, moon_cx, moon_cy, moon_r, phase)
            txt_x = moon_cx + moon_r + 5
        else:
            txt_x = 4

        short = phase_name.replace(' Moon','').replace(' Quarter',' Qtr')
        if L['small']: short = short[:6]
        self._txt(txt_x, L['row1'], short, C_MOON)
        self._txt(txt_x, L['row2'], spring_lbl, spring_c)
        self._txt(txt_x, L['row3'], f"Rng {tidal_range:.1f}{self._unit()}", C_LOW)
        if not L['small']:
            self._txt(txt_x, L['row4'], f"H {hi_h:.1f}  L {lo_h:.1f}", C_LABEL)

        # Right side: vertical tide gauge bar (wider, gradient fill)
        if L['large'] or L['medium']:
            gw      = 8
            gx      = dw - gw - 4
            gy      = 3
            gh      = dh - 16
            fr      = self._fill_ratio()
            fh      = max(1, int(gh * fr))
            fy0     = gy + gh - fh

            draw.rectangle([gx, gy, gx+gw-1, gy+gh], fill=(0,8,25), outline=C_BAR_OUT)
            # Gradient fill: water mid at bottom → wave base at top of fill
            for py in range(fy0, gy+gh):
                t2 = (gy+gh - py) / max(fh, 1)
                draw.line([(gx+1, py),(gx+gw-2, py)], fill=_lerp(C_WATER_MID, C_WAVE1, t2*0.6))
            # Micro wave on fill surface
            for px in range(gw-2):
                wy = fy0 + int(math.sin((px+self.wave_phase)*0.8))
                wy = max(gy+1, min(gy+gh-1, wy))
                draw.point((gx+1+px, wy), fill=C_WAVE_CREST)
            # Tick marks
            for pct2 in (0.25, 0.5, 0.75):
                ty2 = gy + gh - int(gh*pct2)
                draw.line([(gx-2, ty2),(gx, ty2)], fill=C_LABEL)
            # % label centred under gauge
            pct_g = int(fr*100)
            draw.text((gx+(gw-len(f"{pct_g}%")*4)//2, gy+gh+3), f"{pct_g}%", fill=C_LABEL)

        # Cycle progress bar — gradient fill, 3px thick
        if cycle_pct is not None:
            bar_y  = dh - 5
            bar_x0 = txt_x
            bar_x1 = dw - (gw + 10 if (L['large'] or L['medium']) else 3)
            blen   = bar_x1 - bar_x0
            flen   = int(blen * cycle_pct / 100)
            draw.rectangle([bar_x0, bar_y, bar_x1, bar_y+3], fill=(0,8,25))
            for px in range(flen):
                t2 = px / max(flen, 1)
                draw.line([(bar_x0+px, bar_y),(bar_x0+px, bar_y+3)], fill=_lerp(C_LOW, C_HIGH, t2))
            draw.text((bar_x1+2, bar_y-1), f"{cycle_pct}%", fill=C_LABEL)

    # ── Config change ────────────────────────────────────────────────────────────

    def on_config_change(self, new_config):
        super().on_config_change(new_config)
        def _rgb(k, d):
            try:   return tuple(max(0, min(255, int(c))) for c in self.config.get(k, list(d)))
            except: return d
        self.station_id   = str(self.config.get('station_id',   '')).strip()
        self.station_name = str(self.config.get('station_name', '') or '').strip()
        self.units        = self.config.get('units', 'imperial')
        self.mode_dur     = float(self.config.get('display_duration', 12))
        self.show_moon    = bool(self.config.get('show_moon_phase', True))
        self.tide_color   = _rgb('tide_color',      C_WATER_MID)
        self.hi_color     = _rgb('highlight_color', C_WAVE1)
        self.hilo = []; self.hourly = []; self.live = None
        self.update()
