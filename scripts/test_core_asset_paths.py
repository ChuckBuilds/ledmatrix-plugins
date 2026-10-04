#!/usr/bin/env python3
"""Every asset path a plugin spells must match the shipped file's case.

The Pi's filesystem is case-sensitive: ``NFL.png`` and ``nfl.png`` are two
different files there. Windows and default macOS are not, so a path that
differs from the shipped file only in case loads on a dev box, then misses on
every Pi. That is how the leaderboard lost its NFL, MLB and NHL league logos:
it named ``nfl_logos/nfl.png``, the core shipped both spellings until 3.3.0
dropped the lowercase copies (core #506), and nothing here noticed. The only
symptom was a warning on the Pi every cycle and a blank logo column.

This scans every ``assets/...`` string literal in plugin code and JSON, and in
the docs render fixtures, and fails when the file exists in the core checkout
(or the plugin's own directory) only under a different case. A path that
exists nowhere is not flagged: plenty are optional drop-ins or are downloaded
at runtime.

Scoreboard separator icons get a stricter check, because a wrong one fails
silently: each ``*_SEPARATOR_ICON`` must name a file the core ships, or be
declared in UNSHIPPED_SEPARATOR_ICONS as a drop-in nothing ships.

Needs a core checkout (LEDMATRIX_CORE, or ../LEDMatrix); exits 2 without one.

    python scripts/test_core_asset_paths.py
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS = REPO_ROOT / "plugins"
DOCS_ASSETS = REPO_ROOT / "docs" / "assets"

#: A quoted asset path. f-strings and os.path.join() pieces do not match, so
#: only literal paths are checked; those are where a misspelling hides.
ASSET_RE = re.compile(
    r"""["'](assets/[A-Za-z0-9_.\-/]+\.(?:png|jpe?g|gif|bmp|bdf|ttf|otf))["']""",
    re.IGNORECASE)


#: Separator icons a scoreboard names but the core does not ship. Each is a
#: drop-in: the league scrolls without a separator until a file is added at
#: that path (ufc falls back to the icon it ships). A path NOT listed here
#: must name a file the core ships -- hockey named ncaa_hockey.png for years
#: while the core's NCAA hockey badge sat at ncaah.png. An entry that the core
#: starts shipping fails too, so this list only shrinks.
UNSHIPPED_SEPARATOR_ICONS = {
    "assets/sports/milb_logos/MiLB.png",  # baseball: no MiLB league logo
    "assets/sports/ncaa_logos/ncaa_baseball.png",  # baseball: NCAA badges are sport-specific
    "assets/sports/wnba_logos/WNBA.png",  # basketball: no WNBA league logo
    "assets/sports/ncaa_logos/NCAA.png",  # hockey, lacrosse: no sport-neutral NCAA badge
    "assets/sports/ncaa_logos/ncaa_lacrosse.png",  # lacrosse: no NCAA lacrosse badge
    "assets/sports/ufc_logos/UFC.png",  # ufc: an override; the plugin ships its own copy
}

SEPARATOR_RE = re.compile(r"""^\s+\w+_SEPARATOR_ICON\s*=\s*["']([^"']+)["']""", re.M)


def core_checkout():
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""),
                      str(REPO_ROOT.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "assets").is_dir():
            return Path(candidate)
    return None


def spelled_on_disk(root, rel):
    """How ``rel`` is spelled under ``root``.

    Returns ``rel`` when every component matches exactly, the on-disk spelling
    when one only matches ignoring case, and None when it is absent. Compares
    against os.listdir() rather than calling os.path.exists(), which says yes
    to any case on Windows and macOS -- the very blind spot this guards.
    """
    current = Path(root)
    spelled = []
    for part in rel.split("/"):
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        if part not in entries:
            folded = [e for e in entries if e.lower() == part.lower()]
            if not folded:
                return None
            part = sorted(folded)[0]
        spelled.append(part)
        current = current / part
    return "/".join(spelled)


