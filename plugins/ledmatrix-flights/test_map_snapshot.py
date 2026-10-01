"""
The map is drawn from an immutable snapshot that update() publishes in one store.

update() edits aircraft_data and aircraft_trails in place on the update
worker, and the map can be drawn from another thread meanwhile (a Vegas
redraw runs without the plugin lock). So update() freezes what the map draws
into a MapSnapshot and swaps it in with a single attribute store, and the
renderer reads that alone. These pin:

  * the snapshot cannot be changed after publish, by assignment or through
    the live dicts it was copied from;
  * update() stores it exactly once, and not at all when nothing drawn changed;
    it does so before the network-bound enrichment steps, and even when a
    later step raises; __init__ publishes an empty one;
  * the renderer never touches aircraft_data or aircraft_trails once a
    snapshot is published;
  * can_extrapolate holds only for a position still fresh when published
    (or, test_glide.py, one held from the last snapshot);
  * _map_layer + _draw_heads(at=None) is byte-identical to the renderer as it
    was before the split (a verbatim copy of it is kept below as the reference);
  * the projection is computed once per snapshot and size;
  * get_vegas_content() and get_vegas_content_type() resolve 'auto' the same way.

Run: <core-venv>/bin/python -m pytest plugins/ledmatrix-flights/test_map_snapshot.py
"""

import copy
import dataclasses
import logging
import os
import random
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

# Other plugins ship modules under these bare names too; make sure the imports
# below resolve to this plugin's files.
for _stale in ("manager", "data_model", "fetcher", "utils"):
    sys.modules.pop(_stale, None)

try:
    import src.plugin_system.base_plugin as _base_plugin
    # Another test module in the same process may have installed a stand-in
    # (test_vegas_map_parity does); only a module loaded from a file is real.
    HAVE_CORE = getattr(_base_plugin, '__file__', None) is not None
except ImportError:
    # No core: stand in for BasePlugin. Only the on_config_change test needs
    # the real one, and it skips without it.
    HAVE_CORE = False
    _src = types.ModuleType('src')
    _ps = types.ModuleType('src.plugin_system')
    _bp = types.ModuleType('src.plugin_system.base_plugin')

    class _BasePlugin:
        def __init__(self, *args, **kwargs):
            pass

    _bp.BasePlugin = _BasePlugin
    _bp.VegasDisplayMode = None
    _ps.base_plugin = _bp
    _src.plugin_system = _ps
    sys.modules['src'] = _src
    sys.modules['src.plugin_system'] = _ps
    sys.modules['src.plugin_system.base_plugin'] = _bp

from data_model import MapSnapshot, TrackedFlight  # noqa: E402
from manager import FlightTrackerPlugin  # noqa: E402

W, H = 128, 64
CENTER = (28.0, -82.0)


class _DisplayManager:
    def __init__(self, width=W, height=H):
        self.matrix = types.SimpleNamespace(width=width, height=height)
        self.image = Image.new('RGB', (width, height))

    def update_display(self):
        pass

    def clear(self):
        self.image = Image.new('RGB', (self.matrix.width, self.matrix.height))


class _Shell(FlightTrackerPlugin):
    """A tracker whose __init__ builds nothing; tests set what they use."""

    def __init__(self):  # pylint: disable=super-init-not-called
        pass


def make_plugin(aircraft=None, trails=None, *, width=W, height=H, show_trails=True,
                radius=10, zoom=1.0, font=None):
    p = _Shell()
    dm = _DisplayManager(width, height)
    p._display_manager_ref = dm
    p.display_manager = dm
    p.logger = logging.getLogger("test-flights-map-snapshot")
    p.center_lat, p.center_lon = CENTER
    p.map_radius_miles = radius
    p.zoom_factor = zoom
    p.show_trails = show_trails
    p.trail_length = 10
    p.bounds_warning_cache = {}
    p.bounds_warning_interval = 30
    p.map_bg_enabled = False
    p.disable_on_cache_error = False
    p.cache_error_count = 0
    p.max_cache_errors = 5
    p.aircraft_data = aircraft if aircraft is not None else {}
    p.aircraft_trails = trails if trails is not None else {}
    p.fonts = {'small': font or ImageFont.load_default()}
    return p


