#!/usr/bin/env python3
"""Regression tests for update_registry.py's registry/plugins-tree check.

update_registry.py iterates only entries already in plugins.json. A new
monorepo plugin directory with no hand-added entry was never published, and a
registry plugin_path whose directory was removed or renamed was only logged.
Both passed with exit 0. `--check` now fails on either; these pin that, and
that it still passes on the real tree (so the check is actually looking at
the 40-odd plugins, not an empty directory).

Exit codes: 0 pass, 1 fail.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import update_registry as reg  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def entry(pid, path):
    return {"id": pid, "plugin_path": path, "latest_version": "1.0.0"}


def make_tree(entries, dirs):
    root = Path(tempfile.mkdtemp())
    (root / "plugins").mkdir()
    for d in dirs:
        (root / "plugins" / d).mkdir()
        (root / "plugins" / d / "manifest.json").write_text(
            json.dumps({"id": d, "version": "1.0.0"}))
    (root / "plugins.json").write_text(json.dumps({"plugins": entries}))
    return root


def run_check(root, *extra):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = reg.main(["--registry", str(root / "plugins.json"), *extra])
    return code, out.getvalue()


def case(label, entries, dirs, expect_code, needle=None, extra=("--check",)):
    root = make_tree(entries, dirs)
    try:
        code, out = run_check(root, *extra)
        ok = code == expect_code and (needle is None or needle in out)
        check(f"{label} (exit {code})", ok)
        if not ok:
            print(out)
        return root
    finally:
        shutil.rmtree(root, ignore_errors=True)


print("synthetic trees")
case("in sync passes", [entry("a", "plugins/a")], ["a"], 0)
case("id differs from dir, matched by plugin_path, passes",
     [entry("weather", "plugins/ledmatrix-weather")], ["ledmatrix-weather"], 0)
case("third-party entry with empty plugin_path is ignored",
     [entry("a", "plugins/a"), entry("ext", "")], ["a"], 0)
case("plugin dir with no registry entry fails",
     [entry("a", "plugins/a")], ["a", "newbie"], 1, "plugins/newbie has a manifest")
case("registry plugin_path with no directory fails",
     [entry("a", "plugins/a"), entry("gone", "plugins/gone")], ["a"], 1,
     "no plugins/gone/manifest.json")
case("two entries claiming one plugin_path fails",
     [entry("a", "plugins/a"), entry("a2", "plugins/a/")], ["a"], 1, "both claim")
case("without --check the same problem only warns",
     [entry("a", "plugins/a")], ["a", "newbie"], 0, "WARNING", extra=())

# A directory without a manifest (assets-only, leftovers) is not a plugin.
root = make_tree([entry("a", "plugins/a")], ["a"])
(root / "plugins" / "scratch").mkdir()
code, _ = run_check(root, "--check")
check(f"a directory without manifest.json is not a plugin (exit {code})", code == 0)
shutil.rmtree(root, ignore_errors=True)

# --check must never write.
root = make_tree([entry("a", "plugins/a")], ["a"])
(root / "plugins" / "a" / "manifest.json").write_text(
    json.dumps({"id": "a", "version": "2.0.0"}))
before = (root / "plugins.json").read_text()
run_check(root, "--check")
check("--check does not rewrite plugins.json",
      (root / "plugins.json").read_text() == before)
shutil.rmtree(root, ignore_errors=True)

print("\nthe real tree")
registry = json.loads((REPO / "plugins.json").read_text(encoding="utf-8"))
monorepo = [p for p in registry["plugins"] if p.get("plugin_path")]
dirs = [d for d in (REPO / "plugins").iterdir() if (d / "manifest.json").is_file()]
check(f"the check sees a plausible tree ({len(dirs)} plugin dirs, "
      f"{len(monorepo)} monorepo entries)", len(dirs) >= 20 and len(monorepo) >= 20)
problems = reg.find_consistency_problems(registry, REPO / "plugins")
for p in problems:
    print(f"        {p}")
check("plugins.json and plugins/ agree", not problems)

print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
sys.exit(1 if failures else 0)
