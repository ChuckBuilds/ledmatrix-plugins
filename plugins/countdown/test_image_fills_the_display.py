#!/usr/bin/env python3
"""Tests that a countdown image is scaled to the area it is actually given.

Regressions under test:

1. The image area defaulted to a third of the display width for every layout
   preset, including 'image-only'. That preset draws no text, so the whole
   display is available -- but the image was scaled into `dw // 3` and pasted
   at x0, leaving two thirds of the panel as background. A 256x64 banner on a
   128x32 board came out 42x10 instead of 128x32, roughly a tenth of the area
   it should have had. 'image-only' rendered identically to 'image-left'.

2. _calculate_fit_size() rounded the short side of an extreme aspect ratio
   down to zero -- a 2000x3 banner into 128x32 gives (128, 0). Image.resize
   rejects a zero dimension, and the raise was caught upstream as a failed
   load, so the image disappeared with only a log line to explain it.

Run: <core-venv>/bin/python plugins/countdown/test_image_fills_the_display.py
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


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _PluginManager:
    """No font_manager: _resolve_font loads the family file directly."""
    font_manager = None


TMP = Path(tempfile.mkdtemp(prefix="countdown-image-"))


def _image(w, h):
    """A solid red source of the given size, so its extent is measurable."""
    path = TMP / f"src_{w}x{h}.png"
    if not path.exists():
        Image.new("RGB", (w, h), (255, 0, 0)).save(path)
    return path


def _render(preset, display, source, **countdown):
    dw, dh = display
    cd = {
        "id": "t", "enabled": True, "name": "X",
        "target_date": (datetime.now() + timedelta(days=100)).strftime("%Y-%m-%d"),
        "image_path": str(source), "layout_preset": preset,
    }
    cd.update(countdown)
    config = {
        "enabled": True, "countdowns": [cd],
        "font_family": "press_start", "font_size": 8,
        "name_font_size": 8, "background_color": [0, 0, 0],
    }
    dm = VisualTestDisplayManager(dw, dh)
    plugin = manager.CountdownPlugin("countdown", config, dm, None, _PluginManager())
    plugin.update()
    plugin.display()
    return dm.image.convert("RGB")


def _extent(img):
    """(x0, y0, x1, y1) of the red source within the frame, or None."""
    w, h = img.size
    px = img.load()
    pts = [(x, y) for x in range(w) for y in range(h)
           if px[x, y][0] > 120 and px[x, y][1] < 80]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


os.chdir(str(CORE))

print("image-only uses the whole display")
# A source with the same aspect as the board fills it exactly. Under the bug
# this was dw//3 wide.
for dw, dh in ((128, 32), (256, 64), (64, 32)):
    frame = _render("image-only", (dw, dh), _image(dw * 2, dh * 2))
    ext = _extent(frame)
    check(f"{dw}x{dh}: matching-aspect source fills the panel",
          ext == (0, 0, dw, dh))

print("image-only is not the same as image-left")
wide = _image(256, 64)
only = _extent(_render("image-only", (128, 32), wide))
left = _extent(_render("image-left", (128, 32), wide))
check("image-only covers the full width", only == (0, 0, 128, 32))
check("image-left still reserves width for text", left is not None and left[2] <= 128 // 3 + 1)
check("the two presets no longer render identically", only != left)

print("aspect ratio is still preserved")
# A square source on a wide board is limited by height, and centred.
ext = _extent(_render("image-only", (128, 32), _image(64, 64)))
check("square source stays square", ext is not None and (ext[2] - ext[0]) == (ext[3] - ext[1]))
check("square source is centred, not left-aligned",
      ext is not None and ext[0] == (128 - (ext[2] - ext[0])) // 2)

print("an explicit image_width still wins")
ext = _extent(_render("image-only", (128, 32), _image(256, 64),
                      layout={"image_width": 40, "image_height": 32}))
check("advanced-modal pixel override is honoured",
      ext is not None and (ext[2] - ext[0]) <= 40)

print("extreme aspect ratios still draw something")
for iw, ih in ((2000, 3), (3, 2000)):
    ext = _extent(_render("image-only", (128, 32), _image(iw, ih)))
    check(f"{iw}x{ih} source is not dropped entirely", ext is not None)

print("fit size never returns a zero dimension")
plugin = manager.CountdownPlugin(
    "countdown", {"enabled": True, "countdowns": []},
    VisualTestDisplayManager(128, 32), None, _PluginManager())
for size in ((2000, 3), (3, 2000), (1000, 1), (1, 1000)):
    w, h = plugin._calculate_fit_size(size, (128, 32))
    check(f"{size} -> ({w}, {h}) has both sides >= 1", w >= 1 and h >= 1)

print()
if failures:
    print("FAILED (%d):" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
