#!/usr/bin/env python3
"""
nfl-draft: live_refresh_interval is honoured by core's scheduler, and the
plugin loads when core's hardware init failed.

Regressions under test:

1. Core resolves a plugin's update cadence as get_update_interval() hook, then
   the manifest's update_interval, then config. The manifest says 300 and the
   plugin had no hook, so update() ran every 300s whatever live_refresh_interval
   said: the schema allows 60-1800, but anything under 300 never happened on
   draft day. get_update_interval() now returns live_refresh_interval while the
   draft is live or in its date window, and None otherwise (the manifest's
   300s tick, which update() self-throttles to projection_refresh_interval).
2. __init__ read display_manager.matrix.width, which raises when matrix is None
   (core's hardware init failed), so the plugin failed to load.

The plugin is built through its real __init__ with the background fetch thread
stubbed out (no network), in a scratch working directory so the logo install
does not write into the core checkout.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/nfl-draft/test_update_interval_and_init.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import json
import logging
import os
import sys
import tempfile
import threading
from datetime import datetime as _real_datetime
from pathlib import Path
from types import SimpleNamespace

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break
else:
    print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
    sys.exit(2)
os.environ.setdefault("EMULATOR", "true")
# A scratch working directory: importing the emulator writes
# emulator_config.json into the cwd, and __init__ installs the draft logo
# under assets/.
old_cwd = os.getcwd()
scratch = tempfile.mkdtemp(prefix="nfl-draft-test-")
os.chdir(scratch)

from PIL import Image  # noqa: E402

try:
    from src.display_manager import DisplayManager  # noqa: E402
except ImportError as exc:  # no rgbmatrix and no emulator installed
    print("SKIP: cannot import core DisplayManager (%s)" % exc)
    sys.exit(2)
from src.plugin_system.plugin_manager import PluginManager  # noqa: E402

import manager  # noqa: E402
from manager import NFLDraftPlugin  # noqa: E402

MANIFEST = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _NoThread:
    """Stands in for the background fetch __init__ starts."""

    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def _display_manager(matrix):
    """Core's DisplayManager without its hardware __init__.

    width/height are core's own properties: matrix.width when there is a
    matrix, else the canvas size.
    """
    dm = DisplayManager.__new__(DisplayManager)
    dm.config = {"display": {"hardware": {"limit_refresh_rate_hz": 100}}}
    dm.matrix = matrix
    dm.image = Image.new("RGB", (128, 32))
    return dm


def _frozen(year, month, day):
    class _Frozen(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return _real_datetime(year, month, day, 12, 0, 0)
    return _Frozen


def _build(config, matrix=None):
    return NFLDraftPlugin("nfl-draft", dict({"enabled": True}, **config),
                          _display_manager(matrix), None, None)


def _scheduled_interval(plugin):
    """What core's scheduler uses for this plugin, with this plugin's manifest."""
    pm = PluginManager.__new__(PluginManager)
    pm.logger = logging.getLogger("test.plugin_manager")
    pm.plugin_manifests = {"nfl-draft": MANIFEST}
    pm._update_interval_cache = {}
    pm.config_manager = None
    return pm._get_plugin_update_interval("nfl-draft", plugin)


real_datetime = manager.datetime
try:
    manager.threading = type("T", (), {"Thread": _NoThread, "Lock": threading.Lock})

    print("hardware init failed (display_manager.matrix is None)")
    try:
        plugin = _build({"live_refresh_interval": 60})
        check("the plugin loads", True)
    except AttributeError as exc:
        check(f"the plugin loads ({exc})", False)
        plugin = None
    if plugin is not None:
        check("dimensions come from the canvas (128x32)",
              (plugin.display_width, plugin.display_height) == (128, 32))
    else:  # keep the interval checks independent of the init bug
        plugin = _build({"live_refresh_interval": 60},
                        matrix=SimpleNamespace(width=128, height=32))

    plugin._fetch_draft_picks = lambda round_num=None: []
    plugin._create_draft_scroll_image = lambda: None

    print("off-season: the manifest's tick")
    manager.datetime = _frozen(2026, 9, 16)
    plugin.update()
    check("get_update_interval() has no opinion off-season",
          plugin.get_update_interval() is None)
    check("core schedules update() on the manifest's 300s",
          _scheduled_interval(plugin) == 300.0)

    print("draft week: live_refresh_interval")
    manager.datetime = _frozen(2027, 4, 24)
    plugin.last_update_time = None
    plugin.update()
    check("get_update_interval() returns live_refresh_interval (60) in the draft window",
          plugin.get_update_interval() == 60.0)
    check("core schedules update() every 60s, under the manifest's 300",
          _scheduled_interval(plugin) == 60.0)

    print("the draft goes live outside the date window")
    manager.datetime = _frozen(2027, 5, 2)
    plugin.is_draft_live = False
    plugin.last_update_time = None

    def _goes_live(round_num=None):
        plugin.is_draft_live = True
        return []
    plugin._fetch_draft_picks = _goes_live
    plugin.update()
    check("a fetch that sees the draft live switches to live_refresh_interval",
          plugin.get_update_interval() == 60.0)

    print("a saved interval applies")
    plugin.on_config_change(dict(plugin.config, live_refresh_interval=900))
    check("get_update_interval() follows a saved live_refresh_interval (900)",
          plugin.get_update_interval() == 900.0)

    print("a bad value never raises into the scheduler")
    plugin.live_refresh_interval = "soon"
    check("a non-numeric live_refresh_interval returns None",
          plugin.get_update_interval() is None)
finally:
    manager.threading = threading
    manager.datetime = real_datetime
    os.chdir(old_cwd)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
