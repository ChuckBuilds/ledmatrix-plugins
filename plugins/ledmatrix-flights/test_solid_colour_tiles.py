#!/usr/bin/env python3
"""A tile that is all one colour is a tile, not an error page.

Map tiles covering open water, desert, or any square with no features render
as a single flat colour, and a 256x256 PNG of one colour compresses to about
100 bytes. _fetch_tile used to reject any body under 2KB as "likely an error
page", and separately rejected any image more than 80% a single colour. Both
describe a legitimate ocean tile exactly.

Observed on a coastal install: at zoom 11 roughly a third of the grid is open
Gulf. Because _get_tile_urls() returns a single URL when a custom tile server
is configured, one rejected water tile exhausted the URL list and tripped
_block_tile_network(), after which every remaining tile in the grid returned
None for the full cooldown. The map rendered with no background at all -- not
with a hole where the water was -- and re-tripped on the next attempt.

Run: python3 plugins/ledmatrix-flights/test_solid_colour_tiles.py
"""

import io
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

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
    from PIL import Image
except ImportError as e:
    print("SKIP: %s" % e)
    sys.exit(2)

import manager as fm  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


OSM_WATER = (170, 211, 223)


def solid_tile_png():
    """A 256x256 tile of OSM's water blue, encoded as the servers encode it."""
    img = Image.new('RGB', (256, 256), OSM_WATER).convert(
        'P', palette=Image.ADAPTIVE, colors=2)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, content, content_type='image/png'):
        self.content = content
        self.headers = {'content-type': content_type}

    def raise_for_status(self):
        return None


class FakePlugin:
    """Just enough of the plugin to drive _fetch_tile's validation."""

    _fetch_tile = fm.FlightTrackerPlugin._fetch_tile
    _block_tile_network = fm.FlightTrackerPlugin._block_tile_network

    def __init__(self, tmp):
        self._tile_network_blocked_until = 0.0
        self.cache_error_count = 0
        self._tmp = tmp
        self.logger = type("L", (), {m: (lambda *a, **k: None) for m in
                                     ("debug", "info", "warning", "error")})()

    def _get_tile_cache_path(self, x, y, z):
        return Path(self._tmp, "%d_%d_%d.png" % (z, x, y))

    def _is_tile_cached(self, x, y, z):
        return self._get_tile_cache_path(x, y, z).exists()

    def _get_tile_urls(self, x, y, z):
        # One URL, as a configured custom tile server yields -- no fallback.
        return ["http://tiles.invalid/%d/%d/%d.png" % (z, x, y)]


def serve(body, content_type='image/png'):
    """Point the module's requests.get at a fixed response."""
    fm.requests.get = lambda *a, **k: FakeResponse(body, content_type)


def main():
    import tempfile

    original_get = fm.requests.get
    try:
        blue = solid_tile_png()

        print("the tile the old heuristics rejected")
        check("a solid tile really is under the old 2KB threshold",
              len(blue) < 2000, "%d bytes" % len(blue))
        check("and it really is 256x256",
              Image.open(io.BytesIO(blue)).size == (256, 256))

        print("a solid-colour tile is accepted")
        p = FakePlugin(tempfile.mkdtemp())
        serve(blue)
        got = p._fetch_tile(549, 861, 11)
        check("_fetch_tile returns an image", got is not None)
        check("the image is tile-sized",
              got is not None and got.size == (256, 256))
        check("the network was not blocked",
              p._tile_network_blocked_until == 0.0)
        check("the tile was written to the cache",
              p._is_tile_cached(549, 861, 11))

        print("an HTML error page is still rejected")
        p = FakePlugin(tempfile.mkdtemp())
        serve(b"<html><body>404 Not Found</body></html>", 'text/html')
        check("_fetch_tile returns None", p._fetch_tile(1, 2, 3) is None)
        check("and the network is blocked",
              p._tile_network_blocked_until > 0.0)

        print("a body that is not an image is still rejected")
        p = FakePlugin(tempfile.mkdtemp())
        serve(b"not an image at all", 'application/octet-stream')
        check("_fetch_tile returns None", p._fetch_tile(1, 2, 3) is None)
        check("nothing was cached", not p._is_tile_cached(1, 2, 3))

        print("a truncated image is still rejected")
        p = FakePlugin(tempfile.mkdtemp())
        serve(blue[:len(blue) // 2])
        check("_fetch_tile returns None", p._fetch_tile(4, 5, 6) is None)
    finally:
        fm.requests.get = original_get

    print()
    if failures:
        print("%d check(s) failed: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("All checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
