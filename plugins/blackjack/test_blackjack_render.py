#!/usr/bin/env python3
"""Render and layout tests for the blackjack plugin.

The safety harness renders one frame per mode, which lands during the opening
pause -- so on its own it proves only that an empty table survives every panel
shape. This drives the whole hand, beat by beat, across a wide sweep of panel
shapes, and checks the layout invariants a screenshot would not catch.

Standalone script, per this repo's convention:
    0 pass, 2 skip (prerequisites absent), 1 fail.

    python plugins/blackjack/test_blackjack_render.py
"""

from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    print(f"SKIP: Pillow is not installed ({exc})")
    raise SystemExit(2)

import blackjack_render as br
from blackjack_engine import ACTION, DEAL, OUTCOME, REVEAL, Rules, Shoe, play_hand
from blackjack_render import Theme, ViewState, compute_layout, render

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "test"))
from render_examples import build_timeline, state_at  # noqa: E402

FAILURES = []

#: A spread of shapes, not a list of blessed sizes: the harness default eight,
#: plus the degenerate small ones and some off-grid oddities, because an RGB
#: matrix build can be any rectangle.
SIZES = [
    (64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32),
    (128, 96), (256, 128), (32, 16), (32, 32), (48, 24), (80, 40),
    (160, 32), (192, 64), (384, 32), (64, 128), (96, 96), (256, 64),
    (128, 16), (8, 16),
]


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def lit_pixels(image):
    return sum(1 for pixel in image.getdata() if pixel != (0, 0, 0))


def sample_hand(seed=11, predicate=None):
    predicate = predicate or (lambda s: s.player_card_count >= 3 and s.dealer_card_count >= 3)
    shoe = Shoe(6, random.Random(seed))
    for _ in range(4000):
        script = play_hand(shoe, Rules())
        if predicate(script):
            timeline, total = build_timeline(script)
            return script, timeline, total
    raise AssertionError("no matching hand")


def beats(timeline, total):
    """One sample inside every beat, plus the edges of the animated ones."""
    out = [0.0, 0.3]
    for start, duration, event in timeline:
        out += [start + 0.01, start + duration * 0.3, start + duration - 0.01]
        if event.kind == DEAL:
            out += [start + 0.2, start + 0.44]
        if event.kind == REVEAL:
            out += [start + 0.27, start + 0.55]
    out += [total - 0.01, total, total + 5.0]
    return out


# ---------------------------------------------------------------------------


def test_font_covers_every_string():
    """A character with no glyph renders as a blank, silently. Every string the
    plugin can put on screen has to be in the face."""
    strings = ["DEALER", "YOU", "HIT", "STAND", "DOUBLE", "?",
               "BLACKJACK!", "BUST!", "PUSH", "YOU WIN!", "DEALER WINS",
               "DEALER BUST", "DEALER 21"]
    strings += [f"{a}-{b}" for a in (4, 21, 26) for b in (2, 17, 30)]
    strings += [str(n) for n in range(2, 31)]
    missing = sorted({char for text in strings for char in text.upper()
                      if char not in br._GLYPHS})
    check("every on-screen string is drawable", not missing, str(missing))

    ranks = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
    check("every rank has a card glyph",
          all(rank in br._RANK_GLYPHS for rank in ranks))
    check("every character a total can contain is in the numeral face",
          all(char in br._NUMERALS
              for char in set("".join(str(n) for n in range(0, 32)) + "?-")))
    check("every suit has a pip in every size",
          all(suit in face for _, face in br._PIP_FACES for suit in "SHDC"))
    check("every pip face is square and the size it claims",
          all(len(g) == size and all(len(row) == size for row in g)
              for size, face in br._PIP_FACES for g in face.values()),
          str([(size, {s: (len(g), len(g[0])) for s, g in face.items()})
               for size, face in br._PIP_FACES]))
    check("each face is a consistent height",
          all(len(g) == br.GLYPH_HEIGHT for g in br._GLYPHS.values())
          and all(len(g) == br.NUMERAL_HEIGHT for g in br._NUMERALS.values())
          and all(len(g) == br.NUMERAL_HEIGHT for g in br._RANK_GLYPHS.values()))
    check("glyph rows are all the same width",
          all(len({len(row) for row in g}) == 1
              for face in (br._GLYPHS, br._NUMERALS, br._RANK_GLYPHS)
              for g in face.values()))
    check("every rank is the same width in a given face",
          len({len(g[0]) for g in br._RANK_GLYPHS.values()}) == 1,
          str({r: len(g[0]) for r, g in br._RANK_GLYPHS.items()}))


