#!/usr/bin/env python3
"""show_powerplay must draw something, and nothing when it is off (#431).

ESPN's situation.isPowerPlay was parsed into game["power_play"] and the
setting was resolved into the manager config, but no render path read either,
so no value of show_powerplay changed a single pixel.

A live card now marks a power play in POWER_PLAY_COLOR: "PP" centred between
the clock and the score where those rows can hold it, otherwise (32-row
panels) the clock row itself is coloured. Checked on both render paths -- the
switch scorebug in hockey.py and the scroll/Vegas card in game_renderer.py --
at every size from 64x32 to 192x48 plus 128x64:

  * setting on + power play  -> marker colour present, in the right rows
  * setting on, no power play -> byte-identical to the setting being off
  * setting off + power play  -> byte-identical to no power play
  * the card follows display_options -> league root -> defaults, default True

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_power_play_indicator.py
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
logging.disable(logging.CRITICAL)

SIZES = [(64, 32), (128, 32), (96, 48), (128, 48), (192, 48), (128, 64)]
results = []


def check(name, passed, detail=None):
    results.append((name, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", name,
                           "" if passed or detail is None else " -- %r" % (detail,)))


def marker_rows(img, color):
    """Sorted set of rows containing a pixel of exactly `color`."""
    w, h = img.size
    px = img.load()
    return sorted({y for y in range(h) for x in range(w) if px[x, y] == color})


def main():
    os.chdir(str(CORE))
    from PIL import Image
    import hockey
    from manager import HockeyScoreboardPlugin
    from game_renderer import GameRenderer
    import game_renderer

    color = getattr(hockey, "POWER_PLAY_COLOR", None)
    if color is None or getattr(game_renderer, "POWER_PLAY_COLOR", None) is None:
        check("both render paths define POWER_PLAY_COLOR", False)
        print("\n1 failed -- show_powerplay is never drawn")
        return 1
    check("both render paths use the same marker colour",
          color == game_renderer.POWER_PLAY_COLOR)

    logo = Image.new("RGBA", (16, 16), (0, 0, 200, 255))

    def switch(w, h, display_options, power_play):
        dm = MagicMock()
        dm.matrix = None
        dm.width, dm.height = w, h
        dm.image = Image.new("RGB", (w, h))
        cfg = {"enabled": True, "timezone": "UTC",
               "nhl": {"enabled": True, "display_modes": {"live": True},
                       "display_options": dict(display_options, show_shots_on_goal=True)},
               "ncaa_mens": {"enabled": False}, "ncaa_womens": {"enabled": False}}
        mgr = HockeyScoreboardPlugin("hockey-scoreboard", cfg, dm, MagicMock(), MagicMock()).nhl_live
        mgr._load_and_resize_logo = lambda *a, **k: logo
        mgr._draw_scorebug_layout({
            "id": "1", "home_id": "1", "away_id": "2", "home_abbr": "BOS", "away_abbr": "TOR",
            "home_logo_path": Path("BOS.png"), "away_logo_path": Path("TOR.png"),
            "home_score": "3", "away_score": "2", "period_text": "P2", "clock": "12:45",
            "home_shots": 22, "away_shots": 18, "power_play": power_play, "is_live": True})
        return mgr, dm.image.copy()

    def card(w, h, config_blocks, power_play):
        cfg = {"timezone": "Etc/UTC", "scroll_card": {}, "customization": {},
               "display": {"use_short_date_format": False}}
        cfg.update(config_blocks)
        r = GameRenderer(w, h, cfg, logo_cache={})
        r._load_and_resize_logo = lambda *a, **k: logo
        return r.render_game_card({
            "league": "nhl", "id": "1",
            "home_team": {"abbrev": "BOS", "score": "3"},
            "away_team": {"abbrev": "TOR", "score": "2"},
            "status": {"state": "in", "period": 2, "display_clock": "12:45"},
            "power_play": power_play}, "live").convert("RGB")

    print("switch scorebug (hockey.py)")
    mgr, _ = switch(64, 32, {}, False)
    check("show_powerplay defaults to on when unset", mgr.show_powerplay is True)
    mgr, _ = switch(64, 32, {"show_powerplay": False}, False)
    check("show_powerplay false reaches the live manager", mgr.show_powerplay is False)

    for (w, h) in SIZES:
        _, off = switch(w, h, {"show_powerplay": True}, False)
        _, on = switch(w, h, {"show_powerplay": True}, True)
        _, disabled = switch(w, h, {"show_powerplay": False}, True)
        _check_size("switch %dx%d" % (w, h), w, h, on, off, disabled, color)

    print("\nscroll/Vegas card (game_renderer.py)")
    for (w, h) in SIZES:
        off = card(w, h, {"nhl": {"enabled": True}}, False)
        on = card(w, h, {"nhl": {"enabled": True}}, True)
        disabled = card(w, h, {"nhl": {"enabled": True,
                                       "display_options": {"show_powerplay": False}}}, True)
        _check_size("card %dx%d" % (w, h), w, h, on, off, disabled, color)

    print("\ncard setting ladder")
    ladder = [
        ("unset -> on", {"nhl": {"enabled": True}}, True),
        ("display_options false -> off",
         {"nhl": {"enabled": True, "display_options": {"show_powerplay": False}}}, False),
        ("league-root false -> off", {"nhl": {"enabled": True, "show_powerplay": False}}, False),
        ("defaults false -> off",
         {"nhl": {"enabled": True}, "defaults": {"show_powerplay": False}}, False),
        ("display_options true beats defaults false",
         {"nhl": {"enabled": True, "display_options": {"show_powerplay": True}},
          "defaults": {"show_powerplay": False}}, True),
    ]
    for label, blocks, want in ladder:
        drawn = bool(marker_rows(card(128, 48, blocks, True), color))
        check("%s" % label, drawn == want, drawn)

    failed = [n for n, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


def _check_size(label, w, h, on, off, disabled, color):
    check("%s: no power play draws no marker" % label, not marker_rows(off, color))
    check("%s: setting off + power play == no power play" % label,
          disabled.tobytes() == off.tobytes())
    rows = marker_rows(on, color)
    check("%s: power play draws the marker" % label, bool(rows))
    if not rows:
        return
    if h <= 32:
        # No free row: the clock row (top of the panel) carries the colour.
        check("%s: marker is the clock row (rows %d-%d)" % (label, rows[0], rows[-1]),
              rows[-1] < 12, rows)
    else:
        # "PP" sits below the clock and above the vertical centre (the score).
        check("%s: PP between clock and score (rows %d-%d)" % (label, rows[0], rows[-1]),
              rows[0] >= 9 and rows[-1] < h // 2, rows)


if __name__ == "__main__":
    sys.exit(main())
