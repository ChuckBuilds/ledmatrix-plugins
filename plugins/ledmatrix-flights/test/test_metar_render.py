#!/usr/bin/env python3
"""Tests for the METAR card renderer's unit handling and observation-age display.

Covers:
  - Wind / visibility / altimeter / temperature formatting in US (default) and
    international / Fahrenheit / mph / km unit configurations.
  - Observation-age formatting and the staleness flag.
  - The decoded card renders non-blank at every supported panel size.

Run standalone:
    python plugins/ledmatrix-flights/test/test_metar_render.py
"""

import os
import sys
import time

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from renderer import FlightRenderer  # noqa: E402


class _FakeMatrix:
    def __init__(self, w, h):
        self.width, self.height = w, h


class _FakeDM:
    def __init__(self, w, h):
        self.matrix = _FakeMatrix(w, h)
        self.image = None

    def update_display(self):
        pass


def _r(config=None, w=128, h=32):
    return FlightRenderer(_FakeDM(w, h), {}, config or {})


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #

def test_us_defaults():
    r = _r()
    assert r._fmt_wind(90, 8, None) == "090@8"
    assert r._fmt_wind(190, 15, 24) == "190@15G24"
    assert r._fmt_wind(0, 0, None) == "CALM"
    assert r._fmt_wind("VRB", 5, None) == "VRB@5"
    assert r._fmt_vis(10) == "10+SM" and r._fmt_vis(2) == "2SM" and r._fmt_vis("10+") == "10+SM"
    assert r._fmt_altim(30.01) == "A30.01"
    assert r._fmt_c(31) == "31"
    print("PASS test_us_defaults")


def test_international_units():
    r = _r({"metar": {"altimeter_unit": "hpa", "visibility_unit": "m"}})
    assert r._fmt_altim(30.01) == "Q1016", r._fmt_altim(30.01)
    assert r._fmt_vis(10) == "9999m"
    assert r._fmt_vis(2).endswith("m")
    print("PASS test_international_units")


def test_fahrenheit_mph_km():
    r = _r({"metar": {"temp_unit": "f", "wind_unit": "mph", "visibility_unit": "km"}})
    assert r._fmt_c(0) == "32" and r._fmt_c(31) == "88"
    assert r._fmt_wind(90, 10, None) == "090@12MPH"  # 10kt -> ~11.5 -> 12
    assert r._fmt_vis(10) == "10+km" and r._fmt_vis(2).endswith("km")
    print("PASS test_fahrenheit_mph_km")


# --------------------------------------------------------------------------- #
# Observation age
# --------------------------------------------------------------------------- #

def test_age_fresh_and_stale():
    r = _r()
    now = time.time()
    assert r._fmt_age(now - 14 * 60) == ("14m", False)
    s, stale = r._fmt_age(now - 108 * 60)
    assert s == "1h48" and stale is True, (s, stale)
    assert r._fmt_age(now - 76 * 60)[1] is True     # just past the 75-min cutoff
    assert r._fmt_age(now - 60 * 60)[1] is False
    assert r._fmt_age(None) == ("", False)
    assert r._fmt_age(0) == ("", False)
    print("PASS test_age_fresh_and_stale")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def test_card_renders_all_sizes():
    now = time.time()
    wx = {"icao": "KTPA", "raw": "KTPA ...", "flt_cat": "VFR", "wind_dir": 90,
          "wind_spd": 8, "wind_gust": None, "vis": 10, "wx_string": "",
          "clouds": [("FEW", 4500)], "ceiling_ft": None, "temp_c": 31, "dewp_c": 22,
          "altim_inhg": 30.01, "obs_time": now - 14 * 60, "raw_taf": ""}
    for w, h in [(64, 32), (128, 32), (128, 64), (256, 32)]:
        r = _r(w=w, h=h)
        r.render_metar_card(wx)
        assert r.dm.image.size == (w, h)
        assert r.dm.image.getbbox() is not None, f"blank at {w}x{h}"
    print("PASS test_card_renders_all_sizes")


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
