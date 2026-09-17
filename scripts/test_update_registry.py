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
import urllib.error
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

print("\nthird-party versions (--external, fetch faked)")
EXT_REPO = "https://github.com/someone/ledmatrix-ext"
EXT_URL = "https://raw.githubusercontent.com/someone/ledmatrix-ext/main/manifest.json"


def ext_entry(**over):
    e = {"id": "ext", "plugin_path": "", "repo": EXT_REPO, "branch": "main",
         "latest_version": "1.0.0", "last_updated": "2026-01-01",
         "description": "as reviewed"}
    e.update(over)
    return e


def run_external(entries, manifest=None, error=None, dry_run=False, external=True):
    """Run update_registry on a registry of `entries`; returns (entries after, fetched urls)."""
    root = make_tree(entries, [])
    urls = []

    def fetch(url):
        urls.append(url)
        if error:
            raise error
        return manifest if isinstance(manifest, str) else json.dumps(manifest)

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            reg.update_registry(str(root / "plugins.json"), dry_run, external, fetch)
        return json.loads((root / "plugins.json").read_text())["plugins"], urls
    finally:
        shutil.rmtree(root, ignore_errors=True)


newer = {"id": "ext", "version": "1.2.0", "description": "rewritten by the repo",
         "versions": [{"version": "1.2.0", "released": "2026-09-01"},
                      {"version": "1.0.0", "released": "2026-01-01"}]}
after, urls = run_external([ext_entry()], newer)
check("fetches the repo root manifest on the entry's branch", urls == [EXT_URL])
check("a newer manifest raises latest_version", after[0]["latest_version"] == "1.2.0")
check("last_updated is the release date of that version", after[0]["last_updated"] == "2026-09-01")
check("the reviewed description is not overwritten", after[0]["description"] == "as reviewed")

after, _ = run_external([ext_entry()], "{\"id\": \"ext\", \"version\": \"1.1.0\", \"last_updated\": \"2026-08-01\",}")
check("trailing commas parse; last_updated falls back to the manifest's",
      (after[0]["latest_version"], after[0]["last_updated"]) == ("1.1.0", "2026-08-01"))

after, _ = run_external([ext_entry(latest_version="2.0.0")], newer)
check("an older manifest never downgrades", after[0]["latest_version"] == "2.0.0")

after, _ = run_external([ext_entry()], dict(newer, id="someone-else"))
check("a manifest with another id is ignored", after[0]["latest_version"] == "1.0.0")

after, _ = run_external([ext_entry()], error=urllib.error.URLError("404"))
check("an unreadable repo is skipped, not fatal", after[0]["latest_version"] == "1.0.0")

after, _ = run_external([ext_entry()], "<html>not json</html>")
check("a manifest that is not JSON is skipped", after[0]["latest_version"] == "1.0.0")

after, urls = run_external([ext_entry(repo="https://gitlab.com/someone/ext")], newer)
check("a non-GitHub repo is not fetched", urls == [] and after[0]["latest_version"] == "1.0.0")

after, urls = run_external([ext_entry()], newer, external=False)
check("without --external nothing is fetched", urls == [] and after[0]["latest_version"] == "1.0.0")

after, _ = run_external([ext_entry()], newer, dry_run=True)
check("--dry-run fetches but does not write", after[0]["latest_version"] == "1.0.0")

check("repo URLs with .git and a trailing slash resolve",
      reg.raw_manifest_url(EXT_REPO + ".git/", "dev")
      == "https://raw.githubusercontent.com/someone/ledmatrix-ext/dev/manifest.json")
check("a repo subpath does not resolve",
      reg.raw_manifest_url(EXT_REPO + "/tree/main/x", "main") is None)

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
