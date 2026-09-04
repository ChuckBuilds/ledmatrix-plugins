#!/usr/bin/env python3
"""Every Draw() that renders text must ask for 1-bit text.

An LED panel has no partial brightness. PIL defaults ``fontmode`` to "L", which
anti-aliases TrueType glyphs into a grey fringe the panel can only round off --
so a 4px glyph arrives as a smeared 3px one. ``fontmode = "1"`` turns that off.

Whether it currently *shows* depends on the size: 4x6-font.ttf at 6 is 74%
partial pixels, while PressStart2P at its native 8 is clean by luck. Font sizes
are user-configurable, so "clean today" is not worth relying on -- the setting
belongs on every draw that renders text to the panel.

Checked statically, because the plugins that most need it (mqtt-notifications,
nfl-draft, on-air, static-image) only render with live data the harness has none
of; a render-based check would silently skip exactly those.

Scoped with the AST rather than a file-wide regex: a Draw() is reported only
when *that* binding is used for .text() in the same function. A file-wide match
flags every unrelated `draw` that merely shares the name.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "plugins")

# Offline asset generators: they bake placeholder PNGs on a developer machine,
# not text on the panel. Their output is a logo, and logo resampling is a
# separately-decided question.
SKIP_FILES = {
    "download_assets.py", "logo_downloader.py", "logo_loader.py",
    "cricket_logo_downloader.py", "headshot_downloader.py",
    "generate_placeholder_icon.py", "render_preview.py",
    "render_readme_assets.py",
}


def _is_draw_call(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Draw"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ImageDraw")


def _scan_scope(body, out, path):
    """Report Draw() bindings in this scope that draw text and set no fontmode."""
    draws, texts, fontmodes = {}, set(), set()

    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Assign) and _is_draw_call(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    draws[t.id] = node.lineno
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == "fontmode":
                    if isinstance(t.value, ast.Name):
                        fontmodes.add(t.value.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "text" and isinstance(node.func.value, ast.Name):
                texts.add(node.func.value.id)

    for var, lineno in sorted(draws.items(), key=lambda kv: kv[1]):
        if var in texts and var not in fontmodes:
            out.append(f"{os.path.relpath(path, ROOT)}:{lineno}: "
                       f"`{var}` renders text without fontmode")


def offenders():
    found = []
    for dirpath, _, names in os.walk(PLUGINS):
        for name in sorted(names):
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            if name in SKIP_FILES:
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _scan_scope(node.body, found, path)
    return found


def main():
    bad = offenders()
    if bad:
        print('[FAIL] Draw() renders text without fontmode = "1":')
        for b in bad:
            print(f"  {b}")
        print('\nAdd `<draw>.fontmode = "1"` right after the Draw() call.')
        return 1
    print('[pass] every text-rendering Draw() sets fontmode = "1"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
