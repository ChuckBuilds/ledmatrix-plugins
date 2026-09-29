#!/usr/bin/env python3
r"""Every plugins/*/manifest.json must be pure ASCII.

    python scripts/check_manifests_ascii.py

Exit codes: 0 pass, 1 fail.

## Why this exists

JSON is UTF-8 by RFC 8259, but Python's ``open()`` without ``encoding=`` uses
the locale's encoding, which is cp1252 on Windows. The core read manifests
that way in ``src/plugin_system/testing/loading.py:load_manifest`` -- the
loader behind ``scripts/check_plugin.py`` -- until v3.4.0, and
``scripts/dev_server.py`` still does. Under cp1252 a raw UTF-8 character either

- garbles silently: an em dash (E2 80 94) reads back as three characters,
  a-circumflex, euro sign, right double quote; or
- aborts the read with UnicodeDecodeError, when its bytes include one of the
  five that cp1252 leaves undefined (81 8D 8F 90 9D) -- a closing curly
  quote, U+201D, ends in 9D.

The first is not hypothetical. Two manifests went through that round trip
and were committed with the damage escaped: on-air's description reads
``\u00e2\u20ac\u201d`` where an em dash was meant, and odds-ticker's 1.1.7
notes ``LA\u00e2\u2020\u2019LAR`` where ``LA\u2192LAR`` was.

Every other manifest already stores such characters as JSON ``\uXXXX``
escapes, which every reader decodes to the same text whatever its encoding.
``json.dumps`` writes them by default (``ensure_ascii=True``). This guard keeps
it that way: it reads raw bytes, so it catches a manifest that decodes
cleanly on Linux CI but not on a Windows harness run.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

# The tree holds 46 manifests. Fewer than 41 means the glob or the layout
# changed and a clean result would be vacuous.
MIN_PLAUSIBLE_MANIFESTS = 41

BOM = "\ufeff"


def escape_char(ch: str) -> str:
    """The JSON escape for one character: \\uXXXX, or a surrogate pair above
    the Basic Multilingual Plane (JSON has no \\U form)."""
    cp = ord(ch)
    if cp <= 0xFFFF:
        return "\\u%04x" % cp
    cp -= 0x10000
    return "\\u%04x\\u%04x" % (0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF))


def find_problems(raw: bytes) -> list[str]:
    """One line per offending character in a manifest's raw bytes."""
    if raw.isascii():
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return [f"not valid UTF-8 either: byte 0x{raw[e.start]:02X} at offset "
                f"{e.start} (saved in a legacy encoding?)"]
    problems = []
    # Not splitlines(): it also breaks on U+0085, U+2028 and U+2029, which
    # are exactly the kind of character this must report.
    for lineno, line in enumerate(text.split("\n"), 1):
        for col, ch in enumerate(line, 1):
            if ch.isascii():
                continue
            if ch == BOM and lineno == 1 and col == 1:
                problems.append("line 1: starts with a UTF-8 byte-order mark; "
                                "save the file without one")
            else:
                problems.append(f"line {lineno}, col {col}: U+{ord(ch):04X} "
                                f"-- write {escape_char(ch)}")
    return problems


def main(plugins_dir: Path = PLUGINS_DIR,
         min_manifests: int = MIN_PLAUSIBLE_MANIFESTS) -> int:
    manifests = sorted(plugins_dir.glob("*/manifest.json"))
    failed = False
    if len(manifests) < min_manifests:
        print(f"FAIL only {len(manifests)} manifest.json files found under "
              f"{plugins_dir} (expected at least {min_manifests}); the check "
              f"is not looking at the plugin tree")
        failed = True
    for path in manifests:
        problems = find_problems(path.read_bytes())
        if not problems:
            continue
        failed = True
        print(f"FAIL {path.parent.name}/manifest.json: raw non-ASCII")
        for p in problems:
            print(f"       {p}")
    if failed:
        print("\nStore non-ASCII characters as JSON \\uXXXX escapes (what "
              "json.dumps writes by default). Tools that open manifest.json in "
              "the platform's default encoding -- cp1252 on Windows -- garble "
              "or reject raw UTF-8.")
        return 1
    print(f"PASS {len(manifests)} manifests are pure ASCII")
    return 0


if __name__ == "__main__":
    sys.exit(main())
