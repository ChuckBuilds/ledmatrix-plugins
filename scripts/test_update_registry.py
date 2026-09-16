#!/usr/bin/env python3
"""Regression tests for update_registry.py's registry/plugins-tree check.

update_registry.py iterates only entries already in plugins.json. A new
monorepo plugin directory with no hand-added entry was never published, and a
registry plugin_path whose directory was removed or renamed was only logged.
Both passed with exit 0. `--check` now fails on either; these pin that, and
that it still passes on the real tree (so the check is actually looking at
the 40-odd plugins, not an empty directory).

`--check` also fails when an entry's `latest_version` is behind *or* ahead of
its manifest, or a synced metadata field differs. It used to discard that
result and print PASS.

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


def make_tree(entries, dirs, manifests=None):
    """A registry plus plugin dirs; `manifests` overrides a dir's manifest."""
    root = Path(tempfile.mkdtemp())
    (root / "plugins").mkdir()
    for d in dirs:
        (root / "plugins" / d).mkdir()
        manifest = (manifests or {}).get(d, {"id": d, "version": "1.0.0"})
        (root / "plugins" / d / "manifest.json").write_text(json.dumps(manifest))
    (root / "plugins.json").write_text(json.dumps({"plugins": entries}))
    return root


def run_check(root, *extra):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = reg.main(["--registry", str(root / "plugins.json"), *extra])
    return code, out.getvalue()


def case(label, entries, dirs, expect_code, needle=None, extra=("--check",),
         manifests=None):
    root = make_tree(entries, dirs, manifests)
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

print("\nregistry vs manifest drift")
# --check used to discard update_registry()'s result and fail only on
# coverage, so a registry behind or ahead of its manifest, or with stale
# metadata, printed PASS.
case("registry behind its manifest fails",
     [entry("a", "plugins/a")], ["a"], 1, "is behind manifest version '1.1.0'",
     manifests={"a": {"id": "a", "version": "1.1.0"}})
case("registry ahead of its manifest fails",
     [{**entry("a", "plugins/a"), "latest_version": "1.2.0"}], ["a"], 1,
     "is ahead of manifest version '1.0.0'")
case("a synced metadata field that differs fails",
     [{**entry("a", "plugins/a"), "description": "old"}], ["a"], 1,
     "description differs",
     manifests={"a": {"id": "a", "version": "1.0.0", "description": "new"}})
case("a metadata field the manifest does not carry is not drift",
     [{**entry("a", "plugins/a"), "description": "registry only"}], ["a"], 0)
case("'1.0' and '1.0.0' are the same version",
     [{**entry("a", "plugins/a"), "latest_version": "1.0"}], ["a"], 0)
case("a third-party entry's version is not compared",
     [entry("a", "plugins/a"), {"id": "ext", "plugin_path": "", "latest_version": "9.9.9"}],
     ["a"], 0)
case("without --check a registry ahead only warns",
     [{**entry("a", "plugins/a"), "latest_version": "1.2.0"}], ["a"], 0,
     "WARNING a: plugins.json latest_version '1.2.0' is ahead", extra=())
case("--dry-run alone does not fail on drift",
     [entry("a", "plugins/a")], ["a"], 0, extra=("--dry-run",),
     manifests={"a": {"id": "a", "version": "1.1.0"}})

# A normal run fixes what it reports, so --check passes straight after it --
# except "ahead", which it must not "fix" by downgrading.
root = make_tree([entry("a", "plugins/a"),
                  {**entry("b", "plugins/b"), "latest_version": "3.0.0"}],
                 ["a", "b"],
                 {"a": {"id": "a", "version": "1.1.0", "name": "A",
                        "last_updated": "2026-01-02"},
                  "b": {"id": "b", "version": "2.0.0"}})
code, _ = run_check(root)
written = {p["id"]: p for p in json.loads((root / "plugins.json").read_text())["plugins"]}
check(f"a normal run syncs version and metadata (exit {code})",
      code == 0 and written["a"]["latest_version"] == "1.1.0"
      and written["a"]["name"] == "A" and written["a"]["last_updated"] == "2026-01-02")
check("a normal run never downgrades a registry that is ahead",
      written["b"]["latest_version"] == "3.0.0")
code, out = run_check(root, "--check")
check(f"--check after a normal run fails only on the entry it could not fix (exit {code})",
      code == 1 and "b: plugins.json latest_version '3.0.0' is ahead" in out
      and "FAIL a:" not in out)
shutil.rmtree(root, ignore_errors=True)

print("\nlast_updated is the newer of last_updated and versions[0].released")
# 27+ manifests had a top-level last_updated older than their newest release,
# and the registry copied the stale date.


def with_dates(last_updated=None, released=None):
    manifest = {"id": "a", "version": "1.0.0",
                "versions": [{"version": "1.0.0", **({"released": released} if released else {})}]}
    if last_updated:
        manifest["last_updated"] = last_updated
    return manifest


for label, manifest, want in [
    ("released newer than last_updated wins",
     with_dates("2026-09-02", "2026-09-15"), "2026-09-15"),
    ("last_updated newer than released wins",
     with_dates("2026-09-15", "2026-09-02"), "2026-09-15"),
    ("released alone is used", with_dates(None, "2026-09-15"), "2026-09-15"),
    ("last_updated alone is used", with_dates("2026-09-15", None), "2026-09-15"),
    ("a non-ISO last_updated is ignored when a release date exists",
     with_dates("Sept 20", "2026-09-15"), "2026-09-15"),
    ("a non-ISO last_updated alone is copied as before",
     with_dates("Sept 20", None), "Sept 20"),
    ("no date at all is no date", with_dates(), None),
]:
    got = reg.release_date(manifest)
    check(f"{label} ({got})", got == want)

case("--check fails on a registry date older than the newest release",
     [{**entry("a", "plugins/a"), "last_updated": "2026-09-02"}], ["a"], 1,
     "last_updated differs", manifests={"a": with_dates("2026-09-02", "2026-09-15")})
case("--check passes when the registry shows the release date",
     [{**entry("a", "plugins/a"), "last_updated": "2026-09-15"}], ["a"], 0,
     manifests={"a": with_dates("2026-09-02", "2026-09-15")})
root = make_tree([{**entry("a", "plugins/a"), "latest_version": "0.9.0"}], ["a"],
                 {"a": with_dates("2026-09-02", "2026-09-15")})
run_check(root)
written = json.loads((root / "plugins.json").read_text())["plugins"][0]
check("a version bump writes the release date, not the stale last_updated",
      written["last_updated"] == "2026-09-15" and written["latest_version"] == "1.0.0")
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