def sources():
    """(file, plugin dir or None) for every file whose literals are checked."""
    for path in sorted(PLUGINS.rglob("*")):
        if path.suffix not in (".py", ".json") or "__pycache__" in path.parts:
            continue
        plugin_dir = PLUGINS / path.relative_to(PLUGINS).parts[0]
        yield path, plugin_dir
    if DOCS_ASSETS.is_dir():
        for path in sorted(DOCS_ASSETS.rglob("*.json")):
            plugin_dir = PLUGINS / path.relative_to(DOCS_ASSETS).parts[0]
            yield path, plugin_dir if plugin_dir.is_dir() else None


def case_mismatches(core):
    """'file:line: path -> shipped spelling' for every miscased literal."""
    problems = []
    for path, plugin_dir in sources():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in ASSET_RE.finditer(line):
                rel = match.group(1)
                for root in (core, plugin_dir):
                    if root is None:
                        continue
                    on_disk = spelled_on_disk(root, rel)
                    if on_disk is None:
                        continue
                    if on_disk != rel:
                        where = "core" if root == core else "the plugin"
                        problems.append(
                            f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: "
                            f"{rel} -> {where} ships {on_disk}")
                    break
    return problems


class SpelledOnDiskTests(unittest.TestCase):
    """The resolver itself, on a scratch tree (any filesystem)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "assets" / "sports" / "nfl_logos").mkdir(parents=True)
        (self.root / "assets" / "sports" / "nfl_logos" / "NFL.png").write_bytes(b"")

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_spelling_is_returned_unchanged(self):
        rel = "assets/sports/nfl_logos/NFL.png"
        self.assertEqual(spelled_on_disk(self.root, rel), rel)

    def test_case_only_difference_reports_the_shipped_spelling(self):
        self.assertEqual(spelled_on_disk(self.root, "assets/sports/nfl_logos/nfl.png"),
                         "assets/sports/nfl_logos/NFL.png")
        self.assertEqual(spelled_on_disk(self.root, "assets/Sports/nfl_logos/NFL.png"),
                         "assets/sports/nfl_logos/NFL.png")

    def test_absent_file_is_none(self):
        self.assertIsNone(spelled_on_disk(self.root, "assets/sports/nfl_logos/MiLB.png"))
        self.assertIsNone(spelled_on_disk(self.root, "assets/sports/milb_logos/MiLB.png"))

    def test_quoted_literals_are_found_and_templates_are_not(self):
        line = ("a = 'assets/sports/nfl_logos/nfl.png'; "
                "b = f\"assets/sports/{x}_logos/{y}.png\"; c = \"assets/fonts/4x6-font.ttf\"")
        self.assertEqual([m.group(1) for m in ASSET_RE.finditer(line)],
                         ["assets/sports/nfl_logos/nfl.png", "assets/fonts/4x6-font.ttf"])


class CoreAssetCaseTests(unittest.TestCase):
    """Every literal asset path in the repo against a real core checkout."""

    def test_no_asset_path_differs_from_the_shipped_file_only_in_case(self):
        core = core_checkout()
        if core is None:
            self.skipTest("no LEDMatrix core checkout")
        problems = case_mismatches(core)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_separator_icons_are_shipped_or_declared_drop_ins(self):
        core = core_checkout()
        if core is None:
            self.skipTest("no LEDMatrix core checkout")
        problems = []
        named = set()
        for path in sorted(PLUGINS.glob("*/scroll_display.py")):
            for match in SEPARATOR_RE.finditer(path.read_text(encoding="utf-8")):
                rel = match.group(1)
                named.add(rel)
                if rel in UNSHIPPED_SEPARATOR_ICONS or spelled_on_disk(core, rel) == rel:
                    continue
                problems.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}: {rel} is not in the core; "
                    f"point it at an icon the core ships, or list it in "
                    f"UNSHIPPED_SEPARATOR_ICONS and skip it quietly")
        for rel in sorted(UNSHIPPED_SEPARATOR_ICONS):
            if spelled_on_disk(core, rel) is not None:
                problems.append(f"{rel} now ships with the core; drop it from "
                                f"UNSHIPPED_SEPARATOR_ICONS")
            elif rel not in named:
                problems.append(f"{rel} is in UNSHIPPED_SEPARATOR_ICONS but no "
                                f"scroll_display.py names it any more")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


if __name__ == "__main__":
    if core_checkout() is None:
        print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE or clone ../LEDMatrix)")
        sys.exit(2)
    unittest.main()
