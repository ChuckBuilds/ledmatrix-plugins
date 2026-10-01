"""
The Vegas map glides: aircraft move between polls instead of jumping per poll.

In the Vegas ticker the map is a live element (core 3.8.0). get_vegas_elements()
draws it under the plugin lock after each update(); redraw_vegas_element()
redraws it a few times a second WITHOUT the lock, from the published
MapSnapshot and the background the locked render used. These pin:

  * dead reckoning: an aircraft that can extrapolate is carried along its
    track at its speed for its position's age, capped at 20 s, where it holds
    -- also once its report goes stale, and across the publishes after that:
    it never jumps back to the report; one that cannot extrapolate stays
    where it was reported;
  * easing: a new poll's small correction eases out over 1.5 s from where the
    previous snapshot was drawing the aircraft; a correction over 6 px at the
    size drawn, or an aircraft new to the snapshot, snaps;
  * a glide render at at == pos_mono with nothing left to ease is byte-identical
    to the ordinary (at=None) render;
  * a trail ends at its moved head: never short of it, never past it;
  * get_vegas_elements() returns the one map element only in map mode with
    map_glide on; redraw_vegas_element() returns exactly the size asked, None
    for anything it has no background for, and never reads aircraft_data, the
    tile cache or the network, nor draws on the background it reuses;
  * a partial tile composite is reused for 10 s unless a missing tile arrives;
  * being shown in the ticker counts as visible for update() (routes and
    flight plans; not weather, which the ticker never shows);
  * map_glide / map_glide_hz are read, clamped, and applied live.

Run: <core-venv>/bin/python -m pytest plugins/ledmatrix-flights/test_glide.py
"""

import copy
import dataclasses
import logging
import math
import os
import random
import sys
import tempfile
import threading
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
    HAVE_CORE = getattr(_base_plugin, '__file__', None) is not None
except ImportError:
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

import manager  # noqa: E402
from data_model import EASE_SECONDS, MAX_GLIDE_SECONDS, MapSnapshot  # noqa: E402
from manager import FlightTrackerPlugin  # noqa: E402

needs_core = pytest.mark.skipif(
    not HAVE_CORE or manager.VegasElement is None,
    reason="needs the LEDMatrix 3.8.0 core (set LEDMATRIX_CORE)")

W, H = 128, 64
CENTER = (28.0, -82.0)
RADIUS = 10
PPM = W / (2 * RADIUS)              # pixels per mile at 128 wide, radius 10
T0 = 1000.0                         # a time.monotonic() for hand-built skies
KT = 360.0                          # 0.115 statute miles a second
MI_PER_S = KT * 1.150779 / 3600.0
COLOR = (10, 100, 190)
HEAD = tuple(min(255, int(c * 1.3)) for c in COLOR)


# ---------------------------------------------------------------------------
# A tracker with just the state the map touches
# ---------------------------------------------------------------------------

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


def make_plugin(aircraft=None, trails=None, *, width=W, height=H, show_trails=True):
    p = _Shell()
    dm = _DisplayManager(width, height)
    p._display_manager_ref = dm
    p.display_manager = dm
    p.logger = logging.getLogger("test-flights-glide")
    p.center_lat, p.center_lon = CENTER
    p.map_radius_miles = RADIUS
    p.zoom_factor = 1.0
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
    p.fonts = {'small': ImageFont.load_default()}
    # Vegas map mode with the glide on.
    p.map_glide = True
    p.map_glide_hz = 4
    p.display_mode = 'map'
    p.tracked_flight_data = {}
    p.proximity_enabled = False
    p.anchor_airport = None
    return p


def enable_map_background(p):
    """A deterministic tile background: no network, no disk."""
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


#: A row a third of a pixel below the centre's (y 32.32): an aircraft "due
#: east" is then drawn on row 32, where one on the centre's own row (y 32.0)
#: could truncate either side of it.
ROW = -0.05


def at_miles(east=0.0, north=0.0):
    """The lat/lon the map draws ``east``/``north`` statute miles from the centre.

    The projection is azimuthal (distance along the initial bearing), so this
    is the great-circle destination at that bearing and distance: a point at
    the centre's latitude is not due east on the map.
    """
    if east == north == 0:
        return CENTER                       # exactly: projected to (w/2, h/2)
    radius = 3959.0                         # utils.haversine_miles' Earth
    d = math.hypot(east, north) / radius
    bearing = math.atan2(east, north)
    lat1, lon1 = math.radians(CENTER[0]), math.radians(CENTER[1])
    lat2 = math.asin(math.sin(lat1) * math.cos(d)
                     + math.cos(lat1) * math.sin(d) * math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def aircraft_dict(icao, lat, lon, *, speed=KT, heading=90.0, track_valid=True,
                  pos_age=0.0, pos_stale=False, received_mono=T0, on_ground=False,
                  color=COLOR):
    return {'icao': icao, 'lat': lat, 'lon': lon, 'speed': speed, 'heading': heading,
            'track_valid': track_valid, 'pos_age': pos_age, 'pos_stale': pos_stale,
            'received_mono': received_mono, 'on_ground': on_ground, 'color': color,
            'distance_miles': 1.0, 'callsign': icao, 'altitude': 9000,
            'last_seen': 10 ** 12}


def snapshot(aircraft, trails=None, *, now=T0, seq=1, show_trails=True, prev=None,
             published=None, center=CENTER):
    snap = MapSnapshot.build(seq, aircraft, trails or {}, center_lat=center[0],
                             center_lon=center[1], map_radius_miles=RADIUS,
                             zoom_factor=1.0, show_trails=show_trails, now_mono=now)
    if published is not None:
        snap = snap.with_corrections(prev, published)
    return snap


def draw(p, snap, at, width=W, height=H, background=None):
    """_map_layer under _draw_heads, as both Vegas paths compose the map."""
    img = p._map_layer(snap, width, height, background)
    p._draw_heads(img, snap, at=at)
    return img


def heads(p, snap, at, width=W, height=H):
    return p._glide_heads(snap, p._map_projection(snap, width, height), width, height, at)


def pixels_of(img, color):
    w, h = img.size
    raw = img.convert('RGB').tobytes()
    want = bytes(color)
    return [(i // 3 % w, i // 3 // w) for i in range(0, len(raw), 3)
            if raw[i:i + 3] == want]


# ---------------------------------------------------------------------------
# Dead reckoning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heading,dx,dy", [(90.0, 1, 0), (270.0, -1, 0), (0.0, 0, -1),
                                           (180.0, 0, 1)])
