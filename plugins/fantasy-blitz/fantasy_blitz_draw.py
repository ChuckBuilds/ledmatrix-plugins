"""Drawing kit for the Fantasy Blitz screens: palette, primitives and sprites.

Everything here draws onto a plain PIL RGB image with Pillow's C routines
(paste, polygon, resize) rather than per-pixel Python, because a Pi redraws
animated screens many times a second.

LED rules this module encodes, from the user story's art direction:

* Black is the canvas -- an unlit LED. Large fills stay at 35% brightness or
  less; full brightness is for edges, numbers and text.
* Dark club colours are lifted (:func:`lift`) until their strongest channel
  reaches ~150, or navy disappears on a panel.
* Text over a gradient or a burst gets a black outline.
"""

import math
import random
from typing import Dict, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw

import fantasy_blitz_font as font

RGB = Tuple[int, int, int]

BLACK: RGB = (0, 0, 0)
INK: RGB = (10, 6, 2)
WHITE: RGB = (236, 240, 248)
GRAY: RGB = (126, 134, 150)
DIM: RGB = (58, 64, 78)
GOLD: RGB = (255, 194, 40)
GOLD_HI: RGB = (255, 238, 170)
EPIC: RGB = (181, 102, 255)
RARE: RGB = (63, 163, 255)
COMMON: RGB = (220, 225, 235)
RED: RGB = (255, 50, 70)
ORANGE: RGB = (255, 146, 40)
YELLOW: RGB = (255, 214, 60)
GREEN: RGB = (70, 240, 126)
ICE: RGB = (120, 210, 255)
SILVER: RGB = (196, 205, 218)
BRONZE: RGB = (214, 132, 60)

TIER_COLORS: Dict[str, RGB] = {"legendary": GOLD, "epic": EPIC, "rare": RARE, "common": COMMON}
TIER_NAMES: Dict[str, str] = {"legendary": "LEGENDARY", "epic": "EPIC", "rare": "RARE", "common": "COMMON"}
POSITION_COLORS: Dict[str, RGB] = {
    "QB": (252, 43, 109), "RB": (32, 206, 184), "WR": (86, 201, 248),
    "TE": (254, 174, 88), "K": (201, 108, 255), "DEF": (191, 117, 93),
}
INJURY_COLORS: Dict[str, RGB] = {
    "Q": YELLOW, "D": ORANGE, "O": RED, "IR": (190, 30, 45), "SUS": (190, 30, 45), "PUP": ORANGE,
}


# ----------------------------------------------------------------------
# colour
# ----------------------------------------------------------------------

def mix(a: Sequence[float], b: Sequence[float], t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def scale(c: Sequence[float], k: float) -> RGB:
    return tuple(int(max(0, min(255, round(v * k)))) for v in c[:3])  # type: ignore[return-value]


def lift(c: Sequence[float], minimum: int = 150) -> RGB:
    """Brighten a colour until its strongest channel reaches ``minimum``."""
    top = max(c[:3])
    if top >= minimum:
        return tuple(int(v) for v in c[:3])  # type: ignore[return-value]
    if top == 0:
        return (minimum, minimum, minimum)
    k = minimum / float(top)
    return tuple(int(min(255, round(v * k))) for v in c[:3])  # type: ignore[return-value]


def luminance(c: Sequence[float]) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def readable_on(bg: Sequence[float], preferred: Sequence[float]) -> RGB:
    """``preferred`` if it stands out on ``bg``, else black or white."""
    candidates = [tuple(preferred[:3]), WHITE, INK]
    best = max(candidates, key=lambda c: abs(luminance(c) - luminance(bg)) + (25 if c == tuple(preferred[:3]) else 0))
    return best  # type: ignore[return-value]


def team_colors(team: Dict[str, object]) -> Tuple[RGB, RGB]:
    """(primary, accent) of a club, both lifted for the panel."""
    return lift(team["primary"]), lift(team["accent"], 150)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# primitives
# ----------------------------------------------------------------------

def rect(img: Image.Image, x: int, y: int, w: int, h: int, color: Sequence[int], alpha: float = 1.0) -> None:
    if w <= 0 or h <= 0 or alpha <= 0:
        return
    box = (int(x), int(y), int(x + w), int(y + h))
    if alpha >= 1.0:
        img.paste(tuple(int(c) for c in color[:3]), box)
    else:
        img.paste(tuple(int(c) for c in color[:3]), box, Image.new("L", (int(w), int(h)), int(255 * alpha)))


def frame(img: Image.Image, x: int, y: int, w: int, h: int, color: Sequence[int]) -> None:
    if w <= 0 or h <= 0:
        return
    ImageDraw.Draw(img).rectangle([x, y, x + w - 1, y + h - 1], outline=tuple(color[:3]))


def hline(img: Image.Image, x: int, y: int, w: int, color: Sequence[int]) -> None:
    rect(img, x, y, w, 1, color)


def hgrad(img: Image.Image, x: int, y: int, w: int, h: int, c1: Sequence[int], c2: Sequence[int]) -> None:
    if w <= 0 or h <= 0:
        return
    strip = Image.new("RGB", (w, 1))
    strip.putdata([mix(c1, c2, i / max(1, w - 1)) for i in range(w)])
    img.paste(strip.resize((w, h), Image.NEAREST), (x, y))


def vgrad(img: Image.Image, x: int, y: int, w: int, h: int, c1: Sequence[int], c2: Sequence[int]) -> None:
    if w <= 0 or h <= 0:
        return
    strip = Image.new("RGB", (1, h))
    strip.putdata([mix(c1, c2, j / max(1, h - 1)) for j in range(h)])
    img.paste(strip.resize((w, h), Image.NEAREST), (x, y))


def ellipse(img: Image.Image, cx: float, cy: float, rx: float, ry: float,
            color: Sequence[int], alpha: float = 1.0) -> None:
    if rx <= 0 or ry <= 0:
        return
    box = [cx - rx, cy - ry, cx + rx, cy + ry]
    if alpha >= 1.0:
        ImageDraw.Draw(img).ellipse(box, fill=tuple(color[:3]))
        return
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=int(255 * alpha))
    img.paste(tuple(color[:3]), (0, 0), mask)


