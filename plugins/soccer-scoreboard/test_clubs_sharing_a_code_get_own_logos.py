#!/usr/bin/env python3
"""Two clubs with one ESPN abbreviation each draw their own logo.

Dundee (ESPN id 261) and Dundee United (264) are both DUN in the Scottish
Premiership. Every soccer league shares one logo directory, and logos were
named by abbreviation, so both clubs used DUN.png: the derby showed one crest
twice. Clubs are now kept per team id (DUN_261.png); core's abbreviation-named
logo is the fallback when the club's own cannot be downloaded.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_clubs_sharing_a_code_get_own_logos.py
"""

import logging
import os
import sys
import tempfile
import types
from collections import OrderedDict
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
    import soccer_logo_files as slf         # noqa: E402
    import game_renderer                    # noqa: E402
    import sports                           # noqa: E402
except ImportError as exc:
    print(f"SKIP: cannot import the plugin without a LEDMatrix core ({exc})")
    sys.exit(2)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


DUNDEE, UNITED = (0, 40, 160, 255), (255, 120, 0, 255)   # navy, tangerine
clubs = Path(tempfile.mkdtemp()) / "soccer_logos"
(clubs / "national").mkdir(parents=True)

print("file names")
a = slf.soccer_logo_filename(clubs, "DUN", "261")
b = slf.soccer_logo_filename(clubs, "DUN", "264")
check("Dundee and Dundee United get different files", a != b, f"{a} {b}")
check("a World Cup flag keeps its abbreviation name",
      slf.soccer_logo_filename(clubs / "national", "ESP", "164") == "ESP.png")
check("no team id falls back to the abbreviation",
      slf.soccer_logo_filename(clubs, "DUN", "") == "DUN.png")

print("\nresolving a file")
downloads = []


def offline(league, team_id, abbr, path, url=None, create_placeholder=True):
    downloads.append((abbr, team_id, create_placeholder))
    return False


slf.download_missing_logo = offline
Image.new("RGBA", (40, 40), DUNDEE).save(clubs / "DUN.png")     # what core ships
got = slf.resolve_soccer_logo(clubs / a, "DUN", "261", None, "soccer_sco.1")
check("offline, the shipped abbreviation logo is used", got == clubs / "DUN.png", got)
check("the club's own file was tried first", downloads[:1] == [("DUN", "261", False)], downloads)

Image.new("RGBA", (40, 40), DUNDEE).save(clubs / a)
Image.new("RGBA", (40, 40), UNITED).save(clubs / b)
check("the club's own file wins over the shipped one",
      slf.resolve_soccer_logo(clubs / b, "DUN", "264", None, "soccer_sco.1") == clubs / b)

game = {"league": "sco.1", "away_abbr": "DUN", "home_abbr": "DUN",
        "away_id": "261", "home_id": "264",
        "away_logo_path": clubs / a, "home_logo_path": clubs / b,
        "home_score": "1", "away_score": "1", "is_final": True}


def colour_near(img, x):
    return img.convert("RGB").getpixel((x, img.height // 2))


print("\nscroll / Vegas card (shared cache)")
r = game_renderer.GameRenderer(128, 32, {}, logo_cache={})
card = r.render_game_card(game, "recent")
left, right = colour_near(card, 8), colour_near(card, 119)
check("away side draws Dundee's navy", left[2] > 120 and left[0] < 80, left)
check("home side draws Dundee United's tangerine", right[0] > 200 and right[2] < 80, right)

print("\nswitch view (SportsCore cache)")
core = types.SimpleNamespace(
    logger=logging.getLogger("t"), _logo_cache=OrderedDict(), league="sco.1",
    sport_key="soccer", display_width=128, display_height=32,
    _scorebug_centre_gap=lambda: 0, _LOGO_EDGE_BLEED_PX=2, _LOGO_CACHE_MAX=64)
load = sports.SportsCore._load_and_resize_logo
dundee = load(core, "261", "DUN", clubs / a, None)
united = load(core, "264", "DUN", clubs / b, None)
check("both logos load", dundee is not None and united is not None)
check("the second DUN is not the first one's cached crest",
      dundee is not united and united.getpixel((5, 5))[0] > 200,
      united.getpixel((5, 5)) if united else None)

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
