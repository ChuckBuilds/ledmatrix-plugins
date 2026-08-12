#!/usr/bin/env python3
"""Tests that an unreachable tile server cannot freeze the scroll.

Map tiles are fetched from inside get_vegas_content(), which the Vegas
coordinator calls on the render thread -- so every second spent waiting on a
tile is a second the marquee is stopped. Profiled on a live rig with py-spy,
the main thread was found stuck 5.30s in a single getaddrinfo:

    coordinator.run_iteration -> stream_manager._fetch_plugin_content
      -> plugin_adapter._get_native_content
        -> ledmatrix-flights get_vegas_content
          -> _render_map_image -> _get_map_background -> _fetch_tile
            -> requests.get -> socket.getaddrinfo

The old timeout was 10s, tried against each of two URLs, for every tile in
the grid. Nothing bounded the total.

Run: python3 plugins/ledmatrix-flights/test_tile_network_bound.py
"""

import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

# manager.py imports the core's BasePlugin at module scope, so the core tree
# has to be importable. LEDMATRIX_CORE points at a checkout; without one there
# is nothing to test against.
import os
_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    import requests  # noqa: F401
except ImportError:
    print("SKIP: requests not installed")
    sys.exit(2)

import manager as fm  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class FakePlugin:
    """Just enough of the plugin to exercise _fetch_tile's network policy."""

    _fetch_tile = fm.FlightTrackerPlugin._fetch_tile
    _block_tile_network = fm.FlightTrackerPlugin._block_tile_network

    def __init__(self, tmp):
        self._tile_network_blocked_until = 0.0
        self.cache_error_count = 0
        self._tmp = tmp
        self.attempts = 0
        self.logger = type("L", (), {m: (lambda *a, **k: None) for m in
                                     ("debug", "info", "warning", "error")})()

    def _get_tile_cache_path(self, x, y, z):
        return Path(self._tmp, "%d_%d_%d.png" % (z, x, y))

    def _is_tile_cached(self, x, y, z):
        return self._get_tile_cache_path(x, y, z).exists()

    def _get_tile_urls(self, x, y, z):
        return ["http://a.invalid/%d/%d/%d.png" % (z, x, y),
                "http://b.invalid/%d/%d/%d.png" % (z, x, y)]


def main():
    import tempfile
    tmp = tempfile.mkdtemp()

    print("the per-request timeout is short enough for a render thread")
    check("timeout is bounded", fm._TILE_TIMEOUT_SECONDS <= 5,
          "%ss" % fm._TILE_TIMEOUT_SECONDS)
    # Two URLs per tile, and a grid has many tiles. A whole grid must not be
    # able to outlast the plugin executor's 30s budget on its own.
    worst_one_tile = fm._TILE_TIMEOUT_SECONDS * 2
    check("one tile cannot exhaust a 30s update budget", worst_one_tile < 30,
          "%ss" % worst_one_tile)

    print("\na failing tile stops the rest of the grid trying")
    p = FakePlugin(tmp)
    calls = {"n": 0}
    real_get = fm.requests.get

    def boom(*a, **k):
        calls["n"] += 1
        raise fm.requests.exceptions.ConnectionError("no route")

    fm.requests.get = boom
    try:
        first = p._fetch_tile(1, 1, 10)
        after_first = calls["n"]
        for i in range(40):                      # the rest of a tile grid
            p._fetch_tile(2 + i, 1, 10)
        check("first tile returns nothing", first is None)
        check("it tried both URLs once", after_first == 2, "%d" % after_first)
        check("and no further tile touched the network",
              calls["n"] == after_first, "%d total attempts" % calls["n"])
    finally:
        fm.requests.get = real_get

    print("\nthe block is time-bounded, not permanent")
    check("a cooldown is set", p._tile_network_blocked_until > time.time())
    check("and it expires",
          p._tile_network_blocked_until - time.time() <= fm._TILE_FAILURE_COOLDOWN + 1)
    p._tile_network_blocked_until = 0.0
    fm.requests.get = boom
    try:
        before = calls["n"]
        p._fetch_tile(99, 99, 10)
        check("the network is retried once the cooldown lapses",
              calls["n"] > before)
    finally:
        fm.requests.get = real_get

    print("\ncached tiles are still served while the network is blocked")
    from PIL import Image
    p2 = FakePlugin(tmp)
    p2._tile_network_blocked_until = time.time() + 999
    cached = p2._get_tile_cache_path(7, 7, 10)
    Image.new('RGB', (256, 256), (10, 20, 30)).save(cached)
    before_cached = calls["n"]
    fm.requests.get = boom
    try:
        got = p2._fetch_tile(7, 7, 10)
    finally:
        fm.requests.get = real_get
    check("a cached tile comes back", got is not None)
    check("without any network call", calls["n"] == before_cached,
          "%d attempts" % (calls["n"] - before_cached))

    print("\nand an uncached one simply yields nothing, quickly")
    t = time.perf_counter()
    missing = p2._fetch_tile(8, 8, 10)
    elapsed = time.perf_counter() - t
    check("returns None", missing is None)
    check("and returns at once", elapsed < 0.05, "%.3fs" % elapsed)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
