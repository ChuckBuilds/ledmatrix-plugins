#!/usr/bin/env python3
"""Regression tests for scripts/check_min_core_version.py.

The gate reports by absence, so a version that stopped looking would print OK
just as confidently as one that looked and found nothing. These pin:

- **Detection.** The M5 shape -- an unguarded ``src.common.sports_shared``
  import under a floor below what its first release reports -- is reported,
  and raising the floor clears it. Core v3.3.1 reports itself as 3.3.0
  (``REPORTED_AS``), so a 3.3.0 floor is the highest one that admits it.
- **Guards.** Only a ``try`` whose handler would catch ImportError excuses an
  import; an ``except ValueError`` or an import in the handler itself does not.
- **The floor is the one the install gate enforces**, including a
  ``compatible_versions`` bound above the declared minimum.
- **It is really scanning the tree**, and the tree is clean once the eight
  scoreboards declare 3.3.0.
- **The table matches core's tags**, when a core checkout with tags is
  available via LEDMATRIX_CORE (that section is skipped otherwise).

Run: python scripts/test_check_min_core_version.py
Exit: 0 pass, 1 fail, 2 skip.
"""

import json
import os
import shutil
import subprocess  # nosec B404 - runs git on the developer's own core checkout
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_min_core_version as gate  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def run(files, manifest=None):
    """Run the gate over one synthetic plugin; return its problem list."""
    root = Path(tempfile.mkdtemp())
    pdir = root / "p"
    pdir.mkdir()
    (pdir / "manifest.json").write_text(json.dumps(
        manifest if manifest is not None else floor("3.2.0")))
    for name, src in files.items():
        path = pdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
    try:
        return gate.check_plugin(pdir)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def floor(v, compat=None):
    return {"id": "p", "compatible_versions": [compat or f">={v}"],
            "versions": [{"version": "1.0.0", "ledmatrix_min_version": v}]}


SHARED = "from src.common.sports_shared import parse_game\n"

# --------------------------------------------------------------------------
print("detection")

check("unguarded sports_shared under a 3.2.0 floor is reported",
      len(run({"sports.py": SHARED}, floor("3.2.0"))) == 1)
check("a 3.3.0 floor clears it: v3.3.1 reports __version__ 3.3.0",
      run({"sports.py": SHARED}, floor("3.3.0")) == [])
check("a 3.3.1 floor clears it too",
      run({"sports.py": SHARED}, floor("3.3.1")) == [])
CARD = "from src.common.sports_card import x\n"
check("a 3.3.0 module under a 3.2.0 floor is reported",
      len(run({"card.py": CARD}, floor("3.2.0"))) == 1)
check("a compatible_versions bound above the declared min counts",
      run({"sports.py": SHARED}, floor("3.2.0", compat=">=3.3.0")) == [])
check("a declared min above compatible_versions counts",
      run({"sports.py": SHARED},
          {"id": "p", "compatible_versions": [">=2.0.0"],
           "min_ledmatrix_version": "3.3.0"}) == [])
check("no floor at all reads as 0.0.0 and is reported",
      len(run({"sports.py": SHARED}, {"id": "p"})) == 1)
check("'import src.x' is seen as well as 'from src.x import'",
      len(run({"m.py": "import src.common.sports_shared\n"})) == 1)
check("'from src.common import sports_card' matches the submodule",
      len(run({"m.py": "from src.common import sports_card as _c\n"},
              floor("3.2.0"))) == 1)
check("a package entry covers its submodules",
      len(run({"m.py": "from src.vegas_mode.plugin_adapter import X\n"},
              floor("3.0.0"))) == 1)
check("modules that predate the plugin system are never reported",
      run({"m.py": "from src.plugin_system.base_plugin import BasePlugin\n"
                   "from src.logo_downloader import LogoDownloader\n"},
          floor("2.0.0")) == [])
check("an unreleased module is reported whatever the floor",
      len(run({"m.py": "from src.common import sports_helpers\n"},
              floor("9.9.9"))) == 1)
check("a 3.4.0 module is reported under a 3.3.0 floor",
      len(run({"m.py": "from src.common import scroll_config\n"},
              floor("3.3.0"))) == 1)
check("a 3.4.0 floor clears a 3.4.0 module",
      run({"m.py": "from src.common import scroll_config\n"},
          floor("3.4.0")) == [])
check("imports inside functions are still imports",
      len(run({"m.py": "def f():\n    " + SHARED})) == 1)
check("a relative import named like core is ignored",
      run({"m.py": "from .src.common.sports_shared import x\n"}) == [])

# --------------------------------------------------------------------------
print("\nguards")

check("try/except ImportError guards",
      run({"m.py": "try:\n    " + SHARED + "except ImportError:\n    pass\n"}) == [])
check("except ModuleNotFoundError in a tuple guards",
      run({"m.py": "try:\n    " + SHARED
                   + "except (ValueError, ModuleNotFoundError):\n    pass\n"}) == [])
check("bare except guards",
      run({"m.py": "try:\n    " + SHARED + "except:\n    pass\n"}) == [])
check("except Exception guards",
      run({"m.py": "try:\n    " + SHARED + "except Exception:\n    pass\n"}) == [])
check("except ValueError does not guard",
      len(run({"m.py": "try:\n    " + SHARED + "except ValueError:\n    pass\n"})) == 1)
check("an import in the except handler is not guarded by its own try",
      len(run({"m.py": "try:\n    import json\nexcept ImportError:\n    "
                       + SHARED})) == 1)
check("an import in finally is not guarded",
      len(run({"m.py": "try:\n    pass\nexcept ImportError:\n    pass\n"
                       "finally:\n    " + SHARED})) == 1)
