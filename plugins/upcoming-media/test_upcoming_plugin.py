"""
Plugin behaviour for upcoming-media: renders stay inside the panel for every
toggle combination, display() never fetches, settings apply live, modes with
nothing to show are skipped, and Vegas/scroll/switch hand the core what it
expects. Needs the LEDMatrix core on PYTHONPATH (scripts/run_plugin_tests.py
--core sets it).

Run: pytest plugins/upcoming-media/test_upcoming_plugin.py
"""

import copy
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from src.plugin_system.testing import MockCacheManager, MockDisplayManager, MockPluginManager
except ImportError:  # pragma: no cover
    print("SKIP: LEDMatrix core not on PYTHONPATH")
    pytest.skip("LEDMatrix core not on PYTHONPATH", allow_module_level=True)

from PIL import Image  # noqa: E402

import manager as plugin_module  # noqa: E402
from manager import MODE_EPISODES, MODE_MOVIES, UpcomingMediaPlugin  # noqa: E402
from upcoming_media_sources import UpcomingItem  # noqa: E402

FIXTURES = json.loads((HERE / "test" / "fixtures" / "mock.json").read_text())
NOW = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)
SIZES = [(64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32), (128, 96), (256, 128)]
BASE = {
    "enabled": True,
    "sonarr_url": "http://127.0.0.1:9", "sonarr_api_key": "k",
    "radarr_url": "http://127.0.0.1:9", "radarr_api_key": "k",
    "marquee_enabled": False,
}


def make(config=None, size=(128, 32), seed=True):
    cache = MockCacheManager()
    if seed:
        for key, value in FIXTURES.items():
            cache.set(key, copy.deepcopy(value))
    dm = MockDisplayManager(width=size[0], height=size[1])
    cfg = dict(BASE)
    cfg.update(config or {})
    plugin = UpcomingMediaPlugin("upcoming-media", cfg, dm, cache, MockPluginManager())
    plugin._now = lambda: NOW
    return plugin, dm


@pytest.fixture(autouse=True)
def no_network():
    """Any request is a bug here: data and art come from the seeded cache."""
    def boom(*args, **kwargs):
        raise AssertionError(f"network call: {args} {kwargs}")
    with mock.patch("upcoming_media_sources.requests.get", side_effect=boom) as get:
        yield
    # update() swallows exceptions, so check the call count too.
    assert not get.called, f"network call: {get.call_args_list}"


def test_update_reads_the_cache_and_selects_the_week():
    plugin, _ = make()
    plugin.update()
    eps = plugin._items[MODE_EPISODES]
    movies = plugin._items[MODE_MOVIES]
    assert [i.title for i in eps][:2] == ["The Quiet Harbor", "Starfall Station"]
    assert {(m.title, m.release_label) for m in movies} == {
        ("Glass Meridian", "Digital"), ("The Orchard Kings", "In Theaters")}
    # artwork came out of the cache, not the network
    assert plugin.images.has(eps[0].images["poster"])


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("toggles", list(itertools.product(
    ["auto", "logo", "poster", "none"], ["compact", "long"], [True, False], [True, False])))
def test_cards_fit_the_panel(size, toggles):
    image_type, ep_format, show_desc, show_name = toggles
    plugin, _ = make({"image_type": image_type, "episode_format": ep_format,
                      "show_description": show_desc, "show_episode_title": show_name}, size)
    plugin.update()
    for mode in (MODE_EPISODES, MODE_MOVIES):
        for item in plugin._items[mode]:
            card, _ = plugin.renderer.render_card(item, *size, NOW, timezone.utc)
            assert card.size == size
            strip_card, _ = plugin.renderer.render_card(item, *size, NOW, timezone.utc, strip=True)
            assert strip_card.height == size[1]
            assert 8 <= strip_card.width <= max(size[0], 192) + size[1] * 3 + 4


@pytest.mark.parametrize("size", SIZES)
def test_display_draws_both_modes_in_switch_and_scroll(size):
    for display_mode in ("switch", "scroll"):
        plugin, dm = make({"display_mode": display_mode}, size)
        plugin.update()
        for mode in (MODE_EPISODES, MODE_MOVIES):
            assert plugin.display(display_mode=mode, force_clear=True) is True
            for _ in range(5):
                plugin.display(display_mode=mode)
            assert dm.image.size == size


def test_first_display_does_not_fetch():
    plugin, dm = make(seed=False)
    with mock.patch.object(plugin.sonarr, "fetch_raw", side_effect=AssertionError("fetch")):
        assert plugin.display(display_mode=MODE_EPISODES, force_clear=True) is True
    assert plugin._fetched[MODE_EPISODES] is False


