"""
Every aircraft records how old its position was, by the source's own clock.

The map will later move aircraft between polls (dead reckoning), which needs
to know when each position was true -- not when we happened to poll. Each
source says so differently: readsb-style feeds (SkyAware, adsb.fi, adsb.lol)
as seconds before the payload's ``now`` (``seen_pos``, else ``seen``), OpenSky
as epoch times against its rounded-down ``time``, FR24's feed.js as an epoch
at index 10. The payload's own stamp trails the moment it was sent (OpenSky's
by 5-15 s), so that gap is added back from the response's Date header. These
pin, per source, from payloads shaped like the real ones:

  * pos_age is that age, clamped to 0..30 s, and pos_stale says it was older;
  * missing, garbage or implausible times give 0 and never cost the aircraft;
  * track_valid says the heading came from a real track field, not the 0
    every source falls back to;
  * received_mono is when the response arrived (a fallback payload keeps its
    original receipt and lag), and last_seen is untouched.

Run: <core-venv>/bin/python -m pytest plugins/ledmatrix-flights/test_position_time.py
"""

import copy
import email.utils
import logging
import os
import sys
import time
import types
from pathlib import Path

import pytest

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
    import src.plugin_system.base_plugin  # noqa: F401
except ImportError:
    # No core: stand in for BasePlugin. Nothing here needs its behaviour.
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

import fetcher  # noqa: E402
import manager  # noqa: E402
from utils import (  # noqa: E402
    MAX_POS_AGE_SECONDS, clamp_pos_age, fr24_pos_age, http_date, is_number,
    payload_lag, position_age, source_send_time,
)

CENTER = (27.9506, -82.4572)          # Tampa, the plugin's default centre
NOW = 1_727_700_000.0                 # the wall clock at receipt, pinned
HUGE = 10 ** 400                      # a JSON integer no float can hold
ALT_COLORS = {'0': [255, 100, 0], '10000': [0, 200, 150], '40000': [150, 0, 200]}
approx = pytest.approx


def _date(epoch):
    """An HTTP Date header for ``epoch``: whole seconds, as servers send it."""
    return email.utils.formatdate(epoch, usegmt=True)


class _Response:
    status_code = 200

    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = dict(headers or {})

    def raise_for_status(self):
        return None

    def json(self):
        return copy.deepcopy(self._payload)


@pytest.fixture
def wall_clock(monkeypatch):
    """Pin time.time() to NOW; time.monotonic() is left alone."""
    monkeypatch.setattr(time, "time", lambda: NOW)
    return NOW


def _serve(monkeypatch, module, payload, date=None):
    """Answer every request with ``payload``, sent at ``date`` by the source's clock."""
    headers = {"Date": _date(date)} if date is not None else {}
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: _Response(payload, headers))


# ---------------------------------------------------------------------------
# Payloads, shaped like what each source actually returns (trimmed to the
# fields the plugin reads plus a few it ignores, so a key-name slip shows).
# ---------------------------------------------------------------------------

