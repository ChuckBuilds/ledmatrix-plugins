#!/usr/bin/env python3
"""Every bout on a fight card is its own fight: live, recent and upcoming.

ESPN's MMA scoreboard sends a whole card as ONE event whose competitions are
its bouts, early prelims first. The live manager read competitions[0] only, so
live_games, the live switch view, the Vegas cards and the finished-fight
capture all followed the card's first-listed bout. That bout is over early in
the night, and from then on the card had nothing live while its main card was
in the cage. Before the first bout it was the other way round: a scheduled
bout's displayClock is "-", which the shared live update takes for a running
clock (anything but 0:00), so the first bout sat on the live screen from the
moment the day's scoreboard listed it.

Checked against all 103 Wayback captures of ESPN's UFC scoreboard from 2026:
the old live manager held exactly the bouts ESPN had in progress in 31 of
them, this one in all 103. These checks replay one fight night, UFC 331,
recorded whole four times (test/fixtures/espn_mma_fight_night.json), through
the real managers with the network stubbed at fetch_espn_scoreboard.

Recent and Upcoming already split cards into bouts, but dated every bout with
the card's opening time; each bout now carries its own segment's start, so
Recent leads with the main card rather than the early prelims.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_every_bout_is_its_own_fight.py
Exit 0 pass, 1 fail, 2 skip (no LEDMatrix core checkout found).
"""

import copy
import json
import logging
import os
import sys
from datetime import datetime, timezone
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

import mma  # noqa: E402
import sports  # noqa: E402
from manager import UFCScoreboardPlugin  # noqa: E402
from ufc_managers import (  # noqa: E402
    UFCLiveManager,
    UFCRecentManager,
    UFCUpcomingManager,
)

FIXTURES = PLUGIN_DIR / "test" / "fixtures" / "espn_mma_fight_night.json"
CAPTURES = {c["name"]: c["scoreboard"]
            for c in json.loads(FIXTURES.read_text(encoding="utf-8"))["captures"]}

CARD = "600060963"
#: Early prelim, listed first: all the old live manager ever looked at.
FIRST_LISTED = "401905382"
#: The main card's opener: walkouts at 01:05 UTC, round 3 at 01:44 UTC.
OPENER = "401905378"
#: Van vs. Pantoja, listed last.
MAIN_EVENT = "401903509"
MAIN_CARD = {OPENER, "401903510", "401905376", "401905375", MAIN_EVENT}

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def board(name):
    """A fresh copy of a recorded scoreboard (the managers may annotate it)."""
    return copy.deepcopy(CAPTURES[name])


def bouts(name):
    return CAPTURES[name]["events"][0]["competitions"]


def make(cls, **settings):
    display = MagicMock()
    display.width, display.height = 128, 32
    display.matrix.width, display.matrix.height = 128, 32
    cache = MagicMock()
    cache.get.return_value = None
    config = {"timezone": "America/New_York",
              "display": {"use_short_date_format": True},
              "ufc_scoreboard": {"enabled": True, "show_odds": False, **settings}}
    mgr = cls(config, display, cache)
    # No network: the feed is the fixture, and there are no headshots to get.
    mgr._fetch_missing_headshots = lambda *a, **k: None
    return mgr


_real_fetch = sports.fetch_espn_scoreboard


def poll_live(mgr, name):
    """One real live update, with ESPN answering from the recorded scoreboard."""
    sports.fetch_espn_scoreboard = lambda *a, **k: board(name)
    try:
        mgr.last_update = 0
        mgr.update()
    finally:
        sports.fetch_espn_scoreboard = _real_fetch
    return [g["id"] for g in mgr.live_games]


def states(name):
    counts = {}
    for comp in bouts(name):
        state = comp["status"]["type"]["state"]
        counts[state] = counts.get(state, 0) + 1
    return counts


print("the recorded card")
check("one event, twelve bouts, in every capture",
      all(len(b["events"]) == 1 and b["events"][0]["id"] == CARD
          and len(b["events"][0]["competitions"]) == 12 for b in CAPTURES.values()))
check("fight-day morning: all twelve scheduled", states("fight_day_morning") == {"pre": 12},
      states("fight_day_morning"))
for name in ("main_card_walkouts", "main_card_round_3"):
    live = [c["id"] for c in bouts(name) if c["status"]["type"]["state"] == "in"]
    check(f"{name}: seven final, the opener in, four scheduled",
          states(name) == {"post": 7, "in": 1, "pre": 4} and live == [OPENER],
          f"{states(name)} in={live}")
check("card over: all twelve final", states("card_over") == {"post": 12}, states("card_over"))
first = bouts("main_card_round_3")[0]
check("competitions[0] is an early prelim, final while the main card is on",
      first["id"] == FIRST_LISTED and first["status"]["type"]["name"] == "STATUS_FINAL")
check("a scheduled bout's displayClock is '-'",
      {c["status"]["displayClock"] for c in bouts("fight_day_morning")} == {"-"})

print("\nsplitting a card into bouts")
events = mma._bouts_as_events(board("main_card_round_3")["events"])
check("one event per bout, each holding just its bout",
      len(events) == 12 and all(len(e["competitions"]) == 1 for e in events))
check("... in running order",
      [e["competitions"][0]["id"] for e in events] == [c["id"] for c in bouts("main_card_round_3")])
check("... each keeping the card's own id, name and date",
      all((e["id"], e["name"], e["date"]) == (CARD, "UFC 331: Van vs. Pantoja 2", "2026-09-19T21:00Z")
          for e in events))
