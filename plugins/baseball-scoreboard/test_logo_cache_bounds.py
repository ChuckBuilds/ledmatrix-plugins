#!/usr/bin/env python3
"""The decoded-logo caches stay bounded, and the card cache is size-scoped.

  * P-M7 -- SportsCore._logo_cache and the scroll card renderer's cache were
    unbounded dicts. A board that works through a season of rotating slates
    kept every decoded logo for the life of the process. Both now evict the
    least recently used entry past a cap, as the core's SportsCore does
    (LEDMatrix #559).
  * The card renderer keyed its cache on league and team alone, but the cache
    is handed in by the scroll display and outlives any one renderer. A
    renderer built at another card size was served logos scaled for the
    first one.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_logo_cache_bounds.py
"""

import logging
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

from PIL import Image  # noqa: E402

logging.disable(logging.CRITICAL)
failures = []
TEAMS = ["T%02d" % i for i in range(80)]


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _write_logos(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for team in TEAMS:
        Image.new("RGBA", (120, 120), (200, 30, 30, 255)).save(folder / ("%s.png" % team))


def test_sports_cache(tmp):
    print("SportsCore logo cache")
    import sports
    logo_dir = tmp / "sports_logos"
    _write_logos(logo_dir)

    body = dict((name, lambda self, *a, **k: None)
                for name in getattr(sports.SportsUpcoming, "__abstractmethods__", ()))
    body["_scorebug_centre_gap"] = lambda self: 0
    cls = type("LogoProbe", (sports.SportsUpcoming,), body)
    probe = cls.__new__(cls)
    probe.logger = logging.getLogger("logo_probe")
    probe.sport_key = "mlb"
    probe.display_width, probe.display_height = 64, 32
    probe._logo_cache = OrderedDict()
    cap = sports.SportsCore._LOGO_CACHE_MAX

    for team in TEAMS:
        probe._load_and_resize_logo("1", team, logo_dir / ("%s.png" % team), None)
    check("the cache never holds more than %d logos" % cap,
          len(probe._logo_cache) <= cap, len(probe._logo_cache))
    check("the oldest logo was the one evicted", TEAMS[0] not in probe._logo_cache)
    check("the newest logo is kept", TEAMS[-1] in probe._logo_cache)

    survivor = next(iter(probe._logo_cache))
    probe._load_and_resize_logo("1", survivor, logo_dir / ("%s.png" % survivor), None)
    Image.new("RGBA", (120, 120)).save(logo_dir / "EXTRA.png")
    probe._load_and_resize_logo("1", "EXTRA", logo_dir / "EXTRA.png", None)
    check("a cache hit counts as use and survives the next eviction",
          survivor in probe._logo_cache)


def test_renderer_cache(tmp):
    # GameRenderer._load_and_resize_logo(league, team_abbrev) takes two
    # arguments; a static checker resolves the name to SportsCore's
    # four-argument method and reports a missing logo_path.
    # pylint: disable=no-value-for-parameter
    print("\nGameRenderer logo cache")
    os.chdir(str(tmp))
    _write_logos(tmp / "assets" / "sports" / "mlb_logos")
    from game_renderer import GameRenderer

    shared = {}
    small = GameRenderer(64, 32, {}, logo_cache=shared)
    large = GameRenderer(128, 64, {}, logo_cache=shared)
    a = small._load_and_resize_logo("mlb", "T00")
    b = large._load_and_resize_logo("mlb", "T00")
    check("both renderers loaded the logo", a is not None and b is not None)
    if a is not None and b is not None:
        check("a larger card is not served the smaller card's logo",
              b.size != a.size, (a.size, b.size))
        check("each logo fits its own card", a.height <= 32 and b.height <= 64,
              (a.size, b.size))

    for team in TEAMS:
        small._load_and_resize_logo("mlb", team)
    cap = GameRenderer._LOGO_CACHE_MAX
    check("the shared card cache never holds more than %d logos" % cap,
          len(shared) <= cap, len(shared))


def main():
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        try:
            test_sports_cache(tmp)
            test_renderer_cache(tmp)
        finally:
            os.chdir(here)
    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
