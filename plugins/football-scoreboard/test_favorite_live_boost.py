#!/usr/bin/env python3
"""
Tests for the exclude_teams + favorite_live_boost live-rotation logic added
to SportsLive (_classify_live_game, _build_weighted_schedule), and the
exclude_teams recent/final-scores spoiler protection in SportsRecent.update().

Run: <core-venv>/bin/python plugins/football-scoreboard/test_favorite_live_boost.py
"""

import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

# SportsLive itself is abstract (_extract_game_details/_fetch_data are supplied
# by league mixins) - use the concrete NFL live manager, which shares the exact
# same SportsLive._classify_live_game/_build_weighted_schedule implementation.
from nfl_managers import NFLLiveManager, NFLRecentManager  # noqa: E402


def make_live(favorite_teams=None, exclude_teams=None, show_favorite_teams_only=False,
              show_all_live=False, favorite_live_boost=2):
    """Build a live-manager instance with just the attributes these methods touch."""
    live = NFLLiveManager.__new__(NFLLiveManager)
    live.favorite_teams = favorite_teams or []
    live.exclude_teams = exclude_teams or []
    live.show_favorite_teams_only = show_favorite_teams_only
    live.show_all_live = show_all_live
    live.favorite_live_boost = favorite_live_boost
    return live


def game(gid, home, away):
    return {"id": gid, "home_abbr": home, "away_abbr": away}


results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


# --- exclude_teams always wins, even with show_all_live ---------------------
live = make_live(exclude_teams=["SF"], show_all_live=True)
included, reason = live._classify_live_game("SF", "LAD")
check("excluded team hidden even with show_all_live=True", included is False)
check("exclude reason reported", reason == "excluded team")

# --- exclude wins over favorite_teams too ------------------------------------
live = make_live(favorite_teams=["SF"], exclude_teams=["SF"], show_favorite_teams_only=True)
included, _ = live._classify_live_game("SF", "LAD")
check("excluded team wins over favorite_teams", included is False)

# --- both toggles off -> show everything not excluded ------------------------
live = make_live(favorite_teams=["SF"], show_favorite_teams_only=False, show_all_live=False)
included, _ = live._classify_live_game("LAD", "SD")
check("both filters off shows non-favorite live games", included is True)

# --- favorites-only with favorites configured filters correctly -------------
live = make_live(favorite_teams=["SF"], show_favorite_teams_only=True, show_all_live=False)
inc_fav, _ = live._classify_live_game("SF", "LAD")
inc_other, _ = live._classify_live_game("LAD", "SD")
check("favorites-only includes favorite's game", inc_fav is True)
check("favorites-only excludes non-favorite game", inc_other is False)

# --- favorite_live_boost=1, no favorites live -> plain single-pass schedule --
live = make_live(favorite_teams=["SF"], favorite_live_boost=1)
games = [game("a", "LAD", "SD"), game("b", "SF", "NYM"), game("c", "CHC", "STL")]
schedule = live._build_weighted_schedule(games)
check("boost=1 degenerates to plain order", schedule == ["a", "b", "c"])

# --- no favorite live at all -> plain single-pass schedule regardless of boost
live = make_live(favorite_teams=["SF"], favorite_live_boost=3)
games_no_fav = [game("a", "LAD", "SD"), game("b", "CHC", "STL")]
schedule = live._build_weighted_schedule(games_no_fav)
check("no favorite live -> plain order even with boost>1", schedule == ["a", "b"])

# --- boost=2 with favorite + 2 others -> favorite gets 2 of every 4 slots ----
live = make_live(favorite_teams=["SF"], favorite_live_boost=2)
games = [game("fav", "SF", "LAD"), game("o1", "SD", "COL"), game("o2", "CHC", "STL")]
schedule = live._build_weighted_schedule(games)
check("weighted schedule length == total weight (2+1+1=4)", len(schedule) == 4)
check("favorite appears exactly 2 of 4 slots", schedule.count("fav") == 2)
check("favorite scheduled first", schedule[0] == "fav")
# Evenly spaced: no two consecutive slots should both be the favorite when
# there are other games to interleave with.
consecutive_favs = any(schedule[i] == schedule[i + 1] == "fav" for i in range(len(schedule) - 1))
check("favorite's repeats are spaced out, not clumped", not consecutive_favs)

# --- boost=3, single favorite game only (nothing to interleave with) --------
live = make_live(favorite_teams=["SF"], favorite_live_boost=3)
schedule = live._build_weighted_schedule([game("fav", "SF", "LAD")])
check("single live game repeats boost times", schedule == ["fav", "fav", "fav"])

# --- empty games list --------------------------------------------------------
live = make_live()
check("empty games -> empty schedule", live._build_weighted_schedule([]) == [])


# --- exclude_teams must also hide games in the *default* recent-games path ---
# Regression test for a bug CodeRabbit caught on this PR: the exclude filter
# was only applied inside _select_recent_games_for_display, which is skipped
# entirely when show_favorite_teams_only is False (the schema default) - so
# excluded teams' final scores still leaked through. Fixed by filtering at the
# point processed_games is built in update(), so both branches inherit it.
def _final_game(gid, home, away, days_ago=1):
    return {
        "id": gid,
        "home_abbr": home,
        "away_abbr": away,
        "is_final": True,
        "clock": "0:00",
        "period": 4,
        "status_text": "Final",
        "start_time_utc": datetime.now(timezone.utc) - timedelta(days=days_ago),
        "home_score": "20",
        "away_score": "17",
    }


recent = NFLRecentManager.__new__(NFLRecentManager)
recent.logger = type("StubLogger", (), {"__getattr__": lambda self, _n: (lambda *a, **k: None)})()
recent.sport_key = "nfl"
recent.favorite_teams = []
recent.exclude_teams = ["SF"]
recent.show_favorite_teams_only = False  # the default/no-favorites path
recent.recent_games_to_show = 5
recent.games_list = []
recent.current_game = None
recent.current_game_index = 0
recent.last_update = 0
recent.update_interval = 999999
recent.last_game_switch = 0
recent.game_display_duration = 15
recent.show_ranking = False
recent._games_lock = threading.RLock()
recent._zero_clock_timestamps = {}
recent.is_enabled = True
excluded_game = _final_game("g1", "SF", "LAD")
other_game = _final_game("g2", "SEA", "ARI")
recent._extract_game_details = lambda game_event: game_event
recent._fetch_data = lambda: {"events": [excluded_game, other_game]}
recent._fetch_team_rankings = lambda: None

recent.update()
result_ids = {g["id"] for g in recent.games_list}
check("excluded team hidden from recent/final scores in default (no-favorites) path",
      "g1" not in result_ids and "g2" in result_ids)

print()
failed = [n for n, p in results if not p]
if failed:
    print(f"{len(failed)} FAILED: {failed}")
    sys.exit(1)
print(f"All {len(results)} checks passed.")
