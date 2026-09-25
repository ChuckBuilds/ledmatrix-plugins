"""Every network call Fantasy Blitz makes, and the cache around it.

Sources (all public, no API key):

* Sleeper -- ``api.sleeper.app/v1/state/nfl`` for the current week,
  ``api.sleeper.com/stats|projections/nfl/...`` for every player's weekly
  line and projection with fantasy points already calculated in PPR,
  Half-PPR and Standard, and ``/v1/players/nfl/trending/{add,drop}``.
* ESPN -- the NFL scoreboard (which games are live or final), a game's
  summary (scoring-play text for big-play alerts), and ESPN's fantasy
  ``kona_player_info`` view as a fallback when Sleeper's feed is down.

Sleeper's stats and projections URLs are not in its published docs, which is
why the ESPN fallback exists.

Caching: each value is stored as ``{"fetched_at": <epoch>, "data": ...}``
and read back with no expiry, so the plugin judges freshness itself and can
fall back to the last good copy when a fetch fails. (The core's cache lets a
stored ttl override the reader's max_age; keeping our own timestamp sidesteps
that, and makes a recorded fixture fresh under a frozen test clock.) Keys are
namespaced with the plugin id.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

import requests

import fantasy_blitz_model as model
from fantasy_blitz_teams import from_espn

SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_STATS_URL = "https://api.sleeper.com/stats/nfl/{season}/{week}"
SLEEPER_PROJECTIONS_URL = "https://api.sleeper.com/projections/nfl/{season}/{week}"
SLEEPER_SEASON_URL = "https://api.sleeper.com/stats/nfl/{season}"
SLEEPER_TRENDING_URL = "https://api.sleeper.app/v1/players/nfl/trending/{kind}"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
ESPN_FANTASY_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
                    "{season}/segments/0/leaguedefaults/{scoring}")

USER_AGENT = "LEDMatrix-FantasyBlitz/1.0 (+https://github.com/ChuckBuilds/ledmatrix-plugins)"

#: ESPN's fantasy default-league id per scoring format.
ESPN_SCORING_IDS = {"ppr": 3, "half_ppr": 2, "standard": 1}
#: ESPN fantasy position ids.
ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
#: ESPN pro team ids -> ESPN abbreviations (converted to Sleeper's below).
ESPN_TEAM_IDS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
    9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA",
    16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI",
    23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR",
    30: "JAX", 33: "BAL", 34: "HOU",
}
#: ESPN fantasy stat ids -> the Sleeper stat names the renderers use.
ESPN_STAT_IDS = {
    "3": "pass_yd", "4": "pass_td", "20": "pass_int", "23": "rush_att",
    "24": "rush_yd", "25": "rush_td", "53": "rec", "42": "rec_yd", "43": "rec_td",
    "58": "rec_tgt", "72": "fum_lost", "83": "fgm", "84": "fga", "86": "xpm",
    "95": "int", "96": "fum_rec", "99": "sack", "94": "def_td", "120": "pts_allow",
}
ESPN_INJURY = {
    "QUESTIONABLE": "Questionable", "DOUBTFUL": "Doubtful", "OUT": "Out",
    "INJURY_RESERVE": "IR", "SUSPENSION": "Sus",
}

POSITION_PARAMS = [("position[]", pos) for pos in model.POSITIONS]


class FantasyData:
    """Fetches, normalises and caches everything the screens draw."""

    def __init__(self, cache_manager, logger: Optional[logging.Logger], plugin_id: str,
                 timeout: float = 15.0, session: Optional[requests.Session] = None):
        self.cache = cache_manager
        self.logger = logger or logging.getLogger(__name__)
        self.plugin_id = plugin_id
        self.timeout = float(timeout)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_error_log: Dict[str, float] = {}
        #: Set by the last _cached() call: did it answer from a live fetch?
        self.last_fetch_failed = False

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    def key(self, *parts: Any) -> str:
        return ":".join([self.plugin_id] + [str(p) for p in parts])

    def _get_json(self, url: str, params: Any = None, headers: Optional[Dict[str, str]] = None) -> Any:
        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def read(self, key: str) -> Optional[Dict[str, Any]]:
        """The stored ``{"fetched_at", "data"}`` entry for ``key``, or None."""
        try:
            entry = self.cache.get(key, max_age=None)
        except TypeError:  # an old cache without the max_age keyword
            entry = self.cache.get(key)
        except Exception as exc:  # noqa: BLE001 - a corrupt entry is a miss
            self.logger.debug("Cache read failed for %s: %s", key, exc)
            return None
        if isinstance(entry, dict) and "fetched_at" in entry and "data" in entry:
            return entry
        return None

    def write(self, key: str, data: Any, now: Optional[float] = None) -> None:
        try:
            self.cache.set(key, {"fetched_at": time.time() if now is None else now, "data": data})
        except Exception as exc:  # noqa: BLE001 - failing to cache is not fatal
            self.logger.debug("Cache write failed for %s: %s", key, exc)

    def cached(self, key: str, max_age: float, fetch: Callable[[], Any],
               now: Optional[float] = None) -> Any:
        """Fresh cached data, else a fetch, else the last good copy (or None)."""
        now = time.time() if now is None else now
        entry = self.read(key)
        self.last_fetch_failed = False
        if entry is not None and now - float(entry.get("fetched_at") or 0) < max_age:
            return entry["data"]
        try:
            data = fetch()
        except Exception as exc:  # noqa: BLE001 - network and parse errors alike
            self.last_fetch_failed = True
            self._log_error(key, exc)
            return entry["data"] if entry is not None else None
        if data is None:
            return entry["data"] if entry is not None else None
        self.write(key, data, now)
        return data

    def age(self, key: str, now: Optional[float] = None) -> Optional[float]:
        entry = self.read(key)
        if entry is None:
            return None
        return (time.time() if now is None else now) - float(entry.get("fetched_at") or 0)

    def _log_error(self, key: str, exc: Exception) -> None:
        """Warn about a failing source at most every ten minutes."""
        family = key.split(":")[1] if ":" in key else key
        now = time.time()
        if now - self._last_error_log.get(family, 0.0) >= 600:
            self._last_error_log[family] = now
            self.logger.warning("Could not fetch %s: %s", family, exc)

    # ------------------------------------------------------------------
    # Sleeper
    # ------------------------------------------------------------------

    def state(self, max_age: float = 1800) -> Optional[Dict[str, Any]]:
        """``{"season": "2026", "week": 3, "season_type": "regular", ...}``."""
        def fetch():
            data = self._get_json(SLEEPER_STATE_URL)
            if not isinstance(data, dict) or "week" not in data:
                raise ValueError("unexpected NFL state payload")
            return {k: data.get(k) for k in ("season", "week", "season_type", "display_week",
                                             "previous_season", "leg")}
        return self.cached(self.key("state"), max_age, fetch)

    def week_stats(self, season: Any, week: int, max_age: float) -> Optional[Dict[str, Any]]:
        def fetch():
            rows = self._get_json(
                SLEEPER_STATS_URL.format(season=season, week=int(week)),
                params=[("season_type", "regular")] + POSITION_PARAMS + [("order_by", "pts_ppr")],
            )
            if not isinstance(rows, list):
                raise ValueError("unexpected stats payload")
            return model.normalize_sleeper_rows(rows, "stats")
        return self.cached(self.key("stats", season, week), max_age, fetch)

    def week_projections(self, season: Any, week: int, max_age: float = 21600) -> Optional[Dict[str, Any]]:
        def fetch():
            rows = self._get_json(
                SLEEPER_PROJECTIONS_URL.format(season=season, week=int(week)),
                params=[("season_type", "regular")] + POSITION_PARAMS + [("order_by", "pts_ppr")],
            )
            if not isinstance(rows, list):
                raise ValueError("unexpected projections payload")
            players = model.normalize_sleeper_rows(rows, "projections")
            # Keep the projections that matter: the feed lists every rostered
            # player, most of them projected for nothing.
            return {pid: p for pid, p in players.items()
                    if max((v or 0.0) for v in (p.get("proj") or {}).values() or [0.0]) >= 0.5
                    or p.get("pos") == "DEF"}
        return self.cached(self.key("proj", season, week), max_age, fetch)

    def season_totals(self, season: Any, max_age: float = 21600) -> Optional[Dict[str, Any]]:
        """Season-to-date points per player: ``{pid: player}`` with ``gp``."""
        def fetch():
            rows = self._get_json(
                SLEEPER_SEASON_URL.format(season=season),
                params=[("season_type", "regular")] + POSITION_PARAMS + [("order_by", "pts_ppr")],
            )
            if not isinstance(rows, list):
                raise ValueError("unexpected season payload")
            players = model.normalize_sleeper_rows(rows, "stats")
            keep = {}
            for pid, p in players.items():
                if max((v or 0.0) for v in (p.get("pts") or {}).values() or [0.0]) >= 5.0:
                    p["stats"] = {k: v for k, v in (p.get("stats") or {}).items() if k == "gp"}
                    keep[pid] = p
            return keep
        return self.cached(self.key("season", season), max_age, fetch)

    def trending(self, kind: str = "add", limit: int = 15, max_age: float = 1800) -> Optional[List[Dict[str, Any]]]:
        kind = "drop" if kind == "drop" else "add"

        def fetch():
            rows = self._get_json(SLEEPER_TRENDING_URL.format(kind=kind),
                                  params={"lookback_hours": 24, "limit": int(limit)})
            if not isinstance(rows, list):
                raise ValueError("unexpected trending payload")
            return [{"player_id": str(r.get("player_id")), "count": r.get("count")}
                    for r in rows if isinstance(r, dict) and r.get("player_id")]
        return self.cached(self.key("trending", kind), max_age, fetch)

    # ------------------------------------------------------------------
    # ESPN
    # ------------------------------------------------------------------

    def games(self, season: Any, week: int, max_age: float) -> Optional[List[Dict[str, Any]]]:
        """The week's games: ``[{"id", "state", "home", "away", ...}]``."""
        def fetch():
            payload = self._get_json(ESPN_SCOREBOARD_URL, params={
                "seasontype": 2, "week": int(week), "dates": int(season)})
            return normalize_scoreboard(payload)
        return self.cached(self.key("games", season, week), max_age, fetch)

    def scoring_plays(self, event_id: str, max_age: float = 45) -> Optional[List[Dict[str, Any]]]:
        def fetch():
            payload = self._get_json(ESPN_SUMMARY_URL, params={"event": event_id})
            return normalize_scoring_plays(payload)
        return self.cached(self.key("plays", event_id), max_age, fetch)

    def espn_week_players(self, season: Any, week: int, scoring: str,
                          max_age: float) -> Optional[Dict[str, Any]]:
        """ESPN's fantasy feed as a stand-in for Sleeper's, same player shape.

        One request returns actual and projected points in the chosen format
        for the 300 highest-projected players. Snap counts are not in this
        feed, so a bust can only be excused by an injury tag.
        """
        def fetch():
            payload = self._get_json(
                ESPN_FANTASY_URL.format(season=int(season), scoring=ESPN_SCORING_IDS.get(scoring, 3)),
                params={"scoringPeriodId": int(week), "view": "kona_player_info"},
                headers={"X-Fantasy-Filter": espn_fantasy_filter(season, week)},
            )
            return normalize_espn_fantasy(payload, int(week), scoring)
        return self.cached(self.key("espnweek", season, week, scoring), max_age, fetch)


