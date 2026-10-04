#!/usr/bin/env python3
"""Tests where the odds text sits on a baseball scroll card.

Two things are under test.

Odds used to be drawn a whole text row below the top -- `status_bbox[3] + 2`,
which measures 8px with the 4x6 font and 10px with PressStart2P -- while every
other scoreboard drew them at the top edge. On a 32px card that put the same
element a third of the card lower on baseball than on football, basketball,
soccer, afl, nrl and ufc, which is what "too low on some sports" looked like.

The row existed for a reason, though: baseball is the only scoreboard with
text centred on that row (the inning), and the odds are drawn hard left and
hard right. With the card's default fonts on a 64px panel, the inning spans
x=24-40; a spread alone (15px, at an edge) clears it, but any "O/U: ..."
(30px and up) reaches it. So the odds now start at the top edge and step down
only when these particular strings would actually collide -- a measurement,
not a panel-size rule, since it is the text widths that decide.

Measured with the card's default fonts, at sizes on their pixel grid (4x6 at
7, PressStart2P at 8). Off the grid, Pillow's two layout engines disagree:
Raqm (the Linux wheels, so CI and the Pi) keeps fractional advances while the
basic engine (the Windows wheel ships without it) rounds each one. These tests
once used 4x6 at 6, where "O/U: 8.5" measures 25.7px on the Pi and 30px on
Windows -- so the same checks passed in CI and failed on a Windows checkout.
On the grid both engines give whole pixels and agree.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_odds_placement.py
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(2)


def _core_font(name, size):
    """A font the core ships, or None if the core tree is not to hand."""
    import os
    core = os.environ.get("LEDMATRIX_CORE", "")
    for base in (core, "."):
        p = Path(base) / "assets" / "fonts" / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return None


# The card's defaults: odds (and detail) in 4x6 at 7; the inning, "Final" and
# the upcoming time in PressStart2P at 8.
ODDS_FONT = _core_font("4x6-font.ttf", 7)
TIME_FONT = _core_font("PressStart2P-Regular.ttf", 8)
if ODDS_FONT is None or TIME_FONT is None:
    # PIL's default font has other widths, and they change between Pillow
    # versions, so every expectation below would be measuring something else.
    print("SKIP: the core's fonts were not found (set LEDMATRIX_CORE)")
    sys.exit(2)

import game_renderer as gr  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def odds_y(width, height, over_under, inning_half="top", inning=3,
           y_offset=0, x_offset=0, top_text=None, top_font=None,
           top_x_offset=0):
    """Render the odds and report the y they landed on."""
    r = gr.GameRenderer.__new__(gr.GameRenderer)
    r.display_width, r.display_height = width, height
    r.config = {}
    r.logger = type("L", (), {m: (lambda *a, **k: None)
                              for m in ("exception", "error", "warning", "debug")})()
    r.fonts = {"detail": ODDS_FONT, "odds": ODDS_FONT, "time": TIME_FONT}
    r._get_layout_offset = lambda e, a, default=0: (
        y_offset if a == "y_offset" else x_offset)
    drawn = []
    r._draw_text_with_outline = (
        lambda draw, t, xy, font, fill=None: drawn.append((t, xy[0], xy[1])))
    draw = ImageDraw.Draw(Image.new("RGB", (width, height)))
    game = {"inning_half": inning_half, "inning": inning}
    r._draw_dynamic_odds(draw, {
        "spread": -1.5, "over_under": over_under,
        "home_team_odds": {"spread_odds": -1.5},
        "away_team_odds": {"spread_odds": 1.5},
    }, game=game, **({} if top_text is None else {'top_span':
        r._top_row_span(draw, top_text, top_font or TIME_FONT, top_x_offset)}))
    if not drawn:
        return None, drawn
    return max(y for _t, _x, y in drawn), drawn


def main():
    print("odds sit at the top edge, like every other scoreboard")
    for w, h in ((128, 32), (128, 64), (256, 64), (512, 64)):
        y, _ = odds_y(w, h, 8.5)
        check("%dx%d top edge" % (w, h), y == 0, "y=%s" % y)
        y, _ = odds_y(w, h, 12.5)
        check("%dx%d top edge with a two-digit O/U" % (w, h), y == 0, "y=%s" % y)

    print("\nexcept where they would actually hit the centred inning text")
    # On 64px the inning spans x=24-40. The spread alone sits at x=49-64 and
    # clears it; "O/U: 8.5" sits at x=0-30 and does not.
    y_spread, _ = odds_y(64, 32, None)
    y_short, _ = odds_y(64, 32, 8.5)
    y_long, _ = odds_y(64, 32, 12.5)
    check("64x32 stays at the top when only the spread is drawn",
          y_spread == 0, "y=%s" % y_spread)
    check("64x32 steps down when an O/U is drawn", y_short > 0,
          "y=%s" % y_short)
    check("and when the O/U is wide", y_long > 0, "y=%s" % y_long)
    check("and steps down by about one text row", 4 <= y_long <= 12,
          "y=%s" % y_long)

    print("\nthe step is decided by the text, not the panel size")
    # Same panel, same odds: the spread clears the inning (16px wide) but not
    # a recent card's "Final" (40px, x=12-52), so only the latter moves it.
    y_inning, _ = odds_y(64, 32, None)
    y_final, _ = odds_y(64, 32, None, top_text="Final")
    check("a narrow panel with short strings still uses the top edge",
          y_inning == 0, "y=%s" % y_inning)
    check("but the same strings step down beside a wider top row",
          y_final > 0, "y=%s" % y_final)

    print("\neach card type is measured against the text it actually draws")
    # _draw_dynamic_odds is called from the live, recent and upcoming
    # renderers, and they do not centre the same string on the top row: the
    # inning, "Final", and a time or date respectively. Measuring the inning
    # for all three checked a string that was not on the panel.
    y_live, _ = odds_y(64, 32, 12.5)
    y_final, _ = odds_y(64, 32, 12.5, top_text="Final")
    check("a wide O/U still steps down beside the inning", y_live > 0,
          "y=%s" % y_live)
    check("and beside a recent card's 'Final'", y_final > 0, "y=%s" % y_final)

    y_time, _ = odds_y(64, 32, 12.5, top_text="7:05 PM")
    check("and beside an upcoming card's time", y_time > 0, "y=%s" % y_time)

    # Nothing centred on the top row means nothing to avoid.
    y_clear, _ = odds_y(64, 32, 12.5, top_text="")
    check("but an empty top row leaves the odds at the edge", y_clear == 0,
          "y=%s" % y_clear)

    # A wide panel has room beside any of them.
    for label, t in (("inning", None), ("Final", "Final"), ("time", "7:05 PM")):
        y, _ = odds_y(256, 64, 12.5, top_text=t)
        check("256x64 clears the %s" % label, y == 0, "y=%s" % y)

    print("\nthe span is measured with the font and offset actually used")
    # An upcoming card with swap_date_time draws the date in `detail`, not
    # `time`, and shifts it by that element's x_offset. Measuring a centred
    # `time` string instead can both miss a real overlap and invent one.
    r = gr.GameRenderer.__new__(gr.GameRenderer)
    r.display_width, r.display_height = 128, 32
    d = ImageDraw.Draw(Image.new("RGB", (128, 32)))

    small = r._top_row_span(d, "Sep 19", ODDS_FONT)
    big = r._top_row_span(d, "Sep 19", _core_font("4x6-font.ttf", 14))
    check("a wider font gives a wider span",
          (big[1] - big[0]) > (small[1] - small[0]),
          "%r vs %r" % (big, small))
    # Within a couple of pixels: the width can be fractional and both ends are
    # truncated to int, so the midpoint can sit just under centre.
    check("and both stay centred", abs((small[0] + small[1]) - 128) <= 2
          and abs((big[0] + big[1]) - 128) <= 2, "%r %r" % (small, big))

    shifted = r._top_row_span(d, "Sep 19", ODDS_FONT, x_offset=-20)
    check("an x_offset moves the span with the text",
          shifted[0] == small[0] - 20 and shifted[1] == small[1] - 20,
          "%r vs %r" % (shifted, small))

    check("an empty top row has no span",
          r._top_row_span(d, "", ODDS_FONT) is None)

    print("\nthe manual offsets still apply")
    y0, _ = odds_y(256, 64, 8.5)
    y5, _ = odds_y(256, 64, 8.5, y_offset=5)
    check("y_offset moves it", y5 == y0 + 5, "%s vs %s" % (y5, y0))
    _, drawn0 = odds_y(256, 64, 8.5)
    _, drawn7 = odds_y(256, 64, 8.5, x_offset=7)
    check("x_offset moves it",
          all(b[1] - a[1] == 7 for a, b in zip(drawn0, drawn7)),
          "%r vs %r" % ([d[1] for d in drawn0], [d[1] for d in drawn7]))

    print("\nnothing is drawn when there are no odds to draw")
    r = gr.GameRenderer.__new__(gr.GameRenderer)
    r.display_width = r.display_height = 64
    r.config = {}
    r.logger = type("L", (), {m: (lambda *a, **k: None)
                              for m in ("exception", "error", "warning", "debug")})()
    r.fonts = {"detail": ODDS_FONT, "odds": ODDS_FONT, "time": TIME_FONT}
    r._get_layout_offset = lambda e, a, default=0: 0
    got = []
    r._draw_text_with_outline = lambda *a, **k: got.append(a)
    r._draw_dynamic_odds(ImageDraw.Draw(Image.new("RGB", (64, 64))), {}, game={})
    check("empty odds draw nothing", not got, "%d draws" % len(got))

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
