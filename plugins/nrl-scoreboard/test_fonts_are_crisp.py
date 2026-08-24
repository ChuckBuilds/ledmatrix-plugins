#!/usr/bin/env python3
"""Every default font must render with no anti-aliasing.

PressStart2P is crisp only at multiples of 8, 4x6-font only at multiples of 7.
This lineage asked for 10px scores and 6px status/detail -- all off-grid, so
the glyphs were anti-aliased: measured 64% of lit score pixels and 86% of lit
status pixels were partially lit. On an LED matrix a part-lit pixel is a dim
lamp, not a soft edge, which is why the text read as smeared rather than small.

The part that makes this stick is the config rule. The web UI's save flow
writes the FULL schema default block into config.json for every element on
every save, so essentially every real install carries an explicit
"font_size": 10. Snapping only the code default would therefore have changed
nothing on an actual device. A configured size counts as a real choice only
when it DIFFERS from the schema default; one that merely echoes it is treated
as unchosen and snapped.

Both render paths are covered: game_renderer.py (scroll/Vegas cards) and
sports.py (the regular display).

Run: <core-venv>/bin/python plugins/nrl-scoreboard/test_fonts_are_crisp.py
"""

import os
import sys
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

import json  # noqa: E402
import logging  # noqa: E402
logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def aa_pct(font):
    """Share of lit pixels that are neither fully on nor fully off."""
    from PIL import Image, ImageDraw
    img = Image.new("L", (600, 90), 0)
    try:
        ImageDraw.Draw(img).text((4, 4), "00-00 Final Q4", font=font, fill=255)
    except Exception:
        return -1.0
    lit = [p for p in img.getdata() if p > 0]
    if not lit:
        return 0.0
    return 100.0 * sum(1 for p in lit if p < 255) / len(lit)


def schema_default_config():
    """A config shaped like one the web UI would have written."""
    path = plugin_dir / "config_schema.json"
    if not path.exists():
        return {}
    props = (json.loads(path.read_text()).get("properties", {})
             .get("customization", {}).get("properties", {}))
    cust = {}
    for key, spec in props.items():
        sp = spec.get("properties", {})
        entry = {}
        if "font" in sp and sp["font"].get("default") is not None:
            entry["font"] = sp["font"]["default"]
        if "font_size" in sp and sp["font_size"].get("default") is not None:
            entry["font_size"] = sp["font_size"]["default"]
        if entry:
            cust[key] = entry
    return {"customization": cust}


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer

    if not hasattr(GameRenderer, "_FONT_PIXEL_GRID"):
        print("  [FAIL] no _FONT_PIXEL_GRID -- fonts are still loaded at "
              "whatever size config asks for, so the off-grid defaults "
              "(10px score, 6px status) render anti-aliased.")
        print("\n1 failed")
        return 1

    grid = GameRenderer._FONT_PIXEL_GRID
    schema_cfg = schema_default_config()

    print("the grid table describes real files, and describes them correctly")
    from PIL import ImageFont
    for name, step in grid.items():
        path = CORE / "assets" / "fonts" / name
        check("%s exists" % name, path.exists())
        if not path.exists():
            continue
        check("%s is crisp at %d" % (name, step),
              aa_pct(ImageFont.truetype(str(path), step)) == 0.0)
        check("%s is NOT crisp at %d" % (name, step + 2),
              aa_pct(ImageFont.truetype(str(path), step + 2)) > 0.0)

    print("\nscroll/Vegas card fonts are crisp at every height")
    for h in (32, 48, 64, 96, 128):
        for label, cfg in (("bare", {}), ("schema-default config", schema_cfg)):
            r = GameRenderer(128, h, cfg)
            worst = max((aa_pct(f) for f in r.fonts.values()), default=0.0)
            check("h=%-3d %-22s worst anti-aliasing %.0f%%" % (h, label, worst),
                  worst <= 0.0)

    print("\nregular-display fonts are crisp too")
    import sports as _sports
    base = None
    for nm in dir(_sports):
        o = getattr(_sports, nm)
        if isinstance(o, type) and hasattr(o, "_load_fonts") and \
                hasattr(o, "_load_custom_font_from_element_config"):
            base = o
            break
    if base is None:
        check("found the regular-display font loader", False)
    else:
        probe = type("Probe", (base,), {
            "_extract_game_details": lambda s, *a, **k: None,
            "_fetch_data": lambda s, *a, **k: None})
        inst = probe.__new__(probe)
        inst.logger = logging.getLogger("test")
        for label, cfg in (("bare", {}), ("schema-default config", schema_cfg)):
            inst.config = cfg
            worst = max((aa_pct(f) for f in inst._load_fonts().values()),
                        default=0.0)
            check("%-22s worst anti-aliasing %.0f%%" % (label, worst),
                  worst <= 0.0)

    print("\na size the user genuinely chose is still respected")
    r = GameRenderer(128, 64, {"customization": {"score_text": {"font_size": 13}}})
    check("an explicit 13px score is left at 13px", r.fonts["score"].size == 13)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
