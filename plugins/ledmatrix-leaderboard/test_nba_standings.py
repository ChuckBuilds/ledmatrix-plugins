#!/usr/bin/env python3
"""
Regression test: NBA standings come from ESPN's standings endpoint.

league_config defines an NBA standings_url, but DataFetcher.fetch_standings only
routed nfl/mlb/nhl/college-baseball there. NBA fell through to the teams
endpoint, whose team objects carry no stats, so every team rendered 0-0 in
whatever order ESPN listed them -- 31 requests per refresh for fake standings.

The network is stubbed: the stub answers the standings URL with a two-conference
NBA standings payload and records every URL requested.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    python plugins/ledmatrix-leaderboard/test_nba_standings.py
"""

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import requests  # noqa: F401  (data_fetcher imports it)
except ImportError:
    print("SKIP: requests not installed")
    sys.exit(2)

import data_fetcher as df  # noqa: E402
from league_config import LeagueConfig  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def entry(abbr, wins, losses):
    return {
        "team": {"displayName": abbr, "abbreviation": abbr, "id": abbr},
        "stats": [
            {"type": "wins", "value": wins},
            {"type": "losses", "value": losses},
            {"type": "winpercent", "value": wins / float(wins + losses)},
        ],
    }


STANDINGS = {
    "children": [
        {"name": "Eastern Conference",
         "standings": {"entries": [entry("BOS", 50, 20), entry("NY", 40, 30)]}},
        {"name": "Western Conference",
         "standings": {"entries": [entry("OKC", 60, 10), entry("LAL", 30, 40)]}},
    ]
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeCache:
    def get_cached_data_with_strategy(self, *args, **kwargs):
        return None

    def save_cache(self, *args, **kwargs):
        pass


def main():
    logger = logging.getLogger("test_nba_standings")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False

    league_config = LeagueConfig(
        {"enabled_sports": {"nba": {"enabled": True, "top_teams": 10}}}, logger
    ).get_league_config("nba")
    standings_url = league_config["standings_url"]

    requested = []

    def fake_get(url, params=None, timeout=None, **kwargs):
        requested.append(url)
        if url == standings_url:
            return FakeResponse(STANDINGS)
        # The teams endpoint shape: teams without stats.
        return FakeResponse({"sports": [{"leagues": [{"teams": [
            {"team": {"abbreviation": "BOS", "name": "Celtics", "id": "2"}}]}]}]})

    df.requests.get = fake_get
    fetcher = df.DataFetcher(FakeCache(), logger, request_timeout=5)

    print("[NBA routing]")
    standings = fetcher.fetch_standings(league_config)
    check(requested[:1] == [standings_url],
          f"NBA asks the standings endpoint first (requested {requested})")
    check(len(requested) == 1, f"one request per refresh, not one per team (got {len(requested)})")
    check([t["abbreviation"] for t in standings] == ["OKC", "BOS", "NY", "LAL"],
          f"both conferences merged, best record first (got {[t.get('abbreviation') for t in standings]})")
    check(bool(standings) and standings[0].get("record_summary") == "60-10",
          f"records come from the standings stats (got {standings[0].get('record_summary') if standings else None})")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a crash is a failure, not a skip
        failures.append(repr(exc))
        print(f"  FAIL: raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