def test_same_colour_pips_are_distinguishable():
    """Spade against club, and heart against diamond.

    These are the only pairs shape has to separate: every other pair is a red
    pip against a black one, and ink colour has already told the eye which is
    which before it gets to the silhouette. The club this replaced was a split
    top row over a full one, which at a pip's size reads as an asterisk -- near
    enough to the spade that a hand of black cards had no suits at all.
    """
    problems = []
    for size, face in br._PIP_FACES:
        cells = size * size
        for first, second in (("S", "C"), ("H", "D")):
            a, b = face[first], face[second]
            differing = sum(1 for row_a, row_b in zip(a, b)
                            for pixel_a, pixel_b in zip(row_a, row_b)
                            if pixel_a != pixel_b)
            # A sixth of the face. The set achieves a fifth at its tightest
            # (7x7 spade against club, and 5x5 heart against diamond), so this
            # leaves room to reshape a pip without letting one quietly collapse
            # toward its neighbour. Below a sixth the two marks are the same
            # shape with a couple of pixels moved, which is what a pip cannot
            # afford: there is no second character to disambiguate it and no
            # word shape to fall back on.
            if differing * 6 < cells:
                problems.append(f"{size}x{size} {first}/{second} differ by "
                                f"{differing} of {cells}px")
    check("same-coloured suits are told apart by shape", not problems,
          "; ".join(problems))


def test_rank_glyphs_are_distinguishable():
    """The whole point of the 5x7 face. Every pair of ranks must differ by more
    than a pixel or two, or a K reads as an A across the room."""
    face = br._RANK_GLYPHS
    ranks = sorted(face)
    pairs = []
    worst = (99, "")
    for index, first in enumerate(ranks):
        for second in ranks[index + 1:]:
            a, b = face[first], face[second]
            if len(a[0]) != len(b[0]):
                continue
            differing = sum(1 for row_a, row_b in zip(a, b)
                            for pixel_a, pixel_b in zip(row_a, row_b)
                            if pixel_a != pixel_b)
            # Six is what the face currently achieves (6/8 and 8/9 are the
            # tightest pairs); five leaves room to reshape a glyph without
            # letting one quietly collapse toward its neighbour.
            if differing < 5:
                pairs.append(f"{first}/{second} differ by {differing}px")
            if differing < worst[0]:
                worst = (differing, f"{first}/{second}")
    check("no two ranks are within a few pixels of each other", not pairs,
          "; ".join(pairs))

    # The face this replaced put 8 and 9 -- and 5 and 6, and 3 and 9 -- one lit
    # pixel apart. Measure against it so a future "let's save two columns"
    # cannot quietly walk back the reason this face exists.
    legacy = {rank: br._GLYPHS[rank] for rank in
              ("2", "3", "4", "5", "6", "7", "8", "9", "A", "J", "Q", "K")}

    def closest(source):
        keys = sorted(source)
        return min(sum(1 for row_a, row_b in zip(source[a], source[b])
                       for pixel_a, pixel_b in zip(row_a, row_b)
                       if pixel_a != pixel_b)
                   for i, a in enumerate(keys) for b in keys[i + 1:])

    before, after = closest(legacy), worst[0]
    check("the rank face separates ranks better than the 3x5 label face",
          after >= before * 3, f"3x5 {before}px, 5x7 {after}px")
    print(f"        closest pair of ranks: 3x5 face {before}px apart, "
          f"5x7 face {after}px apart ({worst[1]})")


def test_small_cards_drop_the_rank_rather_than_fake_it():
    """Under the size the 5x7 face needs there is no rank, just a lit face.
    A card that small cannot carry a legible character, and a guessed one is
    worse than none -- the suit colour still says red or black."""
    problems = []
    for card_w, card_h in ((7, 9), (8, 11), (10, 14)):
        image = Image.new("RGB", (card_w + 10, card_h + 10), (0, 0, 0))
        br.draw_card(ImageDraw.Draw(image), 5, 5, card_w, card_h,
                     br.Card("8", "S"), True, Theme(), 1.0)
        if br._rank_glyph("8", card_w - 2, card_h - 2) is None:
            problems.append(f"{card_w}x{card_h} should still carry a rank")
    for card_w, card_h in ((5, 7), (6, 8), (4, 6)):
        if br._rank_glyph("8", card_w - 2, card_h - 2) is not None:
            problems.append(f"{card_w}x{card_h} should not try to draw a rank")
        image = Image.new("RGB", (card_w + 10, card_h + 10), (0, 0, 0))
        br.draw_card(ImageDraw.Draw(image), 5, 5, card_w, card_h,
                     br.Card("8", "S"), True, Theme(), 1.0)
        if lit_pixels(image) == 0:
            problems.append(f"{card_w}x{card_h} drew nothing at all")
    check("the rank is dropped, not faked, below the face's size", not problems,
          "; ".join(problems))


