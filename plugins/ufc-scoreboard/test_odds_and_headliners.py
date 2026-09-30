#!/usr/bin/env python3
"""Odds are asked for with the card id AND the bout id; Upcoming keeps the headliners.

Odds: ESPN's odds URL is .../events/<card>/competitions/<bout>/odds. The shared
SportsCore._fetch_odds passes only the fight's id (a bout's competition id), so
the URL was .../events/<bout>/competitions/<bout>/odds, which ESPN answers with
404 for every UFC fight (verified 2026-09-30: 404 for that form, 200 with a
DraftKings line for the card-and-bout form). MMA now registers each bout's card
with the odds manager as it extracts the fight.

Upcoming: ESPN lists a card's bouts main event last, and the main card shares
one start time, so keeping the soonest N by time cut a 12-bout card off before
its co-main and main event. The recorded UFC 331 scoreboard is replayed
(test/fixtures/espn_mma_fight_night.json).

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_odds_and_headliners.py
Exit 0 pass, 1 fail, 2 skip (no LEDMatrix core checkout found).
"""

import copy
import json
import logging
import os
import sys
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

import base_odds_manager as bom  # noqa: E402
from mma import MMAUpcoming  # noqa: E402
from ufc_managers import UFCUpcomingManager  # noqa: E402

CAPTURES = {c["name"]: c["scoreboard"] for c in json.loads(
    (PLUGIN_DIR / "test" / "fixtures" / "espn_mma_fight_night.json").read_text(encoding="utf-8"))["captures"]}

CARD, MAIN_EVENT, CO_MAIN, FIRST_LISTED = "600060963", "401903509", "401905375", "401905382"
FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Cache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value

    def clear_cache(self, key):
        self.data.pop(key, None)


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"items": []}
        return resp


print("odds URL")
odds = bom.BaseOddsManager(_Cache())
odds.session = _Session()
odds.logger.setLevel(logging.CRITICAL)
odds.get_odds("mma", "ufc", MAIN_EVENT)
check("an unregistered bout keeps the old URL (nothing known about its card)",
      odds.session.urls[-1].endswith(f"/events/{MAIN_EVENT}/competitions/{MAIN_EVENT}/odds"),
      odds.session.urls[-1])
odds.register_bout(MAIN_EVENT, CARD)
odds.get_odds("mma", "ufc", MAIN_EVENT)
check("a registered bout asks for <card>/competitions/<bout>",
      odds.session.urls[-1].endswith(f"/events/{CARD}/competitions/{MAIN_EVENT}/odds"),
      odds.session.urls[-1])
check("... cached under card_bout",
      f"odds_espn_mma_ufc_{CARD}_{MAIN_EVENT}" in odds.cache_manager.data,
      sorted(odds.cache_manager.data))
odds.get_odds("mma", "ufc", "600001", "600002")
check("explicit ids are untouched", odds.session.urls[-1].endswith("/events/600001/competitions/600002/odds"))


def upcoming(**settings):
    d = MagicMock()
    d.width, d.height = 128, 32
    d.matrix.width, d.matrix.height = 128, 32
    c = MagicMock()
    c.get.return_value = None
    cfg = {"timezone": "America/New_York", "display": {"use_short_date_format": True},
           "ufc_scoreboard": {"enabled": True, "show_odds": False, **settings}}
    mgr = UFCUpcomingManager(cfg, d, c)
    mgr._fetch_missing_headshots = lambda *a, **k: None
    mgr._fetch_data = lambda: copy.deepcopy(CAPTURES["fight_day_morning"])
    mgr.last_update = 0
    mgr.update()
    return mgr


print("\nextraction registers the card")
mgr = upcoming()
check("every extracted bout's card is known to the odds manager",
      mgr.odds_manager._card_of_bout.get(MAIN_EVENT) == CARD
      and len(mgr.odds_manager._card_of_bout) == 12, mgr.odds_manager._card_of_bout.get(MAIN_EVENT))

print("\nUpcoming keeps the headliners")
ids = [g["id"] for g in mgr.games_list]
check("default pool of 10 holds the main event and co-main", MAIN_EVENT in ids and CO_MAIN in ids, ids)
check("... and drops the two first-listed early prelims",
      len(ids) == 10 and FIRST_LISTED not in ids and "401903511" not in ids, ids)
check("... shown in start order, ties in ESPN's listing order",
      [g["game_time"] for g in mgr.games_list] == sorted(g["game_time"] for g in mgr.games_list)
      and ids[-1] == MAIN_EVENT, ids)
ids = [g["id"] for g in upcoming(upcoming_games_to_show=3).games_list]
check("a pool of 3 is the last three listed", ids[-1] == MAIN_EVENT and CO_MAIN in ids and len(ids) == 3, ids)
check("a pool of 20 holds all twelve", len(upcoming(upcoming_games_to_show=20).games_list) == 12)

print("\ntwo cards: the sooner card still fills the pool first")
a = [{"id": f"a{i}", "event_id": "A", "start_time_utc": None} for i in range(4)]
from datetime import datetime, timezone
for g in a:
    g["start_time_utc"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
b = [{"id": f"b{i}", "event_id": "B", "start_time_utc": datetime(2026, 1, 8, tzinfo=timezone.utc)} for i in range(4)]
got = [g["id"] for g in MMAUpcoming._trim_to_headliners(b + a, 6)]
check("card A whole, then the tail of card B", got == ["a0", "a1", "a2", "a3", "b2", "b3"], got)

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
