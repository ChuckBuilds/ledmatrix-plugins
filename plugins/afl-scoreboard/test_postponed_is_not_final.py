#!/usr/bin/env python3
"""Postponed, cancelled and suspended fixtures must not render as "Final 0-0".

ESPN files a washed-out or called-off match under status.type.state "post" --
the same bucket as a finished game -- with both scores "0". The extractor set
is_final from the state alone and the AFL period label hard-coded "Final", so
the Recent screen admitted the fixture twice over (is_final, and the "appears
finished" check that looks for "final" in period_text) and drew "Final 0-0".

These checks pin:

  * _status_is_final is true for a completed STATUS_FINAL only;
  * completed False, or a POSTPONED / CANCELED / SUSPENDED name, is not final;
  * the AFL period label for such a fixture is ESPN's own short detail, and
    contains no "final" for the Recent screen's fallback check to find.

Run: <core-venv>/bin/python plugins/afl-scoreboard/test_postponed_is_not_final.py
"""

import logging
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

import sports  # noqa: E402
import afl_managers  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _period_text(status_type, period=4):
    mgr = afl_managers.BaseAflManager.__new__(afl_managers.BaseAflManager)
    mgr.logger = logging.getLogger("postponed_probe")
    mgr.league_key = "afl"

    def common(event):
        details = {"id": "x", "home_abbr": "COLL", "away_abbr": "GEEL",
                   "game_time": "", "is_live": False, "is_upcoming": False,
                   "is_final": sports._status_is_final(event["status"]["type"])}
        return details, {}, {}, event["status"], None

    mgr._extract_game_details_common = common
    return mgr._extract_game_details(
        {"id": "x", "status": {"period": period, "displayClock": "0:00",
                               "type": status_type}})


def main():
    final = sports._status_is_final
    print("status classification")
    check("a completed STATUS_FINAL is final",
          final({"state": "post", "name": "STATUS_FINAL", "completed": True}))
    check("a payload without the completed flag keeps the old behaviour",
          final({"state": "post", "name": "STATUS_FINAL"}))
    check("a live game is not final",
          not final({"state": "in", "name": "STATUS_IN_PROGRESS", "completed": False}))
    for name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
        check("%s (state post) is not final" % name,
              not final({"state": "post", "name": name, "completed": False}))
        check("%s is not final even if completed were set" % name,
              not final({"state": "post", "name": name, "completed": True}))
    check("state post with completed False is not final",
          not final({"state": "post", "name": "STATUS_WHATEVER", "completed": False}))
    check("garbage is not final", not final(None))

    print("\nthe AFL period label")
    played = _period_text({"state": "post", "name": "STATUS_FINAL",
                           "completed": True, "shortDetail": "FT"})
    check("a played game still says Final", played["period_text"] == "Final",
          played["period_text"])
    check("and is_final", played["is_final"] is True)

    postponed = _period_text({"state": "post", "name": "STATUS_POSTPONED",
                              "completed": False, "shortDetail": "Postponed"}, period=0)
    check("a postponed game is labelled Postponed",
          postponed["period_text"] == "Postponed", postponed["period_text"])
    check("with no 'final' for the Recent fallback check to match",
          "final" not in postponed["period_text"].lower())
    check("and is not final", postponed["is_final"] is False)

    no_detail = _period_text({"state": "post", "name": "STATUS_CANCELED",
                              "completed": False}, period=0)
    check("no shortDetail falls back to the status name, still not Final",
          "final" not in no_detail["period_text"].lower(), no_detail["period_text"])

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
