"""
Tests that Vegas map content matches the rotation's map view.

get_vegas_content() used to reimplement a cut-down map: background plus
aircraft dots only, so trails, the centre position marker and the aircraft
count were silently missing from the ticker even with show_trails enabled.
Both paths now share _render_map_image(); these tests pin that so the
duplication cannot creep back.
"""

import sys
import types

import pytest
from PIL import Image, ImageFont

# The plugin imports BasePlugin from the core, which is not on the path here.
if 'src' not in sys.modules:
    src = types.ModuleType('src')
    plugin_system = types.ModuleType('src.plugin_system')
    base_plugin = types.ModuleType('src.plugin_system.base_plugin')

    class _BasePlugin:
        def __init__(self, *args, **kwargs):
            pass

    base_plugin.BasePlugin = _BasePlugin
    base_plugin.VegasDisplayMode = None
    plugin_system.base_plugin = base_plugin
    src.plugin_system = plugin_system
    sys.modules['src'] = src
    sys.modules['src.plugin_system'] = plugin_system
    sys.modules['src.plugin_system.base_plugin'] = base_plugin

W, H = 128, 64
CENTER_LAT, CENTER_LON = 28.0, -82.0


class FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass

    # The plugin guards expensive debug formatting behind isEnabledFor, which
    # every real logger has. Reporting False keeps that formatting out of the
    # test, and stops the guard raising AttributeError on a stand-in that only
    # implemented the three methods it happened to need at the time.
    def isEnabledFor(self, level):
        return False


class FakeDisplayManager:
    def __init__(self, width=W, height=H):
        self.matrix = types.SimpleNamespace(width=width, height=height)
        self.image = Image.new('RGB', (width, height))
        self.updated = False

    def update_display(self):
        self.updated = True

    def clear(self):
        self.image = Image.new('RGB', (self.matrix.width, self.matrix.height))


def _plugin_shell():
    """A FlightTrackerPlugin whose __init__ is a no-op.

    The real __init__ builds fetchers, threads and caches; the map renderer
    needs none of that. Subclassing with an empty __init__ is clearer than
    __new__ gymnastics and keeps static analysis happy.
    """
    from manager import FlightTrackerPlugin

    class _Shell(FlightTrackerPlugin):
        def __init__(self):
            pass

    return _Shell()


def make_plugin(show_trails=True, aircraft=None, trails=None, width=W, height=H):
    """Build a plugin shell with just the state the map renderer touches."""
    p = _plugin_shell()
    dm = FakeDisplayManager(width, height)
    p._display_manager_ref = dm
    p.display_manager = dm
    p.logger = FakeLogger()

    p.center_lat = CENTER_LAT
    p.center_lon = CENTER_LON
    p.map_radius_miles = 10
    p.zoom_factor = 1.0
    p.show_trails = show_trails
    p.trail_length = 10
    p.bounds_warning_cache = {}
    p.bounds_warning_interval = 60

    # Disable the map background so the renderer takes the deterministic
    # solid-black path — no network, no tile cache.
    p.map_bg_enabled = False
    p.disable_on_cache_error = False
    p.cache_error_count = 0
    p.max_cache_errors = 5

    p.aircraft_data = aircraft if aircraft is not None else {}
    p.aircraft_trails = trails if trails is not None else {}

    # Real font so the count overlay can measure and draw.
    p.fonts = {'small': ImageFont.load_default()}
    return p


def near(lat_offset=0.0, lon_offset=0.0):
    return CENTER_LAT + lat_offset, CENTER_LON + lon_offset


def one_aircraft():
    lat, lon = near(0.02, 0.02)
    return {'ABC123': {'lat': lat, 'lon': lon, 'color': (0, 200, 0)}}


def one_trail():
    return {
        'ABC123': [
            (CENTER_LAT + 0.005 * i, CENTER_LON + 0.005 * i, 1000.0 + i)
            for i in range(6)
        ]
    }


def lit_pixels(img):
    """Count pixels with any channel above the noise floor.

    Uses tobytes() rather than getdata(), which Pillow deprecates.
    """
    raw = img.convert('RGB').tobytes()
    return sum(
        1 for i in range(0, len(raw), 3)
        if raw[i] > 10 or raw[i + 1] > 10 or raw[i + 2] > 10
    )


