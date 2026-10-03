#!/usr/bin/env python3
"""Regression tests: the "Image Error" screen is visible, and an extreme
aspect ratio still loads.

1. _display_error() assigned a new blank canvas to display_manager.image and
   then drew through display_manager.draw, which still pointed at the previous
   canvas. The text went onto an image nobody showed and the panel was pushed
   blank -- whenever a font manager was present, which is always on a real
   board. It also passed no colour, so the text would have been white rather
   than the red the plugin registers for errors.
2. _calculate_fit_size() rounded a very wide or very tall source's short side
   down to zero (2000x3 into 64x32 gives 64x0); Image.resize rejects that, the
   load failed, and the image read as an error.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/static-image/test_error_screen_and_fit.py
Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""

import logging
import os
import sys
import tempfile
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
    from PIL import Image, ImageFont
    from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
    import manager
except Exception as exc:
    print("SKIP: missing dependency (%s)" % exc)
    sys.exit(2)

logging.disable(logging.CRITICAL)

results = []


def check(case, passed, detail=""):
    results.append(passed)
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + ("" if passed or not detail else f"  -- {detail}"))


class _FontManager:
    """Stands in for the core FontManager: serves PressStart2P at any size."""

    def register_manager_font(self, **kwargs):
        pass

    def resolve_font(self, element_key=None, family=None, size_px=8):
        return ImageFont.truetype(str(CORE / "assets" / "fonts" / "PressStart2P-Regular.ttf"), size_px)


class _PluginManager:
    font_manager = _FontManager()


def make(images, w=64, h=32):
    dm = VisualTestDisplayManager(w, h)
    config = {"enabled": True, "images": images, "fit_to_display": True,
              "preserve_aspect_ratio": True}
    return dm, manager.StaticImagePlugin("static-image", config, dm, None, _PluginManager())


print("the error screen")
dm, plugin = make([{"id": "gone", "path": "does/not/exist.png"}])
# Leave a lit frame behind, as the previous plugin's screen would be.
dm.image = Image.new("RGB", (64, 32), (0, 0, 255))
from PIL import ImageDraw  # noqa: E402
dm.draw = ImageDraw.Draw(dm.image)
plugin.display()
frame = dm.image.convert("RGB")
pixels = [frame.getpixel((x, y)) for y in range(frame.height) for x in range(frame.width)]
red = sum(1 for p in pixels if p[0] > 150 and p[1] < 80 and p[2] < 80)
blue = sum(1 for p in pixels if p[2] > 150 and p[0] < 80)
check("'Image Error' is drawn on the frame the panel shows", red > 20, f"{red} red pixels")
check("the previous screen is not left behind", blue == 0, f"{blue} blue pixels")

print("an extreme aspect ratio")
tmp = Path(tempfile.mkdtemp(prefix="static-image-fit-"))
banner = tmp / "banner.png"
Image.new("RGB", (2000, 3), (0, 255, 0)).save(banner)
dm, plugin = make([{"id": "banner", "path": str(banner)}])
check("a 2000x3 banner loads into 64x32", plugin.image_loaded)
check("the fit size never has a zero side",
      min(plugin._calculate_fit_size((2000, 3), (64, 32))) >= 1
      and min(plugin._calculate_fit_size((3, 2000), (64, 32))) >= 1)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
