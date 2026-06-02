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
C_BG           = (0,   0,   0)
C_WATER_DEEP   = (0,  50, 140)
C_WATER_MID    = (0,  90, 180)
C_WATER_LIGHT  = (0, 130, 210)
C_WAVE1        = (0, 210, 255)
C_WAVE2        = (0, 140, 200)
C_CHART_FILL   = (0,  40, 110)
C_CHART_LINE   = (0, 210, 255)
C_CHART_GLOW1  = (0, 100, 180)
C_CHART_GLOW2  = (0,  60, 130)
C_GRID         = (15,  25,  50)
C_NOW_LINE     = (255, 220,  40)
C_HIGH         = (255, 200,  50)
C_LOW          = ( 80, 190, 255)
C_RISING       = ( 50, 230, 100)
C_FALLING      = (255,  80,  80)
C_SLACK        = (255, 210,  60)
C_TEXT         = (200, 225, 255)
C_LABEL        = (100, 130, 180)
C_DIM          = ( 50,  60,  80)
C_MOON         = (240, 235, 200)
C_BAR_OUTLINE  = ( 30,  50,  90)
C_COL_BG       = (  0,  15,  40)


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

def _safe_iso(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None

def _layout(dw, dh):
    bar_w  = max(8, min(32, int(dw * 0.13)))
    bar_x  = 2
    bar_h  = dh - 4
    bar_ybot = dh - 2
    txt_x  = bar_x + bar_w + 4
    c_ml, c_mr, c_mt = 3, 3, 1
    c_axis = max(7, int(dh * 0.16))
    c_x, c_y = c_ml, c_mt
    c_w = dw - c_ml - c_mr
    c_h = dh - c_axis - c_mt - 1
    wave_amp = max(1, min(4, dh // 12))
    row1 = 1
    row2 = max(9,  int(dh * 0.28))
    row3 = max(18, int(dh * 0.55))
    row4 = max(27, int(dh * 0.78))
    return dict(bar_w=bar_w, bar_x=bar_x, bar_h=bar_h, bar_ybot=bar_ybot,
                txt_x=txt_x, c_x=c_x, c_y=c_y, c_w=c_w, c_h=c_h,
                c_axis=c_axis, wave_amp=wave_amp,
                row1=row1, row2=row2, row3=row3, row4=row4,
                small=(dw<=64), medium=(64<dw<=128), large=(dw>128))

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

def draw_wave_bar(canvas, draw, x, ybot, bw, bh, fill_ratio, amp, wave_phase):
    fill_px  = max(2, int(bh * fill_ratio))
    fill_top = ybot - fill_px
    draw.rectangle([x - 1, ybot - bh - 1, x + bw, ybot + 1], outline=C_BAR_OUTLINE)
    band1 = fill_px * 2 // 3
    band2 = fill_px - band1
    if band1 > 0:
        draw.rectangle([x, fill_top + band2, x + bw - 1, ybot], fill=C_WATER_DEEP)
    if band2 > 0:
        draw.rectangle([x, fill_top, x + bw - 1, fill_top + band2 + 1], fill=C_WATER_MID)
    surf_band = max(1, fill_px // 4)
    if fill_px > surf_band:
        draw.rectangle([x, fill_top, x + bw - 1, fill_top + surf_band], fill=C_WATER_LIGHT)
    for pct in (0.25, 0.5, 0.75):
        ty = ybot - int(bh * pct)
        draw.line([(x + bw - 2, ty), (x + bw, ty)], fill=C_LABEL)
    for px in range(bw):
        wy = fill_top - 1 + int((amp - 1) * math.sin((px + wave_phase * 1.8 + 25) * 0.55))
        wy = max(0, min(ybot, wy))
        draw.point((x + px, wy), fill=C_WAVE2)
    for px in range(bw):
        wy = fill_top + int(amp * math.sin((px + wave_phase) * 0.42))
        wy = max(0, min(ybot, wy))
        draw.line([(x + px, wy), (x + px, min(ybot, wy + 2))], fill=C_WAVE1)
    for px in range(0, bw, max(3, bw // 5)):
        wy = fill_top + int(amp * math.sin((px + wave_phase) * 0.42))
        wy = max(0, min(ybot - 1, wy - 1))
        draw.point((x + px, wy), fill=(255, 255, 255))

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
    wave_p = phase

    heights     = [e['height'] for e in hilo]
    lo_h, hi_h  = min(heights), max(heights)
    # current level ~ 60% up the range (mid-rising)
    cur_level   = lo_h + (hi_h - lo_h) * 0.42
    fill_ratio  = (cur_level - lo_h) / max(hi_h - lo_h, 0.01)
    direction   = 'RISING'

    draw_wave_bar(canvas, draw, L['bar_x'], L['bar_ybot'],
                  L['bar_w'], L['bar_h'], fill_ratio, L['wave_amp'], wave_p)

    dir_c = C_RISING
    _txt(draw, L['txt_x'], L['row1'], direction, dir_c, FONT_TINY)
    arr_x = L['txt_x'] + len(direction) * 4 + 4
    if arr_x < dw - 6:
        draw_arrow(draw, arr_x, L['row1'] + 3, direction, sz=3)

    _txt(draw, L['txt_x'], L['row2'], _fmth(cur_level), C_TEXT, FONT_TINY)

    sep_y = L['row2'] + 9
    if sep_y < dh - 12:
        draw.line([(L['txt_x'], sep_y), (dw-3, sep_y)], fill=C_BAR_OUTLINE)

    now   = datetime.now()
    nexts = [e for e in hilo if _safe_iso(e['dt']) and _safe_iso(e['dt']) > now][:2]
    row   = sep_y + 2
    for tide in nexts:
        if row + 8 > dh: break
        is_high = tide.get('type','?') == 'H'
        tc  = C_HIGH if is_high else C_LOW
        sym = '▲' if is_high else '▼'
        _txt(draw, L['txt_x'], row,
             f"{sym} {_fmtt(tide['dt'])}  {_fmth(tide['height'])}", tc, FONT_TINY)
        row += 10

    name = 'Seattle'
    if row + 1 < dh:
        _txt(draw, L['txt_x'], dh - 8, name, C_DIM, FONT_TINY)

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
            draw.rectangle([i*col_w+1, 0, i*col_w+col_w-2, dh-4], fill=C_COL_BG)

        type_label = ('HIGH' if is_high else 'LOW') if not L['small'] else ('H' if is_high else 'L')
        _txt_c(draw, cx, L['row1'], type_label, tc if not is_past else C_DIM, FONT_TINY)
        _txt_c(draw, cx, L['row2'], _fmtt(tide['dt']), C_TEXT if not is_past else C_DIM, FONT_TINY)
        _txt_c(draw, cx, L['row3'], _fmth(tide['height']),
               _lerp(C_LOW, C_HIGH, (tide['height']-lo_h)/h_range) if not is_past else C_DIM,
               FONT_TINY)

        bar_h_px = max(1, int((tide['height']-lo_h)/h_range * 4))
        bx1, bx2 = i*col_w+3, i*col_w+col_w-4
        draw.rectangle([bx1, dh-1-bar_h_px, bx2, dh-1],
                       fill=tc if not is_past else C_DIM)

    for i in range(1, n):
        draw.line([(i*col_w, 1), (i*col_w, dh-5)], fill=C_BAR_OUTLINE)

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

    ax_y = cy + ch + 2
    ax_labels = [(0,'12a'),(6,'6a'),(12,'12p'),(18,'6p')]
    if L['small']: ax_labels = [(0,'0'),(12,'12')]
    for lh, lt in ax_labels:
        lx = cx + int(lh * cw / 23)
        draw.text((max(0, lx-4), ax_y), lt, fill=C_LABEL, font=FONT_TINY)

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

    bar_y  = dh - 4
    bar_x0 = txt_x
    bar_x1 = dw - 3
    blen   = bar_x1 - bar_x0
    flen   = int(blen * cycle_pct / 100)
    draw.rectangle([bar_x0, bar_y, bar_x1, bar_y+2], fill=C_COL_BG)
    if flen > 0:
        draw.rectangle([bar_x0, bar_y, bar_x0+flen, bar_y+2],
                       fill=_lerp(C_LOW, C_HIGH, cycle_pct/100))
    pct_x = max(txt_x, min(dw-26, bar_x0+flen-8))
    draw.text((pct_x, bar_y-8), f"{cycle_pct}%", fill=C_LABEL, font=FONT_TINY)

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