check("a deferred re-import behind a guarded sibling is excused",
      run({"m.py": "try:\n    " + SHARED + "    OK = True\n"
                   "except ImportError:\n    OK = False\n"
                   "def f():\n    " + SHARED}) == [])
check("a module-level unguarded import is not excused by a guarded sibling",
      len(run({"m.py": "try:\n    " + SHARED + "except ImportError:\n    pass\n"
                       + SHARED})) == 1)

# --------------------------------------------------------------------------
print("\nscope")

check("test files are skipped",
      run({"test_x.py": SHARED, "x_test.py": SHARED, "conftest.py": SHARED,
           "tests/helper.py": SHARED, "test/helper.py": SHARED}) == [])
check("runtime files in subpackages are scanned",
      len(run({"pkg/mod.py": SHARED})) == 1)
check("an unparseable file is skipped, not fatal",
      run({"broken.py": "def (:\n"}) == [])

# --------------------------------------------------------------------------
print("\nprerequisites")

original = gate.PLUGINS
gate.PLUGINS = Path(tempfile.mkdtemp()) / "missing"
try:
    check("a missing plugins directory exits 2", gate.main([]) == 2)
finally:
    gate.PLUGINS = original
check("only unknown plugin ids exits 2", gate.main(["no-such-plugin-xyz"]) == 2)

# --------------------------------------------------------------------------
print("\nthe gate is actually looking")

if not gate.PLUGINS.is_dir():
    print("SKIP: no plugins directory in this checkout")
    sys.exit(2)

plugin_dirs = sorted(p for p in gate.PLUGINS.iterdir()
                     if (p / "manifest.json").is_file())
seen = 0
for pdir in plugin_dirs:
    for path in gate.runtime_files(pdir):
        try:
            seen += sum(1 for _ in gate.core_imports(
                path.read_text(encoding="utf-8", errors="replace")))
        except SyntaxError:
            pass
check("it finds a plausible number of core imports in the tree", seen >= 150,
      f"{seen} imports across {len(plugin_dirs)} plugins")

# The scoreboards floor at 3.3.0, which v3.3.1 reports. Simulate that without
# touching manifests, so this asserts nothing *else* in the tree trips the gate.
real_floor = gate.effective_floor
gate.effective_floor = lambda m: max(real_floor(m), (3, 3, 0)) \
    if str(m.get("id", "")).endswith("-scoreboard") else real_floor(m)
try:
    remaining = [p for d in plugin_dirs for p in gate.check_plugin(d)]
finally:
    gate.effective_floor = real_floor
check("the tree is clean once scoreboards declare 3.3.0", not remaining,
      "; ".join(remaining[:3]))

# --------------------------------------------------------------------------
print("\ntable vs core tags")

core = os.environ.get("LEDMATRIX_CORE", "")


def tree(ref):
    # nosec B603 - fixed argv, no shell; core is LEDMATRIX_CORE, ref a pinned tag
    out = subprocess.run(["git", "-C", core, "ls-tree", "-r", "--name-only", ref,  # nosec B603
                          "--", "src"], capture_output=True, text=True)
    return set(out.stdout.split()) if out.returncode == 0 else None


tags = ["3.0.0", "3.1.0", "3.2.0", "3.3.0", "3.3.1", "3.4.0"]
trees = {t: tree(f"v{t}") for t in tags} if core and os.path.isdir(core) else {}
if not trees or any(v is None for v in trees.values()):
    print("  SKIP  LEDMATRIX_CORE is not a core git checkout with release tags")
else:
    head = tree("HEAD") or set()

    def present(files, module):
        base = module.replace(".", "/")
        return f"{base}.py" in files or f"{base}/__init__.py" in files

    wrong = []
    for module, version in gate.MODULE_FIRST_VERSION.items():
        if version is None:
            if present(trees[tags[-1]], module) or not present(head, module):
                wrong.append(f"{module}: expected unreleased and on HEAD")
            continue
        if version not in trees:
            wrong.append(f"{module}: {version} is not a tracked tag")
            continue
        prev = tags[tags.index(version) - 1]
        if not present(trees[version], module) or present(trees[prev], module):
            wrong.append(f"{module}: not first shipped in {version}")
    check("every table entry first ships in the tag it names", not wrong,
          "; ".join(wrong[:3]))

    # REPORTED_AS must describe what each published tag really says about
    # itself. Tags do not change, so an entry that passes here stays correct.
    import re as _re
    misreport = []
    for tag, says in gate.REPORTED_AS.items():
        out = subprocess.run(["git", "-C", core, "show", f"v{tag}:src/__init__.py"],  # nosec B603
                             capture_output=True, text=True)
        m = _re.search(r'__version__\s*=\s*["\']([^"\']+)', out.stdout)
        if not m or m.group(1) != says:
            misreport.append(f"v{tag} reports {m.group(1) if m else '?'}, table says {says}")
    check("REPORTED_AS matches each tag's __version__", not misreport,
          "; ".join(misreport))

    # A new core module on HEAD that the table does not know about would be
    # silently treated as always-available.
    # src/web_interface is the web UI's own code, not a plugin API.
    def module_of(f):
        mod = f[:-3].replace("/", ".")
        return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod

    untracked = sorted(
        f for f in head - trees["3.0.0"]
        if f.endswith(".py") and "/tests/" not in f
        and not f.startswith("src/web_interface/")
        # a module that became a package (sports.py -> sports/__init__.py)
        # was importable all along
        and not present(trees["3.0.0"], module_of(f))
        and gate.first_version(module_of(f))[0] is None)
    check("no post-3.0.0 core module is missing from the table", not untracked,
          ", ".join(untracked[:5]))

# --------------------------------------------------------------------------
print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
