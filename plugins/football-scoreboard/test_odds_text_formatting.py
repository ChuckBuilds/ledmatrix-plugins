#!/usr/bin/env python3
"""
Tests that odds strings render whole numbers without a trailing ".0".

ESPN sends spreads as floats, so a 7-point line arrived as -7.0 and drew
as "-7.0" beside cards saying "-3.5" and "-46.5" -- three styles of the
same stat on one rotation. Whole numbers now drop the ".0" (spread and
over/under alike); halves keep their .5.

Exercised against a stand-in ``self`` whose _draw_text_with_outline is a
recorder: no display hardware, no fonts, no network.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_odds_text_formatting.py
"""

import logging
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


class _Draw:
    @staticmethod
    def textlength(text, font=None):
        return 4 * len(text)


class _Manager:
    _draw_dynamic_odds = sports.SportsCore._draw_dynamic_odds
    # Borrowed for the same reason as the method above: _draw_dynamic_odds now
    # asks for the odds colour, and this probe deliberately carries only the
    # surface that method needs. Stubbing it instead would let the real
    # resolution regress unnoticed.
    _odds_color = sports.SportsCore._odds_color

    def __init__(self):
        self.fonts = {"detail": object()}
        self.logger = logging.getLogger("odds_format_probe")
        self.drawn = []

    def _draw_text_with_outline(self, draw, text, position, font, fill=None):
        self.drawn.append(text)

    def _get_layout_offset(self, element, axis):
        return 0


failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _render(spread, over_under):
    mgr = _Manager()
    mgr._draw_dynamic_odds(_Draw(), {
        "spread": spread,
        "over_under": over_under,
        "home_team_odds": {"spread_odds": None},
        "away_team_odds": {"spread_odds": None},
    }, 256, 64)
    return mgr.drawn


def main():
    print("a whole-number line drops the trailing .0")
    drawn = _render(spread=-7.0, over_under=58.0)
    check("spread renders as -7", "-7" in drawn, drawn)
    check("no -7.0 anywhere", not any(t.endswith(".0") and t.startswith("-7") for t in drawn), drawn)
    check("over/under renders as O/U: 58", "O/U: 58" in drawn, drawn)

    print("\nhalves keep their .5")
    drawn = _render(spread=-46.5, over_under=56.5)
    check("spread renders as -46.5", "-46.5" in drawn, drawn)
    check("over/under renders as O/U: 56.5", "O/U: 56.5" in drawn, drawn)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
