#!/usr/bin/env python3
"""
Render tide-display plugin preview images without needing the full LEDMatrix system.
Outputs one PNG per mode per display size, plus a composite sheet.

Usage:  python3 render_preview.py
"""

import math, os
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

# ── Palette (must match manager.py) ──────────────────────────────────────────
C_BG          = (  0,   0,   5)
C_SKY_HORIZON = (  0,  20,  65)
C_WATER_TOP   = (  0,  30,  90)
C_WATER_MID   = (  0,  65, 160)
C_WATER_DEEP  = (  0,  40, 120)
C_WAVE1       = (  0, 140, 220)
C_WAVE_CREST  = (160, 240, 255)
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
C_COL_HIGH      = ( 31,  23,  10)
C_COL_LOW       = (  9,  23,  36)
C_COL_HIGH_NEXT = ( 56,  43,  15)
C_COL_LOW_NEXT  = ( 16,  42,  61)
# aliases for backward compat with render helpers
C_BAR_OUTLINE = C_BAR_OUT


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

def _safe_iso(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None

def _layout(dw, dh):
    c_ml, c_mr, c_mt = 3, 3, 1
    c_axis = max(9, int(dh * 0.20))  # 9px min: 1px line + 2px gap + 6px font
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

# ── Fake tide data (Seattle-ish semi-diurnal) ─────────────────────────────────
_BASE = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

def _make_hilo():
    """Four typical semi-diurnal tides for today."""
    return [
        {'dt': (_BASE + timedelta(hours=2,  minutes=24)).isoformat(), 'height': 5.6, 'type': 'H'},
        {'dt': (_BASE + timedelta(hours=8,  minutes=47)).isoformat(), 'height': 0.8, 'type': 'L'},
        {'dt': (_BASE + timedelta(hours=15, minutes=13)).isoformat(), 'height': 4.9, 'type': 'H'},
        {'dt': (_BASE + timedelta(hours=21, minutes=35)).isoformat(), 'height': 1.2, 'type': 'L'},
    ]

def _make_hourly():
    """24-point cosine curve matching the hilo data."""
    hrs = []
    for h in range(24):
        v = (3.2 + 2.4 * math.cos((h - 2.4) * 2 * math.pi / 12.4)
                  + 0.6 * math.cos((h - 2.4) * 2 * math.pi / 24.8))
        hrs.append(max(0.2, v))
    return hrs


# ── Font loader ────────────────────────────────────────────────────────────────
def _load_fonts():
    search = [
        "/var/home/chuck/Github/LEDMatrix/assets/fonts/4x6-font.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for path in search:
        if os.path.exists(path):
            try:
                tiny  = ImageFont.truetype(path, 6)
                small = ImageFont.truetype(path, 7)
                return tiny, small
            except OSError:
                continue
    # Fallback to PIL default
    def_ = ImageFont.load_default()
    return def_, def_

FONT_TINY, FONT_SMALL = _load_fonts()

def _txt(draw, x, y, text, color=C_TEXT, font=None):
    draw.text((x, y), text, fill=color, font=font or FONT_TINY)

def _txt_c(draw, cx, y, text, color=C_TEXT, font=None):
    fnt  = font or FONT_TINY
    bbox = draw.textbbox((0, 0), text, font=fnt)
    w    = bbox[2] - bbox[0]
    draw.text((cx - w // 2, y), text, fill=color, font=fnt)


# ── Drawing helpers (same logic as manager.py) ─────────────────────────────────

WAVE_PHASE = 24.0  # fixed phase for preview

def _wave_y(px, wave_phase=WAVE_PHASE):
    p = wave_phase
    y1 = math.sin((px + p)         * 0.28) * 0.85
    y2 = math.sin((px + p * 1.35)  * 0.47) * 0.45
    y3 = math.sin((px + p * 0.72)  * 0.71) * 0.2
    return y1 + y2 + y3

def _draw_stars(draw, dw, sky_h):
    n = max(0, (dw * sky_h) // 120)
    h = 2654435761
    for i in range(n):
        h = (h ^ (i * 2246822519 + 1)) & 0xFFFFFFFF
        sx = h % dw
        sy = (h >> 16) % max(1, sky_h - 2)
        b  = 18 + (h >> 8) % 34
        draw.point((sx, sy), fill=(b, b + 8, b + 22))

def full_wave(canvas, draw, dw, dh, fill_ratio, wave_phase=WAVE_PHASE):
    """Full-display animated water: mirrors manager.py _full_wave()."""
    effective = min(fill_ratio, 0.18)
    fill_px   = max(4, int(dh * effective))
    surf_y    = dh - fill_px

    sky_top = (2, 4, 18)
    for py in range(surf_y + 1):
        t = py / max(surf_y, 1)
        draw.line([(0,py),(dw-1,py)], fill=_lerp(sky_top, C_SKY_HORIZON, t*t))

    _draw_stars(draw, dw, surf_y)

    for py in range(surf_y, dh):
        t = (py - surf_y) / max(fill_px, 1)
        if t < 0.5:
            color = _lerp(C_WATER_TOP, C_WATER_MID, t * 2)
        else:
            color = _lerp(C_WATER_MID, C_WATER_DEEP, (t - 0.5) * 2)
        draw.line([(0,py),(dw-1,py)], fill=color)

    horizon_c = _lerp(_lerp(C_SKY_HORIZON, C_WATER_TOP, 0.5), (80, 140, 220), 0.35)
    draw.line([(0, surf_y), (dw-1, surf_y)], fill=horizon_c)

    wave_ys = [surf_y + int(_wave_y(px, wave_phase)) for px in range(dw)]

    for px in range(dw):
        wy = wave_ys[px]
        if 0 <= wy < surf_y:
            bt = (math.sin((px + wave_phase * 1.3) * 0.11) + 1) * 0.5
            draw.point((px, wy), fill=_lerp(C_WAVE1, C_WAVE_CREST, bt * 0.72))
            if wy + 1 < dh:
                draw.point((px, wy+1), fill=_lerp(C_WATER_TOP, C_WAVE1, 0.7))

    for px in range(0, dw):
        wy_p = wave_ys[max(0, px-2)]
        wy_c = wave_ys[px]
        wy_n = wave_ys[min(dw-1, px+2)]
        if wy_c <= wy_p and wy_c <= wy_n and wy_c < surf_y:
            wy = wy_c - 1
            if 0 <= wy < dh:
                draw.point((px, wy), fill=(220, 252, 255))

    return surf_y

def _txt_s(draw, x, y, text, color=C_TEXT, font=None):
    """Draw text with a 1px drop shadow."""
    fnt = font or FONT_TINY
    draw.text((x + 1, y + 1), text, fill=(0, 0, 8), font=fnt)
    draw.text((x, y), text, fill=color, font=fnt)

def draw_arrow(draw, cx, cy, direction, sz=4):
    c = C_RISING if direction=='RISING' else C_FALLING if direction=='FALLING' else C_SLACK
    if direction == 'RISING':
        draw.polygon([(cx,cy-sz),(cx-sz,cy+sz//2),(cx+sz,cy+sz//2)], fill=c)
    elif direction == 'FALLING':
        draw.polygon([(cx,cy+sz),(cx-sz,cy-sz//2),(cx+sz,cy-sz//2)], fill=c)
    else:
        draw.line([(cx-sz,cy),(cx+sz,cy)], fill=c, width=2)

def draw_moon(draw, cx, cy, r, phase):
    bbox = [cx-r, cy-r, cx+r, cy+r]
    if phase < 0.04 or phase > 0.96:
        draw.ellipse(bbox, outline=C_LABEL, width=1); return
    if 0.47 < phase < 0.53:
        draw.ellipse(bbox, fill=C_MOON, outline=C_MOON); return
    draw.ellipse(bbox, fill=C_MOON, outline=C_MOON)
    frac   = abs(phase - 0.5) * 2
    dark_w = max(0, min(r*2, int(r*2*frac)))
    dx = (cx - r) if phase < 0.5 else (cx + r - dark_w)
    if dark_w > 0:
        draw.ellipse([dx, cy-r, dx+dark_w, cy+r], fill=C_BG)
    draw.ellipse(bbox, outline=_lerp(C_BG, C_MOON, 0.4), width=1)

def _fmth(h, unit='ft'): return f"{h:.1f}{unit}"
def _fmtt(iso):
    try:
        dt = datetime.fromisoformat(iso)
        hr = dt.hour % 12 or 12
        return f"{hr}:{dt.minute:02d}{'a' if dt.hour<12 else 'p'}"
    except (TypeError, ValueError):
        return '--'

# ── Mode renderers ─────────────────────────────────────────────────────────────

def render_current(dw, dh, hilo, hourly, phase=24.0):
    canvas = Image.new('RGB', (dw, dh), C_BG)
    draw   = ImageDraw.Draw(canvas)
    L      = _layout(dw, dh)

    heights    = [e['height'] for e in hilo]
    lo_h, hi_h = min(heights), max(heights)
    cur_level  = lo_h + (hi_h - lo_h) * 0.42
    fill_ratio = (cur_level - lo_h) / max(hi_h - lo_h, 0.01)
    direction  = 'RISING'

    surf_y = full_wave(canvas, draw, dw, dh, fill_ratio, phase)
    sky_h  = surf_y

    PAD = 2
    r1  = PAD
    r2  = r1 + 8
    r3  = r2 + 8 if (r2 + 8) < sky_h - 4 else None
    r4  = r3 + 7 if r3 and (r3 + 7) < sky_h - 4 else None

    dir_c = C_RISING
    _txt_s(draw, 3, r1, direction, dir_c)
    arr_x = 3 + len(direction) * 4 + 3
    if arr_x < dw // 2 - 6:
        draw_arrow(draw, arr_x, r1 + 3, direction, sz=3)
    _txt_s(draw, 3, r2, _fmth(cur_level), C_TEXT)

    mid = dw // 2 - 1
    if sky_h > 12:
        draw.line([(mid, PAD), (mid, sky_h - PAD)], fill=C_BAR_OUT)

    rx    = dw // 2 + 3
    now   = datetime.now()
    nexts = [e for e in hilo if _safe_iso(e['dt']) and _safe_iso(e['dt']) > now][:2]

    if nexts:
        t0  = nexts[0]
        sym = 'HI' if t0.get('type','?') == 'H' else 'LO'
        _txt_s(draw, rx, r1, f"{sym} {_fmtt(t0['dt'])}", C_TEXT)
        tc0 = C_HIGH if t0.get('type','?') == 'H' else C_LOW
        _txt_s(draw, rx, r2, _fmth(t0['height']), tc0)

    if len(nexts) >= 2 and r3 is not None:
        t1   = nexts[1]
        sym2 = 'HI' if t1.get('type','?') == 'H' else 'LO'
        tc1  = C_HIGH if t1.get('type','?') == 'H' else C_LOW
        _txt_s(draw, rx, r3, f"{sym2} {_fmtt(t1['dt'])}", C_TEXT)
        if r4 is not None:
            _txt_s(draw, rx, r4, _fmth(t1['height']), tc1)

    last = (r4 or r3 or r2) + 8
    if last + 5 < sky_h:
        _txt_s(draw, 3, last + 2, 'Seattle', C_LABEL)
        pct_str = f"{int(fill_ratio * 100)}%"
        pct_w   = len(pct_str) * 4 + 2
        _txt_s(draw, dw - pct_w - 2, last + 2, pct_str, C_LABEL)

    return canvas


def render_schedule(dw, dh, hilo):
    canvas = Image.new('RGB', (dw, dh), C_BG)
    draw   = ImageDraw.Draw(canvas)
    L      = _layout(dw, dh)
    now    = datetime.now()
    tides  = hilo[:4]
    n      = len(tides)
    if n == 0: return canvas

    col_w  = dw // n
    heights = [e['height'] for e in hilo]
    lo_h, hi_h = min(heights), max(heights)
    h_range = max(hi_h - lo_h, 0.01)

    # simulate next upcoming = index 1 (2nd tide, the low)
    next_idx = 1

    for i, tide in enumerate(tides):
        cx      = i * col_w + col_w // 2
        is_high = tide.get('type','?') == 'H'
        dt      = _safe_iso(tide['dt'])
        is_past = dt is not None and dt < now
        tc      = C_HIGH if is_high else C_LOW

        if i == next_idx:
            bg = C_COL_HIGH_NEXT if is_high else C_COL_LOW_NEXT
        else:
            bg = C_COL_HIGH if is_high else C_COL_LOW
        draw.rectangle([i*col_w+1, 0, i*col_w+col_w-2, dh-3], fill=bg)
        if i == next_idx:
            draw.line([(i*col_w+1, 0), (i*col_w+col_w-2, 0)], fill=tc)

        type_label = ('HIGH' if is_high else 'LOW') if not L['small'] else ('H' if is_high else 'L')
        _txt_c(draw, cx, L['row1'], type_label, tc if not is_past else C_DIM, FONT_TINY)
        _txt_c(draw, cx, L['row2'], _fmtt(tide['dt']), C_TEXT if not is_past else C_DIM, FONT_TINY)
        _txt_c(draw, cx, L['row3'], _fmth(tide['height']),
               _lerp(C_LOW, C_HIGH, (tide['height']-lo_h)/h_range) if not is_past else C_DIM,
               FONT_TINY)

        bar_max  = max(3, dh - L['row3'] - 10)
        bar_h_px = max(2, int((tide['height']-lo_h)/h_range * bar_max))
        bx1, bx2 = i*col_w+3, i*col_w+col_w-4
        bar_color = tc if not is_past else _lerp(C_DIM, tc, 0.3)
        draw.rectangle([bx1, dh-2-bar_h_px, bx2, dh-1], fill=bar_color)
        if i == next_idx:
            draw.rectangle([bx1, dh-2-bar_h_px, bx2, dh-1], outline=C_TEXT)

    for i in range(1, n):
        draw.line([(i*col_w, 0), (i*col_w, dh-1)], fill=C_BAR_OUT)

    return canvas


def render_chart(dw, dh, hilo, hourly):
    canvas = Image.new('RGB', (dw, dh), C_BG)
    draw   = ImageDraw.Draw(canvas)
    L      = _layout(dw, dh)

    cx, cy = L['c_x'], L['c_y']
    cw, ch = L['c_w'], L['c_h']

    heights = hourly[:24]
    lo, hi  = min(heights), max(heights)
    h_range = hi - lo or 1.0

    def _py(h): return cy + ch - int((h-lo)/h_range*ch)
    def _px(i): return cx + int(i * cw / max(len(heights)-1, 1))

    for pct in (0.25, 0.5, 0.75):
        gy = cy + ch - int(pct*ch)
        draw.line([(cx, gy), (cx+cw, gy)], fill=C_GRID)

    pts = [(_px(i), _py(h)) for i,h in enumerate(heights)]

    base_y = cy + ch
    poly   = pts + [(_px(len(pts)-1), base_y), (_px(0), base_y)]
    if len(poly) >= 3:
        draw.polygon(poly, fill=C_CHART_FILL)

    for dy, gc in [(2, C_CHART_GLOW2), (1, C_CHART_GLOW1), (0, C_CHART_LINE)]:
        for i in range(len(pts)-1):
            x1,y1 = pts[i]; x2,y2 = pts[i+1]
            draw.line([(x1,y1+dy),(x2,y2+dy)], fill=gc, width=1)
            if dy > 0:
                draw.line([(x1,y1-dy),(x2,y2-dy)], fill=gc, width=1)

    for tide in hilo:
        try:
            dt      = datetime.fromisoformat(tide['dt'])
            frac_hr = dt.hour + dt.minute/60.0
            tx2     = cx + int(frac_hr * cw / 23)
            ty2     = _py(tide['height'])
            is_high = tide.get('type','?') == 'H'
            lc      = C_HIGH if is_high else C_LOW
            sym     = 'H' if is_high else 'L'
            lx = max(cx, min(cx+cw-5, tx2-2))
            ly = max(cy, min(cy+ch-8, (ty2-9) if is_high else (ty2+2)))
            draw.text((lx, ly), sym, fill=lc, font=FONT_TINY)
            draw.line([(tx2, ty2-1),(tx2, ty2+1)], fill=(255,255,255))
        except (KeyError, ValueError, TypeError):
            continue

    # Current time — fix at 10:30 for preview
    now_frac = 10.5
    now_x = cx + int(now_frac * cw / 23)
    draw.line([(now_x, cy),(now_x, cy+ch)], fill=C_NOW_LINE, width=1)
    cur_h_idx = min(int(now_frac), len(heights)-1)
    cur_py    = _py(heights[cur_h_idx])
    r = max(1, dh // 20)
    draw.ellipse([now_x-r, cur_py-r, now_x+r, cur_py+r], outline=C_NOW_LINE, width=1)
    if r > 1:
        draw.ellipse([now_x-r+1, cur_py-r+1, now_x+r-1, cur_py+r-1],
                     fill=_lerp(C_BG, C_NOW_LINE, 0.45))

    ax_y = min(dh - 7, cy + ch + 2)  # guarantee 7px room to bottom
    ax_labels = [(0,'12a'),(6,'6a'),(12,'12p'),(18,'6p')]
    if L['small']: ax_labels = [(0,'0'),(12,'12')]
    for lh, lt in ax_labels:
        lx   = cx + int(lh * cw / 23)
        tw   = len(lt) * 4
        label_x = max(0, min(dw - tw - 1, lx - tw // 2))
        draw.text((label_x, ax_y), lt, fill=C_LABEL, font=FONT_TINY)

    draw.line([(cx, cy+ch+1),(cx+cw, cy+ch+1)], fill=C_BAR_OUTLINE)
    return canvas


def render_stats(dw, dh, hilo):
    canvas = Image.new('RGB', (dw, dh), C_BG)
    draw   = ImageDraw.Draw(canvas)
    L      = _layout(dw, dh)

    heights     = [e['height'] for e in hilo]
    lo_h, hi_h  = min(heights), max(heights)
    tidal_range = hi_h - lo_h

    # Waxing gibbous for the preview
    phase        = 0.38
    phase_name   = 'Waxing Gibbous'
    spring_label = 'NEAP TIDE'
    spring_color = C_LOW
    cycle_pct    = 47

    moon_r  = max(4, min(10, dh // 5))
    moon_cx = moon_r + 3
    moon_cy = dh // 2 - (4 if L['small'] else 6)

    draw_moon(draw, moon_cx, moon_cy, moon_r, phase)
    txt_x = moon_cx + moon_r + 5

    short_name = phase_name.replace(' Moon','').replace(' Quarter',' Qtr')
    if L['small']: short_name = short_name[:6]
    _txt(draw, txt_x, L['row1'], short_name, C_MOON, FONT_TINY)
    _txt(draw, txt_x, L['row2'], spring_label, spring_color, FONT_TINY)
    _txt(draw, txt_x, L['row3'], f"Range {tidal_range:.1f}ft", C_LOW, FONT_TINY)
    if not L['small']:
        _txt(draw, txt_x, L['row4'], f"H {hi_h:.1f}  L {lo_h:.1f}ft", C_LABEL, FONT_TINY)

    bar_h  = max(2, dh // 16)
    bar_y  = dh - bar_h - 1
    bar_x0 = txt_x
    bar_x1 = dw - 3
    blen   = max(1, bar_x1 - bar_x0)
    flen   = int(blen * cycle_pct / 100)
    draw.rectangle([bar_x0, bar_y, bar_x1, bar_y+bar_h], fill=(0, 8, 25))
    if flen > 0:
        for px in range(flen):
            t2 = px / max(flen, 1)
            draw.line([(bar_x0+px, bar_y),(bar_x0+px, bar_y+bar_h)],
                      fill=_lerp(C_LOW, C_HIGH, t2))
    # % label above the bar so it can't clip past the display bottom
    pct_str = f"{cycle_pct}%"
    pct_w   = len(pct_str) * 4 + 1
    pct_x   = max(bar_x0, min(dw - pct_w - 1, bar_x0 + flen - pct_w // 2))
    draw.text((pct_x, max(1, bar_y - 7)), pct_str, fill=C_LABEL, font=FONT_TINY)

    return canvas


# ── Composite sheet ────────────────────────────────────────────────────────────

def make_sheet(sizes, hilo, hourly):
    modes      = ['current', 'schedule', 'chart', 'stats']
    mode_names = ['Current', 'Schedule', 'Chart', 'Stats']

    SCALE    = 4    # enlarge each pixel so details are visible
    PAD      = 6    # padding between cells
    LABEL_H  = 12   # height of text label above each cell
    HEADER_H = 18   # column header height
    LEFT_W   = 60   # row label area

    cells_w  = max(dw for dw,_ in sizes)
    cells_h  = max(dh for _,dh in sizes)
    n_modes  = len(modes)
    n_sizes  = len(sizes)

    sheet_w = LEFT_W + n_modes * (cells_w * SCALE + PAD) + PAD
    sheet_h = HEADER_H + n_sizes * (LABEL_H + cells_h * SCALE + PAD) + PAD

    sheet = Image.new('RGB', (sheet_w, sheet_h), (12, 12, 20))
    sdraw = ImageDraw.Draw(sheet)

    # Column headers
    for col, (m, mn) in enumerate(zip(modes, mode_names)):
        hx = LEFT_W + PAD + col * (cells_w * SCALE + PAD) + (cells_w * SCALE) // 2
        sdraw.text((hx - len(mn)*3, 4), mn, fill=(180, 200, 240), font=FONT_TINY)

    # Rows
    for row, (dw, dh) in enumerate(sizes):
        ry = HEADER_H + row * (LABEL_H + cells_h * SCALE + PAD)
        size_label = f"{dw}×{dh}"
        sdraw.text((4, ry + LABEL_H + cells_h * SCALE // 2 - 3),
                   size_label, fill=(120, 140, 180), font=FONT_TINY)

        for col, mode in enumerate(modes):
            cx = LEFT_W + PAD + col * (cells_w * SCALE + PAD)
            cy = ry + LABEL_H

            # Render at native size
            if   mode == 'current':  img = render_current(dw, dh, hilo, hourly, phase=22)
            elif mode == 'schedule': img = render_schedule(dw, dh, hilo)
            elif mode == 'chart':    img = render_chart(dw, dh, hilo, hourly)
            else:                    img = render_stats(dw, dh, hilo)

            # Scale up (nearest neighbour to preserve LED pixel look)
            big = img.resize((dw * SCALE, dh * SCALE), Image.NEAREST)

            # Centre within column
            ox = cx + (cells_w * SCALE - dw * SCALE) // 2
            oy = cy + (cells_h * SCALE - dh * SCALE) // 2
            sheet.paste(big, (ox, oy))

            # Dim border around cell area
            sdraw.rectangle([ox - 1, oy - 1,
                             ox + dw * SCALE, oy + dh * SCALE],
                            outline=(30, 40, 60))

    return sheet


if __name__ == '__main__':
    out_dir = os.path.dirname(os.path.abspath(__file__))
    hilo    = _make_hilo()
    hourly  = _make_hourly()

    sizes = [
        (64,  32),
        (128, 32),
        (192, 48),
        (256, 64),
    ]

    print("Rendering tide display previews …")

    sheet = make_sheet(sizes, hilo, hourly)
    out   = os.path.join(out_dir, 'preview_sheet.png')
    sheet.save(out)
    print(f"  Saved: {out}  ({sheet.width}×{sheet.height})")

    # Also save individual mode PNGs at 192×48 (most common)
    dw, dh = 192, 48
    SCALE  = 5
    for mode, fn in [('current','preview_current.png'),
                     ('schedule','preview_schedule.png'),
                     ('chart','preview_chart.png'),
                     ('stats','preview_stats.png')]:
        if   mode == 'current':  img = render_current(dw, dh, hilo, hourly, phase=22)
        elif mode == 'schedule': img = render_schedule(dw, dh, hilo)
        elif mode == 'chart':    img = render_chart(dw, dh, hilo, hourly)
        else:                    img = render_stats(dw, dh, hilo)

        big  = img.resize((dw*SCALE, dh*SCALE), Image.NEAREST)
        path = os.path.join(out_dir, fn)
        big.save(path)
        print(f"  Saved: {path}")

    print("Done.")
