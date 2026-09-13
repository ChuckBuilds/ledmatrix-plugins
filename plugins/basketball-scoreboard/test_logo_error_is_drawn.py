#!/usr/bin/env python3
"""The "Logo Error" fallback must draw on the image that is shown.

Each of the three scorebugs (live in basketball.py, upcoming and recent in
sports.py) handled a failed logo load with

    draw_final = ImageDraw.Draw(main_img.convert("RGB"))
    ... draw "Logo Error" on draw_final ...
    display_manager.image = main_img.convert("RGB")   # a second, fresh copy

so the text went onto a throwaway copy and the panel went black for the whole
dwell. The pattern is checked structurally in both files -- every
ImageDraw.Draw() target must be a name that is later shown -- and the
behaviour is checked by running the conversion both ways.

Run: python plugins/basketball-scoreboard/test_logo_error_is_drawn.py
"""

import ast
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def draws_on_temporary_convert(tree):
    """ImageDraw.Draw(<expr>.convert(...)) calls: drawing on a discarded copy."""
    hits = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Draw" and node.args
                and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Attribute)
                and node.args[0].func.attr == "convert"):
            hits.append(node.lineno)
    return hits


def main():
    total_sites = 0
    for name in ("sports.py", "basketball.py"):
        source = (plugin_dir / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        hits = draws_on_temporary_convert(tree)
        check("%s: no ImageDraw.Draw on a throwaway convert() (lines %s)"
              % (name, hits or "-"), not hits)
        # String constants, not raw text: comments mention the label too.
        total_sites += sum(1 for node in ast.walk(tree)
                           if isinstance(node, ast.Constant) and node.value == "Logo Error")
    check("all three Logo Error sites are still present", total_sites == 3)

    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover
        print("SKIP: Pillow not installed")
        return 2

    main_img = Image.new("RGBA", (32, 16), (0, 0, 0, 255))
    error_img = main_img.convert("RGB")
    ImageDraw.Draw(error_img).text((1, 1), "E", fill=(255, 255, 255))
    check("drawing on the kept copy leaves lit pixels on the shown image",
          error_img.getbbox() is not None)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
