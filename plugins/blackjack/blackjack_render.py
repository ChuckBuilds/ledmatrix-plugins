"""Table rendering for the LEDMatrix ``blackjack`` plugin.

Everything here is a pure function of a :class:`ViewState` and a panel size, so
a frame can be produced for any instant of a hand without the plugin holding
animation state that could fall out of step.

Two things drive the visual design:

* **Negative space.** An LED matrix is emissive, so unlit pixels are true black
  and lit ones are the whole picture. The table is therefore mostly darkness
  with a few bright shapes: cards are dark faces with a lit border and a lit
  rank, not white rectangles. The classic "ivory card" look lights ~70% of the
  panel and, on a real matrix, washes out into a glare with no shape to it.
* **A table, not a void.** Negative space is not the same thing as nothing.
  The felt is a *dithered* field at a tenth of the felt colour -- about a
  twentieth of the light a card puts out -- with a rail around it, a bevelled
  rule between the seats.
  That is the difference between a game screen and two numbers floating in the
  dark, and it costs almost no lit pixels: the texture is an ordered pattern of
  the dimmest tone the panel can hold, not a wash. ``Theme.table_style`` keeps
  the bare version ('void') for anyone who wants it.
* **Integer-scaled bitmap type.** The text is a 3x5 pixel face drawn as
  scaled blocks rather than a rasterised TTF, so a glyph is the same crisp
  shape at every scale on every panel -- no anti-aliased grey fringe, and no
  dependence on which Pillow layout engine the host happens to have.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from blackjack_engine import (
    RED_SUITS,
    Card,
    TONE_BLACKJACK,
    TONE_LOSE,
    TONE_PUSH,
    TONE_WIN,
)

RGB = Tuple[int, int, int]

# ---------------------------------------------------------------------------
# 3x5 bitmap face
# ---------------------------------------------------------------------------

#: Glyphs as row strings; width is per-glyph so M, N and W get the columns they
#: need instead of every letter paying for them.
_GLYPHS: Dict[str, Tuple[str, ...]] = {
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
    "K": ("101", "110", "100", "110", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("10001", "11011", "10101", "10001", "10001"),
    "N": ("1001", "1101", "1011", "1001", "1001"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "011"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("10001", "10001", "10101", "11011", "10001"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "!": ("1", "1", "1", "0", "1"),
    "?": ("110", "001", "010", "000", "010"),
    "-": ("000", "000", "111", "000", "000"),
    ".": ("0", "0", "0", "0", "1"),
    ":": ("0", "1", "0", "1", "0"),
    "+": ("000", "010", "111", "010", "000"),
    "/": ("001", "001", "010", "100", "100"),
    " ": ("00", "00", "00", "00", "00"),
}

GLYPH_HEIGHT = 5
#: Blank columns between glyphs, in unscaled pixels.
GLYPH_TRACKING = 1


def text_width(text: str, scale: int = 1) -> int:
    """Rendered width of ``text`` in pixels at ``scale``, tracking included."""
    total = 0
    for index, char in enumerate(text.upper()):
        glyph = _GLYPHS.get(char)
        if glyph is None:
            glyph = _GLYPHS[" "]
        total += len(glyph[0]) * scale
        if index < len(text) - 1:
            total += GLYPH_TRACKING * scale
    return total


def text_height(scale: int = 1) -> int:
    return GLYPH_HEIGHT * scale


def fit_scale(text: str, max_width: int, max_scale: int = 4, min_scale: int = 1) -> int:
    """Largest scale at which ``text`` still fits ``max_width``.

    Returns ``min_scale`` when even that overflows -- the caller is expected to
    have already decided the text is worth drawing, and a clipped word is more
    useful than a missing one.
    """
    for scale in range(max_scale, min_scale, -1):
        if text_width(text, scale) <= max_width:
            return scale
    return min_scale


def draw_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: RGB,
              scale: int = 1) -> int:
    """Draw ``text`` with its top-left at ``(x, y)``. Returns the width drawn."""
    cursor = x
    for index, char in enumerate(text.upper()):
        glyph = _GLYPHS.get(char) or _GLYPHS[" "]
        _blit_glyph(draw, cursor, y, glyph, color, scale)
        cursor += len(glyph[0]) * scale
        if index < len(text) - 1:
            cursor += GLYPH_TRACKING * scale
    return cursor - x


def draw_text_centered(draw: ImageDraw.ImageDraw, center_x: int, y: int, text: str,
                       color: RGB, scale: int = 1) -> None:
    draw_text(draw, center_x - text_width(text, scale) // 2, y, text, color, scale)


def _blit_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, glyph: Sequence[str],
                color: RGB, scale: int) -> None:
    for row_index, row in enumerate(glyph):
        run_start = None
        for col_index in range(len(row) + 1):
            lit = col_index < len(row) and row[col_index] == "1"
            if lit and run_start is None:
                run_start = col_index
            elif not lit and run_start is not None:
                # One rectangle per horizontal run rather than per pixel: a
                # banner at scale 3 is ~500 set pixels, and PIL call overhead
                # dominates at 125 fps.
                x0 = x + run_start * scale
                y0 = y + row_index * scale
                draw.rectangle(
                    [x0, y0, x0 + (col_index - run_start) * scale - 1, y0 + scale - 1],
                    fill=color,
                )
                run_start = None


# ---------------------------------------------------------------------------
# Rank and suit art
# ---------------------------------------------------------------------------

#: The face card ranks and hand totals are set in. It is 5x7 rather than the
#: 3x5 used for labels and the result banner, because those are *words* -- read
#: by shape, and forgiving of a cramped face -- while a rank is a single
#: character with no context to disambiguate it. At 3x5 there are only fifteen
#: pixels to tell 2, 3, 5, 8 and 9 apart, and they lose: each is a stack of
#: three horizontal bars differing in which of two side pixels are lit. Two
#: more rows and two more columns buy real bowls and diagonals, which is the
#: difference between reading a card and inferring it.
#:
#: Cost: a 5-wide glyph needs a 7px card interior, so this face is used down to
#: a 7x9 card and the 3x5 set takes over below that -- a size at which a card
#: is nine pixels tall and legibility was already lost.
NUMERAL_HEIGHT = 7

_NUMERALS: Dict[str, Tuple[str, ...]] = {
    "0": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    # Flat-topped, so the left side stays open. The round-topped 3 that reads
    # better in print differs from an 8 by three lit pixels here, all of them
    # in the left column -- which on a matrix at arm's length is not a
    # difference at all.
    "3": ("11111", "00010", "00100", "01110", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
}

#: Ten is the only two-character rank. Setting it as two 5-wide numerals would
#: make it twice the width of every other rank, so every card on the panel
#: would have to shrink to the size a ten needs. Instead it gets one glyph the
#: same 5 columns wide as the rest: a bare stem for the one, a full ring for
#: the zero. Nothing else on a card is two characters, so there is no ambiguity
#: for the narrow one to cause.
_RANK_GLYPHS: Dict[str, Tuple[str, ...]] = dict(
    {rank: _NUMERALS[rank] for rank in
     ("2", "3", "4", "5", "6", "7", "8", "9", "A", "J", "Q", "K")},
    **{"10": ("10111", "10101", "10101", "10101", "10101", "10101", "10111")},
)


def numeral_width(text: str, scale: int = 1) -> int:
    """Rendered width of ``text`` in the 5x7 numeral face."""
    total = 0
    for index, char in enumerate(text.upper()):
        glyph = _NUMERALS.get(char) or _NUMERALS["-"]
        total += len(glyph[0]) * scale
        if index < len(text) - 1:
            total += GLYPH_TRACKING * scale
    return total


def numeral_height(scale: int = 1) -> int:
    return NUMERAL_HEIGHT * scale


def draw_numerals(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
                  color: RGB, scale: int = 1) -> None:
    """Draw ``text`` in the 5x7 numeral face, top-left at ``(x, y)``."""
    cursor = x
    for index, char in enumerate(text.upper()):
        glyph = _NUMERALS.get(char) or _NUMERALS["-"]
        _blit_glyph(draw, cursor, y, glyph, color, scale)
        cursor += len(glyph[0]) * scale
        if index < len(text) - 1:
            cursor += GLYPH_TRACKING * scale


#: 5x5 suit pips.
#:
#: Spade and club are the pair that has to work: they are the same colour, so
#: shape is all the eye has. The previous club opened with a split row
#: (``01010``) over a full one, which on a matrix reads as an asterisk rather
#: than a clover -- two lit dots with a gap are a sparkle, not a lobe. Both
#: marks are built from profile instead: the spade widens from a point and
#: flares into a foot, while the club alternates wide-narrow-wide down its
#: length, which is the only trace of three lobes that survives at this size.
#: The first attempt gave the club a solid two-row cap, which read cleanly on
#: its own but shared three of its five rows with the spade; alternating rows
#: reads just as well and puts eight pixels between them.
_PIPS: Dict[str, Tuple[str, ...]] = {
    "H": ("01010", "11111", "11111", "01110", "00100"),
    "D": ("00100", "01110", "11111", "01110", "00100"),
    "S": ("00100", "01110", "11111", "11111", "01110"),
    "C": ("01110", "11111", "01110", "11111", "00100"),
}

#: 3x3 pips for cards too small for the 5x5 set. Nine pixels cannot draw a
#: suit, only tell them apart, so the set is chosen for contrast: heart and
#: diamond differ at the top (two bumps against one point), and spade and club
#: are each other upside down -- spade points up over a solid base, club is a
#: solid cap over a stem. Club sits one pixel from heart, which is harmless
#: because a club is never drawn in the red ink and a heart is never drawn in
#: the black.
_PIPS_SMALL: Dict[str, Tuple[str, ...]] = {
    "H": ("101", "111", "010"),
    "D": ("010", "111", "010"),
    "S": ("010", "111", "111"),
    "C": ("111", "111", "010"),
}



#: 7x7 pips, for cards with room for a suit mark that is actually drawn rather
#: than merely indicated. Seven rows is the first size at which a club can have
#: its three lobes *and* a one-pixel neck under the top one. That neck is the
#: whole difference: a spade widens from its point to its shoulders without
#: interruption, so a club whose top lobe merges straight into the side pair is
#: a spade with a blunt tip. Pinching it costs one row and separates the two
#: marks by ten pixels instead of eight.
_PIPS_LARGE: Dict[str, Tuple[str, ...]] = {
    "H": ("0110110", "1111111", "1111111", "1111111", "0111110", "0011100", "0001000"),
    "D": ("0001000", "0011100", "0111110", "1111111", "0111110", "0011100", "0001000"),
    "S": ("0001000", "0011100", "0111110", "1111111", "1111111", "0001000", "0011100"),
    "C": ("0011100", "0111110", "0001000", "1101011", "1111111", "0001000", "0011100"),
}


#: Pip faces widest-first. Picking is "largest bitmap that fits at 1:1, then
#: scale that up", never "whichever face gives the most drawn pixels": a 3x3
#: doubled is twelve pixels of nothing, while a 7x7 at 1:1 in the same box is a
#: club you can name.
_PIP_FACES: Tuple[Tuple[int, Dict[str, Tuple[str, ...]]], ...] = (
    (7, _PIPS_LARGE), (5, _PIPS), (3, _PIPS_SMALL),
)


def _draw_edge(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
               edge: RGB, lit: RGB, shade: RGB) -> None:
    """The card's border, lit along the top and left and dropped along the
    bottom and right.

    One pixel is the entire thickness available, so depth has to come from
    brightness rather than from geometry: the eye reads a consistent light
    direction across a row of cards as the cards standing off the felt, which a
    single flat outline never gave. The two tones average to the flat outline's
    brightness, so the row does not get louder -- only rounder.

    Below 5px the bevel is dropped for a flat outline. At that size two of the
    four sides are one pixel long, and a card whose edge is brighter on two
    adjacent pixels reads as a rendering fault, not as a light source.
    """
    right, bottom = x + w - 1, y + h - 1
    if w < 5 or h < 5:
        draw.rectangle([x, y, right, bottom], outline=edge)
        return
    # One outline in the lit tone and two lines back over it, rather than four
    # lines: three PIL calls per card instead of four, and there are ten cards
    # on a 256x128 table every frame.
    draw.rectangle([x, y, right, bottom], outline=lit)
    draw.line([(x, bottom), (right, bottom)], fill=shade)
    draw.line([(right, y), (right, bottom)], fill=shade)
    _round_corners(draw, x, y, w, h)


def _fit_pip(suit: str, avail_w: int, avail_h: int):
    """``(glyph, scale, size)`` for the biggest pip that fits, or ``None``."""
    for size, face in _PIP_FACES:
        if size > avail_w or size > avail_h:
            continue
        scale = min(avail_w // size, avail_h // size)
        return face.get(suit), scale, size * scale
    return None


def _pip_gap(rank_scale: int) -> int:
    """Blank rows between the rank and its pip."""
    return max(1, rank_scale // 2)


def _pip_ink(ink: RGB, face: RGB) -> RGB:
    """The pip sits one step back from the rank: read the rank, then the suit.

    Stepping *toward the face* rather than scaling the ink down is what makes
    this work in both card styles. On an ivory solid face the ink is nearly
    black, so a scaled-down ink was a *darker* pip than the rank -- the
    hierarchy inverted on exactly the style that has the least contrast to
    spare.
    """
    return tuple(int(round(i + (f - i) * 0.3)) for i, f in zip(ink, face))  # type: ignore[return-value]


def _rank_and_pip(glyph_w: int, inner_w: int, inner_h: int, suit: str):
    """``(rank_scale, pip)`` for a face this size, ``pip`` possibly ``None``.

    The rank is sized against its own height plus a two-row allowance, not "as
    large as fits": a glyph that fills its card edge to edge stops reading as a
    character and starts reading as a lit rectangle with notches in it.

    On a large card the rank then gives back one step if -- and only if -- that
    buys a bigger suit mark. A 35x49 card at the unmodified scale spends 35 of
    its 47 interior rows on the numeral and leaves the suit a 7px speck, which
    is what makes the card read as a scoreboard digit rather than a card. One
    step down is a 28px numeral (still enormous) beside a 14px pip, and the two
    marks read as a pair. The trade is refused when it changes nothing, so a
    29x41 card keeps its taller rank rather than shrinking it for the same pip.
    """
    rank_scale = max(1, min(inner_w // glyph_w, inner_h // (NUMERAL_HEIGHT + 2)))

    def pip_for(scale: int):
        block_h = NUMERAL_HEIGHT * scale
        avail_h = inner_h - block_h - _pip_gap(scale)
        # Never taller than about three fifths of the rank: the rank is what
        # you read and the pip is what confirms it, and a pip that matches the
        # numeral turns the card into two marks arguing about which one is the
        # value. The floor of five is the smallest card's exemption -- at rank
        # scale 1 three fifths is four pixels, which throws away the 5x5 pip a
        # 128x32 panel has always had room for and leaves a 3x3 in its place.
        avail_h = min(avail_h, max(5, block_h * 3 // 5))
        if avail_h < 3 or inner_w < 3:
            return None
        return _fit_pip(suit, inner_w, avail_h)

    pip = pip_for(rank_scale)
    if rank_scale >= 4:
        alternative = pip_for(rank_scale - 1)
        # Half again bigger, not merely bigger. A 27x38 card can trade seven
        # rows of numeral for two pixels of pip, which is paying rank height
        # for nothing anyone can see; the trade is only worth making when it
        # moves the pip up a whole step.
        if alternative and (pip is None or alternative[2] * 2 > pip[2] * 3):
            return rank_scale - 1, alternative
    return rank_scale, pip



WHITE: RGB = (255, 255, 255)


#: Solid black frames, one per panel size, for the banner's table dim.
#: ``Image.blend`` against a cached black is about half the cost of
#: ``point(lambda ...)``, which rebuilds a 256-entry lookup table by calling
#: back into Python 768 times -- every frame, for the four seconds the banner
#: is up.
_BLACK_FRAMES: Dict[Tuple[int, int], Image.Image] = {}


#: Fraction of the slide spent covering the distance; the rest is the card
#: rocking into its place. Kept high because the settle has to read as an
#: arrival, not as a second move.
_SETTLE_AT = 0.86


def mix_color(color: RGB, other: RGB, amount: float) -> RGB:
    """``color`` moved ``amount`` of the way toward ``other``.

    Brightening an accent is not scale_color's job: the tones are already at or
    near 255 in their strongest channel (blackjack gold is 255,208,32), so
    scaling up clips to the same colour and nothing appears to happen. Mixing
    toward white is the only headroom a saturated tone has left.
    """
    amount = max(0.0, min(1.0, amount))
    return (
        int(round(color[0] + (other[0] - color[0]) * amount)),
        int(round(color[1] + (other[1] - color[1]) * amount)),
        int(round(color[2] + (other[2] - color[2]) * amount)),
    )


def _black_like(image: Image.Image) -> Image.Image:
    frame = _BLACK_FRAMES.get(image.size)
    if frame is None:
        frame = Image.new("RGB", image.size, (0, 0, 0))
        _BLACK_FRAMES[image.size] = frame
    return frame


def _draw_trail(draw: ImageDraw.ImageDraw, x: int, y: int, seat: SeatLayout,
                step: int, strength: float, theme: Theme) -> None:
    """Two dim outlines behind a card in flight.

    A matrix has no persistence and the deal is eleven frames long, so a card
    crossing the table jumps four pixels per frame and reads as a row of stills
    rather than as a throw. These are the motion blur the panel cannot give it:
    outlines rather than filled ghosts, because a solid block at a third
    brightness beside a dark card just looks like a second, blurrier card.
    """
    if strength <= 0.05 or step <= 0:
        return
    bottom = y + seat.card_h - 1
    for depth, weight in ((1, 0.55), (2, 0.26)):
        left = x + depth * step
        if left > seat.x + seat.width:
            continue
        draw.rectangle([left, y, left + seat.card_w - 1, bottom],
                       outline=scale_color(theme.card_back_ink, weight * strength))


def _draw_chase(draw: ImageDraw.ImageDraw, width: int, top: int, bottom: int,
                thickness: int, tone: RGB, clock: float, speed: float) -> None:
    """Marquee lights running along the band's two rules.

    This is what replaced a 15% brightness sine over the whole banner. That
    pulse moved the fill, the rules and the *type* together, which on a matrix
    is the signature of a sagging supply rather than of a celebration -- and it
    was the only thing separating a win from a loss, at a depth of modulation
    you have to stare at to see. Motion in the chrome is unmistakable at a
    glance and leaves the word rock steady.

    Drawn as one rectangle per lit segment rather than per pixel: a 256px rule
    is ~20 segments against 256 point() calls, and this runs every frame for
    the length of the banner.
    """
    period = max(5, width // 11)
    seg = max(2, period // 3)
    hot = mix_color(tone, WHITE, 0.55)
    offset = (clock * speed) % period
    # The two rules run opposite ways. Chasing in the same direction reads as
    # the whole band sliding sideways; mirrored, it reads as lights around a
    # sign.
    start = int(round(offset)) - period
    while start < width:
        draw.rectangle([start, top, start + seg - 1, top + thickness - 1], fill=hot)
        mirrored = width - 1 - (start + seg - 1)
        draw.rectangle([mirrored, bottom - thickness + 1, mirrored + seg - 1, bottom],
                       fill=hot)
        start += period



#: Cells that draw nothing. ``0`` is the pip faces' blank and ``.`` the
#: sprites'; accepting both spellings lets a pip bitmap and a court figure go
#: through one blitter.
_BLANK_CELLS = ".0"


_COURT_SPRITES: Dict[str, Tuple[str, ...]] = {
    # Three icons that separate by *silhouette class* before any detail
    # resolves: a standard on a staff, a round crown, a spiked crown with a
    # cross. At scale 1 -- where these can land on a card only 20px wide -- a
    # figure's face would be five pixels across, so the outline is the whole
    # design and nothing inside it can be read.
    #
    # The set this replaced drew a whole figure each, differing in the crown,
    # the hair and the collar. At scale 1 they were three white masses of
    # near-identical area, because at eleven pixels wide a filled human
    # silhouette has no room to be anything but a mass.
    #
    # The two crowns are symmetric and bottom-heavy, so the jack is
    # deliberately neither: left-aligned, top-heavy, asymmetric. A plain cap
    # was tried first and says nothing -- it is a shape, not a rank. Of the
    # things that do say something, a sword reads at scale 1 as a bare cross,
    # which is exactly the mark on top of the king's crown; the standard does
    # not collide with anything else on the table, and a page carrying the
    # banner is what the rank is.
    "J": (
        "...........",
        "...........",
        "...........",
        "..#######..",
        "..#....##..",
        "..#...##...",
        "..#..##....",
        "..#.##.....",
        "..###......",
        "..#........",
        "..#........",
        "..#........",
        "..#........",
        "...........",
        "...........",
        "...........",
        "...........",
    ),
    "Q": (
        "...........",
        "...........",
        "...........",
        "..##...##..",
        ".####.####.",
        ".#########.",
        ".#########.",
        ".#########.",
        "..#######..",
        "...........",
        "..#######..",
        "...........",
        "...........",
        "...........",
        "...........",
        "...........",
        "...........",
    ),
    "K": (
        "...........",
        ".....#.....",
        "....###....",
        ".....#.....",
        ".#...#...#.",
        ".#...#...#.",
        ".#...#...#.",
        ".##.###.##.",
        ".#########.",
        ".#########.",
        ".#########.",
        "...........",
        "..#######..",
        "...........",
        "...........",
        "...........",
        "...........",
    ),
}


_INDEX_BLOCKS: Dict[Tuple[str, str], Tuple[str, ...]] = {}


_PIP_FACE_BY_SIZE: Dict[int, Dict[str, Tuple[str, ...]]] = {
    size: face for size, face in _PIP_FACES
}


#: Where each rank's pips sit, as ``(column, row)`` on a 3-column by 13-row
#: grid spanning the pip field. Thirteen rows rather than the seven you might
#: expect, because the classic arrangement is not on one pitch: the pairs of a
#: nine sit on quarters (rows 0/4/8/12) while the pairs of a seven sit on halves
#: (0/6/12), and a seven's odd pip sits *between* its first two pairs (row 3).
#: Thirteen steps is the coarsest grid that lands all three exactly, so no
#: rank's pips are a rounding error away from another's.
#:
#: These are the real arrangements, not a tidy grid -- a seven is six pips in
#: two columns with the seventh raised into the upper gap, not a 2-3-2 block.
#: Get it wrong and the card reads as a domino.
_PIP_LAYOUTS: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "2": ((1, 0), (1, 12)),
    "3": ((1, 0), (1, 6), (1, 12)),
    "4": ((0, 0), (2, 0), (0, 12), (2, 12)),
    "5": ((0, 0), (2, 0), (1, 6), (0, 12), (2, 12)),
    "6": ((0, 0), (2, 0), (0, 6), (2, 6), (0, 12), (2, 12)),
    "7": ((0, 0), (2, 0), (1, 3), (0, 6), (2, 6), (0, 12), (2, 12)),
    "8": ((0, 0), (2, 0), (1, 3), (0, 6), (2, 6), (1, 9), (0, 12), (2, 12)),
    "9": ((0, 0), (2, 0), (0, 4), (2, 4), (1, 6), (0, 8), (2, 8), (0, 12), (2, 12)),
    "10": ((0, 0), (2, 0), (1, 2), (0, 4), (2, 4),
           (0, 8), (2, 8), (1, 10), (0, 12), (2, 12)),
}


_ROTATED: Dict[Tuple[str, ...], Tuple[str, ...]] = {}


#: Run decomposition of a sprite, cached by the sprite itself. A 7x7 pip is
#: eight rectangles and fifty string lookups; a 256x128 table draws up to a
#: hundred pips and twenty index blocks every frame, and the string half of
#: that cost is the half that never changes.
_SPRITE_RUNS: Dict[Tuple[str, ...], Tuple[Tuple[int, int, int, str], ...]] = {}


def _blit_keylined(draw: ImageDraw.ImageDraw, x: int, y: int,
                   rows: Tuple[str, ...], ink: RGB, keyline: RGB,
                   scale: int) -> None:
    """``_blit_sprite`` with a one-pixel outline a step back from the ink.

    The keyline is one pixel at every scale rather than one *cell*, because it
    is doing the job an outline does in a sprite sheet -- separating the mark
    from what is behind it -- and a four-pixel border on a scale-4 ace is a
    second shape, not an edge. Dilating each run by a pixel is the same set as
    dilating the whole glyph, so the two passes cost one extra rectangle per
    run rather than a per-pixel sweep.
    """
    for row_index, start, end, _char in _sprite_runs(rows):
        x0 = x + start * scale
        y0 = y + row_index * scale
        draw.rectangle([x0 - 1, y0 - 1, x0 + (end - start + 1) * scale,
                        y0 + scale], fill=keyline)
    for row_index, start, end, _char in _sprite_runs(rows):
        x0 = x + start * scale
        y0 = y + row_index * scale
        draw.rectangle([x0, y0, x0 + (end - start + 1) * scale - 1,
                        y0 + scale - 1], fill=ink)


def _blit_sprite(draw: ImageDraw.ImageDraw, x: int, y: int,
                 rows: Tuple[str, ...], colors: Dict[str, RGB],
                 scale: int = 1) -> None:
    """Draw a multi-tone sprite, one rectangle per run of one colour."""
    for row_index, start, end, char in _sprite_runs(rows):
        color = colors.get(char)
        if color is None:
            continue
        x0 = x + start * scale
        y0 = y + row_index * scale
        draw.rectangle([x0, y0, x0 + (end - start + 1) * scale - 1,
                        y0 + scale - 1], fill=color)


def _card_plan(inner_w: int, inner_h: int):
    """``(pip, index_scale, side, top, index_corners)``, or ``None``.

    ``None`` sends the caller to the compact centred-rank face.

    **A pip field is never drawn without a corner index.** An earlier version
    bought the index only where it cost the pips nothing, which meant the two
    middle tiers drew a rank as an uncounted field of specks and nothing else:
    on a 128x64 panel a five, a six and a seven were three 3x3 blobs, four, and
    five, with no numeral anywhere on the card. Counting blobs is not reading,
    and the hand's value is the one thing on this screen anybody needs. A real
    deck does not do it either -- the index in the corner is exactly what makes
    a fanned hand readable, and pips without one is a half-drawn card, not a
    purer one.

    So the index is bought first and the pips take what is left. Where even a
    single index leaves no room to lay a ten out classically, the card gives up
    on pips altogether and falls back to the centred 5x7 rank, which is the
    most legible thing a small card can carry.

    Two indexes when the card can afford them, one otherwise. The rotated
    bottom-right copy is what makes a big card look printed rather than
    packed, but it is a luxury: cards here are fanned left to right, so the
    top-left index is the one that stays visible when a hand overlaps, and
    spending a second gutter on the hidden corner is what pushed a 23x33 card
    off pips entirely.
    """

    def fit(left_gutter: int, right_gutter: int):
        """Largest pip and the top margin it allows, for these gutters.

        The top margin is given up before the pip size is: a pip that touches
        the card's shoulder still reads as a pip, while a smaller one is a
        smaller statement of the rank.
        """
        for margin in range(max(1, inner_h // 12), 0, -1):
            pip = _pip_for_field(inner_w - left_gutter - right_gutter,
                                 inner_h - 2 * margin)
            if pip is not None:
                return pip, margin
        return None, 1

    # The sprite tier is only for a card big enough to be a *printed* card:
    # 5x5 pips or better, and a double-size index in both corners. Both halves
    # of that come straight from the complaint that sent this back.
    #
    # A 3x3 pip is a speck -- counting nine of them on a panel across a room is
    # slower than reading one numeral, which is the whole reason a deck prints
    # an index. And a scale-1 index on a big card is the same 5x7 numeral that
    # fills an entire small card, so on a 512x64 strip it came out as a tiny
    # mark in the corner of a large empty face: the rank was technically on the
    # card and practically not.
    #
    # The consequence is deliberate and worth stating: no panel in the harness
    # sample, and none of the panels this is actually run on, reaches this. A
    # card needs roughly a 39x46 interior, which wants a panel bigger than
    # 256x128. The art is exercised by the tests at explicit sizes rather than
    # by any rendered sheet.
    #
    # Every affordable arrangement, then the best of them -- not the first
    # that fits. Taking the first put a scale-2 index on the largest card and
    # paid for it with the pips, dropping a 38x55 face from 7x7 marks to 3x3:
    # the index is mandatory, but it is not worth more than the thing it
    # labels. Bigger pips win, then the second index, then a bigger index.
    best = None
    for scale in (2, 1):
        if INDEX_H * scale + 2 > inner_h:
            continue
        gutter = INDEX_W * scale + 1
        for side in (1, 0):
            for corners in (2, 1):
                # Two indexes on one diagonal: the upright one has to clear the
                # rotated one, or a tall thin card stacks them into each other.
                if corners == 2 and 2 * INDEX_H * scale + 2 > inner_h:
                    continue
                right = gutter if corners == 2 else side
                pip, top = fit(gutter, right)
                if pip is None or pip < 5 or scale < 2 or corners < 2:
                    continue
                rank = (pip, corners, scale, side)
                if best is None or rank > best[0]:
                    best = (rank, (pip, scale, side, top, corners))
    return best[1] if best else None

def _draw_ace(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
              suit: str, ink: RGB, keyline: RGB) -> None:
    """One outsized pip, keylined.

    The ace is the one rank a real deck draws large, and at these sizes it is
    the only one with the room to be *ornate* rather than merely counted. The
    ornament is a one-pixel outline rather than a ruled panel: a rectangle
    around the pip, tried first, reads as a second card border two pixels
    inside the first, and on a 23x33 card that is three concentric frames.
    """
    # Three fifths of the field, not all of it -- a pip that reaches the card's
    # edges stops reading as a mark placed on a card and starts reading as the
    # card being that colour.
    fitted = _fit_pip(suit, w, max(7, h * 3 // 5))
    if not fitted or not fitted[0]:
        return
    glyph, scale, size = fitted
    px = x + (w - size) // 2
    py = y + (h - size) // 2
    if scale >= 2 and size + 2 <= w and size + 2 <= h:
        _blit_keylined(draw, px, py, glyph, ink, keyline, scale)
    else:
        # A one-pixel keyline on a 7x7 pip drawn at 1:1 is not an edge, it is a
        # second ring of ink half again the width of the mark -- the club and
        # the spade both come out of it as the same soft blob. From scale 2 the
        # outline is a tenth of the pip and does what an outline is for.
        _blit_sprite(draw, px, py, glyph, {"1": ink}, scale)


def _draw_card_art(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                   card: Card, ink: RGB, face: RGB, plan) -> bool:
    """Draw a card's interior in the sprite tier. ``False`` to fall back.

    ``(x, y, w, h)`` is the interior, inside the border.
    """
    pip_size, index_scale, side, top, index_corners = plan
    # Stepped toward the face rather than scaled down from the ink: on the
    # solid style the ink is nearly black, so a scaled ink is a *darker*
    # secondary and the court figures came out as silhouettes with darker holes
    # punched in them -- the hierarchy inverting on the style with the least
    # contrast to spare.
    mid = mix_color(ink, face, 0.30)

    gutter = INDEX_W * index_scale + 1 if index_scale else side
    # With one index the field is pushed off the left gutter only; with two it
    # sits centred between them, the way a printed card is laid out.
    right = gutter if index_corners == 2 else side
    field_x, field_w = x + gutter, w - gutter - right
    field_y, field_h = y + top, h - 2 * top

    court = _COURT_SPRITES.get(card.rank)
    court_scale = 0
    if court is not None:
        court_scale = min(field_w // _COURT_W, field_h // _COURT_H)
        if court_scale < 1:
            # Wide enough for pips but too short for a figure. A court sprite
            # squeezed out of proportion is a smear, and the compact face still
            # says J, Q or K.
            return False

    if index_scale:
        block = _index_block(card.rank, card.suit)
        colors = {"#": ink, "+": mid}
        _blit_sprite(draw, x, y, block, colors, index_scale)
        if index_corners == 2:
            # The second index is rotated, not repeated. It is how a real card
            # is readable fanned from either side, and it is the detail that
            # stops a big card looking like a poster of a card.
            _blit_sprite(draw, x + w - INDEX_W * index_scale,
                         y + h - INDEX_H * index_scale,
                         _rotate180(block), colors, index_scale)

    if court is not None:
        sprite_w, sprite_h = _COURT_W * court_scale, _COURT_H * court_scale
        _blit_sprite(draw, field_x + (field_w - sprite_w) // 2,
                     field_y + (field_h - sprite_h) // 2, court,
                     {"#": ink, "+": mid}, court_scale)
    elif card.rank == "A":
        _draw_ace(draw, field_x, field_y, field_w, field_h, card.suit, ink, mid)
    else:
        _draw_pip_field(draw, field_x, field_y, field_w, field_h,
                        card.rank, card.suit, pip_size, ink)
    return True


def _draw_pip_field(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                    rank: str, suit: str, pip_size: int, ink: RGB) -> None:
    """The rank drawn as its count of pips, in the classic arrangement."""
    glyph = _PIP_FACE_BY_SIZE[pip_size][suit]
    # Pips below the midline are turned over, as they are on a real card, so
    # the hand reads the same from either end of the table. Only at 7x7, and
    # the reason is measured rather than aesthetic: an inverted 3x3 spade *is*
    # the 3x3 club, pixel for pixel, and an inverted 5x5 spade comes within
    # four pixels of one -- closer than the sixth of a face the pip set is held
    # to, on the one pair colour cannot separate. At 7x7 the closest
    # same-coloured pair the flip creates is eleven pixels of forty-nine, so
    # the mark stays its own suit upside down. See the turned-pip test.
    lower = _rotate180(glyph) if pip_size >= 7 else glyph
    span_x, span_y = w - pip_size, h - pip_size
    for col, row in _PIP_LAYOUTS[rank]:
        px = x + (col * span_x + 1) // 2
        py = y + (row * span_y + 6) // 12
        _blit_sprite(draw, px, py, lower if row > 6 else glyph, {"1": ink})


def _index_block(rank: str, suit: str) -> Tuple[str, ...]:
    """The corner index as one sprite: rank in the ink, suit a step back."""
    key = (rank, suit)
    block = _INDEX_BLOCKS.get(key)
    if block is None:
        rank_rows = tuple(row.replace("1", "#") for row in _RANK_GLYPHS[rank])
        pip_rows = tuple("0" + row.replace("1", "+") + "0"
                         for row in _PIPS_SMALL[suit])
        block = rank_rows + ("00000",) + pip_rows
        _INDEX_BLOCKS[key] = block
    return block


def _pip_for_field(field_w: int, field_h: int) -> Optional[int]:
    """Largest pip face that lays *any* rank out classically in this field.

    Sized against the worst rank rather than the one being drawn, so every card
    in a hand carries the same pip. Sizing per rank makes a four's pips half
    again bigger than the seven beside it, and a row of cards whose marks
    change size reads as a rendering fault rather than as a hand.

    A ten is the worst case in both axes: three columns with a pixel of black
    between them, and four rows of pairs with a pixel between those.
    """
    for size in (7, 5, 3):
        if 3 * size + 2 <= field_w and 4 * size + 3 <= field_h:
            return size
    return None


def _rotate180(rows: Tuple[str, ...]) -> Tuple[str, ...]:
    out = _ROTATED.get(rows)
    if out is None:
        out = tuple(row[::-1] for row in reversed(rows))
        _ROTATED[rows] = out
    return out


def _sprite_runs(rows: Tuple[str, ...]):
    runs = _SPRITE_RUNS.get(rows)
    if runs is None:
        out = []
        for row_index, row in enumerate(rows):
            start = 0
            for col in range(1, len(row) + 1):
                if col == len(row) or row[col] != row[start]:
                    if row[start] not in _BLANK_CELLS:
                        out.append((row_index, start, col - 1, row[start]))
                    start = col
        runs = tuple(out)
        _SPRITE_RUNS[rows] = runs
    return runs



#: Overshoot constant for :func:`_ease_back`. The textbook value is 1.70158,
#: which peaks about 10% past the target; scaled up a fifth here because the
#: overshoot has to survive being rounded to whole pixels.
_BACK = 1.70158 * 1.2


_CALL_SHAKE_SPAN = 0.07


#: How long the impact flash lasts, in seconds. Two to three frames at 40fps,
#: which is the NES dose: long enough that the eye records a white panel,
#: short enough that it is an impact rather than a fade to white. Seconds
#: rather than a slice of the banner's opening, because a flash measured in
#: frames has to be measured in time -- tying it to a configurable duration
#: made it one frame on a short result beat and a quarter-second wash on a
#: long one.
_FLASH_SECONDS = 0.07


#: Seconds of lag the trailing pixel is drawn at. A matrix has no persistence,
#: so a chip moving twenty pixels a second is a row of stills; the ghost behind
#: it is the same motion blur the dealt cards already borrow.
_FOUNTAIN_LAG = 0.055


#: Seconds for one chip to go up and come back down.
_FOUNTAIN_LIFE = 1.1


#: Free rows above the band below which the fountain is not worth drawing --
#: a chip with four pixels of sky to rise into is a flickering dot, not an arc.
_FOUNTAIN_MIN_ROOM = 10


#: Emitter columns for the sustained fountain, as a fraction of panel width.
_FOUNTAIN_X: Tuple[float, ...] = (0.10, 0.27, 0.41, 0.55, 0.69, 0.83, 0.19, 0.76)


_GLEAM_DELAY = 0.30


_GLEAM_PERIOD = 1.7


#: The gleam that runs across a winning headline: how long one sweep takes and
#: how often it repeats.
_GLEAM_SWEEP = 0.42


#: Fraction of the banner's opening spent rattling the panel, and the fraction
#: of a call-out's beat spent rattling it.
_SHAKE_SPAN = 0.34


#: Launch parameters for the celebration burst: ``(vx, vy, delay, size)``.
#:
#: A hand-written constant table rather than a seeded RNG, and this is the
#: whole trick to keeping particles honest here. Every frame the plugin draws
#: is a pure function of elapsed time -- a dropped frame must not be able to
#: move the picture -- so nothing may be *simulated*. A spark's position is
#: therefore evaluated from its launch parameters and the clock alone:
#: ``p(t) = p0 + v*t + g*t^2/2``, closed form, no integration, no stored
#: velocity. Rendering the same instant twice gives the same pixels, and
#: skipping ten frames skips the sparks forward rather than leaving them
#: behind.
#:
#: Speeds are in panel widths (x) and heights (y) per second, so the burst
#: covers the same *shape* on a 64x32 and a 256x128 panel.
_SPARKS: Tuple[Tuple[float, float, float, int], ...] = (
    (-0.55, -1.95, 0.00, 2),
    (0.55, -1.95, 0.00, 2),
    (-1.15, -1.45, 0.03, 2),
    (1.15, -1.45, 0.03, 2),
    (-1.70, -0.70, 0.06, 1),
    (1.70, -0.70, 0.06, 1),
    (-1.95, 0.25, 0.09, 1),
    (1.95, 0.25, 0.09, 1),
    (-0.85, -2.35, 0.12, 1),
    (0.85, -2.35, 0.12, 1),
    (-1.45, 0.95, 0.15, 1),
    (1.45, 0.95, 0.15, 1),
)


#: Downward acceleration, panel heights per second squared.
_SPARK_GRAVITY = 4.2


#: How long a spark stays lit. Past this it is simply not drawn -- there is no
#: particle to retire, only an expression that stops being evaluated.
_SPARK_LIFE = 0.80


#: A neon tube with a bad connection. Sixteen slots read at 11Hz, gated so the
#: sign only stutters for a quarter second every couple of seconds -- a
#: permanent strobe on an emissive panel is unwatchable, and the point is a
#: sign that is *failing*, not one that is flashing at you.
_STUTTER = (1, 1, 1, 0, 1, 0, 0, 1, 1, 1, 1, 0, 1, 1, 0, 1)


_STUTTER_PERIOD = 1.9


_STUTTER_WINDOW = 0.30


#: Seconds after the result beat starts before the score line appears, and how
#: long its count-up runs. Real seconds rather than a slice of the band's
#: opening: the opening is 0.7s at stock settings and the score line is the
#: last thing in it, so a tally driven off ``banner_progress`` had six frames
#: to run in and read as a glitch rather than as a score counting up.
#: How long the flourish holds the second line before the score takes it back.
#: Long enough to read a seven-character word twice, short enough that the
#: score is still up for most of the banner.
_FLOURISH_SECONDS = 1.9

_SUB_DELAY = 0.45


#: Fraction of a call's beat spent snapping the chip open. Two frames at the
#: stock 1.2s action beat; a slower shutter reads as the tag sliding.
_TAG_SNAP = 0.045


#: How long the final total stays white-hot once the tally lands.
_TALLY_POP = 0.16


_TALLY_SPAN = 0.55


#: Blink period for a natural and for an ordinary win. Both twinkle, because a
#: 32-row panel has no room for the fountain and a winning sign that then holds
#: still for four seconds is a still image -- but the natural blinks half again
#: as fast, so the hierarchy between the two results survives.
_TWINKLE_PERIOD = 1.15


_TWINKLE_PERIOD_WIN = 1.8


#: Twinkle stations along the band, as a fraction of the free margin. Fixed,
#: for the same reason the spark table is: a star has to be in the same place
#: at the same instant no matter which frames the panel actually drew.
_TWINKLE_PHASES: Tuple[float, ...] = (0.0, 0.62, 0.27, 0.81, 0.45, 0.13)


#: Word masks, keyed by ``(text, scale)``. The banner headline does not change
#: for the four seconds it is up, so building the glyph mask once and pasting
#: through it turns ~120 ``rectangle`` calls per frame into a dict lookup --
#: which is what buys the keyline and the shadow their pixels back.
_TYPE_MASKS: Dict[Tuple[str, int], Tuple[Image.Image, Image.Image]] = {}


#: Two hands' worth of headline, subtext and call tags at a couple of sizes.
#: Cleared wholesale rather than evicted by age: the working set is tiny and a
#: stale entry is only a few kilobytes, but an unbounded dict on a panel that
#: runs for weeks is a leak.
_TYPE_MASK_CAP = 64


#: Gap between the two waves a wide panel fires.
_WAVE_DELAY = 0.22


_WHITE_FRAMES: Dict[Tuple[Tuple[int, int], RGB], Image.Image] = {}


def _bevel_plate(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                 tone: RGB, alpha: float) -> None:
    """A lit chip with a keyline, a hard shadow and a three-step ramp.

    The dithered row is an ordered 2x1 pattern rather than a fourth solid tone:
    a chip is eight to sixteen rows tall, so a genuine fourth step would take a
    whole row of the ramp for a difference of a few levels. Alternating pixels
    of the shade over the body reads as the step between them and costs no
    rows at all.
    """
    if w < 3 or h < 1:
        return
    body = scale_color(tone, 0.92 * alpha)
    # Shadow two pixels out, so what survives past the keyline is a one-pixel
    # fringe down and to the right rather than nothing at all.
    draw.rectangle([x + 1, y + 1, x + w, y + h], fill=(0, 0, 0))
    draw.rectangle([x - 1, y - 1, x + w, y + h - 1], fill=(0, 0, 0))
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=body)
    draw.rectangle([x, y, x + w - 1, y],
                   fill=scale_color(mix_color(tone, WHITE, 0.55), alpha))
    if h >= 5:
        draw.rectangle([x, y + h - 1, x + w - 1, y + h - 1],
                       fill=scale_color(tone, 0.48 * alpha))
        shade = scale_color(tone, 0.68 * alpha)
        for px in range(x + 1, x + w - 1, 2):
            draw.point((px, y + h - 2), fill=shade)
    _round_corners(draw, x, y, w, h)


def _corner_brackets(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                     colour: RGB) -> None:
    """Four brighter corner ticks on a bordered chip."""
    if w < 6 or h < 5:
        return
    tick = max(1, min(3, w // 7))
    for cx, sx in ((x, 1), (x + w - 1, -1)):
        for cy, sy in ((y, 1), (y + h - 1, -1)):
            draw.rectangle(_ordered_box(cx, cy, cx + sx * (tick - 1), cy), fill=colour)
            draw.rectangle(_ordered_box(cx, cy, cx, cy + sy * (tick - 1)), fill=colour)


def _draw_fountain(draw: ImageDraw.ImageDraw, width: int, top: int,
                   room: int, since: float, tone: RGB) -> None:
    """Chips thrown up off the top of a winning sign, on a loop.

    The opening burst is over in under a second; on a 32-row panel that is the
    whole celebration, because there is nowhere else for a particle to be. A
    128-row panel has forty empty rows above the band, and a sign that lights
    up and then holds perfectly still for four seconds in all that space is a
    still image with a chase around it.

    Phase, not simulation: emitter ``i`` is at ``((since / life) + offset_i)``
    modulo one, and its height is the parabola ``4p(1-p)``. Nothing is carried
    from the previous frame, so the fountain cannot drift out of step with the
    clock however many frames the Pi drops -- and the trailing ghost is that
    same expression evaluated a few hundredths of a second earlier, rather than
    a remembered previous position.
    """
    if room < _FOUNTAIN_MIN_ROOM:
        return
    unit = max(1, min(2, room // 14))
    rise = room - 2
    trail = scale_color(tone, 0.42)
    bright = mix_color(tone, WHITE, 0.55)
    lag = _FOUNTAIN_LAG / _FOUNTAIN_LIFE

    def height_at(phase: float) -> int:
        phase %= 1.0
        return int(round(4.0 * phase * (1.0 - phase) * rise))

    # Two chips per column, half a cycle apart: eight emitters over 256 columns
    # is a star field, not a shower, and doubling the read of the table costs
    # nothing because there is no table to double.
    for index, column in enumerate(_FOUNTAIN_X):
        for half in (0.0, 0.5):
            phase = ((since / _FOUNTAIN_LIFE) + index * 0.137 + half) % 1.0
            up = height_at(phase)
            if up <= 0:
                continue
            drift = (1 if index % 2 else -1) * (phase - 0.5) * width * 0.055
            x = max(2, min(width - 3, int(column * width + drift)))
            ghost = height_at(phase - lag)
            if ghost != up and 0 < top - ghost < top:
                draw.rectangle([x, top - ghost, x + unit - 1, top - ghost],
                               fill=trail)
            y = top - up
            if y < 0:
                continue
            # Bright on the way up, plain tone falling: a chip catching the
            # light once and then dropping is two tones, and two tones is the
            # difference between a thrown object and a blinking LED.
            draw.rectangle([x, y, x + unit - 1, y + unit - 1],
                           fill=bright if phase < 0.5 else tone)


def _draw_knockout(image: Image.Image, x: int, y: int, text: str, scale: int,
                   tone: RGB, gleam: Optional[float] = None,
                   flat: float = 0.0) -> None:
    """Arcade knockout type: keyline, hard shadow, and a lit-to-shaded ramp.

    Flat coloured glyphs were the single biggest reason the banner read as
    "big numbers on screen": on a tinted band a word in the band's own hue is
    the same picture as the band, only brighter. Three things fix that and all
    of them are era-correct:

    * a **1px black keyline**, so the word is a separate object from whatever
      is behind it -- which now includes a textured felt, not just black;
    * a **1px hard shadow** down-right outside the keyline, which is what gives
      arcade type its stamped-metal weight;
    * a **vertical ramp** -- highlight on the top row of the glyph, tone
      through the body, shade on the bottom row. The face is a bitmap, so every
      glyph shares its five rows and "the top row of the letter" is just the
      top ``scale`` rows of the word box. Three pastes, no per-glyph work.

    ``gleam`` is a specular sweep position in ``[0, 1]`` across the word, or
    ``None`` for none. ``flat`` mixes the whole word toward white, for the
    frames right after it lands.
    """
    mask, dilated = _type_masks(text, scale)
    ox, oy = x - 1, y - 1
    # Shadow first, then keyline over it: the shadow is the dilated silhouette
    # offset by one, so what survives is a one-pixel fringe down and right of
    # the keyline rather than a second, blurry word.
    image.paste((0, 0, 0), (ox + 1, oy + 1), dilated)
    image.paste((0, 0, 0), (ox, oy), dilated)

    body = mix_color(tone, WHITE, flat) if flat > 0.01 else tone
    top = mix_color(body, WHITE, 0.45)
    bottom = scale_color(body, 0.62)
    height = text_height(scale)
    # Rows are in word space; the mask is offset by its one-pixel margin.
    for row0, row1, colour in ((0, scale, top),
                               (scale, max(scale, height - scale), body),
                               (max(scale, height - scale), height, bottom)):
        if row1 <= row0:
            continue
        image.paste(colour, (x, y + row0),
                    mask.crop((1, 1 + row0, mask.width - 1, 1 + row1)))

    if gleam is None:
        return
    # A specular sweep, slanted by cutting it into three vertical chunks that
    # step sideways. A vertical bar reads as a scanline artefact; a slant reads
    # as light moving across metal, which is the whole point.
    width = text_width(text, scale)
    band = max(2, scale + 1)
    centre = gleam * (width + band * 4) - band * 2
    hot = mix_color(tone, WHITE, 0.92)
    chunks = 3
    step = max(1, height // chunks)
    for chunk in range(chunks):
        r0 = chunk * step
        r1 = height if chunk == chunks - 1 else min(height, r0 + step)
        if r1 <= r0:
            continue
        left = int(round(centre + (chunk - 1) * band))
        x0 = max(0, left)
        x1 = min(width, left + band)
        if x1 <= x0:
            continue
        image.paste(hot, (x + x0, y + r0),
                    mask.crop((1 + x0, 1 + r0, 1 + x1, 1 + r1)))


def _draw_knockout_centered(image: Image.Image, center_x: int, y: int, text: str,
                            scale: int, tone: RGB, gleam: Optional[float] = None,
                            flat: float = 0.0) -> None:
    _draw_knockout(image, center_x - text_width(text, scale) // 2, y, text,
                   scale, tone, gleam, flat)


def _draw_sparks(draw: ImageDraw.ImageDraw, width: int, height: int,
                 cx: float, cy: float, elapsed: float, tone: RGB,
                 count: int, spread: float = 1.0, waves: int = 1) -> None:
    """The burst that erupts from the middle of the panel when a hand is won.

    Deliberately timed to live in the moment *before* the band has finished
    opening. A 32-row panel has about nine free rows once the band is up, which
    is nowhere for a particle to go -- but while the band is still a few pixels
    tall the whole table is empty and dark, and that is where the explosion
    fits. By the time the word lands the sparks are off the edges.

    ``waves`` fires the same table again, later and slower. A wide panel has
    four times the area to fill and the table is only twelve long; re-reading
    it at an offset is denser confetti for no extra constants and no extra
    state -- the second wave is the same closed-form expression evaluated at
    ``elapsed - delay``.
    """
    if elapsed > _SPARK_LIFE + _WAVE_DELAY * (waves - 1) + 0.2:
        return
    hot = mix_color(tone, WHITE, 0.85)
    unit = _spark_unit(width, height)
    for wave in range(waves):
        wave_t = elapsed - _WAVE_DELAY * wave
        wave_spread = spread * (1.0 if wave == 0 else 0.60)
        for index in range(min(count, len(_SPARKS))):
            vx, vy, delay, size = _SPARKS[index]
            age = wave_t - delay
            if age <= 0.0 or age >= _SPARK_LIFE:
                continue
            x = int(cx + vx * wave_spread * width * age)
            y = int(cy + (vy * wave_spread * age
                          + _SPARK_GRAVITY * age * age * 0.5) * height)
            if x < -2 or y < -2 or x > width + 1 or y > height + 1:
                continue
            life = age / _SPARK_LIFE
            if life < 0.30:
                colour = hot
            elif life < 0.62:
                colour = tone
            else:
                colour = scale_color(tone, 0.55)
            arm = unit if (life < 0.35 and size > 1) else 0
            if arm:
                # A four-armed star while it is hot, collapsing to a dot as it
                # cools. A star that never shrinks reads as a snowflake sitting
                # still; the collapse is what sells the decay.
                draw.rectangle([x - arm, y, x + arm, y], fill=colour)
                draw.rectangle([x, y - arm, x, y + arm], fill=colour)
            elif size > 1 and life < 0.62:
                draw.rectangle([x, y, x + unit - 1, y + unit - 1], fill=colour)
            else:
                draw.rectangle([x, y, x + max(0, unit - 2), y + max(0, unit - 2)],
                               fill=colour)


def _draw_tally(image: Image.Image, center_x: int, y: int, text: str,
                tone: RGB, scale: int, progress: float, pop: float) -> None:
    """The score line under the headline, counted up digit by digit.

    A hand that ends 20-18 arriving as the finished string is a caption. The
    same string spun up from zero in half a second is a *score*, which is the
    grammar every arcade game ends a round with, and it costs one extra
    ``int()`` per frame.

    Both numbers are drawn right-aligned to the position they will finish in,
    so a 9 growing into a 19 does not shove the rest of the line sideways.
    Centring each intermediate value instead made the whole line jitter left
    and right for the length of the count, which at this size is the one thing
    integer-scaled type cannot survive.
    """
    base = scale_color(tone, 0.78)
    full_w = text_width(text, scale)
    x = center_x - full_w // 2
    parts = text.split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        _draw_knockout(image, x, y, text, scale, base)
        return
    eased = _ease_out(max(0.0, min(1.0, progress)))
    lit = mix_color(base, WHITE, 0.8 * pop) if pop > 0.01 else base
    left_w = text_width(parts[0], scale)
    left = str(int(round(int(parts[0]) * eased)))
    right = str(int(round(int(parts[1]) * eased)))
    _draw_knockout(image, x + left_w - text_width(left, scale), y, left,
                   scale, lit)
    _draw_knockout(image, x + left_w + GLYPH_TRACKING * scale, y, "-",
                   scale, scale_color(base, 0.7))
    _draw_knockout(image, x + full_w - text_width(right, scale), y, right,
                   scale, lit)


def _draw_twinkle(draw: ImageDraw.ImageDraw, width: int, top: int, bottom: int,
                  margin: int, elapsed: float, tone: RGB,
                  period: float = _TWINKLE_PERIOD) -> None:
    """Sparkle stars blinking in the band's left and right margins.

    Only where the headline is not: the margin is measured from the word, so a
    band whose type fills it gets no stars rather than stars on top of the
    word. This is the sustained half of a natural's celebration -- the burst is
    over in under a second and a sign that then just sits there is a still.
    """
    if margin < 5 or bottom - top < 5:
        return
    hot = mix_color(tone, WHITE, 0.8)
    inner_top = top + 2
    inner_bottom = bottom - 2
    for index, phase in enumerate(_TWINKLE_PHASES):
        blink = ((elapsed / period) + phase) % 1.0
        if blink > 0.34:
            continue
        # Deterministic station: alternating sides, stepped in from the edge.
        side = index % 2
        step = (index // 2) + 1
        x = (2 + step * (margin - 4) // 3) if side == 0 \
            else (width - 3 - step * (margin - 4) // 3)
        y = inner_top if (index % 4) < 2 else inner_bottom
        if not (0 <= x < width and inner_top <= y <= inner_bottom):
            continue
        arm = 1 if 0.08 < blink < 0.26 else 0
        draw.point((x, y), fill=hot)
        if arm:
            draw.rectangle([x - arm, y, x + arm, y], fill=hot)
            draw.rectangle([x, y - arm, x, y + arm], fill=hot)


def _ease_back(t: float) -> float:
    """Ease-out that goes past its target and springs back.

    Used for the result band's shutter. A pure ease-out arrives and stops,
    which is how a window closes; a band that opens a few pixels too far and
    snaps back is how a sign *drops into place*, and it is the one piece of
    overshoot on this panel that survives integer pixels -- the type cannot
    have it, because a bitmap face has no fractional size to overshoot into.
    """
    t = max(0.0, min(1.0, t))
    u = t - 1.0
    return 1.0 + (_BACK + 1.0) * u ** 3 + _BACK * u ** 2


def _flash(image: Image.Image, since: float, progress: float, tone: RGB,
           banner_tone: str) -> Image.Image:
    """The impact frame: the whole panel blown out toward the tone's white.

    Tinted rather than pure white, so a bust flashes hot red and a natural
    flashes gold -- the eye gets told *which* thing happened in the frame
    before it can read the word. Applied over the finished banner rather than
    under it, because a flash that things are drawn on top of is a background,
    not a flash.
    """
    # Both clocks have to agree that this is an *arrival*. ``since`` is the
    # one that sets the length, but a caller handing the renderer a finished
    # banner with a zero clock -- which is exactly what a test or a preview
    # does when it builds a ViewState by hand -- would otherwise get a
    # white-out over the whole panel instead of a result.
    if since >= _FLASH_SECONDS or progress >= 0.5:
        return image
    peak = {TONE_BLACKJACK: 0.92, TONE_WIN: 0.78,
            TONE_LOSE: 0.72, TONE_PUSH: 0.34}.get(banner_tone, 0.5)
    # Squared, so the second frame is already half gone. A linear fall spent
    # its last frame at a third brightness, which is a wash, not a hit.
    amount = peak * (1.0 - since / _FLASH_SECONDS) ** 2
    if amount < 0.02:
        return image
    return Image.blend(image, _flat_frame(image.size, mix_color(tone, WHITE, 0.72)),
                       amount)


def _flat_frame(size: Tuple[int, int], colour: RGB) -> Image.Image:
    frame = _WHITE_FRAMES.get((size, colour))
    if frame is None:
        if len(_WHITE_FRAMES) > 16:
            _WHITE_FRAMES.clear()
        frame = Image.new("RGB", size, colour)
        _WHITE_FRAMES[(size, colour)] = frame
    return frame


def _frame_shake(state: ViewState, height: int) -> Tuple[int, int]:
    """Whole-panel offset for this instant, or ``(0, 0)``.

    Two events earn a rattle and both are the table hitting you: the result
    band arriving, hardest on a loss, and a hand busting. Everything else --
    including an ordinary HIT tag -- must not move the panel, or the tag stops
    being a caption and becomes an earthquake four times a hand.
    """
    amplitude = 0.0
    if state.banner_text and state.banner_progress > 0.0:
        progress = state.banner_progress
        if state.banner_tone == TONE_LOSE:
            if progress < _SHAKE_SPAN:
                amplitude = _shake_peak(height) * (1.0 - progress / _SHAKE_SPAN) ** 2
        elif state.banner_tone != TONE_PUSH:
            # A win gets one pixel of kick, not a quake: the celebration is the
            # burst, and shaking a sign that is lighting up reads as a fault.
            span = _SHAKE_SPAN * 0.4
            if progress < span:
                amplitude = 1.0 - progress / span
    if state.action_text and state.action_tone == TONE_LOSE:
        progress = max(0.0, state.action_progress)
        if progress < _CALL_SHAKE_SPAN:
            amplitude = max(amplitude,
                            (1.0 - progress / _CALL_SHAKE_SPAN) ** 2)
    return _shake_offset(amplitude, state.clock)


def _ordered_box(x0: int, y0: int, x1: int, y1: int) -> List[int]:
    """``[x0, y0, x1, y1]`` with the corners the way Pillow insists on them."""
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _shake_offset(amplitude: float, clock: float) -> Tuple[int, int]:
    """A whole-pixel rattle, evaluated from the clock rather than accumulated.

    Square waves, not sines: a sine spends most of its time near the middle, so
    at 40fps a sine shake reads as a slow wobble. Two different frequencies on
    the two axes so the panel rattles instead of sliding along a diagonal.
    """
    if amplitude < 0.5:
        return 0, 0
    amp = int(round(amplitude))
    sway = int(round(amplitude * 0.5))
    dx = amp if math.sin(clock * 106.8) >= 0 else -amp
    dy = sway if math.sin(clock * 71.2 + 1.3) >= 0 else -sway
    return dx, dy


def _shake_peak(height: int) -> float:
    """Rattle amplitude for a panel this tall.

    An NES shook a 224-row screen by two to eight pixels. Scaling that down
    gives less than a pixel at 32 rows, which is no shake at all -- so the
    floor is one whole pixel and it grows with the panel instead.
    """
    return float(max(1, min(3, 1 + height // 64)))


def _spark_unit(width: int, height: int) -> int:
    """How many pixels one spark is across on a panel this size.

    A one-pixel spark on a 256x128 panel is dust -- the cards on that table are
    sixty pixels tall, and a celebration made of single pixels beside them
    reads as stuck LEDs rather than as anything thrown. The sprite therefore
    grows with the panel, the same way the cards and the type already do.
    """
    return max(1, min(3, min(width // 96, height // 40) + 1))


def _type_masks(text: str, scale: int) -> Tuple[Image.Image, Image.Image]:
    """``(glyph mask, glyph mask dilated by one pixel)`` for ``text``.

    The mask carries a one-pixel margin so the dilation has somewhere to go;
    without it ``MaxFilter`` clamps at the edge and the keyline is missing on
    the outside of the first and last letters -- exactly the two places a word
    needs it most.
    """
    key = (text, scale)
    cached = _TYPE_MASKS.get(key)
    if cached is not None:
        return cached
    if len(_TYPE_MASKS) >= _TYPE_MASK_CAP:
        _TYPE_MASKS.clear()
    mask = Image.new("L", (text_width(text, scale) + 2, text_height(scale) + 2), 0)
    draw_text(ImageDraw.Draw(mask), 1, 1, text, 255, scale)
    cached = (mask, mask.filter(ImageFilter.MaxFilter(3)))
    _TYPE_MASKS[key] = cached
    return cached


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def scale_color(color: RGB, factor: float) -> RGB:
    """``color`` at ``factor`` brightness, clamped to a valid RGB triple."""
    return (
        max(0, min(255, int(round(color[0] * factor)))),
        max(0, min(255, int(round(color[1] * factor)))),
        max(0, min(255, int(round(color[2] * factor)))),
    )


#: ``Theme.table_style`` values.
#: Deck colour schemes. 'classic' is the two-colour deck every physical deck
#: ships with; 'four' is the card-room four-colour deck, which exists because
#: two same-coloured suits are told apart by shape alone and shape is the
#: slower channel.
DECK_CLASSIC = "classic"
DECK_FOUR = "four"
DECK_COLOR_SCHEMES = (DECK_CLASSIC, DECK_FOUR)


TABLE_FELT = "felt"
TABLE_VOID = "void"
TABLE_STYLES = (TABLE_FELT, TABLE_VOID)


@dataclass
class Theme:
    """Every colour the table draws with."""

    dealer: RGB = (255, 140, 50)
    player: RGB = (60, 200, 255)
    felt: RGB = (0, 110, 62)
    red_ink: RGB = (255, 70, 70)
    black_ink: RGB = (225, 232, 245)
    #: Four-colour deck inks, keyed by suit. A real card room hands these out
    #: for exactly the reason they help here: at a glance, on a dark surface,
    #: a spade and a club are the same mark until you stop and look at the
    #: shape, and colour resolves before shape does.
    #:
    #: Blue for spades and amber for diamonds puts them near the player's cyan
    #: and the dealer's orange, which is survivable only because the accents
    #: are type at the panel's edges and the suits are marks in the middle. It
    #: is checked at 1x on a 128x32, not reasoned about.
    four_ink: Dict[str, RGB] = field(default_factory=lambda: {
        "H": (255, 64, 64),
        # Gold rather than orange. At (255, 156, 32) a diamond was 24 units
        # from the dealer's own accent -- the same colour, for practical
        # purposes, with only position telling them apart. Gold keeps it warm
        # and clears the accent by a hue step.
        "D": (255, 196, 24),
        "C": (56, 214, 104),
        # Indigo rather than a true blue: the player's accent is cyan
        # (60, 200, 255), and a spade at (120, 170, 255) sat one step from it
        # on the same row of a 512x64 strip. Dropping the green and holding the
        # red moves it to a different hue family instead of a lighter one.
        "S": (130, 140, 255),
    })
    #: The same four for the ivory face, where the ink has to be dark enough to
    #: read *on* the card rather than bright enough to read on black.
    four_ink_solid: Dict[str, RGB] = field(default_factory=lambda: {
        "H": (196, 24, 40),
        "D": (204, 96, 0),
        "C": (0, 124, 56),
        "S": (28, 64, 158),
    })
    card_face: RGB = (10, 13, 22)
    #: Crimson ground, lighter crimson weave, gold frame -- the casino back.
    #: The gold is deliberately short of full. At (226, 170, 60) the back's lit
    #: edge measured 172 in luminance against 69-129 for a face card's border,
    #: so the one card nobody can read was the brightest object on the table.
    #: Dimmed it lands at 127, just under a diamond's border -- visible, and
    #: behind the hand rather than in front of it.
    card_back: RGB = (48, 8, 18)
    card_back_weave: RGB = (96, 26, 40)
    card_back_ink: RGB = (176, 130, 42)
    solid_face: RGB = (236, 238, 246)
    solid_red_ink: RGB = (196, 24, 40)
    solid_black_ink: RGB = (22, 24, 34)
    win: RGB = (60, 230, 120)
    lose: RGB = (255, 68, 68)
    push: RGB = (255, 198, 64)
    blackjack: RGB = (255, 208, 32)
    #: 'outline' keeps cards dark with a lit edge; 'solid' paints ivory faces.
    card_style: str = "outline"
    #: 'felt' lays a dithered field and a rail under the hand; 'void' is the
    #: bare black table.
    table_style: str = TABLE_FELT
    #: 'classic' is the two-colour deck -- red hearts and diamonds, light
    #: spades and clubs. 'four' gives every suit its own colour.
    deck_colors: str = DECK_FOUR

    def suit_ink(self, suit: str, solid: bool = False) -> RGB:
        """The ink a suit is drawn in, for the face style in use."""
        if self.deck_colors == DECK_FOUR:
            table = self.four_ink_solid if solid else self.four_ink
            ink = table.get(suit)
            if ink is not None:
                return ink
        red = suit in RED_SUITS
        if solid:
            return self.solid_red_ink if red else self.solid_black_ink
        return self.red_ink if red else self.black_ink

    def tone_color(self, tone: str) -> RGB:
        return {
            TONE_WIN: self.win,
            TONE_LOSE: self.lose,
            TONE_PUSH: self.push,
            TONE_BLACKJACK: self.blackjack,
        }.get(tone, self.player)

    def seat_color(self, seat: str) -> RGB:
        return self.dealer if seat == "dealer" else self.player


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

#: The smallest card the layout will plan around: two border pixels plus the
#: 5x7 rank face. This is a *layout* floor -- it decides whether a seat can
#: afford a label or a totals column -- not the point at which the art gives
#: up. What a card actually draws at a given size is _rank_face's business,
#: and it keeps a rank on smaller cards than these by falling back to the
#: compact face.
MIN_RANK_CARD_W = 7
MIN_RANK_CARD_H = 9
#: Absolute floor; anything smaller is not a card, it is a dot.
MIN_CARD_W = 3
MIN_CARD_H = 4
#: Standard playing-card proportions (2.5 x 3.5 inches).
CARD_ASPECT = 1.42


@dataclass
class SeatLayout:
    """Where one seat's cards, label and total go."""

    seat: str
    x: int
    y: int
    width: int
    height: int
    card_w: int
    card_h: int
    step: int
    cards_x: int
    cards_y: int
    #: Width the full hand occupies once every card has arrived.
    span: int = 0
    label: str = ""
    label_x: int = 0
    label_y: int = 0
    label_scale: int = 1
    total_x: int = 0
    total_y: int = 0
    total_scale: int = 1
    show_total: bool = True
    accent: Optional[Tuple[int, int, int, int]] = None
    #: Boxes behind the name and the total, or None where the seat cannot
    #: spare the two pixels of padding one needs. Static for the whole hand,
    #: so the renderer bakes them into the table image once.

    def card_origin(self, index: int) -> Tuple[int, int]:
        return self.cards_x + index * self.step, self.cards_y


