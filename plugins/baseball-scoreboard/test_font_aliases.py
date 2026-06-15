#!/usr/bin/env python3
"""
Regression test: font family aliases must resolve to real font files.

The schema defaults (and the persisted configs they produce) use the core
FontManager's family aliases — "press_start", "four_by_six" — rather than
literal filenames. The font loaders used to treat the config value as a
filename, building paths like "assets/fonts/press_start" that don't exist,
which logged "Font file not found ... using default" on every load.

These tests fail before the alias-resolution fix and pass after it.
"""

import os
import sys

# Make the plugin's sibling modules importable
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from game_renderer import resolve_font_name, FONT_ALIASES  # noqa: E402

EXPECTED = {
    "press_start": "PressStart2P-Regular.ttf",
    "four_by_six": "4x6-font.ttf",
    "five_by_seven": "5x7.bdf",
}


def test_aliases_resolve_to_filenames():
    for alias, filename in EXPECTED.items():
        got = resolve_font_name(alias)
        assert got == filename, f"{alias!r} resolved to {got!r}, expected {filename!r}"
    print("✓ family aliases resolve to real filenames")


def test_filenames_pass_through():
    for name in ("PressStart2P-Regular.ttf", "9x15B.bdf", "4x6-font.ttf"):
        got = resolve_font_name(name)
        assert got == name, f"filename {name!r} should pass through, got {got!r}"
    print("✓ literal filenames pass through unchanged")


def test_sports_and_renderer_maps_match():
    # Both loaders carry their own copy of the map; they must stay in sync.
    import sports
    assert sports.FONT_ALIASES == FONT_ALIASES, (
        "sports.FONT_ALIASES and game_renderer.FONT_ALIASES have diverged"
    )
    print("✓ sports.py and game_renderer.py alias maps agree")


def test_resolved_files_exist_in_assets():
    # Only meaningful when run from within the core LEDMatrix tree (where
    # assets/fonts lives). Skip gracefully otherwise so CI plugin-only runs pass.
    fonts_dir = os.path.join("assets", "fonts")
    if not os.path.isdir(fonts_dir):
        print(f"… skipped assets check (no {fonts_dir} relative to cwd)")
        return
    for filename in FONT_ALIASES.values():
        path = os.path.join(fonts_dir, filename)
        assert os.path.exists(path), f"alias target {path} does not exist"
    print("✓ every alias target exists under assets/fonts")


if __name__ == "__main__":
    print("Baseball scoreboard font-alias regression test")
    print("=" * 46)
    ok = True
    for t in (
        test_aliases_resolve_to_filenames,
        test_filenames_pass_through,
        test_sports_and_renderer_maps_match,
        test_resolved_files_exist_in_assets,
    ):
        try:
            t()
        except AssertionError as e:
            ok = False
            print(f"✗ {t.__name__}: {e}")
        except Exception as e:  # import errors etc.
            ok = False
            print(f"✗ {t.__name__}: unexpected error: {e}")
    print("=" * 46)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
