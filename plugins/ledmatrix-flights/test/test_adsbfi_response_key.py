#!/usr/bin/env python3
"""
Regression test for AdsbNetFetcher response-key parsing.

adsb.lol returns aircraft under the "ac" key (ADSBexchange v2 format), but
adsb.fi's opendata API returns them under "aircraft". The fetcher previously
read only "ac", so the adsb.fi provider always reported "no aircraft in range".

This test verifies the fetcher accepts BOTH keys.
"""

import os
import sys
from typing import Dict, List

# Make the plugin package importable (fetcher.py imports `from utils import ...`)
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import fetcher  # noqa: E402
from fetcher import AdsbNetFetcher  # noqa: E402

CENTER_LAT = 47.3223
CENTER_LON = -122.3126
ALTITUDE_COLORS: Dict[str, List[int]] = {"0": [255, 100, 0], "40000": [0, 200, 150]}


def _fake_aircraft():
    # Positioned exactly at the center so it is always within radius.
    return {
        "hex": "abc123",
        "flight": "ASA844 ",
        "t": "A21N",
        "lat": CENTER_LAT,
        "lon": CENTER_LON,
        "alt_baro": 25450,
        "gs": 410,
        "track": 180,
        "r": "N925VA",
    }


class _FakeResponse:
    # status_code because the fetcher checks for 429 before touching the body.
    # Without it this stub raised AttributeError, which read as a fetch failure
    # rather than a broken double.
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _run_with_payload(payload) -> int:
    """Patch requests.get to return `payload`, run a fetch, return aircraft count."""
    original_get = fetcher.requests.get
    fetcher.requests.get = lambda *a, **k: _FakeResponse(payload)
    try:
        f = AdsbNetFetcher(provider="adsbfi")
        result = f.fetch(CENTER_LAT, CENTER_LON, 30, ALTITUDE_COLORS)
        return len(result or {})
    finally:
        fetcher.requests.get = original_get


def test_adsbfi_aircraft_key():
    """adsb.fi format: aircraft under 'aircraft' key must be parsed."""
    count = _run_with_payload({"aircraft": [_fake_aircraft()], "resultCount": 1})
    assert count == 1, f"expected 1 aircraft from 'aircraft' key, got {count}"
    print("✓ adsb.fi 'aircraft' key parsed correctly")


def test_adsblol_ac_key():
    """adsb.lol format: aircraft under 'ac' key must still be parsed."""
    count = _run_with_payload({"ac": [_fake_aircraft()], "total": 1})
    assert count == 1, f"expected 1 aircraft from 'ac' key, got {count}"
    print("✓ adsb.lol 'ac' key still parsed correctly")


def test_empty_response():
    """Neither key present → no aircraft (no crash)."""
    count = _run_with_payload({"now": 0})
    assert count == 0, f"expected 0 aircraft from empty response, got {count}"
    print("✓ empty response handled")


if __name__ == "__main__":
    print("AdsbNetFetcher response-key regression test")
    print("=" * 44)
    ok = True
    for t in (test_adsbfi_aircraft_key, test_adsblol_ac_key, test_empty_response):
        try:
            t()
        except AssertionError as e:
            ok = False
            print(f"✗ {t.__name__}: {e}")
    print("=" * 44)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
