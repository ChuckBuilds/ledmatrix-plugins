#!/usr/bin/env python3
"""Regression tests for the version-bump gate (scripts/check_version_bump.py).

The gate this replaced compared only ``version`` with the base and counted any
difference as a bump. That passed a downgrade, and it passed a release whose
``versions[0]`` still described the previous one -- ledmatrix-stocks 2.9.1 and
stock-news 2.6.2 shipped that way (#462), so the store read the old floor.

Pure-function cases pin each rule; one end-to-end case drives the CLI against a
throwaway git repo so ``git show <base>:...`` is exercised too (skipped, not
failed, when git is unavailable).

Exit codes: 0 pass, 1 fail.
"""

import json
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_version_bump as gate  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def m(version, *history):
    """Manifest with `version` and versions[] tops listed newest first."""
    return {"version": version,
            "versions": [{"version": v} for v in history]}


def bump_fails(cur, base, needle):
    problems = gate.check_bump("p", cur, base)
    return any(needle in p for p in problems), problems


print("semver ordering")
check("1.10.0 > 1.9.9", gate.parse_semver("1.10.0") > gate.parse_semver("1.9.9"))
check("2.0.0 > 1.99.99", gate.parse_semver("2.0.0") > gate.parse_semver("1.99.99"))
check("1.2.0-beta < 1.2.0", gate.parse_semver("1.2.0-beta") < gate.parse_semver("1.2.0"))
check("1.2.0-beta.2 < 1.2.0-beta.10",
      gate.parse_semver("1.2.0-beta.2") < gate.parse_semver("1.2.0-beta.10"))
for bad in ("1.2", "abc", None, "1.2.3.4"):
    try:
        gate.parse_semver(bad)
        check(f"{bad!r} rejected", False)
    except gate.BadVersion:
        check(f"{bad!r} rejected", True)

print("\nchanged plugin rules")
ok = gate.check_bump("p", m("1.1.0", "1.1.0", "1.0.0"), m("1.0.0", "1.0.0"))
check(f"a proper bump passes ({ok})", ok == [])

hit, probs = bump_fails(m("1.0.0", "1.0.0"), m("1.0.0", "1.0.0"), "not bumped")
check("unchanged version fails", hit)

hit, probs = bump_fails(m("0.9.0", "0.9.0", "1.0.0"), m("1.0.0", "1.0.0"), "backwards")
check("a downgrade fails", hit)

hit, probs = bump_fails(m("1.0.10", "1.0.10", "1.0.9"), m("1.0.9", "1.0.9"), "backwards")
check("1.0.9 -> 1.0.10 is not mistaken for a downgrade", not hit and probs == [])

hit, probs = bump_fails(m("1.1.0", "1.0.0"), m("1.0.0", "1.0.0"), "versions[0].version")
check("version bumped without a versions[] entry fails (the stocks case)", hit)

hit, probs = bump_fails(m("1.1.0", "1.1.0"), m("1.0.0", "1.0.0"), "is gone")
check("editing the old top entry in place fails", hit)

hit, probs = bump_fails({"version": "1.1.0"}, m("1.0.0", "1.0.0"), "no versions[]")
check("a manifest with no versions[] fails", hit)

hit, probs = bump_fails(m("1.1", "1.1"), m("1.0.0", "1.0.0"), "MAJOR.MINOR.PATCH")
check("an unparseable version fails", hit)

check("a new plugin in sync passes",
      gate.check_bump("p", m("1.0.0", "1.0.0"), None) == [])
hit, probs = bump_fails(m("1.0.0", "0.9.0"), None, "versions[0].version")
check("a new plugin out of sync fails", hit)
check("a deleted plugin passes", gate.check_bump("p", None, m("1.0.0", "1.0.0")) == [])

# Base itself out of sync (main today for stocks/stock-news): a correct next
# release must still pass, so the gate doesn't punish the fix.
ok = gate.check_bump("p", m("2.9.2", "2.9.2", "2.9.0"), m("2.9.1", "2.9.0"))
check(f"a correct bump from an out-of-sync base passes ({ok})", ok == [])

print("\nrepo-wide audit is actually looking")
ids = [p for p in gate.PLUGINS.iterdir() if (p / "manifest.json").is_file()]
check(f"{len(ids)} manifests found (>= {gate.MIN_PLAUSIBLE_PLUGINS})",
      len(ids) >= gate.MIN_PLAUSIBLE_PLUGINS)


def git(repo, *args):
    return subprocess.run(  # nosec B603 B607
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


print("\nend to end through git show")
if shutil.which("git") is None:
    print("  SKIP  git not available")
else:
    root = Path(tempfile.mkdtemp())
    original = (gate.REPO_ROOT, gate.PLUGINS)
    try:
        (root / "plugins" / "p").mkdir(parents=True)
        mf = root / "plugins" / "p" / "manifest.json"
        git(root, "init", "-q")
        mf.write_text(json.dumps(m("1.0.0", "1.0.0")))
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        base = git(root, "rev-parse", "HEAD")
        gate.REPO_ROOT, gate.PLUGINS = root, root / "plugins"

        mf.write_text(json.dumps(m("1.0.1", "1.0.0")))
        check("CLI fails a bump missing its versions[] entry",
              gate.main(["--base", base, "p"]) == 1)
        mf.write_text(json.dumps(m("0.9.0", "0.9.0", "1.0.0")))
        check("CLI fails a downgrade", gate.main(["--base", base, "p"]) == 1)
        mf.write_text(json.dumps(m("1.0.1", "1.0.1", "1.0.0")))
        check("CLI passes a proper bump", gate.main(["--base", base, "p"]) == 0)
        (root / "plugins" / "q").mkdir()
        (root / "plugins" / "q" / "manifest.json").write_text(
            json.dumps(m("0.1.0", "0.1.0")))
        check("CLI passes a plugin that is new since base",
              gate.main(["--base", base, "q"]) == 0)
        check("CLI rejects an injected id",
              gate.main(["--base", base, "p;rm -rf"]) == 1)
    finally:
        gate.REPO_ROOT, gate.PLUGINS = original
        shutil.rmtree(root, ignore_errors=True)

print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
sys.exit(1 if failures else 0)
