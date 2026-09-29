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

Three fields let the core decide before it downloads anything. All are
additive: every core since 3.0.0 reads entries with dict.get and ignores keys
it does not know.

- `ledmatrix_min_version`: the floor the manifest declares, by the core's own
  precedence (see `declared_min_version`). A core older than that refuses the
  install before the download instead of after it. Absent when the manifest
  declares none. Synced and checked like the metadata fields above.
- `aliases`: other ids the plugin goes by -- for a monorepo entry, the
  manifest id when it differs from the registry id (weather, stocks, music and
  leaderboard install as `ledmatrix-<id>`). Absent when there are none.
  Synced and checked like the metadata fields above.
- `commit`: the monorepo commit that introduced the manifest's current
  `version` (see `CommitResolver`). Informational: nothing installs from it.
  Needs full git history, so a shallow clone or a directory outside git
  leaves the field as it was, and a run that raises `latest_version` without
  being able to name the new commit drops the old one rather than pair it
  with a version it never shipped. `--check` does not compare it: in a PR the
  commit that will introduce a bump does not exist yet (main squash-merges),
  so the Update Plugin Registry workflow fills it in after the merge.

Usage:
    python update_registry.py              # Update plugins.json (warns on the above)
    python update_registry.py --dry-run    # Show what would change
    python update_registry.py --check      # CI: dry run, exit 1 on the above
    python update_registry.py --external   # Also sync third-party versions from GitHub
