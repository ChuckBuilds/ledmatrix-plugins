"""
Tests for MusicPlugin._progress_bar_width.

The safety harness cannot cover this: its mock track has no duration, so the
progress bar is never drawn and the rendered extent is identical with and
without the change. These exercise the sizing rule directly.
"""

import sys
import types

import pytest

# The plugin imports BasePlugin from the core, which is not on the path here.
# Stub just enough for the module to import, then test the method unbound.
if 'src' not in sys.modules:
    src = types.ModuleType('src')
    plugin_system = types.ModuleType('src.plugin_system')
    base_plugin = types.ModuleType('src.plugin_system.base_plugin')

    class _BasePlugin:  # minimal stand-in
        def __init__(self, *args, **kwargs):
            pass

    base_plugin.BasePlugin = _BasePlugin
    base_plugin.VegasDisplayMode = None
    plugin_system.base_plugin = base_plugin
    src.plugin_system = plugin_system
    sys.modules['src'] = src
    sys.modules['src.plugin_system'] = plugin_system
    sys.modules['src.plugin_system.base_plugin'] = base_plugin


class FakeDisplayManager:
    """Reports text width as a fixed number of pixels per character."""

    def __init__(self, px_per_char=6, fail=False):
        self.px_per_char = px_per_char
        self.fail = fail

    def get_text_width(self, text, font=None):
        if self.fail:
            raise RuntimeError("font unavailable")
        return len(text) * self.px_per_char


class FakeLogger:
    def debug(self, *a, **k):
        pass


def make_plugin(config=None, px_per_char=6, fail=False):
    """Build a MusicPlugin shell without running its real __init__.

    The real __init__ starts polling threads and API clients; the progress-bar
    sizing needs none of that. Subclassing with an empty __init__ is clearer
    than __new__ gymnastics and keeps static analysis happy.
    """
    from manager import MusicPlugin

    class _Shell(MusicPlugin):
        def __init__(self):
            pass

    plugin = _Shell()
    plugin.config = config if config is not None else {}
    plugin.display_manager = FakeDisplayManager(px_per_char, fail)
    plugin.logger = FakeLogger()
    return plugin


TEXT_AREA = 400
FONT = object()


class TestProgressBarWidth:
    def test_matches_the_widest_line(self):
        plugin = make_plugin()
        # artist is longest at 10 chars -> 60px
        width = plugin._progress_bar_width(TEXT_AREA, [
            ('Song', FONT),          # 24px
            ('An Artist', FONT),     # 54px
            ('Alb', FONT),           # 18px
        ])
        assert width == 54

    def test_short_title_no_longer_spans_the_panel(self):
        # The reported problem: a few characters left a bar across the display.
        plugin = make_plugin()
        width = plugin._progress_bar_width(TEXT_AREA, [('Hey', FONT), ('Yo', FONT), None])
        assert width < TEXT_AREA
        assert width == 24  # the MIN_PROGRESS_BAR_WIDTH floor

    def test_never_exceeds_the_text_area(self):
        plugin = make_plugin()
        # 200 chars would measure 1200px, far beyond the area.
        width = plugin._progress_bar_width(TEXT_AREA, [('x' * 200, FONT)])
        assert width == TEXT_AREA

    def test_scrolling_line_pins_the_bar_to_full_width(self):
        # A line long enough to scroll genuinely fills the width, so a
        # full-width bar is correct there.
        plugin = make_plugin()
        assert plugin._progress_bar_width(TEXT_AREA, [('y' * 80, FONT)]) == TEXT_AREA

    def test_floor_is_applied(self):
        plugin = make_plugin()
        assert plugin._progress_bar_width(TEXT_AREA, [('a', FONT)]) == 24

    def test_floor_cannot_exceed_a_narrow_text_area(self):
        plugin = make_plugin()
        assert plugin._progress_bar_width(10, [('a', FONT)]) == 10

    def test_hidden_album_line_is_ignored(self):
        plugin = make_plugin()
        with_album = plugin._progress_bar_width(
            TEXT_AREA, [('Song', FONT), ('Art', FONT), ('A Very Long Album', FONT)])
        without_album = plugin._progress_bar_width(
            TEXT_AREA, [('Song', FONT), ('Art', FONT), None])
        assert with_album > without_album

    def test_empty_strings_are_skipped(self):
        plugin = make_plugin()
        assert plugin._progress_bar_width(
            TEXT_AREA, [('', FONT), ('Four', FONT), None]) == 24

    def test_all_lines_empty_falls_back_to_full_area(self):
        plugin = make_plugin()
        assert plugin._progress_bar_width(TEXT_AREA, [('', FONT), None]) == TEXT_AREA

    def test_disabled_by_config_restores_full_width(self):
        plugin = make_plugin(config={'progress_bar_match_text': False})
        assert plugin._progress_bar_width(TEXT_AREA, [('Hey', FONT)]) == TEXT_AREA

    def test_enabled_by_default(self):
        plugin = make_plugin(config={})
        assert plugin._progress_bar_width(TEXT_AREA, [('Hey', FONT)]) < TEXT_AREA

    def test_font_measurement_failure_keeps_the_bar(self):
        # Losing the bar entirely would be worse than an over-wide one.
        plugin = make_plugin(fail=True)
        assert plugin._progress_bar_width(TEXT_AREA, [('Song', FONT)]) == TEXT_AREA

    @pytest.mark.parametrize('area', [1, 24, 25, 100, 512])
    def test_result_always_within_bounds(self, area):
        plugin = make_plugin()
        width = plugin._progress_bar_width(area, [('Some Title', FONT)])
        assert 1 <= width <= area