def test_text_measure_matches_render():
    """Centring is done from text_width(), so a measurement that disagrees with
    what is drawn puts every banner off-centre."""
    bad = []
    for text in ("BLACKJACK!", "DEALER WINS", "PUSH", "21-17", "W", "!"):
        for scale in (1, 2, 3):
            image = Image.new("RGB", (400, 40), (0, 0, 0))
            br.draw_text(ImageDraw.Draw(image), 5, 5, text, (255, 255, 255), scale)
            box = image.getbbox()
            drawn = box[2] - 5 if box else 0
            measured = br.text_width(text, scale)
            # The measurement includes the trailing edge of the last glyph
            # column; a glyph whose final column is blank is narrower drawn.
            if not 0 <= measured - drawn <= scale:
                bad.append(f"{text}@{scale}: measured {measured}, drew {drawn}")
    check("text_width agrees with what is drawn", not bad, "; ".join(bad))


def test_layout_invariants():
    problems = []
    for width, height in SIZES:
        for dealer_n, player_n in ((2, 2), (2, 5), (5, 2), (7, 8)):
            layout = compute_layout(width, height, dealer_n, player_n)
            dealer, player = layout.seats["dealer"], layout.seats["player"]
            tag = f"{width}x{height}/{dealer_n},{player_n}"

            if (dealer.width, dealer.height) != (player.width, player.height):
                problems.append(f"{tag}: seats differ in size")
            for seat, count in ((dealer, dealer_n), (player, player_n)):
                if seat.card_w < 1 or seat.card_h < 1:
                    problems.append(f"{tag}: {seat.seat} card collapsed")
                last_x = seat.cards_x + (count - 1) * seat.step + seat.card_w
                if seat.cards_x < 0 or last_x > width:
                    problems.append(f"{tag}: {seat.seat} cards {seat.cards_x}..{last_x} outside {width}")
                if seat.cards_y < 0 or seat.cards_y + seat.card_h > height:
                    problems.append(f"{tag}: {seat.seat} cards overflow vertically")
                if seat.show_total and last_x > seat.total_x - 1:
                    problems.append(f"{tag}: {seat.seat} cards reach the totals column")
                if seat.span != (count - 1) * seat.step + seat.card_w:
                    problems.append(f"{tag}: {seat.seat} span disagrees with its slots")
            if dealer.y + dealer.height > player.y:
                if layout.mode != "columns":
                    problems.append(f"{tag}: seats overlap vertically")
    check("layout keeps every card on the panel", not problems,
          "; ".join(problems[:4]))

    check("wide strips split into columns",
          compute_layout(256, 32, 2, 2).mode == "columns"
          and compute_layout(384, 32, 2, 2).mode == "columns")
    check("ordinary panels stack",
          all(compute_layout(w, h, 2, 2).mode == "stacked"
              for w, h in ((64, 32), (128, 32), (128, 64), (256, 128))))


def test_renders_every_beat_on_every_size():
    script, timeline, total = sample_hand()
    samples = beats(timeline, total)
    blank_after_first_card = []
    wrong_size = []
    errors = []

    first_card_settled = timeline[0][0] + 0.5
    for width, height in SIZES:
        layout = compute_layout(width, height, script.dealer_card_count,
                                script.player_card_count)
        for when in samples:
            try:
                image = render(width, height, layout,
                               state_at(script, timeline, when), Theme())
            except Exception as exc:  # noqa: BLE001 - the point of the test
                errors.append(f"{width}x{height}@{when:.2f}: {exc!r}")
                continue
            if image.size != (width, height):
                wrong_size.append(f"{width}x{height}@{when:.2f} -> {image.size}")
            if when >= first_card_settled and lit_pixels(image) == 0:
                blank_after_first_card.append(f"{width}x{height}@{when:.2f}")

    check("no beat crashes on any panel shape", not errors, "; ".join(errors[:3]))
    check("every frame is the declared panel size", not wrong_size,
          "; ".join(wrong_size[:3]))
    check("no blank frame once the first card has landed",
          not blank_after_first_card, "; ".join(blank_after_first_card[:5]))