def test_an_aircraft_moves_along_its_track_by_its_speed(heading, dx, dy):
    """From the centre (64, 32): 360 kt for 10 s is 1.151 mi, 7.37 px at 6.4 px/mi."""
    lat, lon = at_miles()
    snap = snapshot({'A': aircraft_dict('A', lat, lon, heading=heading)})
    p = make_plugin(show_trails=False)
    moved = 10.0 * MI_PER_S * PPM
    assert moved == pytest.approx(7.365, abs=0.001)
    x, y = heads(p, snap, T0 + 10.0)[0]
    assert (x, y) == (int(64 + dx * moved), int(32 + dy * moved))

    # And it is drawn there, in its own colour, and nowhere else.
    img = draw(p, snap, T0 + 10.0)
    assert pixels_of(img, HEAD) == [(x, y)]


def test_a_diagonal_track_moves_on_both_axes():
    lat, lon = at_miles()
    snap = snapshot({'A': aircraft_dict('A', lat, lon, heading=45.0)})
    step = 10.0 * MI_PER_S * PPM * math.sin(math.radians(45))
    assert heads(make_plugin(), snap, T0 + 10.0)[0] == (int(64 + step), int(32 - step))


def test_the_move_follows_the_position_time_not_the_receipt():
    """A position already 4 s old at receipt has 4 s of flying in it at receipt."""
    lat, lon = at_miles()
    snap = snapshot({'A': aircraft_dict('A', lat, lon, pos_age=4.0)})
    p = make_plugin()
    assert heads(p, snap, T0 + 6.0) == heads(p, snapshot(
        {'A': aircraft_dict('A', lat, lon, received_mono=T0 - 4.0)}), T0 + 6.0)
    assert heads(p, snap, T0)[0] == (int(64 + 4.0 * MI_PER_S * PPM), 32)


@pytest.mark.parametrize("fields", [
    dict(on_ground=True), dict(speed=29.0), dict(track_valid=False), dict(heading=None),
    dict(pos_stale=True), dict(received_mono=None)],
    ids=['on-ground', 'slow', 'no-track', 'no-heading', 'stale-at-source', 'no-receipt'])
def test_an_aircraft_that_cannot_extrapolate_stays_put(fields):
    lat, lon = at_miles(north=2.0)
    snap = snapshot({'A': aircraft_dict('A', lat, lon, **fields)})
    assert not snap.aircraft[0].can_extrapolate
    p = make_plugin()
    raw = p._map_projection(snap, W, H).heads[0]
    for at in (T0, T0 + 5.0, T0 + 19.0):
        assert heads(p, snap, at)[0] == raw
        assert draw(p, snap, at).tobytes() == draw(p, snap, None).tobytes()


def test_a_position_that_ages_past_30s_holds_where_the_glide_left_it():
    """can_extrapolate is decided at publish; the age keeps growing after it.
    Past 30 s the position is stale, and a stale position does not move: not
    on, and not back to where it was reported either."""
    lat, lon = at_miles()
    snap = snapshot({'A': aircraft_dict('A', lat, lon)})
    p = make_plugin()
    assert snap.aircraft[0].can_extrapolate
    capped = heads(p, snap, T0 + MAX_GLIDE_SECONDS)[0]
    assert capped != (64, 32)
    for at in (T0 + 30.0, T0 + 30.01, T0 + 300.0):
        assert heads(p, snap, at)[0] == capped


def _aged_out(prev, now, **fields):
    """The publish after ``prev`` with A's report unchanged but no longer one
    to carry on (aged out of the feed, by default), held as the publisher holds it."""
    ac = prev.aircraft[0]
    record = aircraft_dict('A', ac.lat, ac.lon, **fields)
    return snapshot({'A': record}, now=now, seq=prev.seq + 1).held_from(prev) \
        .with_corrections(prev, now)


@pytest.mark.parametrize("fields", [
    dict(),                                     # received at T0, now 31 s on
    dict(pos_age=30.0, pos_stale=True, received_mono=T0 + 31.0),
    dict(speed=10.0, received_mono=T0 + 31.0),
    dict(track_valid=False, received_mono=T0 + 31.0)],
    ids=['aged-since-receipt', 'stale-at-source', 'slowed', 'lost-track'])
def test_the_publish_after_a_report_ages_out_keeps_it_where_it_is(fields):
    """The publish that finds the same report too old (or otherwise no longer
    one to carry on) keeps carrying it as the last one did, so it holds at the
    cap instead of going back to the report."""
    lat, lon = at_miles(north=ROW)
    first = snapshot({'A': aircraft_dict('A', lat, lon)}, published=T0)
    later = _aged_out(first, T0 + 31.0, **fields)
    assert later.aircraft[0].can_extrapolate
    assert later.aircraft[0].pos_mono == first.aircraft[0].pos_mono
    assert later.draw_key() == first.draw_key()     # the same drawing: nothing to publish
    p = make_plugin()
    capped = heads(p, first, T0 + MAX_GLIDE_SECONDS)
    for at in (T0 + 31.0, T0 + 31.5, T0 + 60.0):
        assert heads(p, later, at) == capped


def test_a_report_that_moved_is_not_held():
    """Only an unchanged report is held: one that moved is drawn where it now
    is, even if it can no longer be carried on (it landed, say)."""
    first = snapshot({'A': aircraft_dict('A', *at_miles(north=ROW))}, published=T0)
    landed = aircraft_dict('A', *at_miles(east=1.0, north=ROW), on_ground=True,
                           received_mono=T0 + 5.0)
    second = snapshot({'A': landed}, now=T0 + 5.0, seq=2).held_from(first)
    assert not second.aircraft[0].can_extrapolate


def test_a_dot_that_drops_out_of_the_feed_never_goes_backwards(monkeypatch):
    """Through the publisher, on a fake clock, at 4 frames a second: an
    aircraft that stops reporting glides on for 20 s, then holds, through
    every update() publish after (each re-reading the same, aging record)."""
    clock = [T0]
    monkeypatch.setattr(manager.time, 'monotonic', lambda: clock[0])
    aircraft = {'A': aircraft_dict('A', *at_miles(east=-5.0, north=ROW))}
    p = make_plugin(aircraft, show_trails=False)
    xs = []
    for frame in range(4 * 70):
        clock[0] = T0 + frame * 0.25
        if frame % 20 == 0:                     # an update() every 5 s
            p._publish_map_snapshot()
        xs.append(heads(p, p._map_snapshot, clock[0])[0][0])
    assert all(b >= a for a, b in zip(xs, xs[1:])), xs
    assert xs[-1] == int(64 - 5.0 * PPM + MAX_GLIDE_SECONDS * MI_PER_S * PPM)
    assert p._map_snapshot.seq == 1             # holding is not a new drawing