def enable_map_background(p):
    """A deterministic tile background with no network and no disk cache."""
    p.map_bg_enabled = True
    p.tile_size = 256
    p.tile_provider = 'osm'
    p.custom_tile_server = None
    p.tile_cache_dir = Path(tempfile.gettempdir()) / 'ledmatrix-flights-test-tiles'
    p.cache_ttl_hours = 24
    p.fade_intensity = 0.4
    p.map_brightness = p.map_contrast = p.map_saturation = 1.0
    p.cached_map_bgs = {}
    p.last_map_center = None
    p.last_map_zoom = None

    def fake_fetch(x, y, zoom, allow_network=True):
        tile = Image.new('RGB', (256, 256))
        tile.putdata([((i + 7 * x) % 256, (i // 256 + 3 * y) % 256, 90)
                      for i in range(256 * 256)])
        return tile
    p._fetch_tile = fake_fetch


def deg(miles):
    return miles / 69.0


def sky():
    """Three aircraft; trails in a different order from the aircraft, two of them
    crossing (so the order they are drawn in shows), one running off-screen,
    and one for an aircraft no longer tracked."""
    aircraft = {
        'AAA111': {'icao': 'AAA111', 'lat': CENTER[0] + deg(3.2), 'lon': CENTER[1] + deg(1),
                   'color': (0, 200, 0), 'callsign': 'DAL1'},
        'BBB222': {'icao': 'BBB222', 'lat': CENTER[0] - deg(1), 'lon': CENTER[1] + deg(3),
                   'color': [255, 100, 0], 'callsign': 'UAL2'},
        'CCC333': {'icao': 'CCC333', 'lat': CENTER[0] + deg(1), 'lon': CENTER[1] + deg(4.5),
                   'color': (200, 0, 150), 'callsign': 'SWA3'},
    }
    trails = {
        # East-west across the north-south run of AAA111's trail below.
        'CCC333': [(CENTER[0] + deg(1), CENTER[1] + deg(-4 + i), 1000.0 + i)
                   for i in range(9)],
        'GONE00': [(CENTER[0], CENTER[1] + deg(0.3 * i), 1000.0 + i) for i in range(5)],
        'AAA111': [(CENTER[0] + deg(-3 + 0.75 * i), CENTER[1] + deg(1), 1000.0 + i)
                   for i in range(9)],
        'BBB222': [(CENTER[0] - deg(1 + 1.5 * i), CENTER[1] + deg(3 + 0.2 * i), 1000.0 + i)
                   for i in range(6)],
    }
    return aircraft, trails


def lit_pixels(img):
    raw = img.convert('RGB').tobytes()
    return sum(1 for i in range(0, len(raw), 3)
               if raw[i] > 10 or raw[i + 1] > 10 or raw[i + 2] > 10)


# ---------------------------------------------------------------------------
# The reference: FlightTrackerPlugin._render_map_image as it was before the
# snapshot (origin/main at 1.14.7), copied verbatim with self -> p. It reads
# the live dicts and projects every point per call; the new renderer must draw
# exactly what it drew.
# ---------------------------------------------------------------------------

def legacy_render_map_image(p):
    map_bg = p._get_map_background(p.center_lat, p.center_lon,
                                   allow_network=False)

    if map_bg:
        img = map_bg.copy()
    else:
        img = Image.new('RGB', (p.display_width, p.display_height), (0, 0, 0))

    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"

    center_pixel = p._latlon_to_pixel(p.center_lat, p.center_lon)
    if center_pixel:
        x, y = center_pixel
        draw.point((x, y), fill=(255, 255, 255))

    if p.show_trails:
        for icao, trail in p.aircraft_trails.items():
            if icao not in p.aircraft_data:
                continue

            aircraft = p.aircraft_data[icao]
            trail_pixels = []

            for lat, lon, timestamp in trail:
                pixel = p._latlon_to_pixel(lat, lon)
                if pixel:
                    trail_pixels.append(pixel)

            if len(trail_pixels) >= 2:
                for i in range(len(trail_pixels) - 1):
                    alpha = int(255 * (i + 1) / len(trail_pixels))
                    color = tuple(int(c * alpha / 255) for c in aircraft['color'])
                    draw.line([trail_pixels[i], trail_pixels[i + 1]], fill=color, width=1)

    for aircraft in p.aircraft_data.values():
        pixel = p._latlon_to_pixel(aircraft['lat'], aircraft['lon'])
        if not pixel:
            continue

        x, y = pixel
        base_color = aircraft.get('color') or (255, 255, 255)
        color = tuple(min(255, int(c * 1.3)) for c in base_color)
        draw.point((x, y), fill=color)

    if len(p.aircraft_data) > 0:
        info_text = f"{len(p.aircraft_data)}"
        p._draw_text_smart(draw, info_text, (2, 2), p.fonts['small'],
                           fill=(200, 200, 200), use_outline=False)
        bbox = draw.textbbox((0, 0), info_text, font=p.fonts['small'])
        text_width = bbox[2] - bbox[0]
        p._draw_airplane_icon(draw, 2 + text_width + 2, 2, color=(200, 200, 200))

    return img


def _core_font():
    """The 4x6 face the plugin really draws the count in, when the core is here."""
    if _core:
        path = Path(_core) / 'assets' / 'fonts' / '4x6-font.ttf'
        if path.exists():
            return ImageFont.truetype(str(path), 7)
    return None


def composed(p):
    """_map_layer under _draw_heads(at=None), called by hand."""
    snap = p._current_map_snapshot()
    width, height = p.display_width, p.display_height
    bg = p._get_map_background(snap.center_lat, snap.center_lon, allow_network=False)
    img = p._map_layer(snap, width, height, bg)
    p._draw_heads(img, snap, at=None)
    return img


# ---------------------------------------------------------------------------
# Byte-identical to the pre-snapshot renderer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("width,height", [(64, 32), (128, 32), (128, 64), (256, 64)])
@pytest.mark.parametrize("show_trails", [True, False])
@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("published", [False, True])
def test_split_renderer_matches_the_old_one(width, height, show_trails, background, published):
    aircraft, trails = sky()
    fonts = [None] + ([_core_font()] if _core_font() else [])
    for font in fonts:
        expected_plugin = make_plugin(copy.deepcopy(aircraft), copy.deepcopy(trails),
                                      width=width, height=height,
                                      show_trails=show_trails, font=font)
        p = make_plugin(copy.deepcopy(aircraft), copy.deepcopy(trails), width=width,
                        height=height, show_trails=show_trails, font=font)
        if background:
            enable_map_background(expected_plugin)
            enable_map_background(p)
        expected = legacy_render_map_image(expected_plugin).tobytes()
        assert lit_pixels(Image.frombytes('RGB', (width, height), expected)) > 20
        if published:
            p._publish_map_snapshot()
            assert p._map_snapshot is not None
        assert p._render_map_image().tobytes() == expected
        assert composed(p).tobytes() == expected
        # A second frame, now from the cached projection, is still the same.
        assert p._render_map_image().tobytes() == expected


def test_matches_the_old_renderer_on_random_skies():
    rng = random.Random(1914)
    for _ in range(60):
        width, height = rng.choice([(64, 32), (128, 32), (128, 64), (192, 48), (512, 64)])
        radius = rng.choice([5, 10, 40])
        aircraft, trails = {}, {}
        for n in range(rng.choice([0, 1, 4, 11, 23])):
            icao = 'R%05d' % n
            aircraft[icao] = {
                'lat': CENTER[0] + rng.uniform(-1.3, 1.3) * deg(radius),
                'lon': CENTER[1] + rng.uniform(-1.3, 1.3) * deg(radius),
                'color': rng.choice([(255, 100, 0), (0, 150, 255), (200, 0, 150)])}
        keys = list(aircraft)
        rng.shuffle(keys)
        for icao in keys:
            lat, lon = aircraft[icao]['lat'], aircraft[icao]['lon']
            trails[icao] = [(lat - rng.uniform(-1, 2) * deg(0.3) * i,
                             lon - rng.uniform(-1, 2) * deg(0.3) * i, 1000.0 + i)
                            for i in range(rng.randrange(0, 11))][::-1]
        state = dict(width=width, height=height, radius=radius,
                     show_trails=rng.random() < 0.8, zoom=rng.choice([1.0, 1.5]))
        old = make_plugin(copy.deepcopy(aircraft), copy.deepcopy(trails), **state)
        new = make_plugin(copy.deepcopy(aircraft), copy.deepcopy(trails), **state)
        new._publish_map_snapshot()
        assert new._render_map_image().tobytes() == legacy_render_map_image(old).tobytes()


def test_at_is_threaded_through_and_moves_nothing_that_cannot_extrapolate():
    # sky() has no receipt times, so nothing in it can be carried on; the
    # gliding itself is pinned in test_glide.py.
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    p._publish_map_snapshot()
    seen = []
    real = p._draw_heads

    def spy(img, snap, at=None):
        seen.append(at)
        return real(img, snap, at=at)
    p._draw_heads = spy
    still = p._render_map_image().tobytes()
    later = p._render_map_image(at=12345.6).tobytes()
    assert seen == [None, 12345.6]
    assert later == still


# ---------------------------------------------------------------------------
# The snapshot is immutable
# ---------------------------------------------------------------------------

def test_snapshot_cannot_be_assigned_to():
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    p._publish_map_snapshot()
    snap = p._map_snapshot
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.seq = 99
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.aircraft[0].lat = 0.0
    assert isinstance(snap.aircraft, tuple)
    assert isinstance(snap.trail_order, tuple)
    for ac in snap.aircraft:
        assert isinstance(ac.trail, tuple)
        assert all(isinstance(point, tuple) for point in ac.trail)
        assert isinstance(ac.color, tuple)


def test_editing_the_live_dicts_cannot_reach_a_published_snapshot():
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    p._publish_map_snapshot()
    snap = p._map_snapshot
    key = snap.draw_key()

    # Everything update() does to them in place.
    aircraft['AAA111']['lat'] += 0.5
    aircraft['BBB222']['color'][0] = 7          # the colour was a list
    trails['AAA111'].append((0.0, 0.0, 2000.0))
    trails['CCC333'][:] = []
    del aircraft['CCC333']
    aircraft['NEW999'] = {'lat': CENTER[0], 'lon': CENTER[1], 'color': (1, 2, 3)}

    assert p._map_snapshot is snap
    assert snap.draw_key() == key


# ---------------------------------------------------------------------------
# The renderer reads the snapshot alone
# ---------------------------------------------------------------------------

class _Untouchable(dict):
    """A mapping that fails the test on any read."""

    def _boom(self, *a, **k):
        raise AssertionError("the renderer read the live aircraft dicts")

    __getitem__ = __iter__ = __len__ = __contains__ = get = items = values = keys = _boom


def test_renderer_never_reads_the_live_dicts_once_published():
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    enable_map_background(p)
    p._publish_map_snapshot()
    before = p._render_map_image().tobytes()

    p.aircraft_data = _Untouchable()
    p.aircraft_trails = _Untouchable()
    assert p._render_map_image().tobytes() == before

    # And through the Vegas path, which is where a lock-free redraw will come from.
    p.display_mode = 'map'
    assert p.get_vegas_content()[0].tobytes() == before


def test_in_place_edits_show_only_after_the_next_publish():
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    p._publish_map_snapshot()
    before = p._render_map_image().tobytes()

    aircraft['AAA111']['lat'] -= deg(2)
    aircraft['ZZZ999'] = {'lat': CENTER[0] - deg(4), 'lon': CENTER[1] - deg(6),
                          'color': (255, 255, 0)}
    trails['BBB222'].append((CENTER[0], CENTER[1] + deg(5), 3000.0))
    assert p._render_map_image().tobytes() == before

    p._publish_map_snapshot()
    after = p._render_map_image().tobytes()
    assert after != before
    fresh = make_plugin(copy.deepcopy(aircraft), copy.deepcopy(trails))
    assert after == legacy_render_map_image(fresh).tobytes()


def test_before_the_first_publish_the_map_draws_the_live_data():
    """The first frame can precede the first update(). It must still draw what
    is there, and must not publish: a one-off built on the render thread could
    otherwise overwrite a newer snapshot."""
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    assert p._render_map_image().tobytes() == legacy_render_map_image(p).tobytes()
    assert getattr(p, '_map_snapshot', None) is None


# ---------------------------------------------------------------------------
# update() publishes once, and seq tracks what is drawn
# ---------------------------------------------------------------------------

class _RecordingShell(_Shell):
    def __setattr__(self, name, value):
        if name == '_map_snapshot':
            self.__dict__.setdefault('stores', []).append(
                (value, len(self.__dict__.get('aircraft_data', {}))))
        super().__setattr__(name, value)


class _FakeFetcher:
    def __init__(self, result):
        self.result = result

    def fetch(self, *a, **k):
        return copy.deepcopy(self.result)


_UNSET = object()


def _fetched(icao, lat, lon, *, speed=250.0, heading=90.0, track_valid=True, pos_age=2.0,
             pos_stale=False, received_mono=_UNSET, on_ground=False, callsign='DAL1'):
    """A fetcher's aircraft dict, received just now unless said otherwise."""
    if received_mono is _UNSET:
        received_mono = time.monotonic()
    return {'icao': icao, 'callsign': callsign, 'lat': lat, 'lon': lon, 'altitude': 9000,
            'speed': speed, 'heading': heading, 'distance_miles': 1.0, 'color': (0, 200, 150),
            'last_seen': 10 ** 12, 'track_valid': track_valid, 'pos_age': pos_age,
            'pos_stale': pos_stale, 'received_mono': received_mono, 'on_ground': on_ground}


def updating_plugin(result):
    """A tracker set up for update()'s adsb.fi branch, fetching ``result``."""
    p = _RecordingShell()
    template = make_plugin()
    for name, value in template.__dict__.items():
        object.__setattr__(p, name, value)
    object.__setattr__(p, 'stores', [])
    p.data_source = 'adsbfi'
    p._fetcher = _FakeFetcher(result)
    # Each poll appends a trail point, which is a real change until the trail
    # is full; one point keeps "the same sky again" the same drawing.
    p.trail_length = 1
    p.proximity_distance_miles = 0.1
    p.all_aircraft_data = {}
    p.altitude_colors = {'0': [255, 100, 0], '40000': [150, 0, 200]}
    p.flight_records_enabled = False
    p.fr24_enrichment = False
    p.pending_fr24_details, p.pending_flight_plans = {}, set()
    p.use_offline_db = False
    p.skyaware_url = ''
    p.tracked_flights_cfg = []
    p.metar_enabled = False
    p.metar_airports = []
    p._lock_icao = None
    p._last_displayed_time = 0.0
    p._display_idle_threshold = 30.0
    p.update_interval = p.live_update_interval = 5
    p.last_fetch = 0
    p._prefetch_map_tiles = lambda: None
    return p


def test_update_publishes_in_one_store_after_the_data_is_in():
    result = {'AAA111': _fetched('AAA111', CENTER[0] + deg(1), CENTER[1]),
              'BBB222': _fetched('BBB222', CENTER[0], CENTER[1] + deg(1))}
    p = updating_plugin(result)
    p.update()
    assert len(p.stores) == 1
    snap, aircraft_when_stored = p.stores[0]
    assert isinstance(snap, MapSnapshot)
    assert aircraft_when_stored == 2            # stored after processing, not during
    assert [ac.icao for ac in snap.aircraft] == ['AAA111', 'BBB222']
    assert snap.seq == 1

    # The same sky again: nothing drawn changed, so nothing is stored.
    p.last_fetch = 0
    p.update()
    assert len(p.stores) == 1
    assert p._map_snapshot is snap

    # A move is stored, once, with the next seq.
    p._fetcher.result['AAA111']['lat'] += deg(1)
    p.last_fetch = 0
    p.update()
    assert len(p.stores) == 2
    assert p._map_snapshot.seq == 2


def test_seq_moves_only_when_the_drawing_would():
    def snap_after(edit):
        aircraft = {'AAA111': _fetched('AAA111', CENTER[0] + deg(1), CENTER[1]),
                    'PARKED': _fetched('PARKED', CENTER[0], CENTER[1] + deg(1),
                                       speed=4.0, on_ground=True)}
        p = make_plugin(aircraft, {'AAA111': [(CENTER[0], CENTER[1], 1.0)]})
        p._publish_map_snapshot()
        first = p._map_snapshot
        edit(p)
        p._publish_map_snapshot()
        return first, p._map_snapshot

    def unchanged(edit):
        first, second = snap_after(edit)
        return second is first and second.seq == first.seq == 1

    def bumped(edit):
        first, second = snap_after(edit)
        return second is not first and second.seq == first.seq + 1

    def re_reported(icao, **fields):
        def edit(p):
            ac = p.aircraft_data[icao]
            ac.update(received_mono=ac['received_mono'] + 1.0, **fields)
        return edit

    assert unchanged(lambda p: None)
    assert unchanged(lambda p: p.aircraft_data['AAA111'].update(callsign='OTHER', altitude=1))
    # A parked aircraft re-reported at the same spot: same pixels at any time.
    assert unchanged(re_reported('PARKED', pos_age=5.0))
    # A moving one re-reported: its position is true at a different moment.
    assert bumped(re_reported('AAA111'))
    # One that has become too old to move on from, still at the same spot, is
    # held as it was being carried (MapSnapshot.held_from, test_glide.py):
    # the same pixels at any time.
    assert unchanged(lambda p: p.aircraft_data['AAA111'].update(pos_stale=True))
    assert bumped(lambda p: p.aircraft_data['AAA111'].update(lat=CENTER[0]))
    assert bumped(lambda p: p.aircraft_data['AAA111'].update(color=(1, 2, 3)))
    assert bumped(lambda p: p.aircraft_trails['AAA111'].append((CENTER[0], CENTER[1] + 0.01, 2.0)))
    assert bumped(lambda p: p.aircraft_data.pop('PARKED'))
    assert bumped(lambda p: setattr(p, 'show_trails', False))


def test_can_extrapolate():
    def can(**over):
        p = make_plugin({'A': _fetched('A', CENTER[0], CENTER[1], **over)})
        p._publish_map_snapshot()
        return p._map_snapshot.aircraft[0].can_extrapolate

    assert can()
    assert can(speed=30.0)
    assert not can(speed=29.9)
    assert not can(track_valid=False)
    assert not can(on_ground=True)
    assert not can(received_mono=None)          # no receipt time: no base to move from
    assert not can(heading=None)

    # Age. The source said it was past the clamp (pos_age alone reads 30).
    assert can(pos_age=29.0)
    assert not can(pos_age=30.0, pos_stale=True)
    # Or it has aged past it since receipt: a fallback payload, or a record
    # kept on after it left the feed.
    assert not can(pos_age=0.0, received_mono=time.monotonic() - 31)
    assert not can(pos_age=29.0, received_mono=time.monotonic() - 2)

    p = make_plugin({'A': _fetched('A', CENTER[0], CENTER[1], pos_age=2.5,
                                   received_mono=1000.0)})
    p._publish_map_snapshot()
    ac = p._map_snapshot.aircraft[0]
    assert ac.pos_mono == 997.5
    assert (ac.speed_kt, ac.track_deg) == (250.0, 90.0)


def test_can_extrapolate_is_decided_at_publish():
    """The age that counts is the position's age when the snapshot is made."""
    def built(now_mono):
        aircraft = {'A': _fetched('A', CENTER[0], CENTER[1], pos_age=2.5,
                                  received_mono=1000.0)}
        return MapSnapshot.build(1, aircraft, {}, center_lat=CENTER[0],
                                 center_lon=CENTER[1], map_radius_miles=10,
                                 zoom_factor=1.0, show_trails=True,
                                 now_mono=now_mono).aircraft[0]
    assert built(1000.0).can_extrapolate                 # 2.5 s old
    assert built(1027.5).can_extrapolate                 # 30 s old
    assert not built(1027.6).can_extrapolate             # past it
    assert built(1027.6).pos_mono == 997.5               # the time itself is kept


# ---------------------------------------------------------------------------
# update() hands the map its sky as soon as it has one
# ---------------------------------------------------------------------------

def _drawn(p):
    """(icao, lat) of each aircraft in the published snapshot."""
    return [(ac.icao, ac.lat) for ac in p._map_snapshot.aircraft]


def test_update_publishes_before_the_network_bound_steps():
    """FR24 enrichment and detail fetches are network calls with 8-10 s
    timeouts that change nothing drawn; the new positions must not wait on them."""
    result = {'AAA111': _fetched('AAA111', CENTER[0] + deg(1), CENTER[1])}
    p = updating_plugin(result)
    p.fr24_enrichment = True
    p._last_displayed_time = time.time()       # on screen, so they run
    seen = {}
    p._maybe_refresh_fr24_enrichment = lambda: seen.setdefault('enrichment', _drawn(p))
    p._background_fetch_fr24_details = lambda: seen.setdefault('details', _drawn(p))
    p._enrich_from_offline_db = lambda: seen.setdefault('offline', _drawn(p))
    p._queue_interesting_callsigns = lambda: None
    p.update()
    expected = [('AAA111', CENTER[0] + deg(1))]
    assert seen == {'enrichment': expected, 'details': expected, 'offline': expected}
    assert len(p.stores) == 1


@pytest.mark.parametrize("failing", ['_enrich_from_offline_db', '_update_flight_records'])
def test_a_failing_step_cannot_freeze_the_map(failing):
    """A step raising after the dicts took the new poll -- enrichment, or the
    tail of the ingest itself -- still leaves the map showing that poll, as
    it did when the map read the dicts live."""
    result = {'AAA111': _fetched('AAA111', CENTER[0] + deg(1), CENTER[1])}
    p = updating_plugin(result)
    p.update()
    assert _drawn(p) == [('AAA111', CENTER[0] + deg(1))]

    def boom():
        raise RuntimeError("step failed")
    setattr(p, failing, boom)
    p._fetcher.result['AAA111']['lat'] += deg(1)
    p.last_fetch = 0
    with pytest.raises(RuntimeError):
        p.update()
    assert _drawn(p) == [('AAA111', CENTER[0] + deg(2))]
    assert p._map_snapshot.seq == 2


def _real_tracker(config):
    class _Cache:
        cache_dir = tempfile.mkdtemp()

    return FlightTrackerPlugin('ledmatrix-flights', config,
                               display_manager=_DisplayManager(),
                               cache_manager=_Cache(), plugin_manager=object())


MAP_CONFIG = {'data_source': 'skyaware', 'center_latitude': CENTER[0],
              'center_longitude': CENTER[1], 'map_radius_miles': 10,
              'map_background': {'enabled': False}}


def test_init_publishes_an_empty_sky():
    """The first frame can come before the first update() (and from another
    thread): it must draw a snapshot, not the dicts update() is filling."""
    if not HAVE_CORE:
        pytest.skip("needs the LEDMatrix core (set LEDMATRIX_CORE)")
    tracker = _real_tracker(MAP_CONFIG)
    snap = tracker._map_snapshot
    assert snap is not None and snap.seq == 1 and snap.aircraft == ()
    expected = legacy_render_map_image(tracker).tobytes()     # the empty dicts, live

    tracker.aircraft_data = _Untouchable()
    tracker.aircraft_trails = _Untouchable()
    assert tracker._render_map_image().tobytes() == expected


def test_a_config_change_moves_the_published_map():
    """on_config_change() is the one path that changes what the map draws
    outside update(); it must reach the snapshot without re-reading the dicts."""
    if not HAVE_CORE:
        pytest.skip("needs the LEDMatrix core (set LEDMATRIX_CORE)")
    config = MAP_CONFIG
    tracker = _real_tracker(config)
    aircraft, trails = sky()
    tracker.aircraft_data, tracker.aircraft_trails = aircraft, trails
    tracker._publish_map_snapshot()
    first = tracker._map_snapshot
    wide = tracker._render_map_image().tobytes()

    tracker.aircraft_data = _Untouchable()
    tracker.aircraft_trails = _Untouchable()
    tracker.on_config_change(dict(config, map_radius_miles=25, show_trails=False))
    second = tracker._map_snapshot
    assert second.seq == first.seq + 1
    assert (second.map_radius_miles, second.show_trails) == (25, False)
    assert second.aircraft == first.aircraft
    assert tracker._render_map_image().tobytes() != wide

    # The same values again change nothing.
    tracker.on_config_change(dict(config, map_radius_miles=25, show_trails=False))
    assert tracker._map_snapshot is second


def test_on_config_change_publishes():
    import ast
    tree = ast.parse((HERE / 'manager.py').read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == 'on_config_change')
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, 'attr', None) == '_publish_map_snapshot']
    assert calls, "on_config_change must republish the map geometry"


