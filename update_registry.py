#!/usr/bin/env python3
"""
Update plugins.json registry from local plugin manifests.

In the monorepo model, each plugin's manifest.json is the source of truth
for version information. This script reads each plugin's manifest and
updates the registry accordingly.

Usage:
    python update_registry.py              # Update plugins.json
    python update_registry.py --dry-run    # Show what would change
"""

import json
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path


def parse_version(version_str: str) -> tuple:
    """Parse a version string into a comparable tuple."""
    version_str = (version_str or "0.0.0").lstrip("v")
    try:
        return tuple(int(p) for p in version_str.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


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


def update_registry(registry_path: str = "plugins.json", dry_run: bool = False) -> bool:
    """
    Update plugins.json with version info from local plugin manifests.

    Returns True if updates were made.
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

    for plugin in registry["plugins"]:
        plugin_id = plugin["id"]
        plugin_path = plugin.get("plugin_path", "")

        # Only process monorepo plugins (those with plugin_path set)
        if not plugin_path:
            print(f"  {plugin_id}: skipped (external repo)")
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
            if not dry_run:
                plugin["latest_version"] = manifest_version
                # Prefer the manifest's last_updated if present (matches the
                # plugin's actual release date); fall back to today.
                plugin["last_updated"] = manifest.get("last_updated") or datetime.now().strftime("%Y-%m-%d")
            updates_made = True
        elif parse_version(manifest_version) < parse_version(registry_version):
            print(f"  {plugin_id}: manifest ({manifest_version}) < registry ({registry_version}), skipping")
        else:
            print(f"  {plugin_id}: up to date ({registry_version})")

        # Sync user-visible metadata fields from the manifest. The manifest
        # is the source of truth per the module docstring, so the registry
        # should never disagree with it on the fields the Plugin Store
        # actually renders to users.
        synced_fields = []
        for field in ("name", "description", "author", "category", "tags", "icon"):
            if field in manifest and plugin.get(field) != manifest[field]:
                if not dry_run:
                    plugin[field] = manifest[field]
                synced_fields.append(field)
                updates_made = True
        if synced_fields:
            print(f"    synced fields: {', '.join(synced_fields)}")

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

    return updates_made


def main():
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
    args = parser.parse_args()

    try:
        update_registry(args.registry, args.dry_run)
    except FileNotFoundError:
        print(f"Error: Could not find {args.registry}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: {args.registry} is not valid JSON")
        sys.exit(1)


if __name__ == "__main__":
    main()
