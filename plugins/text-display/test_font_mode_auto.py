#!/usr/bin/env python3
"""
Regression test for font_mode: "auto" font-ladder crispness.

PIL antialiases TTF outlines by default; a "pixel-style" font (PressStart2P,
4x6-font) only rasterizes without antialiasing at specific sizes (for
PressStart2P: exact multiples of its 8px design grid). A ladder rung at an
unverified size silently renders blurry on an LED panel. This test measures
actual rendered pixels for every rung in AUTO_FONT_LADDER and fails if any
of them are not crisp — the class of bug fixed here: "5by7.regular" (never
crisp at any size) and "4x6-font" at 6px (33% antialiased; 7px is crisp)
were both in the ladder before this test existed.

Run from the core LEDMatrix tree (needs src.font_manager, assets/fonts):
    cd /path/to/LEDMatrix
    python -m pytest /path/to/text-display/test_font_mode_auto.py -q
"""

import os
import sys

import pytest

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import AUTO_FONT_LADDER  # noqa: E402

pytestmark = pytest.mark.skipif(
    AUTO_FONT_LADDER is None,
    reason="core without src.adaptive_layout — auto font_mode falls back to manual",
)


def test_every_ladder_rung_is_crisp():
    from src.adaptive_layout import measure_font_crispness
    from src.font_manager import FontManager

    fm = FontManager({})
    offenders = []
    for step in AUTO_FONT_LADDER:
        font = fm.get_font(step.family, step.size_px)
        crispness = measure_font_crispness(font, "Subscribe 123")
        if crispness > 0.02:  # allow a hair of tolerance for diagonal strokes
            offenders.append(f"{step.family}@{step.size_px}px: {crispness:.1%} antialiased")
    assert not offenders, "Blurry ladder rung(s):\n  " + "\n  ".join(offenders)


def test_ladder_is_nonempty():
    assert len(AUTO_FONT_LADDER) >= 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
