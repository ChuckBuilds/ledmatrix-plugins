#!/usr/bin/env python3
"""A fight between rounds stays on the live display, and draws "End R4".

SportsLive._is_game_really_over, shared with the team sports, called a game over
at clock 0:00 from period 4. LEDMatrix#680 flagged that for ufc: if ESPN sent
the break between rounds 4 and 5 of a five-round fight as "0:00, period 4",
the live manager would drop the fight for that minute. ufc now declares
FINAL_PERIOD = None, so no clock ends a fight, but the payload checks stay. Checked against ESPN's
MMA scoreboard it does not. The live clock counts down, but a round that goes
the distance ends on a Round End play whose clock is "-", and the break arrives
as STATUS_END_OF_ROUND, state "in", clock 0.0, displayClock "-". "-" is not a
zero clock to the shared rule, so the fight stays live.

These checks pin that through the real UFCLiveManager.update(), over ESPN
scoreboard bouts in each state (test/fixtures/espn_mma_round_states.json: real
captures, plus the round 4 and round 5 breaks derived from the real round 1
break, marked as such). A later rule that reads a non-numeric clock as 0:00
would drop main events at the round 4 break, and fails here.

The same payloads found a display bug, fixed alongside: the break check looked
for STATUS_END_PERIOD, the team-sport name, which the MMA feed never sends, so
a break drew "R4 -" on the live scorebug instead of ESPN's "End R4".

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_round_break_stays_live.py
Exit 0 pass, 1 fail, 2 skip (no LEDMatrix core checkout found).
"""

import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
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

import sports  # noqa: E402
from ufc_managers import UFCLiveManager  # noqa: E402

FIXTURES = PLUGIN_DIR / "test" / "fixtures" / "espn_mma_round_states.json"
CASES = {c["name"]: c for c in json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]}

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def live_manager():
    display = MagicMock()
    display.width, display.height = 128, 32
    display.matrix.width, display.matrix.height = 128, 32
    cache = MagicMock()
    cache.get.return_value = None
    config = {"timezone": "UTC",
              "ufc_scoreboard": {"enabled": True, "show_odds": False}}
    mgr = UFCLiveManager(config, display, cache)
    # No network: the feed is the fixture, and there are no headshots to get.
    mgr._fetch_missing_headshots = lambda *a, **k: None
    return mgr


def run_update(mgr, *events):
    """One real live update against a scoreboard holding `events`."""
    mgr._fetch_data = lambda: {"events": list(events)}
    mgr.last_update = 0
    mgr.update()
    return [g.get("id") for g in mgr.live_games]


def bout_id(case):
    return case["event"]["competitions"][0]["id"]


print("fixtures")
check("every case is present", {
    "in_round_3_of_3", "break_after_round_1", "end_of_round_after_stoppage",
    "walkouts_five_rounder",
    "final_five_round_decision", "final_five_round_stoppage",
    "final_three_round_decision", "final_three_round_stoppage",
    "break_after_round_4_of_5", "end_of_round_5_awaiting_decision",
} <= set(CASES), sorted(CASES))

print("\nwhat ESPN sends between rounds")
real = CASES["break_after_round_1"]["event"]["competitions"][0]["status"]
check("a recorded break is STATUS_END_OF_ROUND, state in, displayClock '-'",
      (real["type"]["name"], real["type"]["state"], real["displayClock"])
      == ("STATUS_END_OF_ROUND", "in", "-"), repr(real))

print("\nthe round 4 break is not 'over'")
_probe = SimpleNamespace(logger=logging.getLogger("round_break_probe"),
                         FINAL_PERIOD=sports.SportsLive.FINAL_PERIOD)
mgr = live_manager()
brk = mgr._extract_game_details(CASES["break_after_round_4_of_5"]["event"])
check("round 4 break extracts as period 4, clock '-', live, not final",
      brk and (brk["period"], brk["clock"], brk["is_live"], brk["is_final"]) == (4, "-", True, False),
      brk and repr((brk["period"], brk["clock"], brk["is_live"], brk["is_final"])))
check("SportsLive._is_game_really_over says not over",
      sports.SportsLive._is_game_really_over(_probe, brk) is False)
check("... and so does the method the live manager resolves",
      mgr._is_game_really_over(brk) is False)
check("the scorebug draws ESPN's break text",
      brk["is_period_break"] is True and brk["status_text"] == "End R4",
      brk["status_text"])

print("\neach ESPN state through UFCLiveManager.update()")
for name, case in CASES.items():
    mgr = live_manager()
    live = run_update(mgr, case["event"])
    expected = case["expect_live"]
    check(f"{name}: {'on' if expected else 'off'} the live display",
          (bout_id(case) in live) is expected, f"live={live}")
    if "expect_period_break" in case:
        details = mgr._extract_game_details(case["event"])
        check(f"{name}: is_period_break is {case['expect_period_break']}",
              details["is_period_break"] is case["expect_period_break"])

print("\na five-round decision, from the round 4 break to the result")
mgr = live_manager()
fight = bout_id(CASES["break_after_round_4_of_5"])
check("live during the break after round 4",
      fight in run_update(mgr, CASES["break_after_round_4_of_5"]["event"]))
check("still live after the final horn, while the scorecards are read",
      fight in run_update(mgr, CASES["end_of_round_5_awaiting_decision"]["event"]))
check("gone once ESPN posts STATUS_FINAL",
      fight not in run_update(mgr, CASES["final_five_round_decision"]["event"]))

print("\na stoppage leaves the live display on its result")
mgr = live_manager()
fight = bout_id(CASES["end_of_round_after_stoppage"])
check("live while the stoppage awaits its result (End R2, 0:51)",
      fight in run_update(mgr, CASES["end_of_round_after_stoppage"]["event"]))
check("gone once the result posts",
      fight not in run_update(mgr, CASES["final_three_round_stoppage"]["event"]))

print("\none bout at its break, another finished, on the same card")
mgr = live_manager()
live = run_update(mgr, CASES["break_after_round_4_of_5"]["event"],
                  CASES["final_three_round_decision"]["event"])
check("only the fight at its break is live",
      live == [bout_id(CASES["break_after_round_4_of_5"])], f"live={live}")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