def test_opening_frame_is_not_empty():
    """The harness renders one frame and treats a blank one as a mode with
    nothing to show. The table chrome has to be on screen from t=0."""
    script, timeline, _ = sample_hand()
    empty = []
    for width, height in SIZES:
        layout = compute_layout(width, height, 2, 2)
        image = render(width, height, layout, state_at(script, timeline, 0.0), Theme())
        if lit_pixels(image) == 0:
            empty.append(f"{width}x{height}")
    check("the empty table still draws something", not empty, ", ".join(empty))


def test_banner_leaves_the_table_visible():
    """The banner explains cards that have to still be on screen to be
    explained. A band that covers the panel is a regression, not a style."""
    too_tall = []
    for text in ("BLACKJACK!", "BUST!", "DEALER WINS", "PUSH", "DEALER BUST"):
        for width, height in SIZES:
            if height < 16:
                continue
            layout = compute_layout(width, height, 2, 3)
            state = ViewState(
                dealer_cards=[], player_cards=[], hole_down=False, hole_flip=1.0,
                banner_text=text, banner_subtext="20-18", banner_tone="win",
                banner_progress=1.0, clock=0.0)
            image = render(width, height, layout, state, Theme())
            # The band is the only thing that reaches the left edge, so rows
            # lit at x=0 are band rows. Counting *any* lit pixel per row would
            # count the dimmed table behind the band -- which is exactly what
            # this test wants to survive.
            band_rows = sum(1 for row in range(height)
                            if image.getpixel((0, row)) != (0, 0, 0))
            if band_rows > height * 0.78:
                too_tall.append(f"{text}@{width}x{height}: {band_rows}/{height}")
    check("the result band leaves room for the table", not too_tall,
          "; ".join(too_tall[:4]))


def test_action_tag_prefers_empty_space():
    """The call is a caption on the hand; drawing it over the hand defeats it.
    On the baseline panel there is room beside the cards, so it goes there."""
    from PIL import ImageChops

    script, timeline, _ = sample_hand()
    layout = compute_layout(128, 32, script.dealer_card_count, script.player_card_count)
    player = layout.seats["player"]
    # Sample a moment when every card is down, so the comparison is against a
    # full table rather than an empty one.
    when = next(start + 0.9 for start, _, event in timeline if event.kind == ACTION)
    base = state_at(script, timeline, when)
    base.action_text = ""
    covered = []
    for text in ("HIT", "STAND", "DOUBLE"):
        tagged = state_at(script, timeline, when)
        tagged.action_text = text
        tagged.action_progress = 0.5
        without = render(128, 32, layout, base, Theme())
        with_tag = render(128, 32, layout, tagged, Theme())
        box = ImageChops.difference(with_tag, without).getbbox()
        if box is None:
            covered.append(f"{text} drew nothing")
        elif box[0] < player.cards_x + player.span:
            covered.append(f"{text} starts at x={box[0]}, cards end at "
                           f"{player.cards_x + player.span}")
    check("the call sits beside the cards, not on them", not covered,
          "; ".join(covered))


def test_flip_never_blanks_the_card():
    """A flip passes through edge-on. At exactly 0.5 the drawn width rounds to
    zero, and an early version drew nothing there -- a one-frame hole."""
    holes = []
    for progress in [index / 40.0 for index in range(41)]:
        image = Image.new("RGB", (40, 40), (0, 0, 0))
        br.draw_card(ImageDraw.Draw(image), 5, 5, 14, 20,
                     br.Card("A", "S"), progress >= 0.5, Theme(),
                     abs(1.0 - 2.0 * progress))
        if lit_pixels(image) == 0:
            holes.append(f"{progress:.3f}")
    check("a card is lit at every point of its flip", not holes, ", ".join(holes))

    # A turning card is narrower than its slot, so the art is planned against
    # the *drawn* width and steps down the ladder as the card closes. Every one
    # of those steps has to land inside the card: the corner index is placed
    # from the right edge and the ace's keyline is drawn a pixel outside its
    # pip, and either would hang over the felt if the plan and the rectangle
    # ever disagreed by a column.
    escapes = []
    for card_w, card_h in ((3, 4), (9, 13), (16, 23), (23, 33), (40, 57)):
        for rank in ("A", "7", "10", "K"):
            for step in range(0, 41, 2):
                squash = step / 40.0
                image = Image.new("RGB", (card_w + 20, card_h + 20), (0, 0, 0))
                br.draw_card(ImageDraw.Draw(image), 10, 10, card_w, card_h,
                             br.Card(rank, "H"), True, Theme(), squash)
                box = image.getbbox()
                if box and (box[0] < 10 or box[1] < 10
                            or box[2] > 10 + card_w or box[3] > 10 + card_h):
                    escapes.append(f"{card_w}x{card_h} {rank} at "
                                   f"{squash:.2f}: {box}")
    check("no card draws outside itself at any point of its flip", not escapes,
          "; ".join(escapes[:4]))