# dump1090-fa / readsb aircraft.json, as SkyAware serves it. `now` is epoch
# seconds; the feeder's web server sends it a moment later.
SKYAWARE_DATE = NOW - 1               # sent between NOW - 1 and NOW
SKYAWARE_LAG = 0.75                   # (SKYAWARE_DATE + 0.5) - now
SKYAWARE = {
    "now": NOW - 1.25,
    "messages": 48213377,
    "aircraft": [
        {"hex": "a4f2b1", "type": "adsb_icao", "flight": "DAL1234 ", "alt_baro": 12000,
         "alt_geom": 12375, "gs": 312.4, "track": 47.3, "baro_rate": -832,
         "squawk": "4521", "category": "A3", "lat": 27.998, "lon": -82.401, "nic": 8,
         "rc": 186, "seen_pos": 2.7, "version": 2, "mlat": [], "tisb": [],
         "messages": 1873, "seen": 0.4, "rssi": -21.3},
        # No seen_pos (older dump1090 forks): seen stands in. No track either,
        # only readsb's true_heading (sent mostly on the ground), which the
        # SkyAware path does not take its heading from.
        {"hex": "a1c3d9", "flight": "N512TX  ", "alt_baro": 2400, "gs": 104.0,
         "true_heading": 190.0, "lat": 27.93, "lon": -82.50, "seen": 6.5},
        # seen_pos garbage: seen stands in.
        {"hex": "ab11c2", "alt_baro": 8000, "gs": 250, "track": 0, "lat": 27.95,
         "lon": -82.44, "seen_pos": "stale", "seen": 1.25},
        # Older than the clamp: readsb keeps lat/lon for up to 60 s.
        {"hex": "ac0011", "alt_baro": 35000, "gs": 470, "track": 270.0, "lat": 27.9,
         "lon": -82.47, "seen_pos": 58.0, "seen": 0.1},
        # On the ground, no track, no times at all.
        {"hex": "a00001", "alt_baro": "ground", "gs": 8.5, "lat": 27.975, "lon": -82.533},
        # Negative (clock nonsense) and a null track.
        {"hex": "a00002", "alt_baro": 1500, "gs": 90, "track": None, "lat": 27.96,
         "lon": -82.45, "seen_pos": -3.0, "seen": 0.0},
        # A bool is not a number, whatever JSON says.
        {"hex": "a00003", "alt_baro": 1500, "gs": 90, "track": True, "lat": 27.961,
         "lon": -82.451, "seen_pos": True, "seen": 2.0},
        # An integer too big for a float, in the time and the track.
        {"hex": "a00007", "alt_baro": 1500, "gs": 90, "track": HUGE, "lat": 27.962,
         "lon": -82.452, "seen_pos": HUGE, "seen": 1.0},
        # No position: skipped, as before.
        {"hex": "a00004", "alt_baro": 30000, "seen": 1.0},
    ],
}

# adsb.fi opendata v2 answers under "aircraft" with `now` in epoch seconds;
# adsb.lol under "ac" with `now` in epoch milliseconds.
_ADSBNET_ROWS = [
    {"hex": "a4f2b1", "type": "adsb_icao", "flight": "DAL1234 ", "r": "N820DN",
     "t": "A321", "alt_baro": 12000, "alt_geom": 12375, "gs": 312.4, "track": 47.3,
     "baro_rate": -832, "category": "A3", "lat": 27.998, "lon": -82.401,
     "seen_pos": 3.1, "seen": 0.5, "rssi": -18.2, "messages": 5521},
    {"hex": "a1c3d9", "flight": "N512TX", "alt_baro": 2400, "gs": 104.0,
     "true_heading": 190.0, "lat": 27.93, "lon": -82.50, "seen": 4.0},
    {"hex": "a00001", "alt_baro": "ground", "gs": 0, "lat": 27.975, "lon": -82.533,
     "seen_pos": "?", "seen": None},
    {"hex": "a00005", "alt_baro": 9000, "gs": 220, "track": 725.0, "lat": 27.94,
     "lon": -82.46, "seen_pos": 31.5},
    {"hex": "a00007", "alt_baro": 9000, "gs": 220, "track": HUGE, "lat": 27.941,
     "lon": -82.461, "seen_pos": HUGE, "seen": 1.0},
]
ADSBNET_DATE = NOW - 1
ADSBFI = {"aircraft": _ADSBNET_ROWS, "now": NOW - 2.0, "resultCount": 5, "ptime": 3.1}
ADSBLOL = {"ac": _ADSBNET_ROWS, "msg": "No error", "now": int((NOW - 3.0) * 1000),
           "total": 5, "ctime": int((NOW - 3.0) * 1000) + 5, "ptime": 2}

