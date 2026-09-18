"""Layout, compositing, and overlay drawing for the Geochron world clock.

This module is independent of BasePlugin/display_manager so it can be used
both by manager.py (live plugin) and render_preview.py (standalone preview
generator). Text drawing is left to the caller via a small callback so each
caller can use its own font-loading strategy.
"""

import math
from datetime import timedelta

import numpy as np
from PIL import Image

import worldmap

# Warm highlight blended into the twilight band, peaking at d=0.5.
TWILIGHT_GLOW_COLOR = (255, 140, 40)
TWILIGHT_GLOW_STRENGTH = 0.18

# Blend strength toward night_tint_color on the night side.
NIGHT_TINT_STRENGTH = 0.40

# Text row height in pixels: the 4x6 face at its crisp 7px + a 1px line gap.
ROW_H = 8


def _layout(dw, dh, map_center_lon=0.0, sidebar_w=None):
    """Compute the responsive layout for a dw x dh display.

    Returns a dict describing the map placement (in display pixels) and the
    lon/lat range of the world the map should show, plus any sidebar info.
    sidebar_w, on wide panels, is the width the timezone list needs (see
    sidebar_width); the map gives up whatever that takes. 0 drops the sidebar.
    """
    aspect = dw / dh

    if aspect >= 3.0:
        mode = "wide_sidebar"
        default_w = max(32, int(dw * 0.22))
        if sidebar_w is None:
            sidebar_w = default_w
        elif sidebar_w > 0:
            sidebar_w = max(default_w, min(int(sidebar_w), dw // 2))
        # sidebar_w == 0: no readout, so the map takes the whole panel.
        map_w = dw - sidebar_w
        map_h = dh
        # Asymmetric latitude band, biased toward the northern hemisphere:
        # +70 covers Moscow (55.75) plus the rest of Canada, Alaska,
        # Scandinavia, and Iceland; -50 still covers Sydney (-33.87) and Rio
        # (-22.91) with margin while cropping out the mostly-empty Southern
        # Ocean and Antarctica. The resulting 120-degree span also closely
        # matches typical wide_sidebar map aspect ratios, reducing vertical
        # stretching from the crop->resize step.
        lat_min = -50.0
        lat_max = 70.0
        lon_extent = 360.0
        lon_center = 0.0
    elif aspect >= 1.5:
        mode = "near_bleed"
        sidebar_w = 0
        map_w, map_h = dw, dh
        lat_min = -90.0
        lat_max = 90.0
        lon_extent = 360.0
        lon_center = 0.0
    else:
        mode = "square_tall"
        sidebar_w = 0
        map_w, map_h = dw, dh
        lat_min = -90.0
        lat_max = 90.0
        lon_extent = max(90.0, min(360.0, 180.0 * aspect))
        lon_center = map_center_lon

    return {
        "mode": mode,
        "dw": dw,
        "dh": dh,
        "map_x": 0,
        "map_y": 0,
        "map_w": map_w,
        "map_h": map_h,
        "sidebar_w": sidebar_w,
        "sidebar_x": map_w if sidebar_w else None,
        "lon_min": lon_center - lon_extent / 2.0,
        "lon_max": lon_center + lon_extent / 2.0,
        "lat_min": lat_min,
        "lat_max": lat_max,
    }


def lonlat_to_px(lon, lat, layout):
    """Project a (lon, lat) in degrees to a (x, y) display pixel.

    Mirrors the crop window used by render_map_image. Returns (x, y, visible)
    where visible is False if the point falls outside the cropped/shown
    region (e.g. on the far side of the world on a square/tall panel).
    """
    L = layout
    lon_span = L["lon_max"] - L["lon_min"]
    lat_span = L["lat_max"] - L["lat_min"]

    if lon_span >= 360.0:
        lon_n = ((lon + 180.0) % 360.0) - 180.0
    else:
        lon_n = ((lon - L["lon_min"]) % 360.0) + L["lon_min"]

    fx = (lon_n - L["lon_min"]) / lon_span
    fy = (L["lat_max"] - lat) / lat_span
    x = L["map_x"] + fx * L["map_w"]
    y = L["map_y"] + fy * L["map_h"]
    visible = 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0
    return x, y, visible


def render_map_image(base_padded, darkness, layout, night_brightness, night_tint_color):
    """Composite the day/night terminator onto the base map and crop/resize
    it to the layout's map area.

    base_padded: PIL RGB image from worldmap.render_base_map().
    darkness: (GRID_H, GRID_W) float array in [0, 1] from solar.compute_terminator().
    """
    L = layout

    arr = np.asarray(base_padded, dtype=np.float32)
    d = worldmap.tile_padded(darkness).astype(np.float32)[..., None]

    tint = np.array(night_tint_color, dtype=np.float32)
    night = arr * float(night_brightness)
    night = night * (1.0 - NIGHT_TINT_STRENGTH) + tint * NIGHT_TINT_STRENGTH

    out = arr * (1.0 - d) + night * d

    glow_strength = 4.0 * d * (1.0 - d) * TWILIGHT_GLOW_STRENGTH
    glow = np.array(TWILIGHT_GLOW_COLOR, dtype=np.float32)
    out = out * (1.0 - glow_strength) + glow * glow_strength

    out = np.clip(out, 0, 255).astype(np.uint8)
    composited = Image.fromarray(out, "RGB")

    x0 = worldmap.lon_to_x(L["lon_min"])
    x1 = worldmap.lon_to_x(L["lon_max"])
    y0 = worldmap.lat_to_y(L["lat_max"])
    y1 = worldmap.lat_to_y(L["lat_min"])

    crop = composited.crop((int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))))
    return crop.resize((L["map_w"], L["map_h"]), Image.Resampling.LANCZOS)


