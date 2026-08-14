#!/usr/bin/env python3
"""
Tests that map tiles are never fetched over the network on the render thread.

Regression under test: _fetch_tile() went to the network on a cache miss, and
the render path reaches it through get_vegas_content(). A tile normally
arrives in tens of milliseconds; an unreachable one costs the full timeout,
and on the render thread that is a frozen marquee. Measured on a live rig at
3458ms, 3377ms and 3479ms in a single session -- the existing 3s timeout and
300s cooldown bounded that to one freeze per five minutes rather than
removing it, which the module comment says outright.

The render path now serves the cache only and records what it went without;
update() fetches those on the plugin manager's update worker, where a timeout
costs nothing visible.

Run: <core-venv>/bin/python plugins/ledmatrix-flights/test_tiles_off_render_thread.py
"""

import ast
import sys
import threading
import time
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import FlightTrackerPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Flights:
    """Stand-in carrying only what the tile paths touch."""

    _MAX_TILES_WANTED = FlightTrackerPlugin._MAX_TILES_WANTED
    _note_tile_wanted = FlightTrackerPlugin._note_tile_wanted
    _prefetch_map_tiles = FlightTrackerPlugin._prefetch_map_tiles

    def __init__(self):
        self._tiles_wanted = set()
        self._tiles_wanted_lock = threading.Lock()
        self._tile_network_blocked_until = 0.0
        self.logger = _Logger()
        self.fetched = []
        self.fetch_result = object()

    def _fetch_tile(self, x, y, zoom, allow_network=True):
        self.fetched.append((x, y, zoom, allow_network))
        return self.fetch_result


class _Logger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def main():
    print("the render path never opens a socket")
    source = (plugin_dir / "manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    render = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name == "_render_map_image"), None)
    check("_render_map_image exists", render is not None)
    bg_calls = [n for n in ast.walk(render) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "_get_map_background"]
    check("it asks for the map background once", len(bg_calls) == 1)
    if bg_calls:
        kwargs = {k.arg: k.value for k in bg_calls[0].keywords}
        allow = kwargs.get("allow_network")
        check("and passes allow_network=False",
              isinstance(allow, ast.Constant) and allow.value is False)

    fetch = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_fetch_tile"), None)
    check("_fetch_tile takes an allow_network gate",
          fetch is not None and "allow_network" in [a.arg for a in fetch.args.args])

    # The gate must come before any network call in the body.
    if fetch is not None:
        gate = [n for n in ast.walk(fetch) if isinstance(n, ast.If)
                and any(isinstance(sub, ast.Name) and sub.id == "allow_network"
                        for sub in ast.walk(n.test))]
        net = [n for n in ast.walk(fetch) if isinstance(n, ast.Call)
               and getattr(getattr(n.func, "value", None), "id", None) == "requests"]
        check("the gate exists", bool(gate))
        check("and sits above the network call",
              bool(gate) and bool(net) and min(g.lineno for g in gate) < min(c.lineno for c in net))

    print("\na render-path miss is remembered, not dropped")
    flights = _Flights()
    flights._note_tile_wanted(1, 2, 11)
    flights._note_tile_wanted(1, 2, 11)
    flights._note_tile_wanted(3, 4, 11)
    check("misses are recorded once each", flights._tiles_wanted == {(1, 2, 11), (3, 4, 11)})

    print("\n_fetch_tile itself records the miss when refused the network")
    # Not via _note_tile_wanted directly: the point is that the shipped
    # _fetch_tile records it, so a render-path miss actually reaches the
    # prefetch queue. Testing the helper alone passes with that call deleted.
    class _RealFetch(_Flights):
        _fetch_tile = FlightTrackerPlugin._fetch_tile

        def __init__(self):
            super().__init__()
            self.cached = False

        def _get_tile_cache_path(self, x, y, zoom):
            return Path("/nonexistent/%d_%d_%d.png" % (zoom, x, y))

        def _is_tile_cached(self, x, y, zoom):
            return self.cached

    real = _RealFetch()
    result = real._fetch_tile(7, 8, 11, allow_network=False)
    check("a cache miss returns None rather than blocking", result is None)
    check("and the tile is queued for the prefetch",
          (7, 8, 11) in real._tiles_wanted)

    print("\nthe prefetch fetches them with the network allowed")
    flights._prefetch_map_tiles()
    check("both were fetched", len(flights.fetched) == 2)
    check("all with allow_network=True",
          all(entry[3] is True for entry in flights.fetched))
    check("the queue is drained", flights._tiles_wanted == set())

    flights.fetched.clear()
    flights._prefetch_map_tiles()
    check("a second prefetch with nothing queued does nothing",
          flights.fetched == [])

    print("\nthe failure cooldown still applies to the prefetch")
    flights = _Flights()
    flights._note_tile_wanted(5, 6, 11)
    flights._tile_network_blocked_until = time.time() + 300
    flights._prefetch_map_tiles()
    check("nothing is fetched while the server is known bad", flights.fetched == [])

    print("\nthe queue cannot grow without bound")
    flights = _Flights()
    for i in range(_Flights._MAX_TILES_WANTED * 3):
        flights._note_tile_wanted(i, 0, 11)
    check("capped at _MAX_TILES_WANTED (%d)" % _Flights._MAX_TILES_WANTED,
          len(flights._tiles_wanted) == _Flights._MAX_TILES_WANTED)

    print("\nupdate() is what drains it")
    upd = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name == "update"), None)
    calls = [n for n in ast.walk(upd) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "_prefetch_map_tiles"]
    check("update() calls the prefetch", len(calls) == 1)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
