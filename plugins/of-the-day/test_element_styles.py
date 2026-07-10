#!/usr/bin/env python3
"""
Regression tests for of-the-day's element-style customization.

This plugin is the exemplar for the x-style-elements system: it had NO
customization before — the schema declares two elements (title_text,
body_text) compactly and the core expands them into full font/size/color/
offset config blocks. The promises tested here:

1. UNTOUCHED IS UNCHANGED — with no customization config (or one carrying
   only the schema defaults the web UI bakes in on save), rendering is
   byte-identical to the pre-customization code.
2. OVERRIDES ENGAGE — a genuinely changed font size / color / offset
   visibly changes the render.
3. The schema declaration expands (core side) and its defaults agree with
   what the plugin's resolver reads from the raw file.

Run from the core LEDMatrix tree (needs src.* and assets/fonts):
    cd /path/to/LEDMatrix
    python -m pytest /path/to/of-the-day/test_element_styles.py -q
"""

import os
import sys
from datetime import date

import pytest
from PIL import ImageChops

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import OfTheDayPlugin, STYLE_AVAILABLE  # noqa: E402

pytestmark = pytest.mark.skipif(
    not STYLE_AVAILABLE,
    reason="core without src.element_style — plugin uses classic styling",
)

ITEM = {"title": "Serendipity", "subtitle": "noun | ser-en-DIP-i-tee",
        "description": "Finding something good without looking for it."}


def _plugin(w, h, config=None):
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager)
    cfg = {"enabled": True, "categories": {}, "category_order": []}
    cfg.update(config or {})
    p = OfTheDayPlugin("of-the-day", cfg, VisualTestDisplayManager(w, h),
                       MockCacheManager(), MockPluginManager())
    return p


def _render_title(p):
    p._display_title({}, ITEM)
    return p.display_manager.image.copy()


def _render_content(p):
    p._display_content({}, ITEM)
    return p.display_manager.image.copy()


# What the web UI writes into config.json on save: the full schema defaults,
# whether or not the user touched anything.
SCHEMA_POPULATED = {"customization": {
    "title_text": {"font": "PressStart2P-Regular.ttf", "font_size": 8,
                   "text_color": [255, 255, 255]},
    "body_text": {"font": "4x6-font.ttf", "font_size": 6,
                  "text_color": [200, 200, 200]},
    "layout": {"title_text": {"x_offset": 0, "y_offset": 0},
               "body_text": {"x_offset": 0, "y_offset": 0}},
}}


class TestUntouchedIsUnchanged:
    @pytest.mark.parametrize("w,h", [(64, 32), (128, 32), (128, 64)])
    def test_bare_config_matches_schema_populated(self, w, h):
        """A never-saved config and a once-saved config (defaults baked in)
        must render identically — schema defaults are not overrides."""
        for render in (_render_title, _render_content):
            bare = render(_plugin(w, h, {}))
            populated = render(_plugin(w, h, SCHEMA_POPULATED))
            assert ImageChops.difference(bare, populated).getbbox() is None

    def test_classic_colors_survive(self):
        """The schema-default white/gray text_color must not clobber the
        plugin's classic colors (they're identical here, but the render
        must go through the classic path, not a forced override)."""
        p = _plugin(128, 32, SCHEMA_POPULATED)
        style = p._element_style_resolver if hasattr(p, '_element_style_resolver') else None
        p._display_title({}, ITEM)  # builds the resolver
        title = p._element_style_resolver.style(
            'title_text', classic_font='PressStart2P-Regular.ttf',
            classic_size=8, classic_color=(255, 255, 255))
        assert not title.user_forced
        assert not title.user_forced_color


class TestOverridesEngage:
    def test_font_size_override_changes_render(self):
        base = _render_title(_plugin(128, 32, {}))
        big = _render_title(_plugin(128, 32, {"customization": {
            "title_text": {"font": "PressStart2P-Regular.ttf",
                           "font_size": 16}}}))
        assert ImageChops.difference(base, big).getbbox() is not None

    def test_color_override_changes_render(self):
        base = _render_title(_plugin(128, 32, {}))
        red = _render_title(_plugin(128, 32, {"customization": {
            "title_text": {"text_color": [255, 0, 0]}}}))
        assert ImageChops.difference(base, red).getbbox() is not None

    def test_offset_shifts_render(self):
        base = _render_title(_plugin(128, 32, {}))
        shifted = _render_title(_plugin(128, 32, {"customization": {
            "layout": {"title_text": {"x_offset": 4}}}}))
        diff = ImageChops.difference(base, shifted).getbbox()
        assert diff is not None


class TestSchemaDeclaration:
    def test_expansion_generates_blocks(self):
        from src.element_style import expand_style_elements
        import json
        schema = json.load(open(os.path.join(PLUGIN_DIR, "config_schema.json")))
        expanded = expand_style_elements(schema)
        cust = expanded["properties"]["customization"]["properties"]
        assert cust["title_text"]["x-style-managed"] is True
        assert cust["title_text"]["properties"]["font"]["default"] == \
            "PressStart2P-Regular.ttf"
        assert cust["body_text"]["properties"]["text_color"]["default"] == \
            [200, 200, 200]
        assert "title_text" in cust["layout"]["properties"]

    def test_raw_file_defaults_match_declaration(self):
        from src.element_style import defaults_from_schema_file
        defaults = defaults_from_schema_file(
            os.path.join(PLUGIN_DIR, "config_schema.json"))
        assert defaults["customization"]["title_text"]["font_size"] == 8
        assert defaults["customization"]["body_text"]["text_color"] == [200, 200, 200]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
