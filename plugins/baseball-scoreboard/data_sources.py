"""
Pluggable Data Source Architecture

This module provides abstract data sources that can be plugged into the sports system
to support different APIs and data providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
import requests
import logging

class DataSource(ABC):
    """Abstract base class for data sources."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.session = requests.Session()

        # Configure retry strategy
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    @abstractmethod
    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings for a sport/league."""

    def get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            'User-Agent': 'LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)',
            'Accept': 'application/json'
        }


class ESPNDataSource(DataSource):
    """ESPN API data source."""

    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports"

    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings, or the poll for leagues that have one.

        Order matters and used to be wrong. College leagues publish a poll at
        /rankings and a records table at /standings; professional leagues have
        only /standings. The old code tried /standings first and fell back to
        /rankings only on a 404 -- but college /standings answers 200, so the
        fallback never fired and college rankings came back empty forever.
        Nothing failed; the AP rank badge simply never appeared, and anything
        else keyed off rankings quietly did nothing.

        A 200 that lacks the key is treated as a miss, so a league answering
        both endpoints still ends up with whichever one actually carries a poll.
        """
        league_name = (league or "").lower()
        wants_poll = "college" in league_name or "ncaa" in league_name
        endpoints = ["rankings", "standings"] if wants_poll else ["standings", "rankings"]

        for endpoint in endpoints:
            try:
                url = f"{self.base_url}/{sport}/{league}/{endpoint}"
                response = self.session.get(
                    url, headers=self.get_headers(), timeout=15
                )
                response.raise_for_status()
                data = response.json()
                if endpoint == "rankings" and not data.get("rankings"):
                    continue
                self.logger.debug(f"Fetched {endpoint} for {sport}/{league}")
                return data
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status not in (404, None):
                    self.logger.error(
                        f"Error fetching {endpoint} from ESPN for "
                        f"{sport}/{league}: {e}"
                    )
        self.logger.debug(
            f"Standings/rankings not available for {sport}/{league} from ESPN API"
        )
        return {}

    def fetch_game_summary(self, sport: str, league: str, event_id: str) -> Optional[Dict]:
        """Fetch the per-game summary (play-by-play, rosters) from ESPN API."""
        try:
            url = f"{self.base_url}/{sport}/{league}/summary"
            response = self.session.get(url, params={"event": event_id}, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
            self.logger.debug(f"Fetched game summary for {sport}/{league} event {event_id}")
            return data

        except Exception as e:
            self.logger.error(f"Error fetching game summary from ESPN for {sport}/{league} event {event_id}: {e}")
            return None

    # ESPN's athlete bio/stats live on a different host than the scoreboard
    # (site.web.api vs site.api), under the common/v3 tree.
    _ATHLETE_BASE = "https://site.web.api.espn.com/apis/common/v3/sports"

    def fetch_player_details(self, sport: str, league: str, player_id: str) -> Optional[Dict]:
        """Fetch a player's bio + season stats from ESPN's athlete + overview
        endpoints. Returns a parsed dict (display_name, jersey, position, bat,
        throw, height, weight, headshot_url, stats) or None on any failure.

        Mirrors the masters plugin's fetch_player_details; the bio endpoint
        carries the identity/headshot and the /overview endpoint carries the
        season statistics (which NCAA feeds may omit -- handled gracefully)."""
        if not player_id:
            return None
        try:
            bio_url = f"{self._ATHLETE_BASE}/{sport}/{league}/athletes/{player_id}"
            bio_resp = self.session.get(bio_url, headers=self.get_headers(), timeout=10)
            if bio_resp.status_code != 200:
                self.logger.debug(
                    f"Player bio HTTP {bio_resp.status_code} for {sport}/{league} {player_id}"
                )
                return None
            bio_data = bio_resp.json()

            overview_data = None
            try:
                overview_resp = self.session.get(
                    f"{bio_url}/overview", headers=self.get_headers(), timeout=10
                )
                if overview_resp.status_code == 200:
                    overview_data = overview_resp.json()
            except Exception as e:
                self.logger.debug(f"Player overview fetch failed for {player_id}: {e}")

            return self._parse_player_details(bio_data, overview_data)
        except Exception as e:
            self.logger.debug(f"Failed to fetch player details for {player_id}: {e}")
            return None

    @staticmethod
    def _parse_player_details(bio_data: Dict, overview_data: Optional[Dict]) -> Optional[Dict]:
        """Combine the bio + overview responses into one flat player dict.

        The overview's statistics block is `{names/labels: [...], splits:
        [{stats: [...]}, ...]}` -- we zip the labels against the first split's
        values into a {label: value} map, then pull the baseball-relevant ones
        (AVG/HR/RBI for hitters, ERA/W-L/K for pitchers) while keeping the full
        map so anything ESPN provides is available to the renderer."""
        try:
            athlete = bio_data.get("athlete") or bio_data
            if not isinstance(athlete, dict):
                return None

            headshot = (athlete.get("headshot") or {}).get("href")
            position = athlete.get("position") or {}
            if isinstance(position, dict):
                position = position.get("abbreviation") or position.get("displayName") or ""

            stats: Dict[str, str] = {}
            if overview_data:
                stat_block = overview_data.get("statistics") or {}
                labels = stat_block.get("names") or stat_block.get("labels") or []
                splits = stat_block.get("splits") or []
                chosen = splits[0] if isinstance(splits, list) and splits else None
                if isinstance(chosen, dict):
                    values = chosen.get("stats") or []
                    for label, value in zip(labels, values):
                        if label:
                            stats[str(label)] = value

            return {
                "player_id": athlete.get("id"),
                "display_name": athlete.get("displayName"),
                "first_name": athlete.get("firstName"),
                "last_name": athlete.get("lastName"),
                "jersey": athlete.get("jersey"),
                "position": position or "",
                "bat": (athlete.get("bats") or {}).get("abbreviation")
                if isinstance(athlete.get("bats"), dict) else athlete.get("bats"),
                "throw": (athlete.get("throws") or {}).get("abbreviation")
                if isinstance(athlete.get("throws"), dict) else athlete.get("throws"),
                "height": athlete.get("displayHeight") or athlete.get("height"),
                "weight": athlete.get("displayWeight") or athlete.get("weight"),
                "headshot_url": headshot,
                "stats": stats,
            }
        except Exception:
            return None


# Factory function removed - sport classes now instantiate data sources directly