@dataclass
class Layout:
    width: int
    height: int
    mode: str
    seats: Dict[str, SeatLayout]
    divider: Optional[Tuple[int, int, int, int]] = None
    #: How many rows (or columns) the gutter can spare the rule. Two is a
    #: bevelled rail -- a lit edge over a dark one -- which is what makes the
    #: line read as the table's own edge rather than as a drawn-on rule.
    divider_span: int = 1
    #: Ceiling on the result banner's type size; big panels earn a bigger one.
    banner_scale_cap: int = 3


def _fan(count: int, card_w: int, available: int) -> Tuple[int, int]:
    """``(step, span)`` for ``count`` cards of ``card_w`` in ``available`` px.

    Cards sit shoulder to shoulder when they fit and fan into an overlap when
    they do not, the way a dealer squeezes a seven-card hand onto the felt.

    The overlap has no lower bound on the step. An earlier version floored it
    at a third of a card "for legibility", which quietly broke the one thing
    this has to guarantee: eight cards on a 32px panel then spanned 24px of a
    20px row and ran into the totals column. The answer to an unreadable fan is
    a smaller card, not a wider one that does not fit.
    """
    if count <= 1:
        return card_w, min(card_w, available)
    gap = max(1, card_w // 4)
    step = card_w + gap
    if count * step - gap <= available:
        return step, count * step - gap
    # A step of zero is allowed. On a panel narrow enough that even one pixel
    # of offset per card overflows (eight cards in six pixels), a squared-up
    # stack is the only honest answer -- and it is still on the panel, which a
    # floored step is not.
    step = max(0, (available - card_w) // (count - 1))
    return step, (count - 1) * step + card_w


def _label_gap(scale: int) -> int:
    """Clearance between a seat's inline name and its first card.

    Grows with the type: at scale 3 a flat two pixels let the R of DEALER and
    the card's lit border read as one shape.

    It stays this tight on purpose. Widening it by a single pixel cost a 256x32
    strip its inline name and dropped its totals a whole size, because the seat
    picks its arrangement on whether going inline still leaves the cards as
    wide -- and three pixels was exactly the margin.
    """
    return 2 + scale


def _preferred_label_scale(height: int) -> int:
    """Type size for a seat's name, taken from the seat box rather than the
    panel -- a 256x32 strip in columns mode is two tall thin seats, and sizing
    its labels off the panel width would set DEALER four times the height of
    the row it names."""
    if height >= 80:
        return 3
    if height >= 40:
        return 2
    return 1


@dataclass
class _Body:
    """Where the cards and the totals column land once the seat's name has
    been placed. Kept separate from :class:`SeatLayout` so the three ways of
    marking a seat -- name beside the hand, name above it, colour bar -- can
    each be costed in card pixels before one is chosen."""

    y: int
    height: int
    card_w: int
    card_h: int
    step: int
    span: int
    cards_x: int
    cards_y: int
    total_x: int
    total_scale: int
    show_total: bool


def _plan_body(x: int, y: int, width: int, height: int, count: int,
               align_count: int, want_total: bool, has_left_marker: bool) -> _Body:
    """Size and place one seat's cards and total inside the room left for them.

    ``align_count`` is the longer of the two hands at the table. Both seats
    position themselves against it, so a two-card dealer hand and a five-card
    player hand start at the same x instead of each being centred on its own
    width -- which on a 256x128 put the two rows 24px out of register and made
    a table that is otherwise two identical rows look unsettled.
    """
    total_scale = 1
    if height >= 24:
        total_scale = 2
    if height >= 44:
        total_scale = 3
    while total_scale > 1 and numeral_height(total_scale) > height:
        total_scale -= 1
    total_w = numeral_width("00", total_scale) + 3
    show_total = (want_total and height >= numeral_height(total_scale)
                  and width - total_w >= MIN_RANK_CARD_W * 2)
    cards_w = width - total_w if show_total else width

    gap = 2
    w_from_height = max(MIN_CARD_W, int(round(height / CARD_ASPECT)))
    # Cap the width so a four-card hand -- the common case -- sits side by side
    # without overlapping. Height alone would size a 256x128 card at 43px wide
    # and then fan five of them into a smear.
    w_from_width = max(MIN_CARD_W, (cards_w - 3 * gap) // 4)
    card_w = max(MIN_CARD_W, min(w_from_height, w_from_width))
    card_h = max(MIN_CARD_H, min(height, int(round(card_w * CARD_ASPECT))))
    card_w = max(MIN_CARD_W, min(card_w, cards_w))
    step, span = _fan(count, card_w, cards_w)
    # max() of the two spans, not of the two counts: _fan gives seven cards a
    # wider step than eight, so the longer hand is not always the wider one and
    # sizing the row off the count alone let a seven-card dealer hand overrun
    # the totals column an eight-card one would have cleared.
    align_span = max(span, _fan(align_count, card_w, cards_w)[1])

    total_x = x + width - total_w + 2
    if has_left_marker and show_total:
        # A third of the slack toward the name, not half. The seat's name at
        # the left and its total at the right are the row's bookends; centring
        # the hand between them leaves four evenly spaced islands and nothing
        # that reads as a line. Pushing it toward its own name makes the row
        # scan left to right -- name, hand, total -- and collects the rest of
        # the slack into one strip, which is the strip the player's call has to
        # fit in: at half, DOUBLE no longer fit beside the hand on a 128x32 and
        # fell back on top of the table.
        cards_x = x + max(0, cards_w - align_span) // 3
    else:
        # Nothing on the left, so the hand is the only object in the row and it
        # centres on the seat. Centring it in the leftover width instead pushes
        # every hand half a totals column off-centre with nothing to balance
        # it, which reads as a layout bug rather than as breathing room.
        cards_x = x + max(0, width - align_span) // 2
    if show_total:
        # Clear the totals column by a gap that scales with the card. A flat
        # two pixels was invisible once the totals moved to the wider 5x7 face
        # and the column grew into the space -- the last card and the total
        # ended up reading as one object.
        clearance = max(4, card_w // 3)
        cards_x = min(cards_x, max(x, total_x - clearance - align_span))
    cards_y = y + max(0, (height - card_h) // 2)
    return _Body(y=y, height=height, card_w=card_w, card_h=card_h, step=step,
                 span=span, cards_x=cards_x, cards_y=cards_y, total_x=total_x,
                 total_scale=total_scale, show_total=show_total)


def _seat_layout(seat: str, label: str, reserve: str, x: int, y: int,
                 width: int, height: int, count: int, align_count: int,
                 want_label: bool, want_total: bool) -> SeatLayout:
    """Lay one seat out inside the box ``(x, y, width, height)``.

    Card slots are positioned from the *final* card count, so a card that has
    not arrived yet already owns its space and nothing slides sideways when it
    does. Positions being fixed for the whole hand is what keeps a five-card
    draw from looking like a nervous tic.

    The seat is marked in one of three ways, and which one is chosen is settled
    in card pixels rather than by rule. The arrangement this wants is the name
    beside the hand: name, cards, total on one line running the full width of
    the seat, which is the only version where the empty table between them
    looks placed instead of left over. It is taken whenever the columns it
    spends come out of that emptiness; where they would come out of the cards
    instead the seat falls back to a name above the hand, and below that to a
    two-pixel colour bar.

    Every measurement is taken against ``reserve``, the longest name at the
    table, never against this seat's own. YOU is twelve pixels narrower than
    DEALER, so measuring each seat for itself gave the player a wider body and
    therefore wider cards than the dealer -- on a 96x48 the two rows came out
    at 14px and 11px cards, which reads as a rendering fault rather than as a
    layout.
    """
    pref = _preferred_label_scale(height)

    accent = None
    header_scale = 0
    if want_label and height >= text_height(pref) + MIN_RANK_CARD_H + 2 \
            and width >= text_width(reserve, pref):
        header_scale = pref
        label_h = text_height(pref) + 2
        body = _plan_body(x, y + label_h, width, height - label_h, count,
                          align_count, want_total, False)
    elif width >= 24 and height >= 6:
        # No room for a word above the cards either, so the seat gets a colour
        # instead: a two-pixel bar the eye reads as "this row is yours" without
        # spending a row of type on saying so.
        accent = (x, y + 1, x + 1, y + height - 2)
        body = _plan_body(x + 4, y, width - 4, height, count, align_count,
                          want_total, True)
    else:
        body = _plan_body(x, y, width, height, count, align_count,
                          want_total, False)

    inline_scale = 0
    if want_label:
        for scale in range(pref, 0, -1):
            if text_height(scale) > height:
                continue
            reserved = text_width(reserve, scale) + _label_gap(scale)
            if width - reserved < MIN_RANK_CARD_W * 2:
                continue
            candidate = _plan_body(x + reserved, y, width - reserved, height,
                                   count, align_count, want_total, True)
            # Only worth it if the hand is no smaller and the total survives:
            # on a 64x32 the word costs half the card width, and a legible hand
            # beats a legible caption every time.
            if candidate.card_w >= body.card_w \
                    and candidate.show_total >= body.show_total:
                body, inline_scale, accent, header_scale = candidate, scale, None, 0
                break

    if inline_scale:
        label_scale = inline_scale
        # A pixel in from the seat's own edge. On a panel whose margin is
        # already one pixel, setting the name flush would put its leftmost
        # column on the display's own column zero, where the result band is
        # supposed to be the only thing that ever lights.
        label_x = x + 1
        # Centred on the cards rather than on the seat box: the word is a
        # caption on the hand, and on a tall box the two drift apart otherwise.
        label_y = body.cards_y + max(0, (body.card_h - text_height(label_scale)) // 2)
    elif header_scale:
        label_scale, label_x, label_y = header_scale, x + 1, y + 1
    else:
        # No room for the word. Blank it rather than leaving it set: the
        # renderer draws whatever label the seat carries, so a label that was
        # never given a position was stamped at (0, 0) -- both seats' words on
        # top of each other and on top of the table.
        label, label_scale, label_x, label_y = "", 1, 0, 0

    # The total sits on the cards' centre line, not the box's, so name, hand
    # and number read as one line even where the cards do not fill the box.
    total_h = numeral_height(body.total_scale)
    total_y = body.cards_y + (body.card_h - total_h) // 2
    total_y = max(body.y, min(total_y, body.y + body.height - total_h))

    return SeatLayout(
        seat=seat, x=x, y=y, width=width, height=height,
        card_w=body.card_w, card_h=body.card_h, step=body.step,
        cards_x=body.cards_x, cards_y=body.cards_y, span=body.span,
        label=label, label_x=label_x, label_y=label_y, label_scale=label_scale,
        total_x=body.total_x, total_y=total_y, total_scale=body.total_scale,
        show_total=body.show_total, accent=accent,
    )


def compute_layout(width: int, height: int, dealer_count: int, player_count: int,
                   show_labels: bool = True, show_totals: bool = True) -> Layout:
    """Pick a table layout for this panel.

    Two arrangements, chosen by shape rather than by a size whitelist -- an RGB
    matrix can be any rectangle:

    * **stacked** -- dealer above, player below. The default, and what reads as
      a blackjack table.
    * **columns** -- dealer left, player right, for strips so wide that stacking
      would leave two rows of postage stamps in a field of black (a 256x32
      strip gets 24px-tall cards this way instead of 14px ones).
    """
    dealer_count = max(2, int(dealer_count))
    player_count = max(2, int(player_count))

    margin_x = 2 if width >= 96 else 1
    margin_y = 2 if height >= 48 else 1
    inner_x = margin_x
    inner_y = margin_y
    inner_w = max(1, width - 2 * margin_x)
    inner_h = max(1, height - 2 * margin_y)

    if width >= 5 * height:
        mode = "columns"
        # Wider than the stacked gutter on purpose. Stacked seats are told
        # apart by being two rows; side-by-side ones have only this gap and the
        # rule in it to say "two seats", and at three pixels on a 256px strip
        # the four hands read as one eight-card fan.
        gutter = max(4, width // 28)
        col_w = (inner_w - gutter) // 2
        # Odd leftovers go to the gutter, never to one seat: two seats of
        # different sizes give the dealer bigger cards than the player, which
        # reads as a rendering bug even though it is only a rounding remainder.
        gutter = inner_w - 2 * col_w
        dealer_box = (inner_x, inner_y, col_w, inner_h)
        player_box = (inner_x + col_w + gutter, inner_y, col_w, inner_h)
        # The rule is the lit face of the rail and sits at its left; the dark
        # side goes to its right. Centring the *rail* rather than the lit line
        # keeps the two seats evenly spaced either side of it.
        divider_span = 2 if gutter >= 2 else 1
        divider_x = inner_x + col_w + (gutter - divider_span) // 2
        divider = (divider_x, inner_y, divider_x, inner_y + inner_h - 1)
    else:
        mode = "stacked"
        gutter = 2 if height >= 48 else 1
        row_h = (inner_h - gutter) // 2
        gutter = inner_h - 2 * row_h
        dealer_box = (inner_x, inner_y, inner_w, row_h)
        player_box = (inner_x, inner_y + row_h + gutter, inner_w, row_h)
        divider_span = 2 if gutter >= 2 else 1
        divider_y = inner_y + row_h + (gutter - divider_span) // 2
        divider = (inner_x, divider_y, inner_x + inner_w - 1, divider_y)

    banner_cap = 4 if height >= 96 else 3
    # Both seats are measured for the longest name and the longest hand, so
    # the two rows come out congruent: same card size, same left edge, one
    # name column down the side of the table.
    reserve = max(("DEALER", "YOU"), key=text_width)
    align_count = max(dealer_count, player_count)
    seats = {
        "dealer": _seat_layout("dealer", "DEALER", reserve, *dealer_box,
                               dealer_count, align_count, show_labels, show_totals),
        "player": _seat_layout("player", "YOU", reserve, *player_box,
                               player_count, align_count, show_labels, show_totals),
    }
    return Layout(width=width, height=height, mode=mode, seats=seats,
                  divider=divider, divider_span=divider_span,
                  banner_scale_cap=banner_cap)


# ---------------------------------------------------------------------------
# View state
# ---------------------------------------------------------------------------


@dataclass
class ViewState:
    """Everything a frame needs, with no reference to time.

    The plugin turns ``(script, elapsed)`` into one of these; the renderer turns
    one of these into an image. Neither half knows about the other's problem.
    """

    dealer_cards: List[Card] = field(default_factory=list)
    player_cards: List[Card] = field(default_factory=list)
    dealer_final: int = 2
    player_final: int = 2
    #: Dealer card index 1 is face down until the reveal.
    hole_down: bool = True
    #: Reveal flip progress: 0.0 still face down, 1.0 fully turned over.
    hole_flip: float = 0.0
    dealer_total: Optional[int] = None
    player_total: Optional[int] = None
    #: ``(seat, index, progress)`` for the card currently being dealt.
    dealing: Optional[Tuple[str, int, float]] = None
    #: Fades from 1 to 0 over the half-second after the hole card lands face
    #: up, so the reveal has a moment of its own instead of ending the instant
    #: the squash does.
    reveal_glow: float = 0.0
    action_text: str = ""
    action_progress: float = 0.0
    #: Which seat the tag belongs beside. The player's call is the common case,
    #: but a dealer bust is announced at the dealer's own hand.
    action_seat: str = "player"
    #: Empty for an ordinary HIT/STAND/DOUBLE call. Set to an outcome tone for
    #: a call-out -- BUST, 21 -- which is drawn knocked out of a solid chip so
    #: the two never read as the same kind of event.
    action_tone: str = ""
    banner_text: str = ""
    banner_subtext: str = ""
    #: A short label for a rare hand, shown in place of the score for the
    #: first beat of the banner.
    banner_flourish: str = ""
    banner_tone: str = ""
    banner_progress: float = 0.0
    #: Seconds since the result beat began. ``banner_progress`` is a *fraction*
    #: of an opening whose length the user configures, which is the right clock
    #: for the band and the wrong one for anything that has to last a fixed
    #: time: a score tally driven off it finishes in six frames, and a spark
    #: needs real seconds to fall. Zero whenever no banner is up.
    banner_elapsed: float = 0.0
    #: Free-running seconds, used for the winner pulse and the impact rattle.
    clock: float = 0.0


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _round_corners(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                   fill: RGB = (0, 0, 0)) -> None:
    """Knock the four corner pixels back to ``fill``.

    One pixel is the whole radius available at these sizes, and it is enough:
    on a matrix the eye reads the missing corner as a curve. ``fill`` is black
    for the card's own outline and the card colour for a frame drawn inside it
    -- rounding an inner frame against black would punch four holes through the
    card instead of softening the frame.
    """
    if w < 5 or h < 5:
        return
    for px, py in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
        draw.point((px, py), fill=fill)


def draw_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
              card: Optional[Card], face_up: bool, theme: Theme,
              squash: float = 1.0) -> None:
    """Draw one card, optionally mid-flip.

    ``squash`` scales the drawn width about the card's centre: 1.0 is flat on
    the felt, 0.0 is edge-on. A flip is two draws -- the back shrinking to
    nothing and the face growing back out -- which is the cheapest convincing
    3D effect there is on a 2D framebuffer.
    """
    squash = max(0.0, min(1.0, squash))
    drawn_w = max(1, int(round(w * squash)))
    left = x + (w - drawn_w) // 2
    right = left + drawn_w - 1
    bottom = y + h - 1

    if drawn_w <= 2:
        # Edge-on: a lit sliver, so the flip never blinks out entirely.
        draw.rectangle([left, y, right, bottom], fill=theme.card_back_ink)
        return

    if not face_up or card is None:
        _draw_card_back(draw, left, y, drawn_w, h, theme)
        return

    solid = theme.card_style == "solid"
    face = theme.solid_face if solid else theme.card_face
    ink = theme.suit_ink(card.suit, solid)
    if solid:
        edge = scale_color(face, 0.62), scale_color(face, 0.82), scale_color(face, 0.40)
    else:
        edge = scale_color(ink, 0.45), scale_color(ink, 0.66), scale_color(ink, 0.26)

    draw.rectangle([left, y, right, bottom], fill=face)
    _draw_edge(draw, left, y, drawn_w, h, *edge)

    # The rank and pip are only drawn on a card that is close to flat. A glyph
    # squeezed into a two-pixel-wide card is noise, and the flip is over in a
    # third of a second.
    #
    # The plan is measured against the *drawn* width, so a card still turning
    # steps down the ladder rather than overflowing: at 82% of its width a 40px
    # card has given up its corner index but kept its pips, which for the two
    # frames it lasts reads as the card catching the light.
    plan = _card_plan(drawn_w - 2, h - 2) if squash >= 0.82 else None
    if plan is not None and _draw_card_art(draw, left + 1, y + 1, drawn_w - 2,
                                           h - 2, card, ink, face, plan):
        return

    glyph = _rank_glyph(card.rank, drawn_w - 2, h - 2)
    if squash < 0.82 or glyph is None:
        if drawn_w >= 3 and h >= 4 and squash >= 0.82:
            # Too small for type: a lit core says "there is a card here", and
            # the suit colour still carries red-versus-black.
            draw.rectangle([left + 1, y + 1, right - 1, bottom - 1], fill=ink)
        return

    glyph_w = len(glyph[0])
    inner_w = drawn_w - 2
    inner_h = h - 2

    rank_scale, pip = _rank_and_pip(glyph_w, inner_w, inner_h, card.suit)
    block_h = NUMERAL_HEIGHT * rank_scale
    gap = _pip_gap(rank_scale)

    total_h = block_h + (pip[2] + gap if pip else 0)
    top = y + 1 + max(0, (inner_h - total_h) // 2)
    rank_x = left + 1 + max(0, (inner_w - glyph_w * rank_scale) // 2)
    _blit_glyph(draw, rank_x, top, glyph, ink, rank_scale)
    if pip and pip[0]:
        pip_glyph, pip_scale, _ = pip
        pip_w = len(pip_glyph[0]) * pip_scale
        pip_x = left + 1 + max(0, (inner_w - pip_w) // 2)
        _blit_glyph(draw, pip_x, top + block_h + gap, pip_glyph,
                    _pip_ink(ink, face), pip_scale)


def _rank_glyph(rank: str, inner_w: int, inner_h: int):
    """The rank mark for a card with this much room inside its border, or None.

    None means the card is smaller than the 5x7 face needs (under 7x9), and
    the caller lights the face instead. There is deliberately no compact
    fallback: a three-by-five rank puts 8 and 9 one pixel apart, which is the
    defect this face exists to fix rather than something to keep a copy of.
    """
    glyph = _RANK_GLYPHS.get(rank)
    if glyph is None or inner_w < len(glyph[0]) or inner_h < NUMERAL_HEIGHT:
        return None
    return glyph


def _draw_card_back(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                    theme: Theme) -> None:
    """A face-down card: deep indigo, an inset frame, and a woven lattice.

    The frame is what makes a back read as a *back* rather than as an empty
    slot. A full-bleed lattice has no silhouette of its own -- at a glance it
    is a rectangle of texture the same size as a card, which is also what an
    unfilled card slot looks like. A margin with a panel ruled inside it is the
    shape every real card back has, and two rectangles buy it.
    """
    right = x + w - 1
    bottom = y + h - 1
    ink = theme.card_back_ink
    draw.rectangle([x, y, right, bottom], fill=theme.card_back)
    _draw_edge(draw, x, y, w, h, scale_color(ink, 0.75),
               scale_color(ink, 0.95), scale_color(ink, 0.52))
    if w < 5 or h < 5:
        return
    x0, y0 = x + 2, y + 2
    x1, y1 = right - 2, bottom - 2
    if x1 < x0 or y1 < y0:
        return
    if w >= 13 and h >= 17:
        # Only where the panel ruled inside it is still wide enough to show
        # pattern. Below that the frame encloses two or three lattice pixels
        # and the back reads as an empty window rather than a woven back.
        draw.rectangle([x0, y0, x1, y1], outline=scale_color(ink, 0.62))
        _round_corners(draw, x0, y0, x1 - x0 + 1, y1 - y0 + 1, theme.card_back)
        x0, y0, x1, y1 = x0 + 2, y0 + 2, x1 - 2, y1 - 2
        if x1 < x0 or y1 < y0:
            return
    # Diagonals as clipped line segments, not a per-pixel sweep: this runs for
    # every face-down card on every frame, and a 38x55 card on a 256x128 panel
    # is ~1900 point() calls against ~30 line() ones. Every lit pixel satisfies
    # (px + py) % 3 == 0, so each anti-diagonal is the constant sum `total` and
    # clipping it to the card interior is two max/min.
    lattice = theme.card_back_weave
    first = x0 + y0
    for total in range(first + (-first) % 3, x1 + y1 + 1, 3):
        start_x = max(x0, total - y1)
        end_x = min(x1, total - y0)
        if start_x > end_x:
            continue
        draw.line([(start_x, total - start_x), (end_x, total - end_x)], fill=lattice)

    # A lozenge in the middle, which is what turns a woven rectangle into a
    # card back rather than a swatch. Only where it can be drawn at a radius of
    # two or more: at one pixel it is a single lit dot in the centre of the
    # card, which reads as a stuck LED rather than as a motif.
    centre_x, centre_y = (x0 + x1) // 2, (y0 + y1) // 2
    radius = min(max(1, (x1 - x0) // 2 - 1), max(1, (y1 - y0) // 3))
    if radius >= 2:
        points = [(centre_x, centre_y - radius), (centre_x + radius, centre_y),
                  (centre_x, centre_y + radius), (centre_x - radius, centre_y)]
        draw.polygon(points, fill=scale_color(theme.card_back, 1.45))
        draw.polygon(points, outline=ink)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

#: 4x4 ordered (Bayer) threshold matrix for the felt.
#:
#: Ordered rather than random: noise at this density on a 32-row panel reads as
#: dead pixels -- the eye finds the clumps and calls them faults -- while a
#: repeating cell reads as weave. Four rows rather than two because a 2x2 cell
#: at any useful density is a hard checker, and a checker at one pixel pitch
#: moires against the card borders and the 3x5 type.
#: The corner index: a 5x7 rank over a blank row over a 3x3 suit mark.
INDEX_W, INDEX_H = 5, 11

#: Court figures, drawn at 11x17 and integer-scaled from there.
#:
#: Eleven columns is not an aesthetic choice, it is the widest base that still
#: lands on the smallest card in the pip tier: a 16x23 card -- what a 128x64
#: panel and the 256x32 strip both deal -- has a 12x19 interior field, and a
#: twelve-wide figure would have fallen back to a letter on exactly the shapes
#: the plugin is most often run at. Seventeen rows is then the card's own
#: proportion, so the figure scales up without a letterbox.
#:
#: The three have to separate by *silhouette*, because at scale 1 the face is
#: five pixels across and there is no detail to read: the king is a spiked
#: crown over a beard that tapers to a point, the queen is three small coronet
#: points over hair that falls square to the shoulders, and the jack is a flat
#: wide cap over a bare neck. Crowded, pointed, flat -- three different
#: outlines, told apart before anything inside them resolves. The faces are
#: what you get for looking closer.
#:
#: ``#`` is the card's ink, ``+`` a step back toward the face. ``.`` is left
#: alone, which shows the card face already painted underneath -- so eyes, and
#: the gaps between a crown's spikes, are holes rather than a fourth colour.
#: Two ink tones and a hole is the whole palette; a third tone at this size
#: reads as a dithering artefact rather than as shading.
_COURT_W, _COURT_H = 11, 17


_BAYER4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
#: Cells lit to the brighter felt tone, out of sixteen. Five is the lowest
#: density that still reads as a surface rather than as stray pixels, and the
#: highest that stays under the card: a dark card face is (10, 13, 22) and the
#: lit felt tone is about (0, 23, 13), so the card is still the brighter shape
#: everywhere it sits. Raising this to eight -- a plain checker -- made a
#: 64x32 table read as static with cards on it.
#: subtract() clamps at zero, so "the falloff beat the threshold here" is
#: exactly "the result is non-zero".
def _LIT(value: int) -> int:
    return 255 if value else 0


_BAYER_FIELDS: Dict[Tuple[int, int], Image.Image] = {}
_FELT_IMAGES: Dict[Tuple, Image.Image] = {}

#: Finished tables, keyed by everything that can change one. The plugin only
#: rebuilds its layout when the panel or the card counts change, so this is a
#: hit on all but a handful of frames a hand -- which is the whole reason a
#: full-panel dither is affordable at 40fps.
_TABLES: Dict[Tuple, Image.Image] = {}
_TABLE_CACHE_MAX = 8



def _bayer_field(width: int, height: int) -> Image.Image:
    """An ``L`` image of the 4x4 Bayer thresholds, tiled to fill.

    Built as one 4-row band and then stacked, so it costs ``w/4 + h/4`` pastes
    rather than one per cell: a 256x128 panel is 96 instead of 2048.
    """
    key = (width, height)
    cached = _BAYER_FIELDS.get(key)
    if cached is not None:
        return cached
    tile = Image.new("L", (4, 4))
    tile.putdata([int((value + 0.5) * 255 / 16)
                  for row in _BAYER4 for value in row])
    band = Image.new("L", (max(1, width), 4))
    for x in range(0, width, 4):
        band.paste(tile, (x, 0))
    field = Image.new("L", (max(1, width), max(1, height)))
    for y in range(0, height, 4):
        field.paste(band, (0, y))
    if len(_BAYER_FIELDS) > 8:
        _BAYER_FIELDS.clear()
    _BAYER_FIELDS[key] = field
    return field


def _felt_image(width: int, height: int, deep: RGB, mid: RGB) -> Image.Image:
    """The felt as a lit table rather than a flat field of noise.

    A flat dither is the thing that read as unfinished: an even scatter over
    the whole panel is a texture swatch, not a surface under a light. This
    dithers against a radial falloff instead, so the weave is densest under the
    middle of the table -- which is where the cards are -- and thins to bare
    black at the edges. Two masks give three tones out of two colours, which is
    the only way to get a gradient out of a palette this small.

    The falloff is a circle stretched to the panel, so a 512x64 strip gets a
    long ellipse of light rather than a spot in the middle with dead ends.

    All of it is PIL compositing rather than per-pixel Python: a 256x128 panel
    is 32k pixels, and the two thresholds are one subtract and one point each.
    Built once per table, then copied per frame.
    """
    key = (width, height, deep, mid)
    cached = _FELT_IMAGES.get(key)
    if cached is not None:
        return cached

    thresholds = _bayer_field(width, height)
    # radial_gradient is black in the middle and white at the rim; the table
    # wants the opposite, and wants it stretched to the panel's own shape.
    falloff = ImageOps.invert(Image.radial_gradient("L")).resize(
        (max(1, width), max(1, height)), Image.BILINEAR)

    # Two remaps of the same falloff: a broad one that decides where there is
    # any felt at all, and a narrow one that decides where it is bright. The
    # gap between them is what reads as the edge of the pool of light.
    broad = falloff.point(lambda v: min(255, int(v * 1.55)))
    narrow = falloff.point(lambda v: max(0, min(255, int((v - 86) * 1.9))))

    image = Image.new("RGB", (max(1, width), max(1, height)), (0, 0, 0))
    image.paste(Image.new("RGB", image.size, deep),
                (0, 0), ImageChops.subtract(broad, thresholds).point(_LIT))
    image.paste(Image.new("RGB", image.size, mid),
                (0, 0), ImageChops.subtract(narrow, thresholds).point(_LIT))
    if len(_FELT_IMAGES) > 8:
        _FELT_IMAGES.clear()
    _FELT_IMAGES[key] = image
    return image


def _fill_felt(image: Image.Image, theme: Theme) -> None:
    """Lay the lit felt over the whole image."""
    deep, mid = _felt_tones(theme)
    image.paste(_felt_image(image.width, image.height, deep, mid), (0, 0))


def _felt_tones(theme: Theme) -> Tuple[RGB, RGB]:
    """The two felt tones: the field and the dither's lit cell.

    A tenth and a fifth of the felt colour. The ceiling here is not taste, it
    is the cards: at a third the felt outshone a dark card face and the hand
    stopped being the brightest thing on the table, which is the one property
    the whole outline card style depends on.
    """
    return scale_color(theme.felt, 0.10), scale_color(theme.felt, 0.21)


def _rail_rect(layout: Layout) -> Optional[Tuple[int, int, int, int]]:
    """The inset rectangle for the table's rail, or ``None``.

    Drawn only where the seats leave two clear pixels on every side: one for
    the panel's black gutter and one for the rail itself. That is a measurement
    rather than a size whitelist -- a 128x32 panel spends its margin on cards
    and gets no rail, a 128x96 one has the room and does -- and it is the right
    test, because a rail that steals a row from a 14px card is worse than no
    rail at all.
    """
    seats = layout.seats.values()
    if min(s.x for s in seats) < 2 or min(s.y for s in seats) < 2:
        return None
    if max(s.x + s.width for s in seats) > layout.width - 2:
        return None
    if max(s.y + s.height for s in seats) > layout.height - 2:
        return None
    return (1, 1, layout.width - 2, layout.height - 2)


def _draw_rail(draw: ImageDraw.ImageDraw, rect: Tuple[int, int, int, int],
               theme: Theme) -> None:
    """The table's edge: a dim rule all the way round with brighter corners.

    The corners are the whole trick. A plain rectangle at this brightness is a
    faint box the eye stops seeing after a second; lighting the first few
    pixels of each arm instead reads as a frame with joinery in it, which is
    what an NES status screen does with two tones and no anti-aliasing.
    """
    x0, y0, x1, y1 = rect
    draw.rectangle([x0, y0, x1, y1], outline=scale_color(theme.felt, 0.34))
    corner = scale_color(theme.felt, 0.78)
    arm = max(2, min((x1 - x0) // 6, (y1 - y0) // 6, 6))
    for cx, step_x in ((x0, 1), (x1, -1)):
        for cy, step_y in ((y0, 1), (y1, -1)):
            draw.line([(cx, cy), (cx + step_x * (arm - 1), cy)], fill=corner)
            draw.line([(cx, cy), (cx, cy + step_y * (arm - 1))], fill=corner)


def _table_key(layout: Layout, theme: Theme) -> Tuple:
    """Everything a built table depends on, as a hashable key."""
    seats = []
    for name in sorted(layout.seats):
        seat = layout.seats[name]
        seats.append(seat.accent)
    return (layout.width, layout.height, layout.divider, layout.divider_span,
            theme.table_style, theme.felt, theme.dealer, theme.player,
            tuple(seats))


def _build_table(layout: Layout, theme: Theme) -> Image.Image:
    """Everything on the table that does not change while the hand is played.

    Built once and copied per frame. The alternative -- redrawing the felt, the
    rail and the rule every frame -- is a full-panel tile on every frame and
    a full-panel tile on top of the cards, for a picture that is identical
    thirty-nine frames out of forty.
    """
    image = Image.new("RGB", (layout.width, layout.height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    on_felt = theme.table_style != TABLE_VOID

    if on_felt:
        _fill_felt(image, theme)
        rail = _rail_rect(layout)
        if rail:
            _draw_rail(draw, rail, theme)

    _draw_divider(draw, layout, theme)

    for seat in layout.seats.values():
        color = theme.seat_color(seat.seat)
        if seat.accent:
            # Bevelled rather than a flat bar: two pixels is enough for a lit
            # face and a dark side, and on felt a flat bar of one tone reads as
            # a smudge in the weave rather than as a marker.
            ax0, ay0, ax1, ay1 = seat.accent
            draw.rectangle([ax0, ay0, ax1, ay1], fill=scale_color(color, 0.28))
            draw.line([(ax0, ay0), (ax0, ay1)], fill=scale_color(color, 0.62))

    # A black pixel all the way round, always. Two reasons, and the second is
    # the one that matters: an emissive panel has no bezel, so a felt that runs
    # into the frame has no edge and the table stops looking like an object;
    # and it keeps the result band the only thing that ever lights the outermost
    # column, which is how the band's height is measured.
    draw.rectangle([0, 0, layout.width - 1, layout.height - 1],
                   outline=(0, 0, 0))
    return image


def table_image(layout: Layout, theme: Theme) -> Image.Image:
    """The cached table for this layout and theme."""
    key = _table_key(layout, theme)
    table = _TABLES.get(key)
    if table is None:
        table = _build_table(layout, theme)
        if len(_TABLES) >= _TABLE_CACHE_MAX:
            # Whole-dict eviction rather than an LRU: the plugin uses one or
            # two tables at a time, so this can only ever fire on a test sweep
            # across panel sizes, where rebuilding is free.
            _TABLES.clear()
        _TABLES[key] = table
    return table


#: Brightness of the divider along its length, centre outward. The rule has to
#: say "two halves of one table" without competing with the cards, and a flat
#: line at a readable brightness does compete; grading it lets the middle be
#: bright enough to see while the ends dissolve into the felt.
_DIVIDER_FALLOFF = (0.22, 0.38, 0.56, 0.74, 0.90, 1.0, 0.90, 0.74, 0.56, 0.38, 0.22)


def _draw_divider(draw: ImageDraw.ImageDraw, layout: Layout, theme: Theme) -> None:
    """The rail between the two seats.

    Runs the full width of the table and fades out at both ends. What it
    replaced was a dotted stub inset a fifth at each end, which was sized for a
    64px panel: on a 256px one it was a dash hanging in the middle of a row
    that now runs from the seat's name to its total, and it read as a leftover
    guide rather than as the table the hands sit on.

    Where the gutter can spare a second line the rule gets a dark one under it
    -- the same lit-edge-over-dark-edge the cards use -- which turns a drawn
    line into the lip of the table. One line on its own was the last piece of
    the old look that still said "a rule on a background" out loud.

    Eleven segments, not a per-pixel sweep, so a 384px panel costs the same
    eleven calls at 40fps as a 64px one.
    """
    if not layout.divider:
        return
    x0, y0, x1, y1 = layout.divider
    horizontal = y0 == y1
    length = (x1 - x0 + 1) if horizontal else (y1 - y0 + 1)
    if length <= 0:
        return
    origin = x0 if horizontal else y0
    base = scale_color(theme.felt, 0.8)
    # The shadow is the table showing through, not a colour of its own, so on a
    # void table there is nothing to draw and the rail is a single line again.
    shade = (0, 0, 0) if theme.table_style != TABLE_VOID else None
    bands = len(_DIVIDER_FALLOFF)
    for index, weight in enumerate(_DIVIDER_FALLOFF):
        start = origin + index * length // bands
        end = origin + (index + 1) * length // bands - 1
        if end < start:
            continue
        color = scale_color(base, weight)
        if color == (0, 0, 0):
            continue
        if horizontal:
            draw.line([(start, y0), (end, y0)], fill=color)
            if shade and layout.divider_span >= 2 and weight >= 0.5:
                draw.line([(start, y0 + 1), (end, y0 + 1)], fill=shade)
        else:
            draw.line([(x0, start), (x0, end)], fill=color)
            if shade and layout.divider_span >= 2 and weight >= 0.5:
                draw.line([(x0 + 1, start), (x0 + 1, end)], fill=shade)


def _draw_seat(draw: ImageDraw.ImageDraw, seat: SeatLayout, cards: Sequence[Card],
               face_down_index: Optional[int], flip: float,
               dealing: Optional[Tuple[int, float]], total: Optional[int],
               theme: Theme, glow_index: Optional[int] = None,
               glow: float = 0.0) -> None:
    """Draw one seat: its name, its cards, and its running total.

    The seat's chrome -- the accent bar -- is not drawn
    here: it never changes during a hand, so it is baked into the table image
    once and this only sets the type that goes in it.
    """
    color = theme.seat_color(seat.seat)

    if seat.label:
        draw_text(draw, seat.label_x, seat.label_y, seat.label,
                  scale_color(color, 0.75), seat.label_scale)

    if seat.show_total and (total is not None or cards):
        known = total is not None
        text = str(total) if known else "?"
        # Right-aligned in the totals column. The column is sized for two
        # digits, and a one-digit total set from the left would sit somewhere
        # the two-digit one never does, so the number jumps sideways the moment
        # a hand goes from 9 to 17.
        tx = seat.total_x + (numeral_width("00", seat.total_scale)
                             - numeral_width(text, seat.total_scale))
        draw_numerals(draw, tx, seat.total_y, text,
                      color if known else scale_color(color, 0.7),
                      seat.total_scale)

    moving_index = dealing[0] if dealing else None
    for index, card in enumerate(cards):
        if index == moving_index:
            continue  # drawn last, on top of the rest
        face_down = index == face_down_index
        x, y = seat.card_origin(index)
        if not face_down:
            draw_card(draw, x, y, seat.card_w, seat.card_h, card, True, theme, 1.0)
            continue
        # Mid-reveal the card is edge-on at flip 0.5: the back shrinks away and
        # the face grows back out of the same sliver.
        squash = abs(1.0 - 2.0 * flip)
        draw_card(draw, x, y, seat.card_w, seat.card_h, card,
                  flip >= 0.5, theme, squash)

    if moving_index is not None and moving_index < len(cards):
        _draw_dealing_card(draw, seat, cards[moving_index], moving_index,
                           dealing[1], face_down_index == moving_index, theme)

    if glow > 0.01 and glow_index is not None and glow_index < len(cards):
        # The card the whole hand was waiting on lands and then... nothing; the
        # squash ends and it is just another card in the row. A border that
        # burns bright and decays over half a second is the "there it is" the
        # reveal was missing, and it is drawn on the card's own edge rather
        # than around it so it cannot touch the neighbour in a tight fan.
        gx, gy = seat.card_origin(glow_index)
        edge = scale_color(mix_color(theme.dealer, WHITE, 0.55 * glow),
                           0.40 + 0.60 * glow)
        draw.rectangle([gx, gy, gx + seat.card_w - 1, gy + seat.card_h - 1],
                       outline=edge)
        _round_corners(draw, gx, gy, seat.card_w, seat.card_h)


def _draw_dealing_card(draw: ImageDraw.ImageDraw, seat: SeatLayout, card: Card,
                       index: int, progress: float, stays_down: bool,
                       theme: Theme) -> None:
    """A card in flight: it slides in from the right as a back, then flips face
    up in place. A card dealt face down (the hole card) skips the flip."""
    slot_x, slot_y = seat.card_origin(index)
    # Start beyond the seat's own right edge, not a fixed three card widths:
    # on a 256-wide panel three widths is still inside the felt, so the first
    # card of a hand materialised in the middle of the table rather than
    # arriving from the shoe.
    travel = max(seat.card_w * 3 + 4, seat.x + seat.width - slot_x + 2)
    slide_end = 0.6 if not stays_down else 0.85

    if progress <= slide_end:
        p = progress / slide_end if slide_end else 1.0
        eased = _ease_out(min(1.0, p / _SETTLE_AT))
        x = int(round(slot_x + travel * (1.0 - eased)))
        if p > _SETTLE_AT:
            # A card pitched onto felt does not stop dead; it runs a little
            # past its place and rocks back. Without it the arrival is the one
            # frame where the position stops changing, which on a matrix is
            # indistinguishable from a dropped frame.
            settle = (p - _SETTLE_AT) / (1.0 - _SETTLE_AT)
            x -= int(round(max(1, seat.card_w // 5) * math.sin(math.pi * settle)))
        # Under ease-out cubic the speed falls off as the square of the time
        # left, so the trail thins out on exactly the curve the card does.
        strength = (1.0 - min(1.0, p / _SETTLE_AT)) ** 2
        _draw_trail(draw, x, slot_y, seat, max(2, int(round(seat.card_w * 0.55))),
                    strength, theme)
        draw_card(draw, x, slot_y, seat.card_w, seat.card_h, card, False, theme, 1.0)
        return

    if stays_down:
        draw_card(draw, slot_x, slot_y, seat.card_w, seat.card_h, card, False, theme, 1.0)
        return

    flip = (progress - slide_end) / max(1e-6, 1.0 - slide_end)
    squash = abs(1.0 - 2.0 * min(1.0, flip))
    face_up = flip >= 0.5
    draw_card(draw, slot_x, slot_y, seat.card_w, seat.card_h, card, face_up,
              theme, squash)


def _draw_action(draw: ImageDraw.ImageDraw, layout: Layout,
                 state: ViewState, theme: Theme) -> None:
    """The call beside a hand -- HIT / STAND / DOUBLE, or a BUST / 21 call-out.

    It fades in and back out over the beat rather than snapping, so a sequence
    of hits reads as separate decisions instead of one flickering word.

    Two weights, because two different things happen here. A *call* is the
    player choosing, and it is a quiet bordered chip on black. A *call-out* is
    the table announcing a fact -- this hand is dead, that hand is twenty-one
    -- and it is knocked out of a solid chip in the outcome colour. Drawing
    both the same made a bust land with exactly the weight of a routine hit.
    """
    text = state.action_text
    if not text:
        return
    progress = max(0.0, min(1.0, state.action_progress))
    # The tag *snaps* on and fades off. It used to ramp up over the first fifth
    # of the beat -- a quarter of a second of a word getting brighter, which
    # reads as the panel thinking about it. A call is a decision; it arrives
    # already made. The fall-away stays soft so a run of hits reads as separate
    # decisions rather than one flickering word.
    alpha = 1.0 if progress <= 0.75 else max(0.0, (1.0 - progress) / 0.25)
    if alpha <= 0.02:
        return

    seat = layout.seats.get(state.action_seat) or layout.seats["player"]
    called_out = bool(state.action_tone)
    tone = theme.tone_color(state.action_tone) if called_out \
        else theme.seat_color(seat.seat)

    # First choice is the empty strip between the last card and the totals
    # column -- the call is a caption on the hand, and covering the hand to
    # show it is exactly backwards. The type size is chosen to fit that strip
    # rather than chosen first and then found not to fit, which is what pushed
    # every STAND (one letter wider than HIT) onto the cards.
    free_left = seat.cards_x + seat.span + 2
    # Two pixels off the totals column, not the wider clearance the cards keep:
    # the tag carries its own border and black fill, so it is already separated
    # from the number beside it, and on a 128x32 panel the extra pixels are the
    # difference between DOUBLE fitting here and falling back onto the cards.
    free_right = (seat.total_x - 2) if seat.show_total else (seat.x + seat.width)
    free_w = free_right - free_left
    divider_y = None
    if layout.divider:
        dx0, dy0, dx1, dy1 = layout.divider
        divider_y = dy0 if dy0 == dy1 else None

    def box_for(scale: int) -> Tuple[int, int, int]:
        pad = 2 if scale == 1 else 3
        # A knockout chip pays for the second margin: the word is a hole in a
        # lit block, so a row short at the top reads as a clipped glyph rather
        # than as tight leading the way it does on bordered type.
        below = pad if called_out else 0
        return (text_width(text, scale) + pad * 2,
                text_height(scale) + pad + below, pad)

    # The tag grows with the cards. A two-scale ceiling was right when the
    # reference panel was 128x32; on a 256x128 table it left a nine-pixel chip
    # beside a sixty-pixel card, which for a BUST call-out is a whisper.
    want = min(4, max(1, seat.card_h // 14)) if called_out \
        else (3 if seat.card_h >= 40 else 2)
    scale = 0
    for candidate in range(want, 0, -1):
        box_w, box_h, pad = box_for(candidate)
        if box_w <= free_w and box_h <= seat.card_h:
            scale = candidate
            break

    if scale and (scale == want or not called_out):
        box_w, box_h, pad = box_for(scale)
        x = free_left + (free_w - box_w) // 2
        y = seat.cards_y + (seat.card_h - box_h) // 2
    elif called_out:
        # The leftover strip is the right home for a *caption*, but a hand that
        # just died is an announcement, and on a big panel the strip is a
        # nineteen-pixel sliver beside a sixty-pixel card. So a call-out that
        # cannot have the size the row deserves takes the row instead, centred
        # on the hand it is about. It is a bordered chip over four seconds of
        # cards, not a redraw of them -- the hand is still there on both sides
        # of it, and back in full a second and a half later.
        scale = fit_scale(text, max(8, seat.width - 6), max_scale=want)
        while scale > 1 and box_for(scale)[1] > seat.card_h:
            scale -= 1
        box_w, box_h, pad = box_for(scale)
        x = seat.cards_x + (seat.span - box_w) // 2
        y = seat.cards_y + (seat.card_h - box_h) // 2
    else:
        # The hand fills the row, so the call sits over the table instead --
        # astride the felt line where a stacked table has its only free strip.
        scale = fit_scale(text, max(8, seat.width - 4), max_scale=2)
        box_w, box_h, pad = box_for(scale)
        x = seat.x + (seat.width - box_w) // 2
        y = (divider_y - box_h // 2) if divider_y is not None \
            else seat.y + seat.height - box_h
    th = text_height(scale)
    x = max(0, min(layout.width - box_w, x))
    y = max(0, min(layout.height - box_h, y))

    # The chip springs open from a slit rather than appearing at full size: two
    # frames of a shutter, which is what a menu box does in every game of the
    # era. Contained inside the chip's own footprint on purpose -- an effect
    # that grew *outward* would reach back over the cards the tag is captioning,
    # which is the one place this tag is not allowed to be.
    grown = _ease_out(min(1.0, progress / _TAG_SNAP))
    drawn_h = max(1, int(round(box_h * grown)))
    y0 = y + (box_h - drawn_h) // 2
    text_y = y + (box_h - th) // 2
    show_text = drawn_h >= th + 1

    if called_out:
        # A lit plate with the word punched out of it, and the plate itself
        # given a top highlight, a dithered step and a shaded bottom row. Flat
        # fill made a BUST the same object as a HIT in a different colour; the
        # ramp is what makes it a stamped sign.
        _bevel_plate(draw, x, y0, box_w, drawn_h, tone, alpha)
        if show_text:
            draw_text(draw, x + pad, text_y, text, (0, 0, 0), scale)
        return

    color = scale_color(tone, alpha)
    draw.rectangle([x + 1, y0 + 1, x + box_w, y0 + drawn_h], fill=(0, 0, 0))
    draw.rectangle([x - 1, y0 - 1, x + box_w, y0 + drawn_h], fill=(0, 0, 0))
    draw.rectangle([x, y0, x + box_w - 1, y0 + drawn_h - 1],
                   outline=scale_color(color, 0.42))
    # Corner brackets. A plain rectangle is a border; four brighter corners are
    # a *selection*, which is the grammar every menu of the era used and is
    # exactly what a HIT or a STAND is -- a choice that has just been taken.
    _corner_brackets(draw, x, y0, box_w, drawn_h,
                     scale_color(mix_color(tone, WHITE, 0.45), alpha))
    if show_text:
        draw_text(draw, x + pad, text_y, text, color, scale)


def _draw_banner(image: Image.Image, layout: Layout, state: ViewState,
                 theme: Theme) -> Image.Image:
    """The result banner: a hit, a burst, and a sign that lights up.

    The table is not cleared away -- a blackjack is only a blackjack because of
    the cards still sitting there -- so the band is a *tint* of the pixels
    already there and the hand reads as shapes under coloured glass.

    What happens on top of that band is the arcade half, and it is a sequence
    of hits rather than a fade:

    1. **a flash frame.** Two frames of near-white over the whole panel. This
       is the oldest trick in the era and the cheapest: one blend against a
       cached flat frame.
    2. **the rattle.** The panel is knocked off its axis and settles -- three
       pixels on a big panel for a loss, one for a win. Applied to the finished
       composite in :func:`render`, so it costs one paste and never has to be
       reconciled with where anything was drawn.
    3. **the burst.** On a win, sparks erupt from the middle of the table on
       parabolic arcs while the band is still opening -- which is the only
       moment a 32-row panel has anywhere to put them.
    4. **the sign.** Two rules sweep apart, the tone washes into the gap, and
       the word *lands whole and white-hot* rather than assembling itself. A
       gleam then runs across it, and on a natural sparkle stars blink in the
       band's margins.
    5. **the score.** The totals count up from zero and pop white when they
       land.

    The previous version did stages 3-5 as a letter-by-letter fade of flat
    coloured type on a tinted band, which is decent motion design and reads, at
    a glance, as big numbers on a screen.
    """
    progress = max(0.0, min(1.0, state.banner_progress))
    since = max(0.0, state.banner_elapsed)
    tone = theme.tone_color(state.banner_tone)
    celebrating = state.banner_tone in (TONE_BLACKJACK, TONE_WIN)
    natural = state.banner_tone == TONE_BLACKJACK

    width, height = layout.width, layout.height
    max_text_w = max(8, width - 6)
    # The band never takes more than about two-thirds of the panel: the cards
    # behind it are the reason the banner says what it says, and a full-height
    # band throws them away at exactly the moment they matter.
    band_cap = max(GLYPH_HEIGHT + 2, int(height * 0.72))
    sub = state.banner_subtext
    # The flourish takes the second line first, then hands it back to the
    # score. It is the surprising half and the score is the reference half, so
    # the order is "what just happened" then "what the numbers were" -- and
    # showing both at once would need a third line the band cannot afford.
    flourish = state.banner_flourish

    def band_for(scale: int, with_sub: bool) -> Optional[int]:
        """Band height at this type size, or None if it will not fit."""
        if text_width(state.banner_text, scale) > max_text_w:
            return None
        pad = 2 if scale == 1 else 3
        total = text_height(scale) + pad * 2
        if with_sub:
            total += text_height(1 if scale <= 1 else scale - 1) + 1
        return total if total <= band_cap else None

    # Prefer keeping the score line: it is the one piece of the hand the banner
    # would otherwise cover up. Only drop it when no type size fits with it.
    scale, band_h, show_sub = 1, None, False
    for want_sub in ((True, False) if sub else (False,)):
        for candidate in range(layout.banner_scale_cap, 0, -1):
            fitted = band_for(candidate, want_sub)
            if fitted is not None:
                scale, band_h, show_sub = candidate, fitted, want_sub
                break
        if band_h is not None:
            break
    if band_h is None:
        scale, show_sub = 1, False
        band_h = min(band_cap, text_height(1) + 4)

    th = text_height(scale)
    sub_scale = 1 if scale <= 1 else scale - 1
    sub_h = text_height(sub_scale) if show_sub else 0

    # A loss shuts faster than a win opens. Same stages, but a bust should feel
    # like the table closing on you and a win like a sign lighting up, and the
    # only free variable that costs nothing is the pacing.
    open_span = 0.36 if not celebrating else 0.52
    open_t = _ease_back(min(1.0, progress / open_span))
    # Clamped to the same ceiling the settled band obeys. The overshoot is a
    # flourish; it is not a licence to cover the table for three frames, and on
    # a short panel the band already sits within a pixel of the cap so there is
    # nowhere to overshoot into anyway.
    drawn_h = max(1, min(band_cap, int(round(band_h * open_t))))
    center_y = height // 2
    top = max(0, center_y - drawn_h // 2)
    bottom = min(height - 1, top + drawn_h - 1)

    # The table darkens ahead of the rules rather than alongside them. When
    # the two ran together the rules swept across a table still at three
    # quarters brightness and cut the totals in half: an 18 with a bright line
    # through the 8 reads as a 10.
    dim = 1.0 - 0.70 * min(1.0, progress / (open_span * 0.5))
    if dim < 0.999:
        image = Image.blend(_black_like(image), image, dim)

    wash = min(1.0, max(0.0, (progress - open_span * 0.55) / (open_span * 0.85)))
    if wash > 0.02 and bottom >= top:
        box = (0, top, width, bottom + 1)
        region = image.crop(box)
        tint = Image.new("RGB", region.size, scale_color(tone, 0.17))
        image.paste(Image.blend(region, tint, 0.60 * wash), box)

    draw = ImageDraw.Draw(image)
    # Two pixels of rule on a tall panel. One is a hairline at 128 rows and the
    # band stops reading as an edge; it is still one pixel wherever the band is
    # too shallow to spend two on each side.
    rule_h = 2 if (height >= 64 and drawn_h >= 6) else 1
    rule = scale_color(tone, 0.62)
    if state.banner_tone == TONE_LOSE and since > _FLASH_SECONDS:
        # A loss gets the opposite of the winner's marquee: the sign it lit is
        # a dud, and every so often a tube in it drops out. Four seconds of a
        # perfectly still red word was the other half of "big numbers on
        # screen", and a chase on a bust would be the table cheering.
        if (since % _STUTTER_PERIOD) < _STUTTER_WINDOW \
                and not _STUTTER[int(since * 11.0) % len(_STUTTER)]:
            rule = scale_color(tone, 0.16)
    draw.rectangle([0, top, width - 1, top + rule_h - 1], fill=rule)
    draw.rectangle([0, bottom - rule_h + 1, width - 1, bottom], fill=rule)
    # One black row inside each rule. Without it the lit rule bleeds straight
    # into the tinted field and the band reads as a soft gradient -- a lens
    # flare, not a sign. The gap is the same 1px keyline every sprite on this
    # panel gets, applied to the largest object on it.
    if drawn_h >= rule_h * 2 + 3:
        draw.rectangle([0, top + rule_h, width - 1, top + rule_h], fill=(0, 0, 0))
        draw.rectangle([0, bottom - rule_h, width - 1, bottom - rule_h], fill=(0, 0, 0))
    if celebrating and bottom > top:
        _draw_chase(draw, width, top, bottom, rule_h, tone, state.clock,
                    46.0 if natural else 26.0)

    if celebrating:
        # Twelve sparks on a panel with room, eight on a small one. Not for
        # speed -- twelve points cost nothing -- but because twelve particles
        # across sixty-four columns is confetti with no gaps in it, and a burst
        # you cannot count the pieces of is just noise.
        _draw_sparks(draw, width, height, width / 2.0, center_y, since, tone,
                     12 if width >= 96 else 8,
                     1.0 if natural else 0.82,
                     waves=2 if width >= 192 else 1)
        _draw_fountain(draw, width, top, top, since, tone)

    if progress < open_span * 0.8:
        return _flash(image, since, progress, tone, state.banner_tone)

    # The word lands whole, white-hot for a couple of frames, and cools into
    # the tone. It used to assemble itself letter by letter on a win, which is
    # a pretty effect and the wrong one: a result is a verdict, and a verdict
    # that spells itself out has no impact frame. The gleam that follows is
    # where the motion went.
    text_t = min(1.0, (progress - open_span * 0.8) / max(0.05, 0.92 - open_span * 0.8))
    content_h = th + (sub_h + 1 if show_sub else 0)
    text_y = top + max(0, (drawn_h - content_h) // 2)
    gleam = None
    if state.banner_tone != TONE_LOSE:
        phase = since - _GLEAM_DELAY
        if phase >= 0.0:
            swept = (phase % _GLEAM_PERIOD) / _GLEAM_SWEEP
            if swept <= 1.0:
                gleam = swept
    if text_y + th <= bottom + 1:
        _draw_knockout_centered(image, width // 2, text_y, state.banner_text,
                                scale, tone, gleam,
                                0.9 * max(0.0, 1.0 - text_t * 4.0))

    if celebrating:
        margin = (width - text_width(state.banner_text, scale)) // 2
        _draw_twinkle(draw, width, top, bottom, margin, since, tone,
                      _TWINKLE_PERIOD if natural else _TWINKLE_PERIOD_WIN)

    if show_sub:
        sub_y = text_y + th + 1
        if sub_y + sub_h <= bottom + 1 and since >= _SUB_DELAY:
            elapsed_sub = since - _SUB_DELAY
            # A rare hand takes the second line first and the score takes it
            # back. Both cannot be up at once -- the band has one line to spend
            # -- and the flourish goes first because it is the surprising half;
            # a "777" that appeared after the score would read as a footnote to
            # it rather than as the thing that just happened.
            showing_flourish = (flourish
                                and elapsed_sub < _FLOURISH_SECONDS
                                and text_width(flourish, sub_scale) <= max_text_w)
            if showing_flourish:
                draw_text_centered(ImageDraw.Draw(image), width // 2, sub_y,
                                   flourish, tone, sub_scale)
            else:
                # The count starts when the flourish clears, not when the band
                # opens, or a rare hand would show a half-counted score the
                # instant its label disappeared.
                head_start = _FLOURISH_SECONDS if flourish else 0.0
                tallied = max(0.0, elapsed_sub - head_start)
                pop = max(0.0, 1.0 - abs(tallied - _TALLY_SPAN) / _TALLY_POP) \
                    if tallied >= _TALLY_SPAN else 0.0
                _draw_tally(image, width // 2, sub_y, sub, tone, sub_scale,
                            tallied / _TALLY_SPAN, pop)
    return _flash(image, since, progress, tone, state.banner_tone)


def render_summary(width: int, height: int, script, theme: Theme) -> Image.Image:
    """A finished hand as one still: the finished table, then the result.

    This is what the Vegas ticker shows. A hand is a twenty-second animation
    and a ticker item is a picture that slides past in two, so the animation
    cannot be the content -- but the *outcome* can, and the script is simulated
    to completion before the first card is dealt, so the finished hand is
    known at any moment.

    Laid out as the result *beside* the cards where there is width for it, and
    over them where there is not. The ticker's width budget is at most one
    panel and anything wider is cropped to its start, so a two-panel
    arrangement would show the cards and lose the result -- which is the half
    that matters. On a 512x64 strip both fit side by side comfortably; on a
    128x32 the result takes the final frame's own banner treatment instead,
    which already says everything in the space available.
    """
    final = ViewState(
        dealer_cards=list(script.dealer_cards),
        player_cards=list(script.player_cards),
        dealer_final=script.dealer_card_count,
        player_final=script.player_card_count,
        hole_down=False, hole_flip=1.0,
        dealer_total=script.dealer_total, player_total=script.player_total,
        clock=0.0,
    )

    outcome = script.outcome_text
    tone = theme.tone_color(script.outcome_tone)
    # The result column has to hold the widest line it will draw, plus a rule
    # and a pixel of air either side.
    scale = fit_scale(outcome, max(8, width // 2 - 6), max_scale=2)
    panel_w = max(text_width(outcome, scale),
                  numeral_width(f"{script.player_total}-{script.dealer_total}", 1)) + 6

    # Side by side only where the table keeps a workable width. Below that the
    # cards would be squeezed to buy room for a word.
    if width - panel_w >= 72:
        table_w = width - panel_w
        image = Image.new("RGB", (width, height), (0, 0, 0))
        layout = compute_layout(table_w, height, script.dealer_card_count,
                                script.player_card_count)
        image.paste(render(table_w, height, layout, final, theme), (0, 0))
        draw = ImageDraw.Draw(image)
        rule_x = table_w + 1
        draw.line([(rule_x, 2), (rule_x, height - 3)], fill=scale_color(tone, 0.45))
        centre = table_w + panel_w // 2
        block_h = text_height(scale) + (numeral_height(1) + 2 if height >= 24 else 0)
        top = max(0, (height - block_h) // 2)
        draw_text_centered(draw, centre, top, outcome, tone, scale)
        if height >= 24:
            draw_numerals(
                draw,
                centre - numeral_width(f"{script.player_total}-{script.dealer_total}", 1) // 2,
                top + text_height(scale) + 2,
                f"{script.player_total}-{script.dealer_total}",
                scale_color(tone, 0.6), 1)
        return image

    # Too narrow to split: the hand's own final frame already composes the
    # cards and the verdict into one panel, so use it rather than inventing a
    # second cramped arrangement that says the same thing worse.
    final.banner_text = outcome
    final.banner_subtext = f"{script.player_total}-{script.dealer_total}"
    final.banner_flourish = script.flourish
    final.banner_tone = script.outcome_tone
    final.banner_progress = 1.0
    final.banner_elapsed = _FLOURISH_SECONDS + _SUB_DELAY + _TALLY_SPAN + 0.2
    layout = compute_layout(width, height, script.dealer_card_count,
                            script.player_card_count)
    return render(width, height, layout, final, theme)


def render(width: int, height: int, layout: Layout, state: ViewState,
           theme: Theme) -> Image.Image:
    """One frame, start to finish.

    A fresh in-memory image every frame rather than clearing the display
    manager's buffer: ``DisplayManager.clear()`` writes straight to the matrix,
    so using it as a per-frame reset makes the panel flash black between
    frames.

    The fresh image is a copy of the cached table -- the lit felt, the rail and
    the rule -- so the static two-thirds of the picture costs one memcpy a
    frame instead of being redrawn.
    """
    image = table_image(layout, theme).copy()
    draw = ImageDraw.Draw(image)

    dealing_seat = state.dealing[0] if state.dealing else None
    for seat_name, cards, total, final in (
        ("dealer", state.dealer_cards, state.dealer_total, state.dealer_final),
        ("player", state.player_cards, state.player_total, state.player_final),
    ):
        seat = layout.seats[seat_name]
        face_down = 1 if (seat_name == "dealer" and state.hole_down
                          and len(cards) > 1) else None
        dealing = None
        if dealing_seat == seat_name and state.dealing:
            dealing = (state.dealing[1], state.dealing[2])
        flip = state.hole_flip if seat_name == "dealer" else 1.0
        glow_index = 1 if (seat_name == "dealer" and len(cards) > 1) else None
        _draw_seat(draw, seat, cards, face_down, flip, dealing, total, theme,
                   glow_index, state.reveal_glow if seat_name == "dealer" else 0.0)

    if state.action_text:
        _draw_action(draw, layout, state, theme)

    if state.banner_text and state.banner_progress > 0:
        image = _draw_banner(image, layout, state, theme)

    # The rattle is applied last, to the finished frame. Offsetting the
    # composite rather than every draw call means nothing downstream has to
    # know it is happening -- and it is still a pure function of the clock, so
    # a dropped frame skips a jolt instead of leaving the table off its axis.
    #
    # The vacated edge is filled black rather than with the felt: a shake that
    # slid the felt too would move the table's own texture against the panel,
    # which reads as the picture tearing rather than as the table being hit.
    dx, dy = _frame_shake(state, height)
    if dx or dy:
        shifted = Image.new("RGB", (width, height), (0, 0, 0))
        shifted.paste(image, (dx, dy))
        image = shifted

    return image
