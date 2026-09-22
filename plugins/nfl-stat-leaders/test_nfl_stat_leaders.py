#!/usr/bin/env python3
"""Data-side contracts for the NFL Stat Leaders plugin.

Covers the pieces that decide whether a panel shows the right numbers:
category matching against ESPN's naming, the franchise-id map the crests
are looked up by, leader normalisation, and the caching rules that keep
``display()`` off the network.

Exit codes follow the monorepo's runner contract: 0 pass, 1 fail, 2 skip.
"""

import json
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import nfl_stat_teams as teams_module
from nfl_stat_categories import (
    CATEGORIES,
    CATEGORIES_BY_KEY,
    DEFAULT_CATEGORY_TOGGLES,
    enabled_categories,
    match_feed_category,
)
from nfl_stat_fetcher import (
    StatFetcher,
    _feed_categories,
    _leader_row,
    current_season_year,
)

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("[pass] %s" % label)
    else:
        print("[FAIL] %s%s" % (label, (" -- " + detail) if detail else ""))
        FAILURES.append(label)


class FakeCache:
    """Enough of CacheManager for the fetcher: get/set with an age check."""

    def __init__(self, seed=None, age=0.0):
        self.store = dict(seed or {})
        self.age = age
        self.reads = []

    def get(self, key, max_age=None):
        self.reads.append((key, max_age))
        if key not in self.store:
            return None
        if max_age is not None and self.age > max_age:
            return None
        return self.store[key]

    def set(self, key, value, ttl=None):
        self.store[key] = value
        self.age = 0.0


def fake_payload():
    def leader(name, pos, team_ref, value):
        return {
            "displayValue": value,
            "athlete": {"shortName": name, "position": {"abbreviation": pos}},
            "team": {"$ref": team_ref},
        }

    return {"categories": [
        {"name": "passingYards", "displayName": "Passing Yards", "leaders": [
            leader("J. Allen", "QB",
                   "http://sports.core.api.espn.com/v2/teams/2?lang=en", "4,183"),
            leader("P. Mahomes", "QB",
                   "http://sports.core.api.espn.com/v2/teams/12?lang=en", "4,004"),
        ]},
        {"name": "rushingYards", "displayName": "Rushing Yards", "leaders": [
            leader("S. Barkley", "RB",
                   "http://sports.core.api.espn.com/v2/teams/21?lang=en", "1,838"),
        ]},
    ]}


# ----------------------------------------------------------------------
# Categories
# ----------------------------------------------------------------------

def test_schema_defaults_match_the_code():
    """The web UI's defaults and the code's defaults are one fact."""
    schema = json.load(open(os.path.join(PLUGIN_DIR, "config_schema.json")))
    block = schema["properties"]["categories"]
    check("category defaults agree with the schema",
          block["default"] == DEFAULT_CATEGORY_TOGGLES,
          "%s != %s" % (block["default"], DEFAULT_CATEGORY_TOGGLES))
    check("every category has a schema property",
          set(block["properties"]) == set(DEFAULT_CATEGORY_TOGGLES))
    per_property = {key: value["default"]
                    for key, value in block["properties"].items()}
    check("per-property defaults agree too",
          per_property == DEFAULT_CATEGORY_TOGGLES)


def test_defaults_are_the_fantasy_six():
    on = [c.key for c in enabled_categories(None)]
    check("six categories are on by default", len(on) == 6, str(on))
    check("the defaults are the standard fantasy scoring stats",
          on == ["passing_yards", "passing_touchdowns", "rushing_yards",
                 "rushing_touchdowns", "receiving_yards",
                 "receiving_touchdowns"], str(on))


def test_unknown_and_missing_toggles():
    check("a missing key keeps its shipped default",
          [c.key for c in enabled_categories({"passing_yards": False})]
          == ["passing_touchdowns", "rushing_yards", "rushing_touchdowns",
              "receiving_yards", "receiving_touchdowns"])
    check("an unknown key is ignored",
          enabled_categories({"not_a_stat": True}) == enabled_categories(None))
    check("a non-dict is treated as no overrides",
          enabled_categories("nonsense") == enabled_categories(None))
    check("everything off yields nothing",
          enabled_categories({c.key: False for c in CATEGORIES}) == [])


