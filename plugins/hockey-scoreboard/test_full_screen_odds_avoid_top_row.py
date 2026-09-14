#!/usr/bin/env python3
"""Full-screen odds must not overprint the top-centre status text.

_draw_dynamic_odds centred "O/U: 5.5" on row 0 whenever there was no
favourite, the same row every scorebug centres the period and clock, "Final"
or "Next Game" on. The scroll/Vegas renderer already anchored left and stepped
down a row on collision; the full-screen copy never got that. Two smaller
differences came along: a home spread of 0.0 (a pick'em) was treated as
missing and replaced by the top-level spread, and that spread was negated
without a number check, so a malformed payload raised and drew nothing.

Exercised against a stand-in ``self`` that records every text draw.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_full_screen_odds_avoid_top_row.py
"""

import logging
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    import sports  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import sports.py (%s)" % exc)
    sys.exit(2)

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Scorebug:
    _draw_dynamic_odds = sports.SportsCore._draw_dynamic_odds
    _odds_would_hit_top_row = staticmethod(sports.SportsCore._odds_would_hit_top_row)
    _top_row_span = staticmethod(sports.SportsCore._top_row_span)

    def __init__(self):
        self.logger = logging.getLogger("odds_probe")
        font = ImageFont.load_default()
        self.fonts = {"odds": font, "detail": font, "time": font}
        self.drawn = []

    def _odds_color(self):
        return (0, 255, 0)

    def _draw_text_with_outline(self, draw, text, position, font, fill=None, **_):
        self.drawn.append((text, position))


def _render(odds, width, status_text="Final"):
    bug = _Scorebug()
    img = Image.new("RGB", (width, 32))
    draw = ImageDraw.Draw(img)
    span = bug._top_row_span(draw, status_text, bug.fonts["time"], width)
    bug._draw_dynamic_odds(draw, odds, width, 32, top_span=span)
    return bug, draw, span


def _overlaps(bug, draw, span):
    font = bug.fonts["odds"]
    text_h = draw.textbbox((0, 0), "A", font=font)[3]
    hits = []
    for text, (x, y) in bug.drawn:
        w = draw.textlength(text, font=font)
        same_row = y < text_h
        if same_row and x < span[1] + 1 and x + w > span[0] - 1:
            hits.append((text, x, y))
    return hits


def main():
    ou_only = {"over_under": 5.5, "home_team_odds": {}, "away_team_odds": {}}

    print("O/U with no favourite on a narrow panel")
    bug, draw, span = _render(ou_only, 64)
    check("the O/U is drawn", any(t.startswith("O/U") for t, _ in bug.drawn), bug.drawn)
    check("it does not overprint 'Final'", not _overlaps(bug, draw, span), bug.drawn)

    print("\nthe same odds on a wide panel stay on the top row")
    bug, draw, span = _render(ou_only, 192)
    check("drawn at y=0", [p[1] for _, p in bug.drawn] == [0], bug.drawn)
    check("no overlap", not _overlaps(bug, draw, span), bug.drawn)

    print("\nlive period and clock text on a narrow panel")
    bug, draw, span = _render(ou_only, 64, status_text="P2 12:34")
    check("no overlap with the period/clock", not _overlaps(bug, draw, span), bug.drawn)

    print("\na home spread of 0.0 is a pick'em, not missing")
    pickem = {"spread": -1.5, "over_under": 5.5,
              "home_team_odds": {"spread_odds": 0.0}, "away_team_odds": {}}
    bug, _draw, _span = _render(pickem, 192)
    check("the top-level -1.5 is not drawn over the pick'em",
          not any(t == "-1.5" for t, _ in bug.drawn), bug.drawn)

    print("\na non-numeric top-level spread does not abort the draw")
    bad = {"spread": "n/a", "over_under": 5.5,
           "home_team_odds": {"spread_odds": -1.5}, "away_team_odds": {}}
    bug, _draw, _span = _render(bad, 192)
    check("the O/U is still drawn", any(t.startswith("O/U") for t, _ in bug.drawn), bug.drawn)
    check("the home spread is still drawn", any(t == "-1.5" for t, _ in bug.drawn), bug.drawn)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
