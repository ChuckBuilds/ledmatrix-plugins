#!/usr/bin/env python3
"""A scroll display reuses its GameRenderer from one build to the next.

prepare_scroll_content built a new GameRenderer for every strip. Its
constructor loads fonts and the element-style schema, and in adaptive layout
its LayoutContext caches every fitted logo and text size -- all thrown away
per build. The display now keeps the renderer between builds
(_take_card_renderer / _keep_card_renderer). These checks pin that it is
reused only when nothing it was built from has changed, that a reused one
draws exactly what a fresh one draws, and that two overlapping builds never
share one.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_scroll_renderer_reuse.py
"""

import logging
import os
import sys
import time
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
logging.disable(logging.CRITICAL)

LOGOS = plugin_dir / "assets" / "sports" / "nfl_logos"
results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           ("  -- " + detail) if detail and not passed else ""))


class _Matrix:
    width = 192
    height = 48


class _DisplayManager:
    width = 192
    height = 48
    matrix = _Matrix()


def _games():
    pairs = [("KC", "BUF"), ("GB", "CHI"), ("DAL", "PHI"), ("SF", "SEA"),
             ("MIA", "NYJ"), ("DEN", "LV"), ("PIT", "BAL")]
    return [{
        "id": str(i), "league": "nfl",
        "home_abbr": h, "home_id": f"h{i}", "home_logo_path": str(LOGOS / f"{h}.png"),
        "away_abbr": a, "away_id": f"a{i}", "away_logo_path": str(LOGOS / f"{a}.png"),
        "home_score": "21", "away_score": "17", "is_final": True,
        "status_text": "Final", "period_text": "Final",
    } for i, (h, a) in enumerate(pairs)]


def _display(sd, config):
    return sd.ScrollDisplay(display_manager=_DisplayManager(), config=config,
                            custom_logger=logging.getLogger("t"),
                            global_config={})


def _strip(display):
    return display.scroll_helper.cached_image.copy()


def _same(a, b):
    from PIL import ImageChops
    return a.size == b.size and ImageChops.difference(
        a.convert("RGB"), b.convert("RGB")).getbbox() is None


def main():
    os.chdir(str(CORE))
    import scroll_display as sd

    built = []
    real = sd.GameRenderer

    class Counting(real):
        def __init__(self, *a, **k):
            built.append(1)
            super().__init__(*a, **k)

    sd.GameRenderer = Counting
    try:
        for layout in ("classic", "adaptive"):
            print(f"{layout} layout")
            config = {"layout_mode": layout}
            games = _games()

            d = _display(sd, config)
            built.clear()
            ok1 = d.prepare_scroll_content(games, "recent", ["nfl"])
            first = _strip(d)
            after_first = len(built)
            t0 = time.perf_counter()
            ok2 = d.prepare_scroll_content(games, "recent", ["nfl"])
            reused_ms = (time.perf_counter() - t0) * 1000
            second = _strip(d)
            check("both builds succeed", ok1 and ok2)
            check("the second build builds no renderer at all",
                  after_first >= 1 and len(built) == after_first,
                  f"{after_first} for the first build, "
                  f"{len(built) - after_first} for the second")
            fresh = _display(sd, config)
            t0 = time.perf_counter()
            fresh.prepare_scroll_content(games, "recent", ["nfl"])
            fresh_ms = (time.perf_counter() - t0) * 1000
            check("a reused renderer draws the same strip as a fresh one",
                  _same(second, _strip(fresh)) and _same(first, second))
            print(f"     (7-card build: fresh renderer {fresh_ms:.0f} ms, "
                  f"reused {reused_ms:.0f} ms)")

            d = _display(sd, config)
            d.prepare_scroll_content(games, "recent", ["nfl"], {"KC": 1})
            d.prepare_scroll_content(games, "recent", ["nfl"], None)
            check("a build without rankings does not keep the last build's",
                  d._card_renderer._team_rankings_cache == {})

            d = _display(sd, config)
            d.prepare_scroll_content(games, "recent", ["nfl"])
            before = d._card_renderer
            d.config = dict(config)
            d.prepare_scroll_content(games, "recent", ["nfl"])
            check("a new config object gets a new renderer",
                  d._card_renderer is not before
                  and d._card_renderer.config is d.config)

            d = _display(sd, config)
            d.prepare_scroll_content(games, "recent", ["nfl"])
            held = d._take_card_renderer(d._card_renderer.display_width)
            check("a renderer taken by one build is not handed to another",
                  d._take_card_renderer(held.display_width) is not held)
            d._keep_card_renderer(held)
            check("it is handed back for the next build",
                  d._take_card_renderer(held.display_width) is held)
            check("another card width gets a new renderer",
                  d._take_card_renderer(held.display_width + 16) is not held)
    finally:
        sd.GameRenderer = real

    failed = [c for c, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