# ----------------------------------------------------------------------
# Normalisers (pure, so the tests can feed them recorded payloads)
# ----------------------------------------------------------------------

def espn_fantasy_filter(season: Any, week: int) -> str:
    """The ``X-Fantasy-Filter`` header for one week of ESPN player points.

    Stat keys are ``<source><split><season><period>``: source 0 is actual,
    1 projected; split 1 is a single week. ESPN ignores a sort on actual
    points (tested 2026-09-24), so the query sorts on the projection and
    takes enough players that every real top scorer is in the set.
    """
    actual_key = f"01{int(season)}{int(week)}"
    proj_key = f"11{int(season)}{int(week)}"
    return json.dumps({"players": {
        "filterSlotIds": {"value": [0, 2, 4, 6, 17, 16]},
        "filterStatsForTopScoringPeriodIds": {"value": 2, "additionalValue": [actual_key, proj_key]},
        "sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 1, "value": proj_key},
        "limit": 300,
    }}, separators=(",", ":"))


def normalize_scoreboard(payload: Any) -> List[Dict[str, Any]]:
    games = []
    for event in (payload or {}).get("events") or []:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        status = (comp.get("status") or event.get("status") or {}).get("type") or {}
        game: Dict[str, Any] = {
            "id": str(event.get("id") or ""),
            "state": status.get("state") or "pre",
            "detail": status.get("shortDetail") or status.get("detail") or "",
            "start": event.get("date") or "",
            "home": "", "away": "", "home_score": 0, "away_score": 0,
        }
        for competitor in comp.get("competitors") or []:
            side = competitor.get("homeAway")
            if side not in ("home", "away"):
                continue
            abbr = from_espn(((competitor.get("team") or {}).get("abbreviation")))
            game[side] = abbr
            try:
                game[f"{side}_score"] = int(float(competitor.get("score") or 0))
            except (TypeError, ValueError):
                game[f"{side}_score"] = 0
        games.append(game)
    return games


