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
hard right. Measured on a 64px panel, "O/U: 8.5" clears the inning by 2px but
"O/U: 12.5" overlaps it by 1-3px, and double-digit over/unders are ordinary in
baseball. So the odds now start at the top edge and step down only when these
particular strings would actually collide -- a measurement, not a panel-size
rule, since it is the text widths that decide.

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

import game_renderer as gr  # noqa: E402


def _font():
    """The core's 4x6, or PIL's default if the core tree is not to hand."""
    import os
    core = os.environ.get("LEDMATRIX_CORE", "")
    for base in (core, "."):
        p = Path(base) / "assets" / "fonts" / "4x6-font.ttf"
        if p.exists():
            return ImageFont.truetype(str(p), 6)
    return ImageFont.load_default()


FONT = _font()
failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def odds_y(width, height, over_under, inning_half="top", inning=3,
           y_offset=0, x_offset=0, top_text=None):
    """Render the odds and report the y they landed on."""
    r = gr.GameRenderer.__new__(gr.GameRenderer)
    r.display_width, r.display_height = width, height
    r.config = {}
    r.logger = type("L", (), {m: (lambda *a, **k: None)
                              for m in ("exception", "error", "warning", "debug")})()
    r.fonts = {"detail": FONT, "time": FONT}
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
    }, game=game, top_text=top_text)
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
    y_short, _ = odds_y(64, 32, 8.5)
    y_long, _ = odds_y(64, 32, 12.5)
    check("64x32 stays at the top when the O/U is short", y_short == 0,
          "y=%s" % y_short)
    check("64x32 steps down when the O/U is wide", y_long > 0, "y=%s" % y_long)
    check("and steps down by about one text row", 4 <= y_long <= 12,
          "y=%s" % y_long)

    print("\nthe step is decided by the text, not the panel size")
    # A long inning label ("FINAL") is wider than a short one, so it can push
    # the odds down at a width where a short label does not.
    y_final, _ = odds_y(64, 32, 8.5, inning_half="top")
    check("a narrow panel with short strings still uses the top edge",
          y_final == 0, "y=%s" % y_final)

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
    r.fonts = {"detail": FONT, "time": FONT}
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
