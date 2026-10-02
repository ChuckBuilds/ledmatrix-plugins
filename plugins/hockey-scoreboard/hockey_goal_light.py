"""The goal light: a pixel-art rink beacon drawn beside the scoring crest.

HockeyLive._draw_celebration_layout lets core draw the takeover, then lays this
over the finished frame. Everything here is integer maths on whole pixels, so a
frame is identical on every board and the golden images stay stable, and the
sprite frames are cached, because the celebration runs at up to 125 FPS.

The lamp is a bell-shaped lens on a bevelled lid and a short bolted post. A
bright reflector streak sweeps across the glass while striped beams fan out
either side, trading left and right the way a rotating reflector does; the lens
goes dark between flashes. All in the scoring team's colour, with a stepped
drop shadow, dim CRT scanlines on the beams and plus-shaped twinkles -- the look
Fantasy Blitz and blackjack use.

Animation is a function of elapsed seconds only, so any single frame (a 1 FPS
board samples one a second) is a finished picture.
"""

from typing import Dict, Tuple

from PIL import Image, ImageChops, ImageDraw

RGB = Tuple[int, int, int]

WHITE: RGB = (236, 240, 248)
INK: RGB = (6, 6, 12)
METAL_HI: RGB = (176, 184, 200)
METAL: RGB = (112, 120, 138)
METAL_SH: RGB = (60, 66, 82)
POST: RGB = (40, 44, 56)

#: Smallest panel that has room beside the crest and under the headline.
MIN_WIDTH = 256
MIN_HEIGHT = 48

#: Sprite canvas, the dome's centre column and how many rows the dome has.
SW, SH = 29, 31
CXS = 14
DOME_H = 21
SHADOW = 3

#: Flash cycles per second (x100) and steps per cycle.
CYCLES_PER_SECOND_X100 = 125
STEPS = 16
#: 8 * cos(2 pi k / 16), and where the reflector streak is on the glass.
_COS8 = (8, 7, 6, 3, 0, -3, -6, -7, -8, -7, -6, -3, 0, 3, 6, 7)
_SWEEP = (0, 2, 4, 5, 6, 5, 4, 2, 0, -2, -4, -5, -6, -5, -4, -2)
#: Beam stripes as slopes in 1/64: (near, far) either side of horizontal.
_STRIPES = ((3, 10), (16, 23))
_REACH = 74
#: Twelve directions, (cos, sin) * 64, for the sparks.
_DIRS = ((64, 0), (55, 32), (32, 55), (0, 64), (-32, 55), (-55, 32),
         (-64, 0), (-55, -32), (-32, -55), (0, -64), (32, -55), (55, -32))


