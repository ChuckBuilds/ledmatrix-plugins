"""
Tests for news ticker headline paging and dynamic-duration hooks.

Run from a LEDMatrix (core) checkout with this plugin directory importable:

    PYTHONPATH=/path/to/LEDMatrix python -m pytest plugins/news/test_headline_paging.py
"""

import os
import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from manager import NewsTickerPlugin
except ImportError:  # pragma: no cover - needs the core repo on PYTHONPATH
    pytest.skip("LEDMatrix core not importable", allow_module_level=True)


class FakeDisplayManager:
    def __init__(self, width=128, height=32):
        self.width = width
        self.height = height
        self.image = Image.new("RGB", (width, height))

    def set_scrolling_state(self, _state):
        pass

    def process_deferred_updates(self):
        pass

    def update_display(self):
        pass


class FakeCacheManager:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


class FakePluginManager:
    """Plugin manager whose config_manager exposes a core dynamic-duration cap."""

    def __init__(self, core_cap=None):
        self.font_manager = None
        payload = {"display": {}}
        if core_cap is not None:
            payload["display"]["dynamic_duration"] = {"max_duration_seconds": core_cap}
        self.config_manager = types.SimpleNamespace(
            load_config=lambda: payload,
            save_config=lambda _cfg: None,
        )


def make_plugin(config=None, width=128, core_cap=1000):
    base = {
        "enabled": True,
        "global": {
            "dynamic_duration": {
                "enabled": True,
                "min_duration_seconds": 30,
                "max_duration_seconds": 300,
                "buffer_ratio": 0.1,
            },
            # 1 px/frame at 0.01 s/frame == 100 px/s
            "display": {"scroll_speed": 1.0, "scroll_delay": 0.01},
        },
        "feeds": {"enabled_feeds": [], "custom_feeds": [], "show_logos": False},
    }
    if config:
        for section, values in config.items():
            base.setdefault(section, {})
            if isinstance(values, dict):
                base[section].update(values)
            else:
                base[section] = values

    return NewsTickerPlugin(
        "news",
        base,
        FakeDisplayManager(width=width),
        FakeCacheManager(),
        FakePluginManager(core_cap=core_cap),
    )


def headlines(count, title_length=40):
    return [
        {
            "feed_name": "TEST",
            "title": f"H{i:02d} " + ("x" * title_length),
            "description": "",
            "published": "",
            "link": "",
        }
        for i in range(count)
    ]


def test_supports_dynamic_duration_reads_global_block():
    """Regression: BasePlugin looks at a top-level key this plugin never used."""
    assert make_plugin().supports_dynamic_duration() is True
    off = make_plugin({"global": {"dynamic_duration": {"enabled": False}}})
    assert off.supports_dynamic_duration() is False
    # With no pacing signal the controller must not be left waiting.
    assert off.is_cycle_complete() is True


def test_dynamic_duration_cap_includes_overrun_slack():
    """The controller takes min(cycle duration, cap), so the cap must not clip
    the slack that lets a slow-running scroll reach the end."""
    plugin = make_plugin()
    assert plugin.get_dynamic_duration_cap() == pytest.approx(300.0 * 1.25)


def test_page_duration_never_exceeds_the_enforced_ceiling():
    """A page must be scrollable end to end within the wall the controller
    enforces, including the ScrollHelper's own max_duration clamp."""
    plugin = make_plugin({"global": {"dynamic_duration": {"max_duration_seconds": 60}}})
    plugin.current_headlines = headlines(60)
    plugin._create_scrolling_image()

    calculated = plugin.scroll_helper.get_dynamic_duration()
    assert calculated < 60, "page must fit without ScrollHelper clamping its estimate"

    ceiling = min(plugin.get_dynamic_duration_cap(), plugin._read_core_duration_cap())
    assert plugin.get_cycle_duration() <= ceiling


def test_cycle_duration_none_before_a_strip_exists():
    plugin = make_plugin()
    assert plugin.get_cycle_duration() is None
    # And the duration floor falls back to the configured value rather than
    # ScrollHelper's 60s placeholder.
    assert plugin.get_display_duration() == 30.0


def test_cycle_duration_carries_overrun_slack():
    plugin = make_plugin()
    plugin.current_headlines = headlines(4)
    plugin._create_scrolling_image()

    scroll_duration = plugin.scroll_helper.get_dynamic_duration()
    assert scroll_duration > 0
    assert plugin.get_cycle_duration() == pytest.approx(scroll_duration * 1.25)


