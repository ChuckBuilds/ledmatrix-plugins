#!/usr/bin/env python3
"""
Regression tests for exclude_teams + filtering.favorite_live_boost on the
live-game rotation (SportsLive).

Covers:
  1. An excluded team's game never appears in the live filter output, even
     with show_all_live=True.
  2. exclude_teams wins over favorite_teams when a team is in both lists.
  3. favorite_live_boost=1 + exclude_teams=[] produces the same schedule
     order as plain start-time sort (regression safety for existing users).
  4. favorite_live_boost=2 interleaves the favorite's game evenly rather
     than clumping repeats together.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_favorite_live_boost.py
"""

import os
import sys
import logging
import threading
from datetime import datetime, timedelta, timezone

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from sports import SportsLive  # noqa: E402


class _ConcreteLive(SportsLive):
    """Minimal concrete SportsLive so we can instantiate without the full
    manager stack. _fetch_data/_extract_game_details are set per-test."""

    def _extract_game_details(self, game):  # abstract in SportsCore
        return game.get("_details")

    def _fetch_data(self):  # abstract in SportsCore
        return None

    def _test_mode_update(self):  # abstract in SportsLive
        return None


def _details(game_id, home, away, start_offset_min=0):
    return {
        "id": game_id,
        "home_abbr": home,
        "away_abbr": away,
        "is_live": True,
        "is_halftime": False,
        "is_final": False,
        "clock": "5:00",
        "period": 3,
        "period_text": "Top 3rd",
        "status_text": "Q3",
        "home_score": "1",
        "away_score": "0",
        "start_time_utc": datetime.now(timezone.utc) + timedelta(minutes=start_offset_min),
    }


def _event(details):
    return {
        "_details": details,
        "competitions": [{"status": {"type": {"state": "in", "name": "In Progress"}}}],
    }


def _make_live(favorite_teams=None, exclude_teams=None, show_all_live=False,
               show_favorite_teams_only=False, favorite_live_boost=2):
    live = object.__new__(_ConcreteLive)
    live.is_enabled = True
    live.test_mode = False
    live.last_update = 0
    live.no_data_interval = 300
    live.update_interval = 30
    live.show_ranking = False
    live.show_odds = False
    live.sport_key = "mlb"
    live.logger = logging.getLogger("test_favorite_live_boost")
    live.live_games = []
    live._rotation_schedule = []
    live.current_game = None
    live.current_game_index = 0
    live.last_game_switch = 0
    live.game_display_duration = 20
    live._games_lock = threading.RLock()
    live.game_update_timestamps = {}
    live.stale_game_timeout = 300
    live.last_log_time = 0
    live.log_interval = 300
    live.favorite_teams = favorite_teams or []
    live.exclude_teams = exclude_teams or []
    live.show_all_live = show_all_live
    live.show_favorite_teams_only = show_favorite_teams_only
    live.favorite_live_boost = favorite_live_boost
    return live


def test_excluded_team_hidden_even_with_show_all_live():
    live = _make_live(exclude_teams=["LAD"], show_all_live=True)
    events = [
        _event(_details("g1", "SF", "SD")),
        _event(_details("g2", "LAD", "COL")),
    ]
    live._fetch_data = lambda: {"events": events}
    live.update()

    ids = {g["id"] for g in live.live_games}
    assert ids == {"g1"}, f"expected only g1 (LAD excluded), got {ids}"
    print("test_excluded_team_hidden_even_with_show_all_live: PASS")


def test_exclude_wins_over_favorite():
    live = _make_live(favorite_teams=["LAD"], exclude_teams=["LAD"],
                       show_favorite_teams_only=True)
    events = [
        _event(_details("g1", "LAD", "COL")),
        _event(_details("g2", "SF", "SD")),
    ]
    live._fetch_data = lambda: {"events": events}
    live.update()

    ids = {g["id"] for g in live.live_games}
    assert ids == set(), f"LAD is both favorite and excluded; exclude must win, got {ids}"
    print("test_exclude_wins_over_favorite: PASS")


def test_boost_one_matches_plain_sort():
    live = _make_live(favorite_teams=["SF"], favorite_live_boost=1, show_all_live=True)
    g1 = _details("g1", "SF", "SD", start_offset_min=5)
    g2 = _details("g2", "LAD", "COL", start_offset_min=1)
    g3 = _details("g3", "ARI", "HOU", start_offset_min=10)
    live._fetch_data = lambda: {"events": [_event(g1), _event(g2), _event(g3)]}
    live.update()

    expected_order = [g["id"] for g in sorted(
        live.live_games, key=lambda g: g["start_time_utc"]
    )]
    assert live._rotation_schedule == expected_order, (
        f"boost=1 must match plain start-time sort: "
        f"schedule={live._rotation_schedule}, expected={expected_order}"
    )
    print("test_boost_one_matches_plain_sort: PASS")


def test_boost_two_interleaves_favorite():
    live = _make_live(favorite_teams=["SF"], favorite_live_boost=2, show_all_live=True)
    g1 = _details("SF_GAME", "SF", "SD")
    g2 = _details("LAD_GAME", "LAD", "COL")
    g3 = _details("PAD_GAME", "ARI", "HOU")
    live._fetch_data = lambda: {"events": [_event(g1), _event(g2), _event(g3)]}
    live.update()

    schedule = live._rotation_schedule
    assert len(schedule) == 4, f"expected a 4-slot schedule (2+1+1 weights), got {schedule}"
    fav_count = schedule.count("SF_GAME")
    assert fav_count == 2, f"favorite should get 2 of 4 slots, got {fav_count} in {schedule}"
    # Not clumped back-to-back at the front (must not start [SF, SF, ...])
    assert not (schedule[0] == "SF_GAME" and schedule[1] == "SF_GAME"), (
        f"favorite slots should not be clumped together: {schedule}"
    )
    print(f"test_boost_two_interleaves_favorite: PASS (schedule={schedule})")


if __name__ == "__main__":
    print("exclude_teams / favorite_live_boost regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_excluded_team_hidden_even_with_show_all_live,
        test_exclude_wins_over_favorite,
        test_boost_one_matches_plain_sort,
        test_boost_two_interleaves_favorite,
    ):
        try:
            t()
        except AssertionError as e:
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
