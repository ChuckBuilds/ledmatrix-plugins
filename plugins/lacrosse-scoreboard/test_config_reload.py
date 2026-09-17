#!/usr/bin/env python3
"""A web-UI save applies live, without restarting the display.

This plugin had no on_config_change override, so the base BasePlugin only
swapped self.config: league enables, durations, live priority, display modes,
the high-FPS flag and the per-league managers -- which read their own
translated copy of the config -- all kept their startup values until the
display service restarted, while the web UI reported the save as done.
baseball and football gained the override in #166; this is the port.

Builds the real plugin against core's test doubles (no network: nothing is
fetched until update() runs).

Run: LEDMATRIX_CORE=<core> <core-venv>/bin/python plugins/lacrosse-scoreboard/test_config_reload.py
"""

import copy
import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

logging.disable(logging.CRITICAL)
from src.plugin_system.testing import (  # noqa: E402
    MockCacheManager, MockDisplayManager, MockPluginManager)
from manager import LacrosseScoreboardPlugin as Plugin  # noqa: E402

LEAGUE = "ncaa_mens"
#: Whether display() can scroll at all (ufc's cannot; see _has_any_scroll_mode).
CAN_SCROLL = True

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def config(enabled, mode="switch", duration=30, live_priority=False):
    return {
        "enabled": True,
        "display_duration": duration,
        LEAGUE: {
            "enabled": enabled,
            "live_priority": live_priority,
            "display_modes": {"live_display_mode": mode,
                              "recent_display_mode": mode,
                              "upcoming_display_mode": mode},
        },
    }


def build(cfg):
    return Plugin("lacrosse-scoreboard", copy.deepcopy(cfg), MockDisplayManager(128, 32),
                  MockCacheManager(), MockPluginManager())


plugin = build(config(False))
check("the override exists", "on_config_change" in vars(Plugin))
check("starts with the league off", getattr(plugin, f"{LEAGUE}_enabled") is False)
check("starts without a live manager", getattr(plugin, f"{LEAGUE}_live", None) is None)
check("starts on the 1 FPS loop", plugin.enable_scrolling is False)
plugin.current_mode_index = 2

print("\nturning the league on, in scroll mode, with new durations")
plugin.on_config_change(config(True, mode="scroll", duration=45, live_priority=True))
check("league enable applied", getattr(plugin, f"{LEAGUE}_enabled") is True)
check("display_duration applied", plugin.display_duration == 45.0, f"{plugin.display_duration}")
check("live priority applied", getattr(plugin, f"{LEAGUE}_live_priority") is True)
check("display mode applied",
      plugin._display_mode_settings[LEAGUE]["live"] == "scroll",
      f"{plugin._display_mode_settings.get(LEAGUE)}")
check("managers built for the newly enabled league",
      getattr(plugin, f"{LEAGUE}_live", None) is not None)
check("the league registry sees the managers",
      plugin._league_registry[LEAGUE]["managers"]["live"] is getattr(plugin, f"{LEAGUE}_live"))
fresh = build(config(True, mode="scroll", duration=45, live_priority=True))
check("rotation modes match a fresh start with this config",
      plugin.modes == fresh.modes and any(LEAGUE in m for m in plugin.modes),
      f"{plugin.modes} vs {fresh.modes}")
check("cycling state reset", plugin.current_mode_index == 0)
check("high-FPS flag re-evaluated", plugin.enable_scrolling is CAN_SCROLL,
      f"{plugin.enable_scrolling}")

print("\nturning it back off")
plugin.on_config_change(config(False))
check("the disabled league's managers are dropped",
      getattr(plugin, f"{LEAGUE}_live", None) is None)
check("back on the 1 FPS loop", plugin.enable_scrolling is False)
fresh = build(config(False))
check("rotation modes match a fresh start with this config",
      plugin.modes == fresh.modes, f"{plugin.modes} vs {fresh.modes}")

print("\na partial save that omits 'enabled' keeps the plugin's state")
plugin.on_config_change({**config(False), "enabled": False})
check("disabled by a save", plugin.is_enabled is False)
partial = copy.deepcopy(config(False))
partial.pop("enabled")
plugin.on_config_change(partial)
check("not silently re-enabled", plugin.is_enabled is False)

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
