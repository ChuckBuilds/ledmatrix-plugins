#!/usr/bin/env python3
"""Games rotated in between updates get their odds line.

The other-games rotation swaps a fresh slice in on the display path and does
no network work, while odds were only attached in update() -- hourly for an
upcoming list. Every slice cut between updates therefore drew no odds even with
show_odds on. The rotation now hands the new slice to
_attach_odds_to_rotated_games, which fetches in a daemon thread (ported from
football-scoreboard, #343).

Stand-ins built with __new__, a fake odds manager, no network.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_rotated_games_get_odds.py
"""

import logging
import os
import sys
import threading
import time
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    import sports  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import sports.py (%s)" % exc)
    sys.exit(2)

failures = []


def check(name, ok, detail=None):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name,
                          "" if ok or detail is None else " -- %r" % (detail,)))
    if not ok:
        failures.append(name)


class _FakeOdds:
    def __init__(self):
        self.calls = []

    def get_odds(self, sport, league, event_id, update_interval_seconds=None):
        self.calls.append((sport, league, event_id, update_interval_seconds))
        return {"over_under": 2.5}


def _probe(show_odds=True):
    cls = type("RotationProbe", (sports.SportsUpcoming,), {
        "_fetch_data": lambda s, *a, **k: None,
        "_extract_game_details": lambda s, *a, **k: None,
    })
    obj = object.__new__(cls)
    obj.show_odds = show_odds
    obj.mode_config = {"odds_update_interval": 1234}
    obj.odds_manager = _FakeOdds()
    obj.sport = "soccer"
    obj.league = "eng.1"
    obj.sport_key = "soccer_eng.1"
    obj.logger = logging.getLogger("rotation_probe")
    return obj


def _join_fetch_threads():
    deadline = time.time() + 5
    for t in threading.enumerate():
        if t.name.endswith("-rotated-odds"):
            t.join(max(0.0, deadline - time.time()))


def main():
    print("rotated-in games without odds are fetched off the display path")
    obj = _probe()
    fresh = {"id": "g1"}
    priced = {"id": "g2", "odds": {"over_under": 3.5}}
    obj._attach_odds_to_rotated_games([fresh, priced])
    _join_fetch_threads()
    check("the unpriced game got its odds", fresh.get("odds") == {"over_under": 2.5},
          fresh.get("odds"))
    ids = [c[2] for c in obj.odds_manager.calls]
    check("only the unpriced game was asked about", ids == ["g1"], ids)
    check("the configured odds interval is used",
          obj.odds_manager.calls and obj.odds_manager.calls[0][3] == 1234,
          obj.odds_manager.calls)

    print("\nshow_odds off fetches nothing")
    obj = _probe(show_odds=False)
    obj._attach_odds_to_rotated_games([{"id": "g3"}])
    _join_fetch_threads()
    check("no odds requests", obj.odds_manager.calls == [], obj.odds_manager.calls)

    print("\nthe rotation hands its new slice over")
    obj = _probe()
    handed = []
    obj._attach_odds_to_rotated_games = lambda games: handed.append(list(games))
    rebuilt = [{"id": "a", "away_abbr": "CHE", "home_abbr": "ARS"},
               {"id": "b", "away_abbr": "LIV", "home_abbr": "EVE"}]
    obj._advance_other_games_if_due = lambda: rebuilt
    obj._games_lock = threading.RLock()
    obj.games_list = [{"id": "old"}]
    obj.current_game = {"id": "old"}
    obj.current_game_index = 0
    obj.last_game_switch = 0
    changed = obj._rotate_other_games_on_display()
    check("the rotation reports a change", changed is True)
    check("the new slice was passed to the odds fetch",
          handed and [g["id"] for g in handed[0]] == ["a", "b"], handed)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
