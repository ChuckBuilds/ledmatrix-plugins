#!/usr/bin/env python3
"""The advanced-modal layout overrides each do what their field says.

Regressions under test:

1. value_x was read only when name_x was also set, and even then fell back to
   None (the normalized layout always carries the key), so a value_x on its
   own was ignored.
2. Under text_align "right" neither name_x nor value_x applied.
3. Setting only image_width / image_height counted as a position override,
   which placed the image at x=0: an image-right image jumped to the left,
   with the text beside it on the right.

Run: <core-venv>/bin/python plugins/countdown/test_layout_overrides.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(PLUGIN_DIR.parents[2] / "LEDMatrix")
CORE = None
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        CORE = candidate
        sys.path.insert(0, str(candidate))
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import Image
    from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
    import manager
except Exception as exc:
    print("SKIP: missing dependency (%s)" % exc)
    sys.exit(2)

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

failures = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok or not detail else "  -- " + detail))
    if not ok:
        failures.append(label)


class _PluginManager:
    font_manager = None


TMP = Path(tempfile.mkdtemp(prefix="countdown-layout-"))
RED = TMP / "red.png"
Image.new("RGB", (64, 64), (255, 0, 0)).save(RED)
W, H = 128, 64


def render(**countdown):
    cd = {
        "id": "t", "enabled": True, "name": "AB",
        "target_date": (datetime.now() + timedelta(days=100)).strftime("%Y-%m-%d"),
        "layout_preset": "text-only",
    }
    cd.update(countdown)
    config = {"enabled": True, "countdowns": [cd], "font_family": "press_start",
              "font_size": 8, "name_font_size": 8, "background_color": [0, 0, 0]}
    dm = VisualTestDisplayManager(W, H)
    plugin = manager.CountdownPlugin("countdown", config, dm, None, _PluginManager())
    plugin.update()
    plugin.display()
    return dm.image.convert("RGB")


def extent(img, rows, test):
    px = img.load()
    xs = [x for y in rows for x in range(W) if test(px[x, y])]
    return (min(xs), max(xs) + 1) if xs else None


def centre(span):
    return None if span is None else (span[0] + span[1]) / 2


def lit(p):
    return sum(p) > 300 and not (p[0] > 120 and p[1] < 80)


def red(p):
    return p[0] > 120 and p[1] < 80


NAME_ROWS, VALUE_ROWS = range(0, H // 2), range(H // 2, H)

os.chdir(str(CORE))

print("value_x on its own")
frame = render(layout={"value_x": 30})
check("the value is centred on value_x", abs(centre(extent(frame, VALUE_ROWS, lit)) - 30) <= 2,
      str(extent(frame, VALUE_ROWS, lit)))
check("the name keeps its automatic place (centred)",
      abs(centre(extent(frame, NAME_ROWS, lit)) - W / 2) <= 2, str(extent(frame, NAME_ROWS, lit)))

print("overrides under right alignment")
frame = render(text_align="right", layout={"name_x": 30})
check("name_x applies with text_align right", abs(centre(extent(frame, NAME_ROWS, lit)) - 30) <= 2,
      str(extent(frame, NAME_ROWS, lit)))
check("the value stays right-aligned", extent(frame, VALUE_ROWS, lit)[1] >= W - 6,
      str(extent(frame, VALUE_ROWS, lit)))

print("an image size alone keeps the preset's placement")
frame = render(layout_preset="image-right", image_path=str(RED),
               layout={"image_width": 30})
span = extent(frame, range(H), red)
check("image-right with image_width 30 sits at the right edge",
      span is not None and span[1] == W and span[1] - span[0] <= 30, str(span))
check("the text is to its left", (extent(frame, VALUE_ROWS, lit) or (W, W))[1] <= W - 30,
      str(extent(frame, VALUE_ROWS, lit)))

print("an image position still wins")
frame = render(layout_preset="image-right", image_path=str(RED),
               layout={"image_x": 10, "image_width": 30})
span = extent(frame, range(H), red)
check("image_x 10 places the image there", span is not None and span[0] >= 10 and span[1] <= 40,
      str(span))

print()
print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