def test_unconfigured_shows_setup_on_episodes_and_skips_movies():
    plugin, _ = make({"sonarr_url": "", "radarr_url": ""})
    plugin.update()
    assert plugin.display(display_mode=MODE_EPISODES, force_clear=True) is True
    assert plugin.display(display_mode=MODE_MOVIES, force_clear=True) is False


def test_only_radarr_skips_episodes():
    plugin, _ = make({"sonarr_url": ""})
    plugin.update()
    assert plugin.display(display_mode=MODE_EPISODES, force_clear=True) is False
    assert plugin.display(display_mode=MODE_MOVIES, force_clear=True) is True


def test_empty_window_is_skipped_unless_asked():
    plugin, _ = make({"days_ahead": 0, "include_aired_today": False, "max_items": 1})
    plugin._items[MODE_MOVIES] = []
    plugin._fetched[MODE_MOVIES] = True
    assert plugin.display(display_mode=MODE_MOVIES, force_clear=True) is False
    plugin.on_config_change(dict(BASE, show_empty_message=True))
    plugin._fetched[MODE_MOVIES] = True
    assert plugin.display(display_mode=MODE_MOVIES, force_clear=True) is True


def test_fetch_error_keeps_last_good_list():
    plugin, _ = make()
    plugin.update()
    before = [i.uid for i in plugin._items[MODE_EPISODES]]
    plugin.cache_manager.reset()
    from upcoming_media_sources import SourceError
    with mock.patch.object(plugin.sonarr, "fetch_raw", side_effect=SourceError("Sonarr: offline")), \
            mock.patch.object(plugin.radarr, "fetch_raw", side_effect=SourceError("Radarr: offline")):
        plugin.update()
    assert [i.uid for i in plugin._items[MODE_EPISODES]] == before
    assert plugin._errors[MODE_EPISODES] == "Sonarr: offline"


def test_config_change_applies_without_restart():
    plugin, _ = make()
    plugin.update()
    assert plugin.render_settings.episode_format == "compact"
    plugin.on_config_change(dict(BASE, episode_format="long", display_mode="scroll",
                                 customization={"date_text": {"text_color": [1, 2, 3]}}))
    assert plugin.render_settings.episode_format == "long"
    assert plugin.render_settings.colors["date"] == (1, 2, 3)
    assert plugin.enable_scrolling and plugin.needs_high_fps
    assert plugin._fetched[MODE_EPISODES] is False  # refetch on next update()


def test_jellyfin_used_when_sonarr_missing():
    plugin, _ = make({"sonarr_url": "", "jellyfin_url": "http://jf", "jellyfin_api_key": "x"})
    assert plugin._episode_source() is plugin.jellyfin
    plugin, _ = make({"jellyfin_url": "http://jf", "jellyfin_api_key": "x"})
    assert plugin._episode_source() is plugin.sonarr
    plugin, _ = make({"episode_source": "jellyfin", "jellyfin_url": "http://jf", "jellyfin_api_key": "x"})
    assert plugin._episode_source() is plugin.jellyfin


def test_vegas_content_is_a_list_of_cards():
    plugin, _ = make(size=(128, 32))
    plugin.update()
    cards = plugin.get_vegas_content()
    assert isinstance(cards, list) and len(cards) == 6
    assert all(isinstance(c, Image.Image) and c.height == 32 for c in cards)
    assert plugin.get_vegas_content_type() == "multi"


def test_switch_cycle_duration_and_completion():
    plugin, _ = make({"switch_duration": 5})
    plugin.update()
    count = len(plugin._items[MODE_EPISODES])
    assert plugin.get_cycle_duration(display_mode=MODE_EPISODES) == count * 5
    clock = [1000.0]
    with mock.patch.object(plugin_module.time, "time", lambda: clock[0]):
        plugin.display(display_mode=MODE_EPISODES, force_clear=True)
        assert not plugin.is_cycle_complete()
        for _ in range(count):
            clock[0] += 5
            plugin.display(display_mode=MODE_EPISODES)
        assert plugin.is_cycle_complete()


def test_scroll_mode_reports_a_duration():
    plugin, _ = make({"display_mode": "scroll"})
    plugin.update()
    plugin.display(display_mode=MODE_EPISODES, force_clear=True)
    duration = plugin.get_cycle_duration(display_mode=MODE_EPISODES)
    assert duration is not None and 15 <= duration <= 180