class TestRenderMapImage:
    def test_returns_an_image_at_display_size(self):
        img = make_plugin()._render_map_image()
        assert img.size == (W, H)

    def test_centre_marker_is_drawn(self):
        # The white dot at our own lat/lon; Vegas was missing this entirely.
        img = make_plugin(show_trails=False)._render_map_image()
        assert img.getpixel((W // 2, H // 2)) == (255, 255, 255)

    def test_trails_add_pixels_when_enabled(self):
        on = make_plugin(True, one_aircraft(), one_trail())._render_map_image()
        off = make_plugin(False, one_aircraft(), one_trail())._render_map_image()
        assert lit_pixels(on) > lit_pixels(off)

    def test_trails_absent_when_disabled(self):
        off = make_plugin(False, one_aircraft(), one_trail())._render_map_image()
        bare = make_plugin(False, one_aircraft(), {})._render_map_image()
        assert lit_pixels(off) == lit_pixels(bare)

    def test_trail_for_untracked_aircraft_is_skipped(self):
        # A trail whose ICAO is no longer in aircraft_data must not be drawn.
        p = make_plugin(True, {}, one_trail())
        img = p._render_map_image()
        # Only the centre marker should be lit.
        assert lit_pixels(img) == 1

    def test_aircraft_dot_is_drawn(self):
        with_ac = make_plugin(False, one_aircraft(), {})._render_map_image()
        without = make_plugin(False, {}, {})._render_map_image()
        assert lit_pixels(with_ac) > lit_pixels(without)


class TestVegasMatchesRotation:
    def _vegas_map(self, plugin):
        plugin.display_mode = 'map'
        plugin.tracked_flight_data = {}
        plugin.proximity_enabled = False
        plugin.anchor_airport = None
        return plugin.get_vegas_content()

    def test_vegas_map_is_pixel_identical_to_the_rotation_view(self):
        # The whole point of the refactor: one renderer, so the ticker cannot
        # drift from the rotation again.
        rotation = make_plugin(True, one_aircraft(), one_trail())
        rotation._display_map()
        expected = rotation.display_manager.image

        vegas = make_plugin(True, one_aircraft(), one_trail())
        images = self._vegas_map(vegas)

        assert images is not None and len(images) == 1
        assert images[0].convert('RGB').tobytes() == expected.convert('RGB').tobytes()

    def test_vegas_map_includes_trails(self):
        with_trails = make_plugin(True, one_aircraft(), one_trail())
        without = make_plugin(False, one_aircraft(), one_trail())
        assert lit_pixels(self._vegas_map(with_trails)[0]) > \
            lit_pixels(self._vegas_map(without)[0])

    def test_vegas_map_includes_the_centre_marker(self):
        vegas = make_plugin(False, one_aircraft(), {})
        img = self._vegas_map(vegas)[0]
        assert img.getpixel((W // 2, H // 2)) == (255, 255, 255)

    def test_display_map_still_pushes_to_the_display(self):
        p = make_plugin(True, one_aircraft(), one_trail())
        p._display_map()
        assert p.display_manager.updated
        assert p.display_manager.image.size == (W, H)

    def test_force_clear_is_honoured(self):
        p = make_plugin(True, one_aircraft(), one_trail())
        p._display_map(force_clear=True)
        assert p.display_manager.updated


class TestNarrowerRender:
    """Vegas narrows the display manager; the projection must follow."""

    def test_map_renders_at_the_narrowed_width(self):
        p = make_plugin(True, one_aircraft(), one_trail(), width=64, height=64)
        p.display_mode = 'map'
        p.tracked_flight_data = {}
        p.proximity_enabled = False
        p.anchor_airport = None
        images = p.get_vegas_content()
        assert images[0].size == (64, 64)

    def test_centre_marker_tracks_the_narrowed_width(self):
        p = make_plugin(False, {}, {}, width=64, height=64)
        img = p._render_map_image()
        assert img.getpixel((32, 32)) == (255, 255, 255)

    @pytest.mark.parametrize("width,height", [(64, 32), (128, 32), (256, 64), (512, 64)])
    def test_renders_without_error_at_any_size(self, width, height):
        p = make_plugin(True, one_aircraft(), one_trail(), width=width, height=height)
        img = p._render_map_image()
        assert img.size == (width, height)


def enable_map_background(plugin, tmp_path):
    """Turn the tile background on with a stub tiler — no network, no disk cache.

    The composite path is what caches by size, so it has to actually run;
    _fetch_tile is the only part that would reach the network.
    """
    plugin.map_bg_enabled = True
    plugin.tile_size = 256
    plugin.tile_provider = 'osm'
    plugin.custom_tile_server = None
    plugin.tile_cache_dir = tmp_path / 'tiles'
    plugin.cache_ttl_hours = 24
    plugin.fade_intensity = 1.0
    plugin.map_brightness = 1.0
    plugin.map_contrast = 1.0
    plugin.map_saturation = 1.0
    plugin.cached_map_bgs = {}
    plugin.last_map_center = None
    plugin.last_map_zoom = None

    calls = []

    # allow_network mirrors _fetch_tile's real signature -- manager.py calls it
    # by keyword, and a three-argument stand-in raised TypeError on every path
    # that reached it. Recorded alongside the coordinates so a test can assert
    # the cache-only render never asks to open a socket.
    def fake_fetch(x, y, zoom, allow_network=True):
        calls.append((x, y, zoom, allow_network))
        # A gradient rather than a flat fill, so a wrongly-scaled crop shows up.
        tile = Image.new('RGB', (plugin.tile_size, plugin.tile_size))
        tile.putdata([
            ((i % plugin.tile_size), (i // plugin.tile_size), 128)
            for i in range(plugin.tile_size ** 2)
        ])
        return tile

    plugin._fetch_tile = fake_fetch
    return calls


class TestMapBackgroundCacheIsSizeAware:
    """The composite is cropped and resized to the display before it is cached.

    Vegas narrows the display manager, so rotation and the ticker ask for the
    same view at different widths. A memo keyed only on centre and zoom handed
    whichever path rendered second the other one's image: the wrong size, with
    aircraft and trails projected for the size it didn't get.
    """

    def test_background_matches_the_requested_size_after_a_narrower_render(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # the renderer drops debug PNGs in the cwd
        p = make_plugin(False, {}, {}, width=128, height=64)
        enable_map_background(p, tmp_path)

        wide = p._get_map_background(CENTER_LAT, CENTER_LON)
        assert wide.size == (128, 64)

        # Same centre and zoom, narrower panel — as Vegas would ask for it.
        p.display_manager.matrix.width = 64
        narrow = p._get_map_background(CENTER_LAT, CENTER_LON)
        assert narrow.size == (64, 64)

    def test_each_size_is_still_cached(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = make_plugin(False, {}, {}, width=128, height=64)
        calls = enable_map_background(p, tmp_path)

        p._get_map_background(CENTER_LAT, CENTER_LON)
        p.display_manager.matrix.width = 64
        p._get_map_background(CENTER_LAT, CENTER_LON)
        after_both = len(calls)

        # Re-asking for either size must not re-tile.
        p._get_map_background(CENTER_LAT, CENTER_LON)
        p.display_manager.matrix.width = 128
        p._get_map_background(CENTER_LAT, CENTER_LON)
        assert len(calls) == after_both

    def test_moving_the_centre_drops_every_cached_size(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = make_plugin(False, {}, {}, width=128, height=64)
        enable_map_background(p, tmp_path)

        p._get_map_background(CENTER_LAT, CENTER_LON)
        p.display_manager.matrix.width = 64
        p._get_map_background(CENTER_LAT, CENTER_LON)
        assert len(p.cached_map_bgs) == 2

        p._get_map_background(CENTER_LAT + 5, CENTER_LON + 5)
        assert list(p.cached_map_bgs) == [(64, 64)]

    def test_rendered_map_is_the_display_size_across_a_size_switch(self, tmp_path, monkeypatch):
        # The end-to-end symptom: _render_map_image copies the background, so a
        # stale-size memo produced a whole frame at the wrong size.
        monkeypatch.chdir(tmp_path)
        p = make_plugin(True, one_aircraft(), one_trail(), width=128, height=64)
        enable_map_background(p, tmp_path)

        assert p._render_map_image().size == (128, 64)
        p.display_manager.matrix.width = 256
        assert p._render_map_image().size == (256, 64)
        p.display_manager.matrix.width = 128
        assert p._render_map_image().size == (128, 64)