def test_extrapolation_is_capped_at_20s():
    lat, lon = at_miles()
    snap = snapshot({'A': aircraft_dict('A', lat, lon)})
    p = make_plugin()
    capped = heads(p, snap, T0 + MAX_GLIDE_SECONDS)[0]
    assert capped == (int(64 + MAX_GLIDE_SECONDS * MI_PER_S * PPM), 32)
    assert heads(p, snap, T0 + 25.0)[0] == capped
    assert heads(p, snap, T0 + 29.9)[0] == capped
    # And never backwards: a time before the position counts as no time.
    assert heads(p, snap, T0 - 5.0)[0] == (64, 32)


def test_an_aircraft_can_glide_onto_the_screen():
    """An off-screen report is kept unrounded, so it can come into view."""
    lat, lon = at_miles(east=-10.5, north=ROW)  # 3.2 px left of the left edge
    snap = snapshot({'A': aircraft_dict('A', lat, lon)})
    p = make_plugin()
    assert p._map_projection(snap, W, H).heads[0] is None
    assert heads(p, snap, T0)[0] is None
    x, y = heads(p, snap, T0 + 10.0)[0]
    assert 0 <= x < 8 and y == 32


# ---------------------------------------------------------------------------
# Easing a new poll in
# ---------------------------------------------------------------------------

P = T0 + 5.0                                # when the second poll is published


def two_polls(offset_east, *, width=W, new_icao=None):
    """Poll 1 at T0 by the centre, flying east on row 32; poll 2 published at P,
    reporting the aircraft ``offset_east`` miles east of where poll 1 was
    carrying it."""
    lat, lon = at_miles(north=ROW)
    first = snapshot({'A': aircraft_dict('A', lat, lon)}, published=T0)
    carried = 5.0 * MI_PER_S
    lat2, lon2 = at_miles(east=carried + offset_east, north=ROW)
    second_aircraft = {'A': aircraft_dict('A', lat2, lon2, received_mono=P)}
    if new_icao:
        second_aircraft[new_icao] = aircraft_dict(new_icao, *at_miles(north=2.0),
                                                  received_mono=P)
    second = snapshot(second_aircraft, now=P, seq=2, prev=first, published=P)
    plain = snapshot(second_aircraft, now=P, seq=2)      # the same, uncorrected
    return first, second, plain


def test_a_poll_stores_where_the_last_snapshot_was_drawing_the_aircraft():
    first, second, _ = two_polls(0.3)
    assert second.published_mono == P
    east, north = second.corrections[0]
    assert east == pytest.approx(-0.3, abs=0.002)
    assert north == pytest.approx(0.0, abs=0.002)
    # Not part of what is drawn: seq moves only for the data.
    assert second.draw_key() == dataclasses.replace(second, corrections=()).draw_key()


def test_a_small_correction_eases_out_over_1_5s():
    first, second, plain = two_polls(0.3)       # 1.9 px: eases
    p = make_plugin()
    # At the publish the dot is exactly where the last snapshot had it.
    assert heads(p, second, P) == heads(p, first, P)
    assert heads(p, second, P) != heads(p, plain, P)
    # Half-way, half of it is left: the report (0.3 mi past the glide) carried
    # on for 5.75 s in all, less half the 0.3 mi correction.
    x = 64 + (5.75 * MI_PER_S + 0.3 - 0.3 * 0.5) * PPM
    assert heads(p, second, P + 0.75)[0] == (int(x), 32)
    assert int(x) not in (heads(p, first, P + 0.75)[0][0], heads(p, plain, P + 0.75)[0][0])
    # From 1.5 s on it is the new report, carried on.
    for later in (P + EASE_SECONDS, P + 2.0, P + 10.0):
        assert heads(p, second, later) == heads(p, plain, later)


@pytest.mark.parametrize("offset", [0.9, 0.3, -0.3, -0.9])
def test_the_eased_dot_never_jumps(offset):
    """At 20 frames a second across the publish, the dot never moves more than
    a pixel between frames, whichever side of the glide the report lands. (A
    report well behind it can walk the dot back a little during the ease: the
    correction is spread over 1.5 s, not hidden.)"""
    first, second, plain = two_polls(offset)    # 0.9 mi is 5.8 px: still eases
    p = make_plugin()
    xs = [heads(p, first, T0 + 4.0 + i * 0.05)[0][0] for i in range(20)]
    xs += [heads(p, second, P + i * 0.05)[0][0] for i in range(60)]
    assert max(abs(b - a) for a, b in zip(xs, xs[1:])) <= 1
    # ...and ends up on the new report.
    assert xs[-1] == heads(p, plain, P + 59 * 0.05)[0][0]
    assert heads(p, plain, P)[0][0] - heads(p, first, P)[0][0] == pytest.approx(
        offset * PPM, abs=1)


def test_a_large_correction_snaps():
    first, second, plain = two_polls(1.5)       # 9.6 px: a real change, not jitter
    p = make_plugin()
    assert math.hypot(*second.corrections[0]) * PPM > 6
    assert heads(p, second, P) == heads(p, plain, P)
    assert heads(p, second, P) != heads(p, first, P)


def test_whether_a_correction_snaps_depends_on_the_size_drawn():
    """0.8 mi is 5.1 px on a 128-wide map (eases) and 20.5 px on a 512-wide one."""
    first, second, plain = two_polls(0.8)
    p = make_plugin()
    assert heads(p, second, P) == heads(p, first, P)
    wide = 512
    assert heads(p, second, P, width=wide) == heads(p, plain, P, width=wide)


def test_an_aircraft_new_to_the_snapshot_snaps():
    first, second, plain = two_polls(0.3, new_icao='NEW')
    p = make_plugin()
    assert second.corrections[1] == (0.0, 0.0)
    assert heads(p, second, P)[1] == heads(p, plain, P)[1]


