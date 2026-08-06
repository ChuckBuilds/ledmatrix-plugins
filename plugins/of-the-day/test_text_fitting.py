#!/usr/bin/env python3
"""
Regression tests for of-the-day's font-aware text fitting.

Long definitions/subtitles must wrap into multiple lines sized to the actual
font metrics (not a fixed line count), and when the configured font can't
fit the whole text on the panel the plugin shrinks scalable fonts to the
largest size that fits everything. When nothing fits, the configured font is
kept and the text is cut with an ellipsis instead of silently dropping lines.

Run from the core LEDMatrix tree (needs src.* and assets/fonts):
    cd /path/to/LEDMatrix
    python -m pytest /path/to/of-the-day/test_text_fitting.py -q
"""

import os
import sys

import pytest
from PIL import ImageChops

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import OfTheDayPlugin  # noqa: E402

SHORT_ITEM = {"title": "Serendipity", "subtitle": "noun",
              "description": "Finding something good without looking for it."}

LONG_ITEM = {
    "title": "Nepotism",
    "subtitle": ("The practice among those with power or influence of "
                 "favoring relatives or friends, especially by giving "
                 "them jobs"),
    "description": ("Accusations of nepotism plagued the new administration, "
                    "as several family members were given high-ranking "
                    "positions."),
}


def _plugin(w, h, config=None):
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager)
    cfg = {"enabled": True, "categories": {}, "category_order": []}
    cfg.update(config or {})
    return OfTheDayPlugin("of-the-day", cfg, VisualTestDisplayManager(w, h),
                          MockCacheManager(), MockPluginManager())


def _body_font(p):
    return p._element_styles()[3]


class TestFitWrappedText:
    def test_short_text_keeps_configured_font(self):
        p = _plugin(128, 64)
        font = _body_font(p)
        fitted, lines, _ = p._fit_wrapped_text("hello world", font, 124, 40)
        assert fitted is font
        assert lines == ["hello world"]

    def test_long_text_wraps_to_multiple_full_lines(self):
        p = _plugin(128, 64)
        font = _body_font(p)
        fitted, lines, _ = p._fit_wrapped_text(
            LONG_ITEM["description"], font, 124, 40)
        assert len(lines) > 1
        # Nothing dropped: rejoining the lines restores every word.
        assert " ".join(lines).split() == LONG_ITEM["description"].split()
        # Every line respects the wrap width for the font actually used.
        assert all(p._text_width(line, fitted) <= 124 for line in lines)

    def test_oversized_font_shrinks_until_text_fits(self):
        p = _plugin(128, 64, {"customization": {
            "body_text": {"font": "4x6-font.ttf", "font_size": 10}}})
        font = _body_font(p)
        fitted, lines, _ = p._fit_wrapped_text(
            LONG_ITEM["description"], font, 124, 40)
        assert fitted.size < font.size
        assert fitted.size >= OfTheDayPlugin.MIN_AUTO_FONT_SIZE
        assert " ".join(lines).split() == LONG_ITEM["description"].split()

    def test_unfittable_text_keeps_font_and_ellipsizes(self):
        p = _plugin(64, 32)
        font = _body_font(p)
        fitted, lines, height = p._fit_wrapped_text(
            LONG_ITEM["description"], font, 60, 11)
        # No smaller size holds everything on this panel: the configured
        # (crisper) font is kept and the cut is marked.
        assert fitted is font
        assert lines[-1].endswith("...")
        # The lines that remain still fit the given box.
        spans = len(lines) * height + (len(lines) - 1)
        assert spans <= 11 + height  # at most max_lines = (11+1)//(h+1) lines
        assert all(p._text_width(line, fitted) <= 60 for line in lines)

    def test_auto_fit_disabled_never_shrinks(self):
        p = _plugin(128, 64, {"auto_fit_text": False, "customization": {
            "body_text": {"font": "4x6-font.ttf", "font_size": 10}}})
        font = _body_font(p)
        fitted, lines, _ = p._fit_wrapped_text(
            LONG_ITEM["description"], font, 124, 40)
        assert fitted is font
        assert lines[-1].endswith("...")


class TestRendering:
    @pytest.mark.parametrize("w,h", [(64, 32), (128, 32), (128, 64), (256, 32)])
    def test_no_blank_screen_and_no_crash(self, w, h):
        p = _plugin(w, h)
        p._display_content({}, LONG_ITEM)
        assert p.display_manager.image.getbbox() is not None
        p._display_title({}, LONG_ITEM)
        assert p.display_manager.image.getbbox() is not None

    def test_short_item_render_unaffected_by_auto_fit_flag(self):
        """Text that fits renders byte-identically with auto-fit on or off."""
        for render in ("_display_title", "_display_content"):
            imgs = []
            for flag in (True, False):
                p = _plugin(128, 32, {"auto_fit_text": flag})
                getattr(p, render)({}, SHORT_ITEM)
                imgs.append(p.display_manager.image.copy())
            assert ImageChops.difference(imgs[0], imgs[1]).getbbox() is None

    def test_long_item_uses_more_lines_than_before(self):
        """A long definition fills the 128x64 panel with wrapped lines whose
        content reaches further down than a single clipped line would."""
        p = _plugin(128, 64)
        p._display_content({}, LONG_ITEM)
        bbox = p.display_manager.image.getbbox()
        assert bbox[3] > 40  # text extends well into the lower half
