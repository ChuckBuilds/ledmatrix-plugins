#!/usr/bin/env python3
"""
Tests that the map is cached per panel size instead of thrashing between two.

Regression under test: the rendered map was held in a single _cached_map, and
display() re-rendered whenever the cached layout's size differed from the
display manager's. The Vegas marquee captures this plugin through the
display-capture fallback at a narrower width than the panel -- 153px against
512px on the rig this was found on -- so the two alternated and every switch
re-rendered from scratch. For a capture that runs on the render thread:
105ms recomputing a terminator that does not depend on size at all, plus
~150ms rendering the map. Measured at 271-639ms of stalled marquee per pass.

What is deliberately NOT cached is the clock. _draw_readout() runs on every
display() call, after the map is pasted, so a cached map does not freeze the
time -- which is the trade this fix avoids having to make.

Run: <core-venv>/bin/python plugins/geochron/test_per_size_map_cache.py
"""

import ast
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import GeochronPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _DisplayManager:
    def __init__(self, width=512, height=64):
        self.width = width
        self.height = height


class _Geo:
    """Stand-in carrying only what the cache paths touch."""

    update = GeochronPlugin.update
    _render_for_size = GeochronPlugin._render_for_size

    def __init__(self):
        self.display_manager = _DisplayManager()
        self._map_cache = {}
        self._darkness = None
        self._cached_map = None
        self._cached_layout = None
        self._subsolar_lat = 0.0
        self._subsolar_lon = 0.0
        self._last_update_utc = None
        self._base_map = object()
        self.night_brightness = 0.35
        self.colors = {"night_tint_color": (0, 0, 40)}
        self.map_center_longitude = 0
        self.show_terminator_bands = True
        self.logger = _Logger()
        self.terminator_calls = 0
        self.render_calls = []


class _Logger:
    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


def _install_stubs(geo):
    """Count the two expensive calls without doing their work."""
    import manager as m

    class _Solar:
        @staticmethod
        def compute_terminator(now, gw, gh, show_bands=True):
            geo.terminator_calls += 1
            return ("darkness-%d" % geo.terminator_calls, 12.3, 45.6)

    class _Renderer:
        @staticmethod
        def _layout(dw, dh, map_center_lon=0):
            return {"dw": dw, "dh": dh, "map_x": 0, "map_y": 0, "sidebar_w": 0}

        @staticmethod
        def render_map_image(base, darkness, layout, brightness, tint):
            geo.render_calls.append((layout["dw"], layout["dh"], darkness))
            return "map-%dx%d-%s" % (layout["dw"], layout["dh"], darkness)

    originals = (m.solar, m.gr)
    m.solar, m.gr = _Solar(), _Renderer()
    return originals, m


def main():
    print("a size that has been rendered is not rendered again")
    geo = _Geo()
    (orig_solar, orig_gr), m = _install_stubs(geo)
    try:
        geo.update()
        first = len(geo.render_calls)
        check("the live panel size is rendered by update()", first == 1)
        check("its entry is cached", (512, 64) in geo._map_cache)

        # The Vegas capture asks for a narrower canvas.
        geo.display_manager.width = 153
        cached = geo._map_cache.get((153, 64))
        check("the capture size is not cached yet", cached is None)
        geo._render_for_size((153, 64), geo._darkness)
        check("rendering it caches it", (153, 64) in geo._map_cache)

        before = len(geo.render_calls)
        geo._map_cache.get((153, 64))
        check("a second look-up at that size renders nothing",
              len(geo.render_calls) == before)
        check("the 512px entry survived the switch", (512, 64) in geo._map_cache)

        print("\nupdate() refreshes every size in use, on the worker thread")
        terminator_before = geo.terminator_calls
        renders_before = len(geo.render_calls)
        geo.display_manager.width = 512
        geo.update()
        check("both cached sizes were re-rendered",
              len(geo.render_calls) - renders_before == 2)
        check("the terminator was computed once, not once per size",
              geo.terminator_calls - terminator_before == 1)
        check("both entries carry the same terminator",
              geo._map_cache[(512, 64)][1].split("-")[-1]
              == geo._map_cache[(153, 64)][1].split("-")[-1])

        print("\nthe live panel's single-entry attributes still track it")
        check("_cached_map points at the live size",
              geo._cached_map == geo._map_cache[(512, 64)][1])
    finally:
        m.solar, m.gr = orig_solar, orig_gr

    print("\nthe clock is not cached with the map")
    # The whole point of caching the map rather than throttling the refresh:
    # the readout is drawn after the paste, every display() call, so a cached
    # map cannot freeze the time.
    source = (plugin_dir / "manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    display_fn = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "display"), None)
    check("display() exists", display_fn is not None)
    readout_calls = [n for n in ast.walk(display_fn)
                     if isinstance(n, ast.Call)
                     and getattr(n.func, "attr", None) == "_draw_readout"]
    check("display() draws the readout on every call", len(readout_calls) == 1)

    readout_fn = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "_draw_readout"), None)
    now_calls = [n for n in ast.walk(readout_fn)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "now"]
    check("the readout reads the clock fresh, not from cache",
          bool(now_calls))

    print("\nno single-entry size check remains in display()")
    # The old bug in one line: re-render when the cached layout's size differs.
    stale = [n for n in ast.walk(display_fn)
             if isinstance(n, ast.Compare)
             and any(isinstance(c, ast.Subscript)
                     and getattr(getattr(c, "slice", None), "value", None) in ("dw", "dh")
                     for c in [n.left] + list(n.comparators))]
    check("display() no longer compares a cached layout's size", not stale)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
