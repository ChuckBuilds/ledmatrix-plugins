#!/usr/bin/env python3
"""
Regression tests for text-display:

1. .bdf fonts render. _load_font used to return a bare freetype.Face, which PIL
   cannot draw or measure with, so at a .bdf's native size every frame raised
   "'Face' object has no attribute 'getbbox'" and the panel stayed blank; at
   any other size set_pixel_sizes raised and the plugin silently used PIL's
   default font instead.
2. A live config save re-runs the shared scroll resolver. on_config_change
   used to push the legacy frame-based speed through set_scroll_speed(), which
   drops the resolver's whole-pixel step, and kept the old frame hold, so a
   speed edit paced differently from the same config after a restart.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/text-display/test_bdf_and_live_scroll.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from PIL import Image, ImageFont
    import src
    from src.common import scroll_config  # noqa: F401  (3.4.0 floor)
except ImportError as exc:
    print(f"SKIP: LEDMatrix core (3.4.0+) or Pillow not importable: {exc}")
    sys.exit(2)

CORE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(src.__file__)))
BDF = os.path.join(CORE_ROOT, "assets", "fonts", "5x7.bdf")
if not os.path.exists(BDF):
    print(f"SKIP: core font {BDF} not found")
    sys.exit(2)
os.chdir(CORE_ROOT)

from manager import TextDisplayPlugin  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class FakeDisplay:
    refresh_hz = 100.0

    def __init__(self, width=128, height=32):
        self.width = width
        self.height = height
        self.matrix = types.SimpleNamespace(width=width, height=height)
        self.image = Image.new("RGB", (width, height))
        self.calls = []

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def update_display(self):
        pass


def make(config, display=None):
    base = {"enabled": True, "font_mode": "manual"}
    base.update(config)
    return TextDisplayPlugin("text-display", base, display or FakeDisplay(),
                             types.SimpleNamespace(), types.SimpleNamespace())


def test_bdf_renders():
    for size, label in ((7, "native size"), (12, "a non-native size")):
        print(f"[.bdf at {label}]")
        display = FakeDisplay()
        plugin = make({"text": "HELLO", "scroll": False,
                       "font_path": BDF, "font_size": size}, display)
        font = plugin.font
        check(isinstance(font, ImageFont.FreeTypeFont),
              f"font is a PIL font (got {type(font).__module__}.{type(font).__name__})")
        check(str(getattr(font, "path", "")).endswith("5x7.bdf"),
              f"the .bdf itself loaded, not a fallback (path {getattr(font, 'path', None)!r})")
        plugin.display()
        check(display.image.getbbox() is not None, "display() drew the text")


def test_live_speed_edit_re_resolves():
    print("[live speed edit]")
    display = FakeDisplay()
    config = {"text": "A message long enough to scroll across the whole panel",
              "scroll": True, "scroll_speed": 1, "scroll_delay": 0.01}
    plugin = make(config, display)
    check(abs(plugin._scroll_settings.requested_pixels_per_second - 100.0) < 0.01,
          "precondition: 100 px/s at load")

    new_config = dict(config, enabled=True, font_mode="manual",
                      scroll_speed=2, scroll_delay=0.03)
    plugin.on_config_change(new_config)
    settings = plugin._scroll_settings
    check(abs(settings.requested_pixels_per_second - 2 / 0.03) < 0.01,
          f"the resolver ran again for 66.7 px/s (got {settings.requested_pixels_per_second:.1f})")
    check(plugin.scroll_helper.fixed_pixels_per_frame == settings.crisp.pixels_per_frame,
          "the resolver's whole-pixel step is applied after the save "
          f"(got {plugin.scroll_helper.fixed_pixels_per_frame})")

    display.calls.clear()
    plugin.display()
    check(display.calls[-1:] == [(True, settings.frame_hold)],
          f"display() passes the re-resolved frame hold {settings.frame_hold} (calls {display.calls})")


if __name__ == "__main__":
    for test in (test_bdf_renders, test_live_speed_edit_re_resolves):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
