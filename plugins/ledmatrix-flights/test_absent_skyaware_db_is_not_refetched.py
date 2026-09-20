#!/usr/bin/env python3
"""
Tests that a /db/<PREFIX>.json the feeder does not serve is not re-requested
on every enrichment pass.

_enrich_from_skyaware_db asks the SkyAware feeder for one small JSON file per
two-character ICAO prefix. A 200 was cached; anything else was deliberately not
("don't cache - allow retry next cycle"), so every prefix the install does not
serve was re-requested every pass, forever.

Measured on 2026-09-19 against one feeder: 10,503 404s in a day, the same
handful of prefixes roughly 1,700 times each, and 24% of every HTTP request
the rig made. The plugin was also the rig's top CPU consumer.

Which prefix files exist is a property of the install, not a transient
condition, so a 404 is now remembered for _SKYAWARE_DB_MISS_TTL. A network
error says nothing about existence and is held only _SKYAWARE_DB_ERROR_TTL.
These checks pin:

  * a 404 prefix is asked about once, not once per pass;
  * a successful prefix is still cached and still enriches;
  * the hold-off expires, so an upgraded feeder is picked up;
  * a network error is retried sooner than a 404;
  * a 200 arriving after a hold-off expires enriches normally.

Run: <core-venv>/bin/python plugins/ledmatrix-flights/test_absent_skyaware_db_is_not_refetched.py
"""

import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import manager as flights_manager  # noqa: E402


class _Logger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Stub:
    """Just enough of FlightTrackerPlugin to run the enrichment."""

    _SKYAWARE_DB_MISS_TTL = flights_manager.FlightTrackerPlugin._SKYAWARE_DB_MISS_TTL
    _SKYAWARE_DB_ERROR_TTL = flights_manager.FlightTrackerPlugin._SKYAWARE_DB_ERROR_TTL
    _enrich_from_skyaware_db = flights_manager.FlightTrackerPlugin._enrich_from_skyaware_db

    def __init__(self):
        self.skyaware_url = "http://feeder.local/data/aircraft.json"
        self.logger = _Logger()


failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _run(stub, responder, clock, aircraft):
    """Drive one enrichment pass with patched requests.get and time.monotonic."""
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return responder(url)

    real_get, real_monotonic = flights_manager.requests.get, flights_manager.time.monotonic
    flights_manager.requests.get = fake_get
    flights_manager.time.monotonic = lambda: clock[0]
    try:
        stub._enrich_from_skyaware_db(aircraft)
    finally:
        flights_manager.requests.get = real_get
        flights_manager.time.monotonic = real_monotonic
    return calls


def _ac(icao):
    return [(icao, {})]


def main():
    print("a prefix the feeder does not serve is asked about once")
    stub, clock = _Stub(), [1000.0]
    responder = lambda url: _Resp(404)
    first = _run(stub, responder, clock, _ac("A0E000"))
    check("the first pass asks", first == ["http://feeder.local/db/A0.json"])
    clock[0] += 5
    again = _run(stub, responder, clock, _ac("A0E000"))
    check("the next pass does not", again == [])
    clock[0] += 60
    check("nor does a pass a minute later",
          _run(stub, responder, clock, _ac("A0E000")) == [])

    print("\nthe hold-off expires, so an upgraded feeder is picked up")
    clock[0] += stub._SKYAWARE_DB_MISS_TTL
    served = lambda url: _Resp(200, {"E000": {"t": "B738", "r": "N123"}})
    ac = _ac("A0E000")
    calls = _run(stub, served, clock, ac)
    check("it asks again once the TTL has passed", calls == ["http://feeder.local/db/A0.json"])
    check("and the aircraft is enriched", ac[0][1].get("aircraft_type") == "B738")
    check("registration comes through too", ac[0][1].get("registration") == "N123")

    print("\na served prefix is cached, not re-requested")
    clock[0] += 1
    check("the cached db answers without a request",
          _run(stub, served, clock, _ac("A0E001")) == [])

    print("\na network error is retried sooner than a 404")
    stub2, clock2 = _Stub(), [500.0]

    def boom(url):
        raise flights_manager.requests.RequestException("connection refused")

    check("the first pass asks", _run(stub2, boom, clock2, _ac("7CF000")) ==
          ["http://feeder.local/db/7C.json"])
    clock2[0] += 5
    check("it holds off briefly", _run(stub2, boom, clock2, _ac("7CF000")) == [])
    clock2[0] += stub2._SKYAWARE_DB_ERROR_TTL
    check("but retries well before a 404 would have",
          _run(stub2, boom, clock2, _ac("7CF000")) == ["http://feeder.local/db/7C.json"])
    check("the error hold-off is shorter than the miss hold-off",
          stub2._SKYAWARE_DB_ERROR_TTL < stub2._SKYAWARE_DB_MISS_TTL)

    print("\nseveral absent prefixes are each remembered independently")
    stub3, clock3 = _Stub(), [0.0]
    missing = lambda url: _Resp(404)
    aircraft = [("A0E000", {}), ("7CF000", {}), ("AEF000", {})]
    first = _run(stub3, missing, clock3, aircraft)
    check("one request per distinct prefix", sorted(first) == sorted([
        "http://feeder.local/db/A0.json",
        "http://feeder.local/db/7C.json",
        "http://feeder.local/db/AE.json"]))
    clock3[0] += 30
    check("and none on the next pass", _run(stub3, missing, clock3, aircraft) == [])

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
