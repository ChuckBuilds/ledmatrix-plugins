"""The Fantasy Blitz pixel font: 3x5 capitals, drawn through 1-bit masks.

Why a bitmap font instead of the core's TTFs: every glyph here is a fixed
grid of lit and unlit LEDs, so the text is 1-bit by construction (nothing for
FreeType to anti-alias), measures the same on every host (TTF advances vary
with the installed FreeType build, which breaks golden images), and scales in
whole steps for the chunky arcade numerals the cards use. The blackjack
plugin draws its cards the same way.

Glyphs are variable width -- most are 3 columns, ``M`` and ``W`` are 5 and
``N`` is 4 so they stay distinguishable -- with one blank column between
letters and a cap height of 5. Everything is upper case.
"""

import unicodedata
from collections import OrderedDict
from typing import Callable, Optional, Sequence, Tuple, Union

from PIL import Image, ImageFilter

RGB = Tuple[int, int, int]
#: Cap height in pixels at scale 1.
GLYPH_HEIGHT = 5

_GLYPHS = {
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("10001", "11011", "10101", "10001", "10001"),
    "N": ("1001", "1101", "1011", "1001", "1001"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "110", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("10001", "10001", "10101", "11011", "10001"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "011", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    ".": ("0", "0", "0", "0", "1"),
    ",": ("0", "0", "0", "1", "1"),
    "-": ("00", "00", "11", "00", "00"),
    "+": ("000", "010", "111", "010", "000"),
    "/": ("001", "001", "010", "100", "100"),
    ":": ("0", "1", "0", "1", "0"),
    "!": ("1", "1", "1", "0", "1"),
    "'": ("1", "1", "0", "0", "0"),
    "?": ("111", "001", "010", "000", "010"),
    "%": ("101", "001", "010", "100", "101"),
    "#": ("01010", "11111", "01010", "11111", "01010"),
    "(": ("01", "10", "10", "10", "01"),
    ")": ("10", "01", "01", "01", "10"),
    "&": ("0100", "1010", "0100", "1010", "0101"),
    " ": ("00", "00", "00", "00", "00"),
    "↑": ("010", "111", "010", "010", "010"),  # up arrow
    "↓": ("010", "010", "010", "111", "010"),  # down arrow
    "•": ("0", "0", "1", "0", "0"),  # bullet, a centred dot
}

#: Characters a feed may send that the grid lacks, mapped to a near match.
_SUBSTITUTES = {
    "’": "'", "‘": "'", "`": "'", "–": "-", "—": "-",
    "·": "•", "_": "-", ";": ":", "*": "•",
}

_MASK_CACHE: "OrderedDict[Tuple[str, int], Image.Image]" = OrderedDict()
_MASK_CACHE_MAX = 768


def normalize(text: object) -> str:
    """Upper-case ASCII the grid can draw: accents stripped, the rest mapped."""
    raw = "" if text is None else str(text)
    out = []
    for ch in raw:
        ch = _SUBSTITUTES.get(ch, ch)
        up = ch.upper()
        if up in _GLYPHS:
            out.append(up)
            continue
        folded = unicodedata.normalize("NFKD", ch)
        folded = "".join(c for c in folded if not unicodedata.combining(c)).upper()
        if folded and all(c in _GLYPHS for c in folded):
            out.append(folded)
        else:
            out.append("?")
    return "".join(out)


def _glyph(ch: str) -> Sequence[str]:
    return _GLYPHS.get(ch) or _GLYPHS["?"]


def text_width(text: object, scale: int = 1) -> int:
    """Width in pixels of ``text`` drawn at ``scale`` (no trailing gap)."""
    s = normalize(text)
    if not s:
        return 0
    total = sum(len(_glyph(ch)[0]) + 1 for ch in s) - 1
    return max(0, total) * max(1, int(scale))


def text_height(scale: int = 1) -> int:
    return GLYPH_HEIGHT * max(1, int(scale))


def text_mask(text: object, scale: int = 1) -> Optional[Image.Image]:
    """An ``L`` mask of the string, 255 where an LED is lit, 0 elsewhere."""
    s = normalize(text)
    scale = max(1, int(scale))
    if not s:
        return None
    key = (s, scale)
    cached = _MASK_CACHE.get(key)
    if cached is not None:
        _MASK_CACHE.move_to_end(key)
        return cached
    width = text_width(s, 1)
    mask = Image.new("L", (width, GLYPH_HEIGHT), 0)
    pixels = mask.load()
    x = 0
    for ch in s:
        rows = _glyph(ch)
        for row_index, row in enumerate(rows):
            for col, bit in enumerate(row):
                if bit == "1":
                    pixels[x + col, row_index] = 255
        x += len(rows[0]) + 1
    if scale > 1:
        mask = mask.resize((width * scale, GLYPH_HEIGHT * scale), Image.NEAREST)
    _MASK_CACHE[key] = mask
    while len(_MASK_CACHE) > _MASK_CACHE_MAX:
        _MASK_CACHE.popitem(last=False)
    return mask


ColorSpec = Union[RGB, Callable[[int, int], RGB]]


def _vertical_fill(size: Tuple[int, int], color_fn: Callable[[int, int], RGB]) -> Image.Image:
    """An RGB block whose row ``y`` is ``color_fn(y, height)``."""
    w, h = size
    column = Image.new("RGB", (1, h))
    column.putdata([tuple(int(max(0, min(255, c))) for c in color_fn(y, h)) for y in range(h)])
    return column.resize((w, h), Image.NEAREST)


def draw_text(img: Image.Image, text: object, x: int, y: int, color: ColorSpec,
              scale: int = 1, align: str = "left",
              outline: Optional[RGB] = None) -> int:
    """Draw ``text`` with its top-left (or centre / right edge) at ``x``.

    ``color`` is an RGB tuple or a ``(row, height) -> RGB`` function for a
    vertical gradient. ``outline`` draws a one-pixel ring first -- black is
    the house style for text over a gradient or a burst. Returns the width.
    """
    mask = text_mask(text, scale)
    if mask is None:
        return 0
    width = mask.width
    if align == "right":
        x -= width
    elif align == "center":
        x -= width // 2
    x, y = int(x), int(y)
    if outline is not None:
        ring = Image.new("L", (mask.width + 2, mask.height + 2), 0)
        ring.paste(mask, (1, 1))
        ring = ring.filter(ImageFilter.MaxFilter(3))
        img.paste(_fill(outline), (x - 1, y - 1), ring)
    if callable(color):
        img.paste(_vertical_fill(mask.size, color), (x, y), mask)
    else:
        img.paste(_fill(color), (x, y), mask)
    return width


def _fill(color: Union[int, Sequence[int]]) -> Union[int, Tuple[int, ...]]:
    """A paste colour: an RGB tuple, or a plain level for an ``L`` mask."""
    if isinstance(color, int):
        return color
    return tuple(int(c) for c in color)


def fit(text: object, max_width: int, scale: int = 1) -> str:
    """``text`` cut to ``max_width`` at a whole character, never mid-glyph."""
    s = normalize(text)
    while s and text_width(s, scale) > max_width:
        s = s[:-1]
    return s.rstrip()
