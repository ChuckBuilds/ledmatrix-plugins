#!/usr/bin/env python3
"""The decoded-logo caches are bounded LRUs (port of core #559).

Both caches -- SportsCore's per manager and GameRenderer's for the scroll and
Vegas cards -- were plain dicts that kept every decoded logo a season of NCAA
slates ever showed. These checks pin that each stays at its cap, that the
least recently used logo is the one evicted, and that GameRenderer still
works with a plain dict handed in by the scroll display.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_logo_cache_is_bounded.py
"""

import os
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def main():
    os.chdir(str(CORE))
    from PIL import Image
    import sports
    import game_renderer

    class Core(sports.SportsCore):
        def __init__(self):
            self.logger = logging.getLogger("test")
            self.display_width = 64
            self.display_height = 32
            self.config = {}
            self.sport_key = "nba"
            self._logo_cache = OrderedDict()

        def _custom_scorebug_layout(self, game, draw):  # pragma: no cover
            raise NotImplementedError

        def _extract_game_details(self, game_event):  # pragma: no cover
            raise NotImplementedError

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

    core = Core()
    cap = core._LOGO_CACHE_MAX
    # ignore_cleanup_errors: Windows refuses to delete a PNG Pillow still
    # holds open, which is not what this test is about.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        abbrs = ["T%03d" % i for i in range(cap + 10)]
        for abbr in abbrs:
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(Path(tmp) / ("%s.png" % abbr))
        for abbr in abbrs[:cap]:
            core._load_and_resize_logo(abbr, abbr, Path(tmp) / ("%s.png" % abbr), None)
        # Touch the oldest so it becomes the most recently used.
        core._load_and_resize_logo(abbrs[0], abbrs[0], Path(tmp) / ("%s.png" % abbrs[0]), None)
        for abbr in abbrs[cap:]:
            core._load_and_resize_logo(abbr, abbr, Path(tmp) / ("%s.png" % abbr), None)
    check("SportsCore: the cache stays at its cap (%d)" % cap,
          len(core._logo_cache) == cap)
    check("SportsCore: a recently used logo survives eviction",
          abbrs[0] in core._logo_cache)
    check("SportsCore: the least recently used logos are evicted",
          abbrs[1] not in core._logo_cache)

    for cache in (OrderedDict(), {}):
        renderer = game_renderer.GameRenderer.__new__(game_renderer.GameRenderer)
        renderer._logo_cache = cache
        rcap = renderer._LOGO_CACHE_MAX
        img = Image.new("RGBA", (4, 4))
        for i in range(rcap):
            renderer._remember_logo("k%d" % i, img)
        renderer._cached_logo("k0")
        for i in range(rcap, rcap + 20):
            renderer._remember_logo("k%d" % i, img)
        kind = type(cache).__name__
        check("GameRenderer (%s): the cache stays at its cap (%d)" % (kind, rcap),
              len(cache) == rcap)
        check("GameRenderer (%s): a recently used logo survives" % kind, "k0" in cache)
        check("GameRenderer (%s): the oldest untouched logo is evicted" % kind,
              "k1" not in cache)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
