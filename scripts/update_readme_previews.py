#!/usr/bin/env python3
"""Keep the Preview column of the root README's plugin tables in sync.

The "Available Plugins" tables in ``README.md`` carry a thumbnail of each
plugin's hero screenshot. This script rewrites that column from what is
actually on disk: a plugin gets a thumbnail once
``docs/assets/<plugin-id>/hero.png`` (or ``plugins/<plugin-id>/assets/hero.png``,
for plugins that ship their own renderer) exists, and an empty cell until then.

Run it after adding a plugin's README screenshots::

    python scripts/update_readme_previews.py
    python scripts/update_readme_previews.py --check   # CI / pre-commit

Doing this by hand across forty-odd rows drifts: a row gets a thumbnail whose
image was never committed, or an image lands and the table is never updated.
The tables are keyed off the ``./plugins/<id>/`` link already in each row, so
there is no second list to keep in step.

The same run also checks the *catalogue* itself, because the Preview column was
never the only thing that drifted. Three faults have all happened and none was
caught by anything:

* a plugin shipped with a manifest, a hero image and a store listing, and no row
  in the table a visitor actually browses -- so the only way to find it was the
  store;
* one category rendered as two tables, from two ``### Productivity (1)``
  headings with one row each;
* a heading's count disagreeing with the rows beneath it.

All three are invisible to someone reading the page and obvious to a script, so
``--check`` fails on them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
ASSETS_ROOT = REPO_ROOT / "docs" / "assets"
REGISTRY = REPO_ROOT / "plugins.json"

HEADER_RE = re.compile(r"^\|\s*Plugin\s*\|\s*Description\s*\|(\s*Preview\s*\|)?\s*$")
SEPARATOR_RE = re.compile(r"^\|[\s:-]+\|[\s:-]+\|([\s:-]+\|)?\s*$")
PLUGIN_LINK_RE = re.compile(r"\]\(\./plugins/([^/)]+)/?\)")

# Wide enough to read a 128-pixel panel at a glance, narrow enough that the
# Description column still has room on a laptop-width screen.
THUMB_WIDTH = 240

HEADER = "| Plugin | Description | Preview |"
SEPARATOR = "|--------|-------------|---------|"


def hero_path(plugin_id: str) -> str | None:
    """Where this plugin's hero image lives, as a repo-relative URL.

    Most plugins render theirs into ``docs/assets/<id>/``. A few carry their own
    renderer and keep the image beside the plugin, so look there too rather than
    leaving those rows blank.
    """
    shared = ASSETS_ROOT / plugin_id / "hero.png"
    if shared.is_file():
        return f"./docs/assets/{plugin_id}/hero.png"
    local = REPO_ROOT / "plugins" / plugin_id / "assets" / "hero.png"
    if local.is_file():
        return f"./plugins/{plugin_id}/assets/hero.png"
    return None


def preview_cell(plugin_id: str) -> str:
    """The Preview cell for one plugin: a thumbnail, or empty if none yet."""
    hero = hero_path(plugin_id)
    if hero is None:
        return " "
    return (
        f' <a href="./plugins/{plugin_id}/">'
        f'<img src="{hero}" width="{THUMB_WIDTH}"'
        f' alt="{plugin_id} on an LED panel"></a> '
    )


def split_row(line: str) -> list[str]:
    """Split a markdown table row into its cells, dropping the outer pipes."""
    return line.strip().strip("|").split("|")


def rewrite(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not HEADER_RE.match(line) or index + 1 >= len(lines) or not SEPARATOR_RE.match(lines[index + 1]):
            out.append(line)
            index += 1
            continue

        out.append(HEADER)
        out.append(SEPARATOR)
        index += 2

        while index < len(lines) and lines[index].startswith("|"):
            cells = split_row(lines[index])
            match = PLUGIN_LINK_RE.search(cells[0] if cells else "")
            if match:
                plugin, description = cells[0], cells[1] if len(cells) > 1 else " "
                out.append(f"|{plugin}|{description}|{preview_cell(match.group(1))}|")
            else:
                out.append(lines[index])
            index += 1

    return "\n".join(out)


CATEGORY_RE = re.compile(r"^### ([A-Za-z0-9 &/+-]+) \((\d+)\)\s*$")


def catalogue_faults(text: str) -> list[str]:
    """Everything wrong with the catalogue that reading it would not reveal.

    Deliberately not checked: the Description column. Those are short blurbs
    written for the table and the manifest carries store-length copy, so all
    forty-four differ on purpose -- asserting they match would be asserting a
    fact that was never true.
    """
    faults: list[str] = []

    on_disk = {path.parent.name for path in REPO_ROOT.glob("plugins/*/manifest.json")}

    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registry = {"plugins": []}
    external = [entry for entry in registry.get("plugins", [])
                if not entry.get("plugin_path")]
    external_repos = {(entry.get("repo") or "").rstrip("/") for entry in external} - {""}
    # A third-party plugin can also sit in its category's table (F1 Live is
    # under Sports). It has no plugins/ directory, so it counts toward the
    # heading but not toward the directory checks below.
    external_rows: dict[int, int] = {}

    # Rows grouped under the heading they sit beneath, so a heading's count can
    # be checked against what it actually contains.
    sections: list[tuple[str, int, list[str]]] = []
    current: tuple[str, int, list[str]] | None = None
    for line in text.splitlines():
        heading = CATEGORY_RE.match(line)
        if heading:
            if current:
                sections.append(current)
            current = (heading.group(1).strip(), int(heading.group(2)), [])
            continue
        if line.startswith("## "):          # left the catalogue entirely
            if current:
                sections.append(current)
            current = None
            continue
        if current is not None and line.lstrip().startswith("|"):
            found = PLUGIN_LINK_RE.search(line)
            if found:
                current[2].append(found.group(1))
            elif any(f"]({repo})" in line or f"]({repo}/)" in line
                     for repo in external_repos):
                external_rows[id(current)] = external_rows.get(id(current), 0) + 1
    if current:
        sections.append(current)

    listed = [pid for _name, _count, ids in sections for pid in ids]

    for pid in sorted(on_disk - set(listed)):
        faults.append(f"plugins/{pid}/ has a manifest but no row in the catalogue")
    for pid in sorted(set(listed) - on_disk):
        faults.append(f"the catalogue lists {pid}, which is not a plugin directory")

    duplicates = {name for name, _c, _i in sections
                  if sum(1 for other, _c2, _i2 in sections if other == name) > 1}
    for name in sorted(duplicates):
        faults.append(f'category "{name}" has more than one heading, so it renders '
                      f"as separate tables")

    for section in sections:
        name, count, ids = section
        rows = len(ids) + external_rows.get(id(section), 0)
        if count != rows:
            faults.append(f'category "{name}" says ({count}) but has {rows} rows')

    # The third-party table is the other half of the catalogue and drifts the
    # same way: Sleeper Fantasy sat in the registry and not in the table, and
    # nothing noticed. Matched on the repo URL because those rows carry a
    # display name rather than a plugin id.
    for entry in external:
        repo = (entry.get("repo") or "").rstrip("/")
        if repo and repo not in text:
            faults.append(f"{entry['id']} is in the registry as a third-party "
                          f"plugin but its repo is not linked in the README")

    seen: dict[str, int] = {}
    for pid in listed:
        seen[pid] = seen.get(pid, 0) + 1
    for pid, times in sorted(seen.items()):
        if times > 1:
            faults.append(f"{pid} appears in the catalogue {times} times")

    return faults


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if the README is out of date, without writing")
    args = parser.parse_args()

    original = README.read_text(encoding="utf-8")
    updated = rewrite(original)

    faults = catalogue_faults(updated)
    for fault in faults:
        print(f"  catalogue: {fault}")

    if original != updated:
        if args.check:
            print("README plugin previews are out of date.")
            print("Run: python scripts/update_readme_previews.py")
            return 1
        README.write_text(updated, encoding="utf-8")
        # Counted from the rendered table rather than one asset directory: two
        # plugins keep their hero beside the plugin instead of under
        # docs/assets, and counting only the latter reported 42 of 44 as though
        # two were missing an image they had.
        with_preview = updated.count('<img src="./plugins/') + \
            updated.count('<img src="./docs/assets/')
        print(f"Updated README.md ({with_preview} plugins have a preview image).")
    else:
        print("README plugin tables are up to date.")

    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
