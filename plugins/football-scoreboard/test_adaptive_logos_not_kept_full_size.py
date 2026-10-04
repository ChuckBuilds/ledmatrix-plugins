#!/usr/bin/env python3
"""Adaptive cards keep fitted logos, not the full-size source files.

The adaptive card path loaded each team's logo unresized and cached it, up to
128 per renderer, in every renderer the plugin builds (a scorebug per manager,
scroll cards, Vegas cards). The source files are big -- 768x768 RGBA for the
NFL, 2.3 MB decoded; 500x500 for most of NCAA -- so on a Saturday slate those
caches grew by hundreds of MB as new teams came on. A Pi 4 running football in
adaptive mode next to three other scoreboards went from 325 MB to 549 MB in six
hours of live games, and the display's live heap plateaued only once every
renderer had filled its 128 slots.

The card only ever draws the logo fitted into its slot, so that is what is kept
now. This draws cards for 40 teams with NFL-sized logos through one renderer and
checks that:

* no image the renderer holds is larger than the panel;
* the decoded pixels it holds stay a small fraction of one full-size logo per
  team (the old cache held 40 x 2.3 MB = 94 MB here);
* a card drawn from the cache is pixel-identical to the same card drawn cold.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_adaptive_logos_not_kept_full_size.py
"""

import gc
import os
import sys
import tempfile
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

from PIL import Image, ImageDraw  # noqa: E402

TEAMS = 40
SOURCE = 768            # the NFL logo files' size
WIDTH, HEIGHT = 192, 48  # the rig the growth was measured on

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           ("  -- " + detail) if detail and not passed else ""))


def _logo(path, i):
    """A full-size logo with some ink, distinct per team."""
    img = Image.new("RGBA", (SOURCE, SOURCE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    colour = (40 + 5 * i, 255 - 5 * i, (97 * i) % 256, 255)
    draw.ellipse((60, 60, SOURCE - 60, SOURCE - 60), fill=colour)
    draw.rectangle((SOURCE // 3, SOURCE // 3, SOURCE // 2, SOURCE // 2),
                   fill=(255, 255, 255, 255))
    img.save(path)


def _game(away, home, logo_dir):
    return {
        "home_id": "1", "home_abbr": home,
        "home_logo_path": str(logo_dir / ("%s.png" % home)),
        "away_id": "2", "away_abbr": away,
        "away_logo_path": str(logo_dir / ("%s.png" % away)),
        "home_score": "21", "away_score": "17",
        "period_text": "Q3", "clock": "8:42", "is_live": True,
        "league": "nfl",
    }


def _held_images(root):
    """Decoded images reachable from ``root`` (attributes, dicts, lists,
    tuples, dataclasses), each counted once."""
    seen, found, stack = set(), [], [root]
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if isinstance(obj, Image.Image):
            if getattr(obj, "_im", None) is not None:
                found.append(obj)
            continue
        if isinstance(obj, dict):
            stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        elif hasattr(obj, "__dict__") and not isinstance(obj, type) \
                and type(obj).__module__ not in ("builtins", "logging"):
            stack.extend(vars(obj).values())
        elif hasattr(obj, "__slots__"):
            stack.extend(getattr(obj, s, None) for s in obj.__slots__)
    return found


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer, ADAPTIVE_AVAILABLE
    if not ADAPTIVE_AVAILABLE:
        print("SKIP: this core has no src.adaptive_layout")
        return 2

    logo_dir = Path(tempfile.mkdtemp()) / "assets" / "sports" / "nfl_logos"
    logo_dir.mkdir(parents=True)
    teams = ["T%02d" % i for i in range(TEAMS)]
    for i, abbr in enumerate(teams):
        _logo(logo_dir / ("%s.png" % abbr), i)

    renderer = GameRenderer(WIDTH, HEIGHT, {"layout_mode": "adaptive"})
    games = [_game(teams[i], teams[i + 1], logo_dir) for i in range(0, TEAMS, 2)]
    first = [renderer.render_game_card(g, "live") for g in games]
    gc.collect()

    held = _held_images(renderer)
    biggest = max((im.width * im.height for im in held), default=0)
    check("no held image is larger than the panel",
          biggest <= WIDTH * HEIGHT,
          "largest held image has %d px; the panel has %d"
          % (biggest, WIDTH * HEIGHT))

    held_bytes = sum(im.width * im.height * len(im.getbands()) for im in held)
    full_size = SOURCE * SOURCE * 4
    check("held logo pixels are far below one full-size logo per team",
          held_bytes < TEAMS * full_size // 20,
          "%.1f MB held for %d teams (full size would be %.1f MB)"
          % (held_bytes / 1e6, TEAMS, TEAMS * full_size / 1e6))

    again = [renderer.render_game_card(g, "live") for g in games]
    check("a card drawn from the cache matches the card drawn cold",
          all(a.tobytes() == b.tobytes() for a, b in zip(first, again)))

    cold = GameRenderer(WIDTH, HEIGHT, {"layout_mode": "adaptive"})
    check("a fresh renderer draws the same cards",
          all(cold.render_game_card(g, "live").tobytes() == a.tobytes()
              for g, a in zip(games, first)))

    failed = [c for c, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
