"""League sync: the head-to-head matchups in one real fantasy league.

Two providers:

* **Sleeper** -- public. A league id (the number in the league's URL) is all
  it takes: ``/v1/league/{id}``, ``/users``, ``/rosters`` and
  ``/matchups/{week}``. Matchup points update live during games.
* **ESPN** -- a public league needs only its id; a private one also needs the
  ``espn_s2`` and ``SWID`` cookies from a signed-in browser, which the plugin
  keeps in the secrets file (``x-secret`` in the schema), never in config.

Yahoo is not supported: its API needs a full OAuth sign-in with a registered
app, which a scoreboard has no way to complete.

Both providers produce the same shape::

    {"provider": "sleeper", "name": "League name", "week": 3,
     "matchups": [{"home": {"name", "owner", "points", "record"},
                   "away": {...}, "mine": True}, ...]}

with the configured team's matchup first when it can be found.
"""

from typing import Any, Dict, List, Optional

import fantasy_blitz_model as model

SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
ESPN_LEAGUE_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
                   "{season}/segments/0/leagues/{league_id}")

PROVIDERS = ("none", "sleeper", "espn")


def _clean_id(value: Any) -> str:
    return "".join(c for c in str(value or "").strip() if c.isalnum())


def fetch_league(data, provider: str, league_id: Any, season: Any, week: int,
                 team_name: str = "", espn_s2: str = "", swid: str = "",
                 max_age: float = 60.0) -> Optional[Dict[str, Any]]:
    """Matchups for ``week`` via the FantasyData cache, or None when unset/failing."""
    league_id = _clean_id(league_id)
    if provider not in ("sleeper", "espn") or not league_id:
        return None
    key = data.key("league", provider, league_id, season, week)

    if provider == "sleeper":
        def fetch():
            base = SLEEPER_LEAGUE_URL.format(league_id=league_id)
            league = data._get_json(base)
            users = data._get_json(base + "/users")
            rosters = data._get_json(base + "/rosters")
            matchups = data._get_json(base + f"/matchups/{int(week)}")
            return normalize_sleeper_league(league, users, rosters, matchups, int(week))
    else:
        def fetch():
            cookies = {}
            if espn_s2 and swid:
                cookies = {"espn_s2": espn_s2, "SWID": swid}
            resp = data.session.get(
                ESPN_LEAGUE_URL.format(season=int(season), league_id=league_id),
                params=[("view", "mMatchupScore"), ("view", "mScoreboard"),
                        ("view", "mTeam"), ("view", "mSettings"),
                        ("scoringPeriodId", int(week))],
                cookies=cookies or None, timeout=data.timeout,
            )
            resp.raise_for_status()
            return normalize_espn_league(resp.json(), int(week))

    league = data.cached(key, max_age, fetch)
    if not league:
        return None
    return order_matchups(league, team_name)


def normalize_sleeper_league(league: Any, users: Any, rosters: Any, matchups: Any,
                             week: int) -> Dict[str, Any]:
    users_by_id = {}
    for user in users or []:
        if not isinstance(user, dict):
            continue
        meta = user.get("metadata") or {}
        users_by_id[str(user.get("user_id"))] = {
            "owner": str(user.get("display_name") or ""),
            "team": str(meta.get("team_name") or user.get("display_name") or ""),
        }
    roster_info = {}
    for roster in rosters or []:
        if not isinstance(roster, dict):
            continue
        owner = users_by_id.get(str(roster.get("owner_id")), {})
        settings = roster.get("settings") or {}
        record = f"{int(settings.get('wins') or 0)}-{int(settings.get('losses') or 0)}"
        if settings.get("ties"):
            record += f"-{int(settings['ties'])}"
        roster_info[roster.get("roster_id")] = {
            "name": owner.get("team") or f"TEAM {roster.get('roster_id')}",
            "owner": owner.get("owner") or "",
            "record": record,
        }
    pairs: Dict[Any, List[Dict[str, Any]]] = {}
    for m in matchups or []:
        if not isinstance(m, dict) or m.get("matchup_id") is None:
            continue
        info = roster_info.get(m.get("roster_id"), {"name": f"TEAM {m.get('roster_id')}",
                                                    "owner": "", "record": ""})
        pairs.setdefault(m["matchup_id"], []).append(dict(
            info, points=model.safe_float(m.get("points")) or 0.0))
    result = []
    for matchup_id in sorted(pairs):
        sides = pairs[matchup_id]
        if len(sides) != 2:
            continue
        result.append({"home": sides[0], "away": sides[1], "mine": False})
    return {"provider": "sleeper", "name": str((league or {}).get("name") or "LEAGUE"),
            "week": week, "matchups": result}


