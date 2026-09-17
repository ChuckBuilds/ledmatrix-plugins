#!/usr/bin/env python3
"""
Update plugins.json registry from local plugin manifests.

In the monorepo model, each plugin's manifest.json is the source of truth
for version information. This script reads each plugin's manifest and
updates the registry accordingly.

Third-party entries (empty plugin_path) live in their authors' repos, so a
local run cannot see their manifests. With --external it fetches each one's
manifest.json from GitHub and raises latest_version to match. Without that,
the store's update badge compares an installed plugin against whatever
version the entry was reviewed at, and a third-party release never reaches
anyone who already has the plugin. The update-registry workflow runs it
daily; local runs and the pre-commit hook stay offline.

`--check` fails on every way the registry and plugins/ can disagree:

- a monorepo entry whose `latest_version` differs from its manifest's
  `version`, in either direction. Behind: the store never offers the update.
  Ahead: the store offers a version that was never shipped, and a normal run
  will not fix it (it never downgrades).
- a monorepo entry whose store-visible metadata (name, description, author,
  category, tags, icon, last_updated) differs from what a normal run would
  write. The pre-commit hook folds that into the commit; a PR without it
  would publish stale metadata until the post-merge sync.
- a plugins/<dir> with a manifest but no registry entry whose plugin_path
  points at it. The plugin is never published to the store, and nothing
  else notices. (Adding a monorepo plugin still means adding its entry by
  hand; this makes forgetting it loud.)
- a registry plugin_path that has no plugins/<dir>/manifest.json. The store
  would offer a plugin that cannot be installed.

Usage:
    python update_registry.py              # Update plugins.json (warns on the above)
    python update_registry.py --dry-run    # Show what would change
    python update_registry.py --check      # CI: dry run, exit 1 on the above
    python update_registry.py --external   # Also sync third-party versions from GitHub
"""

import json
import re
import sys
import argparse
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

#: Manifest fields copied verbatim into the registry entry. The Plugin Store
#: renders these, so the registry must never disagree with the manifest.
#: `last_updated` is synced too, but derived -- see `release_date`.
SYNCED_FIELDS = ("name", "description", "author", "category", "tags", "icon")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def release_date(manifest: dict) -> str | None:
    """The date the registry should show as the plugin's `last_updated`.

    The newer of the manifest's top-level `last_updated` and the release date
    of its current version (the `versions[]` entry whose `version` matches,
    else `versions[0]`). Release PRs add a `versions[0]` entry with today's
    date and routinely forget the top-level field, so copying `last_updated`
    alone published a date older than the release itself. Only `YYYY-MM-DD`
    values are compared; if neither is one, the top-level value is used as it
    stands (None when absent). Used for monorepo manifests and for the
    third-party manifests --external fetches.
    """
    candidates = [manifest.get("last_updated")]
    versions = [v for v in (manifest.get("versions") or []) if isinstance(v, dict)]
    current = next((v for v in versions if v.get("version") == manifest.get("version")),
                   versions[0] if versions else None)
    if current is not None:
        candidates.append(current.get("released"))
    dates = [c for c in candidates if isinstance(c, str) and _ISO_DATE.match(c)]
    return max(dates) if dates else manifest.get("last_updated")


def synced_metadata(manifest: dict) -> dict:
    """Registry fields a normal run writes from this manifest, and their values."""
    fields = {f: manifest[f] for f in SYNCED_FIELDS if f in manifest}
    date = release_date(manifest)
    if date:
        fields["last_updated"] = date
    return fields


def parse_version(version_str: str) -> tuple:
    """Parse a version string into a comparable tuple.

    Padded to three parts, so "1.2" and "1.2.0" compare equal -- the store's
    own comparator treats them as the same version.
    """
    version_str = (version_str or "0.0.0").lstrip("v")
    try:
        parts = tuple(int(p) for p in version_str.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)
    return parts + (0,) * (3 - len(parts))


def parse_json_with_trailing_commas(text: str) -> dict:
    """Parse JSON that may have trailing commas."""
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return json.loads(text)


def read_manifest(plugin_dir: Path) -> dict | None:
    """Read a plugin's manifest.json, handling trailing commas."""
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return parse_json_with_trailing_commas(f.read())


def _normalise_plugin_path(plugin_path: str) -> str:
    return plugin_path.replace("\\", "/").strip().strip("/")


