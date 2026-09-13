#!/usr/bin/env python3
"""get_update_interval() asks for a faster poll only while a fight is live.

The manifest pins update_interval to 60, the only number the core scheduler
used, so ufc.live_update_interval (30s by default) could never fire more often
than once a minute. Core now consults get_update_interval() per tick (#555);
the eight sibling scoreboards implemented it in #479 and ufc was left out.

The risk to guard against is the opposite of the bug: asking for a 30-second
poll when nothing is live would hit ESPN all year.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_live_update_cadence.py
"""

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

from manager import UFCScoreboardPlugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _LiveManager:
    def __init__(self, live_games=(), update_interval=30):
        self.live_games = list(live_games)
        self.update_interval = update_interval

    def has_live_content(self):
        raise AssertionError("get_update_interval() must not call has_live_content()")


class _Stub:
    get_update_interval = UFCScoreboardPlugin.get_update_interval

    def __init__(self, live=None, enabled=True, ufc_enabled=True):
        self.is_enabled = enabled
        self.ufc_enabled = ufc_enabled
        self.ufc_live = live


FIGHT = {"id": "600051234", "fighter1_name": "A", "fighter2_name": "B"}

print("nothing live -> no opinion, so the manifest's 60s stands")
check("no live fights", _Stub(_LiveManager()).get_update_interval() is None)
check("manager not built", _Stub(None).get_update_interval() is None)
check("plugin disabled",
      _Stub(_LiveManager([FIGHT]), enabled=False).get_update_interval() is None)
check("ufc disabled",
      _Stub(_LiveManager([FIGHT]), ufc_enabled=False).get_update_interval() is None)

print("\na fight in progress -> ask for the live interval")
check("default 30s", _Stub(_LiveManager([FIGHT])).get_update_interval() == 30)
check("configured interval honoured",
      _Stub(_LiveManager([FIGHT], update_interval=12)).get_update_interval() == 12)
check("has_live_content() is not consulted (would raise)",
      _Stub(_LiveManager([FIGHT])).get_update_interval() == 30)

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
