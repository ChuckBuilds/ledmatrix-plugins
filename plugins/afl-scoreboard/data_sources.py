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
            response = self.session.get(url, params={"dates": date_range, "limit": 1000}, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
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
                "limit": 1000
            }

            response = self.session.get(url, headers=self.get_headers(), params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            events = data.get('events', [])

            self.logger.debug(f"Fetched {len(events)} scheduled games for {sport}/{league}")
            return events

        except Exception as e:
            self.logger.error(f"Error fetching schedule from ESPN: {e}")
            return []

    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings from ESPN API."""
        # College sports use rankings endpoint, professional leagues use standings
        college_leagues = [
            "mens-college-basketball",
            "womens-college-basketball",
            "college-football",
        ]

        # For college sports, use rankings endpoint directly
        if league in college_leagues:
            try:
                url = f"{self.base_url}/{sport}/{league}/rankings"
                response = self.session.get(url, headers=self.get_headers(), timeout=15)
                response.raise_for_status()

                data = response.json()
                self.logger.debug(f"Fetched rankings for {sport}/{league}")
                return data
            except Exception as e:
                self.logger.debug(f"Error fetching rankings from ESPN for {sport}/{league}: {e}")
                return {}

        # For professional leagues, try standings endpoint first
        try:
            url = f"{self.base_url}/{sport}/{league}/standings"
            response = self.session.get(url, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
            self.logger.debug(f"Fetched standings for {sport}/{league}")
            return data
        except Exception as e:
            # If standings doesn't exist, try rankings as fallback
            if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 404:
                try:
                    url = f"{self.base_url}/{sport}/{league}/rankings"
                    response = self.session.get(url, headers=self.get_headers(), timeout=15)
                    response.raise_for_status()

                    data = response.json()
                    self.logger.debug(f"Fetched rankings for {sport}/{league} (fallback)")
                    return data
                except Exception:
                    # Both endpoints failed - standings/rankings may not be available for this sport/league
                    self.logger.debug(f"Standings/rankings not available for {sport}/{league} from ESPN API")
                    return {}
            else:
                # Non-404 error - log at debug level since standings are optional
                self.logger.debug(f"Error fetching standings from ESPN for {sport}/{league}: {e}")
                return {}


# Factory function removed - sport classes now instantiate data sources directly
