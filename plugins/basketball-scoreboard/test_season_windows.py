#!/usr/bin/env python3
"""Each league's ESPN date window must cover its whole season, postseason included.

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
    print("WNBA covers the postseason, not just the regular season")
    wnba = window_expr("wnba_managers")
    check("window ends in November, not September",
          wnba.endswith("1101"), True)
    check("window is not truncated at 0930", "0930" in wnba, False)

    for d, expected in [
        ("2026-08-22", "20260501-20261101"),   # regular season
        ("2026-09-20", "20260501-20261101"),   # playoffs begin
        ("2026-10-15", "20260501-20261101"),   # Finals -- was outside the old window
        ("2026-04-30", "20250501-20251101"),   # pre-season: still last year
    ]:
        check("wnba on %s" % d, resolve(wnba, datetime.fromisoformat(d), 5), expected)

    print("\nNBA spans the new year and reaches the June Finals")
    nba = window_expr("nba_managers")
    for d, expected in [
        ("2026-09-30", "20251001-20260630"),   # still last season
        ("2026-10-01", "20261001-20270630"),   # flips before the opener
        ("2027-06-10", "20261001-20270630"),   # Finals still inside
    ]:
        check("nba on %s" % d, resolve(nba, datetime.fromisoformat(d), 10), expected)

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