def normalize_espn_league(payload: Any, week: int) -> Dict[str, Any]:
    payload = payload or {}
    members = {str(m.get("id")): str(m.get("displayName") or "")
               for m in payload.get("members") or [] if isinstance(m, dict)}
    teams = {}
    for t in payload.get("teams") or []:
        if not isinstance(t, dict):
            continue
        name = t.get("name") or " ".join(
            part for part in (t.get("location"), t.get("nickname")) if part)
        owners = t.get("owners") or []
        overall = ((t.get("record") or {}).get("overall") or {})
        record = f"{int(overall.get('wins') or 0)}-{int(overall.get('losses') or 0)}"
        if overall.get("ties"):
            record += f"-{int(overall['ties'])}"
        teams[t.get("id")] = {
            "name": str(name or t.get("abbrev") or f"TEAM {t.get('id')}"),
            "abbrev": str(t.get("abbrev") or ""),
            "owner": members.get(str(owners[0])) if owners else "",
            "record": record,
        }
    status = payload.get("status") or {}
    period = week
    current = status.get("currentMatchupPeriod")
    latest = status.get("latestScoringPeriod")
    if current and latest and int(latest) == int(week):
        period = int(current)
    result = []
    for game in payload.get("schedule") or []:
        if not isinstance(game, dict) or game.get("matchupPeriodId") != period:
            continue
        sides = []
        for side in ("home", "away"):
            s = game.get(side) or {}
            if s.get("teamId") is None:
                continue
            pts = model.safe_float(s.get("totalPointsLive"))
            if pts is None:
                pts = model.safe_float(s.get("totalPoints")) or 0.0
            sides.append(dict(teams.get(s.get("teamId"), {"name": f"TEAM {s.get('teamId')}",
                                                         "owner": "", "record": ""}),
                              points=pts))
        if len(sides) == 2:
            result.append({"home": sides[0], "away": sides[1], "mine": False})
    settings = payload.get("settings") or {}
    return {"provider": "espn", "name": str(settings.get("name") or "LEAGUE"),
            "week": week, "matchups": result}


def order_matchups(league: Dict[str, Any], team_name: str = "") -> Dict[str, Any]:
    """Mark the configured team's matchup and move it to the front.

    ``team_name`` matches a team name, an ESPN abbreviation or an owner's
    display name, ignoring case and punctuation. The side that matched is
    swapped to ``home`` so the panel always draws "you" on the left.
    """
    wanted = model.normalize_name(team_name)
    out = dict(league)
    matchups = [dict(m) for m in league.get("matchups") or []]
    if wanted:
        for m in matchups:
            for side, other in (("home", "away"), ("away", "home")):
                s = m.get(side) or {}
                names = {model.normalize_name(s.get(k)) for k in ("name", "owner", "abbrev")}
                if wanted in names:
                    m["mine"] = True
                    if side == "away":
                        m["home"], m["away"] = m["away"], m["home"]
                    break
        matchups.sort(key=lambda m: 0 if m.get("mine") else 1)
    out["matchups"] = matchups
    return out


def describe_provider_problem(provider: str, league_id: Any, espn_s2: str, swid: str) -> Optional[str]:
    """A one-line reason the league cannot load, for the log and get_info()."""
    if provider not in PROVIDERS:
        return f"unknown league provider '{provider}'"
    if provider == "none":
        return None
    if not _clean_id(league_id):
        return "league sync is on but no league id is set"
    if provider == "espn" and bool(espn_s2) != bool(swid):
        return "an ESPN private league needs both espn_s2 and SWID"
    return None
