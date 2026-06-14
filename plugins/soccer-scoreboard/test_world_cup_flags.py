#!/usr/bin/env python3
"""
Regression test for FIFA World Cup national-team flags.

Run standalone from the plugin directory:

    cd plugins/soccer-scoreboard
    python test_world_cup_flags.py

The plugin bundles every World Cup nation's flag and, for the `fifa.world`
league, redirects its logo directory to a dedicated `national/` subdirectory
seeded from those bundled flags. This isolates national flags from club logos
that share an abbreviation (e.g. ESP = Spain vs Espanyol, POR = Portugal vs
Portland Timbers) and guarantees every team renders a real flag instead of a
stale placeholder.

This test fails before that change (no `_setup_national_flags_dir`, no bundled
flags) and passes after. No external test framework is required — the script
exits non-zero on the first failure and prints a summary on success.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

BUNDLED_FLAGS = PLUGIN_DIR / "assets" / "flags"


# ---------------------------------------------------------------------------
# Stub the LEDMatrix host modules so the plugin imports resolve without the
# full core checkout on the path.
# ---------------------------------------------------------------------------
def _install_host_stubs() -> None:
    """Register fake LEDMatrix host modules so the plugin imports resolve."""
    for name in ["src", "src.background_data_service"]:
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["src.background_data_service"].get_background_service = (
        lambda *a, **k: None
    )

    logo_mod = types.ModuleType("src.logo_downloader")

    class _LogoDownloader:
        """Minimal stand-in for the core LogoDownloader used during import."""

        def get_logo_directory(self, league):
            """Return a throwaway logo directory (unused — __init__ is bypassed)."""
            return str(Path(tempfile.gettempdir()) / "soccer_logos")

        @staticmethod
        def normalize_abbreviation(abbr):
            """Uppercase an abbreviation, matching the real downloader."""
            return abbr.upper()

        @staticmethod
        def get_logo_filename_variations(abbr):
            """Return the single uppercase filename variation for the stub."""
            return [f"{abbr.upper()}.png"]

    logo_mod.LogoDownloader = _LogoDownloader
    logo_mod.download_missing_logo = lambda *a, **k: False
    sys.modules["src.logo_downloader"] = logo_mod


def _make_manager_stub():
    """Build a BaseSoccerManager without running its heavy __init__."""
    from soccer_managers import BaseSoccerManager

    mgr = BaseSoccerManager.__new__(BaseSoccerManager)
    mgr.logger = logging.getLogger("test-world-cup-flags")
    return mgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_bundled_flags_present():
    """The plugin ships the full World Cup flag set, not placeholders."""
    assert BUNDLED_FLAGS.is_dir(), f"bundled flags dir missing: {BUNDLED_FLAGS}"
    flags = list(BUNDLED_FLAGS.glob("*.png"))
    assert len(flags) >= 40, f"expected the full World Cup field, found {len(flags)} flags"
    aus = BUNDLED_FLAGS / "AUS.png"
    assert aus.exists(), "Australia flag (AUS.png) is not bundled"
    # The old broken behaviour shipped a ~577-byte gray placeholder. A real
    # flag is meaningfully larger.
    assert aus.stat().st_size > 1500, (
        f"AUS.png looks like a placeholder ({aus.stat().st_size} bytes), not a real flag"
    )


def test_fifa_world_uses_isolated_seeded_dir():
    """fifa.world gets a dedicated national/ dir seeded from the bundled flags."""
    mgr = _make_manager_stub()
    with tempfile.TemporaryDirectory() as tmp:
        club_dir = Path(tmp)
        result = mgr._setup_national_flags_dir(club_dir)

        assert result == club_dir / "national", f"expected national subdir, got {result}"
        assert result.is_dir(), "national flags directory was not created"

        seeded = {p.name for p in result.glob("*.png")}
        bundled = {p.name for p in BUNDLED_FLAGS.glob("*.png")}
        assert seeded == bundled, (
            f"seeded flags differ from bundled set (missing: {bundled - seeded})"
        )

        aus_seeded = (result / "AUS.png").read_bytes()
        aus_bundled = (BUNDLED_FLAGS / "AUS.png").read_bytes()
        assert aus_seeded == aus_bundled, "seeded AUS.png does not match the bundled flag"


def test_does_not_collide_with_club_logos():
    """A pre-existing club crest in the shared dir must not shadow a nation's flag."""
    mgr = _make_manager_stub()
    with tempfile.TemporaryDirectory() as tmp:
        club_dir = Path(tmp)
        # Espanyol (ESP) and Portland (POR) crests sitting in the shared soccer dir.
        bogus = b"\x89PNG\r\n\x1a\n" + b"club-crest" * 4
        (club_dir / "ESP.png").write_bytes(bogus)
        (club_dir / "POR.png").write_bytes(bogus)

        national = mgr._setup_national_flags_dir(club_dir)

        for abbr in ("ESP", "POR"):
            nat = (national / f"{abbr}.png").read_bytes()
            assert nat != bogus, f"{abbr} flag was shadowed by the club crest"
            assert nat == (BUNDLED_FLAGS / f"{abbr}.png").read_bytes(), (
                f"{abbr} national flag does not match the bundled flag"
            )
        # The club crests in the shared dir are left untouched.
        assert (club_dir / "ESP.png").read_bytes() == bogus, "club crest was overwritten"


def main() -> int:
    """Run every flag test and return a process exit code."""
    _install_host_stubs()
    tests = [
        ("bundled flags present", test_bundled_flags_present),
        ("fifa.world uses isolated seeded dir", test_fifa_world_uses_isolated_seeded_dir),
        ("national flags don't collide with club logos", test_does_not_collide_with_club_logos),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 — surface every failure
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failed += 1

    if failed:
        print(f"\n{failed} test(s) failed.")
        return 1
    print("\nAll World Cup flag tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