def test_category_matching():
    tackles = CATEGORIES_BY_KEY["total_tackles"]
    check("an alias name matches",
          match_feed_category(tackles, [{"name": "tackles"}]) is not None)
    check("the preferred name wins over the alias",
          match_feed_category(tackles, [
              {"name": "tackles", "displayName": "Tackles"},
              {"name": "totalTackles", "displayName": "Total Tackles"},
          ])["name"] == "totalTackles")

    rushing = CATEGORIES_BY_KEY["rushing_yards"]
    check("a renamed category still matches on its display name",
          match_feed_category(rushing, [
              {"name": "somethingNew", "displayName": "Rushing Yards"},
          ]) is not None)
    check("a different stat does not match",
          match_feed_category(rushing, [
              {"name": "passingYards", "displayName": "Passing Yards"},
          ]) is None)
    check("junk entries are skipped rather than raising",
          match_feed_category(rushing, [None, 7, {"name": "rushingYards"}])
          is not None)

    ints = CATEGORIES_BY_KEY["interceptions"]
    check("the defensive interception board is preferred",
          match_feed_category(ints, [
              {"name": "interceptions", "displayName": "Interceptions"},
              {"name": "defensiveInterceptions",
               "displayName": "Interceptions"},
          ])["name"] == "defensiveInterceptions")


# ----------------------------------------------------------------------
# Teams
# ----------------------------------------------------------------------

def test_team_map():
    check("all 32 franchises are mapped",
          len(teams_module.ESPN_TEAM_ID_TO_ABBR) == 32)
    check("abbreviations are unique",
          len(set(teams_module.ESPN_TEAM_ID_TO_ABBR.values())) == 32)
    check("a team ref resolves",
          teams_module.abbr_from_ref(
              "http://sports.core.api.espn.com/v2/sports/football/leagues/"
              "nfl/seasons/2025/teams/33?lang=en&region=us") == "BAL")
    check("a non-team ref resolves to nothing",
          teams_module.abbr_from_ref(
              "http://example.com/v2/athletes/3139477") is None)
    check("None is handled", teams_module.abbr_from_ref(None) is None)
    check("relocated-club abbreviations are normalised",
          [teams_module.normalize_abbr(a) for a in ("was", "JAC", "OAK", "SD")]
          == ["WSH", "JAX", "LV", "LAC"])
    check("an unknown id resolves to nothing",
          teams_module.abbr_from_team_id("999") is None)


def test_every_team_has_a_crest_on_disk():
    """A mapped abbreviation that no PNG matches is a blank column on the panel."""
    core = os.environ.get("LEDMATRIX_CORE")
    if not core:
        # The logo tree lives in the core repo, which is not always beside us.
        for candidate in (os.path.join(PLUGIN_DIR, "..", "..", ".."),
                          os.path.join(PLUGIN_DIR, "..", "..", "..", "LEDMatrix")):
            if os.path.isdir(os.path.join(candidate, "assets", "sports",
                                          "nfl_logos")):
                core = candidate
                break
    if not core:
        print("[pass] crest check skipped: no core checkout to look in")
        return
    logo_dir = os.path.join(core, "assets", "sports", "nfl_logos")
    missing = [abbr for abbr in teams_module.ESPN_TEAM_ID_TO_ABBR.values()
               if not os.path.exists(os.path.join(logo_dir, abbr + ".png"))]
    check("every mapped club has a crest", not missing, str(missing))


# ----------------------------------------------------------------------
# Leader normalisation
# ----------------------------------------------------------------------

def test_leader_rows():
    row = _leader_row({
        "displayValue": "4,183",
        "athlete": {"shortName": "J. Allen", "position": {"abbreviation": "qb"}},
        "team": {"$ref": "http://x/v2/teams/2?lang=en"},
    }, 1)
    check("a leader with a team ref is normalised",
          row == {"rank": 1, "name": "J. Allen", "position": "QB",
                  "team": "BUF", "value": "4,183"}, str(row))

    check("a nameless leader is dropped",
          _leader_row({"displayValue": "10", "athlete": {}}, 1) is None)
    check("a valueless leader is dropped",
          _leader_row({"athlete": {"shortName": "X. Y"}}, 1) is None)
    check("a non-dict entry is dropped", _leader_row(["nope"], 1) is None)

    numeric = _leader_row({"value": 1838,
                           "athlete": {"displayName": "Saquon Barkley"}}, 2)
    check("a bare numeric value is formatted with separators",
          numeric["value"] == "1,838", str(numeric))
    check("a player with no club still shows", numeric["team"] == "")

    decimal = _leader_row({"value": 14.5, "athlete": {"shortName": "T. Watt"}}, 1)
    check("a fractional value keeps one decimal", decimal["value"] == "14.5")

    inline = _leader_row({
        "displayValue": "17",
        "athlete": {"shortName": "J. Chase",
                    "team": {"abbreviation": "cin"}},
    }, 1)
    check("an inline team abbreviation is used and normalised",
          inline["team"] == "CIN", str(inline))


