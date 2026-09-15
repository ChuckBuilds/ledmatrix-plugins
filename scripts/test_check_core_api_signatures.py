#!/usr/bin/env python3
"""Regression tests for scripts/check_core_api_signatures.py.

The gate reports by absence, so these pin that it is really looking:

- **Detection.** The #462 shape -- ``set_scrolling_state(True, frame_hold=...)``
  under a 2.0.0 floor -- is reported, by keyword or by position, and a 3.4.0
  floor clears it.
- **Guards.** Only a try around just that call, catching TypeError or broader,
  excuses it. A try wrapping the whole frame does not (odds-ticker's and
  text-display's shape), and ``hasattr`` never guards a keyword.
- **The tree.** It sees the real calls, and the tree is clean.
- **The table matches core**, when LEDMATRIX_CORE is a core checkout with tags.

Run: python scripts/test_check_core_api_signatures.py
Exit: 0 pass, 1 fail, 2 skip.
"""

import ast
import json
import os
import re
import shutil
import subprocess  # nosec B404 - runs git on the developer's own core checkout
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_core_api_signatures as gate  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def floor(v, compat=None):
    return {"id": "p", "compatible_versions": [compat or f">={v}"],
            "versions": [{"version": "1.0.0", "ledmatrix_min_version": v}]}


def run(files, manifest=None):
    root = Path(tempfile.mkdtemp())
    pdir = root / "p"
    pdir.mkdir()
    (pdir / "manifest.json").write_text(json.dumps(
        manifest if manifest is not None else floor("2.0.0")))
    for name, src in files.items():
        path = pdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
    try:
        return gate.check_plugin(pdir)
    finally:
        shutil.rmtree(root, ignore_errors=True)


HOLD = "self.display_manager.set_scrolling_state(True, frame_hold=self._hold())\n"


def method(body, indent="        "):
    return "class P:\n    def display(self):\n" + "".join(
        indent + line + "\n" for line in body.splitlines())


# --------------------------------------------------------------------------
print("detection")

check("frame_hold= under a 2.0.0 floor is reported (the #462 shape)",
      len(run({"manager.py": method(HOLD)})) == 1)
check("frame_hold passed by position is reported",
      len(run({"manager.py": method("self.dm.set_scrolling_state(True, 2)")})) == 1)
check("set_scrolling_state without frame_hold is fine on any floor",
      run({"manager.py": method("self.dm.set_scrolling_state(True)\n"
                                "self.dm.set_scrolling_state(is_scrolling=False)")}) == [])
check("a 3.3.0 floor (what v3.3.1 reports) is still reported",
      len(run({"manager.py": method(HOLD)}, floor("3.3.0"))) == 1)
check("a 3.4.0 floor clears it",
      run({"manager.py": method(HOLD)}, floor("3.4.0")) == [])
check("a compatible_versions bound above the declared min counts",
      run({"manager.py": method(HOLD)}, floor("2.0.0", compat=">=3.4.0")) == [])
check("a top-level min_ledmatrix_version counts",
      run({"manager.py": method(HOLD)},
          {"id": "p", "compatible_versions": [">=2.0.0"],
           "min_ledmatrix_version": "3.4.0"}) == [])
check("no floor at all is reported",
      len(run({"manager.py": method(HOLD)}, {"id": "p"})) == 1)
check("a new method is reported under an old floor",
      len(run({"m.py": method("self.display_manager.set_frame_hold(2)")})) == 1)
check("a plugin's own method of that name is not core's",
      run({"m.py": "class P:\n    def set_frame_hold(self, n):\n        pass\n"
                   "    def f(self):\n        self.set_frame_hold(2)\n"}) == [])

# --------------------------------------------------------------------------
print("\nguards")

check("a try around just the call, except Exception, guards (elections' shape)",
      run({"m.py": method("try:\n    " + HOLD + "except Exception as e:\n    pass")}) == [])
check("except TypeError guards",
      run({"m.py": method("try:\n    " + HOLD + "except TypeError:\n"
                          "    self.dm.set_scrolling_state(True)")}) == [])
