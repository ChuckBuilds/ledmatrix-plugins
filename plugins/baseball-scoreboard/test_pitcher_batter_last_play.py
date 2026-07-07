#!/usr/bin/env python3
"""
Regression tests for the pitcher/batter/last-play parsing helpers in
baseball.py (backing the "at-bat info" rotating screen).

Covers:
  1. CLEAN_PLAY_TYPE_MAP coverage for every mapped ESPN `type.type`.
  2. Keyword fallback for walks/strikeouts (no dedicated ESPN type).
  3. Hide-on-no-match: an unrecognized play returns None rather than a guess.
  4. Backward-scan correctness for both last-play and pitcher/batter,
     skipping trailing empty transition-marker plays.
  5. Roster join across both teams for the athlete-id -> name map.
  6. Cache pruning for games no longer live.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_pitcher_batter_last_play.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from baseball import (  # noqa: E402
    BaseballLive,
    CLEAN_PLAY_TYPE_MAP,
    _build_athlete_name_map,
    _get_current_pitcher_batter,
    _get_last_play_code,
    _map_play_type,
)


def _play(play_type="", text="", participants=None):
    return {
        "type": {"type": play_type} if play_type else {},
        "text": text,
        "participants": participants or [],
    }


def _participant(role, athlete_id):
    return {"type": role, "athlete": {"id": athlete_id}}


def test_clean_type_map_coverage():
    for espn_type, expected_code in CLEAN_PLAY_TYPE_MAP.items():
        code = _map_play_type(_play(play_type=espn_type))
        assert code == expected_code, f"{espn_type} -> expected {expected_code}, got {code}"
    print("test_clean_type_map_coverage: PASS")


def test_keyword_fallback_walk_and_strikeout():
    walk = _map_play_type(_play(play_type="play-result", text="Vientos walked, Bichette to second."))
    assert walk == "BB", f"expected BB for a walk, got {walk}"

    strikeout = _map_play_type(_play(play_type="play-result", text="Judge struck out swinging."))
    assert strikeout == "K", f"expected K for a strikeout, got {strikeout}"
    print("test_keyword_fallback_walk_and_strikeout: PASS")


def test_hide_on_no_match():
    code = _map_play_type(_play(play_type="play-result", text="Mound visit by the pitching coach."))
    assert code is None, f"expected None for an unmapped play, got {code}"

    plays = [_play(play_type="play-result", text="Mound visit by the pitching coach.")]
    assert _get_last_play_code(plays) is None, "should hide rather than guess when nothing matches"
    print("test_hide_on_no_match: PASS")


def test_last_play_skips_trailing_empty_markers():
    plays = [
        _play(play_type="single", text="Judge singled to right field."),
        _play(play_type="", text=""),  # trailing transition marker, e.g. end of inning
    ]
    code = _get_last_play_code(plays)
    assert code == "1B", f"expected to skip the empty marker and find 1B, got {code}"
    print("test_last_play_skips_trailing_empty_markers: PASS")


def test_last_play_uses_most_recent_only():
    plays = [
        _play(play_type="single", text="Judge singled to right field."),
        _play(play_type="strike-out", text="Stanton struck out."),  # unmapped clean type, no keyword match on this text alone (but has real text)
    ]
    # The most recent substantive play ("strike-out"/"struck out") should win,
    # not the earlier single -- even though "strike-out" isn't in
    # CLEAN_PLAY_TYPE_MAP, its text does match the "struck out" keyword.
    code = _get_last_play_code(plays)
    assert code == "K", f"expected the most recent play (K) to win, got {code}"
    print("test_last_play_uses_most_recent_only: PASS")


def test_build_athlete_name_map_joins_both_teams():
    rosters = [
        {"roster": [{"athlete": {"id": "1", "shortName": "A. Judge"}}]},
        {"roster": [{"athlete": {"id": "2", "shortName": "S. Vientos"}}]},
    ]
    names = _build_athlete_name_map(rosters)
    assert names == {"1": "A. Judge", "2": "S. Vientos"}, f"unexpected map: {names}"
    print("test_build_athlete_name_map_joins_both_teams: PASS")


def test_get_current_pitcher_batter_backward_scan():
    names = {"10": "G. Cole", "20": "J. Soto"}
    plays = [
        _play(participants=[_participant("pitcher", "10"), _participant("batter", "20")]),
        _play(),  # trailing transition marker with no participants
    ]
    pitcher, batter = _get_current_pitcher_batter(plays, names)
    assert pitcher == "G. Cole" and batter == "J. Soto", f"got pitcher={pitcher}, batter={batter}"
    print("test_get_current_pitcher_batter_backward_scan: PASS")


def test_get_current_pitcher_batter_no_participants_returns_none():
    pitcher, batter = _get_current_pitcher_batter([_play(), _play()], {})
    assert pitcher is None and batter is None
    print("test_get_current_pitcher_batter_no_participants_returns_none: PASS")


class _ConcreteBaseballLive(BaseballLive):
    """Minimal concrete BaseballLive so we can instantiate without the full
    manager stack (mirrors test_favorite_live_boost.py's _ConcreteLive)."""

    def _extract_game_details(self, game_event):  # abstract in SportsCore
        return None

    def _fetch_data(self):  # abstract in SportsCore
        return None


def _make_live():
    live = object.__new__(_ConcreteBaseballLive)
    live._play_by_play_cache = {"g1": {"pitcher": "A"}, "g2": {"pitcher": "B"}}
    live._play_by_play_last_attempt = {"g1": 100.0, "g2": 200.0, "g3": 300.0}
    live.live_games = [{"id": "g1"}]
    return live


def test_prune_stale_play_by_play():
    live = _make_live()
    live._prune_stale_play_by_play()
    assert list(live._play_by_play_cache.keys()) == ["g1"], live._play_by_play_cache
    assert list(live._play_by_play_last_attempt.keys()) == ["g1"], live._play_by_play_last_attempt
    print("test_prune_stale_play_by_play: PASS")


class _StubDataSource:
    def __init__(self, response):
        self._response = response

    def fetch_game_summary(self, sport, league, game_id):
        return self._response


def _make_live_for_fetch(response):
    live = object.__new__(_ConcreteBaseballLive)
    live._play_by_play_cache = {"g1": {"pitcher": "G. Cole", "batter": "J. Soto", "last_play_code": "1B"}}
    live.espn_summary_sport_league = ("baseball", "mlb")
    live.data_source = _StubDataSource(response)
    import logging
    live.logger = logging.getLogger("test_fetch_play_by_play")
    return live


def test_fetch_play_by_play_keeps_prior_cache_on_empty_response():
    # A "successful" response with no plays/rosters (e.g. right before the
    # game starts) must not clobber a previously-good cache entry.
    live = _make_live_for_fetch({"plays": [], "rosters": []})
    live._fetch_play_by_play("g1")
    assert live._play_by_play_cache["g1"] == {
        "pitcher": "G. Cole", "batter": "J. Soto", "last_play_code": "1B"
    }, live._play_by_play_cache
    print("test_fetch_play_by_play_keeps_prior_cache_on_empty_response: PASS")


def test_fetch_play_by_play_updates_cache_on_real_data():
    names = {"10": "Y. Yamamoto", "20": "F. Freeman"}
    rosters = [
        {"roster": [{"athlete": {"id": "10", "shortName": names["10"]}}]},
        {"roster": [{"athlete": {"id": "20", "shortName": names["20"]}}]},
    ]
    plays = [_play(participants=[_participant("pitcher", "10"), _participant("batter", "20")])]
    live = _make_live_for_fetch({"plays": plays, "rosters": rosters})
    live._fetch_play_by_play("g1")
    assert live._play_by_play_cache["g1"]["pitcher"] == "Y. Yamamoto"
    assert live._play_by_play_cache["g1"]["batter"] == "F. Freeman"
    print("test_fetch_play_by_play_updates_cache_on_real_data: PASS")


if __name__ == "__main__":
    print("pitcher/batter/last-play parsing regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_clean_type_map_coverage,
        test_keyword_fallback_walk_and_strikeout,
        test_hide_on_no_match,
        test_last_play_skips_trailing_empty_markers,
        test_last_play_uses_most_recent_only,
        test_build_athlete_name_map_joins_both_teams,
        test_get_current_pitcher_batter_backward_scan,
        test_get_current_pitcher_batter_no_participants_returns_none,
        test_prune_stale_play_by_play,
        test_fetch_play_by_play_keeps_prior_cache_on_empty_response,
        test_fetch_play_by_play_updates_cache_on_real_data,
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
