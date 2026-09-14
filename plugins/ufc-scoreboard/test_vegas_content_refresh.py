#!/usr/bin/env python3
"""Vegas fight cards follow the fights, and building them does no network I/O.

get_vegas_content() rebuilt its cards only when the cache was EMPTY, and this
plugin's flat scroll manager keeps them in _vegas_content_items, which the
core's cache clear never touches -- so the ticker showed the first slate it
ever built (a frozen round clock, a result that never appeared) until restart.
Building also called update(), putting ESPN requests on the Vegas render path.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_vegas_content_refresh.py
"""

import logging
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

from PIL import Image  # noqa: E402

from manager import UFCScoreboardPlugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class FakeScroll:
    """The flat ScrollDisplayManager: cards persist until it is asked again."""

    def __init__(self):
        self.items = []
        self.builds = 0

    def get_all_vegas_content_items(self):
        return list(self.items)

    def prepare_and_display(self, games, mode, leagues):
        self.builds += 1
        self.items = [Image.new("RGB", (16, 8)) for _ in games]
        return True


def fight(fid, clock="4:12", period=1, state="in"):
    return {"id": fid, "is_live": state == "in", "is_final": state == "post",
            "clock": clock, "period": period, "status": {"state": state},
            "status_text": "R%d %s" % (period, clock)}


obj = UFCScoreboardPlugin.__new__(UFCScoreboardPlugin)
obj.logger = logging.getLogger("vegas_probe")
obj.ufc_enabled = True
obj._scroll_manager = FakeScroll()
obj._vegas_signature = None
current = [fight("1")]
obj._collect_fights_for_scroll = lambda mode_type=None: ([dict(f) for f in current], ["ufc"])


def _no_update():
    raise AssertionError("get_vegas_content() called update()")


obj.update = _no_update
scroll = obj._scroll_manager

try:
    images = obj.get_vegas_content()
    check("first call builds the cards", scroll.builds == 1 and len(images or []) == 1,
          f"builds={scroll.builds}")

    obj.get_vegas_content()
    check("unchanged fights reuse the cards", scroll.builds == 1, f"builds={scroll.builds}")

    current[0] = fight("1", clock="3:58")
    obj.get_vegas_content()
    check("a moving round clock rebuilds", scroll.builds == 2, f"builds={scroll.builds}")

    current[0] = fight("1", clock="0:00", period=3, state="post")
    obj.get_vegas_content()
    check("a result arriving rebuilds", scroll.builds == 3, f"builds={scroll.builds}")

    current.append(fight("2", state="pre"))
    images = obj.get_vegas_content()
    check("a fight joining the slate rebuilds with it",
          scroll.builds == 4 and len(images or []) == 2, f"builds={scroll.builds}")

    current.clear()
    check("no fights -> None", obj.get_vegas_content() is None)
    check("update() was never called", True)
except AssertionError as exc:
    check("update() was never called", False, str(exc))

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
