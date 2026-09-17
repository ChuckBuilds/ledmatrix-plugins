#!/usr/bin/env python3
"""
Regression test: the core schedules update() at the configured update_interval.

The core's scheduler (PluginManager._get_plugin_update_interval) asks the
plugin's get_update_interval() hook first, then uses the manifest's
update_interval, and reads the plugin config only when the manifest has none.
This plugin's manifest says 45, and it had no hook, so update_interval is read and never used.

Runs the core's own resolution against the real plugin, so it needs a LEDMatrix
checkout (core 3.4.0 or newer, where the hook exists).

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/geochron/test_update_interval_hook.py
Exit 0 pass, 2 skip, 1 fail.
"""

import json
import logging
import os
import socket
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

try:
    from src.plugin_system.plugin_manager import PluginManager
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager,
    )
except ImportError as exc:
    print("SKIP: core imports unavailable (%s)" % exc)
    sys.exit(2)

if not hasattr(PluginManager, "_dynamic_update_interval"):
    print("SKIP: core predates get_update_interval() (needs 3.4.0)")
    sys.exit(2)


def _no_network(*_args, **_kwargs):
    raise OSError("network disabled in this test")


socket.socket.connect = _no_network
logging.disable(logging.CRITICAL)

from manager import GeochronPlugin  # noqa: E402

PLUGIN_ID = "geochron"
failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def scheduler_interval(plugin):
    """The interval the core's scheduler would use for this plugin."""
    with open(PLUGIN_DIR / "manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    pm = PluginManager.__new__(PluginManager)
    pm.logger = logging.getLogger("test-scheduler")
    pm._update_interval_cache = {}
    pm.plugin_manifests = {PLUGIN_ID: manifest}
    pm.config_manager = None
    return pm._get_plugin_update_interval(PLUGIN_ID, plugin)


with open(PLUGIN_DIR / "manifest.json", encoding="utf-8") as _f:
    MANIFEST_INTERVAL = json.load(_f)["update_interval"]

plugin = GeochronPlugin(
    PLUGIN_ID,
    {"enabled": True, "update_interval": 20},
    VisualTestDisplayManager(128, 32),
    MockCacheManager(),
    MockPluginManager(),
)

print("configured update_interval 20 (manifest %s)" % MANIFEST_INTERVAL)
got = scheduler_interval(plugin)
check("scheduler uses the configured interval, not the manifest's",
      got == 20, "got %r" % got)

print("changed to 120 from the web UI")
plugin.on_config_change({"enabled": True, "update_interval": 120})
got = scheduler_interval(plugin)
check("scheduler follows the saved change without a restart",
      got == 120, "got %r" % got)

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
