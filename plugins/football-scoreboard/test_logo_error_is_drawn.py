#!/usr/bin/env python3
"""The "Logo Error" fallback must draw on the image that is shown.

Each of the three scorebugs (live in football.py, upcoming and recent in
sports.py) handled a failed logo load by drawing the text on one
`main_img.convert("RGB")` copy and then displaying a second, fresh copy, so the
message never reached the panel and a missing logo left it black for the whole
dwell. The 2026-09 drift audit (P-M13) fixed all three by keeping the converted
image in a name and showing that one.

The fallback sits deep inside display paths that need fonts, logos and a
display manager, so this pins the shape of the code instead, the way
basketball-scoreboard's and hockey-scoreboard's copies of this test do:

  * nothing passes a throwaway `.convert(...)` straight to ImageDraw.Draw;
  * every "Logo Error" site draws on a name and then shows that same name,
    by assigning it to display_manager.image or pasting it;
  * all three sites are still there, so a refactor that moves one cannot make
    the check pass by removing what it inspects.

Run: python plugins/football-scoreboard/test_logo_error_is_drawn.py
"""

import ast
import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent

results = []


def check(case, passed, detail=""):
    results.append((case, bool(passed)))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def draws_on_temporary_convert(tree):
    """Lines with ImageDraw.Draw(<expr>.convert(...)): drawing on a discarded copy."""
    hits = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Draw" and node.args
                and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Attribute)
                and node.args[0].func.attr == "convert"):
            hits.append(node.lineno)
    return hits


def _names_drawn_on(stmts):
    """Names X in `<any> = ImageDraw.Draw(X)` within these statements."""
    names = set()
    for stmt in stmts:
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Draw" and node.args
                    and isinstance(node.args[0], ast.Name)):
                names.add(node.args[0].id)
    return names


def _names_shown(stmts):
    """Names shown on the panel: `display_manager.image = X` or `.paste(X, ...)`."""
    names = set()
    for stmt in stmts:
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
                    and any(isinstance(t, ast.Attribute) and t.attr == "image"
                            for t in node.targets)):
                names.add(node.value.id)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "paste" and node.args
                    and isinstance(node.args[0], ast.Name)):
                names.add(node.args[0].id)
    return names


def logo_error_blocks(tree):
    """(lineno, body) for every `if` body that draws the "Logo Error" text."""
    blocks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if any(isinstance(n, ast.Constant) and n.value == "Logo Error"
               for stmt in node.body for n in ast.walk(stmt)):
            blocks.append((node.lineno, node.body))
    # An outer `if` wrapping a whole scorebug also contains the text; keep only
    # the innermost block for each site.
    innermost = []
    for lineno, body in blocks:
        nested = any(other_line != lineno and any(
            isinstance(n, ast.If) and n.lineno == other_line
            for stmt in body for n in ast.walk(stmt))
            for other_line, _ in blocks)
        if not nested:
            innermost.append((lineno, body))
    return innermost


def main():
    total_sites = 0
    for name in ("football.py", "sports.py"):
        tree = ast.parse((plugin_dir / name).read_text(encoding="utf-8"))
        hits = draws_on_temporary_convert(tree)
        check("%s: no ImageDraw.Draw on a throwaway convert()" % name,
              not hits, "lines %s" % hits)
        for lineno, body in logo_error_blocks(tree):
            total_sites += 1
            drawn, shown = _names_drawn_on(body), _names_shown(body)
            check("%s:%d: the image 'Logo Error' is drawn on is the one shown"
                  % (name, lineno), drawn and drawn & shown,
                  "drawn on %s, shown %s" % (sorted(drawn), sorted(shown)))
    check("all three Logo Error sites are still present", total_sites == 3,
          total_sites)

    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover
        print("SKIP: Pillow not installed")
        return 2

    # Why the shape matters: drawing on a convert() result leaves the source
    # untouched, so showing a second convert() shows nothing.
    main_img = Image.new("RGBA", (32, 16), (0, 0, 0, 255))
    ImageDraw.Draw(main_img.convert("RGB")).text((1, 1), "E", fill=(255, 255, 255))
    check("a throwaway convert() copy leaves the shown image black",
          main_img.convert("RGB").getbbox() is None)
    kept = main_img.convert("RGB")
    ImageDraw.Draw(kept).text((1, 1), "E", fill=(255, 255, 255))
    check("drawing on the kept copy lights the shown image",
          kept.getbbox() is not None)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