# OpenSky /api/states/all?extended=1: [icao24, callsign, origin_country,
# time_position, last_contact, lon, lat, baro_alt, on_ground, velocity,
# true_track, vertical_rate, sensors, geo_alt, squawk, spi, position_source,
# category]. `time` is rounded down to OpenSky's 5/10 s resolution and trails
# the send by that and more: 9-14 s in live calls.
OPENSKY_TIME = int(NOW) - 13
OPENSKY_DATE = NOW - 2                # sent between NOW - 2 and NOW - 1
OPENSKY_LAG = 11.5                    # (OPENSKY_DATE + 0.5) - OPENSKY_TIME
OPENSKY = {
    "time": OPENSKY_TIME,
    "states": [
        ["a4f2b1", "DAL1234 ", "United States", OPENSKY_TIME - 4, OPENSKY_TIME - 1,
         -82.401, 27.998, 3657.6, False, 160.7, 47.3, -4.2, None, 3772.0, "4521",
         False, 0, 4],
        # No time_position in the last 15 s: last_contact stands in.
        ["a1c3d9", "N512TX  ", "United States", None, OPENSKY_TIME - 7, -82.50, 27.93,
         731.5, False, 53.5, 190.0, 0.0, None, 750.0, None, False, 0, 2],
        # Garbage time_position, and no track.
        ["ab11c2", "", "United States", "soon", OPENSKY_TIME - 2, -82.44, 27.95,
         2438.4, False, 128.6, None, None, None, None, None, False, 0, 0],
        # Both times missing; on the ground.
        ["a00001", "", "United States", None, None, -82.533, 27.975, None, True,
         2.0, 0.0, None, None, None, None, False, 0, 0],
        # Older than the clamp (live OpenSky returned one 317 s old), and one
        # from the future.
        ["ac0011", "UAL88   ", "United States", OPENSKY_TIME - 95, OPENSKY_TIME - 90,
         -82.47, 27.9, 10668.0, False, 241.8, 270.0, 0.0, None, 10900.0, None,
         False, 0, 4],
        ["a00006", "", "United States", OPENSKY_TIME + 20, OPENSKY_TIME + 20, -82.46,
         27.941, 900.0, False, 60.0, 12.0, 0.0, None, 950.0, None, False, 0, 1],
        # An integer too big for a float, in time_position and the track.
        ["a00007", "", "United States", HUGE, OPENSKY_TIME - 3, -82.461, 27.942,
         900.0, False, 60.0, HUGE, 0.0, None, 950.0, None, False, 0, 1],
    ],
}


def _fr24_row(icao, lat, lon, track, stamp, *, ground=0, callsign="DAL1234"):
    # [0] icao24, [1] lat, [2] lon, [3] track, [4] alt, [5] gs, [6] squawk,
    # [7] radar, [8] type, [9] reg, [10] time, [11] origin, [12] dest,
    # [13] flight, [14] on_ground, [15] vrate, [16] callsign, [17] ?, [18] airline
    return [icao, lat, lon, track, 0 if ground else 12000, 312, "4521", "F-KTPA1",
            "A321", "N820DN", stamp, "ATL", "TPA", "DL1234", ground, -832, callsign,
            0, "DAL"]


FR24 = {
    "full_count": 13987,
    "version": 4,
    "3b2c1d4e": _fr24_row("A4F2B1", 27.998, -82.401, 47, int(NOW) - 4),
    # An hour old: the query asks for up to maxage=14400, so this is a real
    # position, and a stale one -- not a fresh one.
    "3b2c1d4f": _fr24_row("A1C3D9", 27.93, -82.50, 190, int(NOW) - 3600),
    # A small integer where the time should be: not an epoch at all.
    "3b2c1d50": _fr24_row("AB11C2", 27.95, -82.44, 0, 12),
    # In the future but inside the skew window: clamps to 0.
    "3b2c1d51": _fr24_row("AC0011", 27.9, -82.47, 270, int(NOW) + 30),
    # Older than the clamp: stale.
    "3b2c1d52": _fr24_row("A00006", 27.941, -82.46, 12, int(NOW) - 75),
    # Garbage time and track, on the ground.
    "3b2c1d53": _fr24_row("A00001", 27.975, -82.533, "", "n/a", ground=1),
    # Too far ahead, and further back than the query's maxage: not times.
    "3b2c1d54": _fr24_row("A00008", 27.942, -82.462, 90, int(NOW) + 600),
    "3b2c1d55": _fr24_row("A00009", 27.943, -82.463, 90, int(NOW) - 20000),
    # An integer too big for a float, in the time and the track.
    "3b2c1d56": _fr24_row("A00007", 27.944, -82.464, HUGE, HUGE),
    "stats": {"total": {"ads-b": 11020, "mlat": 1210}, "visible": {"ads-b": 12}},
}


