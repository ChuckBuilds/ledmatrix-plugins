#!/usr/bin/env python3
"""
The map background must survive a cold tile cache.

Fetching tiles off the render thread means the render path now asks for tiles
that are not in the cache yet. Those are *deferred* -- the prefetch in update()
collects them a moment later -- but the compositing loop counted them the same
as a tile the server refused to serve, and the failure branch disables the map
background for the rest of the session above 50%. On a cold cache every tile is
a deferral, so the second frame after startup switched the map off permanently.
Below that threshold the partial composite was cached under a key made of
static config, so a holey map was pinned instead.

These drive the real _get_map_background through a startup sequence with only
_fetch_tile stubbed. The existing test asserts on the *shape* of the call (an
AST check that display() passes allow_network=False) and so cannot see either
behaviour.

Run: python3 plugins/ledmatrix-flights/test_map_cold_start.py
"""

import logging
import os
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

# manager.py imports the core's BasePlugin at module scope, so the core tree
# has to be importable. LEDMATRIX_CORE points at a checkout; without one there
# is nothing to test against.
_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import Image
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(2)

from manager import FlightTrackerPlugin  # noqa: E402

CENTER = (27.95, -82.46)
FAILURES = []


def check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILURES.append(label)


def make_tracker():
    """A tracker with only the map-compositing state populated.

    __init__ wants a display manager, a cache manager and a plugin manager;
    the compositing path needs none of them, so the instance is built without
    running it.
    """
    t = object.__new__(FlightTrackerPlugin)
    t.logger = logging.getLogger("test-flights")
    t.map_bg_enabled = True
    t.disable_on_cache_error = False
    t.cache_error_count = 0
    t.max_cache_errors = 5
    # display_width/height are read-only properties off the display manager.
    t._display_manager_ref = types.SimpleNamespace(
        matrix=types.SimpleNamespace(width=128, height=32))
    t.map_radius_miles = 25.0
    t.zoom_factor = 1.0
    t.tile_size = 256
    t.map_brightness = t.map_contrast = t.map_saturation = t.fade_intensity = 1.0
    t.custom_tile_server = None
    t.tile_provider = "osm"
    t.cached_map_bgs = {}
    t.last_map_center = None
    t.last_map_zoom = None
    t.cached_tiles = set()
    t.requested = []

    def fetch(x, y, zoom, allow_network=True):
        t.requested.append((x, y, zoom))
        if (x, y, zoom) in t.cached_tiles:
            return Image.new("RGB", (t.tile_size, t.tile_size), (10, 80, 10))
        return None  # cache miss; the real one queues it for the prefetch

    t._fetch_tile = fetch
    return t


def grid_for(tracker):
    """The tiles one composite asks for, from a throwaway pass."""
    tracker.requested = []
    tracker._get_map_background(*CENTER, allow_network=False)
    grid = list(tracker.requested)
    tracker.requested = []
    tracker.cached_map_bgs.clear()
    tracker.last_map_center = tracker.last_map_zoom = None
    return grid


def test_cold_cache_does_not_disable_the_map():
    """The case that broke it: nothing cached, so every tile is deferred."""
    t = make_tracker()
    grid = grid_for(t)

    t.cached_tiles = set(grid[:10])          # prefetch has barely started
    t._get_map_background(*CENTER, allow_network=False)
    check("a mostly-empty cache does not disable the map background",
          t.map_bg_enabled is True)

    t.cached_tiles = set(grid)               # prefetch finished
    check("and the map returns once the prefetch has filled the cache",
          t._get_map_background(*CENTER, allow_network=False) is not None)


def test_partial_composite_is_not_pinned():
    """A holey composite must not be cached: the key is all static config, so
    nothing would ever invalidate it."""
    t = make_tracker()
    grid = grid_for(t)

    t.cached_tiles = set(grid[: int(len(grid) * 0.55)])   # under the 50% bar
    partial = t._get_map_background(*CENTER, allow_network=False)
    check("a partial map is not cached", not t.cached_map_bgs)

    t.cached_tiles = set(grid)
    t.requested = []
    full = t._get_map_background(*CENTER, allow_network=False)
    check("the full map is recomposed rather than served from cache",
          full is not None and len(t.requested) > 0)
    if partial is not None and full is not None:
        check("and it is a different image from the partial one", full is not partial)
    check("the complete map IS cached", bool(t.cached_map_bgs))


def test_a_real_fetch_failure_still_disables():
    """The safety valve has to survive this change.

    With the network allowed, a majority of tiles failing still switches the
    map off. A *total* failure returns earlier, at tiles_fetched == 0, without
    disabling anything -- that predates this change and is covered instead by
    the fetch cooldown, which stops a dead server being retried.
    """
    t = make_tracker()
    grid = grid_for(t)
    t.cached_tiles = set(grid[: max(1, len(grid) // 10)])
    t._get_map_background(*CENTER, allow_network=True)
    check("a majority of real fetch failures still disables the map background",
          t.map_bg_enabled is False)


def test_queue_can_hold_a_whole_grid():
    """A cap below the grid size keeps the map partial for extra cycles, which
    is what made the two bugs above reachable."""
    t = make_tracker()
    needed = len(grid_for(t))
    cap = FlightTrackerPlugin._MAX_TILES_WANTED
    check(f"the wanted-tile queue ({cap}) can hold a whole grid ({needed})",
          cap >= needed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    for fn in (test_cold_cache_does_not_disable_the_map,
               test_partial_composite_is_not_pinned,
               test_a_real_fetch_failure_still_disables,
               test_queue_can_hold_a_whole_grid):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'All checks passed.'}")
    sys.exit(1 if FAILURES else 0)