def find_consistency_problems(registry: dict, plugins_dir: Path) -> list[str]:
    """Registry/plugins-tree disagreements that update_registry cannot fix.

    Matching is by plugin_path, not id: registry ids and manifest ids already
    differ for weather, stocks, music and leaderboard, and the core's store
    resolves those through plugin_path.
    """
    problems: list[str] = []
    registered: dict[str, str] = {}
    for plugin in registry.get("plugins", []):
        path = _normalise_plugin_path(plugin.get("plugin_path") or "")
        if not path:
            continue  # third-party entry
        if path in registered:
            problems.append(
                f"registry entries '{registered[path]}' and '{plugin.get('id')}' "
                f"both claim plugin_path '{path}'")
        registered[path] = plugin.get("id", "?")
        target = plugins_dir.parent / path
        if not (target / "manifest.json").is_file():
            problems.append(
                f"registry entry '{plugin.get('id')}' has plugin_path '{path}', "
                f"but there is no {path}/manifest.json")

    for d in sorted(plugins_dir.iterdir()):
        if not d.is_dir() or not (d / "manifest.json").is_file():
            continue
        path = f"{plugins_dir.name}/{d.name}"
        if path not in registered:
            problems.append(
                f"{path} has a manifest but no plugins.json entry with "
                f"plugin_path '{path}', so the store never publishes it. Add an "
                f"entry (see docs/plugin-development/07-testing-ci-and-registry.md)")
    return problems