check("nothing to split -> nothing",
      mma._bouts_as_events(None) == []
      and mma._bouts_as_events([None, {"id": "1"}, {"id": "2", "competitions": None}]) == [])

print("\nlive, through UFCLiveManager.update()")
mgr = make(UFCLiveManager)
check("fight-day morning: nothing live (the scheduled '-' clock is not a running one)",
      poll_live(mgr, "fight_day_morning") == [], f"live={[g['id'] for g in mgr.live_games]}")
live = poll_live(mgr, "main_card_walkouts")
check("walkouts: the opener, and nothing else, is live", live == [OPENER], f"live={live}")
check("... and is the fight the live switch view shows",
      mgr.current_game and mgr.current_game["id"] == OPENER
      and mgr.current_game["status_text"] == "Pre-fight",
      mgr.current_game and mgr.current_game.get("status_text"))
check("... keyed by its competition id, with the card as its event",
      mgr.current_game and (mgr.current_game["event_id"], mgr.current_game["comp_id"])
      == (CARD, OPENER))
live = poll_live(mgr, "main_card_round_3")
check("round 3: still the opener, the same fight", live == [OPENER], f"live={live}")
check("... refreshed in place: R3, 1:21",
      mgr.current_game and (mgr.current_game["id"], mgr.current_game["status_text"],
                            mgr.current_game["period"], mgr.current_game["clock"])
      == (OPENER, "R3, 1:21", 3, "1:21"),
      mgr.current_game and repr((mgr.current_game["status_text"], mgr.current_game["clock"])))
check("card over: nothing live", poll_live(mgr, "card_over") == [] and mgr.current_game is None)

print("\nthe poll that drops a finished bout sees that bout")
# What the finished-fight capture is handed: the details of each bout the live
# poll drops as final. It keeps only a fight that was in live_games, by id.
mgr = make(UFCLiveManager)
poll_live(mgr, "main_card_round_3")
seen = []
_extract = mgr._extract_game_details
mgr._extract_game_details = lambda event: seen.append(_extract(event)) or seen[-1]
poll_live(mgr, "card_over")
dropped = [d for d in seen if d and d["id"] == OPENER]
check("the opener arrives final under the id it was live under",
      len(dropped) == 1 and dropped[0]["is_final"] and dropped[0]["event_id"] == CARD,
      repr([(d["id"], d["is_final"]) for d in dropped]))
check("every bout of the card is offered, once",
      sorted(d["id"] for d in seen if d) == sorted(c["id"] for c in bouts("card_over")))

print("\nthe Vegas cards")
mgr = make(UFCLiveManager)
poll_live(mgr, "main_card_round_3")
plugin = UFCScoreboardPlugin.__new__(UFCScoreboardPlugin)
plugin.logger = logging.getLogger("bouts_probe")
plugin.ufc_enabled = True
plugin._get_league_manager_for_mode = lambda league, mode: mgr if mode == "live" else None
fights, _leagues = plugin._collect_fights_for_scroll()
check("the live card is the bout in the cage",
      [(f["id"], f["status_text"]) for f in fights] == [(OPENER, "R3, 1:21")],
      repr([(f["id"], f["status_text"]) for f in fights]))

print("\neach bout at its own time")
detail = mgr._extract_game_details(
    {**board("main_card_round_3")["events"][0], "competitions": [bouts("main_card_round_3")[11]]})
check("a bout starts at its own segment, not the card's opening",
      detail["start_time_utc"] == datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
      str(detail["start_time_utc"]))
undated = copy.deepcopy(bouts("main_card_round_3")[11])
del undated["date"]
detail = mgr._extract_game_details(
    {**board("main_card_round_3")["events"][0], "competitions": [undated]})
check("a bout without a date of its own takes the card's",
      detail["start_time_utc"] == datetime(2026, 9, 19, 21, 0, tzinfo=timezone.utc),
      str(detail["start_time_utc"]))
check("a scheduled bout has no clock; one on, or final, keeps ESPN's",
      [mgr._extract_game_details({**board(n)["events"][0], "competitions": [c]})["clock"]
       for n, c in (("fight_day_morning", bouts("fight_day_morning")[7]),
                    ("main_card_walkouts", bouts("main_card_walkouts")[7]),
                    ("card_over", bouts("card_over")[7]))]
      == ["", "-", "5:00"])

up = make(UFCUpcomingManager, upcoming_games_to_show=20)
up._fetch_data = lambda: board("fight_day_morning")
up.last_update = 0
up.update()
times = {g["id"]: g["game_time"] for g in up.games_list}
check("Upcoming: every bout, at its own time (ESPN: 5:30, 7:00, 9:00 PM EDT)",
      len(up.games_list) == 12
      and (times.get(FIRST_LISTED), times.get("401905385"), times.get(MAIN_EVENT))
      == ("5:30PM", "7:00PM", "9:00PM"),
      repr((len(up.games_list), times.get(FIRST_LISTED), times.get(MAIN_EVENT))))

rec = make(UFCRecentManager)
# Wide enough that the recorded night stays in the window whenever this runs.
rec.schedule_lookback_days = 36500
rec._fetch_data = lambda: board("card_over")
rec.last_update = 0
rec.update()
shown = {g["id"] for g in rec.games_list}
check("Recent: the five it shows are the main card, not the early prelims",
      shown == MAIN_CARD, repr(sorted(shown)))

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
