#!/usr/bin/env python3
"""
Regression tests: "arriving today" honours the `timezone` setting and the
global LEDMatrix timezone, and the first paint does not fetch.

AfterShip ETAs were compared with date.today(), the Pi's system zone, and the
documented `timezone` override ("Override timezone for 'today'") was never read.

display() called update() when nothing had been fetched yet, putting a 10 s
provider request on the render thread.

Run: python plugins/incoming-packages/test_today_timezone_and_first_paint.py
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
from PIL import Image  # noqa: E402


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

        def on_config_change(self, new_config):
            self.config = new_config or {}
            self.enabled = self.config.get("enabled", self.enabled)

        def validate_config(self):
            return True

    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = BasePlugin
    sys.modules["src.plugin_system.base_plugin"] = mod


_stub_core()
from manager import IncomingPackagesPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


class FakeDM:
    def __init__(self, w=128, h=32):
        self.width, self.height = w, h
        self.image = None
        self.frames = 0

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))

    def update_display(self):
        self.frames += 1


def plugin_manager(tz_name=None):
    pm = types.SimpleNamespace()
    if tz_name:
        pm.config_manager = types.SimpleNamespace(get_timezone=lambda: tz_name)
    return pm


# UTC+14 and UTC-12 are 26 hours apart, so their dates always differ, and at
# least one of them differs from this machine's system date.
tz_name = next(name for name in ("Etc/GMT-14", "Etc/GMT+12")
               if datetime.now(pytz.timezone(name)).date() != date.today())
zone_today = datetime.now(pytz.timezone(tz_name)).date()
tracking = [{"tag": "InTransit", "slug": "ups", "tracking_number": "1Z",
             "latest_estimated_delivery": {"estimated_delivery_date": zone_today.isoformat()}}]


def today_count(plugin):
    snap = plugin.provider._parse(tracking)
    return sum(c.delivering_today for c in snap.carriers)


override = IncomingPackagesPlugin(
    "incoming-packages", {"enabled": True, "provider": "aftership", "timezone": tz_name},
    FakeDM(), None, plugin_manager())
check(f"the `timezone` override ({tz_name}) decides what arrives today",
      today_count(override) == 1)

global_tz = IncomingPackagesPlugin(
    "incoming-packages", {"enabled": True, "provider": "aftership", "timezone": ""},
    FakeDM(), None, plugin_manager(tz_name))
check("an empty override follows the global LEDMatrix timezone", today_count(global_tz) == 1)

bad = IncomingPackagesPlugin(
    "incoming-packages", {"enabled": True, "provider": "aftership", "timezone": "Not/AZone"},
    FakeDM(), None, plugin_manager(tz_name))
check("an invalid override warns and falls back to the global timezone",
      today_count(bad) == 1 and bad.validate_config() is True)

# --- first paint -----------------------------------------------------------
dm = FakeDM()
p = IncomingPackagesPlugin("incoming-packages", {"enabled": True, "provider": "mock"},
                           dm, None, plugin_manager())
calls = []
real_fetch = p.provider.fetch
p.provider.fetch = lambda: calls.append(1) or real_fetch()
p.display()
check("display() before any update() does not fetch", calls == [])
check("display() before any update() still draws a frame", dm.frames == 1 and dm.image is not None)
p.update()
p.display()
check("update() then fetches, and display() shows cards", calls == [1] and bool(p._cards))

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
