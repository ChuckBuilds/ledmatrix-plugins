#!/usr/bin/env python3
"""A bad setting or one broken manager must not blank the whole plugin.

* P-A4: _initialize_managers built Live, Recent and Upcoming in one try, so one
  constructor raising left all three unset; update() did the same per call.
* M12: the adapter wrapped other_games_divisions in list(), so a string "fbs"
  became ['f', 'b', 's'] and a null raised TypeError inside the translation --
  which happens before any manager is built.
* OverflowError: json accepts a bare Infinity, and int(inf) raises
  OverflowError, not ValueError, so it escaped _setting_int / _clamp_window.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_manager_init_isolation.py
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

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

import manager as m  # noqa: E402
import sports  # noqa: E402
from ufc_managers import UFCRecentManager as MMARecent  # noqa: E402  (concrete)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Fake:
    def __init__(self, *a, **k):
        self.updates = 0

    def update(self):
        self.updates += 1


class _Broken:
    def __init__(self, *a, **k):
        raise RuntimeError("constructor failed")


class _RaisesOnUpdate(_Fake):
    def update(self):
        raise RuntimeError("update failed")


def plugin():
    obj = m.UFCScoreboardPlugin.__new__(m.UFCScoreboardPlugin)
    obj.logger = logging.getLogger("isolation_probe")
    obj.is_enabled = True
    obj.ufc_enabled = True
    obj.display_manager = MagicMock()
    obj.cache_manager = MagicMock()
    obj._adapt_config_for_manager = lambda league: {}
    return obj


print("one manager failing to construct")
saved = (m.UFCLiveManager, m.UFCRecentManager, m.UFCUpcomingManager)
try:
    m.UFCLiveManager, m.UFCRecentManager, m.UFCUpcomingManager = _Fake, _Broken, _Fake
    obj = plugin()
    obj._initialize_managers()
    check("Live is still built", isinstance(obj.ufc_live, _Fake))
    check("Upcoming is still built", isinstance(obj.ufc_upcoming, _Fake))
    check("the broken one is None", obj.ufc_recent is None)
    check("the plugin counts as initialised", obj._managers_initialized is True)
    try:
        obj.update()
        check("update() tolerates the None manager", True)
    except Exception as exc:  # noqa: BLE001
        check("update() tolerates the None manager", False, repr(exc))
    check("... and still updates the others",
          obj.ufc_live.updates == 1 and obj.ufc_upcoming.updates == 1)

    print("\none manager failing to update")
    m.UFCLiveManager, m.UFCRecentManager, m.UFCUpcomingManager = _RaisesOnUpdate, _Fake, _Fake
    obj = plugin()
    obj._initialize_managers()
    obj.update()
    check("a Live update that raises does not starve Recent/Upcoming",
          obj.ufc_recent.updates == 1 and obj.ufc_upcoming.updates == 1)
finally:
    m.UFCLiveManager, m.UFCRecentManager, m.UFCUpcomingManager = saved


print("\nother_games_divisions passes through the adapter raw")
for raw in ("fbs", None, ["fcs"]):
    obj = m.UFCScoreboardPlugin.__new__(m.UFCScoreboardPlugin)
    obj.logger = logging.getLogger("isolation_probe")
    obj.cache_manager = MagicMock()
    obj.plugin_manager = None
    obj.config = {"ufc": {"game_limits": {"other_games_divisions": raw}}}
    try:
        block = obj._adapt_config_for_manager("ufc")["ufc_scoreboard"]
        got = block.get("other_games_divisions")
        check(f"{raw!r} arrives unchanged", got == raw, f"got {got!r}")
    except Exception as exc:  # noqa: BLE001
        check(f"{raw!r} arrives unchanged", False, repr(exc))
check("the manager side coerces a string to one division",
      sports.SportsCore._normalise_divisions("fbs") == ["fbs"],
      repr(sports.SportsCore._normalise_divisions("fbs")))


print("\nInfinity in a numeric setting falls back to the default")
check("_clamp_window(inf)", sports._clamp_window(float("inf"), 7) == 7)
probe = MMARecent.__new__(MMARecent)
probe.logger = logging.getLogger("isolation_probe")
probe.league = "ufc"
probe.mode_config = {"other_rotation_interval_seconds": float("inf")}
try:
    got = probe._setting_int("other_rotation_interval_seconds", 1800, 0, 86400)
    check("_setting_int(inf)", got == 1800, f"got {got!r}")
except OverflowError as exc:
    check("_setting_int(inf)", False, repr(exc))

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
