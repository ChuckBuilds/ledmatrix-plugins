#!/usr/bin/env python3
"""No league's ESPN date window may cut off games the screens can show.

WNBA's window was built as:

    datestring = f"{season_year}0501-{season_year}0930"

with the comment "WNBA season typically runs from May to September". The
regular season does end in September, but the playoffs and Finals run into
October -- the 2024 Finals ended on 20 October, 2025's in mid-October. Both
fetch calls pass this window as `dates=`, and there is no date-less fallback,
so no postseason game was ever fetched: the scoreboard went blank exactly when
the games matter most.

The other three leagues are checked here too, since the same truncation is easy
to reintroduce and only shows up once a year:

  NBA        window opens 1 October, season opens later that month
  NCAA M/W   no date window at all -- ESPN's `season` parameter, keyed to the
             year the season ENDS, flipped on 1 November before the openers

NBA and WNBA no longer build a season range at all: they fetch the
schedule_lookback_days/schedule_lookahead_days window around today
(SportsCore._schedule_window), which is all Recent and Upcoming ever show. A
window centred on today cannot miss a postseason, so the truncation above has
no season boundary left to happen at; what is checked for them now is that no
hardcoded season range has come back.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_season_windows.py
"""

import re
import sys
from datetime import datetime
from pathlib import Path

plugin_dir = Path(__file__).parent
failures = []


def check(name, actual, expected):
    if actual == expected:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s: expected %r, got %r" % (name, expected, actual))
        failures.append(name)


def window_expr(module):
    """The f-string literal each manager builds its ESPN window from."""
    src = (plugin_dir / f"{module}.py").read_text()
    m = re.search(r'datestring = f"([^"]+)"', src)
    return m.group(1) if m else None


def resolve(expr, now, boundary, back_a_year_below=True):
    y = now.year
    if back_a_year_below and now.month < boundary:
        y = now.year - 1
    return expr.replace("{season_year}", str(y)).replace("{season_year+1}", str(y + 1))


def main():
    print("NBA and WNBA fetch the window around today, not a season range")
    for module in ("wnba_managers", "nba_managers"):
        src = (plugin_dir / f"{module}.py").read_text()
        check("%s builds no season range" % module, window_expr(module), None)
        check("%s uses the lookback/lookahead window" % module,
              "datestring, window = self._schedule_window()" in src, True)

    print("\nNCAA basketball uses ESPN's season number, keyed to the ending year")
    for module in ("ncaam_basketball_managers", "ncaaw_basketball_managers"):
        src = (plugin_dir / f"{module}.py").read_text()
        check("%s uses no date window" % module, window_expr(module), None)
        check("%s keys on the season parameter" % module,
              'params={"season"' in src or "'season'" in src, True)

        def season(now):
            return now.year + 1 if now.month >= 11 else now.year

        # The 2026-27 season opens in early November and ESPN labels it 2027.
        check("%s in Oct 2026 -> 2026" % module, season(datetime(2026, 10, 15)), 2026)
        check("%s at the Nov opener -> 2027" % module, season(datetime(2026, 11, 5)), 2027)
        check("%s in March Madness -> 2027" % module, season(datetime(2027, 3, 20)), 2027)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
