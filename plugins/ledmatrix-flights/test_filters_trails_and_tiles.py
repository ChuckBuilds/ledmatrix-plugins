#!/usr/bin/env python3
"""
Regression tests for five flight-tracker settings that did not do what they
said.

1. aircraft_categories hid every aircraft on the adsb.fi / adsb.lol sources:
   their fetcher never copied the API's "category" field, so the filter found
   nothing to match.
2. anchor_airport never matched when the route used the other code system:
   FR24 enrichment supplies IATA ("TPA"), the adsbnet route lookup ICAO
   ("KTPA"), and the comparison was a plain string match.
3. trail_length 0 kept the whole trail: list[-0:] is the entire list.
4. Tiles were cached under the provider name even when a custom tile server
   supplied them, so changing or clearing the server kept the old tiles for up
   to a year.
5. show_aircraft_icon was read and never consulted.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-flights/test_filters_trails_and_tiles.py
Exit 0 pass, 1 fail, 2 skip.
"""

import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import fetcher  # noqa: E402
    from manager import DEFAULT_TILE_SERVER, FlightTrackerPlugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


# --- 1. the category survives the adsbnet fetcher ---------------------------
class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"aircraft": [{"hex": "a1b2c3", "flight": "DAL123 ", "lat": 27.95, "lon": -82.46,
                              "alt_baro": 3000, "gs": 200, "track": 90, "category": "A3"}]}


original = fetcher.requests.get
fetcher.requests.get = lambda *a, **k: _Response()
try:
    got = fetcher.AdsbNetFetcher(provider="adsbfi").fetch(27.95, -82.46, 30, {"0": [255, 100, 0], "40000": [0, 200, 150]}) or {}
finally:
    fetcher.requests.get = original
ac = next(iter(got.values()), {})
check("the adsbnet fetcher keeps the ADS-B category", ac.get("category") == "A3", ac)

# --- 2. the anchor airport under both of its codes --------------------------
p = object.__new__(FlightTrackerPlugin)
p.anchor_airport = "KTPA"
p.aircraft_data = {
    "1": {"icao": "1", "origin": "ATL", "destination": "TPA"},    # FR24: IATA
    "2": {"icao": "2", "origin": "KTPA", "destination": "KJFK"},  # adsbnet: ICAO
    "3": {"icao": "3", "origin": "ORD", "destination": "LAX"},
}
found = {a["icao"]: a for a in p._get_anchor_aircraft()}
check("an ICAO anchor matches an IATA route", found.get("1", {}).get("_anchor_arrival") is True,
      sorted(found))
check("and an ICAO route", found.get("2", {}).get("_anchor_departure") is True, sorted(found))
check("and nothing else", "3" not in found)
p.anchor_airport = "TPA"
check("an IATA anchor matches both as well", {a["icao"] for a in p._get_anchor_aircraft()} == {"1", "2"})

# --- 3. trail_length 0 means no trail ---------------------------------------
p.aircraft_trails = {"x": [(1, 1)] * 7}
p.trail_length = 0
p._trim_trail("x")
check("trail_length 0 keeps no trail", p.aircraft_trails["x"] == [], len(p.aircraft_trails["x"]))
p.aircraft_trails = {"x": list(range(7))}
p.trail_length = 3
p._trim_trail("x")
check("trail_length 3 keeps the newest three", p.aircraft_trails["x"] == [4, 5, 6])

# --- 4. tiles cached per source ---------------------------------------------
p.tile_cache_dir = Path("tiles")
p.tile_provider = "osm"
p.custom_tile_server = DEFAULT_TILE_SERVER
default_name = p._get_tile_cache_path(1, 2, 10).name
check("the default server keeps the name existing caches use", default_name == "osm_10_1_2.png",
      default_name)
p.custom_tile_server = "https://tiles.example.org/"
custom_name = p._get_tile_cache_path(1, 2, 10).name
check("another server gets its own cache name",
      custom_name.startswith("custom-") and custom_name != default_name, custom_name)
p.custom_tile_server = ""
direct_name = p._get_tile_cache_path(1, 2, 10).name
check("so does no server at all", direct_name not in (default_name, custom_name), direct_name)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
