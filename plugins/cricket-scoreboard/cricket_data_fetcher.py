"""
Cricket data fetcher for the Cricket Scoreboard plugin.

Cricket on ESPN has NO single stable league id (unlike, say, AFL's `afl` or
NRL's `3`). Instead ESPN organises cricket as dozens of concurrent, per-tour /
per-season numeric *series* ids. This module therefore:

  1. Periodically hits the cricket *header* endpoint to list every currently
     active series (with its numeric id, name and abbreviation).
  2. Resolves those series against the user's `favorite_competitions` (domestic
     league keys from competitions.json, matched by search_terms) and
     `favorite_teams` (national teams, matched by the team name appearing in a
     series' event names).
  3. Fetches each resolved series' `/scoreboard` and parses matches into a
     normalized internal dict.

Verified live against the real ESPN API (no auth):
  header:   https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket
  series:   https://site.api.espn.com/apis/site/v2/sports/cricket/{series_id}/scoreboard

Field shapes confirmed live:
  - competitions[].class.eventType -> "T20" (defensively also handle
    "T20I"/"ODI"/"Test"/"Twenty20"/"First-class")
  - competitions[].competitors[].score -> e.g. "161/5 (18/20 ov, target 156)"
  - competitions[].competitors[].linescores[] -> {period, runs, wickets, overs,
    isBatting, description}
  - status.type.state -> "pre" | "in" | "post"
  - status.summary -> human result string, e.g. "RCB won by 5 wkts (12b rem)"
"""

import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

HEADER_URL = "https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket"
SERIES_URL = "https://site.api.espn.com/apis/site/v2/sports/cricket/{series_id}/scoreboard"

_HEADERS = {
    "User-Agent": "LEDMatrix/2.0 (https://github.com/ChuckBuilds/LEDMatrix)",
    "Accept": "application/json",
}

# Default balls-per-innings by format, used only when the score string does not
# already carry a "(x/y ov)" max-overs hint.
FORMAT_MAX_OVERS = {
    "T20": 20,
    "T20I": 20,
    "TWENTY20": 20,
    "ODI": 50,
    "ODM": 50,
    "LIST A": 50,
    "THE HUNDRED": 100,  # The Hundred counts balls, not overs; handled loosely.
}

# States that ESPN uses in status.type.state.
STATE_PRE = "pre"
STATE_IN = "in"
STATE_POST = "post"


# --------------------------------------------------------------------------- #
# Overs math (base-6 fractional part) -- unit tested in test_cricket_plugin.py
# --------------------------------------------------------------------------- #

def overs_to_decimal(overs: float) -> float:
    """Convert cricket overs notation to a true decimal overs value.

    Cricket overs are base-6 in the fractional part: `18.4` means 18 completed
    overs PLUS 4 balls, i.e. 18 + 4/6 = 18.6667 decimal overs -- NOT 18.4.

    Args:
        overs: overs in cricket notation (e.g. 18.4, 20.0, 6.2).

    Returns:
        Decimal overs suitable for run-rate division (e.g. 18.6667).
    """
    if overs is None:
        return 0.0
    try:
        overs = float(overs)
    except (TypeError, ValueError):
        return 0.0
    if overs < 0:
        return 0.0
    whole = int(math.floor(overs))
    # Recover the balls digit robustly against float noise (e.g. 18.399999).
    balls = int(round((overs - whole) * 10))
    if balls >= 6:
        # Malformed notation (a legal over only has 0..5 in the fraction);
        # roll it forward rather than produce nonsense.
        whole += balls // 6
        balls = balls % 6
    return whole + balls / 6.0


def overs_to_balls(overs: float) -> int:
    """Return the total number of legal balls represented by an overs value."""
    if overs is None:
        return 0
    try:
        overs = float(overs)
    except (TypeError, ValueError):
        return 0
    if overs < 0:
        return 0
    whole = int(math.floor(overs))
    balls = int(round((overs - whole) * 10))
    if balls >= 6:
        whole += balls // 6
        balls = balls % 6
    return whole * 6 + balls


