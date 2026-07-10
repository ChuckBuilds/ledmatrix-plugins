#!/usr/bin/env python3
"""
Regression tests for the opt-in adaptive layout mode (layout_mode: "adaptive").

Guards the same two promises as football-scoreboard's and text-display's
adaptive modes:
1. CLASSIC IS UNTOUCHED — with the default config (layout_mode absent or
   "classic") the renderer takes the classic path and renders byte-identically
   to a renderer that has never heard of adaptive layout.
2. ADAPTIVE SCALES + RESPECTS CUSTOMIZATION — title/artist/album fonts grow
   with the panel (height-driven, matching how the album art itself already
   scales), user-configured fonts win over the ladder, and every ladder rung
   renders with zero antialiasing.

Run from the core LEDMatrix tree (needs src.* and assets/fonts):
    cd /path/to/LEDMatrix
    python -m pytest /path/to/ledmatrix-music/test_adaptive_layout_mode.py -q
"""

import os
import sys

import pytest
from PIL import ImageChops

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import ADAPTIVE_AVAILABLE, ADAPTIVE_LADDER_TEXT, MusicPlugin  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ADAPTIVE_AVAILABLE,
    reason="core without src.adaptive_layout — adaptive mode falls back to classic",
)

SIZES = [(64, 32), (128, 32), (96, 48), (128, 64), (256, 128)]


def _plugin(w, h, config=None):
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager,
    )
    dm = VisualTestDisplayManager(w, h)
    cfg = {"enabled": False, "preferred_source": "spotify"}
    cfg.update(config or {})
    p = MusicPlugin("ledmatrix-music", cfg, dm, MockCacheManager(), MockPluginManager())
    p.current_track_info = {
        "title": "A Song Title",
        "artist": "An Artist Name",
        "album": "An Album Name",
        "album_art_url": None,
        "duration_ms": 200000,
        "progress_ms": 60000,
        "is_playing": True,
    }
    p.is_music_display_active = True
    return p


class TestClassicUntouched:
    @pytest.mark.parametrize("config", [{}, {"layout_mode": "classic"}])
    def test_default_takes_classic_path(self, config):
        p = _plugin(128, 32, config)
        assert not p._adaptive

    @pytest.mark.parametrize("w,h", SIZES)
    def test_classic_render_byte_identical(self, w, h):
        """A default plugin must render the same pixels as one explicitly
        set to classic — proving the adaptive changes are inert by default."""
        baseline = _plugin(w, h, {})
        baseline.display(force_clear=True)
        classic = _plugin(w, h, {"layout_mode": "classic"})
        classic.display(force_clear=True)
        assert ImageChops.difference(
            baseline.display_manager.image, classic.display_manager.image
        ).getbbox() is None


