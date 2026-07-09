#!/usr/bin/env python3
"""
Tests for metar_fetcher.MetarFetcher — the NOAA Aviation Weather Center client
behind the optional Airport Weather add-on.

Covers:
  - METAR JSON normalization (flight category, ceiling from cloud layers,
    altimeter hPa->inHg conversion + inHg pass-through guard, present weather).
  - fetch_weather() batching METAR + TAF and merging the raw TAF onto the METAR.
  - Cache-first / serve-stale behavior on a network error.
  - PIREP / SIGMET parsing and empty-input safety.

Run standalone:
    python plugins/ledmatrix-flights/test/test_metar_fetcher.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import requests  # noqa: E402
from metar_fetcher import MetarFetcher  # noqa: E402


SAMPLE_METAR = {
    "icaoId": "KSEA",
    "name": "Seattle-Tacoma Intl, WA, US",
    "rawOb": "KSEA 251853Z 19015G24KT 2SM -RA BR BKN008 OVC015 09/08 A2978 RMK AO2",
    "fltCat": "IFR",
    "temp": 9.4,
    "dewp": 8.3,
    "wdir": 190,
    "wspd": 15,
    "wgst": 24,
    "visib": 2,
    "wxString": "-RA BR",
    "altim": 1008.5,  # hPa
    "clouds": [{"cover": "BKN", "base": 800}, {"cover": "OVC", "base": 1500}],
    "obsTime": 1000,
}


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _install_routes(f, routes):
    """Patch the fetcher's session.get to dispatch on a substring of the URL.
    A route value that is an Exception instance is raised (to test error paths)."""
    def fake_get(url, params=None, timeout=None):
        for key, payload in routes.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResp(payload)
        return _FakeResp([])
    f.session.get = fake_get


class _FakeCache:
    """Cache stub. get(key, max_age=...) simulates an expired entry (miss) while
    get(key) with no max_age returns the last-good value (for serve-stale)."""
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def get(self, key, max_age=None):
        if max_age is not None:
            return None  # pretend everything is expired -> forces a fetch
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def test_normalize_metar_fields():
    f = MetarFetcher({}, None)
    wx = f._normalize_metar(SAMPLE_METAR)
    assert wx["icao"] == "KSEA", wx["icao"]
    assert wx["flt_cat"] == "IFR", wx["flt_cat"]
    assert wx["ceiling_ft"] == 800, wx["ceiling_ft"]          # lowest BKN/OVC layer
    assert wx["wind_gust"] == 24, wx["wind_gust"]
    assert wx["wx_string"] == "-RA BR", wx["wx_string"]
    assert wx["raw"].startswith("KSEA "), wx["raw"]
    # 1008.5 hPa -> ~29.78 inHg
    assert wx["altim_inhg"] == round(1008.5 * 0.02953, 2), wx["altim_inhg"]
    print("PASS test_normalize_metar_fields")


def test_construction_survives_bad_numeric_config():
    """Malformed numeric options must fall back to defaults, not raise (the fetcher
    is built unguarded from FlightTrackerPlugin.__init__)."""
    f = MetarFetcher({"metar": {"pirep_distance_nm": "oops", "update_interval_minutes": None}}, None)
    assert f.pirep_distance_nm == 200, f.pirep_distance_nm
    assert f.metar_ttl == 600, f.metar_ttl  # 10 min default
    print("PASS test_construction_survives_bad_numeric_config")


def test_altimeter_inhg_passthrough():
    """A feed already reporting inHg (<100) must not be re-scaled."""
    f = MetarFetcher({}, None)
    wx = f._normalize_metar({"icaoId": "KTPA", "altim": 29.92})
    assert wx["altim_inhg"] == 29.92, wx["altim_inhg"]
    print("PASS test_altimeter_inhg_passthrough")


def test_ceiling_none_when_only_few_scattered():
    f = MetarFetcher({}, None)
    wx = f._normalize_metar({"icaoId": "KTPA",
                             "clouds": [{"cover": "FEW", "base": 4500},
                                        {"cover": "SCT", "base": 25000}]})
    assert wx["ceiling_ft"] is None, wx["ceiling_ft"]
    print("PASS test_ceiling_none_when_only_few_scattered")


# --------------------------------------------------------------------------- #
# fetch_weather batching + TAF merge
# --------------------------------------------------------------------------- #

def test_fetch_weather_merges_taf():
    f = MetarFetcher({"metar": {"show_taf": True}}, None)
    _install_routes(f, {
        "/metar": [SAMPLE_METAR],
        "/taf": [{"icaoId": "KSEA", "rawTAF": "KSEA 251720Z 2518/2624 19015G25KT"}],
    })
    out = f.fetch_weather(["KSEA"])
    assert "KSEA" in out, out.keys()
    assert out["KSEA"]["flt_cat"] == "IFR"
    assert out["KSEA"]["raw_taf"].startswith("KSEA 251720Z"), out["KSEA"]["raw_taf"]
    print("PASS test_fetch_weather_merges_taf")


def test_fetch_weather_no_airports():
    f = MetarFetcher({}, None)
    assert f.fetch_weather([]) == {}
    assert f.fetch_weather(None) == {}
    print("PASS test_fetch_weather_no_airports")


def test_fetch_weather_serves_stale_on_error():
    """Cache-first miss + network error -> serve the last-good cached copy."""
    ids = "KSEA"
    stale = [dict(SAMPLE_METAR)]
    cache = _FakeCache({f"metar_wx_{ids}": stale})
    f = MetarFetcher({"metar": {"show_taf": False}}, cache)
    _install_routes(f, {"/metar": requests.RequestException("boom")})
    out = f.fetch_weather([ids])
    assert "KSEA" in out, out.keys()  # recovered from stale cache
    print("PASS test_fetch_weather_serves_stale_on_error")


# --------------------------------------------------------------------------- #
# PIREP / SIGMET
# --------------------------------------------------------------------------- #

def test_fetch_pireps():
    f = MetarFetcher({}, None)
    _install_routes(f, {"/pirep": [{"rawOb": "KSEA UA /OV SEA/TM 1845/FL080/TP B738/TB MOD"}]})
    ps = f.fetch_pireps("KSEA", 200)
    assert len(ps) == 1 and ps[0]["raw"].startswith("KSEA UA"), ps
    print("PASS test_fetch_pireps")


def test_fetch_sigmets():
    f = MetarFetcher({}, None)
    _install_routes(f, {"/airsigmet": [
        {"airSigmetType": "AIRMET", "hazard": "TURB", "rawAirSigmet": "..."},
        {"airSigmetType": "SIGMET", "hazard": "CONVECTIVE", "rawAirSigmet": "..."},
    ]})
    ss = f.fetch_sigmets()
    assert len(ss) == 2 and ss[0]["hazard"] == "TURB", ss
    print("PASS test_fetch_sigmets")


def _run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # pragma: no cover
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