def text(img: Image.Image, s: object, x: int, y: int, color, scale_: int = 1,
         align: str = "left", outline: Optional[RGB] = None) -> int:
    return font.draw_text(img, s, x, y, color, scale_, align, outline)


def big_number(img: Image.Image, s: str, x: int, y: int, color: RGB, scale_: int,
               align: str = "left", shadow: bool = True) -> int:
    """Arcade numerals: a highlight on the top rows and a dark drop shadow."""
    top_rows = max(1, scale_)

    def fill(row: int, height: int) -> RGB:
        if row < top_rows:
            return mix(color, WHITE, 0.55)
        return mix(color, scale(color, 0.72), row / max(1, height - 1))

    if shadow:
        font.draw_text(img, s, x + 1, y + 1, scale(color, 0.28), scale_, align)
    return font.draw_text(img, s, x, y, fill, scale_, align)


def shimmer(img: Image.Image, x: int, y: int, w: int, h: int, pos: float,
            band: float = 5.0, amount: float = 0.35) -> None:
    """A diagonal foil sweep that brightens only already-lit pixels."""
    if w <= 0 or h <= 0 or amount <= 0:
        return
    region = img.crop((x, y, x + w, y + h))
    lit = region.convert("L").point(lambda p: 255 if p > 60 else 0)
    band_mask = Image.new("L", (w, h), 0)
    p = pos - x
    slope = 0.7 * h
    ImageDraw.Draw(band_mask).polygon(
        [(p - band, 0), (p + band, 0), (p + band - slope, h), (p - band - slope, h)],
        fill=int(255 * max(0.0, min(1.0, amount))))
    img.paste(WHITE, (x, y), ImageChops.multiply(lit, band_mask))


# ----------------------------------------------------------------------
# sprites
# ----------------------------------------------------------------------

def _sprite(img: Image.Image, x: int, y: int, rows: Sequence[str], palette: Dict[str, RGB]) -> None:
    px = img.load()
    width, height = img.size
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            color = palette.get(ch)
            if color is None:
                continue
            xx, yy = x + i, y + j
            if 0 <= xx < width and 0 <= yy < height:
                px[xx, yy] = color


def coin(img: Image.Image, x: int, y: int, rank: int) -> None:
    """A 7x7 rank medal: gold, silver and bronze for places 1 to 3."""
    base = [GOLD, SILVER, BRONZE][rank] if rank < 3 else (64, 70, 86)
    rows = [(2, 4), (1, 5), (0, 6), (0, 6), (0, 6), (1, 5), (2, 4)]
    for j, (a, b) in enumerate(rows):
        rect(img, x + a, y + j, b - a + 1, 1, mix(base, WHITE, 0.35) if j < 2 else base)
    label = str(rank + 1)
    font.draw_text(img, label, x + 3, y + 1, (30, 20, 6) if rank < 3 else WHITE, 1, "center")