def current_run_rate(runs: int, overs: float) -> Optional[float]:
    """Current run rate = runs / decimal_overs. None if no overs bowled yet."""
    dec = overs_to_decimal(overs)
    if dec <= 0:
        return None
    return runs / dec


def required_run_rate(runs_needed: int, balls_remaining: int) -> Optional[float]:
    """Required run rate for a chase = runs_needed / (balls_remaining / 6).

    Args:
        runs_needed: runs still required to win (target - current runs).
        balls_remaining: legal balls left in the innings.

    Returns:
        Required runs per over, or None when no balls remain.
    """
    if balls_remaining <= 0:
        return None
    if runs_needed < 0:
        runs_needed = 0
    return runs_needed / (balls_remaining / 6.0)


# --------------------------------------------------------------------------- #
# Fetcher
# --------------------------------------------------------------------------- #

class CricketDataFetcher:
    """Discovers cricket series ids and fetches/parses their scoreboards."""

    def __init__(self, cache_manager, config: Dict[str, Any],
                 competitions: List[Dict[str, Any]], request_timeout: int = 30):
        self.cache_manager = cache_manager
        self.config = config or {}
        self.competitions = competitions or []
        self.request_timeout = request_timeout
        self.session = requests.Session()

        # competition key -> list of lowercase search terms
        self._comp_terms: Dict[str, List[str]] = {}
        for comp in self.competitions:
            key = comp.get("key")
            terms = comp.get("search_terms") or []
            self._comp_terms[key] = [t.lower() for t in terms]

        self._discovery_interval = int(self.config.get("series_discovery_interval", 86400))
        self._last_discovery = 0.0
        self._resolved_series: List[Dict[str, Any]] = []

    # ---- cache helpers ---------------------------------------------------- #

    def _cache_get(self, key: str, max_age: int) -> Any:
        """Best-effort cache read; any cache error is treated as a miss."""
        try:
            if self.cache_manager is None:
                return None
            return self.cache_manager.get(key, max_age=max_age)
        except TypeError:
            try:
                return self.cache_manager.get(key)
            except Exception:
                return None
        except Exception:
            return None

    def _cache_set(self, key: str, value: Any, ttl: int) -> None:
        try:
            if self.cache_manager is None:
                return
            self.cache_manager.set(key, value, ttl=ttl)
        except TypeError:
            try:
                self.cache_manager.set(key, value)
            except Exception:
                pass
        except Exception:
            pass

    # ---- HTTP ------------------------------------------------------------- #

    def _get_json(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            resp = self.session.get(url, headers=_HEADERS, timeout=self.request_timeout)
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload
                logger.warning("Cricket API %s returned non-object JSON", url)
                return None
            logger.warning("Cricket API %s returned HTTP %s", url, resp.status_code)
        except Exception as e:  # pragma: no cover - network failure path
            logger.warning("Cricket API request failed for %s: %s", url, e)
        return None

    # ---- series discovery ------------------------------------------------- #

    def _match_competition(self, league: Dict[str, Any],
                           enabled_keys: List[str]) -> Optional[str]:
        """Return the competition key a header league belongs to, or None."""
        haystacks = " ".join(
            str(league.get(f, "") or "")
            for f in ("name", "shortName", "shortAlternateName", "abbreviation")
        ).lower()
        for key in enabled_keys:
            if key == "international":
                continue  # international is handled by team matching
            for term in self._comp_terms.get(key, []):
                if term and term in haystacks:
                    return key
        return None

    @staticmethod
    def _league_event_text(league: Dict[str, Any]) -> str:
        parts = [str(league.get("name", "") or ""),
                 str(league.get("shortName", "") or "")]
        for ev in league.get("events", []) or []:
            parts.append(str(ev.get("name", "") or ""))
            parts.append(str(ev.get("shortName", "") or ""))
        return " ".join(parts).lower()

    def discover_series(self, force: bool = False) -> List[Dict[str, Any]]:
        """Resolve numeric series ids for the configured favorites.

        Returns a list of dicts: {'series_id', 'name', 'competition_key'}.
        Cached to `cricket:series_ids` for `series_discovery_interval` seconds.
        """
        now = time.time()
        if (not force and self._resolved_series
                and now - self._last_discovery < self._discovery_interval):
            return self._resolved_series

        enabled_keys = list(self.config.get("favorite_competitions",
                                            ["international", "ipl", "bbl"]))
        favorite_teams = [t.lower() for t in self.config.get("favorite_teams", [])]

        cache_key = "cricket:series_ids:" + "|".join(
            sorted(enabled_keys) + sorted(favorite_teams))
        cached = self._cache_get(cache_key, max_age=self._discovery_interval)
        if cached and not force:
            self._resolved_series = cached
            self._last_discovery = now
            return cached
        follow_international = "international" in enabled_keys

        data = self._get_json(HEADER_URL)
        resolved: List[Dict[str, Any]] = []
        seen_ids = set()
        if data:
            sports = data.get("sports", []) or []
            leagues = sports[0].get("leagues", []) if sports else []
            for league in leagues:
                sid = str(league.get("id", "") or "")
                if not sid or sid in seen_ids:
                    continue

                comp_key = self._match_competition(league, enabled_keys)

                # International: match a favorite national team appearing in the
                # series/event names (e.g. "India Women tour of England 2026").
                if comp_key is None and follow_international and favorite_teams:
                    text = self._league_event_text(league)
                    if any(team in text for team in favorite_teams):
                        comp_key = "international"

                if comp_key is None:
                    continue

                resolved.append({
                    "series_id": sid,
                    "name": league.get("name") or league.get("shortName") or sid,
                    "competition_key": comp_key,
                })
                seen_ids.add(sid)

        if resolved:
            self._cache_set(cache_key, resolved, ttl=self._discovery_interval)
        # If discovery failed but we have a stale cache, keep using it.
        if not resolved and cached:
            resolved = cached

        self._resolved_series = resolved
        self._last_discovery = now
        logger.info("Cricket series discovery resolved %d series: %s",
                    len(resolved), ", ".join(r["name"] for r in resolved) or "none")
        return resolved

    # ---- scoreboard fetch + parse ---------------------------------------- #

    def fetch_matches(self, ttl: int = 300) -> List[Dict[str, Any]]:
        """Fetch and parse matches for every resolved series."""
        series = self.discover_series()
        matches: List[Dict[str, Any]] = []
        for entry in series:
            sid = entry["series_id"]
            comp_key = entry["competition_key"]
            cache_key = f"cricket:scoreboard:{sid}"
            data = self._cache_get(cache_key, max_age=ttl)
            if data is None:
                data = self._get_json(SERIES_URL.format(series_id=sid))
                if data is not None:
                    self._cache_set(cache_key, data, ttl=ttl)
            if not data:
                continue
            for ev in data.get("events", []) or []:
                parsed = self._parse_event(ev, series_id=sid,
                                           series_name=entry["name"],
                                           competition_key=comp_key)
                if parsed:
                    matches.append(parsed)
        return matches

    def _parse_event(self, ev: Dict[str, Any], series_id: str, series_name: str,
                     competition_key: str) -> Optional[Dict[str, Any]]:
        try:
            comps = ev.get("competitions", []) or []
            if not comps:
                return None
            comp = comps[0]
            status = ev.get("status") or comp.get("status") or {}
            stype = status.get("type", {}) or {}
            state = (stype.get("state") or "pre").lower()

            cls = comp.get("class", {}) or {}
            event_type = (cls.get("eventType") or cls.get("generalClassCard") or "").strip()
            fmt = self._normalize_format(event_type)
            is_test = fmt in ("Test", "First-class")

            venue = ""
            v = comp.get("venue") or {}
            if v:
                venue = v.get("fullName") or ""

            teams = []
            for c in comp.get("competitors", []) or []:
                teams.append(self._parse_competitor(c))
            # Keep ESPN order (competitors are ordered home/away).
            teams.sort(key=lambda t: t.get("order", 0))

            target = self._parse_target(teams)

            match = {
                "id": str(ev.get("id", "")),
                "series_id": series_id,
                "series_name": series_name,
                "competition_key": competition_key,
                "name": ev.get("name", ""),
                "short_name": ev.get("shortName", ""),
                "format": fmt,
                "is_test": is_test,
                "state": state,
                "status_summary": status.get("summary", "") or "",
                "status_detail": stype.get("detail", "") or "",
                "status_short": stype.get("shortDetail", "") or "",
                "period": int(status.get("period", 0) or 0),
                "date": comp.get("date") or ev.get("date") or "",
                "start_time_utc": self._parse_iso(comp.get("date") or ev.get("date")),
                "venue": venue,
                "teams": teams,
                "target": target,
            }
            return match
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Failed to parse cricket event %s: %s", ev.get("id"), e)
            return None

    def _parse_competitor(self, c: Dict[str, Any]) -> Dict[str, Any]:
        team = c.get("team", {}) or {}
        innings = []
        for ls in c.get("linescores", []) or []:
            overs_raw = ls.get("overs", 0.0)
            innings.append({
                "period": int(ls.get("period", 0) or 0),
                "runs": int(ls.get("runs", 0) or 0),
                "wickets": int(ls.get("wickets", 0) or 0),
                "overs_raw": overs_raw,
                "overs_decimal": overs_to_decimal(overs_raw),
                "balls": overs_to_balls(overs_raw),
                "is_batting": bool(ls.get("isBatting", False)),
                "description": ls.get("description", "") or "",
            })

        logo_url = None
        logos = team.get("logos") or []
        if logos:
            logo_url = logos[0].get("href")

        records = ""
        rec = c.get("records") or []
        if rec and isinstance(rec, list):
            records = rec[0].get("summary", "") if isinstance(rec[0], dict) else ""

        return {
            "order": int(c.get("order", 0) or 0),
            "home_away": c.get("homeAway", ""),
            "id": str(team.get("id", "") or c.get("id", "")),
            "name": team.get("displayName") or team.get("name") or "",
            "short_name": team.get("shortDisplayName") or team.get("name") or "",
            "abbr": team.get("abbreviation") or "",
            "logo_url": logo_url,
            "winner": bool(c.get("winner", False)),
            "score_str": c.get("score", "") or "",
            "innings": innings,
            "records": records,
        }

    @staticmethod
    def _normalize_format(event_type: str) -> str:
        et = (event_type or "").strip().upper()
        if not et:
            return "T20"
        if "TEST" in et:
            return "Test"
        if "FIRST" in et:
            return "First-class"
        if et in ("T20I", "IT20"):
            return "T20I"
        if "T20" in et or "TWENTY20" in et or "TWENTY" in et:
            return "T20"
        if "ODI" in et or "ONE DAY" in et or "ONE-DAY" in et:
            return "ODI"
        if "HUNDRED" in et:
            return "The Hundred"
        if "LIST A" in et:
            return "ODI"
        return event_type.strip()

    @staticmethod
    def _parse_target(teams: List[Dict[str, Any]]) -> Optional[int]:
        """Extract the chase target from a competitor score string.

        e.g. "161/5 (18/20 ov, target 156)" -> 156
        """
        for t in teams:
            m = re.search(r"target\s+(\d+)", t.get("score_str", ""), re.IGNORECASE)
            if m:
                return int(m.group(1))
        return None

    @staticmethod
    def parse_max_overs(score_str: str, fmt: str) -> Optional[int]:
        """Extract max overs from a score string like '(18/20 ov...)'.

        Falls back to the format default (T20=20, ODI=50, ...).
        """
        m = re.search(r"/\s*(\d+)\s*ov", score_str or "", re.IGNORECASE)
        if m:
            return int(m.group(1))
        return FORMAT_MAX_OVERS.get((fmt or "").upper())

    @staticmethod
    def _parse_iso(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            v = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
