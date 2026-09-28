#!/usr/bin/env python3
"""Guards for the placeholder-aware logo load path.

A failed logo download is cached as a placeholder that wears the real logo's
filename. The scoreboards locate logos by scanning filename variations, so
without a placeholder check they load the grey stub and never consult the
downloader again -- one transient failure costs that team its logo forever.

The check lives in `_logo_needs_refresh`. Core 3.5.0 ships it as
`src.common.sports_helpers.logo_needs_refresh`; the scoreboards that floor on
3.5.0 import it under the private name, and the rest (ufc) still carry a
*copied* helper. These tests pin the behaviour -- of each remaining copy and,
when a core checkout is found (LEDMATRIX_CORE, or ../LEDMatrix), of core's --
and hold every copy byte-identical, so a fix to one cannot silently skip the
others. A loader must either define the helper or import core's.

Run from the repo root:

    python scripts/test_logo_placeholder_refresh.py
"""

import ast
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS = REPO_ROOT / "plugins"

HELPER_RE = re.compile(r"def _logo_needs_refresh\(.*?\n(?=\n\nclass )", re.S)
#: A loader that adopted core's helper under the private name.
ADOPTED_RE = re.compile(
    r"^from src\.common\.sports_helpers import \([^)]*"
    r"\blogo_needs_refresh as _logo_needs_refresh\b", re.M)


def core_checkout():
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""),
                      str(REPO_ROOT.parent / "LEDMatrix")):
        path = Path(candidate) / "src" / "common" / "sports_helpers.py" if candidate else None
        if path and path.is_file():
            return path
    return None


def helper_sources():
    """(label, source defining _logo_needs_refresh) for every body under test."""
    sources = []
    for path in copies():
        match = HELPER_RE.search(path.read_text(encoding="utf-8"))
        if match:
            sources.append((path.relative_to(REPO_ROOT).as_posix(), match.group(0)))
            break  # the copies are pinned identical below; one stands for all
    core = core_checkout()
    if core is not None:
        text = core.read_text(encoding="utf-8")
        node = next(n for n in ast.parse(text).body
                    if isinstance(n, ast.FunctionDef) and n.name == "logo_needs_refresh")
        body = ast.get_source_segment(text, node).replace(
            "def logo_needs_refresh(", "def _logo_needs_refresh(", 1)
        sources.append(("core src/common/sports_helpers.py", body + "\n"))
    return sources


def copies():
    """Every file that carries the copied logo load path."""
    found = sorted(PLUGINS.glob("*/sports.py"))
    extra = PLUGINS / "baseball-scoreboard" / "logo_manager.py"
    if extra.is_file():
        found.append(extra)
    return [p for p in found
            if "If no variation found, try to download missing logo"
            in p.read_text(encoding="utf-8")]


