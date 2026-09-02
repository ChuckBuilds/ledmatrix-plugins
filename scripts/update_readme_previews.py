#!/usr/bin/env python3
"""Keep the Preview column of the root README's plugin tables in sync.

The "Available Plugins" tables in ``README.md`` carry a thumbnail of each
plugin's hero screenshot. This script rewrites that column from what is
actually on disk: a plugin gets a thumbnail once
``docs/assets/<plugin-id>/hero.png`` exists, and an empty cell until then.

Run it after adding a plugin's README screenshots::

    python scripts/update_readme_previews.py
    python scripts/update_readme_previews.py --check   # CI / pre-commit

Doing this by hand across forty-odd rows drifts: a row gets a thumbnail whose
image was never committed, or an image lands and the table is never updated.
The tables are keyed off the ``./plugins/<id>/`` link already in each row, so
there is no second list to keep in step.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
ASSETS_ROOT = REPO_ROOT / "docs" / "assets"

HEADER_RE = re.compile(r"^\|\s*Plugin\s*\|\s*Description\s*\|(\s*Preview\s*\|)?\s*$")
SEPARATOR_RE = re.compile(r"^\|[\s:-]+\|[\s:-]+\|([\s:-]+\|)?\s*$")
PLUGIN_LINK_RE = re.compile(r"\]\(\./plugins/([^/)]+)/?\)")

# Wide enough to read a 128-pixel panel at a glance, narrow enough that the
# Description column still has room on a laptop-width screen.
THUMB_WIDTH = 240

HEADER = "| Plugin | Description | Preview |"
SEPARATOR = "|--------|-------------|---------|"


def preview_cell(plugin_id: str) -> str:
    """The Preview cell for one plugin: a thumbnail, or empty if none yet."""
    hero = ASSETS_ROOT / plugin_id / "hero.png"
    if not hero.is_file():
        return " "
    return (
        f' <a href="./plugins/{plugin_id}/">'
        f'<img src="./docs/assets/{plugin_id}/hero.png" width="{THUMB_WIDTH}"'
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if the README is out of date, without writing")
    args = parser.parse_args()

    original = README.read_text(encoding="utf-8")
    updated = rewrite(original)

    if original == updated:
        print("README plugin tables are up to date.")
        return 0

    if args.check:
        print("README plugin previews are out of date.")
        print("Run: python scripts/update_readme_previews.py")
        return 1

    README.write_text(updated, encoding="utf-8")
    with_preview = updated.count('<img src="./docs/assets/')
    print(f"Updated README.md ({with_preview} plugins have a preview image).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