def test_two_publishes_close_together_carry_the_first_ease_on():
    """A second publish 0.3 s into an ease starts from where the dot was drawn,
    so it does not jump either."""
    first, second, _ = two_polls(0.3)
    third = snapshot({'A': aircraft_dict('A', *at_miles(east=5.0 * MI_PER_S + 0.3, north=ROW),
                                         received_mono=P)},
                     now=P + 0.3, seq=3, prev=second, published=P + 0.3)
    p = make_plugin()
    assert heads(p, third, P + 0.3) == heads(p, second, P + 0.3)


def test_the_publisher_computes_corrections():
    """Through _publish_map_snapshot, as update() calls it, on the real clock."""
    now = time.monotonic()
    lat, lon = at_miles()
    aircraft = {'A': aircraft_dict('A', lat, lon, received_mono=now)}
    p = make_plugin(aircraft)
    p._publish_map_snapshot()
    first = p._map_snapshot
    assert first.published_mono is not None and first.corrections == ((0.0, 0.0),)

    aircraft['A'] = aircraft_dict('A', *at_miles(east=0.2), received_mono=time.monotonic())
    p._publish_map_snapshot()
    second = p._map_snapshot
    assert second.seq == first.seq + 1
    assert second.published_mono >= first.published_mono
    # The first was carrying it east from the centre for the time between, so
    # the correction is back towards there: about -0.2 mi east.
    assert second.corrections[0][0] == pytest.approx(
        -0.2 + (second.published_mono - now) * MI_PER_S, abs=0.01)

    # A config change keeps the aircraft and their corrections.
    p.show_trails = False
    p._publish_map_snapshot(geometry_only=True)
    third = p._map_snapshot
    assert third.seq == second.seq + 1
    assert (third.corrections, third.published_mono) == (second.corrections,
                                                         second.published_mono)


# ---------------------------------------------------------------------------
# Nothing moved: exactly the ordinary render
# ---------------------------------------------------------------------------

def random_sky(rng, radius, now):
    aircraft, trails = {}, {}
    for n in range(rng.choice([1, 4, 11, 23, 60])):
        icao = 'R%05d' % n
        lat = CENTER[0] + rng.uniform(-1.3, 1.3) * radius / 69.0
        lon = CENTER[1] + rng.uniform(-1.3, 1.3) * radius / 69.0
        moving = n == 0 or rng.random() < 0.8
        aircraft[icao] = aircraft_dict(
            icao, lat, lon, heading=rng.uniform(0, 360), received_mono=now,
            speed=rng.choice([120.0, 250.0, 480.0]) if moving else 10.0,
            color=rng.choice([(255, 100, 0), (0, 150, 255), (200, 0, 150)]))
        trails[icao] = [(lat - rng.uniform(-1, 2) * 0.3 / 69.0 * i,
                         lon - rng.uniform(-1, 2) * 0.3 / 69.0 * i, 1000.0 + i)
                        for i in range(rng.randrange(0, 11))][::-1]
    return aircraft, trails


@pytest.mark.parametrize("background", [False, True])
def test_a_glide_render_at_the_position_time_is_the_ordinary_render(background):
    """at == pos_mono and nothing left to ease: byte for byte what at=None draws,
    at every size, with trails, including the render width the ticker asks for."""
    rng = random.Random(2026)
    for _ in range(30):
        width, height = rng.choice([(64, 32), (128, 32), (128, 64), (192, 48), (512, 64)])
        radius = rng.choice([5, 10, 40])
        aircraft, trails = random_sky(rng, radius, T0)
        # A previous poll with every aircraft elsewhere, published long enough
        # ago that its corrections have eased out by T0.
        moved = copy.deepcopy(aircraft)
        for ac in moved.values():
            ac['lat'] += 0.01
        prev = MapSnapshot.build(1, moved, trails, center_lat=CENTER[0], center_lon=CENTER[1],
                                 map_radius_miles=radius, zoom_factor=1.0,
                                 show_trails=True, now_mono=T0 - EASE_SECONDS - 1)
        for published, before in ((T0 - EASE_SECONDS, prev), (T0, None)):
            snap = MapSnapshot.build(2, aircraft, trails, center_lat=CENTER[0],
                                     center_lon=CENTER[1], map_radius_miles=radius,
                                     zoom_factor=1.0, show_trails=rng.random() < 0.8,
                                     now_mono=published).with_corrections(before, published)
            assert any(a.can_extrapolate for a in snap.aircraft)
            if before is not None:
                assert any(c != (0.0, 0.0) for c in snap.corrections)
            p = make_plugin(width=width, height=height)
            p.map_radius_miles = radius
            p._map_snapshot = snap
            if background:
                enable_map_background(p)
            bg = p._get_map_background(CENTER[0], CENTER[1], allow_network=False)
            assert draw(p, snap, T0, width, height, bg).tobytes() == \
                draw(p, snap, None, width, height, bg).tobytes()
            assert p._render_map_image(at=T0).tobytes() == p._render_map_image().tobytes()


# ---------------------------------------------------------------------------
# Trails
# ---------------------------------------------------------------------------

def trailed_sky():
    """Moving east 2 mi north of the centre (row 19), a trail behind it that ends,
    as update() builds them, at the reported position."""
    lat, lon = at_miles(north=2.0)
    trail = [at_miles(east=-1.5 + 0.5 * i, north=2.0) + (1000.0 + i,) for i in range(4)]
    return {'A': aircraft_dict('A', lat, lon)}, {'A': trail}


def test_a_moved_head_takes_its_trail_with_it():
    """The trail ends on the report, so that end moves with the dot: the last
    segment runs from the point before it to the dot, faded as it always is."""
    aircraft, trails = trailed_sky()
    snap = snapshot(aircraft, trails)
    p = make_plugin(show_trails=True)
    projection = p._map_projection(snap, W, H)
    assert projection.trails[0] == ((54, 19), (57, 19), (60, 19), (64, 19))
    assert projection.heads[0] == (64, 19)

    img = draw(p, snap, T0 + 10.0)
    head = heads(p, snap, T0 + 10.0)[0]
    assert head == (71, 19)
    assert pixels_of(img, HEAD) == [head]
    last = projection.trail_colors[0][-1]
    assert last == tuple(int(c * int(255 * 3 / 4) / 255) for c in COLOR)
    for x in range(60, head[0]):
        assert img.getpixel((x, 19)) == last, x
    assert img.getpixel((55, 19)) == projection.trail_colors[0][0]
    assert img.getpixel((head[0] + 1, 19)) == (0, 0, 0)