class HelperCopiesAgree(unittest.TestCase):
    def test_every_logo_loader_has_the_helper(self):
        missing = [p.relative_to(REPO_ROOT).as_posix() for p in copies()
                   if "_logo_needs_refresh" not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [], "logo loaders without a placeholder check")

    def test_every_loader_defines_the_helper_or_imports_cores(self):
        neither = [p.relative_to(REPO_ROOT).as_posix() for p in copies()
                   if not HELPER_RE.search(p.read_text(encoding="utf-8"))
                   and not ADOPTED_RE.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(neither, [], "loaders whose _logo_needs_refresh is "
                         "neither a copy here nor core's sports_helpers one")

    def test_all_copies_are_byte_identical(self):
        bodies = {}
        for path in copies():
            text = path.read_text(encoding="utf-8")
            match = HELPER_RE.search(text)
            if match is None and ADOPTED_RE.search(text):
                continue  # adopted core's; nothing local to keep in step
            self.assertIsNotNone(
                match, f"{path.relative_to(REPO_ROOT)}: no _logo_needs_refresh")
            bodies.setdefault(match.group(0), []).append(
                path.relative_to(REPO_ROOT).as_posix())
        self.assertLessEqual(
            len(bodies), 1,
            "copies of _logo_needs_refresh have diverged:\n"
            + "\n".join(f"  variant {i}: {ps}"
                        for i, ps in enumerate(bodies.values())))

    def test_the_download_gate_does_not_trust_mere_existence(self):
        """`not logo_path.exists()` in the gate is what caused the bug.

        With it, a placeholder sitting at logo_path suppressed the download
        even when the variations scan had rejected it as stale.
        """
        offenders = []
        for path in copies():
            text = path.read_text(encoding="utf-8")
            if "if not actual_logo_path and not logo_path.exists():" in text:
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(offenders, [], "download gate still trusts file existence")

    def test_helper_never_imports_logo_downloader_by_bare_name(self):
        """A deferred bare-name import can bind another plugin's vendored copy.

        Six plugins ship their own logo_downloader.py, and the core isolates
        top-level plugin modules after the entry point loads.
        """
        offenders = []
        for path in copies():
            match = HELPER_RE.search(path.read_text(encoding="utf-8"))
            if match and re.search(r"^\s*from logo_downloader import",
                                   match.group(0), re.M):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(offenders, [], "bare-name logo_downloader import in helper")


class HelperBehaviour(unittest.TestCase):
    """Exercise the helper -- a plugin copy and core's -- against stub core modules."""

    def _helpers(self, downloader_module):
        """One loaded helper per body under test, each labelled for subTest."""
        sources = helper_sources()
        if not sources:
            self.skipTest("no plugin copy of _logo_needs_refresh and no core checkout")
        return [(label, self._load_helper(downloader_module, source))
                for label, source in sources]

    def _load_helper(self, downloader_module, source):
        """Import the helper as a real module, extracted from a plugin copy.

        Written to a temp file and imported through importlib rather than
        exec()'d: importing the whole sports.py would drag in the core, and a
        normal import keeps this a module with a filename that tracebacks and
        coverage can point at.
        """
        tmpdir = tempfile.mkdtemp(prefix="logo-helper-")
        self.addCleanup(shutil.rmtree, tmpdir, True)
        module_path = Path(tmpdir) / "logo_helper_under_test.py"
        module_path.write_text(source, encoding="utf-8")

        spec = importlib.util.spec_from_file_location(
            "logo_helper_under_test", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        saved = {k: sys.modules.get(k) for k in ("src", "src.logo_downloader")}
        if downloader_module is not None:
            import types
            pkg = types.ModuleType("src")
            pkg.__path__ = []
            sys.modules["src"] = pkg
            sys.modules["src.logo_downloader"] = downloader_module
        else:
            sys.modules.pop("src.logo_downloader", None)
        self.addCleanup(self._restore, saved)
        return module._logo_needs_refresh

    @staticmethod
    def _restore(saved):
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    @staticmethod
    def _downloader(is_placeholder, age, retry=6 * 60 * 60):
        import types
        module = types.ModuleType("src.logo_downloader")
        module.PLACEHOLDER_RETRY_SECONDS = retry
        module.is_placeholder_logo = lambda _p: is_placeholder
        module.placeholder_age_seconds = lambda _p: age
        return module

    def test_real_logo_is_never_refreshed(self):
        for label, helper in self._helpers(self._downloader(False, None)):
            with self.subTest(helper=label):
                self.assertFalse(helper(Path("REAL.png")))

    def test_stale_placeholder_is_refreshed(self):
        for label, helper in self._helpers(self._downloader(True, 7 * 60 * 60)):
            with self.subTest(helper=label):
                self.assertTrue(helper(Path("COLL.png")))

    def test_fresh_placeholder_is_not_refreshed(self):
        """Rate limiting: otherwise this trades a grey box for a request per frame."""
        for label, helper in self._helpers(self._downloader(True, 60)):
            with self.subTest(helper=label):
                self.assertFalse(helper(Path("COLL.png")))

    def test_unknown_age_is_refreshed(self):
        for label, helper in self._helpers(self._downloader(True, None)):
            with self.subTest(helper=label):
                self.assertTrue(helper(Path("COLL.png")))

    def test_older_core_without_the_marker_keeps_old_behaviour(self):
        """The core may predate placeholder marking; degrade, do not crash."""
        for label, helper in self._helpers(None):
            with self.subTest(helper=label):
                self.assertFalse(helper(Path("COLL.png")))

    def test_a_raising_core_does_not_break_logo_loading(self):
        import types
        module = types.ModuleType("src.logo_downloader")
        module.PLACEHOLDER_RETRY_SECONDS = 100
        module.is_placeholder_logo = lambda _p: (_ for _ in ()).throw(OSError("boom"))
        module.placeholder_age_seconds = lambda _p: None
        for label, helper in self._helpers(module):
            with self.subTest(helper=label):
                self.assertFalse(helper(Path("COLL.png")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
