#!/usr/bin/env python3
"""Enforce CLAUDE.md non-negotiable #1 on changed plugins: a real version bump.

    python scripts/check_version_bump.py --base <sha> football-scoreboard news
    python scripts/check_version_bump.py --all     # repo-wide sync audit

For each plugin id given (CI passes the plugins whose shipped code changed),
compared against the manifest at ``--base``:

1. ``version`` must equal ``versions[0].version``. The store compares
   ``version`` with ``plugins.json``, but the store and loader read the core
   floor and release notes from ``versions[0]``. When the two disagree, users
   get the new code described by the previous release's entry and floor.
2. ``version`` must be strictly greater than the base version (semver
   compare). The old gate only asked for "different", so a downgrade passed,
   and ``update_registry.py`` then silently refuses to publish it.
3. ``versions[0]`` must be a new entry: its version must not already appear
   anywhere in the base ``versions[]``, and the base's top entry must still be
   in the list (a bump made by editing the old top entry in place rewrites the
   shipped release record instead of adding one).

A plugin with no manifest at base is new: only rule 1 applies. A plugin whose
manifest is gone at HEAD was deleted: nothing to check.

``--all`` checks rule 1 across every plugin, with no base. It exits 1 when any
plugin is out of sync. It is not wired into CI, because main had two such
plugins when this was written (ledmatrix-stocks 2.9.1 vs versions[0] 2.9.0,
stock-news 2.6.2 vs 2.6.1); run it by hand to audit.

Exit codes: 0 pass, 1 fail, 2 skipped (e.g. the base manifest could not be
read because git is unavailable).
"""

from __future__ import annotations

import argparse
import json
import re
# git show is invoked with a fixed argv built from validated plugin ids.
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = REPO_ROOT / "plugins"

VALID_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SEMVER = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")

# A repo-wide run that sees fewer manifests than this is not looking at the
# plugin tree it thinks it is (wrong cwd, moved directory, broken glob).
MIN_PLAUSIBLE_PLUGINS = 20


class BadVersion(ValueError):
    pass


def parse_semver(text) -> tuple:
    """Comparable key for a semver string. Raises BadVersion when unparseable.

    Pre-releases sort before their release (1.2.0-beta < 1.2.0), numeric
    identifiers numerically, per semver 2.0.0 section 11.
    """
    if not isinstance(text, str):
        raise BadVersion(f"{text!r} is not a string")
    m = SEMVER.match(text.strip())
    if not m:
        raise BadVersion(f"{text!r} is not MAJOR.MINOR.PATCH")
    core = tuple(int(g) for g in m.group(1, 2, 3))
    pre = m.group(4)
    if pre is None:
        return core + ((1,),)
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p)
                for p in pre.split("."))
    return core + ((0,) + ids,)


def _versions(manifest: dict) -> list:
    return [v for v in (manifest.get("versions") or []) if isinstance(v, dict)]


def check_sync(pid: str, manifest: dict) -> list[str]:
    """Rule 1: version == versions[0].version."""
    version = manifest.get("version")
    versions = _versions(manifest)
    if not versions:
        return [f"{pid}: manifest has no versions[] entries; add one at the "
                f"top for {version!r}"]
    top = versions[0].get("version")
    if top != version:
        return [f"{pid}: version is {version!r} but versions[0].version is "
                f"{top!r}. Add a versions[] entry for {version!r} at the top "
                f"(the store and loader read the floor and notes from it)"]
    return []


def check_bump(pid: str, current: dict | None, base: dict | None) -> list[str]:
    """All problems for one changed plugin. Empty list means it passes."""
    if current is None:
        return []  # deleted in this change
    problems = check_sync(pid, current)

    cur = current.get("version")
    try:
        cur_key = parse_semver(cur)
    except BadVersion as e:
        return problems + [f"{pid}: version {e}"]

    if base is None:
        return problems  # new plugin; nothing to compare against

    old = base.get("version")
    try:
        old_key = parse_semver(old)
    except BadVersion:
        old_key = None  # a broken base can't be compared; don't block the fix

    if cur == old:
        problems.append(f"{pid}: code changed but version not bumped (still "
                        f"{cur}). Users won't get the update.")
    elif old_key is not None and cur_key < old_key:
        problems.append(f"{pid}: version went backwards ({old} -> {cur}). "
                        f"The registry never publishes a downgrade.")

    base_versions = [v.get("version") for v in _versions(base)]
    cur_versions = [v.get("version") for v in _versions(current)]
    if cur_versions and cur != old:
        if cur_versions[0] in base_versions:
            problems.append(
                f"{pid}: versions[0] ({cur_versions[0]}) is not a new entry; "
                f"it already existed at base. Add a new entry at the top.")
        elif base_versions and base_versions[0] not in cur_versions:
            problems.append(
                f"{pid}: the base's top versions[] entry ({base_versions[0]}) "
                f"is gone. Add the new release above it instead of editing "
                f"it in place.")
    return problems


def load_current(pid: str) -> dict | None:
    path = PLUGINS / pid / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_base(pid: str, base: str) -> dict | None:
    """Manifest at git rev `base`, or None if it didn't exist there."""
    proc = subprocess.run(  # nosec B603 B607
        ["git", "show", f"{base}:plugins/{pid}/manifest.json"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        err = proc.stderr.lower()
        if "does not exist" in err or "exists on disk, but not in" in err:
            return None
        raise RuntimeError(proc.stderr.strip() or f"git show failed for {pid}")
    return json.loads(proc.stdout)


def run_all() -> int:
    ids = sorted(p.name for p in PLUGINS.iterdir()
                 if (p / "manifest.json").is_file())
    if len(ids) < MIN_PLAUSIBLE_PLUGINS:
        print(f"FAIL only {len(ids)} manifests under {PLUGINS}; the audit is "
              f"not looking at the plugin tree")
        return 1
    problems = []
    for pid in ids:
        problems += check_sync(pid, load_current(pid))
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        print(f"\n{len(problems)} of {len(ids)} plugin(s) out of sync.")
        return 1
    print(f"PASS all {len(ids)} plugins have version == versions[0].version")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plugin_ids", nargs="*")
    parser.add_argument("--base", help="git rev to compare against (PR base)")
    parser.add_argument("--all", action="store_true",
                        help="audit version/versions[0] sync repo-wide")
    args = parser.parse_args(argv)

    if args.all:
        return run_all()
    if not args.base:
        parser.error("--base is required unless --all is given")
    if not args.plugin_ids:
        print("PASS no changed plugins to check")
        return 0

    failed = False
    for pid in args.plugin_ids:
        if not VALID_ID.match(pid):
            print(f"FAIL invalid plugin id {pid!r}")
            failed = True
            continue
        try:
            current = load_current(pid)
            base = load_base(pid, args.base)
        except (OSError, RuntimeError) as e:
            print(f"SKIP {pid}: could not read the base manifest ({e})")
            return 2
        except ValueError as e:
            print(f"FAIL {pid}: manifest is not valid JSON ({e})")
            failed = True
            continue
        problems = check_bump(pid, current, base)
        if current is None:
            print(f"PASS {pid}: removed, nothing to check")
        elif problems:
            failed = True
            for p in problems:
                print(f"FAIL {p}")
        else:
            old = base.get("version") if base else "(new)"
            print(f"PASS {pid}: {old} -> {current.get('version')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