check("bare except guards",
      run({"m.py": method("try:\n    " + HOLD + "except:\n    pass")}) == [])
check("except ValueError does not guard",
      len(run({"m.py": method("try:\n    " + HOLD + "except ValueError:\n    pass")})) == 1)
check("except AttributeError does not guard a keyword",
      len(run({"m.py": method("try:\n    " + HOLD + "except AttributeError:\n    pass")})) == 1)
check("a try wrapping the whole frame does not guard (odds-ticker's shape)",
      len(run({"m.py": method("try:\n    self.update()\n    " + HOLD
                              + "    self.draw()\nexcept Exception:\n    self.fallback()")})) == 1)
check("a one-statement try whose statement is an if block does not guard",
      len(run({"m.py": method("try:\n    if self.loop:\n        " + HOLD
                              + "except Exception:\n    pass")})) == 1)
check("hasattr does not guard a keyword",
      len(run({"m.py": method("if hasattr(self.dm, 'set_scrolling_state'):\n    "
                              + HOLD)})) == 1)
check("hasattr does guard a new method",
      run({"m.py": method("if hasattr(self.dm, 'set_frame_hold'):\n"
                          "    self.dm.set_frame_hold(2)")}) == [])
check("a call under `if not hasattr` is not guarded (it runs when the method is missing)",
      len(run({"m.py": method("if not hasattr(self.dm, 'set_frame_hold'):\n"
                              "    self.dm.set_frame_hold(2)")})) == 1)
check("the else of `if not hasattr` is guarded",
      run({"m.py": method("if not hasattr(self.dm, 'set_frame_hold'):\n    pass\n"
                          "else:\n    self.dm.set_frame_hold(2)")}) == [])
check("the else of a plain `if hasattr` is not guarded",
      len(run({"m.py": method("if hasattr(self.dm, 'set_frame_hold'):\n    pass\n"
                              "else:\n    self.dm.set_frame_hold(2)")})) == 1)
check("`if hasattr(...) and ...` guards its body",
      run({"m.py": method("if hasattr(self.dm, 'set_frame_hold') and self.on:\n"
                          "    self.dm.set_frame_hold(2)")}) == [])
check("`if not hasattr(...) or ...` does not guard its body",
      len(run({"m.py": method("if not hasattr(self.dm, 'set_frame_hold') or self.on:\n"
                              "    self.dm.set_frame_hold(2)")})) == 1)
check("except AttributeError around just the call guards a new method",
      run({"m.py": method("try:\n    self.dm.set_frame_hold(2)\n"
                          "except AttributeError:\n    pass")}) == [])
check("a call in the handler is not guarded by its own try",
      len(run({"m.py": method("try:\n    pass\nexcept Exception:\n    " + HOLD)})) == 1)

# --------------------------------------------------------------------------
print("\nscope and prerequisites")

check("test files are skipped",
      run({"test_x.py": method(HOLD), "test/helper.py": method(HOLD)}) == [])
check("runtime files in subpackages are scanned",
      len(run({"pkg/scroll.py": method(HOLD)})) == 1)
check("an unparseable file is skipped, not fatal",
      run({"broken.py": "def (:\n"}) == [])

original = gate.PLUGINS
gate.PLUGINS = Path(tempfile.mkdtemp()) / "missing"
try:
    check("a missing plugins directory exits 2", gate.main([]) == 2)
finally:
    gate.PLUGINS = original
check("only unknown plugin ids exits 2", gate.main(["no-such-plugin-xyz"]) == 2)

empty = Path(tempfile.mkdtemp())
(empty / "p").mkdir()
(empty / "p" / "manifest.json").write_text(json.dumps(floor("2.0.0")))
(empty / "p" / "manager.py").write_text("x = 1\n")
gate.PLUGINS = empty
try:
    check("a whole-tree scan that sees no tracked call exits 2, not PASS",
          gate.main([]) == 2)
finally:
    gate.PLUGINS = original
    shutil.rmtree(empty, ignore_errors=True)

# --------------------------------------------------------------------------
print("\nthe gate is actually looking")

if not gate.PLUGINS.is_dir():
    print("SKIP: no plugins directory in this checkout")
    sys.exit(2)