def test_card_art_scales():
    """A mark that fills the card stops reading as a card. Check the ink stays
    a sensible fraction of the face across the size range, for the sparsest
    rank there is and for the densest.

    The floor is low because a pip-count face is *supposed* to be sparse: a
    three of hearts is three small marks on a large empty field, and on the
    biggest card that is 7% of the interior. What the floor is guarding against
    is the card going blank, not the card being quiet -- that the three marks
    are three, and in the right places, is the turned-pip and pip-count tests'
    job. The ceiling is the one doing real work: it is what stops a rank being
    drawn as a lit slab again.
    """
    problems = []
    for rank in ("3", "K"):
        for card_w, card_h in ((7, 9), (10, 14), (15, 21), (23, 33),
                               (35, 49), (48, 68)):
            image = Image.new("RGB", (card_w + 10, card_h + 10), (0, 0, 0))
            br.draw_card(ImageDraw.Draw(image), 5, 5, card_w, card_h,
                         br.Card(rank, "H"), True, Theme(), 1.0)
            region = image.crop((6, 6, 5 + card_w - 1, 5 + card_h - 1))
            # The border is excluded, so what is left is the face: the art and
            # the dark fill.
            lit = sum(1 for pixel in region.getdata() if sum(pixel) > 90)
            fraction = lit / float(region.width * region.height)
            if not 0.05 <= fraction <= 0.55:
                problems.append(f"{rank} at {card_w}x{card_h}: "
                                f"{fraction:.0%} of the face is ink")
            box = image.getbbox()
            if box and (box[0] < 5 or box[1] < 5
                        or box[2] > 5 + card_w or box[3] > 5 + card_h):
                problems.append(f"{rank} at {card_w}x{card_h}: "
                                f"art escapes the card {box}")
    check("card art stays in proportion and inside the card", not problems,
          "; ".join(problems))


def _blobs(image, box):
    """Count 8-connected runs of lit pixels inside ``box``."""
    x0, y0, x1, y1 = box
    lit = {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
           if sum(image.getpixel((x, y))) > 90}
    count = 0
    while lit:
        count += 1
        stack = [lit.pop()]
        while stack:
            px, py = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbour = (px + dx, py + dy)
                    if neighbour in lit:
                        lit.discard(neighbour)
                        stack.append(neighbour)
    return count


def test_pip_cards_show_their_count():
    """The point of the whole sprite tier: a seven is seven marks.

    A count is only a count if the marks are separate, so this is really two
    assertions at once -- that the layout table has the right number of
    entries, and that the pips at this size are far enough apart not to run
    into each other. The second is the one that rots: shave a pixel off a
    margin and a nine becomes a lit lattice that happens to have nine bumps in
    it.

    Counted inside the pip *field* rather than the whole card: every pip-tier
    card now also carries a corner index, and the index's own marks would be
    counted as pips. The field rectangle comes from the plan, so this measures
    exactly the region the pip layout is laid into.
    """
    problems = []
    # Card sizes in the sprite tier. They are all larger than anything the
    # harness renders: the tier now demands 5x5 pips and a double-size index
    # in both corners, which wants a ~41x48 card, so these are synthetic on
    # purpose -- the art is exercised here rather than by a rendered sheet.
    sizes = [(w, h) for w, h in ((41, 48), (46, 66), (52, 72), (60, 80),
                                 (68, 92))
             if br._card_plan(w - 2, h - 2) is not None]
    check("there are pip-tier sizes to measure", len(sizes) >= 3, str(sizes))
    for card_w, card_h in sizes:
        pip, scale, side, top, corners = br._card_plan(card_w - 2, card_h - 2)
        gutter = br.INDEX_W * scale + 1
        right = gutter if corners == 2 else side
        for rank in ("2", "3", "4", "5", "6", "7", "8", "9", "10"):
            image = Image.new("RGB", (card_w + 10, card_h + 10), (0, 0, 0))
            br.draw_card(ImageDraw.Draw(image), 5, 5, card_w, card_h,
                         br.Card(rank, "D"), True, Theme(), 1.0)
            fx = 5 + 1 + gutter
            fy = 5 + 1 + top
            fw = (card_w - 2) - gutter - right
            fh = (card_h - 2) - 2 * top
            found = _blobs(image, (fx, fy, fx + fw - 1, fy + fh - 1))
            if found != int(rank):
                problems.append(f"{card_w}x{card_h} {rank}: {found} pips")
    check("every pip-tier card shows exactly its rank in pips", not problems,
          "; ".join(problems[:6]))


