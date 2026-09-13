#!/usr/bin/env python3
"""Full-screen odds must not print through the scorebug's top-centre text.

With an over/under and no favourite, _draw_dynamic_odds centred "O/U: 47.5" at
y=0 -- the row holding "Final", the clock and "Next Game". The scroll card
renderer already anchors it left and steps the odds down a row when a label
would still overlap; this pins the same rule on the classic scorebug. Also
covers the two spread-parsing slips beside it: a home spread of 0.0 (a
pick'em) was treated as missing, and a non-numeric top-level spread was
negated, which raised and dropped the whole odds row.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_full_screen_odds_clear_top_row.py
"""
import inspect
import logging
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
logging.disable(logging.CRITICAL)

try:
    import sports  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import sports.py (%s)" % exc)
    sys.exit(2)

CHAR_W, CHAR_H = 4, 6


class _Draw:
    @staticmethod
    def textlength(text, font=None):
        return CHAR_W * len(text)

    @staticmethod
    def textbbox(xy, text, font=None):
        return (xy[0], xy[1], xy[0] + CHAR_W * len(text), xy[1] + CHAR_H)


class _Manager:
    _draw_dynamic_odds = sports.SportsCore._draw_dynamic_odds
    _odds_color = sports.SportsCore._odds_color

    def __init__(self):
        self.fonts = {"detail": object()}
        self.logger = logging.getLogger("odds_top_row_probe")
        self.drawn = []

    def _draw_text_with_outline(self, draw, text, position, font, fill=None):
        self.drawn.append((text, position))

    def _get_layout_offset(self, element, axis, default=0):
        return 0


failures = []


def check(name, ok, detail=None):
    print("  [%s] %s%s" % ("pass" if ok else "FAIL", name,
                           "" if ok or detail is None else "  <- %r" % (detail,)))
    if not ok:
        failures.append(name)


def _draw(odds, width, **kw):
    m = _Manager()
    m._draw_dynamic_odds(_Draw(), odds, width, 32, **kw)
    return m.drawn


def main():
    if "top_span" not in inspect.signature(sports.SportsCore._draw_dynamic_odds).parameters:
        check("_draw_dynamic_odds accepts the top-row span", False)
        return 1

    # O/U only, narrow panel, "Final" centred on the top row.
    width = 64
    final = (width - CHAR_W * 5) // 2
    drawn = _draw({"over_under": 47.5}, width, top_span=(final, final + CHAR_W * 5))
    ou = [p for t, p in drawn if t.startswith("O/U")]
    check("O/U is drawn", bool(ou), drawn)
    if ou:
        x, y = ou[0]
        check("O/U is not centred on the status text", x == 0, ou[0])
        check("O/U steps below the top row when it would overlap", y > 0, ou[0])

    # Wide panel: the left-anchored label never reaches the centre -> row 0.
    width = 192
    status = (width - CHAR_W * 5) // 2
    drawn = _draw({"over_under": 47.5}, width, top_span=(status, status + CHAR_W * 5))
    check("no collision keeps the odds on the top row",
          [p for t, p in drawn if t.startswith("O/U")] == [(0, 0)], drawn)

    # A home pick'em (0.0) is a real value, not a missing one.
    drawn = _draw({"spread": -3.0,
                   "home_team_odds": {"spread_odds": 0.0},
                   "away_team_odds": {"spread_odds": 0.0}}, 128)
    check("home spread 0.0 is not replaced by the top-level spread",
          not any(t == "-3" for t, _ in drawn), drawn)

    # A non-numeric top-level spread must not take the O/U down with it.
    drawn = _draw({"spread": "EVEN", "over_under": 41.0}, 128)
    check("non-numeric spread still draws the over/under",
          any(t.startswith("O/U") for t, _ in drawn), drawn)

    print("\n%d failed" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
