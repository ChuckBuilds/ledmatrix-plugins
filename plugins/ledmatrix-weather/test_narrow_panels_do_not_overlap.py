#!/usr/bin/env python3
"""On narrow panels no two labels on a row overlap, and none starts off-panel.

At 64x32 (both unit systems):
* hourly drew four 16px columns and each "80°" is 24px, so the temperatures
  ran together; daily drew three 21px columns for 25px "71/79" labels;
* the metrics bar split 64px three ways for UV, H and a 50px gusty wind;
* the right-aligned condition "Partly Cloudy" (104px) started left of x=0.

Renders every screen through the core's plugin harness with the recorded
fixture, recording each draw.text call, and checks each row.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-weather/test_narrow_panels_do_not_overlap.py
Exit 0 pass, 1 fail, 2 skip.
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import ImageDraw
    from src.plugin_system.testing.harness import render_plugin_matrix
    import freezegun  # noqa: F401  (the harness freezes time with it)
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

os.chdir(_candidate)  # fonts resolve as assets/fonts/..., as on a Pi
spec = json.loads((PLUGIN_DIR / "test" / "harness.json").read_text(encoding="utf-8"))
mock = json.loads((PLUGIN_DIR / spec["mock_data"]).read_text(encoding="utf-8"))

calls = defaultdict(list)  # one entry per ImageDraw -> [(y, x0, x1, text)]
_tokens = iter(range(10 ** 9))
_text = ImageDraw.ImageDraw.text


def recording_text(self, xy, text, *args, **kwargs):
    font = kwargs.get("font") or (args[1] if len(args) > 1 else None)
    try:
        w = self.textlength(text, font=font)
    except Exception:
        w = 0
    # A tag on the draw itself: id() is reused once a screen's draw is freed.
    if not hasattr(self, "_overlap_test_token"):
        self._overlap_test_token = next(_tokens)
    calls[self._overlap_test_token].append((round(xy[1]), xy[0], xy[0] + w, text))
    return _text(self, xy, text, *args, **kwargs)


ImageDraw.ImageDraw.text = recording_text

failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok or not detail else "  -- " + detail))
    if not ok:
        failures.append(label)


for units in ("imperial", "metric"):
    data = {k.replace(":imperial:", ":%s:" % units): v for k, v in mock.items()}
    config = dict(spec["config"], units=units)
    for size in ((64, 32), (96, 48), (128, 32)):
        calls.clear()
        results = render_plugin_matrix("ledmatrix-weather", PLUGIN_DIR, config=config,
                                       mock_data=data, sizes=[size],
                                       freeze_time=spec.get("freeze_time"))
        errors = [r.mode for r in results if r.error]
        check("%s %dx%d renders every screen" % (units, size[0], size[1]), not errors, str(errors))
        clashes, off_panel = [], []
        for rows in calls.values():
            by_y = defaultdict(list)
            for y, x0, x1, text in rows:
                by_y[y].append((x0, x1, text))
                if x0 < 0:
                    off_panel.append(text)
            for items in by_y.values():
                items.sort()
                for (a0, a1, at), (b0, b1, bt) in zip(items, items[1:]):
                    if b0 < a1 - 0.5:
                        clashes.append("%r/%r" % (at, bt))
        check("%s %dx%d: no two labels on a row overlap" % (units, size[0], size[1]),
              not clashes, ", ".join(clashes[:6]))
        check("%s %dx%d: no label starts left of the panel" % (units, size[0], size[1]),
              not off_panel, str(off_panel[:6]))

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