def test_turned_pips_stay_their_own_suit():
    """The lower half of a card is drawn upside down, as on a real card.

    That is only safe where an inverted mark is still its own suit. It is not,
    at the small sizes: an inverted 3x3 spade is the 3x3 club exactly, and an
    inverted 5x5 spade is four pixels from one -- and spade against club is the
    pair ink colour cannot separate, so those four pixels are all there is. The
    turn is therefore restricted by size, and this is the measurement that
    restriction is made of.
    """
    problems = []
    for size, face in br._PIP_FACES:
        turned = size >= 7
        cells = size * size
        for suit, others in (("H", "D"), ("D", "H"), ("S", "C"), ("C", "S")):
            flipped = br._rotate180(face[suit])
            for other in (suit, others):
                differing = sum(1 for row_a, row_b in zip(flipped, face[other])
                                for a, b in zip(row_a, row_b) if a != b)
                # Same bar the upright set is held to: a sixth of the face.
                if turned and differing * 6 < cells and other != suit:
                    problems.append(f"{size}x{size} turned {suit} is "
                                    f"{differing}px from {other}")
    check("a turned pip is only used where it stays its own suit", not problems,
          "; ".join(problems))

    # And the drawing agrees with the arithmetic above rather than merely
    # happening to look right. A two puts one pip in each half of the field, so
    # the lower one is the upper one flipped where the turn is on and the same
    # bitmap where it is off. Every pip is left-right symmetric, so a vertical
    # flip is the whole of the 180 degrees.
    wrong = []
    for pip_size, field_w, field_h in ((3, 11, 15), (5, 17, 23), (7, 23, 31)):
        image = Image.new("RGB", (field_w, field_h), (0, 0, 0))
        br._draw_pip_field(ImageDraw.Draw(image), 0, 0, field_w, field_h,
                           "2", "H", pip_size, (255, 255, 255))
        upper = image.crop((0, 0, field_w, pip_size))
        lower = image.crop((0, field_h - pip_size, field_w, field_h))
        flipped = lower.transpose(Image.FLIP_TOP_BOTTOM)
        turned = list(flipped.getdata()) == list(upper.getdata())
        same = list(lower.getdata()) == list(upper.getdata())
        if (pip_size >= 7) != turned or (pip_size < 7) != same:
            wrong.append(f"{pip_size}x{pip_size}: turned={turned} same={same}")
    check("the lower pip is turned at 7x7 and only there", not wrong,
          "; ".join(wrong))


def test_pips_are_never_drawn_without_an_index():
    """The invariant that replaced "the index only where it is free".

    Buying the index only when it cost the pips nothing meant the two middle
    tiers drew a rank as an uncounted field of specks with no numeral anywhere
    on the card -- on a 128x64 panel a five, a six and a seven were three 3x3
    blobs, four, and five. Counting blobs is not reading. A card that cannot
    afford an index has to fall back to the centred rank instead.
    """
    problems = []
    for inner_w, inner_h in ((12, 19), (14, 21), (18, 26), (21, 31), (26, 38),
                             (38, 55), (46, 66)):
        plan = br._card_plan(inner_w, inner_h)
        if plan is None:
            continue
        pip, index_scale, side, top, corners = plan
        if not index_scale:
            problems.append(f"{inner_w}x{inner_h} draws pips with no index")
        if corners == 2 and 2 * br.INDEX_H * index_scale + 2 > inner_h:
            problems.append(f"{inner_w}x{inner_h} indexes overlap")
        gutter = br.INDEX_W * index_scale + 1
        right = gutter if corners == 2 else side
        if br._pip_for_field(inner_w - gutter - right, inner_h - 2 * top) != pip:
            problems.append(f"{inner_w}x{inner_h} pip does not fit its own field")
    check("a pip field always carries a rank index", not problems,
          "; ".join(problems))

    # The tier's entry bar: 5x5 pips or better and a double-size index in both
    # corners. Everything below it, including every panel the harness renders
    # and every panel this is run on, takes the centred rank instead.
    entry = br._card_plan(39, 46)
    check("the smallest sprite-tier card has 5x5 pips and two big indexes",
          entry is not None and entry[0] >= 5 and entry[1] >= 2 and entry[4] == 2,
          str(entry))
    check("a 3x3 pip field is never reached", all(
        (br._card_plan(w, h) or (5,))[0] >= 5
        for w in range(6, 70) for h in range(8, 100)))
    check("the harness sample never reaches the sprite tier",
          all(br._card_plan(w, h) is None
              for w, h in ((8, 12), (14, 21), (18, 26), (21, 31), (36, 52),
                           (38, 55))))


