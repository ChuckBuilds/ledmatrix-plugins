#!/usr/bin/env python3
"""Tests that the live screen can be driven offline, and draws a real scorebug.

Regression under test: live was the one screen the safety harness never
rendered. Its own fixture said why -- "NFLLiveManager._fetch_data() ->
_fetch_todays_games() is a direct network call with no cache read and no
test_mode passthrough in _adapt_config_for_manager, so the live screen can
never be fed from mock data" -- so live mode was switched off there.

Two things made it untestable, and both were latent bugs rather than gaps:

  * `_adapt_config_for_manager()` never passed `test_mode` into the per-manager
    config, so `SportsLive.test_mode` could not be set from config at all. The
    fully-seeded simulated game in `NFLLiveManager.__init__` was unreachable.
  * `SportsLive.update()` fetched unconditionally, so even with the flag set
    the seeded game was overwritten on the first tick. `_test_mode_update()`
    was defined and never called -- dead code. baseball-scoreboard had already
    fixed the same thing; this ports it.

Which matters now because the season starts in weeks and live is the screen
that carries it. Bugs in this path stay dormant all off-season, exactly as the
has_live_content log flood did (see test_live_content_log_throttle.py:
"football was dormant only because it was the off-season").

Run: <core-venv>/bin/python plugins/football-scoreboard/test_live_screen.py
"""

import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def test_config_passthrough():
    """test_mode must survive the trip from league config to manager config."""
    src = (PLUGIN_DIR / "manager.py").read_text(encoding="utf-8")
    check("_adapt_config_for_manager reads test_mode",
          'league_config.get("test_mode"' in src)
    check("and puts it in the manager config",
          '"test_mode": manager_test_mode' in src)


def test_update_short_circuits_in_test_mode():
    """update() must simulate, not fetch, or the seeded game is lost."""
    src = (PLUGIN_DIR / "sports.py").read_text(encoding="utf-8")
    idx_guard = src.find("if _test_mode_attr:")
    idx_fetch = src.find("data = self._fetch_data()", idx_guard if idx_guard >= 0 else 0)
    check("update() branches on test_mode", idx_guard != -1)
    check("_test_mode_update() is actually called",
          "self._test_mode_update()" in src)
    check("and it short-circuits before the network fetch",
          idx_guard != -1 and idx_fetch != -1 and idx_guard < idx_fetch)


def test_harness_covers_live():
    """The fixture must actually exercise the screen."""
    spec = json.loads((PLUGIN_DIR / "test" / "harness.json").read_text(encoding="utf-8"))
    nfl = spec.get("config", {}).get("nfl", {})
    check("harness enables live",
          nfl.get("display_modes", {}).get("show_live") is True)
    check("harness turns on the simulated game", nfl.get("test_mode") is True)


def test_seeded_live_game_is_complete():
    """The simulated game must carry what a live scorebug draws.

    A live card is not just a score: the clock, the quarter and the down and
    distance are the parts that only appear in this mode, so a fixture missing
    them would render something that passes without covering what matters.
    """
    src = (PLUGIN_DIR / "nfl_managers.py").read_text(encoding="utf-8")
    start = src.find("if self.test_mode:")
    end = src.find("self.live_games = [self.current_game]", start)
    block = src[start:end] if start != -1 and end != -1 else ""

    for field in ("home_score", "away_score", "period_text", "clock",
                  "down_distance_text", "possession", "home_timeouts",
                  "is_live"):
        check("seeded game carries %s" % field, '"%s"' % field in block)
    check("and is marked live", '"is_live": True' in block)


def main():
    print("the plugin can be told to simulate a live game")
    test_config_passthrough()

    print("\nand simulating means simulating, not fetching")
    test_update_short_circuits_in_test_mode()

    print("\nthe harness renders the live screen")
    test_harness_covers_live()

    print("\nthe simulated game is a real scorebug")
    test_seeded_live_game_is_complete()

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