@pytest.mark.parametrize("width", [W, 512])
def test_a_trail_never_runs_past_a_dot_eased_in_from_behind(width):
    """A poll whose report lands ahead of where the dot was being carried eases
    the dot in from behind its report. The trail, which ends on the report,
    must stop at the dot rather than poke out in front of it -- also when the
    dot is behind the trail point before the report too."""
    ppm = width / (2 * RADIUS)
    lat, lon = at_miles(north=ROW)
    first = snapshot({'A': aircraft_dict('A', lat, lon)}, published=T0)
    report = 5.0 * MI_PER_S + 5.0 / ppm             # 5 px ahead of the glide: eases
    step = 2.5 / ppm                                # trail points 2.5 px apart
    trail = {'A': [at_miles(east=report - step * i, north=ROW) + (1000.0 + i,)
                   for i in range(4)][::-1]}
    second = snapshot({'A': aircraft_dict('A', *at_miles(east=report, north=ROW),
                                          received_mono=P)},
                      trail, now=P, seq=2, prev=first, published=P)
    p = make_plugin()
    reported = p._map_projection(second, width, H).heads[0]
    behind = 0
    for i in range(40):
        at = P + i * 0.05
        img = draw(p, second, at, width=width)
        head = heads(p, second, at, width=width)[0]
        behind += head[0] < reported[0]
        lit = [x for x in range(head[0] - 12, width)
               if img.getpixel((x, head[1])) != (0, 0, 0)]
        assert max(lit) == head[0], (at, head, lit)
        # ...and still reaches it: no gap between the trail and the dot.
        assert head[0] - 1 in lit, (at, head, lit)
    assert behind > 10                              # the case under test happened


def test_a_report_repeated_at_the_trail_end_still_gives_its_direction():
    """A report that stopped moving is appended again every poll. The way the
    trail was going is then read from the last point that differs, so a dot
    behind the report still cuts the trail short."""
    projection = manager._MapProjection(
        centre=None, heads=((64, 19),),
        trails=(((54, 19), (57, 19), (60, 19), (64, 19), (64, 19)),),
        trail_colors=(((1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4)),))
    img = Image.new('RGB', (W, H))
    FlightTrackerPlugin._draw_trail(ImageDraw.Draw(img), projection, 0, (58, 19), COLOR)
    lit = [x for x in range(W) if img.getpixel((x, 19)) != (0, 0, 0)]
    assert lit == list(range(54, 59))
    assert img.getpixel((58, 19)) == (2, 2, 2)  # the fade of the segment it cut


@pytest.mark.parametrize("gap", [0.0, 1.0], ids=['trail-ends-at-head', 'trail-ends-short'])
def test_an_unmoved_head_adds_nothing_to_its_trail(gap):
    """Also when the trail stops short of the head (a trail that missed the
    latest report): the ordinary render draws no line across that gap, so an
    aircraft that has not moved must not either."""
    aircraft, trails = trailed_sky()
    trails['A'] = [at_miles(east=-1.5 - gap + 0.5 * i, north=2.0) + (1000.0 + i,)
                   for i in range(4)]
    snap = snapshot(aircraft, trails)
    p = make_plugin(show_trails=True)
    assert draw(p, snap, T0).tobytes() == draw(p, snap, None).tobytes()
    parked = snapshot({'A': dict(aircraft['A'], on_ground=True)}, trails)
    assert draw(p, parked, T0 + 10.0).tobytes() == draw(p, parked, None).tobytes()


def test_no_trail_segment_with_trails_off():
    aircraft, trails = trailed_sky()
    snap = snapshot(aircraft, trails, show_trails=False)
    p = make_plugin(show_trails=False)
    img = draw(p, snap, T0 + 10.0)
    assert pixels_of(img, COLOR) == []
    assert pixels_of(img, HEAD) == [(71, 19)]


# ---------------------------------------------------------------------------
# get_vegas_elements(): the locked render
# ---------------------------------------------------------------------------

def published_plugin(width=W, height=H, background=False):
    """A tracker in map mode with a moving aircraft, published on the real clock."""
    now = time.monotonic()
    aircraft, trails = trailed_sky()
    aircraft['A']['received_mono'] = now
    p = make_plugin(aircraft, trails, width=width, height=height)
    if background:
        enable_map_background(p)
    p._publish_map_snapshot()
    return p


@needs_core
def test_the_map_is_one_live_element_at_the_render_width():
    p = published_plugin()
    p._vegas_render_width = 96                  # as the ticker asks for it
    elements = p.get_vegas_elements()
    assert isinstance(elements, list) and len(elements) == 1
    element = elements[0]
    assert isinstance(element, manager.VegasElement)
    assert element.key == 'map' and element.live
    assert element.image.size == (96, H)
    assert element.refresh_hz == 4.0
    assert element.version == (p._map_snapshot.seq, 96, H)
    remembered = p._glide_bg
    assert (remembered.width, remembered.height) == (96, H)
    assert remembered.snap is p._map_snapshot


@needs_core
def test_the_element_follows_map_glide_hz():
    p = published_plugin()
    p.map_glide_hz = 7
    assert p.get_vegas_elements()[0].refresh_hz == 7.0


@needs_core
def test_the_locked_render_draws_now_and_uses_the_tile_cache_only():
    p = published_plugin(background=True)
    seen = {}
    real_bg, real_heads = p._get_map_background, p._draw_heads

    def bg_spy(*a, **k):
        seen['allow_network'] = k.get('allow_network')
        return real_bg(*a, **k)

    def heads_spy(img, snap, at=None):
        seen['at'] = at
        return real_heads(img, snap, at=at)
    p._get_map_background, p._draw_heads = bg_spy, heads_spy
    before = time.monotonic()
    p.get_vegas_elements()
    assert seen['allow_network'] is False
    assert before <= seen['at'] <= time.monotonic()
    assert p._glide_bg.image is not None


@needs_core
@pytest.mark.parametrize("change", ['glide-off', 'stats', 'area-mode', 'no-core'])
def test_no_element_unless_gliding_the_map(change, monkeypatch):
    p = published_plugin()
    if change == 'glide-off':
        p.map_glide = False
    elif change == 'stats':
        p.display_mode = 'stats'
    elif change == 'area-mode':
        p.display_mode = 'auto'
        p.anchor_airport = 'KTPA'
        p._get_anchor_aircraft = lambda: [p.aircraft_data['A']]
    else:
        monkeypatch.setattr(manager, 'VegasElement', None)
    assert p.get_vegas_elements() is None
    assert getattr(p, '_glide_bg', None) is None


