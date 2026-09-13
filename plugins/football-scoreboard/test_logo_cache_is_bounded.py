#!/usr/bin/env python3
"""Decoded logo caches are bounded LRUs, not dicts that grow all season.

Core #559 capped SportsCore._logo_cache, but in core's base_classes package,
which no plugin imports; this plugin's own caches stayed unbounded, holding
every decoded logo each NCAA slate ever showed. Both the scorebug cache
(sports.py) and the card renderer's caches (game_renderer.py) now evict the
least recently used logo past a cap.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_logo_cache_is_bounded.py
"""
import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
for _c in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
    if _c and Path(_c).is_dir():
        sys.path.insert(0, _c)
        break
logging.disable(logging.CRITICAL)

try:
    import sports  # noqa: E402
    from game_renderer import GameRenderer  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import the plugin modules (%s)" % exc)
    sys.exit(2)

LOGO = plugin_dir / "assets" / "sports" / "nfl_logos" / "KC.png"

failures = []


def check(name, ok, detail=None):
    print("  [%s] %s%s" % ("pass" if ok else "FAIL", name,
                           "" if ok or detail is None else "  <- %r" % (detail,)))
    if not ok:
        failures.append(name)


def main():
    # game_renderer: the helpers every cache write and read goes through.
    cap = getattr(GameRenderer, "_LOGO_CACHE_MAX", None)
    check("GameRenderer declares a logo cache cap", isinstance(cap, int), cap)
    if isinstance(cap, int):
        cache = {}
        for i in range(cap + 10):
            if i == cap:
                # Full, about to evict: reading T0 must save it.
                GameRenderer._lru_get(cache, "T0")
            GameRenderer._lru_put(cache, "T%d" % i, object())
        check("renderer cache stays at the cap", len(cache) == cap, len(cache))
        check("a recently read logo survives eviction", "T0" in cache)
        check("the least recently used logo is evicted", "T1" not in cache)

    # sports.py: through the real loader, with a logo that exists on disk.
    cap = getattr(sports.SportsCore, "_LOGO_CACHE_MAX", None)
    check("SportsCore declares a logo cache cap", isinstance(cap, int), cap)
    if not isinstance(cap, int) or not LOGO.exists():
        return 1 if failures else 0
    # SportsCore is abstract, so borrow its methods and constants onto a plain class
    # rather than instantiating it.
    stub = type("Stub", (), {
        name: getattr(sports.SportsCore, name)
        for name in dir(sports.SportsCore)
        if not name.startswith("__")
    })()
    stub.logger = logging.getLogger("logo_cache_probe")
    stub._logo_cache = OrderedDict()
    stub.sport_key = "nfl"
    stub.display_width, stub.display_height = 128, 32
    stub.config, stub.mode_config = {}, {}
    load = sports.SportsCore._load_and_resize_logo
    import shutil
    import tempfile
    from unittest.mock import patch
    # The loader looks the logo up by abbreviation, so give every probe team
    # a real file; a miss would try to download it.
    with tempfile.TemporaryDirectory() as tmp,             patch.object(sports, "download_missing_logo",
                         side_effect=AssertionError("tried to download")):
        try:
            for i in range(cap + 6):
                path = Path(tmp) / ("T%d.png" % i)
                shutil.copy(LOGO, path)
                load(stub, str(i), "T%d" % i, path, None)
        except Exception as exc:  # noqa: BLE001
            check("loader runs against the probe", False, exc)
            return 1
    check("scorebug cache stays at the cap", len(stub._logo_cache) == cap,
          len(stub._logo_cache))
    check("oldest scorebug logo is evicted", "T0" not in stub._logo_cache)
    check("newest scorebug logo is kept", "T%d" % (cap + 5) in stub._logo_cache)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
