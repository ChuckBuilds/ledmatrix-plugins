#!/usr/bin/env python3
"""
Tests that schedule_lookahead_days actually bounds the Upcoming screen.

The ranged fetch uses the horizon, but selection reads the season-wide
background cache, so every fixture ESPN had published was eligible: with
no NFL football inside a 7-day window, a live board filled with games up
to four weeks out while the config's own description promised "a fixture
just beyond this horizon ... never reaches the board" and the
favourite-check advisory claimed the empty screen was expected.
SportsUpcoming.update() now applies the cutoff to selection, mirroring
the lookback cutoff on the Recent screen.

These checks pin:

  * fixtures inside the window are selected, fixtures beyond it never are;
  * favourites obey the same window (it is a window, not a filter);
  * a probe with no schedule_lookahead_days attribute falls back to the
    default rather than raising.

Exercised against a probe subclass with the data hooks stubbed, same as
test_recent_games_get_odds.py: no display hardware, no network.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_lookahead_window_is_enforced.py
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


def _upcoming(gid, away, home, days_out):
    return {
        "id": gid,
        "away_abbr": away,
        "home_abbr": home,
        "is_upcoming": True,
        "start_time_utc": datetime.now(timezone.utc) + timedelta(days=days_out),
    }


def _make(events, favorites, lookahead=7):
    cls = type("UpcomingWindowProbe", (sports.SportsUpcoming,), {
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
    obj.upcoming_games_to_show = 5
    obj.other_upcoming_games_to_show = 5
    obj.other_rotation_interval_seconds = 0
    obj._other_window_start = 0
    obj._other_window_rotated_at = 0.0
    if lookahead is not None:
        obj.schedule_lookahead_days = lookahead
    obj._team_rankings_cache = {}
    obj._division_team_ids = {}
    obj._division_loaded_at = time.monotonic()
    obj._games_lock = threading.RLock()
    obj._zero_clock_timestamps = {}
    obj.games_list = []
    obj.upcoming_games = []
    obj.current_game = None
    obj.current_game_index = 0
    obj.last_game_switch = 0
    obj.last_warning_time = 0
    obj.warning_cooldown = 300
    obj.league = "nfl"
    obj.sport = "football"
    obj.sport_key = "nfl"
    obj.cache_manager = None
    obj.logger = logging.getLogger("lookahead_probe")
    obj.show_odds = False
    return obj


failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def main():
    events = [
        _upcoming("near", "NE", "SEA", days_out=3),
        _upcoming("edge", "CLE", "CIN", days_out=6),
        _upcoming("far", "MIN", "TB", days_out=27),        # favourite, but weeks out
        _upcoming("mid", "LV", "LAC", days_out=13),
    ]

    print("a 7-day window keeps the near games and drops the distant ones")
    probe = _make(events, favorites=["TB"])
    probe.update()
    shown = sorted(g["id"] for g in probe.games_list)
    check("only fixtures inside the window are selected",
          shown == ["edge", "near"], shown)
    check("a favourite's game beyond the window is not exempt",
          "far" not in shown, shown)

    print("\na wider window admits more of the schedule")
    probe = _make(events, favorites=["TB"], lookahead=30)
    probe.update()
    shown = sorted(g["id"] for g in probe.games_list)
    check("all four fixtures fall inside 30 days", len(shown) == 4, shown)

    print("\nno schedule_lookahead_days attribute: the default applies")
    probe = _make(events, favorites=[], lookahead=None)
    probe.update()
    shown = sorted(g["id"] for g in probe.games_list)
    check("update() does not raise and uses the %d-day default"
          % sports._DEFAULT_LOOKAHEAD_DAYS,
          shown == ["edge", "near"], shown)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
