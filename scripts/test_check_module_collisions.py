#!/usr/bin/env python3
"""Regression tests for scripts/check_module_collisions.py.

The gate reports by absence ("no collisions"), so the ways it can stop looking
are silent. These pin:

- **It still detects** the real case it was written for (elections vs flights,
  both shipping data_model.py, imported from a lazily-loaded subpackage) and a
  function-scoped import.
- **An unparseable file fails.** It used to be treated as import-free, so the
  one file the gate could not read reported "OK".
- **Packages are module names too.** A deferred ``import data.teams`` binds
  whichever plugin's ``data`` package is first on sys.path, so a subdirectory
  holding .py files is a collision candidate. Test/tooling dirs are not.
- **It is looking at the real tree**: a plausible plugin and file count, and
  main is clean.

Exit codes: 0 pass, 1 fail.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_module_collisions as gate  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def build(files):
    """files: {"plugin/rel/path.py": source}. Every plugin gets a manifest."""
    root = Path(tempfile.mkdtemp())
    for rel, src in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    for pdir in {Path(rel).parts[0] for rel in files}:
        (root / pdir / "manifest.json").write_text(json.dumps({"id": pdir}))
    return root


def run(files):
    root = build(files)
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = gate.main(root, min_plugins=1)
        return code, out.getvalue()
    finally:
        shutil.rmtree(root, ignore_errors=True)


MANAGER = "class P:\n    pass\n"

print("detection")
code, out = run({
    "elections/manager.py": MANAGER,
    "elections/data_model.py": "X = 1\n",
    "elections/providers/__init__.py": "from data_model import X\n",
    "flights/manager.py": MANAGER,
    "flights/data_model.py": "X = 2\n",
})
check(f"subpackage import of a shared module fails (exit {code})",
      code == 1 and "deferred-imports 'data_model'" in out)

code, out = run({
    "a/manager.py": MANAGER,
    "a/helpers.py": "def f():\n    return 1\n",
    "a/sports.py": "def later():\n    import helpers\n",
    "b/manager.py": MANAGER,
    "b/helpers.py": "",
})
check(f"function-scoped import of a shared module fails (exit {code})", code == 1)

code, out = run({
    "a/manager.py": MANAGER,
    "a/sports.py": "import helpers\n",
    "a/helpers.py": "",
    "b/manager.py": MANAGER,
    "b/helpers.py": "",
})
check(f"module-level import in a top-level file is safe (exit {code})", code == 0)

code, out = run({
    "a/manager.py": MANAGER,
    "a/a_model.py": "",
    "a/providers/__init__.py": "from a_model import X\n",
    "b/manager.py": MANAGER,
})
check(f"a plugin-unique name passes (exit {code})", code == 0)

print("\nunparseable files")
code, out = run({
    "a/manager.py": MANAGER,
    "a/broken.py": "def oops(:\n",
})
check(f"a syntax error fails instead of reading as clean (exit {code})",
      code == 1 and "broken.py" in out and "could not be parsed" in out)

root = build({"a/manager.py": MANAGER})
(root / "a" / "latin1.py").write_bytes(b"# caf\xe9\nX = 1\n")
with contextlib.redirect_stdout(io.StringIO()) as buf:
    code = gate.main(root, min_plugins=1)
shutil.rmtree(root, ignore_errors=True)
check(f"a non-UTF-8 file fails (exit {code})", code == 1 and "latin1.py" in buf.getvalue())

print("\npackages as collision candidates")
code, out = run({
    "olympics/manager.py": MANAGER,
    "olympics/data/__init__.py": "",
    "olympics/data/medals.py": "",
    "olympics/renderers/__init__.py": "from data import medals\n",
    "other/manager.py": MANAGER,
    "other/data/teams.py": "",
})
check(f"a deferred import of a package another plugin also ships fails (exit {code})",
      code == 1 and "deferred-imports 'data'" in out)

code, out = run({
    "olympics/manager.py": MANAGER,
    "olympics/data/__init__.py": "",
    "olympics/renderers/__init__.py": "from data import medals\n",
    "other/manager.py": MANAGER,
    "other/data/readme.txt": "no python here",
})
check(f"a same-named directory with no .py files is not a candidate (exit {code})",
      code == 0)

code, out = run({
    "a/manager.py": MANAGER,
    "a/renderers/__init__.py": "import scripts\n",
    "a/scripts/tool.py": "",
    "b/manager.py": MANAGER,
    "b/scripts/tool.py": "",
})
check(f"test/tooling directories are not candidates (exit {code})", code == 0)

print("\nthe real tree")
violations, unparseable, owners, n_plugins, n_files = gate.find_problems(gate.PLUGINS_DIR)
check(f"{n_plugins} plugins inspected (>= {gate.MIN_PLAUSIBLE_PLUGINS})",
      n_plugins >= gate.MIN_PLAUSIBLE_PLUGINS)
check(f"{n_files} files parsed (a plausible amount, >= 150)", n_files >= 150)
check("known shared top-level module 'sports' is seen as shared",
      len(owners.get("sports", ())) > 1)
for v in violations:
    print(f"        {v}")
for u in unparseable:
    print(f"        {u}")
check("main has no collisions and no unparseable files",
      not violations and not unparseable)

print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
sys.exit(1 if failures else 0)
