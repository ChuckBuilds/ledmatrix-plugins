#!/usr/bin/env python3
"""
Regression tests: games that did not finish must not show as Final or live.

- A postponed/cancelled game (MiLB files these under abstractGameState
  "Final"; ESPN under state "post" with a "0" score) rendered on Recent as
  "Final 0-0".
- A suspended game (MiLB "Live"; ESPN possibly state "in") stayed in the
  live rotation all day, and ESPN's "end" substring check read "suspended"
  as end-of-inning, bumping the inning.
- An MiLB game in Warmup (Stats API "Live", no inning yet) drew "▼0".
- MiLB live asked the Stats API for the UTC date, i.e. tomorrow from 8 pm
  Eastern, dropping every night game in progress.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_game_status_mapping.py
Exit 0 pass, 1 fail.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import pytz  # noqa: E402

import milb_managers  # noqa: E402
from baseball import Baseball, BaseballLive  # noqa: E402
from milb_managers import BaseMiLBManager  # noqa: E402


class _ConcreteBaseball(Baseball):
    def _fetch_data(self):
        return None


class _ConcreteLive(BaseballLive):
    def _fetch_data(self):
        return None


def _bare(cls, league="milb"):
    obj = object.__new__(cls)
    obj.logger = logging.getLogger("test_game_status_mapping")
    obj.favorite_teams = []
    obj.league = league
    obj.config = {}
    obj.logo_dir = Path(PLUGIN_DIR)
    return obj


def _stats_game(abstract, detailed, linescore=None, home_score=0, away_score=0):
    return {
        "gamePk": 777001,
        "gameDate": "2025-07-04T23:05:00Z",
        "status": {"abstractGameState": abstract, "detailedState": detailed},
        "teams": {
            "home": {"team": {"id": 1, "name": "Durham Bulls", "abbreviation": "DUR"},
                     "score": home_score},
            "away": {"team": {"id": 2, "name": "Norfolk Tides", "abbreviation": "NOR"},
                     "score": away_score},
        },
        "linescore": linescore or {},
    }


def _details_from_stats(game):
    event = BaseMiLBManager._convert_stats_game_to_espn_event(game)
    details = _bare(_ConcreteBaseball)._extract_game_details(event)
    assert details is not None, "extractor returned None"
    return details


def _check_not_played(details, label):
    assert details["is_final"] is False, f"{label}: is_final should be False"
    assert details["is_live"] is False, f"{label}: is_live should be False"
    assert details["is_upcoming"] is False, f"{label}: is_upcoming should be False"


def test_milb_postponed_and_cancelled_are_not_final():
    for detailed in ("Postponed", "Cancelled"):
        _check_not_played(_details_from_stats(_stats_game("Final", detailed)), detailed)


def test_milb_suspended_is_not_live():
    ls = {"currentInning": 7, "inningState": "Top", "currentInningOrdinal": "7th"}
    for detailed in ("Suspended", "Suspended: Rain"):
        _check_not_played(_details_from_stats(_stats_game("Live", detailed, ls)), detailed)


def test_milb_warmup_is_pregame():
    details = _details_from_stats(_stats_game("Live", "Warmup"))
    assert details["is_upcoming"] is True, "Warmup should be upcoming"
    assert details["is_live"] is False


def test_milb_live_without_inning_defaults_to_top_first():
    event = BaseMiLBManager._convert_stats_game_to_espn_event(
        _stats_game("Live", "In Progress", {"inningState": ""}))
    assert event["competitions"][0]["status"]["period"] == 1
    details = _bare(_ConcreteBaseball)._extract_game_details(event)
    assert details["is_live"] is True
    assert details["inning"] == 1, details["inning"]
    assert details["inning_half"] == "top", details["inning_half"]


def test_milb_real_finals_still_final():
    details = _details_from_stats(_stats_game("Final", "Final", {"currentInning": 10}, 4, 3))
    assert details["is_final"] is True
    assert details["status_text"] == "Final/10", details["status_text"]
    for detailed in ("Game Over", "Completed Early: Rain"):
        assert _details_from_stats(_stats_game("Final", detailed))["is_final"] is True, detailed


def _espn_event(name, state, completed, detail, short, period=7):
    return {
        "id": "espn-1",
        "date": "2025-04-05T17:05:00Z",
        "competitions": [{
            "status": {"type": {"name": name, "state": state, "completed": completed,
                                "detail": detail, "shortDetail": short},
                       "period": period},
            "competitors": [
                {"homeAway": "home", "id": "10", "score": "0",
                 "team": {"id": "10", "abbreviation": "NYY", "logo": ""}},
                {"homeAway": "away", "id": "20", "score": "0",
                 "team": {"id": "20", "abbreviation": "BOS", "logo": ""}},
            ],
            "situation": {},
        }],
    }


def test_espn_postponed_is_not_final():
    details = _bare(_ConcreteBaseball, "mlb")._extract_game_details(
        _espn_event("STATUS_POSTPONED", "post", False, "Postponed", "Postponed"))
    _check_not_played(details, "ESPN postponed")
    # A post-state game without ESPN's completed flag is not final either.
    details = _bare(_ConcreteBaseball, "mlb")._extract_game_details(
        _espn_event("STATUS_FINAL", "post", False, "Final", "Final"))
    assert details["is_final"] is False
    details = _bare(_ConcreteBaseball, "mlb")._extract_game_details(
        _espn_event("STATUS_FINAL", "post", True, "Final", "Final"))
    assert details["is_final"] is True


def test_espn_suspended_in_state_is_dropped_from_live():
    event = _espn_event("STATUS_SUSPENDED", "in", False,
                        "Suspended - Top 7th", "Suspended")
    live = _bare(_ConcreteLive, "mlb")
    details = live._extract_game_details(event)
    assert details["is_live"] is False, "suspended should not be is_live"
    assert details["inning"] == 7, f"'suspended' read as end-of-inning: {details['inning']}"
    assert live._is_game_really_over(details) is True
    # A genuine end-of-inning still advances.
    end = live._extract_game_details(
        _espn_event("STATUS_IN_PROGRESS", "in", False, "End of the 7th", "End 7th"))
    assert end["inning"] == 8 and end["inning_half"] == "top"
    assert live._is_game_really_over(end) is False


def test_milb_live_fetch_uses_eastern_date_with_lookback():
    # 01:30 UTC on 07-05 is 21:30 EDT on 07-04: a night game is still on.
    fixed = datetime(2025, 7, 5, 1, 30, tzinfo=pytz.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    mgr = object.__new__(BaseMiLBManager)
    mgr.logger = logging.getLogger("test_game_status_mapping")
    calls = []
    mgr._fetch_from_mlb_stats_api = lambda start, end, sport_ids=None: calls.append((start, end)) or {}
    original = milb_managers.datetime
    milb_managers.datetime = _FixedDatetime
    try:
        mgr._fetch_todays_games()
    finally:
        milb_managers.datetime = original
    assert calls == [("2025-07-03", "2025-07-04")], calls


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    print("Game status mapping regression tests")
    print("=" * 55)
    failures = []
    for name, fn in list(globals().items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001 - report every failure
            failures.append(name)
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
