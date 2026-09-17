#!/usr/bin/env python3
"""National flags and club crests that share an abbreviation get separate cache slots.

ESP is Spain and Espanyol, POR is Portugal and Portland Timbers, COL is Colombia
and the Colorado Rapids. soccer_managers.py already keeps the World Cup flags in
their own national/ directory for this reason, but manager.py builds a single
ScrollDisplayManager whose _logo_cache every renderer shares, and
_logo_cache_key scoped by slot size only. So "ESP" resolved to one key
(ESP@40x32) and whichever league rendered first won: a strip carrying the World
Cup and La Liga drew Spain as Espanyol's crest.

Ported from football-scoreboard #472: the key is scoped by the logo's directory.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_logo_cache_league_scope.py
"""

import os
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break

try:
    from PIL import Image                   # noqa: E402
    from game_renderer import GameRenderer  # noqa: E402
except ImportError as exc:
    print(f"SKIP: cannot import game_renderer without a LEDMatrix core ({exc})")
    sys.exit(2)

#: Abbreviations the plugin itself names as flag/crest collisions.
COLLIDING = ["ESP", "POR", "COL"]

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


tmp = Path(tempfile.mkdtemp())
clubs = tmp / "assets" / "sports" / "soccer_logos"
flags = clubs / "national"
flags.mkdir(parents=True)
SPAIN = (198, 11, 30, 255)       # red
ESPANYOL = (0, 71, 171, 255)     # blue
Image.new("RGBA", (60, 60), ESPANYOL).save(clubs / "ESP.png")
Image.new("RGBA", (60, 60), SPAIN).save(flags / "ESP.png")

shared = {}
r = GameRenderer(128, 32, {}, logo_cache=shared)

# The club crest renders first, as it would with La Liga ahead of the World Cup.
club = r._load_and_resize_logo("1", "ESP", clubs / "ESP.png", None)
flag = r._load_and_resize_logo("2", "ESP", flags / "ESP.png", None)
check("both logos loaded", club is not None and flag is not None)
if flag is not None:
    drawn = flag.convert("RGBA").getpixel((flag.width // 2, flag.height // 2))
    check("the World Cup card draws Spain's flag, not Espanyol's crest",
          drawn[:3] == SPAIN[:3], f"drew {drawn[:3]}, expected {SPAIN[:3]}")
check("flag and crest occupy separate cache entries", len(shared) == 2,
      f"{sorted(shared)}")

# preload_logos() must write under the same keys the loader reads.
shared2 = {}
r2 = GameRenderer(128, 32, {}, logo_cache=shared2)
r2.preload_logos([
    {"home_abbr": "ESP", "home_logo_path": clubs / "ESP.png",
     "away_abbr": "ESP", "away_logo_path": flags / "ESP.png"},
], clubs)
check("preload keeps flag and crest apart", len(shared2) == 2, f"{sorted(shared2)}")
before = dict(shared2)
r2._load_and_resize_logo("2", "ESP", flags / "ESP.png", None)
check("a preloaded logo is a cache hit, not a second entry", shared2.keys() == before.keys(),
      f"{sorted(shared2)}")

clashes = [a for a in COLLIDING
           if r._logo_cache_key(f"{r._logo_scope(clubs / (a + '.png'))}:{a}")
           == r._logo_cache_key(f"{r._logo_scope(flags / (a + '.png'))}:{a}")]
check("no flag/crest abbreviation shares a key", not clashes, str(clashes))

a = r._logo_cache_key(f"{r._logo_scope(clubs / 'BAR.png')}:BAR")
b = r._logo_cache_key(f"{r._logo_scope(Path(str(clubs)) / 'BAR.png')}:BAR")
check("two leagues reading one club directory still share an entry", a == b)
check("the key still carries the slot size", "@" in a, a)

for bad in (None, "", 123):
    try:
        r._logo_scope(bad)
    except Exception as e:  # noqa: BLE001
        check(f"_logo_scope({bad!r}) does not raise", False, repr(e))
        break
else:
    check("_logo_scope tolerates a missing or odd path", True)

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