def test_every_card_states_its_rank():
    """Whatever tier a card lands in, the rank has to be on it somewhere --
    as an index, as a countable pip field, or as the centred numeral."""
    missing = []
    for card_w, card_h in ((10, 14), (13, 18), (16, 23), (20, 28), (23, 33),
                           (30, 43), (40, 57), (48, 68)):
        plan = br._card_plan(card_w - 2, card_h - 2)
        for rank in ("2", "5", "9", "10", "K"):
            image = Image.new("RGB", (card_w + 8, card_h + 8), (0, 0, 0))
            br.draw_card(ImageDraw.Draw(image), 4, 4, card_w, card_h,
                         br.Card(rank, "S"), True, Theme(), 1.0)
            if lit_pixels(image) == 0:
                missing.append(f"{card_w}x{card_h} {rank} drew nothing")
        if plan is None:
            continue
        # In the sprite tier the index is the rank statement, so it must be
        # inside the card and lit.
        _pip, scale, _side, _top, _corners = plan
        if br.INDEX_W * scale > card_w - 2 or br.INDEX_H * scale > card_h - 2:
            missing.append(f"{card_w}x{card_h} index does not fit the card")
    check("every card states its rank at every size", not missing,
          "; ".join(missing))

def test_court_sprites_are_told_apart_by_silhouette():
    """J, Q and K are figures, not letters, and at 11x17 the face inside one is
    five pixels across -- so the outline has to do the work. Compare the
    sprites as filled/empty masks, ignoring the two ink tones, because the
    tones are the first thing to go at scale 1 on a dim panel."""
    problems = []
    ranks = sorted(br._COURT_SPRITES)
    for index, first in enumerate(ranks):
        for second in ranks[index + 1:]:
            a, b = br._COURT_SPRITES[first], br._COURT_SPRITES[second]
            differing = sum(1 for row_a, row_b in zip(a, b)
                            for pixel_a, pixel_b in zip(row_a, row_b)
                            if (pixel_a in br._BLANK_CELLS)
                            != (pixel_b in br._BLANK_CELLS))
            # A tenth of the sprite. The set achieves a fifth at its tightest,
            # so this leaves room to redraw a figure without letting one
            # quietly collapse onto another.
            if differing * 10 < br._COURT_W * br._COURT_H:
                problems.append(f"{first}/{second} silhouettes differ by "
                                f"{differing}px")
    check("no two court figures share a silhouette", not problems,
          "; ".join(problems))
    check("every court sprite is the size it claims",
          all(len(rows) == br._COURT_H
              and all(len(row) == br._COURT_W for row in rows)
              for rows in br._COURT_SPRITES.values()))
    check("court sprites use only the palette the blitter knows",
          not {char for rows in br._COURT_SPRITES.values()
               for row in rows for char in row} - set("#+."))


# ---------------------------------------------------------------------------
# Plugin-level tests (need the LEDMatrix core on the path)
# ---------------------------------------------------------------------------


