#!/usr/bin/env python3
"""
Tests that live odds are fetched for the games on screen, not the whole slate.

The live collection loop used to call _fetch_odds for *every* live game in the
league on every update. The renderer only ever draws current_game, and a full
rotation of a big slate takes minutes while live_odds_update_interval is 60s,
so all but one of those requests expired before the game they belonged to came
round.

Measured on 2026-09-19 across a full college-football slate: 11,978 odds
requests in 13 hours on one rig -- 54% of all its ESPN traffic -- spread over
only ~140 distinct games. The eager loop also cost up to 2s of update() per
live game, because _fetch_odds waits on its worker thread, which is the
likeliest source of the 543s max_execution_time recorded for the plugin.

_wants_live_odds narrows that to the game at the rotation's current position
plus _LIVE_ODDS_LOOKAHEAD more. These checks pin:

  * the game on screen and the next one are asked about;
  * games deeper in the rotation are not;
  * a _rotation_schedule, when the lineage has one, drives the choice --
    including the repeats favourite_live_boost puts in it;
  * lineages without a schedule fall back to live_games order;
  * cold start (nothing on screen yet) lets the first pass through, so a
    fresh slate is not blank for a whole cycle;
  * an out-of-range index does not throw.

Exercised against a stand-in ``self``, same as
test_rotated_in_games_get_odds.py: no display hardware and no network.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_live_odds_follow_the_rotation.py
"""

# A test harness: it reaches into protected members on purpose, builds a
# concrete subclass at runtime, and accepts arguments only to match the
# signatures it stands in for -- none of which pylint can see as intentional.
# pylint: disable=protected-access,abstract-class-instantiated,unused-argument
# pylint: disable=broad-exception-caught

import sys
import threading
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


class _Stub:
    """Just enough of SportsLive for the predicate to read its rotation."""

    def __init__(self, live_ids, index=0, schedule=None):
        self.live_games = [{"id": i} for i in live_ids]
        self.current_game_index = index
        self._games_lock = threading.RLock()
        if schedule is not None:
            self._rotation_schedule = list(schedule)

    _LIVE_ODDS_LOOKAHEAD = sports.SportsCore._LIVE_ODDS_LOOKAHEAD
    _wants_live_odds = sports.SportsCore._wants_live_odds


def _wanted(stub, ids):
    return [i for i in ids if stub._wants_live_odds({"id": i})]


failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def main():
    ids = ["g0", "g1", "g2", "g3", "g4", "g5"]

    print("no schedule: falls back to live_games order")
    stub = _Stub(ids, index=0)
    check("the game on screen is asked about", stub._wants_live_odds({"id": "g0"}))
    check("the next one is too (lookahead=1)", stub._wants_live_odds({"id": "g1"}))
    check("the rest of the slate is not",
          _wanted(stub, ids) == ["g0", "g1"])

    print("\nthe window follows the rotation position")
    stub = _Stub(ids, index=3)
    check("g3 and g4 only", _wanted(stub, ids) == ["g3", "g4"])
    check("the game on screen a moment ago is dropped",
          not stub._wants_live_odds({"id": "g0"}))

    print("\nthe window wraps at the end of the rotation")
    stub = _Stub(ids, index=5)
    check("g5 then back round to g0", _wanted(stub, ids) == ["g0", "g5"])

    print("\na _rotation_schedule wins over live_games order")
    # favourite_live_boost repeats a favourite in the schedule; the window is
    # positional, so a repeat simply means the favourite holds the slot.
    stub = _Stub(ids, index=0, schedule=["g4", "g4", "g2", "g0"])
    check("the schedule's slot 0 is asked about", stub._wants_live_odds({"id": "g4"}))
    check("a repeat collapses -- slot 1 is the same game",
          _wanted(stub, ids) == ["g4"])
    stub = _Stub(ids, index=2, schedule=["g4", "g4", "g2", "g0"])
    check("slot 2 and 3 of the schedule", _wanted(stub, ids) == ["g0", "g2"])
    check("a live game absent from the schedule is not asked about",
          not stub._wants_live_odds({"id": "g1"}))

    print("\ncold start: nothing on screen yet")
    stub = _Stub([], index=0)
    check("every game on the first pass is let through",
          _wanted(stub, ids) == ids)

    print("\nan out-of-range index is tolerated, not thrown")
    stub = _Stub(ids, index=99)
    check("falls back to the front of the rotation",
          _wanted(stub, ids) == ["g0", "g1"])
    stub = _Stub(ids, index=-4)
    check("a negative index does too", _wanted(stub, ids) == ["g0", "g1"])

    print("\nthe slate is not asked about wholesale")
    stub = _Stub(["g%d" % i for i in range(24)], index=7)
    asked = _wanted(stub, ["g%d" % i for i in range(24)])
    check("24 live games cost 2 odds requests, not 24", len(asked) == 2)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
