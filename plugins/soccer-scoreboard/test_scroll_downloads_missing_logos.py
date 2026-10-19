#!/usr/bin/env python3
"""Scroll/Vegas cards download a missing team logo instead of falling back to text.

GameRenderer only read the disk, so a side missing from the shipped logos
(Coventry, promoted to the Premier League in 2026) drew the whole card as bare
"COV@TOT" text. The switch view (sports.py) always downloaded it.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_scroll_downloads_missing_logos.py
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
    import game_renderer                    # noqa: E402
except ImportError as exc:
    print(f"SKIP: cannot import game_renderer without a LEDMatrix core ({exc})")
    sys.exit(2)

logos = Path(tempfile.mkdtemp())
Image.new("RGBA", (60, 60), (255, 255, 255, 255)).save(logos / "TOT.png")
calls = []


def fake_download(league, team_id, abbr, path, url=None):
    calls.append((league, team_id, abbr, url))
    Image.new("RGBA", (60, 60), (0, 120, 255, 255)).save(path)
    return True


game_renderer.download_missing_logo = fake_download
r = game_renderer.GameRenderer(128, 32, {}, logo_cache={})
game = {
    "league": "eng.1", "away_abbr": "COV", "home_abbr": "TOT",
    "away_id": "388", "home_id": "367",
    "away_logo_path": logos / "COV.png", "home_logo_path": logos / "TOT.png",
    "away_logo_url": "https://a.espncdn.com/i/teamlogos/soccer/500/388.png",
    "home_score": "0", "away_score": "0", "is_upcoming": True,
}
img = r.render_game_card(game, "upcoming")

assert calls == [("soccer_eng.1", "388", "COV",
                  "https://a.espncdn.com/i/teamlogos/soccer/500/388.png")], calls
# The away slot carries the downloaded (blue) logo, not the "COV@TOT" text.
assert img.getpixel((10, 16))[2] > 200, img.getpixel((10, 16))
print("PASS: missing logo downloaded and drawn")