def test_feed_envelopes():
    payload = fake_payload()
    check("the v3 envelope is read", len(_feed_categories(payload)) == 2)
    check("the v2 envelope is read",
          len(_feed_categories({"leaders": payload})) == 2)
    check("a bare list under leaders is read",
          len(_feed_categories({"leaders": payload["categories"]})) == 2)
    check("nothing usable yields an empty list",
          _feed_categories({"whatever": 1}) == [] and _feed_categories(None) == [])


# ----------------------------------------------------------------------
# Fetching and caching
# ----------------------------------------------------------------------

def test_fresh_cache_is_used_without_a_request():
    cache = FakeCache({"nfl-stat-leaders_2025_2":
                       {"fetched_at": 0, "payload": fake_payload()}})
    fetcher = StatFetcher(cache)
    fetcher._request_payload = lambda *a, **k: _fail_no_network()
    boards = fetcher.fetch_boards(
        [CATEGORIES_BY_KEY["passing_yards"], CATEGORIES_BY_KEY["rushing_yards"]],
        season=2025, season_type=2, players_per_category=5, max_age=3600)
    check("both boards come back", len(boards) == 2, str(boards))
    check("the board carries its title",
          boards[0]["title"] == "PASSING YARDS")
    check("leaders are ranked from one",
          [row["rank"] for row in boards[0]["leaders"]] == [1, 2])
    check("clubs resolved from refs",
          [row["team"] for row in boards[0]["leaders"]] == ["BUF", "KC"])


def test_players_per_category_is_a_limit():
    cache = FakeCache({"nfl-stat-leaders_2025_2":
                       {"fetched_at": 0, "payload": fake_payload()}})
    fetcher = StatFetcher(cache)
    fetcher._request_payload = lambda *a, **k: _fail_no_network()
    boards = fetcher.fetch_boards([CATEGORIES_BY_KEY["passing_yards"]],
                                  2025, 2, 1, 3600)
    check("only the requested number of players is kept",
          len(boards[0]["leaders"]) == 1)


def test_a_stale_cache_beats_a_blank_panel():
    """An ESPN outage should show yesterday's leaders, not nothing."""
    cache = FakeCache({"nfl-stat-leaders_2025_2":
                       {"fetched_at": 0, "payload": fake_payload()}},
                      age=99999.0)
    fetcher = StatFetcher(cache)
    fetcher._request_payload = lambda *a, **k: None
    boards = fetcher.fetch_boards([CATEGORIES_BY_KEY["passing_yards"]],
                                  2025, 2, 5, 3600)
    check("stale leaders are shown when ESPN is down", len(boards) == 1,
          str(boards))


def test_a_missing_category_is_dropped_not_drawn_empty():
    cache = FakeCache({"nfl-stat-leaders_2025_2":
                       {"fetched_at": 0, "payload": fake_payload()}})
    fetcher = StatFetcher(cache)
    fetcher._request_payload = lambda *a, **k: _fail_no_network()
    boards = fetcher.fetch_boards([CATEGORIES_BY_KEY["sacks"]],
                                  2025, 2, 5, 3600)
    check("a category ESPN has no data for is dropped", boards == [])


def test_a_broken_cache_is_survivable():
    class Broken(FakeCache):
        def get(self, key, max_age=None):
            raise RuntimeError("cache on fire")

        def set(self, key, value, ttl=None):
            raise RuntimeError("cache still on fire")

    fetcher = StatFetcher(Broken())
    fetcher._request_payload = lambda *a, **k: fake_payload()
    boards = fetcher.fetch_boards([CATEGORIES_BY_KEY["passing_yards"]],
                                  2025, 2, 5, 3600)
    check("a failing cache does not lose the fetch", len(boards) == 1)


def test_season_resolution():
    import datetime as dt

    utc = dt.timezone.utc
    check("January belongs to the previous season",
          current_season_year(dt.datetime(2026, 1, 15, tzinfo=utc)) == 2025)
    check("September starts a new season",
          current_season_year(dt.datetime(2026, 9, 15, tzinfo=utc)) == 2026)
    check("March is the cutover",
          current_season_year(dt.datetime(2026, 3, 1, tzinfo=utc)) == 2026)

    fetcher = StatFetcher(FakeCache())
    check("a configured season is used as given",
          fetcher.resolve_season(2019, 2, 3600) == 2019)

    # Auto, with the current season not yet started: fall back one year so
    # the panel shows the season that just finished instead of nothing.
    empty_then_full = {"count": 0}

    def payload_for(season, season_type):
        empty_then_full["count"] += 1
        return fake_payload() if season == current_season_year() - 1 else None

    fetcher._request_payload = payload_for
    check("auto falls back to the last completed season",
          fetcher.resolve_season(0, 2, 3600) == current_season_year() - 1)


def _fail_no_network():
    raise AssertionError("the fetcher went to the network with a fresh cache")


def main():
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    if FAILURES:
        print("\n%d check(s) failed" % len(FAILURES))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