def test_page_fits_inside_the_duration_budget():
    """A page must be scrollable end to end within the enforced cap."""
    plugin = make_plugin({"global": {"dynamic_duration": {"max_duration_seconds": 60}}})
    plugin.current_headlines = headlines(40)

    images, count = plugin._build_page_images()
    assert 0 < count < 40, "long lists must be split, not shown in one strip"

    budget = plugin._page_width_budget()
    width = plugin.display_width + sum(
        img.width + plugin.ELEMENT_GAP + (plugin.ITEM_GAP if i else 0)
        for i, img in enumerate(images)
    )
    assert width <= budget


def test_paging_covers_every_headline_without_gaps():
    plugin = make_plugin({"global": {"dynamic_duration": {"max_duration_seconds": 60}}})
    total = 25
    plugin.current_headlines = headlines(total)

    seen = []
    for _ in range(20):
        images, count = plugin._build_page_images()
        assert images, "every page must carry at least one headline"
        plugin._page_count = count
        seen.extend(
            plugin.current_headlines[(plugin._page_start + i) % total]["title"]
            for i in range(count)
        )
        plugin._advance_page()
        if len(seen) >= total:
            break

    assert seen[:total] == [h["title"] for h in headlines(total)], (
        "pages must walk the list in order, with no headline skipped or repeated"
    )


def test_single_oversized_headline_still_gets_a_page():
    plugin = make_plugin({"global": {"dynamic_duration": {"max_duration_seconds": 30}}})
    plugin.current_headlines = headlines(3, title_length=4000)

    images, count = plugin._build_page_images()
    assert len(images) == 1
    assert count == 1


def test_paging_disabled_puts_everything_in_one_strip():
    plugin = make_plugin({"global": {"headline_paging": {"enabled": False}}})
    plugin.current_headlines = headlines(30)

    assert plugin._page_width_budget() is None
    _images, count = plugin._build_page_images()
    assert count == 30


def test_max_headlines_per_page_is_honoured():
    plugin = make_plugin({"global": {"headline_paging": {"max_headlines_per_page": 3}}})
    plugin.current_headlines = headlines(30)

    images, count = plugin._build_page_images()
    assert len(images) == 3
    assert count == 3


def test_reset_cycle_state_renders_the_queued_page():
    plugin = make_plugin({"global": {"dynamic_duration": {"max_duration_seconds": 60}}})
    plugin.current_headlines = headlines(20)
    plugin._create_scrolling_image()

    first_start = plugin._page_start
    plugin._on_scroll_cycle_complete()
    assert plugin._page_dirty is True
    assert plugin._page_start != first_start

    plugin.reset_cycle_state()
    assert plugin._page_dirty is False
    assert plugin._cycle_complete is False
    assert plugin.scroll_helper.cached_image is not None, "queued page is rendered"
    assert plugin.scroll_helper.scroll_position == 0


def test_parked_page_rolls_over_when_the_controller_never_resets():
    """News as the only display mode: reset_cycle_state() is never called, so
    display() itself has to move on instead of freezing on the last frame."""
    plugin = make_plugin(
        {"global": {"headline_paging": {"max_headlines_per_page": 2, "page_hold_seconds": 0.0}}}
    )
    plugin.current_headlines = headlines(10)
    plugin.display(display_mode="news_ticker")
    first_start = plugin._page_start

    # Run the strip to the end of its travel.
    plugin.scroll_helper.total_distance_scrolled = plugin.scroll_helper.total_scroll_width
    plugin.display(display_mode="news_ticker")
    assert plugin._cycle_complete is True
    assert plugin._page_dirty is True

    # Hold expired: roll onto the queued page without waiting to be reset.
    plugin.display(display_mode="news_ticker")
    assert plugin._page_dirty is False
    assert plugin._cycle_complete is False
    assert plugin._page_start == (first_start + 2) % 10
    assert plugin.scroll_helper.cached_image is not None, "no blank frame on the swap"


def test_refresh_keeps_the_page_position():
    """Rewinding on every refresh is what kept the tail from ever showing."""
    from datetime import datetime

    plugin = make_plugin(
        {
            "feeds": {
                "enabled_feeds": [],
                "custom_feeds": [{"name": "TEST", "url": "https://example.com/rss"}],
                "show_logos": False,
            }
        }
    )
    # Serve the refresh from cache so update() rebuilds headlines without network.
    cache_key = f"news_TEST_{datetime.now().strftime('%Y%m%d%H')}"
    plugin.cache_manager.set(cache_key, headlines(20))
    plugin.headlines_per_feed = 20

    plugin._page_start = 12
    plugin.update()

    assert len(plugin.current_headlines) == 20
    assert plugin._page_start == 12, "a data refresh must not rewind to the first headline"