def raw_manifest_url(repo: str, branch: str) -> str | None:
    """raw.githubusercontent.com URL of a GitHub repo's root manifest.json."""
    parsed = urlparse((repo or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        return None
    owner, name = parts[0], parts[1].removesuffix(".git")
    return f"https://raw.githubusercontent.com/{owner}/{name}/{branch or 'main'}/manifest.json"


def fetch_url(url: str, timeout: float = 15) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ledmatrix-plugins-registry"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - only https raw.githubusercontent.com URLs from raw_manifest_url
        return response.read().decode("utf-8-sig")


def sync_external_entry(plugin: dict, dry_run: bool,
                        fetch: Callable[[str], str] = fetch_url) -> Optional[bool]:
    """Raise a third-party entry's latest_version from its repo's manifest.

    Only the version and its date move. Name, description and the rest stay
    as they were when the entry was reviewed: the author's repo can publish a
    new release, but it cannot rewrite what the store says about it. A
    manifest whose id is not the entry's is ignored, so a repo cannot publish
    versions for some other entry.

    Returns True if the entry changed, False if it is current, None if the
    manifest could not be read (a dead or private repo must not fail the run).
    """
    plugin_id = plugin.get("id", "?")
    url = raw_manifest_url(plugin.get("repo", ""), plugin.get("branch", ""))
    if not url:
        print(f"  {plugin_id}: skipped (external repo is not a github.com repo root)")
        return None
    try:
        manifest = parse_json_with_trailing_commas(fetch(url))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"  {plugin_id}: WARNING - could not read {url}: {e}")
        return None
    if not isinstance(manifest, dict) or manifest.get("id") != plugin.get("id"):
        found = manifest.get("id") if isinstance(manifest, dict) else None
        print(f"  {plugin_id}: WARNING - {url} has id {found!r}, not {plugin_id!r}; skipped")
        return None

    remote = str(manifest.get("version") or "")
    current = plugin.get("latest_version", "")
    if not remote or parse_version(remote) <= parse_version(current):
        print(f"  {plugin_id}: up to date ({current}, external)")
        return False
    print(f"  {plugin_id}: {current} -> {remote} (external)")
    if not dry_run:
        plugin["latest_version"] = remote
        plugin["last_updated"] = release_date(manifest) or datetime.now().strftime("%Y-%m-%d")
    return True


def update_registry(registry_path: str = "plugins.json", dry_run: bool = False,
                    external: bool = False,
                    fetch: Callable[[str], str] = fetch_url) -> list[tuple[str, str]]:
    """
    Update plugins.json with version info from local plugin manifests, and
    with external=True from third-party repos' manifests too.

    Returns one ``(kind, message)`` per disagreement found between a monorepo
    entry and its manifest: kind ``"behind"`` or ``"ahead"`` for a version
    mismatch, ``"metadata"`` for a synced field that differs. Empty means the
    registry already matches.
    A normal run writes every fix it can; a registry version *ahead* of its
    manifest is reported but never written, because that would be a downgrade.
    Third-party version raises (--external) are written but are not drift.
    """
    registry_file = Path(registry_path)
    plugins_dir = registry_file.parent / "plugins"

    with open(registry_file, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # Build map: directory name -> manifest data
    local_manifests = {}
    for d in sorted(plugins_dir.iterdir()):
        if d.is_dir():
            manifest = read_manifest(d)
            if manifest and manifest.get("id"):
                local_manifests[d.name] = manifest

    print(f"Found {len(local_manifests)} plugins in plugins/ directory")
    print(f"Registry has {len(registry.get('plugins', []))} entries\n")

    updates_made = False
    drift: list[tuple[str, str]] = []

    for plugin in registry["plugins"]:
        plugin_id = plugin["id"]
        plugin_path = plugin.get("plugin_path", "")

        # Third-party plugins (no plugin_path) have no local manifest
        if not plugin_path:
            if not external:
                print(f"  {plugin_id}: skipped (external repo; --external syncs it)")
            elif sync_external_entry(plugin, dry_run, fetch):
                updates_made = True
            continue

        # Extract directory name from plugin_path (e.g., "plugins/football-scoreboard" -> "football-scoreboard")
        dir_name = Path(plugin_path).name

        if dir_name not in local_manifests:
            print(f"  {plugin_id}: WARNING - no local directory '{dir_name}' found")
            continue

        manifest = local_manifests[dir_name]
        manifest_version = manifest.get("version", "")
        registry_version = plugin.get("latest_version", "")

        if not manifest_version:
            print(f"  {plugin_id}: no version in manifest")
            continue

        if parse_version(manifest_version) > parse_version(registry_version):
            print(f"  {plugin_id}: {registry_version} -> {manifest_version}")
            drift.append(("behind",
                f"{plugin_id}: plugins.json latest_version {registry_version!r} is "
                f"behind manifest version {manifest_version!r}, so the store "
                f"never offers the update. Run python update_registry.py and "
                f"commit plugins.json."))
            if not dry_run:
                plugin["latest_version"] = manifest_version
                # Prefer the manifest's own release date (see release_date);
                # fall back to today.
                plugin["last_updated"] = release_date(manifest) or datetime.now().strftime("%Y-%m-%d")
            updates_made = True
        elif parse_version(manifest_version) < parse_version(registry_version):
            print(f"  {plugin_id}: manifest ({manifest_version}) < registry ({registry_version}), skipping")
            drift.append(("ahead",
                f"{plugin_id}: plugins.json latest_version {registry_version!r} is "
                f"ahead of manifest version {manifest_version!r}, so the store "
                f"offers a version that was never shipped. update_registry.py "
                f"never downgrades: bump the manifest past it, or correct the "
                f"registry entry."))
        else:
            print(f"  {plugin_id}: up to date ({registry_version})")

        # Sync user-visible metadata fields from the manifest. The manifest
        # is the source of truth per the module docstring, so the registry
        # should never disagree with it on the fields the Plugin Store
        # actually renders to users.
        synced_fields = []
        for field, value in synced_metadata(manifest).items():
            if plugin.get(field) != value:
                if not dry_run:
                    plugin[field] = value
                synced_fields.append(field)
                updates_made = True
        if synced_fields:
            print(f"    synced fields: {', '.join(synced_fields)}")
            drift.append(("metadata",
                f"{plugin_id}: plugins.json {', '.join(synced_fields)} "
                f"{'differs' if len(synced_fields) == 1 else 'differ'} from "
                f"the manifest. Run python update_registry.py and commit "
                f"plugins.json."))

    if updates_made and not dry_run:
        registry["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        with open(registry_file, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"\nUpdated {registry_path}")
    elif dry_run and updates_made:
        print("\nDry run complete. Run without --dry-run to apply changes.")
    else:
        print("\nAll plugins are up to date.")

    return drift


def check_consistency(registry_path: str = "plugins.json") -> list[str]:
    """Load the registry and report registry/plugins-tree disagreements."""
    registry_file = Path(registry_path)
    with open(registry_file, "r", encoding="utf-8") as f:
        registry = json.load(f)
    return find_consistency_problems(registry, registry_file.parent / "plugins")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Update plugins.json from local plugin manifests"
    )
    parser.add_argument(
        "--registry",
        help="Path to plugins.json file",
        default="plugins.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run that exits 1 when plugins.json disagrees with the "
             "manifests (a version in either direction, or synced metadata), a "
             "plugin directory has no registry entry, or a registry "
             "plugin_path has no plugin (for CI)",
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help="Also raise third-party entries' latest_version from the "
             "manifest.json in their GitHub repos (needs network)",
    )
    args = parser.parse_args(argv)

    try:
        drift = update_registry(args.registry, args.dry_run or args.check, args.external)
        problems = check_consistency(args.registry)
    except FileNotFoundError:
        print(f"Error: Could not find {args.registry}")
        return 1
    except json.JSONDecodeError:
        print(f"Error: {args.registry} is not valid JSON")
        return 1

    # A normal run has just written every drift fix except "registry ahead",
    # which would be a downgrade. --check is about the file as committed, so
    # it reports all of it.
    problems = [message for kind, message in drift
                if args.check or kind == "ahead"] + problems

    if not problems:
        if args.check:
            print("\nPASS plugins.json matches every manifest (versions and "
                  "synced metadata), every plugins/ directory has a registry "
                  "entry, and every registry plugin_path exists")
        else:
            print("\nPASS every plugins/ directory has a registry entry, and "
                  "every registry plugin_path exists")
        return 0
    label = "FAIL" if args.check else "WARNING"
    print()
    for problem in problems:
        print(f"{label} {problem}")
    # The post-merge sync still writes the version updates above; only the PR
    # check fails, so one bad entry can't hold every other plugin's release.
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
