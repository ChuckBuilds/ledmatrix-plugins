#!/usr/bin/env python3
"""Live scores are not served from a five-minute-old scoreboard.

_fetch_todays_games() backs every live manager (NBA, WNBA, NCAAM, NCAAW). It
read the cached "current scoreboard" with max_age=300, so however short
live_update_interval was set, a live game's score, clock and period could lag by
up to five minutes: over 300 simulated seconds of live polling basketball made
one network call where soccer and afl made five. soccer (#123), afl and nrl
cache the same call for 30s; this aligns basketball with them.

The check drives the real method with a cache that records the max_age it is
asked for and answers from cache, so no request is ever made.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_live_scoreboard_cache_is_short.py
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break

try:
    from sports import SportsCore  # noqa: E402
except ImportError as exc:
    print(f"SKIP: cannot import sports.py without a LEDMatrix core ({exc})")
    sys.exit(2)

#: What the sibling scoreboards use for this call.
LIVE_CACHE_SECONDS = 30

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Cache:
    def __init__(self):
        self.asked = []

    def get(self, key, max_age=None):
        self.asked.append((key, max_age))
        return {"events": [{"id": "1"}]}

    def set(self, *a, **k):
        raise AssertionError("a cache hit must not be written back")


class _Stub:
    _fetch_todays_games = SportsCore._fetch_todays_games

    def __init__(self, league):
        self.sport = "basketball"
        self.league = league
        self.sport_key = league
        self.cache_manager = _Cache()
        self.logger = logging.getLogger("test")
        self.session = None
        self.headers = {}


for league in ("nba", "wnba", "mens-college-basketball", "womens-college-basketball"):
    stub = _Stub(league)
    data = stub._fetch_todays_games()
    ages = [age for key, age in stub.cache_manager.asked if key.endswith("_scoreboard_current")]
    check(f"{league}: served from cache without a request", bool(data and data.get("events")))
    check(f"{league}: the live scoreboard cache is at most {LIVE_CACHE_SECONDS}s",
          bool(ages) and all(age is not None and age <= LIVE_CACHE_SECONDS for age in ages),
          f"max_age asked: {ages}")

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
