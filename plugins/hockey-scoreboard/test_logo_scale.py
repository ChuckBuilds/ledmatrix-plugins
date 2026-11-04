#!/usr/bin/env python3
"""customization.layout.<home|away>_logo.scale sizes the scorebug logos.

The live, recent and upcoming cards draw each logo at 1.5x the panel height,
pushed a few pixels off its edge, so it bleeds off the top, bottom and side.
That is the classic look and it stays the default; the layout block's scale
multiplies the box, and the outward push eases to 0 as a logo shrinks to the
panel height, so a logo scaled to fit is drawn whole.

1. Unset (or 1.0) sizes the logo exactly as before, on the same cache key.
2. A scale shrinks the box, and a scaled logo is cached apart from the
   unscaled one, so a team drawn at two sizes does not get the first size twice.
   0.67, the value users are told fits, fits on any panel height.
3. The edge bleed is the full base at 1.0 and above, 0 at the fit scale and
   below, and in between in between.
4. The schema declares the scale on both logos, with the default the code uses.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_logo_scale.py
"""

import json
import logging
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

from PIL import Image

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    import sports  # noqa: E402
except ImportError as exc:
    print("SKIP: needs a LEDMatrix core on sys.path (%s)" % exc)
    sys.exit(2)

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Core(sports.SportsCore):
    """SportsCore without the feed: only the logo methods are under test."""

    def _fetch_data(self):
        return None

    def _extract_game_details(self, game_event):
        return None


def make_core(layout=None, width=64, height=32):
    core = object.__new__(_Core)
    core.config = {"customization": {"layout": layout or {}}}
    core.display_width = width
    core.display_height = height
    core.logger = logging.getLogger("test_logo_scale")
    core._logo_cache = OrderedDict()
    core._score_grew = False
    core.sport_key = "nhl"
    return core


def main():
    with tempfile.TemporaryDirectory() as tmp:
        logo_path = Path(tmp) / "TOR.png"
        Image.new("RGBA", (200, 200), (0, 80, 200, 255)).save(logo_path)

        plain = make_core()
        logo = plain._load_and_resize_logo("1", "TOR", logo_path, None,
                                           element="home_logo")
        check("unset scale keeps the classic 1.5x box (48px on a 32-tall panel)",
              logo is not None and logo.size == (48, 48),
              logo and logo.size)
        check("an unscaled logo keeps its bare cache key",
              list(plain._logo_cache) == ["TOR"], list(plain._logo_cache))

        fit = make_core({"home_logo": {"scale": 0.67}, "away_logo": {"scale": 1.0}})
        home = fit._load_and_resize_logo("1", "TOR", logo_path, None,
                                         element="home_logo")
        away = fit._load_and_resize_logo("1", "TOR", logo_path, None,
                                         element="away_logo")
        check("scale 0.67 fits the logo to the panel height",
              home is not None and home.size[1] <= 32, home and home.size)
        check("the other side's scale is its own",
              away is not None and away.size == (48, 48), away and away.size)
        check("a scaled logo is cached apart from the unscaled one",
              set(fit._logo_cache) == {"TOR", "TOR@0.67"}, list(fit._logo_cache))

        tall = make_core({"home_logo": {"scale": 0.67}}, width=400, height=200)
        logo = tall._load_and_resize_logo("1", "TOR", logo_path, None,
                                          element="home_logo")
        check("scale 0.67 fits on a 200-tall panel too (no 1px overhang)",
              logo is not None and logo.size[1] <= 200, logo and logo.size)

        near = make_core({"home_logo": {"scale": 0.4999999},
                          "away_logo": {"scale": 0.5000001}})
        near._load_and_resize_logo("1", "TOR", logo_path, None, element="home_logo")
        near._load_and_resize_logo("1", "TOR", logo_path, None, element="away_logo")
        check("scales that differ only past six digits keep separate cache keys",
              len(near._logo_cache) == 2, list(near._logo_cache))

        bad = make_core({"home_logo": {"scale": "big"}})
        logo = bad._load_and_resize_logo("1", "TOR", logo_path, None,
                                         element="home_logo")
        check("a scale that is not a number falls back to the classic size",
              logo is not None and logo.size == (48, 48), logo and logo.size)

    def bleed(scale, base=10):
        return make_core({"home_logo": {"scale": scale}})._logo_edge_bleed(
            "home_logo", base)

    check("full bleed at 1.0", bleed(1.0) == 10, bleed(1.0))
    check("full bleed above 1.0", bleed(1.5) == 10, bleed(1.5))
    check("no bleed once the logo fits the panel", bleed(0.6) == 0, bleed(0.6))
    check("no bleed at the advertised fit value", bleed(0.67) == 0, bleed(0.67))
    check("part bleed in between", 0 < bleed(0.85) < 10, bleed(0.85))
    check("unset scale bleeds the classic amount",
          make_core()._logo_edge_bleed("away_logo", 2) == 2)

    schema = json.loads((plugin_dir / "config_schema.json").read_text(encoding="utf-8"))
    layout = schema["properties"]["customization"]["properties"]["layout"]["properties"]
    for side in ("home_logo", "away_logo"):
        prop = layout[side]["properties"].get("scale") or {}
        check("%s declares a scale defaulting to 1.0" % side,
              prop.get("type") == "number" and prop.get("default") == 1.0, prop)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