# ---------------------------------------------------------------------------
# Projection: once per snapshot and size
# ---------------------------------------------------------------------------

def test_projection_is_computed_once_per_snapshot_and_size():
    aircraft, trails = sky()
    p = make_plugin(aircraft, trails)
    p._publish_map_snapshot()
    calls = []
    real = p._project_to_pixel

    def counting(*a, **k):
        calls.append(a)
        return real(*a, **k)
    p._project_to_pixel = counting

    p._render_map_image()
    per_frame = len(calls)
    assert per_frame > 0
    p._render_map_image()
    p._render_map_image(at=5.0)
    assert len(calls) == per_frame              # redraws reuse it

    p.display_manager.matrix.width = 64         # the ticker's narrower ask
    p._render_map_image()
    assert len(calls) == 2 * per_frame
    p.display_manager.matrix.width = W
    p._render_map_image()
    assert len(calls) == 2 * per_frame          # both sizes are kept

    aircraft['AAA111']['lat'] += deg(1)
    p._publish_map_snapshot()
    p._render_map_image()
    assert len(calls) == 3 * per_frame          # a new snapshot is projected afresh


def test_projection_debug_formatting_is_skipped_when_debug_is_off():
    p = make_plugin()
    calls = []

    class _Quiet:
        def isEnabledFor(self, level):
            return False

        def debug(self, *a, **k):
            calls.append(a)
    p.logger = _Quiet()
    assert p._latlon_to_pixel(CENTER[0], CENTER[1]) == (W // 2, H // 2)
    assert calls == []

    class _Loud(_Quiet):
        def isEnabledFor(self, level):
            return True
    p.logger = _Loud()
    p._latlon_to_pixel(CENTER[0], CENTER[1])
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# One resolution of display_mode 'auto' for both Vegas callers
# ---------------------------------------------------------------------------

def vegas_plugin(mode, *, airborne, overhead, anchor, mapped, proximity):
    p = make_plugin()
    p.display_mode = mode
    p.tracked_flight_data = ({'DAL1': TrackedFlight('DAL1', status='AIRBORNE')}
                             if airborne else {'DAL1': TrackedFlight('DAL1', status='LANDED')})
    p.proximity_enabled = proximity
    p.proximity_distance_miles = 1.0
    ac = {'icao': 'AAA111', 'lat': CENTER[0], 'lon': CENTER[1], 'color': (0, 200, 0),
          'distance_miles': 0.4 if overhead else 6.0,
          'origin': 'TPA' if anchor else 'ORD', 'destination': 'JFK', 'speed': 200,
          'altitude': 5000}
    p.aircraft_data = {'AAA111': ac} if mapped else {}
    p.all_aircraft_data = dict(p.aircraft_data)
    p.anchor_airport = 'KTPA'
    p.max_aircraft = 5
    p.min_altitude_ft = p.max_altitude_ft = 0
    p.aircraft_categories = []
    p.flight_records_enabled = False
    p._closest_record = p._farthest_record = None
    p.current_stat = 0
    p.last_stat_change = 0.0
    p.stat_duration = 10

    # Record which view get_vegas_content() actually renders.
    rendered = []
    p.rendered = rendered
    p._render_map_image = lambda at=None: rendered.append('map') or Image.new('RGB', (W, H))
    p._display_overhead = lambda force_clear=False: rendered.append('overhead')
    p._display_stats = lambda force_clear=False: rendered.append('stats')
    p._renderer = types.SimpleNamespace(
        render_area_card_image=lambda *a, **k: rendered.append('area') or Image.new('RGB', (W, H)),
        render_flight_tracking=lambda tf: rendered.append('flight_tracking'))
    return p


CASES = [dict(airborne=a, overhead=o, anchor=n, mapped=m, proximity=x)
         for a in (False, True) for o in (False, True) for n in (False, True)
         for m in (False, True) for x in (False, True)]


@pytest.mark.parametrize("mode", ['auto', 'map', 'overhead', 'area', 'stats', 'flight_tracking'])
@pytest.mark.parametrize("case", CASES, ids=lambda c: ",".join(k for k, v in c.items() if v) or "none")
def test_content_and_type_agree(mode, case):
    p = vegas_plugin(mode, **case)
    resolved = p._resolve_vegas_mode()
    content_type = p.get_vegas_content_type()
    p.get_vegas_content()
    assert set(p.rendered) <= {resolved}, (resolved, p.rendered)
    assert content_type == ('multi' if resolved in ('area', 'stats', 'flight_tracking')
                            else 'static')


def test_overhead_wins_in_both():
    """The case the two used to disagree on: an aircraft inside the proximity
    radius that also matches the anchor airport. The content showed one
    overhead card while the type said 'multi' (area)."""
    p = vegas_plugin('auto', airborne=False, overhead=True, anchor=True, mapped=True,
                     proximity=True)
    assert p._resolve_vegas_mode() == 'overhead'
    assert p.get_vegas_content_type() == 'static'
    p.get_vegas_content()
    assert p.rendered == ['overhead']


def test_auto_order():
    def resolved(**case):
        return vegas_plugin('auto', **case)._resolve_vegas_mode()
    everything = dict(airborne=True, overhead=True, anchor=True, mapped=True, proximity=True)
    assert resolved(**everything) == 'flight_tracking'
    assert resolved(**dict(everything, airborne=False)) == 'overhead'
    assert resolved(**dict(everything, airborne=False, proximity=False)) == 'area'
    assert resolved(**dict(everything, airborne=False, overhead=False)) == 'area'
    assert resolved(**dict(everything, airborne=False, overhead=False, anchor=False)) == 'map'
    assert resolved(airborne=False, overhead=False, anchor=False, mapped=False,
                    proximity=True) == 'stats'
    # A mode the content has no branch for falls through to stats in both.
    p = vegas_plugin('metar', **dict(everything, airborne=False))
    assert p._resolve_vegas_mode() == 'stats'
    assert p.get_vegas_content_type() == 'multi'