def _plugin_shell():
    p = object.__new__(manager.FlightTrackerPlugin)
    p.logger = logging.getLogger("test-flights-position-time")
    p.center_lat, p.center_lon = CENTER
    p.map_radius_miles = 10
    p.zoom_factor = 1.0
    p.show_trails = True
    p.trail_length = 10
    p.altitude_colors = ALT_COLORS
    p.aircraft_data, p.all_aircraft_data, p.aircraft_trails = {}, {}, {}
    p.flight_records_enabled = False
    p._fr24_headers = {}
    return p


# ---------------------------------------------------------------------------
# The helpers every source shares
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (2.7, 2.7), (0, 0.0), (30, 30.0), (30.5, MAX_POS_AGE_SECONDS), (-1, 0.0),
    (None, 0.0), ("3", 0.0), (True, 0.0), (float("nan"), 0.0), (float("inf"), 0.0),
    (HUGE, 0.0), (-HUGE, 0.0),
])
def test_clamp_pos_age(raw, expected):
    assert clamp_pos_age(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (4.0, (4.0, False)), (30, (30.0, False)), (30.5, (30.0, True)),
    (121, (30.0, True)), (-5, (0.0, False)), (None, (0.0, False)),
    ("7", (0.0, False)), (float("nan"), (0.0, False)), (HUGE, (0.0, False)),
])
def test_position_age_keeps_what_the_clamp_drops(raw, expected):
    assert position_age(raw) == expected


def test_a_huge_integer_is_not_a_number():
    """math.isfinite() raises OverflowError on it; that must not cost a poll."""
    assert not is_number(HUGE)
    assert not is_number(-HUGE)
    assert is_number(10 ** 300)


def test_fr24_pos_age_needs_a_plausible_epoch():
    def age(stamp):
        return fr24_pos_age(_fr24_row("A", 0, 0, 0, stamp), NOW)
    assert age(NOW - 4) == 4.0
    assert age(NOW - 121) == 121.0         # a real, stale position
    assert age(NOW - 14400) == 14400.0     # as old as the query's maxage
    assert age(NOW - 14401) is None        # older than the query can return
    assert age(NOW + 120) == -120.0        # clock skew; clamps to 0
    assert age(NOW + 121) is None
    assert age(None) is None
    assert age(HUGE) is None
    assert fr24_pos_age(["A", 0, 0, 0], NOW) is None   # too short to have one


def test_http_date():
    assert http_date(_Response({}, {"Date": _date(NOW)})) == NOW
    assert http_date(_Response({}, {})) is None
    assert http_date(_Response({}, {"Date": "soon"})) is None
    assert http_date(object()) is None     # a response with no headers at all


def test_source_send_time():
    # The Date header drops the fraction; half a second goes back on.
    assert source_send_time(_Response({}, {"Date": _date(NOW - 3)}), NOW) == NOW - 2.5
    # Without one, our clock at receipt stands in.
    assert source_send_time(_Response({}, {}), NOW) == NOW
    assert source_send_time(_Response({}, {"Date": "garbage"}), NOW) == NOW


@pytest.mark.parametrize("stamp,sent,expected", [
    (NOW - 2.0, NOW, 2.0),                 # epoch seconds (SkyAware, adsb.fi)
    ((NOW - 2.5) * 1000, NOW, 2.5),        # epoch milliseconds (adsb.lol)
    (NOW + 0.3, NOW, 0.0),                 # stamped "after" the send: no lag
    (NOW - 61, NOW, 0.0),                  # a disagreeing clock, not a delay
    (None, NOW, 0.0), ("now", NOW, 0.0), (HUGE, NOW, 0.0), (NOW, None, 0.0),
])
def test_payload_lag(stamp, sent, expected):
    assert payload_lag(stamp, sent) == approx(expected)


