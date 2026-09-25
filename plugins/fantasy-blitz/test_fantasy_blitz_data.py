"""Fantasy Blitz data plumbing: feed normalisers, the cache, leagues, headshots.

No network: payloads are recorded (test/fixtures/raw_payloads.json) or built
here, and HTTP is replaced by a stub session.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402

import fantasy_blitz_data as data_mod  # noqa: E402
import fantasy_blitz_headshots as heads  # noqa: E402
import fantasy_blitz_league as league  # noqa: E402

with open(os.path.join(HERE, "test", "fixtures", "raw_payloads.json"), encoding="utf-8") as fh:
    RAW = json.load(fh)


class DictCache:
    """Enough of the core cache: get(key, max_age) / set(key, value)."""

    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        if isinstance(self.payload, Exception):
            raise self.payload

    def json(self):
        return self.payload


class StubSession:
    """Answers GETs from a {url-fragment: payload} table and records them."""

    def __init__(self, table):
        self.table = table
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self.calls.append((url, params, headers))
        for fragment, payload in self.table.items():
            if fragment in url:
                return StubResponse(payload)
        return StubResponse(ConnectionError(f"no stub for {url}"))

    def close(self):
        pass


def make_data(table=None):
    return data_mod.FantasyData(DictCache(), None, "fantasy-blitz", 5, StubSession(table or {}))


# ----------------------------------------------------------------------
# cache behaviour
# ----------------------------------------------------------------------

def test_fresh_cache_answers_without_a_fetch():
    data = make_data({"state/nfl": {"season": "2026", "week": 3, "season_type": "regular"}})
    data.write(data.key("state"), {"season": "2026", "week": 2}, now=1000.0)
    assert data.cached(data.key("state"), 60, lambda: 1 / 0, now=1030.0) == {"season": "2026", "week": 2}


def test_stale_cache_refetches_and_failure_falls_back():
    data = make_data()
    key = data.key("x")
    data.write(key, "old", now=0.0)
    assert data.cached(key, 60, lambda: "new", now=100.0) == "new"
    data.write(key, "old", now=0.0)

    def boom():
        raise ConnectionError("down")

    assert data.cached(key, 60, boom, now=100.0) == "old"
    assert data.last_fetch_failed
    assert data.cached(data.key("never"), 60, boom, now=100.0) is None


def test_state_is_trimmed_to_the_fields_used():
    data = make_data({"state/nfl": {"season": "2026", "week": 3, "season_type": "regular", "junk": 1}})
    state = data.state()
    assert state["week"] == 3 and "junk" not in state


def test_week_stats_normalise_through_the_cache():
    data = make_data({"/stats/nfl/2026/2": RAW["sleeper_stats"]})
    stats = data.week_stats("2026", 2, 60)
    assert stats["9488"]["pts"]["ppr"] == 42.5
    url, params, _ = data.session.calls[0]
    assert ("position[]", "DEF") in params and ("season_type", "regular") in params


def test_projections_drop_players_projected_for_nothing():
    rows = RAW["sleeper_projections"] + [{"player_id": "zero", "player": {"position": "WR", "first_name": "No", "last_name": "Body"},
                                          "stats": {"pts_ppr": 0.0}, "team": "SEA"}]
    data = make_data({"/projections/nfl/2026/2": rows})
    proj = data.week_projections("2026", 2)
    assert "zero" not in proj and "9488" in proj


# ----------------------------------------------------------------------
# ESPN normalisers
# ----------------------------------------------------------------------

def test_scoreboard_normalises_states_and_abbreviations():
    games = data_mod.normalize_scoreboard(RAW["espn_scoreboard"])
    assert games and all(g["state"] == "post" for g in games)
    assert all(g["home"] and g["away"] for g in games)
    wsh = {"events": [{"id": "1", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": [
        {"homeAway": "home", "team": {"abbreviation": "WSH"}, "score": "7"},
        {"homeAway": "away", "team": {"abbreviation": "DAL"}, "score": "3"}]}]}]}
    game = data_mod.normalize_scoreboard(wsh)[0]
    assert (game["home"], game["home_score"], game["state"]) == ("WAS", 7, "in")


def test_scoring_plays_keep_text_and_team():
    plays = data_mod.normalize_scoring_plays(RAW["espn_summary"])
    assert plays[0]["text"].startswith("Jaxon Smith-Njigba 82 Yd pass")
    assert plays[0]["team"] == "SEA"


def test_espn_fantasy_fallback_has_the_same_shape():
    players = data_mod.normalize_espn_fantasy(RAW["espn_fantasy"], 2, "ppr")
    allen = players["espn:3918298"]
    assert allen["pos"] == "QB" and allen["team"] == "BUF"
    assert allen["pts"]["ppr"] == pytest.approx(40.82) and allen["pts"]["standard"] is None
    assert allen["stats"]["pass_yd"] == 248 and allen["espn_id"] == "3918298"
    defence = players["espn:def:CAR"]
    assert defence["pos"] == "DEF" and defence["name"] == "Panthers"


def test_espn_filter_is_valid_json():
    parsed = json.loads(data_mod.espn_fantasy_filter(2026, 2))
    assert parsed["players"]["sortAppliedStatTotal"]["value"] == "1120262"
    assert "0120262" in parsed["players"]["filterStatsForTopScoringPeriodIds"]["additionalValue"]


# ----------------------------------------------------------------------
# leagues
# ----------------------------------------------------------------------

SLEEPER_USERS = [{"user_id": "u1", "display_name": "chuck", "metadata": {"team_name": "Gridiron Ghosts"}},
                 {"user_id": "u2", "display_name": "sam", "metadata": {}}]
SLEEPER_ROSTERS = [{"roster_id": 1, "owner_id": "u1", "settings": {"wins": 2, "losses": 0}},
                   {"roster_id": 2, "owner_id": "u2", "settings": {"wins": 1, "losses": 1, "ties": 1}}]
SLEEPER_MATCHUPS = [{"roster_id": 2, "matchup_id": 1, "points": 118.9},
                    {"roster_id": 1, "matchup_id": 1, "points": 131.42}]


def test_sleeper_league_normalises_and_orders_mine_first():
    lg = league.normalize_sleeper_league({"name": "Test League"}, SLEEPER_USERS, SLEEPER_ROSTERS, SLEEPER_MATCHUPS, 2)
    m = lg["matchups"][0]
    assert {m["home"]["name"], m["away"]["name"]} == {"Gridiron Ghosts", "sam"}
    ordered = league.order_matchups(lg, "chuck")
    mine = ordered["matchups"][0]
    assert mine["mine"] and mine["home"]["name"] == "Gridiron Ghosts" and mine["home"]["record"] == "2-0"
    assert mine["away"]["record"] == "1-1-1"


def test_espn_league_prefers_live_points():
    payload = {
        "settings": {"name": "Office League"},
        "status": {"currentMatchupPeriod": 2, "latestScoringPeriod": 2},
        "members": [{"id": "{A}", "displayName": "pat"}],
        "teams": [{"id": 1, "location": "Team", "nickname": "One", "abbrev": "ONE", "owners": ["{A}"],
                   "record": {"overall": {"wins": 1, "losses": 1}}},
                  {"id": 2, "name": "Second Team", "abbrev": "TWO", "owners": []}],
        "schedule": [{"matchupPeriodId": 2, "home": {"teamId": 1, "totalPoints": 50, "totalPointsLive": 61.5},
                      "away": {"teamId": 2, "totalPoints": 70}},
                     {"matchupPeriodId": 1, "home": {"teamId": 1, "totalPoints": 1}, "away": {"teamId": 2, "totalPoints": 2}}],
    }
    lg = league.normalize_espn_league(payload, 2)
    assert lg["name"] == "Office League" and len(lg["matchups"]) == 1
    m = league.order_matchups(lg, "TWO")["matchups"][0]
    assert m["mine"] and m["home"]["name"] == "Second Team" and m["away"]["points"] == 61.5


def test_fetch_league_uses_the_cache_and_stub():
    table = {"/users": SLEEPER_USERS, "/rosters": SLEEPER_ROSTERS, "/matchups/2": SLEEPER_MATCHUPS,
             "league/123": {"name": "Test League"}}
    data = make_data(table)
    lg = league.fetch_league(data, "sleeper", "123", "2026", 2, "Gridiron Ghosts")
    assert lg["name"] == "Test League" and lg["matchups"][0]["mine"]


def test_provider_problems_are_explained():
    assert league.describe_provider_problem("none", "", "", "") is None
    assert "no league id" in league.describe_provider_problem("sleeper", "", "", "")
    assert "both" in league.describe_provider_problem("espn", "1", "cookie", "")
    assert league.fetch_league(make_data(), "yahoo", "1", "2026", 2) is None


# ----------------------------------------------------------------------
# headshots
# ----------------------------------------------------------------------

SEARCH_ITEMS = [
    {"id": "3918298", "type": "player", "league": "nfl", "displayName": "Josh Allen", "jersey": "17",
     "position": {"abbreviation": "QB"}, "headshot": {"href": "https://a.espncdn.com/x/3918298.png"},
     "teamRelationships": [{"core": {"abbreviation": "BUF"}}]},
    {"id": "17102", "type": "player", "league": "nfl", "displayName": "Josh Allen", "jersey": "66",
     "position": {"abbreviation": "C"}, "teamRelationships": [{"core": {"abbreviation": "ARI"}}]},
    {"id": "3915239", "type": "player", "league": "nfl", "displayName": "Josh Hines-Allen",
     "position": {"abbreviation": "DE"}, "teamRelationships": [{"core": {"abbreviation": "JAX"}}]},
]


def test_search_match_uses_club_then_position():
    qb = {"id": "4984", "name": "Josh Allen", "pos": "QB", "team": "BUF"}
    assert heads.match_search_result(qb, SEARCH_ITEMS)["espn_id"] == "3918298"
    traded = {"id": "4984", "name": "Josh Allen", "pos": "QB", "team": "NYJ"}
    assert heads.match_search_result(traded, SEARCH_ITEMS)["jersey"] == "17"
    unknown = {"id": "x", "name": "Josh Allen", "pos": "WR", "team": "NYJ"}
    assert heads.match_search_result(unknown, SEARCH_ITEMS) is None


def test_only_espn_hosts_are_fetched():
    assert heads.is_allowed_url("https://a.espncdn.com/i/headshots/nfl/players/full/1.png")
    assert not heads.is_allowed_url("https://evil.example.com/a.png")
    assert not heads.is_allowed_url("file:///etc/passwd")


def test_crop_portrait_fills_the_box():
    src = Image.new("RGBA", (200, 145), (200, 100, 50, 255))
    for size in ((41, 55), (19, 24), (48, 30)):
        assert heads.crop_portrait(src, *size).size == size


def test_prefetch_resolves_downloads_and_caches():
    png = Image.new("RGBA", (600, 436), (10, 200, 10, 255))
    import io
    buf = io.BytesIO()
    png.save(buf, "PNG")

    class ImageResponse(StubResponse):
        headers = {"Content-Length": str(len(buf.getvalue()))}

        def iter_content(self, size):
            yield buf.getvalue()

        def close(self):
            pass

    data = make_data({"common/v3/search": {"items": SEARCH_ITEMS}})
    original_get = data.session.get

    def get(url, **kwargs):
        if url.endswith(".png"):
            return ImageResponse(None)
        return original_get(url, **kwargs)

    data.session.get = get
    store = heads.HeadshotStore(data, __import__("logging").getLogger("t"))
    allen = {"id": "4984", "name": "Josh Allen", "pos": "QB", "team": "BUF"}
    assert store.prefetch([allen]) == 2  # one lookup, one download
    assert store.jersey(allen) == "17"
    portrait = store.portrait(allen, 30, 40)
    assert portrait is not None and portrait.size == (30, 40)
    assert store.prefetch([allen]) == 0, "everything is cached now"
