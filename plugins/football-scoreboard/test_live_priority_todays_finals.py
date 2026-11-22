#!/usr/bin/env python3
"""live_priority_show_todays_finals: while a favourite's live game holds the
panel, today's finals follow the games in progress in the live scroll.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_live_priority_todays_finals.py
"""

import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

from nfl_managers import NFLLiveManager  # noqa: E402

TZ = pytz.timezone("America/New_York")
results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


def make_live(enabled=True, exclude=None):
    live = NFLLiveManager.__new__(NFLLiveManager)
    live.show_todays_finals_in_live = enabled
    live.todays_finals = {}
    live._todays_finals_date = None
    live.exclude_teams = exclude or []
    live._games_lock = threading.RLock()
    live._get_timezone = lambda: TZ
    return live


def game(gid, home, away, start):
    return {"id": gid, "home_abbr": home, "away_abbr": away,
            "start_time_utc": start, "is_final": True}


now_local = datetime.now(TZ)
today_noon = TZ.localize(datetime(now_local.year, now_local.month, now_local.day, 13, 0)).astimezone(timezone.utc)
today_late = today_noon + timedelta(hours=3)
yesterday = today_noon - timedelta(days=1)

live = make_live()
live._note_todays_final(game("b", "DAL", "NYG", today_late))
live._note_todays_final(game("a", "BUF", "MIA", today_noon))
live._note_todays_final(game("y", "KC", "LV", yesterday))
finals = live.get_todays_finals()
check("only today's finals are kept", [g["id"] for g in finals] == ["a", "b"])
check("earliest kickoff first", finals[0]["id"] == "a")
check("returns copies", finals[0] is not live.todays_finals["a"])

live._note_todays_final(game("a", "BUF", "MIA", today_noon))
check("same game is not duplicated", len(live.get_todays_finals()) == 2)

live = make_live(exclude=["DAL"])
live._note_todays_final(game("b", "DAL", "NYG", today_late))
check("excluded teams stay hidden", live.get_todays_finals() == [])

live = make_live(enabled=False)
live._note_todays_final(game("a", "BUF", "MIA", today_noon))
check("setting off: nothing kept", live.get_todays_finals() == [])

live = make_live()
live._note_todays_final(game("a", "BUF", "MIA", today_noon))
live._todays_finals_date = now_local.date() - timedelta(days=1)
check("a new day starts empty", live.get_todays_finals() == [])

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