def _mix(a: RGB, b: RGB, pct: int) -> RGB:
    return (a[0] + (b[0] - a[0]) * pct // 100,
            a[1] + (b[1] - a[1]) * pct // 100,
            a[2] + (b[2] - a[2]) * pct // 100)


def _scale(c: RGB, pct: int) -> RGB:
    return (min(255, c[0] * pct // 100), min(255, c[1] * pct // 100),
            min(255, c[2] * pct // 100))


def _lift(c: RGB, minimum: int = 170) -> RGB:
    """Brighten a dark team colour until its strongest channel reaches
    `minimum`, or a navy lamp vanishes on a panel."""
    top = max(c)
    if top <= 0:
        return (minimum, minimum, minimum)
    if top >= minimum:
        return c
    return (min(255, c[0] * minimum // top), min(255, c[1] * minimum // top),
            min(255, c[2] * minimum // top))


def _tones(color: RGB) -> Dict[str, RGB]:
    return {"hi": _mix(color, WHITE, 65), "mid": color,
            "shd": _scale(color, 55), "deep": _scale(color, 26)}


def _hw(y: int) -> int:
    """Half-width of the bell at row y: narrow shoulders, flared foot."""
    hw = 7 + (y * 5 + 10) // 20
    return hw - (3 - y) if y < 3 else hw


def _build_sprite(color: RGB, step: int, lit: bool) -> Image.Image:
    t = _tones(color)
    im = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    px = im.load()

    def put(x: int, y: int, c: RGB) -> None:
        if 0 <= x < SW and 0 <= y < SH:
            px[x, y] = (c[0], c[1], c[2], 255)

    for y in range(DOME_H):
        hw = _hw(y)
        for x in range(CXS - hw, CXS + hw + 1):
            if x in (CXS - hw, CXS + hw) or y == 0:
                put(x, y, INK)
                continue
            dx = x - CXS
            band = abs(dx) * 100 // max(1, hw - 1)
            if band > 78:
                tone = t["shd"]
            elif band > 50:
                tone = t["mid"]
            else:
                tone = t["hi"] if lit else t["mid"]
            if not lit:
                tone = _mix(tone, t["deep"], 55)
            inner = ((y in (3, DOME_H - 4) and abs(dx) <= hw - 3)
                     or (abs(dx) == hw - 3 and 3 <= y <= DOME_H - 4))
            if inner:
                tone = _mix(tone, WHITE, 30 if lit else 5)
            put(x, y, tone)
    # the fresnel ring on the lens
    ring = _mix(t["hi"], WHITE, 50 if lit else 0)
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            if 20 <= dx * dx + dy * dy <= 30:
                put(CXS + dx, 11 + dy, ring)
    # the reflector streak, three columns wide
    sx = CXS + _SWEEP[step % STEPS]
    for y in range(3, DOME_H - 3):
        limit = _hw(y) - 1
        for k, a in ((0, 100), (-1, 55), (1, 55)):
            x = sx + k
            if abs(x - CXS) < limit:
                put(x, y, _mix(t["hi"], WHITE, a * (40 + (60 if lit else 0)) // 100))
    for gx, gy in ((-6, 3), (-6, 4), (-6, 5), (-5, 3)):   # the fixed glint
        put(CXS + gx, gy, WHITE)
    # the lid, wider than the dome, and the post
    for x in range(CXS - 14, CXS + 15):
        put(x, DOME_H, INK)
    for y in range(DOME_H + 1, DOME_H + 4):
        for x in range(CXS - 14, CXS + 15):
            edge = x in (CXS - 14, CXS + 14) or y == DOME_H + 3
            put(x, y, INK if edge else (METAL_HI if y == DOME_H + 1 else METAL))
    for y in range(DOME_H + 4, SH):
        for x in range(CXS - 8, CXS + 9):
            edge = x in (CXS - 8, CXS + 8) or y == SH - 1
            put(x, y, INK if edge else (METAL_SH if x < CXS + 5 else POST))
    for bx in (CXS - 5, CXS + 5):
        put(bx, DOME_H + 6, METAL_HI)

    # a stepped drop shadow, the silhouette repeated down and right
    out = Image.new("RGBA", (SW + SHADOW, SH + SHADOW), (0, 0, 0, 0))
    mask = im.split()[3]
    for k in range(SHADOW, 0, -1):
        shade = _scale(t["deep"], 100 - 20 * (SHADOW - k))
        out.paste(Image.new("RGBA", im.size, shade + (255,)), (k, k), mask)
    out.paste(im, (0, 0), im)
    return out


_SPRITES: Dict[Tuple[RGB, int, bool], Image.Image] = {}


def _sprite(color: RGB, step: int, lit: bool) -> Image.Image:
    key = (color, step % STEPS, lit)
    spr = _SPRITES.get(key)
    if spr is None:
        if len(_SPRITES) > 96:
            _SPRITES.clear()
        spr = _SPRITES[key] = _build_sprite(color, step % STEPS, lit)
    return spr


_SCAN: Dict[Tuple[int, int], Image.Image] = {}


def _scanlines(w: int, h: int) -> Image.Image:
    """A multiply mask that dims every other row, the CRT look."""
    mask = _SCAN.get((w, h))
    if mask is None:
        mask = Image.new("RGB", (w, h), (255, 255, 255))
        d = ImageDraw.Draw(mask)
        for y in range(1, h, 2):
            d.line([(0, y), (w - 1, y)], fill=(184, 184, 184))
        _SCAN[(w, h)] = mask
    return mask


def _twinkle(d: ImageDraw.ImageDraw, w: int, h: int, x: int, y: int,
             size: int, c: RGB) -> None:
    for k in range(1, size + 1):
        for px_, py_ in ((x + k, y), (x - k, y), (x, y + k), (x, y - k)):
            if 0 <= px_ < w and 0 <= py_ < h:
                d.point((px_, py_), fill=c)
    if 0 <= x < w and 0 <= y < h:
        d.point((x, y), fill=WHITE)


def available(width: int, height: int) -> bool:
    """Whether a panel this size has room for the goal light."""
    return width >= MIN_WIDTH and height >= MIN_HEIGHT


def draw_goal_light(image: Image.Image, scored_side: str, crest_width: int,
                    color, elapsed: float, duration: float) -> Image.Image:
    """Draw the goal light onto `image`, the finished celebration frame (RGB),
    beside the scoring side's crest. Returns the image."""
    w, h = image.size
    if not available(w, h):
        return image
    color = _lift((int(color[0]), int(color[1]), int(color[2])))
    ms = max(0, int(elapsed * 1000))
    dur_ms = max(500, int(duration * 1000))
    # eased in over a quarter second, out over the last 0.8 s
    fade = min(100, ms * 100 // 250, max(0, (dur_ms - ms) * 100 // 800))
    if fade <= 0:
        return image

    step = ms * CYCLES_PER_SECOND_X100 * STEPS // 100000 % STEPS
    c8 = _COS8[step]
    il, ir = 8 + c8, 8 - c8                       # 0..16, always summing to 16
    lit = max(il, ir) >= 13
    left = scored_side != "home"                  # the away crest is on the left
    cx = crest_width + 36 if left else w - crest_width - 36
    top = (h - (SH + SHADOW)) // 2
    cy = top + 11                                 # the lens centre
    if cx < SW or cx > w - SW:
        return image

    # the halo and beams go on a dark layer that is added, then scanlined
    x_lo, x_hi = max(0, cx - 90), min(w, cx + 91)
    layer = Image.new("RGB", (x_hi - x_lo, h), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    lx = cx - x_lo
    halo = _scale(color, (10 + 16 * max(il, ir) // 16) * fade // 100)
    d.ellipse([lx - 21, cy - 21, lx + 21, cy + 21], fill=halo)
    inner_limit = w // 2 - 40                     # keep beams off the headline
    for side, inten in ((-1, il), (1, ir)):
        if inten <= 0:
            continue
        x0 = cx + side * 10
        reach = _REACH
        if (side == 1) == left:                   # the beam that faces the centre
            room = (inner_limit - x0) * side
            reach = min(reach, max(0, room))
        if reach < 6:
            continue
        col = _scale(color, (12 + 62 * inten * inten // 256) * fade // 100)
        for lo, hi in _STRIPES:
            for sign in (1, -1):
                d.polygon([(lx + side * 10, cy),
                           (lx + side * 10 + side * reach, cy + sign * lo * reach // 64),
                           (lx + side * 10 + side * reach, cy + sign * hi * reach // 64)],
                          fill=col)
    layer = ImageChops.multiply(layer, _scanlines(layer.width, h))
    image.paste(ImageChops.add(image.crop((x_lo, 0, x_hi, h)), layer), (x_lo, 0))

    spr = _sprite(color, step, lit)
    image.paste(spr, (cx - CXS, top), spr)

    d = ImageDraw.Draw(image)
    if lit:
        _twinkle(d, w, h, cx - 6, top + 4, 3, _mix(WHITE, color, 20))
    for i in range(6):                            # sparks flung out of the lamp
        dxu, dyu = _DIRS[(i * 5 + 1) % 12]
        ph = (ms // 10 * (90 + 7 * i) // 100 + i * 17) % 100
        r = 24 + ph * 26 // 100
        x = cx + dxu * r // 64
        y = cy + dyu * r * 4 // (64 * 5)
        size = (1, 2, 1)[ph * 3 // 100] if ph < 85 else 0
        _twinkle(d, w, h, x, y, size, _mix(WHITE, color, ph))
    return image