# ---------------------------------------------------------------------------
# SkyAware: the manager's own path
# ---------------------------------------------------------------------------

def _skyaware_ingest(monkeypatch, payload=SKYAWARE, date=SKYAWARE_DATE):
    p = _plugin_shell()
    p.skyaware_url = "http://feeder.local/data/aircraft.json"
    p._fetch_failures = 0
    p._fetch_retry_after = 0.0
    p._last_raw_payload = None
    p._last_raw_payload_at = 0.0
    p._last_raw_payload_lag = 0.0
    _serve(monkeypatch, manager, payload, date)
    before = time.monotonic()
    data = p._fetch_aircraft_data()
    after = time.monotonic()
    assert data is p._last_raw_payload
    p._process_aircraft_data(data, received_mono=p._last_raw_payload_mono,
                             lag=p._last_raw_payload_lag)
    return p, before, after


def _check_skyaware_ages(ac, lag):
    assert ac["A4F2B1"]["pos_age"] == approx(2.7 + lag)          # seen_pos
    assert ac["A1C3D9"]["pos_age"] == approx(6.5 + lag)          # no seen_pos: seen
    assert ac["AB11C2"]["pos_age"] == approx(1.25 + lag)         # garbage seen_pos: seen
    assert ac["AC0011"]["pos_age"] == MAX_POS_AGE_SECONDS        # clamped...
    assert ac["AC0011"]["pos_stale"] is True                     # ...and said so
    assert ac["A00001"]["pos_age"] == 0.0                        # neither
    assert ac["A00002"]["pos_age"] == 0.0                        # negative
    assert ac["A00003"]["pos_age"] == approx(2.0 + lag)          # a bool is not a time
    assert ac["A00007"]["pos_age"] == approx(1.0 + lag)          # nor is a huge int
    for icao in ("A4F2B1", "A1C3D9", "AB11C2", "A00001", "A00002", "A00003", "A00007"):
        assert ac[icao]["pos_stale"] is False, icao


def test_skyaware_pos_age(monkeypatch, wall_clock):
    p, _, _ = _skyaware_ingest(monkeypatch)
    assert p._last_raw_payload_lag == approx(SKYAWARE_LAG)
    _check_skyaware_ages(p.all_aircraft_data, SKYAWARE_LAG)
    assert "A00004" not in p.all_aircraft_data                   # no position, as before


@pytest.mark.parametrize("date,now,lag", [
    (None, NOW - 1.25, 1.25),              # no Date header: our clock at receipt
    (NOW + 3600, NOW - 1.25, 0.0),         # a Date an hour out is not believed
    (SKYAWARE_DATE, None, 0.0),            # no `now` to count from
    (SKYAWARE_DATE, "later", 0.0),
])
def test_skyaware_lag_sources(monkeypatch, wall_clock, date, now, lag):
    payload = dict(SKYAWARE, now=now)
    p, _, _ = _skyaware_ingest(monkeypatch, payload, date)
    assert p._last_raw_payload_lag == approx(lag)
    assert p.all_aircraft_data["A4F2B1"]["pos_age"] == approx(2.7 + lag)


def test_skyaware_track_valid(monkeypatch, wall_clock):
    p, _, _ = _skyaware_ingest(monkeypatch)
    ac = p.all_aircraft_data
    assert ac["A4F2B1"]["track_valid"] is True
    # true_heading is not what this path takes its heading from, so the
    # heading is the default 0 and not a real track.
    assert ac["A1C3D9"]["track_valid"] is False
    assert ac["A1C3D9"]["heading"] == 0
    assert ac["AB11C2"]["track_valid"] is True            # 0 is due north when it is sent
    assert ac["A00001"]["track_valid"] is False           # the default 0
    assert ac["A00001"]["heading"] == 0                   # ...which is still what heading holds
    assert ac["A00002"]["track_valid"] is False           # null
    assert ac["A00003"]["track_valid"] is False           # bool
    assert ac["A00007"]["track_valid"] is False           # too big for a float