"""

import json
import re
import subprocess  # nosec B404 - fixed git argv, no shell
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


def declared_min_version(manifest: dict) -> str | None:
    """The oldest core this manifest says it runs on, or None.

    The same precedence as the core's install gate
    (`compatibility.declared_min_version`) and scripts/check_min_core_version.py:
    top-level `min_ledmatrix_version`, then `requires.min_ledmatrix_version`,
    then `versions[0].ledmatrix_min_version` or its deprecated spelling
    `ledmatrix_min`. The registry must say what the gate will enforce after
    the download, or the early refusal and the late one disagree.

    `compatible_versions` is not folded in: the registry field is the declared
    floor, and a range (with its possible upper bound) is still checked by the
    core once the manifest is on disk.
    """
    declared = manifest.get("min_ledmatrix_version")
    if not declared:
        requires = manifest.get("requires")
        if isinstance(requires, dict):
            declared = requires.get("min_ledmatrix_version")
    if not declared:
        versions = manifest.get("versions")
        if isinstance(versions, list) and versions and isinstance(versions[0], dict):
            declared = (versions[0].get("ledmatrix_min_version")
                        or versions[0].get("ledmatrix_min"))
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    return None


def derived_fields(manifest: dict, registry_id: str) -> dict:
    """Registry fields computed from a monorepo manifest; None means "absent".

    Unlike `synced_metadata`, a field the manifest stops implying is removed,
    so a dropped floor or a manifest id brought back in line with the registry
    id does not leave a stale value behind.
    """
    manifest_id = manifest.get("id")
    aliases = ([manifest_id] if isinstance(manifest_id, str) and manifest_id
               and manifest_id != registry_id else None)
    return {
        "ledmatrix_min_version": declared_min_version(manifest),
        "aliases": aliases,
    }


def _apply_derived(plugin: dict, fields: dict, dry_run: bool) -> list[str]:
    """Write `derived_fields` onto an entry; returns the names that changed."""
    changed = []
    for field, value in fields.items():
        if value is None:
            if field in plugin:
                if not dry_run:
                    del plugin[field]
                changed.append(field)
        elif plugin.get(field) != value:
            if not dry_run:
                plugin[field] = value
            changed.append(field)
    return changed


class CommitResolver:
    """Finds the commit that introduced a manifest's current `version`.

    Walks the first-parent history of one manifest.json from HEAD, newest
    first, while the committed `version` still equals the one asked about;
    the last commit in that run is where the version appeared. First-parent,
    because main is squash-merged: the commit that matters is the one on
    main, not a branch commit inside a merge.

    Why this commit and not HEAD at generation time: every plugin change must
    bump the version (scripts/check_version_bump.py), so the plugin's tree at
    this commit is the release -- only test files can differ later. HEAD
    would change on every run for every entry, rewriting 40-odd lines of
    plugins.json each time main moves, and would name commits that have
    nothing to do with the plugin.

    `for_repo` returns None when it cannot answer honestly: git missing, the
    registry not at the top of a work tree, or a shallow clone, where the
    walk would stop at the graft and call the oldest visible commit the
    introducing one.
    """

    def __init__(self, root: Path):
        self.root = root
        # One `git cat-file --batch` for every manifest read: a process per
        # read made a full run take seconds, and the pre-commit hook runs it.
        self._batch: Optional[subprocess.Popen] = None

    @classmethod
    def for_repo(cls, root: Path) -> Optional["CommitResolver"]:
        resolver = cls(root)
        top = resolver._git("rev-parse", "--show-toplevel")
        if top is None:
            return None
        try:
            if Path(top.strip()).resolve() != root.resolve():
                return None
        except OSError:
            return None
        if (resolver._git("rev-parse", "--is-shallow-repository") or "").strip() != "false":
            return None
        return resolver

    def _git(self, *args: str) -> Optional[str]:
        try:
            result = subprocess.run(  # nosec B603 B607 - fixed git subcommands, paths only after "--", no shell  # nosemgrep
                ["git", *args], cwd=self.root, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=60,
                check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None

    def _blob(self, spec: str) -> Optional[bytes]:
        """Contents of `<sha>:<path>`, or None when it does not exist."""
        if self._batch is None:
            try:
                self._batch = subprocess.Popen(  # nosec B603 B607 - fixed git argv, specs go over stdin, no shell  # nosemgrep
                    ["git", "cat-file", "--batch"], cwd=self.root,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL)
            except OSError:
                return None
        proc = self._batch
        try:
            proc.stdin.write(spec.encode("utf-8") + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3:  # "<spec> missing" (or the process died)
                return None
            data = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)  # the newline after each object
            return data
        except (OSError, ValueError):
            return None

    def close(self) -> None:
        if self._batch is not None:
            try:
                self._batch.stdin.close()
                self._batch.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                self._batch.kill()
            self._batch = None

    def _version_at(self, sha: str, relpath: str) -> Optional[str]:
        data = self._blob(f"{sha}:{relpath}")
        if data is None:
            return None
        try:
            manifest = parse_json_with_trailing_commas(data.decode("utf-8-sig"))
        except ValueError:  # includes UnicodeDecodeError
            return None
        version = manifest.get("version") if isinstance(manifest, dict) else None
        return version.strip() if isinstance(version, str) else None

    def introducing_commit(self, relpath: str, version: str) -> Optional[str]:
        """The full SHA, or None when HEAD's manifest is not at `version`
        (an uncommitted bump) or the file has no history."""
        log = self._git("log", "--first-parent", "--format=%H", "HEAD", "--", relpath)
        if not log:
            return None
        found = None
        for sha in log.split():
            if self._version_at(sha, relpath) != version.strip():
                break
            found = sha
        return found


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

    Only the version, its date and its `ledmatrix_min_version` move. Name,
    description and the rest stay as they were when the entry was reviewed:
    the author's repo can publish a new release, but it cannot rewrite what
    the store says about it. The floor travels with the version because it
    describes that release, and it is compatibility information only -- the
    core uses it to refuse an install it would refuse after downloading
    anyway. It is also filled in for an entry already at the repo's version.
    A manifest whose id is not the entry's is ignored, so a repo cannot
    publish versions for some other entry.

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
    floor = {"ledmatrix_min_version": declared_min_version(manifest)}
    if not remote or parse_version(remote) < parse_version(current):
        print(f"  {plugin_id}: up to date ({current}, external)")
        return False
    if parse_version(remote) == parse_version(current):
        # Same release: only its floor can be missing or out of date.
        if _apply_derived(plugin, floor, dry_run):
            print(f"  {plugin_id}: up to date ({current}, external); "
                  f"ledmatrix_min_version -> {floor['ledmatrix_min_version']}")
            return True
        print(f"  {plugin_id}: up to date ({current}, external)")
        return False
    print(f"  {plugin_id}: {current} -> {remote} (external)")
    if not dry_run:
        plugin["latest_version"] = remote
        plugin["last_updated"] = release_date(manifest) or datetime.now().strftime("%Y-%m-%d")
    _apply_derived(plugin, floor, dry_run)
    return True


def update_registry(registry_path: str = "plugins.json", dry_run: bool = False,
                    external: bool = False,
                    fetch: Callable[[str], str] = fetch_url,
                    commits: bool = True) -> list[tuple[str, str]]:
    """
    Update plugins.json with version info from local plugin manifests, and
    with external=True from third-party repos' manifests too.

    Returns one ``(kind, message)`` per disagreement found between a monorepo
    entry and its manifest: kind ``"behind"`` or ``"ahead"`` for a version
    mismatch, ``"metadata"`` for a synced or derived field that differs.
    Empty means the registry already matches.
    A normal run writes every fix it can; a registry version *ahead* of its
    manifest is reported but never written, because that would be a downgrade.
    Third-party version raises (--external) are written but are not drift, and
    neither are `commit` changes (see the module docstring). ``commits=False``
    skips the git walk entirely (--check has no use for it).
    """
    registry_file = Path(registry_path)
    plugins_dir = registry_file.parent / "plugins"
    resolver = CommitResolver.for_repo(registry_file.parent) if commits else None
    if commits and resolver is None:
        print("Note: no full git history at the registry's root; "
              "entry commits are left as they are\n")

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

        padded = (isinstance(registry_version, str)
                  and registry_version != registry_version.strip())
        version_changed = False
        if parse_version(manifest_version) > parse_version(registry_version):
            version_changed = True
            print(f"  {plugin_id}: {registry_version} -> {manifest_version}")
            drift.append(("behind",
                f"{plugin_id}: plugins.json latest_version {registry_version!r} is "
                f"behind manifest version {manifest_version!r}, so the store "
                f"never offers the update. Run python update_registry.py and "
                f"commit plugins.json."))
        elif parse_version(manifest_version) < parse_version(registry_version):
            print(f"  {plugin_id}: manifest ({manifest_version}) < registry ({registry_version}), skipping")
            drift.append(("ahead",
                f"{plugin_id}: plugins.json latest_version {registry_version!r} is "
                f"ahead of manifest version {manifest_version!r}, so the store "
                f"offers a version that was never shipped. update_registry.py "
                f"never downgrades: bump the manifest past it, or correct the "
                f"registry entry."))
        elif padded:
            # "1.0.10\r" was published for ten plugins: it parses equal to its
            # manifest's "1.0.10", so nothing above ever rewrote it, and the
            # store showed the stray character. Same version, clean spelling.
            version_changed = True
            print(f"  {plugin_id}: {registry_version!r} -> {manifest_version!r}")
            drift.append(("metadata",
                f"{plugin_id}: plugins.json latest_version {registry_version!r} "
                f"has stray whitespace. Run python update_registry.py and "
                f"commit plugins.json."))
        else:
            print(f"  {plugin_id}: up to date ({registry_version})")

        if version_changed:
            if not dry_run:
                plugin["latest_version"] = manifest_version
                # Prefer the manifest's own release date (see release_date);
                # fall back to today.
                plugin["last_updated"] = release_date(manifest) or datetime.now().strftime("%Y-%m-%d")
            updates_made = True

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
        # And the fields the core reads before it downloads anything.
        derived = _apply_derived(plugin, derived_fields(manifest, plugin_id), dry_run)
        if derived:
            synced_fields += derived
            updates_made = True
        if synced_fields:
            print(f"    synced fields: {', '.join(synced_fields)}")
            drift.append(("metadata",
                f"{plugin_id}: plugins.json {', '.join(synced_fields)} "
                f"{'differs' if len(synced_fields) == 1 else 'differ'} from "
                f"the manifest. Run python update_registry.py and commit "
                f"plugins.json."))

        # The commit that introduced this version. Not drift: see the module
        # docstring. Unknown (no usable history, or a bump not committed
        # yet) keeps the old value -- unless the version just moved, when the
        # old value names a commit of the previous release.
        commit = None
        if resolver is not None:
            commit = resolver.introducing_commit(
                f"{_normalise_plugin_path(plugin_path)}/manifest.json", manifest_version)
        if commit is not None:
            if plugin.get("commit") != commit:
                print(f"    commit: {commit[:12]}")
                if not dry_run:
                    plugin["commit"] = commit
                updates_made = True
        elif version_changed and "commit" in plugin:
            print("    commit: dropped (the new version's commit is not known yet)")
            if not dry_run:
                del plugin["commit"]
            updates_made = True

    if resolver is not None:
        resolver.close()

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
        drift = update_registry(args.registry, args.dry_run or args.check, args.external,
                                commits=not args.check)
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