def normalize_scoring_plays(payload: Any) -> List[Dict[str, Any]]:
    plays = []
    for play in (payload or {}).get("scoringPlays") or []:
        plays.append({
            "id": str(play.get("id") or ""),
            "text": play.get("text") or "",
            "type": {"text": ((play.get("type") or {}).get("text") or "")},
            "team": from_espn(((play.get("team") or {}).get("abbreviation"))),
            "period": ((play.get("period") or {}).get("number")),
            "clock": ((play.get("clock") or {}).get("displayValue")),
        })
    return plays


def normalize_espn_fantasy(payload: Any, week: int, scoring: str) -> Dict[str, Any]:
    """ESPN ``kona_player_info`` -> the same player dicts Sleeper produces.

    Ids are prefixed ``espn:`` so they can never collide with Sleeper's, and
    ``espn_id`` is kept so the headshot needs no lookup. Points fill only the
    requested format; the other two stay None.
    """
    fmt = scoring if scoring in model.SCORING_KEYS else model.DEFAULT_SCORING
    players: Dict[str, Any] = {}
    for entry in (payload or {}).get("players") or []:
        p = (entry or {}).get("player") or {}
        pos = ESPN_POSITIONS.get(p.get("defaultPositionId"))
        if not pos:
            continue
        team = from_espn(ESPN_TEAM_IDS.get(p.get("proTeamId"), ""))
        actual = proj = None
        stats: Dict[str, float] = {}
        for block in p.get("stats") or []:
            if block.get("scoringPeriodId") != week:
                continue
            if block.get("statSourceId") == 0:
                actual = model.safe_float(block.get("appliedTotal"))
                for sid, value in (block.get("stats") or {}).items():
                    name = ESPN_STAT_IDS.get(str(sid))
                    if name and model.safe_float(value) is not None:
                        stats[name] = float(value)
            elif block.get("statSourceId") == 1:
                proj = model.safe_float(block.get("appliedTotal"))
        if actual is not None:
            stats.setdefault("gp", 1.0)
        full = str(p.get("fullName") or "")
        if pos == "DEF":
            first, last = full.replace(" D/ST", ""), full.replace(" D/ST", "")
            pid = f"espn:def:{team}"
        else:
            first, _, last = full.partition(" ")
            pid = f"espn:{p.get('id')}"
        empty = {k: None for k in model.SCORING_KEYS}
        players[pid] = {
            "id": pid,
            "first": first,
            "last": last,
            "name": full.replace(" D/ST", "") if pos == "DEF" else full,
            "pos": pos,
            "team": team,
            "opp": "",
            "game_id": "",
            "injury": ESPN_INJURY.get(str(p.get("injuryStatus") or "")),
            "pts": dict(empty, **{fmt: actual}),
            "proj": dict(empty, **{fmt: proj}),
            "stats": stats,
            "espn_id": None if pos == "DEF" else str(p.get("id")),
        }
    return players
