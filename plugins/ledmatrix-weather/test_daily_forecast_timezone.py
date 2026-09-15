#!/usr/bin/env python3
"""Regression test: daily forecast day labels use the location's timezone.

Open-Meteo stamps each daily entry at the location's local midnight
(timezone=auto). The hourly forecast converted with tz=location_tz, but the
daily filter and labels used naive datetime.now() / datetime.fromtimestamp(),
i.e. the Pi's system zone. On a Pi running UTC -- the usual default -- Tokyo's
midnight is 15:00 the previous day, so every day label was one day early
("Wed 09/16" drawn as "Tue 09/15"), and the "future days only" filter kept
today.

Run with the core venv from a LEDMatrix checkout so manager's imports resolve:
    LEDMatrix/.venv/bin/python <thisfile>
"""
import logging
import os
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE")
if _core:
    sys.path.insert(0, _core)

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Asia/Tokyo")
    from manager import WeatherPlugin  # noqa: E402
except Exception as exc:  # ImportError, or no tz database on this host
    print("SKIP: missing dependency (%s)" % exc)
    sys.exit(2)

logging.getLogger().addHandler(logging.NullHandler())

failures = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  (%s)" % detail) if detail and not ok else ""))
    if not ok:
        failures.append(label)


def _forecast(tz_name):
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    daily = []
    # Today plus four days, each stamped at the location's local midnight.
    for n in range(0, 5):
        d = today + timedelta(days=n)
        ts = int(datetime.combine(d, dtime(0, 0), tzinfo=tz).timestamp())
        daily.append({"dt": ts, "temp": {"max": 20 + n, "min": 10 + n},
                      "weather": [{"main": "Clear", "icon": "01d"}]})
    return {"timezone": tz_name, "hourly": [], "daily": daily}, today


plugin = WeatherPlugin.__new__(WeatherPlugin)
plugin.logger = logging.getLogger("weather-test")

# Zones on both sides of the date line: wherever the host is, at least one is
# a calendar day away from it for part of every day, and Tokyo's midnight is
# the previous UTC date all day long.
for tz_name in ("Asia/Tokyo", "Pacific/Kiritimati", "Pacific/Pago_Pago"):
    print(tz_name)
    data, today = _forecast(tz_name)
    plugin._process_forecast_data(data)
    expected = [(today + timedelta(days=n)) for n in (1, 2, 3)]
    got = [(d["date"], d["date_str"]) for d in plugin.daily_forecast]
    want = [(d.strftime("%a"), d.strftime("%m/%d")) for d in expected]
    check("next three days, labelled in the location's calendar", got == want,
          "got %s, want %s" % (got, want))
    check("highs line up with those days", [d["temp_high"] for d in plugin.daily_forecast] == [21, 22, 23])

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