def test_plugin_drives_a_hand():
    try:
        from src.plugin_system.testing.mocks import (
            MockCacheManager, MockDisplayManager, MockPluginManager)
        from manager import BlackjackPlugin
    except ImportError as exc:
        print(f"  SKIP  plugin-level tests (LEDMatrix core not importable: {exc})")
        return

    config = {"random_seed": 4242, "card_interval": 2.0, "result_seconds": 4.0}
    display = MockDisplayManager(128, 32)
    plugin = BlackjackPlugin("blackjack", config, display, MockCacheManager(),
                             MockPluginManager())

    check("high-FPS is declared", plugin.needs_high_fps is True)
    check("dynamic duration is on by default", plugin.supports_dynamic_duration())

    plugin.reset_cycle_state()
    first = plugin._script
    check("reset_cycle_state deals a hand", first is not None)
    check("a hand is not complete the moment it starts", not plugin.is_cycle_complete())

    plugin.display(force_clear=True)
    check("the force_clear frame after a reset keeps the same hand",
          plugin._script is first)
    check("display pushed a frame", display.update_called)
    check("the pushed frame is panel sized", display.image.size == (128, 32))
    check("get_cycle_duration matches the hand",
          abs(plugin.get_cycle_duration() - plugin._total_duration) < 1e-6)
    check("get_display_duration matches the hand",
          abs(plugin.get_display_duration() - plugin._total_duration) < 1e-6)

    total = plugin._total_duration
    lit_at = {}
    for fraction in [index / 24.0 for index in range(25)]:
        plugin._hand_started = time.monotonic() - total * fraction
        plugin._last_render = 0.0
        plugin.display(force_clear=False)
        lit_at[round(fraction, 3)] = lit_pixels(display.image)
        if display.image.size != (128, 32):
            check("frame size held through the hand", False, str(display.image.size))
            return
    check("every frame through the hand has content",
          all(count > 0 for count in lit_at.values()),
          str({k: v for k, v in lit_at.items() if v == 0}))
    check("the hand still shows the same script", plugin._script is first)

    plugin._hand_started = time.monotonic() - (total + 0.01)
    check("the hand reports complete once its time is up", plugin.is_cycle_complete())
    plugin._last_render = 0.0
    plugin.display(force_clear=False)
    check("a finished hand holds its banner instead of dealing again",
          plugin._script is first)

    # A rotation that leaves and comes back gets a new hand.
    plugin._last_display = time.monotonic() - 30.0
    plugin._last_render = 0.0
    plugin.display(force_clear=True)
    check("coming back from the rotation deals a new hand", plugin._script is not first)

    # The frame-rate throttle must hold the frame, not drop it.
    plugin._last_render = time.monotonic()
    display.update_called = False
    result = plugin.display(force_clear=False)
    check("a throttled frame returns True without pushing",
          result is True and not display.update_called)

    # Fixed-duration installs loop instead of freezing on the banner.
    fixed = BlackjackPlugin("blackjack", dict(config, dynamic_duration={"enabled": False}),
                            MockDisplayManager(64, 32), MockCacheManager(),
                            MockPluginManager())
    fixed.display(force_clear=True)
    looped = fixed._script
    fixed._hand_started = time.monotonic() - (fixed._total_duration + 1.0)
    fixed._last_render = 0.0
    fixed.display(force_clear=False)
    check("a fixed-duration slot deals another hand rather than freezing",
          fixed._script is not looped)

    # A bad config value must not reach the progress arithmetic.
    hostile = BlackjackPlugin("blackjack", {"card_interval": 0, "result_seconds": "x",
                                            "decks": 99, "card_style": "chrome",
                                            "dealer_color": "red"},
                              MockDisplayManager(128, 64), MockCacheManager(),
                              MockPluginManager())
    hostile.display(force_clear=True)
    check("nonsense config falls back instead of dividing by zero",
          hostile.card_interval == 2.0 and hostile.result_seconds == 4.0
          and hostile.rules.decks == 8 and hostile.theme.card_style == "outline")
    check("validate_config rejects what it should",
          not hostile.validate_config())


def test_plugin_renders_every_size():
    try:
        from src.plugin_system.testing.mocks import (
            MockCacheManager, MockDisplayManager, MockPluginManager)
        from manager import BlackjackPlugin
    except ImportError:
        return

    bad = []
    for width, height in SIZES:
        display = MockDisplayManager(width, height)
        plugin = BlackjackPlugin("blackjack", {"random_seed": 7}, display,
                                 MockCacheManager(), MockPluginManager())
        plugin.display(force_clear=True)
        total = plugin._total_duration
        for fraction in (0.0, 0.25, 0.5, 0.75, 0.95, 1.0):
            plugin._hand_started = time.monotonic() - total * fraction
            plugin._last_render = 0.0
            try:
                plugin.display(force_clear=False)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{width}x{height}@{fraction}: {exc!r}")
                break
            if display.image.size != (width, height):
                bad.append(f"{width}x{height}@{fraction} -> {display.image.size}")
                break
    check("the plugin renders a full hand on every panel shape", not bad,
          "; ".join(bad[:3]))


def main():
    for test in (test_font_covers_every_string, test_rank_glyphs_are_distinguishable,
                 test_same_colour_pips_are_distinguishable,
                 test_pip_cards_show_their_count,
                 test_turned_pips_stay_their_own_suit,
                 test_pips_are_never_drawn_without_an_index,
                 test_every_card_states_its_rank,
                 test_court_sprites_are_told_apart_by_silhouette,
                 test_small_cards_drop_the_rank_rather_than_fake_it,
                 test_text_measure_matches_render,
                 test_layout_invariants, test_renders_every_beat_on_every_size,
                 test_opening_frame_is_not_empty, test_banner_leaves_the_table_visible,
                 test_action_tag_prefers_empty_space, test_flip_never_blanks_the_card,
                 test_card_art_scales, test_plugin_drives_a_hand,
                 test_plugin_renders_every_size):
        print(test.__name__)
        test()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): " + ", ".join(FAILURES))
        return 1
    print("\nall render checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
