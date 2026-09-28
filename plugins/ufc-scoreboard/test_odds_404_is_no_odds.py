#!/usr/bin/env python3
"""A 404 from ESPN's odds endpoint means "no line for this bout", not an error.

ESPN answers 404 rather than an empty list for a bout it has no odds for,
which is most of every card. The bundled MMA odds manager logged each one at
ERROR ("Error fetching odds from ESPN API ... 404 Client Error") and cached
nothing, so the same bouts were re-requested, and re-logged, on every update.

A 404 is now cached as the same {"no_odds": True} marker an empty response
gets, logged at DEBUG. Any other HTTP error still logs ERROR and is not cached.

Loads the plugin's own base_odds_manager.py by path (other scoreboards used to
ship the same bare name). No network: the session is replaced.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_odds_404_is_no_odds.py
"""

import importlib.util
import logging
import sys
from pathlib import Path

import requests

PLUGIN_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "ufc_bundled_base_odds_manager", PLUGIN_DIR / "base_odds_manager.py")
bom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bom)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Cache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value


class _Session:
    """Answers every GET with one canned status and body, counting calls."""

    def __init__(self, status, body=b"{}"):
        self.status, self.body, self.calls = status, body, 0

    def get(self, url, timeout=None):
        self.calls += 1
        response = requests.Response()
        response.status_code = self.status
        response._content = self.body
        response.url = url
        response.reason = {404: "Not Found", 500: "Internal Server Error"}.get(self.status, "OK")
        return response


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def manager(status, body=b"{}"):
    mgr = bom.BaseOddsManager(_Cache())
    mgr.session = _Session(status, body)
    records = _Records()
    mgr.logger.handlers = [records]
    mgr.logger.setLevel(logging.DEBUG)
    mgr.logger.propagate = False
    return mgr, records


def errors(records):
    return [r.getMessage() for r in records.records if r.levelno >= logging.ERROR]


print("404: no odds for this bout")
mgr, records = manager(404)
got = mgr.get_odds("mma", "ufc", "600001", "600002")
key = "odds_espn_mma_ufc_600001_600002"
check("returns None", got is None, got)
check("logs no ERROR", not errors(records), errors(records))
check("logs it at DEBUG",
      any(r.levelno == logging.DEBUG and "404" in r.getMessage() for r in records.records))
check("caches the no-odds marker", mgr.cache_manager.data.get(key) == {"no_odds": True},
      mgr.cache_manager.data)
again = mgr.get_odds("mma", "ufc", "600001", "600002")
check("the next call is answered from the cache", again is None and mgr.session.calls == 1,
      mgr.session.calls)

print("\n500: still an error")
mgr, records = manager(500)
got = mgr.get_odds("mma", "ufc", "600001", "600002")
check("returns None", got is None, got)
check("logs ERROR", len(errors(records)) == 1, errors(records))
check("caches nothing", not mgr.cache_manager.data, mgr.cache_manager.data)

print("\n200 with an empty list: unchanged")
mgr, records = manager(200, b'{"count": 0, "items": []}')
got = mgr.get_odds("mma", "ufc", "600001", "600002")
check("returns None", got is None, got)
check("caches the no-odds marker", mgr.cache_manager.data.get(key) == {"no_odds": True},
      mgr.cache_manager.data)

print("\n200 with a line: unchanged")
mgr, records = manager(200, b'{"items": [{"details": "JON -250", '
                            b'"homeAthleteOdds": {"moneyLine": -250}, '
                            b'"awayAthleteOdds": {"moneyLine": 200}}]}')
got = mgr.get_odds("mma", "ufc", "600001", "600002")
check("returns the odds", got and got["home_team_odds"]["money_line"] == -250, got)
check("caches them", mgr.cache_manager.data.get(key) == got)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed")
    sys.exit(1)
print("all checks passed")