def test_scrolling_title_holds_its_card_until_one_full_pass():
    plugin, _ = make({"marquee_enabled": True, "switch_duration": 5}, size=(64, 32))
    plugin.update()
    items = plugin._items[MODE_EPISODES]
    holds = [plugin._hold(i) for i in items]
    assert all(5 <= h <= 15 for h in holds)
    long_ones = [h for h in holds if h > 5]
    assert long_ones, "a 64-wide panel should have at least one scrolling title"
    assert plugin.get_cycle_duration(display_mode=MODE_EPISODES) == pytest.approx(sum(holds))
    assert plugin.get_dynamic_duration_cap() == pytest.approx(sum(holds))

    # The card stays past switch_duration while its title is still moving.
    first = holds[0]
    clock = [1000.0]
    with mock.patch.object(plugin_module.time, "time", lambda: clock[0]):
        plugin.display(display_mode=MODE_EPISODES, force_clear=True)
        clock[0] += first - 0.1
        plugin.display(display_mode=MODE_EPISODES)
        assert plugin._switch[MODE_EPISODES]["index"] == 0
        clock[0] += 0.2
        plugin.display(display_mode=MODE_EPISODES)
        assert plugin._switch[MODE_EPISODES]["index"] == 1


def test_marquee_off_keeps_fixed_card_time():
    plugin, _ = make({"marquee_enabled": False, "switch_duration": 5}, size=(64, 32))
    plugin.update()
    assert {plugin._hold(i) for i in plugin._items[MODE_EPISODES]} == {5}


def test_unreadable_logo_falls_back_to_poster():
    plugin, _ = make(size=(128, 64))
    plugin.update()
    item = next(i for i in plugin._items[MODE_EPISODES]
                if i.images.get("logo") and i.images.get("poster"))
    plugin.images.put(item.images["logo"], Image.new("RGBA", (200, 60), (0, 0, 0, 255)))
    plugin.images.put(item.images["poster"], Image.new("RGBA", (40, 60), (200, 40, 40, 255)))
    plugin.images._fitted.clear()
    with mock.patch.object(plugin.images, "fitted", wraps=plugin.images.fitted) as fitted:
        card, _ = plugin.renderer.render_card(item, 128, 64, NOW, timezone.utc)
    used = [c.args[0] for c in fitted.call_args_list]
    assert used[-1] == item.images["poster"]
    assert card.size == (128, 64)


def test_poster_only_on_square_panel_also_loads_the_logo():
    plugin, _ = make({"image_type": "poster"}, size=(64, 64))
    assert not plugin._poster_usable()
    calls = []
    with mock.patch.object(plugin.images, "prefetch", side_effect=lambda url, h=None: calls.append(url) or True):
        item = UpcomingItem(kind="episode", uid="u", group_id="g", title="T", when=NOW, has_time=True,
                            images={"poster": "http://h/p.jpg", "logo": "http://h/l.png"})
        kept = plugin._prefetch_images(item)
    assert kept == ["http://h/p.jpg", "http://h/l.png"]
    plugin2, _ = make({"image_type": "poster"}, size=(128, 32))
    with mock.patch.object(plugin2.images, "prefetch", return_value=True):
        assert plugin2._prefetch_images(item) == ["http://h/p.jpg"]


def test_metadata_change_with_same_uid_redraws():
    plugin, _ = make()
    plugin.update()
    version = plugin._data_version
    plugin.update()
    assert plugin._data_version == version            # nothing changed
    raw_key = plugin.sonarr.cache_key(plugin.days_ahead)
    payload = copy.deepcopy(plugin.cache_manager.get(raw_key))
    payload[0]["title"] = "A Renamed Episode"
    plugin.cache_manager.set(raw_key, payload)
    plugin.update()
    assert plugin._data_version == version + 1


def test_static_card_redraws_at_local_midnight():
    plugin, dm = make({"max_items": 1}, size=(128, 32))
    plugin.update()
    plugin.display(display_mode=MODE_EPISODES, force_clear=True)
    sig = plugin._switch[MODE_EPISODES]["frame_sig"]
    plugin._now = lambda: NOW.replace(day=NOW.day + 1)
    plugin.display(display_mode=MODE_EPISODES)
    assert plugin._switch[MODE_EPISODES]["frame_sig"] != sig


def test_calendar_cache_key_differs_per_server():
    a, _ = make({"sonarr_url": "http://a:8989"})
    b, _ = make({"sonarr_url": "http://b:8989"})
    assert a.sonarr.cache_key(7) != b.sonarr.cache_key(7)


def test_wide_padded_range_never_clips_on_a_narrow_panel():
    plugin, _ = make({"episode_format": "padded", "image_type": "none"}, size=(64, 32))
    plugin.update()
    item = copy.deepcopy(plugin._items[MODE_EPISODES][0])
    item.season, item.episode, item.episode_end, item.episode_count = 1, 100, 102, 3
    font = plugin.renderer.font("episode", "small")
    line = plugin.renderer._num_line(item, font, 62, separate_name=True)
    assert line == "S1E100-102"
    assert plugin.renderer.text_width(line, font) <= 62
