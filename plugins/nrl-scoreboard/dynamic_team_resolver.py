"""
DynamicTeamResolver for the NRL plugin

Resolves user-configured team strings (favorite_teams / exclude_teams) to
ESPN team IDs.

NRL's ESPN abbreviations are NOT unique: Newcastle Knights and New Zealand
Warriors both use "NEW", and Canberra Raiders and Canterbury Bulldogs both
use "CAN". Matching favorite/excluded teams by abbreviation therefore
silently conflates unrelated teams (a user configuring "NEW" for the
Newcastle Knights would also match every New Zealand Warriors game).

To avoid that, this resolver converts each configured entry into a unique
ESPN team ID by fetching the NRL team list once (cached in-process) and
matching against team names first, then abbreviations - but only when an
abbreviation maps to exactly one team. Every downstream membership check in
sports.py compares team IDs (home_id/away_id) against the output of
resolve_teams(), so resolution here must produce team IDs.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

NRL_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/rugby-league/3/teams?limit=50"


class DynamicTeamResolver:
    """
    Resolves NRL team names/abbreviations/IDs to canonical ESPN team IDs.
    """

    # Class-level cache shared across instances/managers so the teams list
    # is fetched at most once per process (per cache_duration window).
    _teams_index_cache: Dict[str, dict] = {}
    _teams_index_timestamp: Dict[str, float] = {}
    _cache_duration: int = 24 * 3600  # team ids/abbreviations don't change intra-season

    def __init__(self, request_timeout: int = 15):
        """Initialize the dynamic team resolver."""
        self.request_timeout = request_timeout
        self.logger = logger

    def resolve_teams(self, team_list: List[str], sport: str = 'rugby-league') -> List[str]:
        """
        Resolve a list of team names/abbreviations/IDs to ESPN team IDs.

        Args:
            team_list: List of team names, abbreviations, or ESPN team IDs
            sport: Sport type for context (default: 'rugby-league')

        Returns:
            List of resolved ESPN team IDs (as strings). Entries that could
            not be resolved (fetch failed, no match, ambiguous abbreviation)
            are passed through unchanged and logged so the underlying issue
            is visible.
        """
        if not team_list:
            return []

        index = self._get_teams_index(sport)

        resolved_teams = [self._resolve_one(team, index) for team in team_list]

        # Remove duplicates while preserving order
        seen = set()
        unique_teams = []
        for team in resolved_teams:
            if team not in seen:
                seen.add(team)
                unique_teams.append(team)

        return unique_teams

    def _resolve_one(self, team: str, index: Optional[dict]) -> str:
        raw = (team or "").strip()
        if not raw:
            return raw

        if raw.isdigit():
            # Already an ESPN team ID.
            return raw

        if not index:
            self.logger.warning(
                f"NRL team list unavailable; using '{raw}' as-is for "
                "favorite/exclude matching. If this is an abbreviation it "
                "may not be unique (e.g. 'NEW' matches both Newcastle "
                "Knights and New Zealand Warriors)."
            )
            return raw

        key = raw.lower()

        by_name = index["by_name"]
        if key in by_name:
            return by_name[key]

        by_abbr = index["by_abbr"]
        candidates = by_abbr.get(key)
        if not candidates:
            self.logger.warning(
                f"Could not resolve NRL team '{raw}' to a known team; using "
                "it as-is. Use the full team name (e.g. 'Newcastle Knights') "
                "or the ESPN team ID instead of an abbreviation."
            )
            return raw

        if len(candidates) > 1:
            names = ", ".join(f"{name} (id {tid})" for tid, name in candidates)
            self.logger.error(
                f"NRL abbreviation '{raw}' is ambiguous - it matches multiple "
                f"teams: {names}. Configure the full team name or the ESPN "
                "team ID in favorite_teams/exclude_teams instead."
            )
            return raw

        return candidates[0][0]

    def _get_teams_index(self, sport: str) -> Optional[dict]:
        if sport not in ('rugby-league', 'nrl'):
            return None

        now = time.time()
        cached = DynamicTeamResolver._teams_index_cache.get(sport)
        cached_at = DynamicTeamResolver._teams_index_timestamp.get(sport, 0)
        if cached and (now - cached_at) < self._cache_duration:
            return cached

        fetched = self._fetch_teams_index()
        if fetched:
            DynamicTeamResolver._teams_index_cache[sport] = fetched
            DynamicTeamResolver._teams_index_timestamp[sport] = now
            return fetched

        # Fetch failed: fall back to a stale cache rather than nothing.
        return cached

    def _fetch_teams_index(self) -> Optional[dict]:
        try:
            response = requests.get(NRL_TEAMS_URL, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            self.logger.warning(
                f"Failed to fetch NRL team list for favorite/exclude team "
                f"resolution: {e}"
            )
            return None

        return self._build_index(data)

    @staticmethod
    def _build_index(data: dict) -> Optional[dict]:
        try:
            teams = data["sports"][0]["leagues"][0]["teams"]
        except (KeyError, IndexError, TypeError):
            logger.warning(
                "Unexpected NRL teams response shape; cannot resolve "
                "favorite/exclude teams"
            )
            return None

        by_name: Dict[str, str] = {}
        by_abbr: Dict[str, List[Tuple[str, str]]] = {}

        for entry in teams:
            t = entry.get("team", {})
            team_id = t.get("id")
            if not team_id:
                continue
            display_name = t.get("displayName") or t.get("name") or ""

            for name in (
                t.get("displayName"),
                t.get("shortDisplayName"),
                t.get("name"),
                t.get("location"),
                t.get("nickname"),
            ):
                if name:
                    by_name[name.strip().lower()] = team_id

            abbr = t.get("abbreviation")
            if abbr:
                by_abbr.setdefault(abbr.strip().lower(), []).append(
                    (team_id, display_name or abbr)
                )

        if not by_name and not by_abbr:
            return None
        return {"by_name": by_name, "by_abbr": by_abbr}