def test_skyaware_receipt_time_and_last_seen(monkeypatch, wall_clock):
    p, before, after = _skyaware_ingest(monkeypatch)
    for ac in p.all_aircraft_data.values():
        assert before <= ac["received_mono"] <= after
        assert ac["last_seen"] == NOW                     # the 60 s drop still keys on this


def test_skyaware_fallback_keeps_its_original_receipt(monkeypatch, wall_clock):
    """A failed poll reuses the last payload; its positions are as old as its
    receipt, so received_mono (and its lag) must not be refreshed to the reuse."""
    p, before, after = _skyaware_ingest(monkeypatch)
    first_receipt = p._last_raw_payload_mono

    def refuse(*a, **k):
        raise manager.requests.exceptions.ConnectionError("feeder gone")
    monkeypatch.setattr(manager.requests, "get", refuse)
    # update()'s SkyAware branch, with the rest of update() out of the way.
    p.data_source = "skyaware"
    p.fr24_enrichment = False
    p.background_service_enabled = False
    p.tracked_flights_cfg = []
    p.metar_enabled = False
    p.pending_fr24_details, p.pending_flight_plans = {}, set()
    p._lock_icao = None
    p._last_displayed_time = 0.0
    p._display_idle_threshold = 30.0
    p.update_interval = p.live_update_interval = 5
    p.last_fetch = 0
    p.use_offline_db = False
    p._prefetch_map_tiles = lambda: None
    p.all_aircraft_data.clear()
    p.update()
    assert p._last_raw_payload is not None, "the fallback should have been used"
    assert p.all_aircraft_data, "the fallback should have been processed"
    for ac in p.all_aircraft_data.values():
        assert ac["received_mono"] == first_receipt
    _check_skyaware_ages(p.all_aircraft_data, SKYAWARE_LAG)


def test_skyaware_garbage_times_never_cost_the_aircraft(monkeypatch, wall_clock):
    junk = {"aircraft": [
        {"hex": "a1", "lat": 27.95, "lon": -82.45, "seen_pos": {"x": 1}, "seen": [2]},
        {"hex": "a2", "lat": 27.95, "lon": -82.45, "seen_pos": "", "track": "north"},
    ]}
    p, _, _ = _skyaware_ingest(monkeypatch, junk)
    assert p.all_aircraft_data["A1"]["pos_age"] == 0.0
    assert p.all_aircraft_data["A2"]["pos_age"] == 0.0
    assert p.all_aircraft_data["A2"]["track_valid"] is False
    assert p.all_aircraft_data["A2"]["pos_stale"] is False


def test_skyaware_fetcher_class_matches(monkeypatch, wall_clock):
    """fetcher.SkyAwareFetcher is the same source through the other door."""
    _serve(monkeypatch, fetcher, SKYAWARE, SKYAWARE_DATE)
    f = fetcher.SkyAwareFetcher("http://feeder.local/data/aircraft.json", None)
    before = time.monotonic()
    got = f.fetch(*CENTER, 30, ALT_COLORS)
    after = time.monotonic()
    _check_skyaware_ages(got, SKYAWARE_LAG)
    assert got["A00001"]["track_valid"] is False
    assert got["A00001"]["on_ground"] is True
    assert got["A4F2B1"]["track_valid"] is True
    assert got["A1C3D9"]["track_valid"] is False
    assert all(before <= ac["received_mono"] <= after for ac in got.values())
    assert all(ac["last_seen"] == NOW for ac in got.values())

    # A failed poll falls back to that payload, with its receipt and lag.
    def refuse(*a, **k):
        raise fetcher.requests.exceptions.ConnectionError("feeder gone")
    monkeypatch.setattr(fetcher.requests, "get", refuse)
    assert f.fetch(*CENTER, 30, ALT_COLORS) == got


