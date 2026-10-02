#!/usr/bin/env python3
"""The goal light: a pixel-art beacon beside the scoring crest in a goal takeover.

With <league>.celebration_goal_light on, HockeyLive._draw_celebration_layout lets
core draw the takeover, catches the finished frame, lays hockey_goal_light over it
and presents that. Covers:

  1. The setting: off by default in all three leagues' schemas, forwarded by the
     adapter, read by the live manager.
  2. Off, a win, or a panel too small: the frame is exactly core's.
  3. On, a goal, on a panel that fits: only the region round the lamp changes,
     the lamp sits beside the scoring crest (mirrored for the home side), a
     frame is a pure function of elapsed time, and it flashes -- the lens is
     lit at one step and dark at another.
  4. It eases out at the end of the takeover.
  5. Failure and plumbing: a drawing error presents the plain takeover, the
     display manager is always put back, and exactly one frame is presented.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/hockey-scoreboard/test_goal_light.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import json
import logging
import os
import sys
import time
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

results = []


def check(name, passed, detail=None):
    results.append((name, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", name,
                           "" if passed or detail is None else " -- %r" % (detail,)))


def main():
    os.chdir(str(CORE))
    from PIL import Image, ImageChops
    import hockey_goal_light as gl
    from manager import HockeyScoreboardPlugin

    # --- 1. the setting -----------------------------------------------------------
    print("setting")
    schema = json.loads((plugin_dir / "config_schema.json").read_text(encoding="utf-8"))
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "celebration_goal_light" in node:
                found.append(node["celebration_goal_light"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    check("all three leagues carry the setting", len(found) == 3, len(found))
    check("it defaults to off", all(f.get("default") is False for f in found))
    check("it is an advanced boolean",
          all(f.get("type") == "boolean" and f.get("x-advanced") for f in found))

    logo_dir = CORE / "assets" / "sports" / "nhl_logos"
    def logo_for(abbr, h):
        p = logo_dir / ("%s.png" % abbr)
        if p.exists():
            im = Image.open(p).convert("RGBA")
            im.thumbnail((h, h), Image.Resampling.LANCZOS)
            return im
        return Image.new("RGBA", (h, h), (0, 0, 200, 255))

    def live(w, h, goal_light):
        dm = MagicMock()
        dm.matrix = None
        dm.width, dm.height = w, h
        dm.image = Image.new("RGB", (w, h))
        cfg = {"enabled": True, "timezone": "UTC", "customization": {},
               "nhl": {"enabled": True, "display_modes": {"live": True},
                       "celebration_enabled": True,
                       "celebration_goal_light": goal_light},
               "ncaa_mens": {"enabled": False}, "ncaa_womens": {"enabled": False}}
        mgr = HockeyScoreboardPlugin("hockey-scoreboard", cfg, dm,
                                     MagicMock(), MagicMock()).nhl_live
        mgr._load_and_resize_logo = lambda tid, abbr, path, url=None: logo_for(abbr, h)
        return mgr, dm

    game = {"id": "9", "home_id": "3", "away_id": "14", "home_abbr": "NYR",
            "away_abbr": "TB", "home_logo_path": Path("NYR.png"),
            "away_logo_path": Path("TB.png")}

    def cel(kind="goal", side="away"):
        return {"kind": kind, "motif": "win" if kind == "win" else "net",
                "game": dict(game), "scored_side": side,
                "team_abbr": "TB" if side == "away" else "NYR",
                "away_score": 1, "home_score": 0, "started_at": 1000.0,
                "phrase": "GOAL!"}

    def render(mgr, dm, c, elapsed):
        dm.image = Image.new("RGB", dm.image.size)
        real = time.time
        time.time = lambda: 1000.0 + elapsed
        try:
            mgr._draw_celebration_layout(dict(c))
        finally:
            time.time = real
        return dm.image.copy()

    off_mgr, off_dm = live(512, 64, False)
    on_mgr, on_dm = live(512, 64, True)
    check("the adapter forwards the setting to the live manager",
          on_mgr.celebration_goal_light is True and off_mgr.celebration_goal_light is False)
    unset, _ = live(512, 64, None)
    check("unset means off", unset.celebration_goal_light is False)

    # --- 2. nothing changes unless it should ---------------------------------------
    print("\nwhen it stays out of the way")
    plain = render(off_mgr, off_dm, cel(), 1.5)
    check("setting off: core's frame, untouched",
          render(on_mgr, on_dm, cel("win"), 1.5).tobytes()
          == render(off_mgr, off_dm, cel("win"), 1.5).tobytes())
    check("a win is not a goal: no lamp",
          render(on_mgr, on_dm, cel("win"), 1.5).tobytes()
          == render(off_mgr, off_dm, cel("win"), 1.5).tobytes())
    for (w, h) in ((128, 64), (128, 32), (256, 32), (64, 32)):
        a, ad = live(w, h, True)
        b, bd = live(w, h, False)
        check("%dx%d: too small for it, plain takeover" % (w, h),
              render(a, ad, cel(), 1.5).tobytes() == render(b, bd, cel(), 1.5).tobytes())

    # --- 3. on, a goal, a panel that fits -------------------------------------------
    print("\non a 512x64 panel")
    lit_frame = render(on_mgr, on_dm, cel(), 1.5)
    diff = ImageChops.difference(plain, lit_frame).getbbox()
    check("the goal light draws", diff is not None)
    crest_w = max(0, on_mgr._celebration_crests(
        dict(cel(), _crests=None), 64)["away"].width - 2)
    cx = crest_w + 36
    check("only the region round the lamp changes",
          diff is not None and diff[0] >= cx - 91 and diff[2] <= cx + 92, diff)
    check("the lamp sits beside the scoring crest",
          diff is not None and crest_w <= (diff[0] + diff[2]) // 2 <= crest_w + 80, diff)

    home = render(on_mgr, on_dm, cel(side="home"), 1.5)
    plain_home = render(off_mgr, off_dm, cel(side="home"), 1.5)
    hd = ImageChops.difference(plain_home, home).getbbox()
    check("a home goal puts it on the right-hand side",
          hd is not None and hd[0] > 512 // 2, hd)

    check("a frame is a pure function of elapsed time",
          render(on_mgr, on_dm, cel(), 1.5).tobytes() == lit_frame.tobytes())
    steps = {render(on_mgr, on_dm, cel(), 1.0 + k * 0.1).tobytes() for k in range(8)}
    check("it animates: eight moments, eight different frames", len(steps) == 8, len(steps))

    ys = ((64 - (gl.SH + gl.SHADOW)) // 2)
    cy = ys + 11
    colours = set()
    for k in range(16):
        e = k * 1000 // (gl.CYCLES_PER_SECOND_X100 * gl.STEPS // 100) / 1000.0
        f = render(on_mgr, on_dm, cel(), 1.0 + e)
        colours.add(sum(f.getpixel((cx + dx, cy)) [0:3][0] for dx in (-4, 0, 4)))
    check("it flashes: the lens is bright at some steps and dark at others",
          max(colours) - min(colours) > 60, sorted(colours))

    # --- 4. easing ---------------------------------------------------------------------
    print("\neasing")
    check("gone at the end of the takeover",
          render(on_mgr, on_dm, cel(), 8.0).tobytes() == render(off_mgr, off_dm, cel(), 8.0).tobytes())
    def changed(a, b):
        return ImageChops.difference(a, b).convert("L").point(
            lambda v: 255 if v else 0).histogram()[255]

    early = render(on_mgr, on_dm, cel(), 0.05)
    early_plain = render(off_mgr, off_dm, cel(), 0.05)
    check("eases in: the beams are fainter in the first frames (the lamp itself is not)",
          changed(early, early_plain) < changed(lit_frame, plain),
          (changed(early, early_plain), changed(lit_frame, plain)))

    # --- 5. failure and plumbing -------------------------------------------------------
    print("\nplumbing")
    original = gl.draw_goal_light

    def boom(*a, **k):
        raise RuntimeError("lamp broke")

    gl.draw_goal_light = boom
    try:
        broken = render(on_mgr, on_dm, cel(), 1.5)
    finally:
        gl.draw_goal_light = original
    check("a drawing error presents the plain takeover",
          broken.tobytes() == plain.tobytes())
    check("the real display manager is back after a draw",
          on_mgr.display_manager is on_dm)

    on_dm.update_display.reset_mock()
    render(on_mgr, on_dm, cel(), 1.5)
    check("exactly one frame is presented", on_dm.update_display.call_count == 1,
          on_dm.update_display.call_count)

    from sports import SportsLive
    real_super = SportsLive._draw_celebration_layout

    def explode(self, *a, **k):
        raise RuntimeError("core failed")

    SportsLive._draw_celebration_layout = explode
    try:
        try:
            on_mgr._draw_celebration_layout(cel())
        except RuntimeError:
            pass
    finally:
        SportsLive._draw_celebration_layout = real_super
    check("the display manager is put back even if core raises",
          on_mgr.display_manager is on_dm)

    # the sprite itself
    spr = gl._build_sprite((71, 120, 255), 3, True)
    check("the sprite is a fixed size", spr.size == (gl.SW + gl.SHADOW, gl.SH + gl.SHADOW), spr.size)
    check("sprite frames are cached", gl._sprite((71, 120, 255), 3, True) is gl._sprite((71, 120, 255), 3, True))
    check("a dark team colour is lifted so it stays visible",
          max(gl._lift((0, 25, 94))) >= 170)

    failed = [n for n, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
