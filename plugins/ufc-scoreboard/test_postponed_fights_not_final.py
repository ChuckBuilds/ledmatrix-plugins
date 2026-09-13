#!/usr/bin/env python3
"""A postponed or cancelled bout is not a result.

ESPN reports postponed, cancelled and suspended events with state "post", so
judging "final" on state alone put them on the Recent screen as finished
fights. Final now requires status.type.completed and excludes those statuses.

Also pins the `is_halftime` key on MMA fight details: the shared
SportsLive.update() reads it by subscript for every fight in the feed, so a
fight without it raised KeyError and abandoned the whole live update.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_postponed_fights_not_final.py
"""

import logging
import os
import sys
from datetime import timezone
from pathlib import Path
from unittest.mock import MagicMock

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from ufc_managers import UFCRecentManager as MMARecent  # noqa: E402  (concrete)
from sports import _status_is_final  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def status(name, state="post", completed=None, detail="Final"):
    s = {"name": name, "state": state, "shortDetail": detail}
    if completed is not None:
        s["completed"] = completed
    return s


print("_status_is_final")
check("STATUS_FINAL completed", _status_is_final(status("STATUS_FINAL", completed=True)))
check("no completed flag, final name", _status_is_final(status("STATUS_FINAL")))
for name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
    check(f"{name} is not final", not _status_is_final(status(name, completed=False)))
    check(f"{name} is not final even without a completed flag",
          not _status_is_final(status(name)))
check("state post but completed=false", not _status_is_final(status("STATUS_WHATEVER", completed=False)))
check("in progress", not _status_is_final(status("STATUS_IN_PROGRESS", state="in")))
check("non-dict", not _status_is_final(None))


def event(status_type):
    return {
        "id": "600040001",
        "date": "2026-09-06T02:00Z",
        "competitions": [{
            "id": "401770001",
            "type": {"abbreviation": "LW"},
            "status": {"period": 0, "displayClock": "0:00", "type": status_type},
            "competitors": [
                {"order": 1, "id": "11", "athlete": {"fullName": "Fighter One", "shortName": "F. One"}},
                {"order": 2, "id": "22", "athlete": {"fullName": "Fighter Two", "shortName": "F. Two"}},
            ],
        }],
    }


mgr = MMARecent.__new__(MMARecent)
mgr.logger = logging.getLogger("postponed_probe")
mgr.favorite_fighters = []
mgr.favorite_weight_class = []
mgr.config = {}
mgr.display_manager = MagicMock()
mgr.display_manager.format_date_with_ordinal.return_value = "Sep 6th"
mgr.logo_dir = Path(".")
mgr._get_timezone = lambda: timezone.utc

print("\nMMA extractor")
postponed = mgr._extract_game_details(event(status("STATUS_POSTPONED", completed=False, detail="Postponed")))
check("a postponed bout is extracted", postponed is not None)
check("... and is not final (would show on Recent)", postponed and postponed["is_final"] is False)
final = mgr._extract_game_details(event(status("STATUS_FINAL", completed=True)))
check("a finished bout is final", final and final["is_final"] is True)
scheduled = mgr._extract_game_details(event(status("STATUS_SCHEDULED", state="pre", completed=False, detail="Sat 10PM")))
check("fight details carry is_halftime (SportsLive.update subscripts it)",
      scheduled is not None and scheduled.get("is_halftime") is False)

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