# ---------------------------------------------------------------------------
# adsb.fi / adsb.lol
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("provider,payload,lag", [
    ("adsbfi", ADSBFI, 1.5),               # `now` in seconds
    ("adsblol", ADSBLOL, 2.5),             # `now` in milliseconds
])
def test_adsbnet_pos_age_and_track(monkeypatch, wall_clock, provider, payload, lag):
    _serve(monkeypatch, fetcher, payload, ADSBNET_DATE)
    before = time.monotonic()
    got = fetcher.AdsbNetFetcher(provider=provider).fetch(*CENTER, 30, ALT_COLORS)
    after = time.monotonic()
    assert got["A4F2B1"]["pos_age"] == approx(3.1 + lag)     # seen_pos, from `now`
    assert got["A1C3D9"]["pos_age"] == approx(4.0 + lag)     # seen
    assert got["A00001"]["pos_age"] == 0.0                   # garbage seen_pos, null seen
    assert got["A00005"]["pos_age"] == MAX_POS_AGE_SECONDS
    assert got["A00005"]["pos_stale"] is True
    assert got["A00007"]["pos_age"] == approx(1.0 + lag)     # huge seen_pos: seen
    assert not any(got[i]["pos_stale"] for i in ("A4F2B1", "A1C3D9", "A00001", "A00007"))

    assert got["A4F2B1"]["track_valid"] is True
    assert got["A1C3D9"]["track_valid"] is True            # true_heading stands in
    assert got["A00001"]["track_valid"] is False           # no track field at all
    assert got["A00005"]["track_valid"] is False           # 725 degrees is not a track
    assert got["A00007"]["track_valid"] is False           # too big for a float
    assert got["A00001"]["on_ground"] is True
    assert got["A4F2B1"]["on_ground"] is False

    assert all(before <= ac["received_mono"] <= after for ac in got.values())
    assert all(ac["last_seen"] == NOW for ac in got.values())


def test_adsbnet_without_a_date_uses_our_clock(monkeypatch, wall_clock):
    _serve(monkeypatch, fetcher, ADSBFI)
    got = fetcher.AdsbNetFetcher(provider="adsbfi").fetch(*CENTER, 30, ALT_COLORS)
    assert got["A4F2B1"]["pos_age"] == approx(3.1 + 2.0)     # NOW - `now`


# ---------------------------------------------------------------------------
# OpenSky
# ---------------------------------------------------------------------------

def test_opensky_pos_age_against_its_own_clock(monkeypatch, wall_clock):
    _serve(monkeypatch, fetcher, OPENSKY, OPENSKY_DATE)
    before = time.monotonic()
    got = fetcher.OpenSkyFetcher().fetch(*CENTER, 30, ALT_COLORS)
    after = time.monotonic()
    # (time - time_position) plus how far the send trailed `time`, both by
    # OpenSky's clock.
    assert got["A4F2B1"]["pos_age"] == approx(4 + OPENSKY_LAG)
    assert got["A1C3D9"]["pos_age"] == approx(7 + OPENSKY_LAG)    # last_contact stands in
    assert got["AB11C2"]["pos_age"] == approx(2 + OPENSKY_LAG)    # garbage time_position
    assert got["A00007"]["pos_age"] == approx(3 + OPENSKY_LAG)    # huge time_position
    assert got["A00001"]["pos_age"] == 0.0                        # neither time
    assert got["AC0011"]["pos_age"] == MAX_POS_AGE_SECONDS
    assert got["AC0011"]["pos_stale"] is True
    assert got["A00006"]["pos_age"] == 0.0                        # from the future
    assert got["A00006"]["pos_stale"] is False

    assert got["A4F2B1"]["track_valid"] is True
    assert got["AB11C2"]["track_valid"] is False           # true_track null
    assert got["AB11C2"]["heading"] == 0                   # heading unchanged
    assert got["A00001"]["track_valid"] is True            # 0.0 sent is a real north
    assert got["A00007"]["track_valid"] is False           # too big for a float

    assert all(before <= ac["received_mono"] <= after for ac in got.values())
    assert all(ac["last_seen"] == NOW for ac in got.values())


