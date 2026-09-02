#!/usr/bin/env python3
"""
Tests that SportsRecent.update() fetches odds for the finals it selects.

SportsUpcoming fetches odds for the games that survive selection, and
SportsLive fetches them per included game -- SportsRecent never fetched
them at all, so the Recent renderer's "odds if available" never had
anything attached and every final rendered bare.
This plugin has no display-path rotation at all, so unlike
football-scoreboard (where rotated-in finals picked lines up by accident)
its finals were bare in every configuration. ESPN keeps a completed
game's closing line on the same endpoint, so a final is as answerable as
an upcoming game. Same fix and same pins as football-scoreboard 2.29.3.

These checks pin:

  * update() asks for odds for exactly the finals it selected;
  * show_odds off means no requests;
  * non-final games in the feed are not asked about.

Exercised against a probe subclass with the data hooks stubbed, same as
test_favorites_are_prioritised.py: no display hardware, no network --
_fetch_odds itself is a recorder.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_recent_games_get_odds.py
"""

import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


def _final(gid, away, home, days_ago=1):
    return {
        "id": gid,
        "away_abbr": away,
        "home_abbr": home,
        "away_score": "21",
        "home_score": "28",
        "is_final": True,
        "start_time_utc": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


def _make(events, favorites, show_odds=True):
    cls = type("RecentOddsProbe", (sports.SportsRecent,), {
        "_fetch_data": lambda s: {"events": list(events)},
        "_extract_game_details": lambda s, ev: dict(ev),
    })
    obj = cls.__new__(cls)
    obj.is_enabled = True
    obj.last_update = 0
    obj.update_interval = 60
    obj.last_log_time = 0
    obj.log_interval = 300
    obj.show_ranking = False
    obj.show_records = False
    obj.other_games_min_quality = "any"
    obj.other_games_divisions = []
    obj.favorite_teams = favorites
    obj.exclude_teams = []
    obj.show_favorite_teams_only = False
    obj.recent_games_to_show = 2
    obj.other_recent_games_to_show = 2
    obj.other_rotation_interval_seconds = 0
    obj._other_window_start = 0
    obj._other_window_rotated_at = 0.0
    obj.schedule_lookback_days = 7
    obj._team_rankings_cache = {}
    obj._division_team_ids = {}
    obj._division_loaded_at = time.monotonic()
    obj._games_lock = threading.RLock()
    obj._zero_clock_timestamps = {}
    obj.games_list = []
    obj.current_game = None
    obj.current_game_index = 0
    obj.last_game_switch = 0
    obj.league = "eng.1"
    obj.sport = "soccer"
    obj.sport_key = "soccer"
    obj.cache_manager = None
    obj.logger = logging.getLogger("recent_odds_probe")
    obj.show_odds = show_odds
    obj.requested = []
    obj._fetch_odds = lambda game: obj.requested.append(game["id"])
    return obj


failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def main():
    print("finals in the window, show_odds on:")
    events = [
        _final("fav", "AAA", "FAV"),
        _final("oth", "BBB", "CCC"),
        {"id": "live", "away_abbr": "A", "home_abbr": "B", "is_final": False,
         "period": 2, "clock": "7:15", "status_text": "2nd",
         "away_score": "7", "home_score": "3",
         "start_time_utc": datetime.now(timezone.utc)},
    ]
    probe = _make(events, favorites=["FAV"])
    probe.update()
    shown = [g["id"] for g in probe.games_list]
    check("update() selected the finals", sorted(shown) == ["fav", "oth"], shown)
    check("odds were requested for exactly the selected finals",
          sorted(probe.requested) == sorted(shown), probe.requested)
    check("the in-progress game was not asked about",
          "live" not in probe.requested, probe.requested)

    print("\nshow_odds off: no requests")
    probe = _make(events[:2], favorites=["FAV"], show_odds=False)
    probe.update()
    check("update() still selected the finals", len(probe.games_list) == 2,
          [g["id"] for g in probe.games_list])
    check("no odds were requested", probe.requested == [], probe.requested)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
