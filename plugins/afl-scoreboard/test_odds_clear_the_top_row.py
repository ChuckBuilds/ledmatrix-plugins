#!/usr/bin/env python3
"""Full-screen odds must not print through the text centred on the top row.

SportsCore._draw_dynamic_odds centred the over/under at y=0 whenever there was
no favoured side -- the row every full-screen card centres its own text on:
the period and clock on live, "Final" on recent, the league header on
upcoming. A game priced with a total and no spread therefore drew "O/U: 170.5"
straight through that text. The scroll renderer (game_renderer) was fixed
long ago; this is the same rule on the full-screen path: anchor left, and step
down a row when the labels would still overlap the centred text.

Also pinned, from the same audit:

  * a home spread of 0.0 is a real (pick'em) line, not "missing";
  * a non-numeric top-level spread is not negated (that raised TypeError,
    which the surrounding except swallowed, dropping the total as well).

Run: <core-venv>/bin/python plugins/afl-scoreboard/test_odds_clear_the_top_row.py
"""

import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    if not any((Path(p) / 'src' / 'common').is_dir() for p in sys.path if p):
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        sys.exit(2)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(2)

import sports  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Logger:
    """Quiet, except that a swallowed exception fails the test.

    _draw_dynamic_odds wraps everything in try/except and logs; without this
    a broken stand-in draws nothing and a "not drawn" check passes vacuously.
    """

    def __init__(self):
        self.errors = []

    def error(self, *a, **k):
        self.errors.append(a)

    exception = error

    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Card:
    _draw_dynamic_odds = sports.SportsCore._draw_dynamic_odds
    _odds_would_hit_top_row = staticmethod(sports.SportsCore._odds_would_hit_top_row)

    def __init__(self):
        font = ImageFont.load_default()
        self.fonts = {"detail": font, "odds": font}
        self.logger = _Logger()
        self.drawn = []

    def _odds_color(self):
        return (0, 255, 0)

    def _draw_text_with_outline(self, draw, text, xy, font, fill=None):
        self.drawn.append((text, xy))


def draw_odds(odds, width, top_span):
    card = _Card()
    draw = ImageDraw.Draw(Image.new("RGB", (width, 32)))
    card._draw_dynamic_odds(draw, odds, width, 32, top_span=top_span)
    check("no error swallowed drawing %r" % (odds,), not card.logger.errors,
          card.logger.errors)
    return card.drawn, draw, card.fonts["odds"]


def _span(draw, font, text, width):
    w = draw.textlength(text, font=font)
    x = (width - w) // 2
    return (x, x + w)


def main():
    width = 64
    probe_draw = ImageDraw.Draw(Image.new("RGB", (width, 32)))
    font = ImageFont.load_default()
    final_span = _span(probe_draw, font, "Final", width)

    print("a total with no spread on a narrow card")
    drawn, _, _ = draw_odds({"over_under": 170.5}, width, final_span)
    ou = [xy for t, xy in drawn if t.startswith("O/U")]
    check("the total is drawn", len(ou) == 1, drawn)
    if ou:
        x, y = ou[0]
        check("anchored to the left edge, not centred", x == 0, x)
        check("stepped below the top row it would overprint", y > 0, y)

    print("\nroom to spare: nothing moves down")
    wide = 192
    wide_draw = ImageDraw.Draw(Image.new("RGB", (wide, 32)))
    drawn, _, _ = draw_odds({"over_under": 7.5}, wide,
                            _span(wide_draw, font, "Final", wide))
    ou = [xy for t, xy in drawn if t.startswith("O/U")]
    check("the total stays on the top row", ou and ou[0][1] == 0, ou)
    check("at the left edge", ou and ou[0][0] == 0, ou)

    print("\nno centred text: top row, left edge")
    drawn, _, _ = draw_odds({"over_under": 170.5}, width, None)
    check("drawn at (0, 0)", [xy for t, xy in drawn] == [(0, 0)], drawn)

    print("\na pick'em home spread of 0.0 is a real line")
    drawn, _, _ = draw_odds({
        "spread": -3.5, "over_under": 150.5,
        "home_team_odds": {"spread_odds": 0.0},
        "away_team_odds": {"spread_odds": 0.0},
    }, wide, None)
    texts = [t for t, _ in drawn]
    check("the top-level -3.5 does not overwrite it", "-3.5" not in texts, texts)
    check("the total still draws", any(t.startswith("O/U") for t in texts), texts)

    print("\na non-numeric top-level spread")
    drawn, _, _ = draw_odds({"spread": "EVEN", "over_under": 150.5,
                             "home_team_odds": {}, "away_team_odds": {}},
                            wide, None)
    check("the total is not lost to a TypeError",
          any(t.startswith("O/U") for t, _ in drawn), drawn)

    print("\nthe ordinary favourite case is unchanged")
    drawn, _, _ = draw_odds({
        "spread": -12.5, "over_under": 160.5,
        "home_team_odds": {"spread_odds": -12.5},
        "away_team_odds": {"spread_odds": 12.5},
    }, wide, _span(wide_draw, font, "Q2 10:00", wide))
    positions = dict(drawn)
    check("home favourite's spread on the right, top row",
          "-12.5" in positions and positions["-12.5"][0] > wide // 2
          and positions["-12.5"][1] == 0, positions)
    check("total on the left, top row",
          positions.get("O/U: 160.5") == (0, 0), positions)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
