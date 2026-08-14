#!/usr/bin/env python3
"""Bundled fonts must load regardless of the process working directory.

Every font this scoreboard draws with ships in the LEDMatrix core and used to
be named relative to the cwd -- ImageFont.truetype("assets/fonts/...") and
os.path.join("assets", "fonts", ...). That resolves under the packaged systemd
unit, whose WorkingDirectory is the install root, and nowhere else. The
failure is silent: the load raises, the caller's except branch catches it, and
the scoreboard renders in PIL's default face at the wrong metrics rather than
the pixel font the layout was built around.

These checks run from a temporary directory, so a path that depends on the cwd
cannot accidentally pass.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_font_paths_cwd_independent.py
"""

import ast
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        CORE = Path(_candidate)
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from PIL import ImageFont  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


# Modules in this plugin that load bundled fonts, and the font names they ask
# for -- both discovered from the source rather than hard-coded, so a new call
# site is covered the day it is added.
def font_modules():
    found = {}
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        src = path.read_text(encoding="utf-8")
        names = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value.startswith("assets/fonts/"):
                names.add(node.value)
        if "_resolve_font_path" in src:
            found[path] = names
    return found


def main():
    modules = font_modules()
    print("modules that load bundled fonts: %d" % len(modules))
    check("the plugin has at least one such module", bool(modules))

    # Every bundled font this plugin names, deduplicated.
    all_fonts = sorted({n for names in modules.values() for n in names})
    print("\nbundled fonts referenced: %s" % ", ".join(
        f.rsplit("/", 1)[-1] for f in all_fonts) or "(none)")

    with tempfile.TemporaryDirectory() as tmp:
        original = os.getcwd()
        os.chdir(tmp)
        try:
            # If a bare relative path happened to resolve here the rest of the
            # file would prove nothing, so establish that it does not.
            check("the raw relative path does not resolve from this cwd",
                  all(not os.path.exists(f) for f in all_fonts) if all_fonts else True)

            import importlib
            mod = importlib.import_module("sports")
            resolve = mod._resolve_font_path

            for font in all_fonts:
                resolved = resolve(font)
                ok = os.path.exists(resolved)
                check("resolves %s" % font.rsplit("/", 1)[-1], ok)
                if ok and resolved.lower().endswith(".ttf"):
                    try:
                        loaded = ImageFont.truetype(resolved, 8)
                        check("  loads as a real face, not PIL's default",
                              type(loaded).__name__ == "FreeTypeFont")
                    except OSError as exc:
                        check("  loads as a real face, not PIL's default (%s)" % exc, False)

            print("\nfallback behaviour is unchanged")
            # A configured absolute path must pass straight through.
            probe = os.path.join(tmp, "configured.ttf")
            Path(probe).write_bytes(b"")
            check("an existing absolute path is returned untouched",
                  resolve(probe) == probe)
            # An unknown name must come back as given, so the caller's own
            # try/except fallback still fires exactly as it does today.
            check("an unresolvable name is returned unchanged",
                  resolve("assets/fonts/does-not-exist.ttf")
                  == "assets/fonts/does-not-exist.ttf")
        finally:
            os.chdir(original)

    print("\nno module keeps a cwd-relative bundled font load")
    offenders = []
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        raw_literal = []
        unwrapped_join = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr == "truetype" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("assets/"):
                    raw_literal.append(node.lineno)
            if node.func.attr == "join" and len(node.args) >= 2:
                head = [a.value for a in node.args[:2] if isinstance(a, ast.Constant)]
                if head == ["assets", "fonts"] and \
                        "_resolve_font_path(os.path.join" not in src.splitlines()[node.lineno - 1]:
                    unwrapped_join.append(node.lineno)
        if raw_literal or unwrapped_join:
            offenders.append("%s (truetype lines %s, join lines %s)"
                             % (path.name, raw_literal or "-", unwrapped_join or "-"))
    check("every bundled font load goes through the resolver"
          + ("" if not offenders else " -- still raw in: " + "; ".join(offenders)),
          not offenders)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
