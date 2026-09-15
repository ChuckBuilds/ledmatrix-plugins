#!/usr/bin/env python3
"""
Regression tests: "today" follows the configured LEDMatrix timezone, and
on_config_change refreshes self.enabled.

The entry was picked with date.today(), the Pi's system zone. A Pi on UTC with
LEDMatrix set to a local zone changed the word hours away from local midnight.

on_config_change assigned self.config directly instead of calling super(), so
self.enabled kept its old value after a web-UI save.

Run: python plugins/of-the-day/test_timezone_and_config_change.py
Exit 0 pass, 2 skip (pytz missing), 1 fail.
"""

import logging
import sys
import types
from datetime import date, datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    import pytz
except ImportError:
    print("SKIP: pytz not installed")
    sys.exit(2)


def _stub_core():
    """Minimal BasePlugin mirroring the core's constructor and on_config_change."""
    class BasePlugin:
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config or {}
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager
            self.logger = logging.getLogger(f"test.{plugin_id}")
            self.enabled = self.config.get("enabled", True)

        def on_config_change(self, new_config):
            self.config = new_config or {}
            self.enabled = self.config.get("enabled", self.enabled)

    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = BasePlugin
    sys.modules["src.plugin_system.base_plugin"] = mod


_stub_core()
from manager import OfTheDayPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


def plugin_manager(tz_name):
    return types.SimpleNamespace(
        config_manager=types.SimpleNamespace(get_timezone=lambda: tz_name))


# UTC+14 and UTC-12 are 26 hours apart, so their dates always differ, and at
# least one of them differs from this machine's system date.
system_today = date.today()
tz_name = next(name for name in ("Etc/GMT-14", "Etc/GMT+12")
               if datetime.now(pytz.timezone(name)).date() != system_today)
expected = datetime.now(pytz.timezone(tz_name)).date()

dm = types.SimpleNamespace(width=128, height=32)
p = OfTheDayPlugin("of-the-day", {"enabled": True}, dm, None, plugin_manager(tz_name))
check(f"today's entry is picked for the date in {tz_name}", p.current_day == expected)
check("items for that day loaded", bool(p.current_items))

bad = OfTheDayPlugin("of-the-day", {"enabled": True}, dm, None, plugin_manager("Not/AZone"))
check("an invalid timezone falls back to the system date",
      bad.current_day == date.today())

p.on_config_change({"enabled": False})
check("on_config_change refreshes self.enabled", p.enabled is False)
check("on_config_change stores the new config", p.config == {"enabled": False})

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
