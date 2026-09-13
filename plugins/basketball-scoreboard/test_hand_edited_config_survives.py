#!/usr/bin/env python3
"""Hand-edited config values must not crash init or silently empty a mode.

  * other_games_divisions: the adapter wrapped it in list(), so a string
    "fcs" became ['f','c','s'] (matching no division, so every non-favourite
    game was rejected) and null raised TypeError inside the translation,
    which left every manager None. It is now passed through raw, for
    sports.py's own coercion.
  * Infinity: json parses a bare Infinity and int(inf) raises OverflowError,
    which _clamp_window and _setting_int did not catch -- a crash in manager
    init.
  * test_mode was never forwarded, so the simulated live game could not be
    switched on from config.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_hand_edited_config_survives.py
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def main():
    os.chdir(str(CORE))
    from unittest.mock import MagicMock
    import sports
    import manager as plugin_manager

    cls = plugin_manager.BasketballScoreboardPlugin
    plugin = cls.__new__(cls)
    plugin.logger = logging.getLogger("test")
    plugin.cache_manager = MagicMock()
    plugin.plugin_manager = MagicMock()

    def adapted_block(league_config):
        plugin.config = {"nba": league_config}
        return plugin._adapt_config_for_manager("nba")["nba_scoreboard"]

    block = adapted_block({"game_limits": {"other_games_divisions": "fcs"}})
    check("a string division is passed through whole, not split into letters",
          block["other_games_divisions"] == "fcs")
    try:
        block = adapted_block({"game_limits": {"other_games_divisions": None}})
        ok = block["other_games_divisions"] is None
    except TypeError:
        ok = False
    check("a null division list does not raise inside the translation", ok)
    block = adapted_block({"game_limits": {"other_games_divisions": ["fbs", "fcs"]}})
    check("a normal list still arrives", block["other_games_divisions"] == ["fbs", "fcs"])

    check("test_mode is forwarded", adapted_block({"test_mode": True})["test_mode"] is True)

    inf = float("inf")
    try:
        ok = sports._clamp_window(inf, 7) == 7
    except OverflowError:
        ok = False
    check("_clamp_window: Infinity falls back instead of raising", ok)

    class _Stub:
        league = "nba"
        logger = logging.getLogger("test")
        mode_config = {"other_upcoming_games_to_show": inf}
        _setting_int = sports.SportsCore._setting_int

    try:
        ok = _Stub()._setting_int("other_upcoming_games_to_show", 3, 0, 20) == 3
    except OverflowError:
        ok = False
    check("_setting_int: Infinity falls back instead of raising", ok)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
