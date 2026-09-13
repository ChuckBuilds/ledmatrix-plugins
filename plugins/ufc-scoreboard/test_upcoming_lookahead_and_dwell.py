#!/usr/bin/env python3
"""Upcoming honours schedule_lookahead_days; re-entry gives a card a full dwell.

Ported from football-scoreboard (#345).

* Lookahead: the UFC fetch is season-wide (Jan-Dec) and MMAUpcoming.update()
  never trimmed it, so Upcoming showed fights months out regardless of
  schedule_lookahead_days.
* Dwell: last_game_switch kept running while the mode was off screen, so when
  the rotation came back to Recent/Upcoming the first display() advanced at
  once and the card cut off at the end of the previous block was skipped.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_upcoming_lookahead_and_dwell.py
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
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

from ufc_managers import UFCRecentManager as MMARecent, UFCUpcomingManager as MMAUpcoming  # noqa: E402  (concrete)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


NOW = datetime.now(timezone.utc)


def event(cid, days_ahead):
    return {
        "id": "e" + cid,
        "date": (NOW + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%MZ"),
        "competitions": [{
            "id": cid,
            "type": {"abbreviation": "LW"},
            "status": {"period": 0, "displayClock": "0:00",
                       "type": {"state": "pre", "name": "STATUS_SCHEDULED",
                                "shortDetail": "Sat", "completed": False}},
            "competitors": [
                {"order": 1, "id": "1" + cid, "athlete": {"fullName": "A " + cid, "shortName": "A"}},
                {"order": 2, "id": "2" + cid, "athlete": {"fullName": "B " + cid, "shortName": "B"}},
            ],
        }],
    }


def upcoming_manager(events, lookahead):
    mgr = MMAUpcoming.__new__(MMAUpcoming)
    mgr.logger = logging.getLogger("lookahead_probe")
    mgr.is_enabled = True
    mgr.last_update = 0
    mgr.update_interval = 0
    mgr._fetch_data = lambda: {"events": events}
    mgr.show_favorite_teams_only = False
    mgr.favorite_fighters = []
    mgr.favorite_weight_class = []
    mgr.show_odds = False
    mgr.upcoming_games_to_show = 10
    mgr.last_log_time = 0
    mgr.log_interval = 300
    mgr.games_list = []
    mgr.current_game = None
    mgr.current_game_index = 0
    mgr.schedule_lookahead_days = lookahead
    mgr.config = {}
    mgr.display_manager = MagicMock()
    mgr.display_manager.format_date_with_ordinal.return_value = "Sep 20th"
    mgr.logo_dir = Path(".")
    mgr._get_timezone = lambda: timezone.utc
    return mgr


print("lookahead")
events = [event("100", 2), event("200", 6), event("300", 40), event("400", 120)]
mgr = upcoming_manager(events, 7)
mgr.update()
ids = sorted(g["id"] for g in mgr.games_list)
check("only fights inside 7 days are shown", ids == ["100", "200"], f"got {ids}")
mgr = upcoming_manager(events, 60)
mgr.update()
ids = sorted(g["id"] for g in mgr.games_list)
check("a wider window admits more", ids == ["100", "200", "300"], f"got {ids}")


print("\ndwell reset on re-entry")
probe = MMARecent.__new__(MMARecent)
probe.last_game_switch = time.time() - 100
probe._last_display_call_monotonic = time.monotonic() - 60
check("coming back after a minute resets the dwell", probe._reset_dwell_on_reentry() is True)
check("... to now", time.time() - probe.last_game_switch < 1)
check("the next frame of the same stint does not", probe._reset_dwell_on_reentry() is False)
fresh = MMARecent.__new__(MMARecent)
fresh.last_game_switch = 0
check("the 'no game shown yet' sentinel is left alone",
      fresh._reset_dwell_on_reentry() is False and fresh.last_game_switch == 0)


def displaying(cls):
    mgr = cls.__new__(cls)
    mgr.logger = logging.getLogger("dwell_probe")
    mgr.is_enabled = True
    mgr.sport_key = "ufc_scoreboard"
    mgr.games_list = [{"id": "1"}, {"id": "2"}]
    mgr.current_game_index = 0
    mgr.current_game = mgr.games_list[0]
    mgr.game_display_duration = 15
    mgr.last_game_switch = time.time() - 300     # expired while off screen
    mgr._last_display_call_monotonic = time.monotonic() - 300
    mgr._games_lock = threading.Lock()
    mgr.last_warning_time = 0
    mgr.warning_cooldown = 300
    mgr.drawn = []
    mgr._draw_scorebug_layout = lambda game, force_clear=False: mgr.drawn.append(game["id"])
    return mgr


for cls in (MMAUpcoming, MMARecent):
    mgr = displaying(cls)
    mgr.display()
    check(f"{cls.__name__}: re-entry shows the card it left on, not the next one",
          mgr.drawn == ["1"], f"drew {mgr.drawn}")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
