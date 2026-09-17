#!/usr/bin/env python3
"""get_update_interval() asks for a faster poll only while a game is live.

Without the hook the core scheduler calls update() at the static interval --
the manifest's update_interval, or the config's update_interval_seconds where
the manifest declares none -- so during a live game everything that reads
update-cycle data (the Vegas cards, modes not on screen) lagged well behind
live_update_interval. Core 3.4.0 consults get_update_interval() on every tick
(ChuckBuilds/LEDMatrix#555); football and ufc implemented it, this plugin did
not.

The risk to guard against is the opposite of the bug: asking for a 30-second
poll when nothing is live would hit ESPN all year.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_live_update_cadence.py
"""

import ast
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

try:
    from manager import BasketballScoreboardPlugin as Plugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: cannot import the plugin without a LEDMatrix core ({exc})")
    sys.exit(2)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


if not callable(getattr(Plugin, "get_update_interval", None)):
    check("the plugin defines get_update_interval()", False)
    print(f"\n{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)


class _LiveManager:
    def __init__(self, live_games=(), update_interval=30):
        self.live_games = list(live_games)
        self.update_interval = update_interval

    def has_live_content(self):
        raise AssertionError("get_update_interval() must not call has_live_content()")


class _Stub:
    get_update_interval = Plugin.get_update_interval
    _live_scroll_managers = Plugin._live_scroll_managers

    def __init__(self, leagues, enabled=True, shape="registry"):
        """leagues: [(enabled, live manager or None)]."""
        self.is_enabled = enabled
        if shape == "registry":
            self._league_registry = {
                f"league{i}": {"enabled": on, "managers": {"live": mgr}}
                for i, (on, mgr) in enumerate(leagues)}
        else:
            live = next((mgr for on, mgr in leagues if on), None)
            self._get_manager = lambda mode_type: live if mode_type == "live" else None


GAME = {"id": "401", "home_abbr": "AAA", "away_abbr": "BBB"}

print("nothing live -> no opinion, so the static interval stands")
check("no live games", _Stub([(True, _LiveManager())]).get_update_interval() is None)
check("manager not built", _Stub([(True, None)]).get_update_interval() is None)
check("plugin disabled",
      _Stub([(True, _LiveManager([GAME]))], enabled=False).get_update_interval() is None)

print("\na game in progress -> ask for the live interval")
check("default 30s", _Stub([(True, _LiveManager([GAME]))]).get_update_interval() == 30)
check("configured interval honoured",
      _Stub([(True, _LiveManager([GAME], update_interval=12))]).get_update_interval() == 12)
check("has_live_content() is not consulted (would raise)",
      _Stub([(True, _LiveManager([GAME]))]).get_update_interval() == 30)
if "registry" == "registry":
    check("a disabled league's live games are ignored",
          _Stub([(False, _LiveManager([GAME], 5)),
                 (True, _LiveManager())]).get_update_interval() is None)
    check("the fastest live league wins",
          _Stub([(True, _LiveManager([GAME], 45)),
                 (True, _LiveManager([GAME], 15))]).get_update_interval() == 15)

print("\nthe hook stays cheap")
with open(PLUGIN_DIR / "manager.py", encoding="utf-8") as _fh:
    _tree = ast.parse(_fh.read())
_calls = []
for _node in ast.walk(_tree):
    if isinstance(_node, ast.FunctionDef) and _node.name == "get_update_interval":
        _calls = sorted({c.func.attr for c in ast.walk(_node)
                         if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
_forbidden = [c for c in _calls if c in ("has_live_content", "update", "get_config",
                                         "_ensure_manager_updated", "get")]
check("no filtering, config lookups or updates in the per-tick hook", not _forbidden,
      f"calls: {_calls}")

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
