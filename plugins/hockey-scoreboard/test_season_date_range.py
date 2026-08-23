#!/usr/bin/env python3
"""The ESPN season window must follow the calendar, not a pinned year.

_get_season_date_range built its range from literal dates:

    season_start = datetime(2025, 10, 1)
    season_end   = datetime(2026, 6, 30)

`now` was computed on the line above and never used, so the request stayed
pinned to 2025-26 forever. Once the 2026-27 season opened, the fetch would have
asked ESPN for last season's window.

The range now derives from the current date using the same rule
nhl_managers.py applies -- from August onwards you are in the season labelled
with this year -- so the two agree on which season is current instead of
drifting apart.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_season_date_range.py
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import data_fetcher  # noqa: E402

failures = []


def check(name, actual, expected):
    if actual == expected:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s: expected %r, got %r" % (name, expected, actual))
        failures.append(name)


def range_on(date_str, league):
    """The window the fetcher would request on a given date."""
    fetcher = data_fetcher.HockeyDataFetcher.__new__(data_fetcher.HockeyDataFetcher)
    frozen = datetime.fromisoformat(date_str)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    with mock.patch.object(data_fetcher, "datetime", _DT):
        return fetcher._get_season_date_range(league)


def main():
    print("the window follows the calendar year")
    # July is still last season; August flips to the one about to start.
    check("nhl in July 2026 asks for 2025-26",
          range_on("2026-07-31", "nhl"), "20251001-20260630")
    check("nhl in August 2026 asks for 2026-27",
          range_on("2026-08-22", "nhl"), "20261001-20270630")
    check("nhl at the October opener asks for 2026-27",
          range_on("2026-10-07", "nhl"), "20261001-20270630")
    check("nhl in June 2027 still asks for 2026-27",
          range_on("2027-06-20", "nhl"), "20261001-20270630")
    check("nhl rolls again in August 2027",
          range_on("2027-08-01", "nhl"), "20271001-20280630")

    print("\nNCAA ends in March, not June")
    check("ncaa_mens 2026-27", range_on("2026-10-07", "ncaa_mens"), "20261001-20270331")
    check("ncaa_womens 2026-27", range_on("2026-10-07", "ncaa_womens"), "20261001-20270331")

    print("\nan unknown league still gets a current window, not a pinned one")
    check("unknown league follows the year",
          range_on("2026-10-07", "somethingelse"), "20261001-20270630")

    print("\nno literal season year survives in the source")
    src = (plugin_dir / "data_fetcher.py").read_text()
    body = src[src.index("def _get_season_date_range"):]
    body = body[:body.index("def ", 10)]
    for pinned in ("2025", "2026"):
        check("%s is not hardcoded in the range builder" % pinned,
              pinned in body, False)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