@needs_core
def test_auto_mode_with_only_aircraft_is_the_map():
    p = published_plugin()
    p.display_mode = 'auto'
    assert p._resolve_vegas_mode() == 'map'
    assert p.get_vegas_elements() is not None


@needs_core
def test_a_failing_render_returns_none():
    p = published_plugin()

    def boom(*a, **k):
        raise RuntimeError("render failed")
    p._render_map_image = boom
    assert p.get_vegas_elements() is None


# ---------------------------------------------------------------------------
# redraw_vegas_element(): the lock-free redraw
# ---------------------------------------------------------------------------

class _Untouchable(dict):
    """A mapping that fails the test on any read."""

    def _boom(self, *a, **k):
        raise AssertionError("the redraw read the live aircraft dicts")

    __getitem__ = __iter__ = __len__ = __contains__ = get = items = values = keys = _boom


def rendered_plugin(width=96, background=True):
    p = published_plugin(background=background)
    p._vegas_render_width = width
    p.get_vegas_elements()
    p._vegas_render_width = None
    return p


@needs_core
def test_a_redraw_is_exactly_the_size_asked():
    p = rendered_plugin()
    img = p.redraw_vegas_element('map', 96, H, time.monotonic())
    assert isinstance(img, Image.Image)
    assert img.size == (96, H) and img.mode == 'RGB'


@needs_core
def test_a_redraw_is_the_locked_render_at_the_same_time():
    p = rendered_plugin()
    at = time.monotonic() + 3.0
    expected = draw(p, p._map_snapshot, at, 96, H, p._glide_bg.image)
    assert p._glide_bg.image is not None
    assert p.redraw_vegas_element('map', 96, H, at).tobytes() == expected.tobytes()


@needs_core
def test_a_redraw_moves_the_aircraft():
    p = rendered_plugin(background=False)
    snap = p._map_snapshot
    now = snap.aircraft[0].pos_mono
    first = pixels_of(p.redraw_vegas_element('map', 96, H, now), HEAD)
    later = pixels_of(p.redraw_vegas_element('map', 96, H, now + 10.0), HEAD)
    assert len(first) == len(later) == 1
    assert later[0][0] > first[0][0] and later[0][1] == first[0][1]


@needs_core
@pytest.mark.parametrize("key,width,height", [
    ('other', 96, H), ('map', 128, H), ('map', 96, 32), ('map', 95, H)])
def test_a_redraw_it_cannot_do_is_none(key, width, height):
    p = rendered_plugin()
    assert p.redraw_vegas_element(key, width, height, time.monotonic()) is None


def test_no_redraw_before_a_locked_render():
    p = published_plugin()
    assert p.redraw_vegas_element('map', W, H, time.monotonic()) is None


@needs_core
def test_a_redraw_never_reads_aircraft_data():
    p = rendered_plugin()
    at = time.monotonic() + 2.0
    before = p.redraw_vegas_element('map', 96, H, at).tobytes()

    # What update() does to the dicts in place, without publishing yet.
    p.aircraft_data['A']['lat'] += 0.05
    p.aircraft_data['B'] = aircraft_dict('B', *at_miles(north=-3.0))
    p.aircraft_trails['A'].append((CENTER[0], CENTER[1], 5.0))
    assert p.redraw_vegas_element('map', 96, H, at).tobytes() == before

    p.aircraft_data = _Untouchable()
    p.aircraft_trails = _Untouchable()
    assert p.redraw_vegas_element('map', 96, H, at).tobytes() == before


@needs_core
def test_a_redraw_never_touches_the_tile_cache_or_the_network(monkeypatch):
    p = rendered_plugin()
    at = time.monotonic() + 1.0
    expected = p.redraw_vegas_element('map', 96, H, at).tobytes()
    touched = []

    def forbidden(name):
        def boom(*a, **k):
            touched.append(name)
            raise AssertionError(f"the redraw called {name}")
        return boom
    for name in ('_get_map_background', '_fetch_tile', '_is_tile_cached',
                 '_get_tile_cache_path', '_prefetch_map_tiles', '_note_tile_wanted',
                 '_current_map_snapshot', '_resolve_vegas_mode'):
        setattr(p, name, forbidden(name))
    monkeypatch.setattr(manager.requests, 'get', forbidden('requests.get'))
    monkeypatch.setattr(Image, 'open', forbidden('Image.open'))

    img = p.redraw_vegas_element('map', 96, H, at)
    assert touched == []
    assert img is not None and img.tobytes() == expected


@needs_core
def test_the_reused_background_is_never_drawn_on():
    """The remembered background is the composite cache's own image, read by
    the lock-free redraw: every render must draw on a copy of it."""
    p = rendered_plugin()
    bg = p._glide_bg.image
    assert bg is p.cached_map_bgs[(96, H)]
    before = bg.tobytes()
    now = time.monotonic()
    for i in range(5):
        p.redraw_vegas_element('map', 96, H, now + i * 3.0)
    p._vegas_render_width = 96
    p.get_vegas_elements()
    assert p._glide_bg.image is bg
    assert bg.tobytes() == before


@needs_core
def test_a_reused_partial_background_is_never_drawn_on():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    t.aircraft_data, t.aircraft_trails = trailed_sky()
    t.aircraft_data['A']['received_mono'] = time.monotonic()
    t._publish_map_snapshot()
    t.get_vegas_elements()
    bg = t._glide_bg.image
    assert bg is t._partial_map_bg.image and not t.cached_map_bgs
    before = bg.tobytes()
    for i in range(5):
        t.redraw_vegas_element('map', W, H, time.monotonic() + i * 3.0)
    t.get_vegas_elements()
    assert t._glide_bg.image is bg
    assert bg.tobytes() == before


@needs_core
def test_a_redraw_draws_the_latest_published_snapshot():
    """A poll published after the locked render shows at once (it eases in),
    without waiting for the next locked render."""
    p = rendered_plugin(background=False)
    p.aircraft_data['B'] = aircraft_dict('B', *at_miles(north=-3.0),
                                         received_mono=time.monotonic(), color=(250, 0, 0))
    p._publish_map_snapshot()
    img = p.redraw_vegas_element('map', 96, H, time.monotonic())
    assert len(pixels_of(img, (255, 0, 0))) == 1


@needs_core
def test_a_moved_view_waits_for_the_locked_render():
    """The remembered background is for the old view: rather than draw the new
    view over it, the redraw skips until the next locked render."""
    p = rendered_plugin()
    p.center_lat += 0.2
    p._publish_map_snapshot(geometry_only=True)
    assert p.redraw_vegas_element('map', 96, H, time.monotonic()) is None
    p._vegas_render_width = 96
    p.get_vegas_elements()
    assert p.redraw_vegas_element('map', 96, H, time.monotonic()) is not None