@pytest.mark.parametrize("date,lag", [
    (None, 13.0),                          # no Date header: our clock at receipt
    (OPENSKY_TIME + 3600, 0.0),            # an implausible one: `time` alone
])
def test_opensky_when_the_date_header_is_no_use(monkeypatch, wall_clock, date, lag):
    _serve(monkeypatch, fetcher, OPENSKY, date)
    got = fetcher.OpenSkyFetcher().fetch(*CENTER, 30, ALT_COLORS)
    assert got["A4F2B1"]["pos_age"] == approx(4 + lag)


def test_opensky_without_a_response_time(monkeypatch, wall_clock):
    payload = copy.deepcopy(OPENSKY)
    del payload["time"]
    _serve(monkeypatch, fetcher, payload, OPENSKY_DATE)
    got = fetcher.OpenSkyFetcher().fetch(*CENTER, 30, ALT_COLORS)
    assert len(got) == len(OPENSKY["states"])              # nobody lost
    assert all(ac["pos_age"] == 0.0 for ac in got.values())


# ---------------------------------------------------------------------------
# FlightRadar24: the manager's feed path and FR24Fetcher
# ---------------------------------------------------------------------------

def _check_fr24(got, before, after):
    assert got["A4F2B1"]["pos_age"] == 4.0
    assert got["A1C3D9"]["pos_age"] == MAX_POS_AGE_SECONDS  # an hour old...
    assert got["A1C3D9"]["pos_stale"] is True              # ...and not fresh
    assert got["A00006"]["pos_age"] == MAX_POS_AGE_SECONDS
    assert got["A00006"]["pos_stale"] is True
    assert got["AB11C2"]["pos_age"] == 0.0                 # not an epoch at all
    assert got["AC0011"]["pos_age"] == 0.0                 # future, clamped
    assert got["A00001"]["pos_age"] == 0.0                 # garbage
    assert got["A00008"]["pos_age"] == 0.0                 # too far ahead
    assert got["A00009"]["pos_age"] == 0.0                 # older than maxage
    assert got["A00007"]["pos_age"] == 0.0                 # too big for a float
    for icao in ("A4F2B1", "AB11C2", "AC0011", "A00001", "A00008", "A00009", "A00007"):
        assert got[icao]["pos_stale"] is False, icao

    assert got["A4F2B1"]["track_valid"] is True
    assert got["AB11C2"]["track_valid"] is True            # a sent 0 is a number
    assert got["A00001"]["track_valid"] is False           # "" is not
    assert got["A00007"]["track_valid"] is False
    assert got["A00001"]["on_ground"] is True
    assert got["A4F2B1"]["on_ground"] is False

    assert all(before <= ac["received_mono"] <= after for ac in got.values())
    assert all(ac["last_seen"] == NOW for ac in got.values())


def test_fr24_feed_in_the_manager(monkeypatch, wall_clock):
    p = _plugin_shell()
    _serve(monkeypatch, manager, FR24)
    before = time.monotonic()
    got = p._fetch_fr24_feed()
    after = time.monotonic()
    _check_fr24(got, before, after)


def test_fr24_primary_source_keeps_the_fields(monkeypatch, wall_clock):
    """_update_from_fr24 stores the feed's dicts; the fields must survive it."""
    p = _plugin_shell()
    p.pending_fr24_details = {}
    p.fr24_detail_cache = {}
    p.min_callsign_length = 4
    p.airline_callsign_prefixes = []
    _serve(monkeypatch, manager, FR24)
    p._update_from_fr24()
    assert p.aircraft_data["A4F2B1"]["pos_age"] == 4.0
    assert p.aircraft_data["A4F2B1"]["track_valid"] is True
    assert p.aircraft_data["A1C3D9"]["pos_stale"] is True
    assert "received_mono" in p.aircraft_data["A4F2B1"]


def test_fr24_fetcher(monkeypatch, wall_clock):
    _serve(monkeypatch, fetcher, FR24)
    before = time.monotonic()
    got = fetcher.FR24Fetcher().fetch(*CENTER, 30, ALT_COLORS)
    after = time.monotonic()
    _check_fr24(got, before, after)