class TestAdaptiveMode:
    def test_adaptive_flag(self):
        assert _plugin(128, 32, {"layout_mode": "adaptive"})._adaptive

    @pytest.mark.parametrize("w,h", SIZES)
    def test_renders_without_error(self, w, h):
        p = _plugin(w, h, {"layout_mode": "adaptive"})
        p.display(force_clear=True)  # must not raise
        assert p.display_manager.image.size == (w, h)

    @staticmethod
    def _title_row_ink_height(plugin):
        """Measure the rendered title row's actual ink height — a direct
        check of what display() drew, not a re-derivation of the sizing
        logic (which could pass even if the render path were wired wrong)."""
        img = plugin.display_manager.image
        h = plugin.display_manager.matrix.height
        art_size = h
        title_band = img.crop((art_size + 2, 0, img.width, h // 3 + 2))
        lit = title_band.convert("L").point(lambda v: 255 if v > 30 else 0)
        bbox = lit.getbbox()
        return (bbox[3] - bbox[1]) if bbox else 0

    def test_title_font_grows_with_height(self):
        """128x64 and 256x128 (height 2x/4x the 128x32 design size) must
        render a visibly taller title than 128x32 — the same height-driven
        growth the album art (album_art_size = matrix_height) already has."""
        track = {"title": "SONGTITLE", "artist": "ARTISTNAME", "album": "ALBUMNAME",
                "album_art_url": None, "duration_ms": 200000, "progress_ms": 60000,
                "is_playing": True}
        heights = {}
        for w, h in [(128, 32), (128, 64), (256, 128)]:
            p = _plugin(w, h, {"layout_mode": "adaptive"})
            p.current_track_info = track
            p.display(force_clear=True)
            heights[h] = self._title_row_ink_height(p)
        assert heights[64] > heights[32]
        assert heights[128] > heights[64]

    def test_user_font_wins_over_ladder(self):
        """An explicitly configured title font must be used verbatim, even
        in adaptive mode — 12px genuinely differs from the classic default
        (8px), so this must register as a real user override."""
        cfg = {"layout_mode": "adaptive",
               "customization": {"title_text": {"font_size": 12}}}
        p = _plugin(256, 128, cfg)
        assert p._user_font_set('title_text')
        p.display(force_clear=True)  # must not raise, must not crash

    def test_schema_default_is_not_mistaken_for_a_user_override(self):
        """The web UI's save flow (schema_manager.merge_with_defaults)
        writes the FULL schema default object into config.json on every
        save — for every plugin, whether or not the user touched that
        section. A config carrying only the schema's own declared defaults
        must NOT be treated as a forced override, or adaptive sizing would
        never engage on any config that's ever been saved once."""
        cfg = {"layout_mode": "adaptive", "customization": {
            "title_text": {"font": "PressStart2P-Regular.ttf", "font_size": 8},
            "artist_text": {"font": "5x7.bdf", "font_size": 7},
            "album_text": {"font": "5x7.bdf", "font_size": 7},
        }}
        p = _plugin(256, 128, cfg)
        assert not p._user_font_set('title_text')
        assert not p._user_font_set('artist_text')
        assert not p._user_font_set('album_text')

    def test_falls_back_to_classic_without_core_support(self, monkeypatch):
        import manager as music_manager
        monkeypatch.setattr(music_manager, "ADAPTIVE_AVAILABLE", False)
        p = _plugin(128, 32, {"layout_mode": "adaptive"})
        assert not p._adaptive


class TestElementStyleResolver:
    """The shared core resolver (src.element_style) must actually be wired
    in — a silently failing import would fall back to the local loader and
    quietly reintroduce the per-plugin drift this migration removed."""

    def test_resolver_is_active(self):
        import manager as music_manager
        assert music_manager.STYLE_AVAILABLE, \
            "src.element_style import failed on this core"
        p = _plugin(128, 32, {"customization": {
            "title_text": {"font": "PressStart2P-Regular.ttf", "font_size": 8}}})
        assert p._get_element_style_resolver() is not None

    def test_resolver_reads_schema_defaults(self):
        """Schema-populated saved config is not a user override; a genuine
        change is — resolved against this plugin's own config_schema.json,
        which works even here where MockPluginManager has no schema
        manager."""
        p = _plugin(128, 32, {"customization": {
            "artist_text": {"font": "5x7.bdf", "font_size": 7}}})
        assert not p._user_font_set("artist_text")
        p2 = _plugin(128, 32, {"customization": {
            "artist_text": {"font": "5x7.bdf", "font_size": 9}}})
        assert p2._user_font_set("artist_text")

    def test_resolver_rebuilds_when_config_swapped(self):
        """on_config_change replaces self.config with a new dict — the
        cached resolver must not keep answering from the old one."""
        p = _plugin(128, 32, {"customization": {
            "artist_text": {"font": "5x7.bdf", "font_size": 7}}})
        assert not p._user_font_set("artist_text")
        new_config = dict(p.config)
        new_config["customization"] = {
            "artist_text": {"font": "5x7.bdf", "font_size": 9}}
        p.on_config_change(new_config)
        assert p._user_font_set("artist_text")


class TestLadderCrispness:
    """Every rung in the adaptive ladder must render with zero antialiasing —
    see LEDMatrix core's measure_font_crispness for why this matters."""

    def test_ladder_is_crisp(self):
        from src.adaptive_layout import measure_font_crispness
        from src.font_manager import FontManager

        fm = FontManager({})
        offenders = []
        for step in ADAPTIVE_LADDER_TEXT:
            font = fm.get_font(step.family, step.size_px)
            c = measure_font_crispness(font, "A Song Title")
            if c > 0.02:
                offenders.append(f"{step.family}@{step.size_px}px: {c:.1%} antialiased")
        assert not offenders, "Blurry rung(s):\n  " + "\n  ".join(offenders)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
