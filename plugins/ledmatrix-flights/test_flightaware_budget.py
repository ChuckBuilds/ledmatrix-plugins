"""
Regression test: the FlightAware budget recovers on its own.

_record_api_call wrote its adjustments back into daily_api_budget: the
mid-month cap of 40 carried into the next month, and the 95% emergency stop
set it to 0 for good. The month's call count never reset either, so a
long-running panel stopped looking up flight plans until a restart. And the
limit was checked before the cache, so once it was spent even cached plans
(no call needed) came back "Unknown".

The budget methods run against a stand-in ``self`` with a controllable date.

Run with the core venv, LEDMATRIX_CORE pointing at a LEDMatrix checkout:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/ledmatrix-flights/test_flightaware_budget.py
"""

import logging
import os
import sys
from datetime import datetime as real_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    import manager  # noqa: E402
except ImportError as e:
    print(f"SKIP: plugin does not import without the core on the path ({e})")
    sys.exit(2)

logging.disable(logging.CRITICAL)
failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class _Clock(real_datetime):
    at = real_datetime(2026, 9, 10, 12, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.at


manager.datetime = _Clock


class _Cache:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, max_age=None):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value


def plugin(daily=60):
    p = object.__new__(manager.FlightTrackerPlugin)
    p.logger = logging.getLogger("test-fa-budget")
    p.daily_api_budget = daily
    p.api_calls_today = 0
    p.last_reset_date = None
    p.api_call_timestamps = []
    p.max_api_calls_per_hour = 10_000
    p.monthly_api_calls = 0
    p.cost_per_call = 0.005
    p.monthly_budget = 10.0
    p.budget_warning_threshold = 0.8
    return p


def spend(p, n):
    for _ in range(n):
        p._record_api_call()
    p.api_call_timestamps = []  # the hourly limit is not under test


print("the mid-month cap does not carry into the next month")
p = plugin(daily=60)
_Clock.at = real_datetime(2026, 9, 20, 12, 0)
p._check_rate_limit()
spend(p, 1)
_Clock.at = real_datetime(2026, 10, 2, 12, 0)
p._check_rate_limit()  # the new day's first check resets today's count
p.api_calls_today = 45
check(p._check_rate_limit(), "on 2 Oct, call 46 of a configured 60 is allowed")
check(p.daily_api_budget == 60, "the configured daily budget is unchanged")

print("the emergency stop lifts when the month turns")
p = plugin(daily=5000)
_Clock.at = real_datetime(2026, 9, 10, 12, 0)
p._check_rate_limit()
spend(p, 1900)  # $9.50, 95% of $10
p.api_calls_today = 0
check(not p._check_rate_limit(), "at 95% of the month's budget no call is allowed")
_Clock.at = real_datetime(2026, 10, 1, 0, 5)
check(p._check_rate_limit(), "on 1 Oct calls are allowed again")
check(p.monthly_api_calls == 0, "the month's count restarted")

print("a spent budget still serves cached flight plans")
p = plugin(daily=0)
p.flightaware_api_key = "KEY"
p.flight_plan_enabled = True
p.min_callsign_length = 4
p.airline_callsign_prefixes = ["UAL"]
p.cache_ttl_seconds = 3600
p.aircraft_data = {}
p.aircraft_db = None
cached = {"origin": "KORD", "destination": "KSFO", "aircraft_type": "B738"}
p.cache_manager = _Cache({"flight_plan_UAL123": cached})
got = p._get_flight_plan_data("UAL123")
check(got == cached, "UAL123 comes from the cache with the daily budget at 0")

print(f"\n{len(failures)} failed")
sys.exit(1 if failures else 0)
