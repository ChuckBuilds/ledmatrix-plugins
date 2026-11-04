#!/usr/bin/env python3
"""
Tests that each dynamic-duration turn has to show every game again.

With dynamic duration on, the display controller calls reset_cycle_state()
each time a different dynamic mode takes the panel. The plugin did not
override it (the base is a no-op), and its own new-cycle detection in
_record_dynamic_progress only fires when display_mode differs from
actual_mode -- never for granular modes such as nhl_recent. So the per-game
progress from the first turn was kept forever: on every later turn
is_cycle_complete() was already True, the turn ended at the 15s minimum,
and the second game flashed for about a second. Measured live:
"Dynamic duration cycle completed for nhl_recent after 16.18s (target:
90.00s)".

These checks pin, for a two-game granular mode on a fake clock:

  * the first turn completes only once both games had their full dwell;
  * reset_cycle_state() makes is_cycle_complete() False again;
  * the next turn completes only after both games are shown again.

Uses the real plugin class with __init__ skipped: no display hardware, no
network.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_cycle_resets_on_mode_entry.py
"""

import logging
import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(plugin_dir.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

import manager as plugin_manager  # noqa: E402

MODE = "nhl_recent"
DWELL = 15.0

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now


class _RecentManager:
    """A recent-games manager showing two games."""

    def __init__(self):
        self.recent_games = [
            {"id": "1", "away_abbr": "DET", "home_abbr": "TOR"},
            {"id": "2", "away_abbr": "BOS", "home_abbr": "MTL"},
        ]
        self.games_list = self.recent_games
        self.current_game_index = 0
        self.current_game = self.recent_games[0]
        self.game_display_duration = DWELL

    def show(self, index):
        self.current_game_index = index
        self.current_game = self.recent_games[index]


def _plugin(recent):
    cls = plugin_manager.HockeyScoreboardPlugin
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("cycle_reset_probe")
    obj.modes = [MODE]
    obj.current_mode_index = 0
    obj._dynamic_feature_enabled = lambda: True
    obj._get_manager_for_mode = lambda mode: recent
    obj._get_game_duration = lambda *a, **k: DWELL
    obj._current_active_display_mode = MODE
    obj._last_display_mode = None
    obj._last_display_mode_time = 0.0
    obj._dynamic_cycle_seen_modes = set()
    obj._dynamic_mode_to_manager_key = {}
    obj._dynamic_manager_progress = {}
    obj._dynamic_managers_completed = set()
    obj._dynamic_cycle_complete = False
    obj._single_game_manager_start_times = {}
    obj._game_id_start_times = {}
    obj._display_mode_to_managers = {}
    return obj


def _show(obj, recent, clock, index, seconds):
    """Hold one game on screen, recording progress once a second."""
    recent.show(index)
    for _ in range(int(seconds) + 1):
        obj._record_dynamic_progress(recent, actual_mode=MODE, display_mode=MODE)
        clock.now += 1.0


def main():
    clock = _Clock()
    plugin_manager.time.time = clock.time
    recent = _RecentManager()
    obj = _plugin(recent)

    print("first turn: complete only once both games had their dwell")
    _show(obj, recent, clock, 0, DWELL)
    check("one game shown is not a full cycle", obj.is_cycle_complete() is False)
    _show(obj, recent, clock, 1, DWELL)
    check("both games shown completes the cycle", obj.is_cycle_complete() is True)

    print("\nother modes take the panel, then this one comes back")
    clock.now += 120.0
    obj.reset_cycle_state()
    check("the returning turn starts incomplete", obj.is_cycle_complete() is False)

    print("\nsecond turn: the games have to be shown again")
    _show(obj, recent, clock, 0, 1)
    check("a one-second look at the first game is not enough",
          obj.is_cycle_complete() is False)
    _show(obj, recent, clock, 0, DWELL)
    check("the first game alone is still not a full cycle",
          obj.is_cycle_complete() is False)
    _show(obj, recent, clock, 1, DWELL)
    check("both games shown again completes the cycle",
          obj.is_cycle_complete() is True)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
