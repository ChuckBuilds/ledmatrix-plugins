#!/usr/bin/env python3
"""The map must be composed at the width the ticker asked for.

Vegas asks a plugin for a narrower render so a layout built for the full panel
does not read as sparse in the ticker. It normally delivers that by narrowing
the shared canvas for the duration of the call, which a plugin sizing itself
from ``matrix.width`` picks up for free. But it cannot narrow the canvas in
offscreen mode -- ``_render_at`` swaps the shared canvas, which is unsafe
there -- so it only sets ``_vegas_render_width`` and notes that a plugin
reading ``get_vegas_render_width()`` still gets the narrow size while one that
only reads ``matrix.width`` "renders full width and is trimmed instead".

This plugin relied on the canvas being narrowed. Its own docstring said the
projection scales "without any extra plumbing". On a live rig that assumption
held three times out of twelve:

    [ledmatrix-flights] Native: requesting 256px instead of 512px
    [ledmatrix-flights] Native: SUCCESS - 1 images, 512px total width
    [ledmatrix-flights] Native: SUCCESS - 1 images, 256px total width

so the same map came back at two different widths depending on which path the
adapter took, and the full-width renders were cropped afterwards.

No plugin in the repo read get_vegas_render_width() before this.

Run: <core-venv>/bin/python plugins/ledmatrix-flights/test_vegas_render_width.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Matrix:
    width, height = 512, 64


class _DisplayManager:
    matrix = _Matrix()


def _plugin():
    """A FlightTracker carrying what the width property reads.

    Both names are set on purpose. This plugin keeps its own
    ``_display_manager_ref``, while BasePlugin.__init__ stores the same object
    as ``display_manager`` -- and get_vegas_render_width()'s fallback reads the
    latter. A stub with only the private name makes the fallback miss the
    matrix and return its hard-coded 128, which looks exactly like the property
    being broken.
    """
    from manager import FlightTrackerPlugin as _P
    obj = object.__new__(_P)
    dm = _DisplayManager()
    obj._display_manager_ref = dm
    obj.display_manager = dm
    return obj


def main():
    print("the render width follows the ticker's request")
    from src.plugin_system.base_plugin import BasePlugin

    p = _plugin()
    check("the plugin inherits get_vegas_render_width from BasePlugin",
          isinstance(p, BasePlugin) or hasattr(p, "get_vegas_render_width"))

    check("outside a Vegas request it is the panel width (%d)" % p.display_width,
          p.display_width == 512)

    # Exactly what PluginAdapter does before calling get_vegas_content(), and
    # the only thing it can do in offscreen mode.
    p._vegas_render_width = 256
    check("during a narrow request it is the requested width (%d)" % p.display_width,
          p.display_width == 256)

    # And exactly what the adapter's finally clause does afterwards.
    p._vegas_render_width = None
    check("afterwards it is the panel width again (%d)" % p.display_width,
          p.display_width == 512)

    print("\nnonsense hints fall back rather than propagating")
    for bad in (0, -1, "wide", None):
        p._vegas_render_width = bad
        ok = p.display_width == 512
        check(f"a hint of {bad!r} falls back to the panel width", ok)

    print("\nthe composite cache keys on the size, so both widths coexist")
    source = (plugin_dir / "manager.py").read_text(encoding="utf-8")
    check("cached_map_bgs is keyed by (width, height)",
          "current_size = (self.display_width, self.display_height)" in source)
    check("and it is only cleared when the view itself moves",
          "if self.last_map_center != current_center or self.last_map_zoom != zoom:"
          in source)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
