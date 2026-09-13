#!/usr/bin/env python3
"""Selection and rotation fixes ported from football-scoreboard.

  * M3 (#345) -- Upcoming honours schedule_lookahead_days. MLB fetches the
    whole season into one cache, and selection read all of it, so the
    Upcoming screen could show a game weeks out.
  * M3 (#345) -- a mode retaking the panel gives the current card a full
    dwell. The dwell clock kept running while the mode was off screen, so the
    first frame back advanced immediately and a card was skipped.
  * M4 (#343) -- non-favourite games rotated in between hourly updates get
    their odds fetched, off the display path, instead of rendering bare.

Exercised against probe objects with the data hooks stubbed, same as
test_recent_games_get_odds.py: no display hardware, no network.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_selection_drift_ports.py
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "src" / "common" / "sports_shared.py").is_file():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

import sports  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _upcoming(gid, days_ahead):
    return {
        "id": gid, "away_abbr": "A" + gid, "home_abbr": "H" + gid,
        "is_upcoming": True,
        "start_time_utc": datetime.now(timezone.utc) + timedelta(days=days_ahead),
    }


def _make_upcoming(events):
    cls = type("UpcomingProbe", (sports.SportsUpcoming,), {
        "_fetch_data": lambda s: {"events": list(events)},
        "_extract_game_details": lambda s, ev: dict(ev),
    })
    obj = cls.__new__(cls)
    obj.is_enabled = True
    obj.last_update = 0
    obj.update_interval = 60
    obj.last_log_time = 0
    obj.log_interval = 300
    obj.last_warning_time = 0
    obj.warning_cooldown = 300
    obj.show_ranking = False
    obj.show_records = False
    obj.show_odds = False
    obj.other_games_min_quality = "any"
    obj.other_games_divisions = []
    obj.favorite_teams = []
    obj.exclude_teams = []
    obj.show_favorite_teams_only = False
    obj.upcoming_games_to_show = 10
    obj.other_upcoming_games_to_show = 10
    obj.other_rotation_interval_seconds = 0
    obj._other_window_start = 0
    obj._other_window_rotated_at = 0.0
    obj.schedule_lookahead_days = 7
    obj._team_rankings_cache = {}
    obj._division_team_ids = {}
    obj._division_loaded_at = time.monotonic()
    obj._games_lock = threading.RLock()
    obj.games_list = []
    obj.current_game = None
    obj.current_game_index = 0
    obj.last_game_switch = 0
    obj.league = "mlb"
    obj.sport = "baseball"
    obj.sport_key = "mlb"
    obj.mode_config = {}
    obj.cache_manager = None
    obj.logger = logging.getLogger("selection_probe")
    return obj


def test_lookahead_cutoff():
    print("M3: Upcoming is trimmed to schedule_lookahead_days")
    probe = _make_upcoming([_upcoming("near", 2), _upcoming("far", 30)])
    probe.update()
    shown = [g["id"] for g in probe.games_list]
    check("a game inside the window is shown", "near" in shown, shown)
    check("a game past the window is not", "far" not in shown, shown)

    probe = _make_upcoming([_upcoming("near", 2), _upcoming("far", 30)])
    probe.schedule_lookahead_days = 45
    probe.update()
    shown = [g["id"] for g in probe.games_list]
    check("widening the window brings it back", "far" in shown, shown)


def test_dwell_reset_on_reentry():
    print("\nM3: retaking the panel resets the dwell")
    probe = _make_upcoming([])
    probe.last_game_switch = time.time() - 600
    probe._last_display_call_monotonic = 0.0
    check("the first frame after a gap resets the dwell",
          probe._reset_dwell_on_reentry() is True)
    check("... to now", abs(probe.last_game_switch - time.time()) < 2,
          probe.last_game_switch)
    stamp = probe.last_game_switch
    check("consecutive frames do not reset it again",
          probe._reset_dwell_on_reentry() is False
          and probe.last_game_switch == stamp)

    probe._last_display_call_monotonic = time.monotonic() - 60
    probe.last_game_switch = time.time() - 600
    check("a gap longer than a frame counts as re-entry",
          probe._reset_dwell_on_reentry() is True)

    probe._last_display_call_monotonic = 0.0
    probe.last_game_switch = 0
    check("the 'nothing shown yet' sentinel is left alone",
          probe._reset_dwell_on_reentry() is False and probe.last_game_switch == 0)


class _Odds:
    def __init__(self):
        self.asked = []

    def get_odds(self, sport, league, event_id, update_interval_seconds=None):
        self.asked.append(event_id)
        return {"over_under": 8.5}


def _wait_for_odds_threads():
    deadline = time.time() + 5
    for thread in threading.enumerate():
        if thread.name.endswith("-rotated-odds"):
            thread.join(max(0.0, deadline - time.time()))


def test_rotated_games_get_odds():
    print("\nM4: rotated-in games get odds")
    for show_odds in (True, False):
        probe = _make_upcoming([])
        probe.show_odds = show_odds
        probe.odds_manager = _Odds()
        current = {"id": "fav", "away_abbr": "A", "home_abbr": "FAV", "odds": {"x": 1}}
        fresh = {"id": "new", "away_abbr": "B", "home_abbr": "C"}
        probe.games_list = [current]
        probe.current_game = current
        probe._advance_other_games_if_due = lambda: [current, fresh]
        changed = probe._rotate_other_games_on_display()
        _wait_for_odds_threads()
        check("show_odds=%s: the rotation swapped the slice in" % show_odds,
              changed is True)
        if show_odds:
            check("the rotated-in game got its odds", fresh.get("odds") == {"over_under": 8.5},
                  fresh.get("odds"))
            check("a game that already had odds was not asked about again",
                  probe.odds_manager.asked == ["new"], probe.odds_manager.asked)
        else:
            check("show_odds off makes no odds request",
                  probe.odds_manager.asked == [] and "odds" not in fresh,
                  probe.odds_manager.asked)


def main():
    test_lookahead_cutoff()
    test_dwell_reset_on_reentry()
    test_rotated_games_get_odds()
    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