@needs_core
def test_trails_toggled_redraw_without_a_locked_render():
    """show_trails is not part of the background, so the redraw carries on."""
    p = rendered_plugin()
    p.show_trails = False
    p._publish_map_snapshot(geometry_only=True)
    assert p.redraw_vegas_element('map', 96, H, time.monotonic()) is not None


@needs_core
def test_a_redraw_never_raises(caplog):
    p = rendered_plugin()

    def boom(*a, **k):
        raise RuntimeError("layer failed")
    p._map_layer = boom
    with caplog.at_level(logging.DEBUG, logger="test-flights-glide"):
        for _ in range(3):
            assert p.redraw_vegas_element('map', 96, H, time.monotonic()) is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1                   # once, then quietly


@needs_core
def test_redraws_alongside_publishing_update():
    """The redraw runs while update() publishes on another thread: every result
    is the right size or None, and nothing raises."""
    p = rendered_plugin(background=False)
    failures, results = [], []
    stop = threading.Event()

    def publisher():
        rng = random.Random(7)
        while not stop.is_set():
            for icao in list(p.aircraft_data):
                p.aircraft_data[icao]['lat'] += rng.uniform(-0.002, 0.002)
                p.aircraft_data[icao]['received_mono'] = time.monotonic()
                p.aircraft_trails[icao].append((p.aircraft_data[icao]['lat'],
                                                p.aircraft_data[icao]['lon'], 1.0))
                del p.aircraft_trails[icao][:-10]
            p._publish_map_snapshot()

    def redrawer():
        try:
            while not stop.is_set():
                results.append(p.redraw_vegas_element('map', 96, H, time.monotonic()))
        except Exception as exc:  # pragma: no cover - the failure being tested for
            failures.append(exc)

    threads = [threading.Thread(target=publisher), threading.Thread(target=redrawer)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join()
    assert failures == []
    assert results and all(r is not None and r.size == (96, H) for r in results)
    assert p._map_snapshot.seq > 2


# ---------------------------------------------------------------------------
# A partial tile composite is reused briefly
# ---------------------------------------------------------------------------

def tile_tracker():
    """A tracker compositing from a stub tile cache (as test_map_cold_start)."""
    t = make_plugin()
    t.map_bg_enabled = True
    t.map_radius_miles = 25.0
    t.tile_size = 256
    t.map_brightness = t.map_contrast = t.map_saturation = t.fade_intensity = 1.0
    t.custom_tile_server = None
    t.tile_provider = 'osm'
    t.cached_map_bgs = {}
    t.last_map_center = None
    t.last_map_zoom = None
    t.cached_tiles = set()
    t.requested = []

    def fetch(x, y, zoom, allow_network=True):
        t.requested.append((x, y, zoom))
        if (x, y, zoom) in t.cached_tiles:
            return Image.new('RGB', (256, 256), (10, 80, 10))
        return None
    t._fetch_tile = fetch
    t.requested = []
    t._get_map_background(*CENTER, allow_network=False)
    t.grid = list(t.requested)
    t.requested = []
    t._partial_map_bg = None
    return t


def test_a_partial_composite_is_reused_while_no_tile_arrives():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    first = t._get_map_background(*CENTER, allow_network=False)
    assert first is not None and not t.cached_map_bgs        # partial: not cached for good
    missing = [tile for tile in t.grid if tile not in t.cached_tiles]

    t.requested = []
    again = t._get_map_background(*CENTER, allow_network=False)
    assert again is first
    # Only the missing tiles were looked up (cache only), none of those it has.
    assert t.requested == missing


def test_a_tile_arriving_ends_the_reuse():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    first = t._get_map_background(*CENTER, allow_network=False)
    t.cached_tiles.add(t.grid[-1])
    again = t._get_map_background(*CENTER, allow_network=False)
    assert again is not first


def test_the_reuse_lasts_10s():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    first = t._get_map_background(*CENTER, allow_network=False)
    t._partial_map_bg = t._partial_map_bg._replace(made=t._partial_map_bg.made - 9.5)
    assert t._get_map_background(*CENTER, allow_network=False) is first
    t._partial_map_bg = t._partial_map_bg._replace(made=t._partial_map_bg.made - 0.6)
    assert t._get_map_background(*CENTER, allow_network=False) is not first


def test_the_reuse_is_for_the_same_view_and_size_only():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    first = t._get_map_background(*CENTER, allow_network=False)
    t.display_manager.matrix.width = 64
    narrow = t._get_map_background(*CENTER, allow_network=False)
    assert narrow is not first and narrow.size == (64, H)


def test_a_complete_composite_is_cached_as_before():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    t._get_map_background(*CENTER, allow_network=False)
    t.cached_tiles = set(t.grid)
    full = t._get_map_background(*CENTER, allow_network=False)
    assert t.cached_map_bgs == {(W, H): full}
    assert t._partial_map_bg is None
    t.requested = []
    assert t._get_map_background(*CENTER, allow_network=False) is full
    assert t.requested == []


def test_a_network_render_does_not_reuse_it():
    t = tile_tracker()
    t.cached_tiles = set(t.grid[:len(t.grid) // 2])
    first = t._get_map_background(*CENTER, allow_network=False)
    t.requested = []
    t._get_map_background(*CENTER, allow_network=True)
    assert len(t.requested) == len(t.grid)
    assert first is not None


# ---------------------------------------------------------------------------
# Shown in the ticker counts as visible
# ---------------------------------------------------------------------------

def test_visibility_follows_the_ticker_too():
    p = make_plugin()
    p._last_displayed_time = 0.0
    p._display_idle_threshold = 30.0
    now = time.time()
    p._vegas_seen_at = 0.0
    assert not p._is_visible(now)
    p._vegas_seen_at = now - 10
    assert p._is_visible(now)
    p._vegas_seen_at = now - 31
    assert not p._is_visible(now)
    p._last_displayed_time = now - 5
    assert p._is_visible(now)


def test_a_shell_without_the_attribute_is_hidden():
    p = make_plugin()
    p._last_displayed_time = 0.0
    p._display_idle_threshold = 30.0
    assert not p._is_visible(time.time())


@pytest.mark.parametrize("hook", ['get_vegas_content', 'get_vegas_elements'])
def test_the_ticker_asking_marks_the_plugin_visible(hook):
    p = published_plugin()
    p._vegas_seen_at = 0.0
    before = time.time()
    getattr(p, hook)()
    assert before <= p._vegas_seen_at <= time.time()


def _updating_shell():
    """A tracker set up for update()'s adsb.fi branch; its visible-only steps
    (FR24 enrichment, callsign queue, weather) record themselves in ``ran``."""
    p = make_plugin()
    p.data_source = 'adsbfi'

    class _Fetcher:
        def fetch(self, *a, **k):
            return {}
    p._fetcher = _Fetcher()
    p.all_aircraft_data = {}
    p.fr24_enrichment = True
    p.last_fr24_enrichment = time.time()
    p.pending_fr24_details, p.pending_flight_plans = {}, set()
    p.use_offline_db = False
    p.skyaware_url = ''
    p.tracked_flights_cfg = []
    p.metar_enabled = True
    p.metar_airports = ['KTPA']
    p._lock_icao = None
    p._last_displayed_time = 0.0
    p._display_idle_threshold = 30.0
    p.update_interval = p.live_update_interval = 5
    p._prefetch_map_tiles = lambda: None
    p._update_from_fetcher = lambda: None
    p._enrich_from_offline_db = lambda: None
    p._background_fetch_fr24_details = lambda: None
    p.ran = []
    p._maybe_refresh_fr24_enrichment = lambda: p.ran.append('enrichment')
    p._queue_interesting_callsigns = lambda: p.ran.append('queue')
    p._service_metar = lambda now: p.ran.append('weather')
    return p


def test_update_runs_the_visible_steps_while_in_the_ticker():
    """Enrichment runs only while visible; in Vegas display() is never called.
    Weather does not: the ticker has no view of it, only display() does."""
    p = _updating_shell()
    p.last_fetch = 0
    p._vegas_seen_at = 0.0
    p.update()
    assert p.ran == []                          # hidden: nothing fetched for it

    p.ran.clear()
    p.last_fetch = 0
    p._vegas_seen_at = time.time()              # in the ticker
    p.update()
    assert p.ran == ['enrichment', 'queue']

    p.ran.clear()
    p.last_fetch = 0
    p._last_displayed_time = time.time()        # in the rotation
    p.update()
    assert p.ran == ['enrichment', 'queue', 'weather']


@pytest.mark.parametrize("hook", ['get_vegas_content', 'get_vegas_elements'])
def test_coming_into_the_ticker_makes_enrichment_due(hook):
    """As display() does for the rotation: back from hidden, FR24 enrichment
    refreshes at the next update() instead of a whole interval later."""
    p = _updating_shell()
    p.aircraft_data, p.aircraft_trails = trailed_sky()
    p._publish_map_snapshot()
    p._vegas_seen_at = 0.0
    getattr(p, hook)()
    assert p.last_fr24_enrichment == 0.0

    p.last_fr24_enrichment = 123.0              # refreshed since
    getattr(p, hook)()                          # still on screen: not again
    assert p.last_fr24_enrichment == 123.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (4, 4), (1, 1), (10, 10), (2.5, 2.5), (0, 1), (-3, 1), (11, 10), (1e9, 10),
    (None, 4), ('fast', 4), (True, 4), (float('nan'), 4)])
def test_map_glide_hz_is_clamped(value, expected):
    assert FlightTrackerPlugin._glide_hz(value) == expected


def _real_tracker(config):
    class _Cache:
        cache_dir = tempfile.mkdtemp()

    class _PluginManager:
        def __init__(self):
            self.notified = []

        def notify_data_changed(self, plugin_id):
            self.notified.append(plugin_id)

    return FlightTrackerPlugin('ledmatrix-flights', config,
                               display_manager=_DisplayManager(),
                               cache_manager=_Cache(), plugin_manager=_PluginManager())


BARE = {'data_source': 'skyaware', 'center_latitude': CENTER[0],
        'center_longitude': CENTER[1], 'map_background': {'enabled': False}}


def _schema_default(key):
    import json
    with open(HERE / 'config_schema.json', encoding='utf-8') as f:
        return json.load(f)['properties'][key]['default']


@needs_core
def test_defaults_match_the_schema():
    tracker = _real_tracker(dict(BARE))
    assert tracker.map_glide == _schema_default('map_glide') is True
    assert tracker.map_glide_hz == _schema_default('map_glide_hz') == 4
    tracker.on_config_change(dict(BARE))
    assert tracker.map_glide is True and tracker.map_glide_hz == 4


@needs_core
def test_a_config_change_applies_live_and_tells_the_ticker():
    tracker = _real_tracker(dict(BARE))
    tracker._glide_bg = 'SENTINEL'
    tracker._partial_map_bg = 'SENTINEL'
    tracker.plugin_manager.notified.clear()
    tracker.on_config_change(dict(BARE, map_glide=False, map_glide_hz=7))
    assert (tracker.map_glide, tracker.map_glide_hz) == (False, 7)
    assert tracker._glide_bg is None and tracker._partial_map_bg is None
    assert tracker.plugin_manager.notified == ['ledmatrix-flights']
    tracker.display_mode = 'map'
    assert tracker.get_vegas_elements() is None

    tracker.on_config_change(dict(BARE, map_glide_hz=99))
    assert (tracker.map_glide, tracker.map_glide_hz) == (True, 10)


@needs_core
def test_a_failing_notify_does_not_fail_the_config_change():
    tracker = _real_tracker(dict(BARE))

    def boom():
        raise RuntimeError("ticker gone")
    tracker.notify_vegas_data_changed = boom
    tracker.on_config_change(dict(BARE, map_glide_hz=6))
    assert tracker.map_glide_hz == 6


@needs_core
def test_a_real_tracker_glides_end_to_end():
    """Construction to redraw on a real tracker: publish, locked render, redraw."""
    tracker = _real_tracker(dict(BARE, display_mode='map'))
    aircraft, trails = trailed_sky()
    aircraft['A']['received_mono'] = time.monotonic()
    tracker.aircraft_data, tracker.aircraft_trails = aircraft, trails
    tracker._publish_map_snapshot()
    elements = tracker.get_vegas_elements()
    assert elements and elements[0].image.size == (W, H)
    img = tracker.redraw_vegas_element('map', W, H, time.monotonic() + 5.0)
    assert img is not None and img.size == (W, H)
    assert tracker._resolve_vegas_mode() == 'map'
