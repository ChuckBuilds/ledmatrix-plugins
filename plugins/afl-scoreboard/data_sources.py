"""
Pluggable Data Source Architecture

This module provides abstract data sources that can be plugged into the sports system
to support different APIs and data providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List
import requests
import logging
from datetime import datetime, timedelta
from afl_espn_dates import ESPN_MAX_LIMIT, fetch_espn_scoreboard

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
    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        """Fetch live games for a sport/league."""

    @abstractmethod
    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Fetch schedule for a sport/league within date range."""

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

    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        """Fetch live games from ESPN API."""
        try:
            # Query a small range around the host's current local date, not
            # just today -- AFL games are scheduled in Australian time zones,
            # so a game already live can fall on a different calendar date
            # than the host machine's "today" near a date boundary.
            now = datetime.now()
            date_range = f"{(now - timedelta(days=1)).strftime('%Y%m%d')}-{(now + timedelta(days=1)).strftime('%Y%m%d')}"
            url = f"{self.base_url}/{sport}/{league}/scoreboard"
            data = fetch_espn_scoreboard(
                self.session,
                url,
                params={"dates": date_range, "limit": ESPN_MAX_LIMIT},
                headers=self.get_headers(),
                timeout=15,
                logger=self.logger,
            )
            events = data.get('events', [])

            # Filter for live games
            live_events = [event for event in events
                          if event.get('competitions', [{}])[0].get('status', {}).get('type', {}).get('state') == 'in']

            self.logger.debug(f"Fetched {len(live_events)} live games for {sport}/{league}")
            return live_events

        except Exception as e:
            self.logger.error(f"Error fetching live games from ESPN: {e}")
            return []

    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Fetch schedule from ESPN API."""
        try:
            start_date, end_date = date_range
            url = f"{self.base_url}/{sport}/{league}/scoreboard"

            params = {
                'dates': f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}",
                "limit": ESPN_MAX_LIMIT
            }

            data = fetch_espn_scoreboard(
                self.session,
                url,
                headers=self.get_headers(),
                params=params,
                timeout=15,
                logger=self.logger,
            )
            events = data.get('events', [])

            self.logger.debug(f"Fetched {len(events)} scheduled games for {sport}/{league}")
            return events

        except Exception as e:
            self.logger.error(f"Error fetching schedule from ESPN: {e}")
            return []

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
                # Only a 404 is routine -- it is how a league says "no poll
                # here". Everything else is worth an error, and `status is
                # None` covers the ones that matter most: ConnectionError,
                # Timeout, a body that would not parse. Silencing those left a
                # board that could not reach ESPN with one debug line, and the
                # ranked filter running on an empty table.
                if status != 404:
                    self.logger.error(
                        f"Error fetching {endpoint} from ESPN for "
                        f"{sport}/{league}: {e}"
                    )
        self.logger.debug(
            f"Standings/rankings not available for {sport}/{league} from ESPN API"
        )
        return {}


# Factory function removed - sport classes now instantiate data sources directly
