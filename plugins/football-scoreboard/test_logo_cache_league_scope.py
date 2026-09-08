#!/usr/bin/env python3
"""Two leagues, one shared logo cache, ten shared abbreviations.

This plugin serves NFL and NCAA FB, whose logos live in different directories.
Ten abbreviations exist in both:

    CAR  CIN  DAL  DEN  HOU  LAC  MIA  NE  TB  TBD

Miami is the visible one: ncaa_logos/MIA.png is the Hurricanes, nfl_logos/MIA.png
is the Dolphins. _logo_cache_key scopes by logo slot size only, and manager.py
builds a single ScrollDisplayManager whose _logo_cache every renderer shares --
prepare_scroll_content takes `leagues` plural, so one strip carries both. Both
leagues therefore resolved "MIA" to the same key and whichever rendered first
won the slot.

Run: python test_logo_cache_league_scope.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_core = os.environ.get("LEDMATRIX_CORE")
if _core:
    sys.path.insert(0, _core)

from PIL import Image                      # noqa: E402
from game_renderer import GameRenderer     # noqa: E402

NCAA = Path("/x/assets/sports/ncaa_logos/MIA.png")
NFL = Path("/x/assets/sports/nfl_logos/MIA.png")

#: Abbreviations that exist in both shipped logo directories.
COLLIDING = ["CAR", "CIN", "DAL", "DEN", "HOU", "LAC", "MIA", "NE", "TB", "TBD"]

_results = []


def check(name, ok, detail=""):
    _results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -- " + detail) if detail and not ok else ""))


def main():
    import tempfile

    # Two real files, one per league directory, deliberately different colours
    # so the wrong one is unmistakable. This goes through the real
    # _load_and_resize_logo, so it fails on the unfixed code for the right
    # reason rather than because a helper is missing.
    tmp = Path(tempfile.mkdtemp())
    ncaa_dir = tmp / "assets" / "sports" / "ncaa_logos"
    nfl_dir = tmp / "assets" / "sports" / "nfl_logos"
    ncaa_dir.mkdir(parents=True); nfl_dir.mkdir(parents=True)
    HURRICANES = (240, 130, 0, 255)     # orange
    DOLPHINS = (0, 133, 122, 255)       # teal
    Image.new("RGBA", (60, 60), HURRICANES).save(ncaa_dir / "MIA.png")
    Image.new("RGBA", (60, 60), DOLPHINS).save(nfl_dir / "MIA.png")

    shared = {}
    r = GameRenderer(128, 64, {}, logo_cache=shared)

    # NFL Miami renders first, as it would in a rotation carrying both.
    nfl_logo = r._load_and_resize_logo("1", "MIA", nfl_dir / "MIA.png", None)
    ncaa_logo = r._load_and_resize_logo("2", "MIA", ncaa_dir / "MIA.png", None)
    check("both leagues loaded a logo", nfl_logo is not None and ncaa_logo is not None)

    if ncaa_logo is not None:
        drawn = ncaa_logo.convert("RGBA").getpixel((ncaa_logo.width // 2,
                                                    ncaa_logo.height // 2))
        check("the NCAA card draws the NCAA logo, not the NFL one",
              drawn[:3] == HURRICANES[:3],
              f"drew {drawn[:3]}, expected {HURRICANES[:3]} "
              "-- the NFL entry answered the NCAA lookup")

    check("the two leagues occupy separate cache entries",
          len(shared) == 2, f"{len(shared)} entr(y/ies): {sorted(shared)}")

    ncaa_key = r._logo_cache_key(f"{r._logo_scope(NCAA)}:MIA")
    nfl_key = r._logo_cache_key(f"{r._logo_scope(NFL)}:MIA")
    check("the two leagues get different cache keys for MIA",
          ncaa_key != nfl_key, f"both are {ncaa_key}")

    check("the key still carries the slot size",
          "@" in ncaa_key and "x" in ncaa_key.split("@")[-1], ncaa_key)

    # Every colliding abbreviation, not just the reported one.
    clashes = [a for a in COLLIDING
               if r._logo_cache_key(f"{r._logo_scope(NCAA)}:{a}")
               == r._logo_cache_key(f"{r._logo_scope(NFL)}:{a}")]
    check("no colliding abbreviation shares a key", not clashes, str(clashes))

    # Same directory, same abbreviation, really is the same team -- scoping
    # must not fragment the cache and re-decode the same PNG per card.
    a = r._logo_cache_key(f"{r._logo_scope(NCAA)}:MIA")
    b = r._logo_cache_key(f"{r._logo_scope(Path('/x/assets/sports/ncaa_logos/MIA.png'))}:MIA")
    check("the same directory still shares one entry", a == b)

    # A missing path must not raise on the render thread.
    for bad in (None, "", 123):
        try:
            r._logo_scope(bad)
        except Exception as e:            # noqa: BLE001
            check(f"_logo_scope({bad!r}) does not raise", False, repr(e))
            break
    else:
        check("_logo_scope tolerates a missing or odd path", True)

    failed = [n for n, ok, _ in _results if not ok]
    print(f"\n{len(_results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
