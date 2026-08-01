"""
Tests for JellyfinNowPlayingPlugin._content_width.

The progress bar used to span the whole text area, which made the rendered frame
full-width whatever the title length — on a 512px panel a short episode name left
a bar stretching across the display. A bar is drawn pixels, so a ticker cannot
trim it back; it has to be narrower in the first place.

The safety harness cannot cover this: without a reachable Jellyfin server there
is no session, so the now-playing frame is never rendered.
"""

import sys
import types

import pytest

# The plugin imports BasePlugin from the core, which is not on the path here.
if 'src' not in sys.modules:
    src = types.ModuleType('src')
    plugin_system = types.ModuleType('src.plugin_system')
    base_plugin = types.ModuleType('src.plugin_system.base_plugin')

    class _BasePlugin:
        def __init__(self, *args, **kwargs):
            pass

    base_plugin.BasePlugin = _BasePlugin
    plugin_system.base_plugin = base_plugin
    src.plugin_system = plugin_system
    sys.modules['src'] = src
    sys.modules['src.plugin_system'] = plugin_system
    sys.modules['src.plugin_system.base_plugin'] = base_plugin

TEXT_AREA = 300
TITLE_FONT = object()
SUBTITLE_FONT = object()


def make_plugin(title='', subtitle='', config=None, px_per_char=6, fail=False):
    """A plugin shell with a no-op __init__; only the sizing logic is exercised."""
    from manager import JellyfinNowPlayingPlugin

    class _Shell(JellyfinNowPlayingPlugin):
        def __init__(self):
            pass

        def _text_width(self, text, font):
            if fail:
                raise RuntimeError("font unavailable")
            return len(text) * px_per_char

    plugin = _Shell()
    plugin.config = config if config is not None else {}
    plugin.title_font = TITLE_FONT
    plugin.subtitle_font = SUBTITLE_FONT
    plugin.now_playing = {'title': title, 'subtitle': subtitle}
    return plugin


class TestContentWidth:
    def test_matches_the_widest_line(self):
        # subtitle is longer: 12 chars -> 72px
        plugin = make_plugin(title='Ep 1', subtitle='Season Three')
        assert plugin._content_width(TEXT_AREA) == 72

    def test_short_title_no_longer_spans_the_area(self):
        plugin = make_plugin(title='Up', subtitle='')
        width = plugin._content_width(TEXT_AREA)
        assert width < TEXT_AREA
        assert width == 24  # the floor

    def test_never_exceeds_the_available_area(self):
        plugin = make_plugin(title='x' * 200, subtitle='y' * 200)
        assert plugin._content_width(TEXT_AREA) == TEXT_AREA

    def test_marqueed_title_pins_the_bar_to_full_width(self):
        # A title long enough to scroll genuinely fills the area.
        plugin = make_plugin(title='z' * 60, subtitle='')
        assert plugin._content_width(TEXT_AREA) == TEXT_AREA

    def test_floor_cannot_exceed_a_narrow_area(self):
        plugin = make_plugin(title='A', subtitle='')
        assert plugin._content_width(10) == 10

    def test_empty_strings_fall_back_to_the_area(self):
        plugin = make_plugin(title='', subtitle='')
        assert plugin._content_width(TEXT_AREA) == TEXT_AREA

    def test_missing_session_does_not_raise(self):
        plugin = make_plugin()
        plugin.now_playing = None
        assert plugin._content_width(TEXT_AREA) == TEXT_AREA

    def test_disabled_by_config_restores_full_width(self):
        plugin = make_plugin(title='Up', config={'progress_bar_match_text': False})
        assert plugin._content_width(TEXT_AREA) == TEXT_AREA

    def test_enabled_by_default(self):
        plugin = make_plugin(title='Up', config={})
        assert plugin._content_width(TEXT_AREA) < TEXT_AREA

    def test_measurement_failure_keeps_the_bar(self):
        # Losing the bar entirely would be worse than an over-wide one.
        plugin = make_plugin(title='Something', fail=True)
        assert plugin._content_width(TEXT_AREA) == TEXT_AREA

    def test_subtitle_alone_is_enough(self):
        plugin = make_plugin(title='', subtitle='A Longer Subtitle')
        assert plugin._content_width(TEXT_AREA) == len('A Longer Subtitle') * 6

    @pytest.mark.parametrize('area', [1, 24, 25, 128, 512])
    def test_result_always_within_bounds(self, area):
        plugin = make_plugin(title='Some Episode Title', subtitle='Series')
        width = plugin._content_width(area)
        assert 1 <= width <= area
