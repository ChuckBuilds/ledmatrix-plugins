#!/usr/bin/env python3
"""
Regression test: _extract_game_details must not crash on events that lack a
top-level "status" key -- MiLB's events (synthesized from the MLB Stats API
into an ESPN-like shape) only ever populate the competition-level status
(competitions[0].status), not a duplicate top-level one that real ESPN
events happen to also include.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_milb_status_extraction.py
"""

import logging
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from baseball import Baseball  # noqa: E402


class _ConcreteBaseball(Baseball):
    """Minimal concrete Baseball so we can call _extract_game_details
    directly without the full manager/display stack."""

    def _fetch_data(self):  # abstract in SportsCore
        return None


def _make_extractor(league="milb"):
    extractor = object.__new__(_ConcreteBaseball)
    extractor.logger = logging.getLogger("test_milb_status_extraction")
    extractor.favorite_teams = []
    extractor.league = league
    extractor.config = {}
    extractor.logo_dir = PLUGIN_DIR  # any Path-able value; not exercised
    from pathlib import Path
    extractor.logo_dir = Path(PLUGIN_DIR)
    return extractor


def _competitor(home_away, abbr, score, period_runs, hits, errors):
    return {
        "homeAway": home_away,
        "id": f"{abbr}-id",
        "score": score,
        "team": {"abbreviation": abbr, "color": "13294b", "logo": ""},
        "linescores": [
            {"period": i + 1, "displayValue": str(r)} for i, r in enumerate(period_runs)
        ],
        "statistics": [
            {"name": "hits", "displayValue": str(hits)},
            {"name": "errors", "displayValue": str(errors)},
        ],
    }


def _milb_shaped_live_event():
    """A live game event shaped the way MiLB's converter produces it --
    status only exists at competitions[0].status, never duplicated at the
    top level the way real ESPN scoreboard events do."""
    return {
        "id": "milb-event-1",
        "date": "2026-07-08T23:05:00Z",
        "competitions": [
            {
                "status": {
                    "type": {
                        "name": "STATUS_IN_PROGRESS",
                        "state": "in",
                        "detail": "Top 4th",
                        "shortDetail": "Top 4th",
                    },
                    "period": 4,
                },
                "competitors": [
                    _competitor("home", "DUR", "3", [0, 1, 0], 5, 0),
                    _competitor("away", "SWB", "2", [1, 0, 1], 4, 1),
                ],
                "situation": {
                    "count": {"balls": 1, "strikes": 2},
                    "outs": 1,
                    "onFirst": True,
                    "onSecond": False,
                    "onThird": False,
                },
            }
        ],
        # Deliberately no top-level "status" key here.
    }


def test_extract_game_details_survives_missing_top_level_status():
    extractor = _make_extractor(league="milb")
    details = extractor._extract_game_details(_milb_shaped_live_event())
    assert details is not None, "expected a valid details dict, not None (crash or malformed skip)"
    assert details["inning"] == 4, f"expected inning 4 from competition-level status period, got {details['inning']}"
    assert details["inning_half"] == "top", details["inning_half"]
    assert details["is_live"] is True
    assert details["home_abbr"] == "DUR" and details["away_abbr"] == "SWB"
    assert details["balls"] == 1 and details["strikes"] == 2 and details["outs"] == 1
    print("test_extract_game_details_survives_missing_top_level_status: PASS")


def test_extract_game_details_end_of_inning_increments_period():
    extractor = _make_extractor(league="milb")
    event = _milb_shaped_live_event()
    event["competitions"][0]["status"]["type"]["detail"] = "End of the 4th"
    event["competitions"][0]["status"]["type"]["shortDetail"] = "End 4th"
    details = extractor._extract_game_details(event)
    assert details is not None
    assert details["inning"] == 5, f"expected period+1 (5) at end-of-inning, got {details['inning']}"
    assert details["inning_half"] == "top"
    print("test_extract_game_details_end_of_inning_increments_period: PASS")


if __name__ == "__main__":
    print("MiLB status-extraction regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_extract_game_details_survives_missing_top_level_status,
        test_extract_game_details_end_of_inning_increments_period,
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
