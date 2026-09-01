#!/usr/bin/env python3
"""
Tests for exclude_teams + favorite_live_boost (added in manifest v1.3.0).

Covers:
  - _swrr_schedule() itself (pure function, no plugin dependencies).
  - SportsLive.update()'s live-game filter: excluded teams are always hidden,
    even with show_all_live=True, and exclusion wins over favorite_teams.
  - SportsLive.update()'s rotation schedule: favorite_live_boost=1 with no
    favorites reproduces the old plain round-robin order; boost=2 spreads the
    favorite's game evenly across the cycle instead of clustering it.
  - SportsRecent.update()'s recent-game filter: excluded teams never appear
    in recent/final results either.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_favorite_live_boost.py
"""

import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    """Stub the core ``src.*`` modules sports.py imports at load time, so this
    test can run without a full LEDMatrix core checkout on the path."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    mod("src")
    mod("src.common")
    mod("src.plugin_system")
    mod("src.logo_downloader", LogoDownloader=object, download_missing_logo=lambda *a, **k: None)
    mod("src.common.scroll_helper", ScrollHelper=object)
    mod("src.plugin_system.base_plugin", BasePlugin=None, VegasDisplayMode=object)
    mod("src.background_data_service", get_background_service=lambda *a, **k: None)


_stub_core_src()

import sports  # noqa: E402


class _StubLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _TestLive(sports.SportsLive):
    """Concrete no-op overrides of SportsLive's abstract methods, purely so
    object.__new__() can build an instance without running the real __init__
    (which needs a network session, background service, font loading —
    irrelevant here). Each test then shadows these with instance-level
    lambdas returning canned data."""

    def _extract_game_details(self, game_event):
        return game_event

    def _fetch_data(self):
        return None


class _TestRecent(sports.SportsRecent):
    def _extract_game_details(self, game_event):
        return game_event

    def _fetch_data(self):
        return None


def _make_live_manager(favorite_teams, exclude_teams, show_all_live, show_favorite_teams_only, favorite_live_boost):
    """Build a SportsLive instance without running the real __init__ (which
    needs network/session/font/background-service setup irrelevant here)."""
    live = object.__new__(_TestLive)
    live.logger = _StubLogger()
    live.sport_key = "ncaam_lacrosse"
    live.favorite_teams = favorite_teams
    live.exclude_teams = exclude_teams
    live.show_all_live = show_all_live
    live.show_favorite_teams_only = show_favorite_teams_only
    live.favorite_live_boost = favorite_live_boost
    live.live_games = []
    live._rotation_schedule = []
    live.current_game = None
    live.current_game_index = 0
    live.game_update_timestamps = {}
    live.last_log_time = 0
    live.log_interval = 300
    live.stale_game_timeout = 300
    live.test_mode = False
    live.last_update = 0
    live.update_interval = 999999  # don't skip the update() early-return
    live.no_data_interval = 300
    live.last_game_switch = 0
    live.game_display_duration = 1
    live.show_odds = False
    live.show_ranking = False
    live._games_lock = threading.RLock()
    live.is_enabled = True

    # Bypass real ESPN parsing / odds / staleness / rankings — the fake
    # "events" below are already shaped like _extract_game_details() output.
    live._extract_game_details = lambda game_event: game_event
    live._is_game_really_over = lambda details: False
    live._fetch_odds = lambda details: None
    live._detect_stale_games = lambda games: None
    live._fetch_team_rankings = lambda: {}
    return live


def _game(gid, home, away, minutes_ago=0):
    return {
        "id": gid,
        "home_abbr": home,
        "away_abbr": away,
        "is_live": True,
        "is_halftime": False,
        "is_final": False,
        "clock": "10:00",
        "period": 2,
        "home_score": "3",
        "away_score": "2",
        "start_time_utc": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    }


def test_swrr_equal_weights_is_plain_order():
    sched = sports._swrr_schedule([("a", 1), ("b", 1), ("c", 1)])
    assert sched == ["a", "b", "c"], sched
    print("PASS: _swrr_schedule with all weight=1 matches plain order")


def test_swrr_boost_spreads_evenly():
    # Standard nginx/haproxy-style SWRR output for weights (2, 1, 1): the
    # favorite (weight 2) gets 2 of the 4 slots, queued first, with at least
    # one other game between its two appearances within the cycle.
    sched = sports._swrr_schedule([("fav", 2), ("b", 1), ("c", 1)])
    assert sched == ["fav", "b", "c", "fav"], sched
    assert sched.count("fav") == 2, sched
    print("PASS: _swrr_schedule boost=2 gives favorite 2 of 4 slots, queued first")


def test_exclude_wins_over_show_all_live():
    live = _make_live_manager(
        favorite_teams=[], exclude_teams=["DUKE"],
        show_all_live=True, show_favorite_teams_only=False, favorite_live_boost=2,
    )
    live._fetch_data = lambda: {"events": [
        _game("g1", "DUKE", "UNC"),
        _game("g2", "VIRGINIA", "MARYLAND"),
    ]}
    live.update()
    ids = {g["id"] for g in live.live_games}
    assert ids == {"g2"}, ids
    print("PASS: excluded team hidden from live rotation even with show_all_live=True")


def test_exclude_wins_over_favorite_teams():
    live = _make_live_manager(
        favorite_teams=["DUKE"], exclude_teams=["DUKE"],
        show_all_live=False, show_favorite_teams_only=True, favorite_live_boost=2,
    )
    live._fetch_data = lambda: {"events": [_game("g1", "DUKE", "UNC")]}
    live.update()
    assert live.live_games == [], live.live_games
    print("PASS: exclude_teams wins when a team is in both favorite_teams and exclude_teams")


def test_boost_one_matches_plain_rotation_regression():
    live = _make_live_manager(
        favorite_teams=[], exclude_teams=[],
        show_all_live=True, show_favorite_teams_only=False, favorite_live_boost=1,
    )
    live._fetch_data = lambda: {"events": [
        _game("g1", "DUKE", "UNC", minutes_ago=5),
        _game("g2", "VIRGINIA", "MARYLAND", minutes_ago=10),
    ]}
    live.update()
    assert live._rotation_schedule == [g["id"] for g in live.live_games], live._rotation_schedule
    print("PASS: favorite_live_boost=1 with no favorites reproduces plain rotation order")


def test_boost_two_favorite_appears_twice_per_cycle():
    live = _make_live_manager(
        favorite_teams=["DUKE"], exclude_teams=[],
        show_all_live=True, show_favorite_teams_only=False, favorite_live_boost=2,
    )
    live._fetch_data = lambda: {"events": [
        _game("fav", "DUKE", "UNC", minutes_ago=1),
        _game("g2", "VIRGINIA", "MARYLAND", minutes_ago=5),
        _game("g3", "SYRACUSE", "CORNELL", minutes_ago=10),
    ]}
    live.update()
    schedule = live._rotation_schedule
    assert schedule.count("fav") == 2, schedule
    assert schedule[0] == "fav", schedule  # queued first
    # evenly spaced, not clustered: no two "fav" entries adjacent
    fav_positions = [i for i, gid in enumerate(schedule) if gid == "fav"]
    assert fav_positions[1] - fav_positions[0] > 1, schedule
    print(f"PASS: favorite_live_boost=2 gives favorite 2 of {len(schedule)} evenly-spaced slots: {schedule}")


def test_recent_games_hide_excluded_team():
    recent = object.__new__(_TestRecent)
    recent.logger = _StubLogger()
    recent.favorite_teams = []
    recent.exclude_teams = ["DUKE"]
    recent.show_favorite_teams_only = False
    recent.recent_games_to_show = 5
    recent.games_list = []
    recent.current_game = None
    recent.current_game_index = 0
    recent.last_update = 0
    recent.update_interval = 999999
    recent.last_game_switch = 0
    recent.game_display_duration = 1
    recent.show_ranking = False
    recent._games_lock = threading.RLock()
    recent._zero_clock_timestamps = {}
    recent.is_enabled = True
    recent.show_odds = False  # update() offers the selected finals their odds

    final_game = _game("g1", "DUKE", "UNC")
    final_game.update({"is_final": True, "start_time_utc": datetime.now(timezone.utc) - timedelta(days=1)})
    other_game = _game("g2", "VIRGINIA", "MARYLAND")
    other_game.update({"is_final": True, "start_time_utc": datetime.now(timezone.utc) - timedelta(days=1)})

    recent._extract_game_details = lambda game_event: game_event
    recent._fetch_data = lambda: {"events": [final_game, other_game]}
    recent._fetch_team_rankings = lambda: {}

    recent.update()
    ids = {g["id"] for g in recent.games_list}
    assert ids == {"g2"}, ids
    print("PASS: excluded team hidden from recent/final scores too")


if __name__ == "__main__":
    tests = [
        test_swrr_equal_weights_is_plain_order,
        test_swrr_boost_spreads_evenly,
        test_exclude_wins_over_show_all_live,
        test_exclude_wins_over_favorite_teams,
        test_boost_one_matches_plain_rotation_regression,
        test_boost_two_favorite_appears_twice_per_cycle,
        test_recent_games_hide_excluded_team,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
    if failures:
        print(f"\n{failures}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed")