def chip(img: Image.Image, x: int, y: int, w: int, h: int, team: Dict[str, object], number: str) -> None:
    """A jersey chip: club colour with the jersey number, or the club code."""
    primary, accent = team_colors(team)
    rect(img, x, y, w, h, primary)
    # With no jersey number the club code stands in, but only a two-letter
    # one: a three-letter code does not fit, and "LA" alone is two clubs.
    abbr = str(team.get("abbr") or "")
    label = number or (abbr if len(abbr) <= 2 else "")
    if label and font.text_width(label) > w - 2:
        label = ""
    ink = readable_on(primary, accent)
    font.draw_text(img, label, x + w // 2, y + max(0, (h - font.GLYPH_HEIGHT) // 2), ink, 1, "center")


def tag(img: Image.Image, x: int, y: int, label: str, bg: RGB, fg: RGB = INK) -> int:
    """A filled label box 7 px tall; returns its width."""
    w = font.text_width(label) + 4
    rect(img, x, y, w, 7, bg)
    font.draw_text(img, label, x + 2, y + 1, fg)
    return w


def pos_tag(img: Image.Image, x: int, y: int, pos: str) -> int:
    return tag(img, x, y, pos, POSITION_COLORS.get(pos, GRAY))


def injury_box(img: Image.Image, x: int, y: int, code: str) -> int:
    color = INJURY_COLORS.get(code, RED)
    return tag(img, x, y, code, color, WHITE if luminance(color) < 140 else INK)


def xp_bar(img: Image.Image, x: int, y: int, w: int, h: int, proj: Optional[float],
           pts: Optional[float], progress: float = 1.0) -> None:
    """Blue up to the projection, gold past it -- an XP bar that overflows."""
    if w <= 2 or h <= 0:
        return
    pts = max(0.0, pts or 0.0)
    proj = max(0.0, proj or 0.0)
    top = max(pts, proj, 0.1)
    pw = int(round(proj / top * w)) if proj else 0
    aw = int(round(pts / top * w * max(0.0, min(1.0, progress))))
    rect(img, x, y, w, h, (28, 32, 44))
    for i in range(aw):
        color = RARE if i < pw else mix(GOLD, GOLD_HI, (i - pw) / max(1, w - pw) * 0.6)
        rect(img, x + i, y, 1, h, color)
        if h >= 3:
            rect(img, x + i, y, 1, 1, mix(color, WHITE, 0.35))
            rect(img, x + i, y + h - 1, 1, 1, scale(color, 0.7))
    if proj and 0 <= pw < w:
        rect(img, x + pw, max(0, y - 1), 1, h + 2, WHITE)


def hp_bar(img: Image.Image, x: int, y: int, w: int, h: int, proj: float, pts: float,
           progress: float = 1.0) -> None:
    """A health bar that drains from the projection down to what was scored."""
    if w <= 2 or h <= 0:
        return
    frame(img, x - 1, y - 1, w + 2, h + 2, (96, 22, 30))
    rect(img, x, y, w, h, (42, 8, 12))
    left = max(1, int(round(max(0.0, pts) / max(proj, 0.1) * w)))
    current = int(round(w - (w - left) * max(0.0, min(1.0, progress))))
    rect(img, x, y, current, h, RED)
    if h >= 3:
        rect(img, x, y, current, 1, mix(RED, WHITE, 0.35))
        rect(img, x, y + h - 1, current, 1, scale(RED, 0.6))


def portrait(img: Image.Image, x: int, y: int, w: int, h: int, team: Dict[str, object],
             jersey: str = "", photo: Optional[Image.Image] = None,
             logo: Optional[Image.Image] = None) -> None:
    """A card's picture box: the headshot, a crest, or a club-colour silhouette."""
    if w < 4 or h < 4:
        return
    primary, accent = team_colors(team)
    vgrad(img, x, y, w, h, scale(primary, 0.5), (6, 7, 10))
    if photo is not None:
        img.paste(photo, (x, y), photo)
        return
    if logo is not None:
        img.paste(logo, (x + (w - logo.width) // 2, y + (h - logo.height) // 2), logo)
        return
    box = Image.new("RGB", (w, h))
    vgrad(box, 0, 0, w, h, scale(primary, 0.5), (6, 7, 10))
    cx = w / 2.0 - 0.5
    cy = h * 0.36
    r = max(3.0, w * 0.2)
    ellipse(box, cx, cy, r * 1.9, r * 1.9, accent, 0.12)
    top = int(round(h * 0.64))
    draw = ImageDraw.Draw(box)
    draw.polygon([(cx - w * 0.26, top), (cx + w * 0.26, top), (cx + w * 0.46, top + (h - top) * 0.45),
                  (cx + w * 0.46, h), (cx - w * 0.46, h), (cx - w * 0.46, top + (h - top) * 0.45)],
                 fill=primary)
    neck_top = int(round(cy + r * 0.7))
    rect(box, int(round(cx - r * 0.45)), neck_top, max(2, int(round(r * 0.9))), max(1, top - neck_top), (36, 42, 56))
    ellipse(box, cx, cy, r * 0.92, r * 1.12, (46, 54, 72))
    draw.arc([cx - r * 0.92, cy - r * 1.12, cx + r * 0.92, cy + r * 1.12], -70, 70, fill=accent)
    if jersey:
        s = 2 if h >= 40 and font.text_width(jersey, 2) <= w - 4 else 1
        number_y = int(round(top + (h - top) * (0.28 if s == 2 else 0.3)))
        font.draw_text(box, jersey, int(round(cx)) + 1, number_y, readable_on(primary, accent), s, "center")
    img.paste(box, (x, y))


FLAME = ("..1..", ".121.", ".121.", "12321", "12321", ".232.", "..1..")
FLAME_COLORS = {"1": (225, 45, 20), "2": (255, 135, 20), "3": (255, 232, 130)}
SNOW = ("1.1.1", ".111.", "11111", ".111.", "1.1.1")
TROPHY = ("1111111", "1.111.1", ".11111.", "..111..", "...1...", "..111..", ".11111.")
CROWN = ("1..1..1", "11.1.11", "1111111", "1111111")
BOLT = ("..11", ".11.", "1111", ".11.", "11..")


def flame(img: Image.Image, x: int, y: int, flicker: bool = False) -> None:
    palette = dict(FLAME_COLORS)
    if flicker:
        palette = {"1": FLAME_COLORS["2"], "2": FLAME_COLORS["3"], "3": WHITE}
        _sprite(img, x, y, FLAME[:3], palette)
        _sprite(img, x, y + 3, FLAME[3:], FLAME_COLORS)
        return
    _sprite(img, x, y, FLAME, palette)


def snowflake(img: Image.Image, x: int, y: int) -> None:
    _sprite(img, x, y, SNOW, {"1": ICE})


def trophy(img: Image.Image, x: int, y: int, color: RGB = GOLD) -> None:
    _sprite(img, x, y, TROPHY, {"1": color})
    rect(img, x + 2, y + 1, 1, 1, mix(color, WHITE, 0.6))


def crown(img: Image.Image, x: int, y: int, color: RGB = GOLD) -> None:
    _sprite(img, x, y, CROWN, {"1": color})


def bolt(img: Image.Image, x: int, y: int, color: RGB = YELLOW) -> None:
    _sprite(img, x, y, BOLT, {"1": color})


def rays(img: Image.Image, x: int, y: int, w: int, h: int, cx: float, cy: float,
         rotation: float, c1: RGB, c2: RGB, spokes: int = 16) -> None:
    """A dim spinning sunburst behind a celebration, fading to black at the edges."""
    if w <= 0 or h <= 0:
        return
    burst = Image.new("RGB", (w, h), scale(c2, 0.15))
    draw = ImageDraw.Draw(burst)
    radius = math.hypot(w, h) * 1.2
    step = 2 * math.pi / spokes
    color = scale(c1, 0.3)
    for i in range(0, spokes, 2):
        a0 = rotation + i * step
        a1 = a0 + step
        draw.polygon([(cx - x, cy - y),
                      (cx - x + radius * math.cos(a0) / 0.6, cy - y + radius * math.sin(a0)),
                      (cx - x + radius * math.cos(a1) / 0.6, cy - y + radius * math.sin(a1))],
                     fill=color)
    vignette = Image.radial_gradient("L").resize((w, h))
    burst.paste(BLACK, (0, 0), vignette.point(lambda p: int(min(255, p * 1.3))))
    img.paste(burst, (x, y))


def confetti(img: Image.Image, x: int, y: int, w: int, h: int, t: float,
             colors: Sequence[RGB], count: int = 18, seed: int = 11) -> None:
    """Falling 1-2 px flakes. At most 22: more reads as dead pixels (football's rule)."""
    # Seeded so a frame is reproducible (goldens); decoration, not security.
    rng = random.Random(seed)  # nosec B311
    count = min(22, count)
    for i in range(count):
        x0 = rng.random() * w
        speed = 9 + rng.random() * 14
        phase = rng.random() * (h + 8)
        size = 2 if rng.random() < 0.4 else 1
        yy = ((phase + t * speed) % (h + 8)) - 6
        xx = x0 + math.sin(t * 2 + i) * 3
        rect(img, x + int(round(xx)), y + int(round(yy)), size, size, colors[i % len(colors)])


def hazard(img: Image.Image, x: int, y: int, w: int, h: int, offset: int = 0,
           c1: RGB = (150, 18, 30), c2: RGB = (36, 6, 10)) -> None:
    band = Image.new("RGB", (w, h), c2)
    draw = ImageDraw.Draw(band)
    for k in range(-h - 8, w + 8, 8):
        start = k + (offset % 8)
        draw.polygon([(start, 0), (start + 4, 0), (start + 4 - h, h), (start - h, h)], fill=c1)
    img.paste(band, (x, y))


def dot(img: Image.Image, cx: int, cy: int, color: RGB) -> None:
    """A 3x3 dot (the LIVE light). A plus-shaped one read as "+"."""
    rect(img, cx - 1, cy - 1, 3, 3, color)
