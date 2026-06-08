#!/usr/bin/env python3
"""
Regression test for the 7-segment-clock digit/separator render polarity.

Run standalone from the plugin directory:

    cd plugins/7-segment-clock
    python test_render_polarity.py

The digit assets encode lit segments as fully *transparent* pixels and unlit
areas as opaque black. The renderer must therefore color the transparent
pixels. A previous version colored the opaque pixels instead, which produced a
fully blank frame (nothing colored) or, when "color every opaque pixel" was
tried, garbled blocks (e.g. "1" rendered as a solid rectangle).

This test renders digits through the real `_render_digit` and asserts:
  1. a digit with all segments lit ("8") produces visible pixels  -> not blank
  2. "1" lights fewer pixels than "8"                              -> right polarity
     (the broken "color opaque pixels" path inverts this, since the unlit mask
      for "1" is nearly the whole tile)
  3. every lit pixel is exactly the configured color; unlit pixels are clear

No external test framework is required — the script exits non-zero on the first
failure and prints a summary on success.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from PIL import Image

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


def _install_host_stubs() -> None:
    for name in ("src", "src.plugin_system", "src.plugin_system.base_plugin"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["src.plugin_system.base_plugin"].BasePlugin = object


_install_host_stubs()

import manager  # noqa: E402


def _make_plugin() -> "manager.SevenSegmentClockPlugin":
    """Build an instance without running __init__ (which needs the full host)."""
    plugin = object.__new__(manager.SevenSegmentClockPlugin)
    assets = PLUGIN_DIR / "assets" / "images"
    plugin.number_images = {
        i: Image.open(assets / f"number_{i}.png").convert("RGBA") for i in range(10)
    }
    plugin.separator_image = Image.open(assets / "separator.png").convert("RGBA")

    class _NullLogger:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    plugin.logger = _NullLogger()
    return plugin


def _lit_pixels(img: Image.Image, color):
    """Return (count_of_visible_pixels, set_of_distinct_visible_rgb)."""
    px = img.convert("RGBA").load()
    count = 0
    colors = set()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a > 0:
                count += 1
                colors.add((r, g, b))
    return count, colors


def test_eight_is_not_blank() -> None:
    plugin = _make_plugin()
    color = (0, 255, 0)
    count, colors = _lit_pixels(plugin._render_digit(8, color), color)
    assert count > 0, "digit '8' rendered blank — render polarity is wrong"
    assert colors == {color}, f"lit pixels not the configured color: {colors}"
    print(f"  [ok] '8' renders {count} lit pixels, all {color}")


def test_one_lights_fewer_than_eight() -> None:
    plugin = _make_plugin()
    color = (255, 255, 255)
    eight, _ = _lit_pixels(plugin._render_digit(8, color), color)
    one, _ = _lit_pixels(plugin._render_digit(1, color), color)
    # "8" lights all seven segments; "1" lights only two. If the renderer is
    # coloring the *unlit* mask instead, this inverts (one > eight).
    assert one < eight, f"polarity inverted: '1'={one} lit vs '8'={eight} lit"
    print(f"  [ok] '1' ({one}) lights fewer pixels than '8' ({eight})")


def test_separator_renders() -> None:
    plugin = _make_plugin()
    color = (255, 0, 0)
    count, colors = _lit_pixels(plugin._render_separator(color), color)
    assert count > 0, "separator rendered blank"
    assert colors == {color}, f"separator pixels not the configured color: {colors}"
    print(f"  [ok] separator renders {count} lit pixels, all {color}")


def main() -> int:
    tests = [
        test_eight_is_not_blank,
        test_one_lights_fewer_than_eight,
        test_separator_renders,
    ]
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  [FAIL] {t.__name__}: {exc}")
            return 1
    print("All render-polarity tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
