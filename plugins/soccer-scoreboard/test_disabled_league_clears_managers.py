#!/usr/bin/env python3
"""A league disabled at runtime must stop displaying without a restart.

on_config_change rebuilds the managers through _initialize_managers, which
skipped a disabled league outright and so left its previous managers on the
plugin. Most display paths also check the registry's enabled flag, but not all
of them: with the last enabled league turned off, _get_available_modes falls
back to the soccer_eng.1_* modes, and _get_current_manager looked those up in a
registry that still held the stale Premier League managers -- so the board kept
drawing EPL until the service restarted.

This drives the real on_config_change: build with eng.1 enabled, disable it at
runtime, and check nothing can reach the old managers; then re-enable it and
check they come back.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_disabled_league_clears_managers.py
"""

import logging
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix")):
    if _c and (Path(_c) / "src" / "plugin_system" / "base_plugin.py").exists():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

failures = []


def check(name, ok, detail=None):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name,
                          "" if ok or detail is None else " -- %r" % (detail,)))
    if not ok:
        failures.append(name)


class _Manager:
    def __init__(self, label):
        self.label = label

    def display(self, force_clear=False):
        return True

    def __repr__(self):
        return "<%s>" % self.label


def main():
    os.chdir(str(CORE))
    try:
        import manager as pm
    except ImportError as exc:
        print("SKIP: cannot import the plugin (%s)" % exc)
        return 2

    cls = pm.SoccerScoreboardPlugin
    builds = []

    def epl_factory(cfg, dm, cm):
        n = len(builds)
        builds.append(cfg)
        return (_Manager("epl-live-%d" % n), _Manager("epl-recent-%d" % n),
                _Manager("epl-upcoming-%d" % n))

    def config(enabled):
        return {"enabled": True, "custom_leagues": [],
                "leagues": {"eng.1": {"enabled": enabled}}}

    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("disable_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager"):
        setattr(obj, attr, MagicMock())
    obj.config = config(True)
    obj.enabled = True          # BasePlugin.on_config_change reads it
    obj.is_enabled = True
    obj.league_enabled = {"eng.1": True}
    obj.league_live_priority = {"eng.1": False}
    obj._config_lock = threading.Lock()
    obj._active_update_threads = {}
    obj._scroll_prepared = {}
    obj._scroll_active = {}
    obj._favorites_checked = set()
    obj._vegas_signature = None
    obj._scroll_manager = None
    obj.current_mode_index = 0
    obj.last_mode_switch = 0.0
    obj.display_duration = 30.0

    saved = pm.create_premier_league_managers
    pm.create_premier_league_managers = epl_factory
    logging.disable(logging.CRITICAL)
    try:
        obj._initialize_managers()
        obj._load_custom_leagues()
        obj._build_custom_league_map()
        obj._initialize_league_registry()
        obj._display_mode_settings = obj._parse_display_mode_settings()
        obj.modes = obj._get_available_modes()
        first = obj._get_current_manager()
        check("sanity: the enabled league's manager is current",
              isinstance(first, _Manager), first)

        print("\ndisable the league at runtime")
        obj.on_config_change(config(False))
        check("its manager attributes are cleared",
              (obj.eng1_live, obj.eng1_recent, obj.eng1_upcoming) == (None, None, None),
              (getattr(obj, "eng1_live", "unset"),))
        managers = obj._league_registry["eng.1"]["managers"]
        check("the registry holds no managers for it",
              all(m is None for m in managers.values()), managers)
        check("the fallback eng.1 modes find nothing to draw",
              obj._get_current_manager() is None, obj._get_current_manager())
        check("display() with no mode draws nothing",
              obj.display() is False)

        print("\nre-enable it")
        obj.on_config_change(config(True))
        again = obj._get_current_manager()
        check("fresh managers are built", isinstance(again, _Manager) and again is not first,
              again)
    finally:
        logging.disable(logging.NOTSET)
        pm.create_premier_league_managers = saved

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
