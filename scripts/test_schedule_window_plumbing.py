#!/usr/bin/env python3
"""
A schedule-window setting the user saves has to survive the config adapter.

Every scoreboard plugin hands its managers a config built by
_adapt_config_for_manager, and each of those adapters constructs its output key
by key. Anything not named there is dropped -- so the two schedule-window
settings were read by SportsCore, advertised in the schema, described in the
release notes, and silently discarded on the way. config.get() returned None,
_clamp_window fell back, and every user got the defaults with nothing logged.

Grepping for the key names is not enough to catch that: one adapter forwards
its input with **self.config elsewhere in the file, which reads like a
passthrough but is a different method. This runs each adapter for real.

Run: python3 scripts/test_schedule_window_plumbing.py
"""

import importlib.util
import inspect
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Some plugins import the core's BasePlugin at module scope, so the core tree
# has to be importable. LEDMATRIX_CORE points at a checkout; the siblings of
# this repo are the usual place to find one.
_CORE = ""
for _candidate in (os.environ.get("LEDMATRIX_CORE", ""),
                   str(REPO.parent / "LEDMatrix"),
                   str(Path.home() / "projects" / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        _CORE = _candidate
        break
if not _CORE:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
WINDOW_KEYS = ("schedule_lookback_days", "schedule_lookahead_days")

# (plugin directory, a league key that plugin's adapter understands)
PLUGINS = [
    ("afl-scoreboard", "afl"),
    ("baseball-scoreboard", "mlb"),
    ("basketball-scoreboard", "nba"),
    ("football-scoreboard", "nfl"),
    ("hockey-scoreboard", "nhl"),
    ("lacrosse-scoreboard", "nll"),
    ("nrl-scoreboard", "nrl"),
    ("soccer-scoreboard", "epl"),
    ("ufc-scoreboard", "ufc"),
]

FAILURES = []


def check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILURES.append(label)


def load_plugin_class(plugin_dir):
    """Import a plugin's manager module and return the class with the adapter.

    Every plugin ships its own sports.py, so a module cached from the last
    plugin would be handed to the next one -- the same collision the core
    solves with per-plugin namespace isolation. Drop anything previously
    imported out of a plugin directory, and keep only this plugin on the path.
    """
    plugins_root = str(REPO / "plugins")
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None) or ""
        if origin.startswith(plugins_root):
            del sys.modules[name]
    sys.path[:] = [p for p in sys.path if not p.startswith(plugins_root)]
    for path in (str(plugin_dir), _CORE):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location(
        f"mgr_{plugin_dir.name.replace('-', '_')}", plugin_dir / "manager.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return next(
        cls for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == spec.name and hasattr(cls, "_adapt_config_for_manager"))


def adapted_config(cls, league):
    """Run the real adapter against a config that sets both window keys."""

    # pylint: disable=too-few-public-methods,attribute-defined-outside-init
    # A deliberate scaffold: the point is to run the adapter without __init__,
    # which is what constructs the dozens of attributes it reads. None of them
    # affect whether these two keys are carried across.
    class Probe(cls):
        def __getattr__(self, name):
            return 0

    probe = object.__new__(Probe)
    probe.logger = logging.getLogger("plumbing-test")
    probe.config = {
        "enabled": True,
        "schedule_lookback_days": 30,
        "schedule_lookahead_days": 21,
        league: {"enabled": True, "display_modes": {"live": True}},
    }
    adapter = cls._adapt_config_for_manager
    takes_league = len(inspect.signature(adapter).parameters) > 1
    return adapter(probe, league) if takes_league else adapter(probe)


def where(config, key):
    if key in config:
        return "root"
    for value in config.values():
        if isinstance(value, dict) and key in value:
            return "nested"
    return None


def main():
    logging.basicConfig(level=logging.CRITICAL)
    print("the adapter must carry both schedule-window keys through:")
    for name, league in PLUGINS:
        plugin_dir = REPO / "plugins" / name
        if not (plugin_dir / "manager.py").is_file():
            continue
        try:
            config = adapted_config(load_plugin_class(plugin_dir), league)
        except (ImportError, AttributeError, TypeError, KeyError, ValueError) as exc:
            # Report rather than abort, so one broken plugin does not hide the
            # state of the other eight.
            check(f"{name}: adapter ran", False)
            print(f"        {type(exc).__name__}: {exc}")
            continue
        for key in WINDOW_KEYS:
            # SportsCore reads these off the root of the config it is handed.
            check(f"{name}: {key} reaches the config root",
                  where(config, key) == "root")

    print(f"\n{'FAILED: ' + str(len(FAILURES)) + ' check(s)' if FAILURES else 'All checks passed.'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
