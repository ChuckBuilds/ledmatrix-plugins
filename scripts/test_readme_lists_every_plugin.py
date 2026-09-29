#!/usr/bin/env python3
"""Every plugin under plugins/ must have a row in the root README's
Available Plugins tables, and each category heading's count must match its rows.

WHY THIS EXISTS
---------------
The Available Plugins tables are the repo's front page, and they are written by
hand. scripts/update_readme_previews.py only rewrites the Preview column of rows
that already exist -- it cannot add one, because it does not know a plugin's
category -- so a new plugin nobody adds by hand is simply invisible. That
happened to four plugins at once (#385). The "### Sports (20)" counts are hand
maintained too and drift the same way.

Checks, within the "## Available Plugins" section:
  * every plugins/<id>/ with a manifest.json has a row linking ./plugins/<id>/
  * every ./plugins/<id>/ row points at a directory that exists
  * no plugin is listed twice
  * each "### Category (N)" heading has exactly N rows

    python scripts/test_readme_lists_every_plugin.py

Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

HEADING = re.compile(r"^###\s+(?P<name>.+?)\s+\((?P<count>\d+)\)\s*$")
ROW = re.compile(r"^\|\s*\[[^\]]+\]\((?P<href>[^)]+)\)")
LOCAL = re.compile(r"^\./plugins/(?P<id>[^/]+)/?$")


def available_plugins_section(text: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines)
                     if l.strip() == "## Available Plugins")
    except StopIteration:
        return []
    section = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        section.append(line)
    return section


def check(text: str, plugin_ids: set[str]) -> list[str]:
    section = available_plugins_section(text)
    if not section:
        return ["README.md has no '## Available Plugins' section"]

    errors = []
    listed: dict[str, str] = {}
    category, declared, rows = None, 0, 0

    def close_category():
        if category is not None and rows != declared:
            errors.append(f"'### {category} ({declared})' has {rows} rows; "
                          f"change the heading to ({rows})")

    for line in section:
        m = HEADING.match(line)
        if m:
            close_category()
            category, declared, rows = m["name"], int(m["count"]), 0
            continue
        m = ROW.match(line)
        if not m:
            continue
        rows += 1
        local = LOCAL.match(m["href"])
        if not local:
            continue  # third-party row linking its own repo
        pid = local["id"]
        where = category or "(no category)"
        if pid in listed:
            errors.append(f"{pid} is listed twice (under '{listed[pid]}' "
                          f"and '{where}')")
        listed[pid] = where
        if pid not in plugin_ids:
            errors.append(f"row links ./plugins/{pid}/ under '{where}', "
                          f"but there is no such plugin")
    close_category()

    for pid in sorted(plugin_ids - set(listed)):
        errors.append(f"{pid} has no row in README's Available Plugins "
                      f"tables; add one under the right category and bump "
                      f"that heading's count")
    return errors


def main() -> int:
    plugin_ids = {p.parent.name for p in (REPO / "plugins").glob("*/manifest.json")}
    errors = check(README.read_text(encoding="utf-8"), plugin_ids)
    if errors:
        for e in errors:
            print(f"FAIL {e}")
        return 1
    print(f"PASS all {len(plugin_ids)} plugins are listed in README.md and "
          f"every category count matches its rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
