#!/usr/bin/env python3
"""
Regression test: football-scoreboard applies config edits live.

Before this fix the plugin had no on_config_change override, so the base
BasePlugin only swapped self.config: league enables, durations, live priority,
display-mode settings, the per-league managers and the rotation mode list all
kept their startup values until a display restart. This test fails against the
base behavior and passes once the plugin re-derives state on config change.

Leagues are left disabled so no network managers are constructed, but the full
re-derive / rebuild path still runs.

Run with the core venv from within a LEDMatrix tree, or set LEDMATRIX_CORE:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/football-scoreboard/test_config_reload.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

from manager import FootballScoreboardPlugin  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS: {msg}")
    else:
        _failed += 1
        print(f"  FAIL: {msg}")
        raise AssertionError(msg)


class _Matrix:
    width = 128
    height = 32


class _DisplayManager:
    matrix = _Matrix()


def _make_plugin(config):
    return FootballScoreboardPlugin(
        "football-scoreboard",
        config,
        display_manager=_DisplayManager(),
        cache_manager=object(),
        plugin_manager=object(),
    )


def test_on_config_change_applies_live():
    print("[football-scoreboard on_config_change]")
    plugin = _make_plugin(
        {
            "display_duration": 30,
            "nfl": {"enabled": False, "live_priority": False,
                    "display_modes": {"live_display_mode": "switch"}},
        }
    )
    check(plugin.display_duration == 30.0, "initial display_duration derived")
    check(plugin.nfl_live_priority is False, "initial nfl live_priority derived")
    check(plugin._display_mode_settings["nfl"]["live"] == "switch", "initial display mode setting derived")

    # Prime cycling state so we can confirm it is reset on change.
    plugin.current_mode_index = 5

    plugin.on_config_change(
        {
            "display_duration": 45,
            "game_display_duration": 20,
            "nfl": {
                "enabled": False,
                "live_priority": True,
                "display_modes": {"live_display_mode": "scroll"},
            },
        }
    )

    check(plugin.display_duration == 45.0, "display_duration updated live")
    check(plugin.game_display_duration == 20.0, "game_display_duration updated live")
    check(plugin.nfl_live_priority is True, "nfl live_priority updated live")
    check(plugin._display_mode_settings["nfl"]["live"] == "scroll", "display mode setting updated live")
    check(plugin.current_mode_index == 0, "mode cycling reset")
    check(isinstance(plugin.modes, list) and len(plugin.modes) > 0, "rotation modes rebuilt without crashing")


if __name__ == "__main__":
    try:
        test_on_config_change_applies_live()
    except AssertionError:
        pass  # already logged by check()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
