#!/usr/bin/env python3
"""Keep the scoreboards' bundled ESPN date-range helper whole and in use.

Since 2026-09-15 ESPN answers scoreboard ``dates=YYYYMMDD-YYYYMMDD`` queries
with ``400 Bad Request`` for every sport, and ``limit`` above 500 silently
truncates. The fix lives in LEDMatrix core as ``src/common/espn_dates.py``;
each of the nine scoreboards bundles a copy as ``<sport>_espn_dates.py`` so it
works on cores released before that module existed.

Two things decay without a check, so this guard checks both:

1. **The copies drift.** A fix made in one copy and not the others is exactly
   what CLAUDE.md non-negotiable #7 forbids. Every copy must match every other
   (ignoring its three-line header comment) and, when a core checkout that
   ships the module is available, match core's.
2. **A new fetch bypasses the helper.** A ``session.get`` / ``requests.get``
   whose ``params`` literal carries ``"dates"`` goes straight to ESPN, so a
   range 400s again. Every such call in a scoreboard's shipped code fails this
   check; route it through ``fetch_espn_scoreboard``.

Self-check: the scanner must flag a planted bypass, so a broken finder cannot
report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout or no ``src/common/espn_dates.py`` is found.

Run: python scripts/test_espn_dates_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"
SPORTS = ("afl", "baseball", "basketball", "football", "hockey",
          "lacrosse", "nrl", "soccer", "ufc")
HEADER_LINES = 3


def body_of(path: Path) -> str:
    """A bundled copy minus its header comment, with line endings normalised."""
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    header = lines[:HEADER_LINES]
    if not all(line.startswith("#") for line in header):
        raise ValueError(f"{path}: expected a {HEADER_LINES}-line '#' header naming the core module")
    return "\n".join(lines[HEADER_LINES:])


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def bypasses(source: str, filename: str) -> list[int]:
    """Line numbers of ``*.get(..., params={"dates": ...})`` calls."""
    hits = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "params" and isinstance(keyword.value, ast.Dict):
                keys = [k.value for k in keyword.value.keys if isinstance(k, ast.Constant)]
                if "dates" in keys:
                    hits.append(node.lineno)
    return hits


def main() -> int:
    failures: list[str] = []

    planted = 'r = self.session.get(url, params={"dates": d, "limit": 1000}, timeout=5)\n'
    if bypasses(planted, "<planted>") != [1]:
        print("FAIL: self-check -- the scanner did not flag a planted bypass")
        return 1

    copies = {}
    for sport in SPORTS:
        path = PLUGINS / f"{sport}-scoreboard" / f"{sport}_espn_dates.py"
        if not path.is_file():
            failures.append(f"missing {path.relative_to(REPO)}")
            continue
        try:
            copies[sport] = body_of(path)
        except ValueError as exc:
            failures.append(str(exc))

    if copies:
        reference_sport, reference = next(iter(copies.items()))
        for sport, body in copies.items():
            if body != reference:
                failures.append(f"{sport}_espn_dates.py differs from {reference_sport}_espn_dates.py")

        core = find_core()
        core_module = core / "src" / "common" / "espn_dates.py" if core else None
        if core_module and core_module.is_file():
            core_body = core_module.read_text(encoding="utf-8").replace("\r\n", "\n")
            if reference != core_body:
                failures.append(f"the bundled copies differ from {core_module}")
            else:
                print(f"  ok: bundled copies match {core_module}")
        else:
            print("  note: no core checkout shipping src/common/espn_dates.py; "
                  "compared the copies with each other only")

    for sport in SPORTS:
        plugin = PLUGINS / f"{sport}-scoreboard"
        for path in sorted(plugin.rglob("*.py")):
            relative = path.relative_to(plugin)
            if relative.parts[0] == "test" or path.name.startswith("test_"):
                continue
            for line in bypasses(path.read_text(encoding="utf-8"), str(path)):
                failures.append(
                    f"{path.relative_to(REPO)}:{line} sends ESPN a dates param directly; "
                    "use fetch_espn_scoreboard so a rejected range is re-fetched in chunks"
                )

    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        return 1
    print(f"OK: {len(copies)} bundled ESPN date helpers identical, no direct dates fetches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
