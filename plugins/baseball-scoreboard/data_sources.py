"""
Pluggable Data Source Architecture

This module provides abstract data sources that can be plugged into the sports system
to support different APIs and data providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import requests
import logging
from datetime import datetime

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
            'User-Agent': 'LEDMatrix/1.0',
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
            now = datetime.now()
            formatted_date = now.strftime("%Y%m%d")
            url = f"{self.base_url}/{sport}/{league}/scoreboard"
            response = self.session.get(url, params={"dates": formatted_date, "limit": 1000}, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
            events = data.get('events', [])

            # Filter for live games
            live_events = []
            for event in events:
                competitions = event.get('competitions', [])
                if not competitions:
                    continue
                if competitions[0].get('status', {}).get('type', {}).get('state') == 'in':
                    live_events.append(event)

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
        # Try standings endpoint first (for professional leagues like NFL)
        try:
            url = f"{self.base_url}/{sport}/{league}/standings"
            response = self.session.get(url, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
            self.logger.debug(f"Fetched standings for {sport}/{league}")
            return data
        except Exception as e:
            # If standings doesn't exist, try rankings (for college sports)
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
                # Non-404 error - log at error level since this is unexpected
                self.logger.error(f"Error fetching standings from ESPN for {sport}/{league}: {e}")
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


class MLBAPIDataSource(DataSource):
    """MLB API data source."""

    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        self.base_url = "https://statsapi.mlb.com/api/v1"

    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        """Fetch live games from MLB API."""
        try:
            url = f"{self.base_url}/schedule"
            params = {
                'sportId': 1,  # MLB
                'date': datetime.now().strftime('%Y-%m-%d'),
                'hydrate': 'game,team,venue,weather'
            }

            response = self.session.get(url, headers=self.get_headers(), params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            dates = data.get('dates', [])
            games = dates[0].get('games', []) if dates else []

            # Filter for live games
            live_games = [game for game in games
                         if game.get('status', {}).get('abstractGameState') == 'Live']

            self.logger.debug(f"Fetched {len(live_games)} live games from MLB API")
            return live_games

        except Exception as e:
            self.logger.error(f"Error fetching live games from MLB API: {e}")
            return []

    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Fetch schedule from MLB API."""
        try:
            start_date, end_date = date_range
            url = f"{self.base_url}/schedule"

            params = {
                'sportId': 1,  # MLB
                'startDate': start_date.strftime('%Y-%m-%d'),
                'endDate': end_date.strftime('%Y-%m-%d'),
                'hydrate': 'game,team,venue'
            }

            response = self.session.get(url, headers=self.get_headers(), params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            all_games = []
            for date_data in data.get('dates', []):
                all_games.extend(date_data.get('games', []))

            self.logger.debug(f"Fetched {len(all_games)} scheduled games from MLB API")
            return all_games

        except Exception as e:
            self.logger.error(f"Error fetching schedule from MLB API: {e}")
            return []

    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings from MLB API."""
        try:
            url = f"{self.base_url}/standings"
            params = {
                'leagueId': 103,  # American League
                'season': datetime.now().year,
                'standingsType': 'regularSeason'
            }

            response = self.session.get(url, headers=self.get_headers(), params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            self.logger.debug("Fetched standings from MLB API")
            return data

        except Exception as e:
            self.logger.error(f"Error fetching standings from MLB API: {e}")
            return {}


class SoccerAPIDataSource(DataSource):
    """Soccer API data source (generic structure)."""

    def __init__(self, logger: logging.Logger, api_key: str = None):
        super().__init__(logger)
        self.api_key = api_key
        self.base_url = "https://api.football-data.org/v4"  # Example API

    def get_headers(self) -> Dict[str, str]:
        """Get headers with API key for soccer API."""
        headers = super().get_headers()
        if self.api_key:
            headers['X-Auth-Token'] = self.api_key
        return headers

    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        """Fetch live games from soccer API."""
        try:
            # This would need to be adapted based on the specific soccer API
            url = f"{self.base_url}/matches"
            params = {
                'status': 'LIVE',
                'competition': league
            }

            response = self.session.get(url, headers=self.get_headers(), params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            matches = data.get('matches', [])

            self.logger.debug(f"Fetched {len(matches)} live games from soccer API")
            return matches

        except Exception as e:
            self.logger.error(f"Error fetching live games from soccer API: {e}")
            return []

    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Fetch schedule from soccer API."""
        try:
            start_date, end_date = date_range
            url = f"{self.base_url}/matches"

            params = {
                'competition': league,
                'dateFrom': start_date.strftime('%Y-%m-%d'),
                'dateTo': end_date.strftime('%Y-%m-%d')
            }

            response = self.session.get(url, headers=self.get_headers(), params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            matches = data.get('matches', [])

            self.logger.debug(f"Fetched {len(matches)} scheduled games from soccer API")
            return matches

        except Exception as e:
            self.logger.error(f"Error fetching schedule from soccer API: {e}")
            return []

    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings from soccer API."""
        try:
            url = f"{self.base_url}/competitions/{league}/standings"
            response = self.session.get(url, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
            self.logger.debug("Fetched standings from soccer API")
            return data

        except Exception as e:
            self.logger.error(f"Error fetching standings from soccer API: {e}")
            return {}


# Factory function removed - sport classes now instantiate data sources directly