def draw_graticule(draw, layout, step_deg, color):
    """Draw a lat/lon grid over the map area."""
    L = layout
    lon_span = L["lon_max"] - L["lon_min"]
    lat_span = L["lat_max"] - L["lat_min"]
    x_max = L["map_x"] + L["map_w"] - 1
    y_max = L["map_y"] + L["map_h"] - 1

    lat = math.ceil(L["lat_min"] / step_deg) * step_deg
    while lat <= L["lat_max"]:
        fy = (L["lat_max"] - lat) / lat_span
        y = min(L["map_y"] + fy * L["map_h"], y_max)
        draw.line([(L["map_x"], y), (x_max, y)], fill=color)
        lat += step_deg

    lon = math.ceil(L["lon_min"] / step_deg) * step_deg
    while lon <= L["lon_max"]:
        fx = (lon - L["lon_min"]) / lon_span
        x = min(L["map_x"] + fx * L["map_w"], x_max)
        draw.line([(x, L["map_y"]), (x, y_max)], fill=color)
        lon += step_deg


def draw_sun_marker(draw, layout, subsolar_lat, subsolar_lon, color):
    """Draw a marker at the subsolar point."""
    x, y, visible = lonlat_to_px(subsolar_lon, subsolar_lat, layout)
    if not visible:
        return
    r = max(1, min(layout["map_w"], layout["map_h"]) // 48)
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def draw_cities(draw, layout, cities, color):
    """Draw a marker dot for each visible city."""
    r = 1 if min(layout["map_w"], layout["map_h"]) < 150 else 2
    for city in cities:
        x, y, visible = lonlat_to_px(city["lon"], city["lat"], layout)
        if not visible:
            continue
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def format_clock(dt, fmt="24h", show_seconds=True):
    """Format a datetime as a clock string in 12h or 24h format."""
    if fmt == "12h":
        hour = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        if show_seconds:
            return f"{hour}:{dt.minute:02d}:{dt.second:02d}{ampm}"
        return f"{hour}:{dt.minute:02d}{ampm}"
    if show_seconds:
        return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    return f"{dt.hour:02d}:{dt.minute:02d}"


# Seconds between pages when there are more timezones than sidebar rows.
PAGE_SECONDS = 5

# Minimum gap between zone rows; spare height is spread between rows up to this.
MAX_ROW_PITCH = 11


def city_label(city):
    """Short, uniform label for a city's timezone row.

    An explicit ``label`` wins. Multi-word names become initials ("New York"
    -> "NY", "Rio de Janeiro" -> "RJ"); single words their first three letters
    ("Tokyo" -> "TOK"). Codes keep every row the same shape, so the times line
    up in a column and the eye reads down it.
    """
    label = str(city.get("label") or "").strip()
    if label:
        return label.upper()[:4]
    name = str(city.get("name") or "").strip()
    words = [w for w in name.replace("-", " ").split() if w[:1].isupper()]
    if len(words) >= 2:
        return "".join(w[0] for w in words)[:3].upper()
    return name[:3].upper() or "?"


def tz_label(tz_name):
    """Label for the local zone when no configured city shares it."""
    if not tz_name or tz_name.upper() in ("UTC", "ETC/UTC", "GMT", "ETC/GMT"):
        return "UTC"
    return city_label({"name": tz_name.rsplit("/", 1)[-1].replace("_", " ")})


def zone_time(dt, fmt="24h"):
    """Hours and minutes only: seconds tick too fast to read beside a map."""
    return format_clock(dt, fmt, False)


def sidebar_width(measure, clock_format="24h"):
    """Width a wide panel's timezone list needs: the widest label and time."""
    widest = measure("WWW " + ("12:59PM" if clock_format == "12h" else "23:59"))
    return int(math.ceil(widest)) + 4


def build_zones(local_dt, local_tz_name, cities, clock_format="24h"):
    """Timezone rows: local first, then each configured city with a timezone.

    cities: list of dicts with "label" (from city_label) and "local_dt". A city
    in the local zone is folded into the local row rather than repeated.
    Returns a list of (label, time, is_local).
    """
    zones = []
    rest = list(cities)
    if local_dt is not None:
        label = tz_label(local_tz_name)
        for city in rest:
            if city.get("tz") == local_tz_name:
                label = city["label"]
                rest.remove(city)
                break
        zones.append((label, zone_time(local_dt, clock_format), True))
    for city in rest:
        zones.append((city["label"], zone_time(city["local_dt"], clock_format), False))
    return zones


def build_readout(layout, dt_utc, zones, row_h=ROW_H, date_text=None):
    """Place the timezone rows for the sidebar (wide panels) or corner box.

    Returns a dict:
      - mode: "sidebar" or "corner"
      - rows: list of (label, time, is_local, y) with y the row's top edge
      - box: (x0, y0, x1, y1) the backing rectangle, or None for the sidebar
      - x0, x1: left edge for labels and right edge for right-aligned times

    zones comes from build_zones. With no zones the panel shows UTC.
    date_text, on wide panels, heads the list (see sidebar_date) and is
    returned as "header": (text, y); it takes one row from the zones. When the
    sidebar has fewer rows than zones, the local row stays pinned and the
    cities page every PAGE_SECONDS, driven by dt_utc so a frozen clock renders
    the same page.
    """
    L = layout
    if not zones:
        zones = [("UTC", zone_time(dt_utc), True)]

    if L["mode"] == "wide_sidebar":
        fit = max(1, (L["dh"] - 1) // row_h)
        # The date only earns its row when a zone row is still left beside it.
        header = date_text if date_text and fit >= 2 else None
        if header:
            fit -= 1
        shown = zones
        if len(zones) > fit:
            pinned = [z for z in zones if z[2]][:1]
            others = [z for z in zones if not z[2]]
            room = fit - len(pinned)
            if room <= 0:
                shown = (pinned or zones)[:fit]
            else:
                pages = (len(others) + room - 1) // room
                # Even pages: 7 cities in rooms of 6 page as 4 + 3, not 6 + 1.
                per_page = (len(others) + pages - 1) // pages
                page = int(dt_utc.timestamp() // PAGE_SECONDS) % pages
                shown = pinned + others[page * per_page:(page + 1) * per_page]
        n = len(shown) + (1 if header else 0)
        pitch = max(row_h, min(MAX_ROW_PITCH, L["dh"] // n))
        top = (L["dh"] - pitch * n) // 2 + (pitch - row_h) // 2 + 1
        first = top + (pitch if header else 0)
        return {
            "mode": "sidebar",
            "header": (header, top) if header else None,
            "rows": [(label, t, local, first + i * pitch) for i, (label, t, local) in enumerate(shown)],
            "box": None,
            "x0": L["sidebar_x"] + 2,
            "x1": L["dw"] - 2,
        }

    # Corner box over the map: keep it to what reads at a glance.
    n = 2 if L["dh"] >= 2 * row_h + 3 and len(zones) > 1 else 1
    shown = zones[:n]
    y0 = L["dh"] - n * row_h - 1
    return {
        "mode": "corner",
        "header": None,
        "rows": [(label, t, local, y0 + 1 + i * row_h) for i, (label, t, local) in enumerate(shown)],
        "box": (0, y0, None, L["dh"] - 1),
        "x0": 2,
        "x1": None,
    }


def _readout_right(draw, readout, font):
    """Right edge the times align to: fixed in the sidebar, fitted in a corner."""
    if readout["x1"] is not None:
        return readout["x1"]
    rows = readout["rows"]
    measure = lambda text: draw.textlength(text, font=font)  # noqa: E731
    label_w = max(measure(label) for label, _, _, _ in rows)
    time_w = max(measure(t) for _, t, _, _ in rows)
    return int(readout["x0"] + label_w + measure(" ") + time_w)


def readout_box(draw, readout, font):
    """The corner readout's backing rectangle, or None in the sidebar."""
    if readout["box"] is None or not readout["rows"]:
        return None
    bx0, by0, _, by1 = readout["box"]
    return (bx0, by0, _readout_right(draw, readout, font) + 1, by1)


def draw_readout(draw, readout, font, primary, secondary, bg=(10, 10, 10)):
    """Draw readout rows: label on the left, time right-aligned beside it.

    The local label is drawn in the primary colour, city labels in the
    secondary one, and every time in primary so the numbers carry the row.
    """
    rows = readout["rows"]
    if not rows:
        return
    measure = lambda text: draw.textlength(text, font=font)  # noqa: E731
    x0 = readout["x0"]
    x1 = _readout_right(draw, readout, font)
    box = readout_box(draw, readout, font)
    if box is not None:
        draw.rectangle(list(box), fill=bg)
    header = readout.get("header")
    if header:
        text, y = header
        draw.text((x0, y), text, fill=secondary, font=font)
    for label, t, local, y in rows:
        draw.text((x0, y), label, fill=primary if local else secondary, font=font)
        draw.text((x1 - int(measure(t)), y), t, fill=primary, font=font)


def sidebar_date(local_dt, measure, width):
    """Longest date form that fits the sidebar: "FRI AUG 1", "FRI 8/1", "8/1"."""
    options = [
        f"{local_dt:%a %b} {local_dt.day}",
        f"{local_dt:%a} {local_dt.month}/{local_dt.day}",
        f"{local_dt.month}/{local_dt.day}",
    ]
    for text in options:
        if measure(text.upper()) <= width:
            return text.upper()
    return options[-1]


def midnight_longitude(dt_utc):
    """Longitude where mean solar time is midnight: where the date turns over.

    It sweeps west 15 degrees an hour. East of it, up to the date line at 180,
    it is already tomorrow. Mean solar time, not civil zones, so it can sit
    up to an hour or so off a zone boundary -- right for a map, not a calendar.
    """
    hours = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    return ((-15.0 * hours + 180.0) % 360.0) - 180.0


def draw_date_line(draw, layout, dt_utc, font, line_color, text_color,
                   label_position="bottom", avoid=None):
    """Dotted midnight meridian with the weekday on each side of it.

    label_position puts the weekdays along the top or bottom edge of the map.
    They sit straight on the map, no backing box. avoid is a rectangle (the
    corner readout) the labels must not run into; if they would, they are
    left out and the line alone marks midnight.
    """
    L = layout
    lon = midnight_longitude(dt_utc)
    x, _, visible = lonlat_to_px(lon, (L["lat_min"] + L["lat_max"]) / 2.0, L)
    if not visible:
        return
    x = int(min(x, L["map_x"] + L["map_w"] - 1))
    top = L["map_y"]
    bottom = L["map_y"] + L["map_h"]
    for y in range(top, bottom, 2):
        draw.point((x, y), fill=line_color)

    # Date just east of the line (tomorrow) and just west (today).
    east = (dt_utc + timedelta(hours=(lon + 0.5) / 15.0)).date()
    west = east - timedelta(days=1)
    # Both or neither: a lone "FRI" beside the line does not say which side
    # is tomorrow. The line alone still marks midnight.
    ty = top + 1 if label_position == "top" else bottom - ROW_H
    labels = []
    for day, side in ((west, -1), (east, 1)):
        text = f"{day:%a}".upper()
        w = int(math.ceil(draw.textlength(text, font=font)))
        tx = x - 2 - w if side < 0 else x + 2
        if tx < L["map_x"] or tx + w > L["map_x"] + L["map_w"]:
            return
        if avoid is not None:
            ax0, ay0, ax1, ay1 = avoid
            if tx <= ax1 and tx + w >= ax0 and ty <= ay1 and ty + ROW_H >= ay0:
                return
        labels.append((text, tx))
    for text, tx in labels:
        draw.text((tx, ty), text, fill=text_color, font=font)