plugin_dirs = sorted(p for p in gate.PLUGINS.iterdir()
                     if (p / "manifest.json").is_file())
seen = {}
remaining = [p for d in plugin_dirs for p in gate.check_plugin(d, seen)]
check("it sees a plausible number of set_scrolling_state calls",
      seen.get("set_scrolling_state", 0) >= 10, f"{seen}")

holds = 0
for pdir in plugin_dirs:
    for path in gate.modgate.runtime_files(pdir):
        try:
            calls = gate.tracked_calls(path.read_text(encoding="utf-8", errors="replace"),
                                       {"set_scrolling_state"})
        except SyntaxError:
            continue
        holds += sum(1 for c in calls if "frame_hold" in c.keywords)
check("it sees the frame_hold calls #462 added", holds >= 7, f"{holds}")
check("the tree is clean", not remaining, "; ".join(remaining[:3]))

# --------------------------------------------------------------------------
print("\ntable vs core")

core = os.environ.get("LEDMATRIX_CORE", "")
TAGS = ["3.0.0", "3.1.0", "3.2.0", "3.3.0", "3.3.1", "3.4.0"]


def show(ref, path):
    # nosec B603 - fixed argv, no shell; core is LEDMATRIX_CORE, ref a pinned tag
    out = subprocess.run(["git", "-C", core, "show", f"{ref}:{path}"],  # nosec B603
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    return out.stdout if out.returncode == 0 else None


def params(source, name):
    """Parameter names of every def called `name`, or None if there is none."""
    if source is None:
        return None
    found = None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            a = node.args
            found = (found or set()) | {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    return found


def has(ref, change):
    ps = params(show(ref, change.core_file), change.method)
    if ps is None:
        return False
    return change.keyword is None or change.keyword in ps


if not core or not os.path.isdir(core) or show("v3.3.1", "src/__init__.py") is None:
    print("  SKIP  LEDMATRIX_CORE is not a core git checkout with release tags")
else:
    wrong = []
    for change in gate.API_FIRST_VERSION:
        label = gate._signature(change)
        if change.first_version is None:
            if has(f"v{TAGS[-1]}", change) or not has("HEAD", change):
                wrong.append(f"{label}: expected on HEAD and not in v{TAGS[-1]}")
            continue
        if change.first_version not in TAGS:
            wrong.append(f"{label}: {change.first_version} is not a tracked tag")
            continue
        prev = TAGS[TAGS.index(change.first_version) - 1]
        if not has(f"v{change.first_version}", change) or has(f"v{prev}", change):
            wrong.append(f"{label}: not first shipped in {change.first_version}")
        if change.position is not None and change.keyword:
            src = show("HEAD", change.core_file)
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.FunctionDef) and node.name == change.method:
                    names = [x.arg for x in node.args.args if x.arg != "self"]
                    if change.keyword in names and names.index(change.keyword) != change.position:
                        wrong.append(f"{label}: position {change.position} is wrong")
    check("every table entry matches core's tags and HEAD", not wrong,
          "; ".join(wrong[:3]))

    def reported(ref):
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)', show(ref, "src/__init__.py") or "")
        return m.group(1) if m else None

    # UNTAGGED_SATISFIED_BY is only consulted by None rows; its invariants
    # matter (and are only satisfiable) while core main is ahead of every tag.
    if any(c.first_version is None for c in gate.API_FIRST_VERSION):
        head_reports = reported("HEAD")
        check("UNTAGGED_SATISFIED_BY is what core HEAD reports",
              head_reports == gate.UNTAGGED_SATISFIED_BY,
              f"HEAD reports {head_reports}")
        parse = gate.modgate.parse_version
        too_high = [t for t in TAGS
                    if parse(reported(f"v{t}") or "0") >= parse(gate.UNTAGGED_SATISFIED_BY)]
        check("no tracked release tag reports UNTAGGED_SATISFIED_BY or higher",
              not too_high, ", ".join(too_high))
    else:
        print("  SKIP  UNTAGGED_SATISFIED_BY checks: no None entries in the table")

# --------------------------------------------------------------------------
print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
