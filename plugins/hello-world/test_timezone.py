#!/usr/bin/env python3
"""
Regression test: the clock follows the configured LEDMatrix timezone.

update() formatted naive datetime.now(), the Pi's system zone, so a Pi on UTC
with LEDMatrix set to a local zone showed the wrong hour.

Run: python plugins/hello-world/test_timezone.py
Exit 0 pass, 2 skip (pytz missing), 1 fail.
"""

import logging
import sys
import types
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    import pytz
except ImportError:
    print("SKIP: pytz not installed")
    sys.exit(2)


def _stub_core():
    """Minimal BasePlugin mirroring the core's constructor."""
    class BasePlugin:
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config or {}
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager
            self.logger = logging.getLogger(f"test.{plugin_id}")
            self.enabled = self.config.get("enabled", True)

    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = BasePlugin
    sys.modules["src.plugin_system.base_plugin"] = mod


_stub_core()
from manager import HelloWorldPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


def far_zone():
    """A fixed-offset zone about 12 hours from this machine's system zone."""
    offset = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    target = round(offset + 12)
    if target > 14:
        target -= 24
    return "Etc/GMT" if target == 0 else "Etc/GMT%+d" % (-target)  # Etc signs are inverted


def plugin_manager(tz_name):
    return types.SimpleNamespace(
        config_manager=types.SimpleNamespace(get_timezone=lambda: tz_name))


FMT = "%I:%M %p"
tz_name = far_zone()
zone = pytz.timezone(tz_name)

p = HelloWorldPlugin("hello-world", {"enabled": True, "show_time": True},
                     types.SimpleNamespace(width=128, height=32), None,
                     plugin_manager(tz_name))
before = datetime.now(zone).strftime(FMT)
p.update()
after = datetime.now(zone).strftime(FMT)
check(f"the clock shows the time in {tz_name}", p.current_time_str in (before, after))

bad = HelloWorldPlugin("hello-world", {"enabled": True, "show_time": True},
                       types.SimpleNamespace(width=128, height=32), None,
                       plugin_manager("Not/AZone"))
before = datetime.now().strftime(FMT)
bad.update()
after = datetime.now().strftime(FMT)
check("an invalid timezone falls back to system time", bad.current_time_str in (before, after))

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
