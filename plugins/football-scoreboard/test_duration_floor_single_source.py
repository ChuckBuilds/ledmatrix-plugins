#!/usr/bin/env python3
"""One duration-floor function, and the floors it gives did not change.

The plugin carried two copies of the dynamic-duration floor lookup:
``get_dynamic_duration_floor()`` (reads only the league currently on screen)
and ``_get_duration_floor_for_mode()`` (the highest floor across every enabled
league). Only the second was ever called -- by ``get_cycle_duration`` -- and
nothing in the core calls a plugin's ``get_dynamic_duration_floor``, so the
first was dead code that looked authoritative. It was deleted rather than wired
in, because swapping ``get_cycle_duration`` onto it would change the floor for
combined modes and for any call made before a league is on screen.

This pins both halves: the dead copy is gone, and ``get_cycle_duration`` still
clamps to exactly the floors below, for per-mode, per-league, multi-league,
disabled-league and junk values.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_duration_floor_single_source.py
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
REPO = Path(__file__).resolve().parents[2]
for _c in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
    if _c and (Path(_c) / "src").is_dir():
        sys.path.insert(0, _c)
        break

logging.disable(logging.CRITICAL)

try:
    from manager import FootballScoreboardPlugin
except ImportError as exc:  # pragma: no cover - environment, not a failure
    print("SKIP: cannot import the plugin (%s); set LEDMATRIX_CORE" % exc)
    sys.exit(2)

LEAGUES = ("nfl", "ncaa_fb")
PER_GAME = 10.0
results = []


def check(name, passed, detail=None):
    results.append((name, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", name,
                           "" if passed or detail is None else " -- %r" % (detail,)))


def make_plugin(league_blocks):
    config = {"enabled": True, "timezone": "UTC"}
    for league in LEAGUES:
        config[league] = {"enabled": False}
    config.update(league_blocks)
    dm = MagicMock()
    dm.matrix = None
    dm.width, dm.height = 128, 32
    p = FootballScoreboardPlugin("football-scoreboard", config, dm, MagicMock(), MagicMock())
    # Drive get_cycle_duration's game-count path deterministically: one game
    # per enabled league at PER_GAME seconds, switch mode, no mode duration.
    stub = MagicMock()
    p._get_manager_for_league_mode = lambda league, mode: stub
    p._get_games_from_manager = lambda manager, mode: [{"id": "1"}]
    p._get_game_duration = lambda league, mode, manager: PER_GAME
    p._get_effective_mode_duration = lambda display_mode, mode_type: None
    p._should_use_scroll_mode = lambda mode_type: False
    p._get_display_mode = lambda league, mode_type: "switch"
    p._ensure_manager_updated = lambda manager: None
    return p


def dyn(floor=None, mode_floors=None):
    block = {}
    if floor is not None:
        block["min_duration_seconds"] = floor
    if mode_floors:
        block["modes"] = {m: {"min_duration_seconds": v} for m, v in mode_floors.items()}
    return block


# (label, league blocks, display_mode, expected floor or None)
CASES = [
    ("no floor configured", {"nfl": {"enabled": True}}, "nfl_recent", None),
    ("per-league floor", {"nfl": {"enabled": True, "dynamic_duration": dyn(60)}},
     "nfl_recent", 60.0),
    ("per-mode floor beats per-league",
     {"nfl": {"enabled": True, "dynamic_duration": dyn(60, {"recent": 90})}},
     "nfl_recent", 90.0),
    ("per-mode floor for another mode falls back to per-league",
     {"nfl": {"enabled": True, "dynamic_duration": dyn(60, {"live": 90})}},
     "nfl_recent", 60.0),
    ("highest floor across enabled leagues",
     {"nfl": {"enabled": True, "dynamic_duration": dyn(40)},
      "ncaa_fb": {"enabled": True, "dynamic_duration": dyn(75)}},
     "nfl_recent", 75.0),
    ("disabled league's floor is ignored",
     {"nfl": {"enabled": True, "dynamic_duration": dyn(40)},
      "ncaa_fb": {"enabled": False, "dynamic_duration": dyn(500)}},
     "nfl_recent", 40.0),
    ("zero and junk floors are ignored",
     {"nfl": {"enabled": True, "dynamic_duration": dyn(0, {"recent": "abc"})}},
     "nfl_recent", None),
    ("combined upcoming mode, ncaa_fb only",
     {"ncaa_fb": {"enabled": True, "dynamic_duration": dyn(None, {"upcoming": 55})}},
     "football_upcoming", 55.0),
]


def main():
    check("the unused get_dynamic_duration_floor copy is gone",
          not hasattr(FootballScoreboardPlugin, "get_dynamic_duration_floor"))

    for label, blocks, display_mode, expected in CASES:
        p = make_plugin(blocks)
        mode_type = display_mode.rsplit("_", 1)[1]
        got_floor = p._get_duration_floor_for_mode(mode_type)
        check("%s: floor = %r" % (label, expected), got_floor == expected, got_floor)
        duration = p.get_cycle_duration(display_mode)
        games = sum(1 for lg in LEAGUES if blocks.get(lg, {}).get("enabled")) \
            if display_mode.startswith("football_") else 1
        want = max(games * PER_GAME, expected or 0)
        cap = p._get_duration_cap_for_mode(mode_type)
        if cap is not None:
            want = min(want, cap)
        check("%s: get_cycle_duration clamps to it (%r)" % (label, want),
              duration == want, duration)

    failed = [n for n, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
