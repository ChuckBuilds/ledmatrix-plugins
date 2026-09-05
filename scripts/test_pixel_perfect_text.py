#!/usr/bin/env python3
"""Every Draw() that renders text must ask for 1-bit text.

An LED panel has no partial brightness. PIL defaults ``fontmode`` to "L", which
anti-aliases TrueType glyphs into a grey fringe the panel can only round off --
so a 4px glyph arrives as a smeared 3px one. ``fontmode = "1"`` turns that off.

Whether it currently *shows* depends on the size: 4x6-font.ttf at 6 is 74%
partial pixels, while PressStart2P at its native 8 is clean by luck. Font sizes
are user settings, so "clean today" is not worth relying on -- the setting
belongs on every draw that renders text to the panel.

Checked statically, because the plugins that most need it (mqtt-notifications,
nfl-draft, on-air, static-image) only render with live data the harness has none
of; a render-based check would silently skip exactly those.

Scoping, and why it is not simply "same function":

    A file-wide regex flags every unrelated `draw` that merely shares the name.
    But requiring `.text()` in the *same* scope is worse: it misses the common
    shape where a renderer builds the Draw and hands it to a helper --
    ledmatrix-flights has ten Draw sites and not one of them calls .text()
    itself, they all pass `draw` to _draw_centered()/_draw(). Six were
    anti-aliased and an earlier same-scope version of this gate reported the
    file clean.

    So a binding counts as text-rendering if it either draws text itself or is
    passed to something that might. Both directions matter; only checking one
    produced a green gate over a real defect.
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

NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _is_draw_call(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Draw"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ImageDraw")


def _walk_scope(nodes):
    """Yield every node in this scope, without descending into nested scopes."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, NESTED):
                stack.append(child)


def _text_drawing_helpers(tree):
    """Names of functions in this module that draw text on a parameter.

    ledmatrix-flights' renderers never call .text() themselves -- they hand the
    Draw to _draw_centered()/_draw(), which do. Resolving that is the difference
    between catching those six anti-aliased sites and reporting the file clean.

    Iterated to a fixpoint so a helper that only forwards to another helper
    (_draw_centered -> _truncate -> draw.text) still counts.
    """
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            funcs[node.name] = (node, params)

    drawing = set()
    changed = True
    while changed:
        changed = False
        for name, (node, params) in funcs.items():
            if name in drawing:
                continue
            hit = False
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
                    continue
                recv = sub.func.value
                # param.text(...)
                if (sub.func.attr == "text" and isinstance(recv, ast.Name)
                        and recv.id in params):
                    hit = True
                    break
                # forwarded to a helper already known to draw text
                if sub.func.attr in drawing:
                    args = list(sub.args) + [kw.value for kw in sub.keywords]
                    if any(isinstance(a, ast.Name) and a.id in params for a in args):
                        hit = True
                        break
            if hit:
                drawing.add(name)
                changed = True
    return drawing


def _scan_scope(body, out, path, helpers=frozenset()):
    draws = []          # (name, lineno) in source order
    texts = set()       # names that call .text()
    handed_off = set()  # names passed to another call -- the callee may draw text
    crisp = []          # (name, lineno) where fontmode is set to exactly "1"

    for node in _walk_scope(body):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and _is_draw_call(node.value):
                    draws.append((tgt.id, node.lineno))
                # Only `fontmode = "1"` counts. Recording any assignment would
                # let `fontmode = "L"` satisfy the gate.
                elif (isinstance(tgt, ast.Attribute) and tgt.attr == "fontmode"
                        and isinstance(tgt.value, ast.Name)
                        and isinstance(node.value, ast.Constant)
                        and node.value.value == "1"):
                    crisp.append((tgt.value.id, node.lineno))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if (node.func.attr == "text"
                        and isinstance(node.func.value, ast.Name)):
                    texts.add(node.func.value.id)
                if node.func.attr in helpers:
                    for arg in list(node.args) + [kw.value for kw in node.keywords]:
                        if isinstance(arg, ast.Name):
                            handed_off.add(arg.id)
            elif isinstance(node.func, ast.Name) and node.func.id in helpers:
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    if isinstance(arg, ast.Name):
                        handed_off.add(arg.id)

    for name, lineno in sorted(draws, key=lambda d: d[1]):
        if name not in texts and name not in handed_off:
            continue  # this Draw never renders text
        # The setting must come after this binding, or it configured the
        # previous object bound to the same name.
        if any(cname == name and cline > lineno for cname, cline in crisp):
            continue
        rel = os.path.relpath(path, ROOT)
        out.append(f"{rel}:{lineno}: `{name}` renders text without fontmode = \"1\"")


def _scopes(tree):
    """Every function body in the module, plus module level."""
    yield tree.body
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.body


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
            helpers = _text_drawing_helpers(tree)
            for body in _scopes(tree):
                _scan_scope(body, found, path, helpers)
    return sorted(set(found))


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
