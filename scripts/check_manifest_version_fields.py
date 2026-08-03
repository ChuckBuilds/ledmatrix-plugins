#!/usr/bin/env python3
"""Require the *newest* versions[] entry to use `ledmatrix_min_version`.

Run over changed plugins in CI, or over everything with `--all`:

    python scripts/check_manifest_version_fields.py baseball-scoreboard news
    python scripts/check_manifest_version_fields.py --all      # audit, non-gating

## Why only the newest entry

`PluginStoreManager` and `PluginLoader` resolve a plugin's floor through
`src/plugin_system/compatibility.py:declared_min_version`, which reads
`versions[0]` and accepts either spelling. So the deprecated `ledmatrix_min`
costs nothing functionally, and the store's own deprecation check is
warnings-only and reachable only from the sideload path.

Rewriting all 42 manifests to the new spelling would therefore change no
behaviour while forcing 42 version bumps — 42 store updates pushed to every
user for a field rename. Instead this gate asks each plugin to migrate the one
entry that is actually read, at a moment when it is already being bumped for
other reasons. The migration completes as plugins release, and cannot slide
backwards.

Historical entries are left alone: nothing reads them, and rewriting shipped
release records to satisfy a linter is worse than the inconsistency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = REPO_ROOT / "plugins"

NEW = "ledmatrix_min_version"
OLD = "ledmatrix_min"


def check_plugin(plugin_id: str) -> list[str]:
    """Problems with this plugin's newest version entry (empty when fine)."""
    path = PLUGINS / plugin_id / "manifest.json"
    if not path.exists():
        return []  # not a monorepo plugin; nothing to say

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"{plugin_id}: manifest.json could not be read ({e})"]

    versions = [v for v in (manifest.get("versions") or []) if isinstance(v, dict)]
    if not versions:
        return []

    head = versions[0]
    version_label = head.get("version", "?")
    problems: list[str] = []

    if OLD in head and NEW not in head:
        problems.append(
            f"{plugin_id}: versions[0] ({version_label}) uses the deprecated "
            f"'{OLD}'. Rename it to '{NEW}' — this is the entry the store and "
            f"loader actually read. Older entries can stay as they are."
        )

    # compatible_versions is required by the core's manifest schema and is the
    # only field that can express an upper bound; a missing one means the gate
    # has nothing authoritative to evaluate.
    compatible = manifest.get("compatible_versions")
    if not isinstance(compatible, list) or not compatible:
        problems.append(
            f"{plugin_id}: 'compatible_versions' is missing or empty. The core "
            f"manifest schema requires it, and it is the field the install "
            f"gate evaluates for upper bounds."
        )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_ids", nargs="*", help="Plugin ids to check")
    parser.add_argument("--all", action="store_true",
                        help="Audit every plugin; reports without failing")
    args = parser.parse_args()

    if args.all:
        ids = sorted(p.name for p in PLUGINS.iterdir()
                     if (p / "manifest.json").exists())
    else:
        ids = args.plugin_ids
        if not ids:
            print("No plugins to check.")
            return 0

    problems = [p for pid in ids for p in check_plugin(pid)]

    if not problems:
        print(f"OK: {len(ids)} plugin(s) checked, newest version entries are current.")
        return 0

    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)

    if args.all:
        print(f"\n{len(problems)} plugin(s) still to migrate — audit only, "
              f"not failing. They migrate at their next version bump.",
              file=sys.stderr)
        return 0

    print(f"\n{len(problems)} problem(s). These plugins are being changed "
          f"anyway, so the fix is a one-line rename in the entry you just "
          f"added.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
