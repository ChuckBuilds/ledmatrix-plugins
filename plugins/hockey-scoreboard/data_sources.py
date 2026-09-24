"""
Pluggable Data Source Architecture

This module provides abstract data sources that can be plugged into the sports system
to support different APIs and data providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import requests
import logging
from datetime import datetime
# Prefer core's ESPN date-range helper, which core keeps current (orjson
# parsing, giving way to the Vegas render thread); fall back to the bundled
# copy on cores that don't ship src.common.espn_dates yet.
try:
    from src.common.espn_dates import ESPN_MAX_LIMIT, fetch_espn_scoreboard
except ModuleNotFoundError as exc:
    # Fall back only when the CORE module is absent; an import failure from
    # inside it should surface, not be masked.
    if exc.name not in {"src", "src.common", "src.common.espn_dates"}:
        raise
    from hockey_espn_dates import ESPN_MAX_LIMIT, fetch_espn_scoreboard

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
            now = datetime.now()
            formatted_date = now.strftime("%Y%m%d")
            url = f"{self.base_url}/{sport}/{league}/scoreboard"
            data = fetch_espn_scoreboard(
                self.session,
                url,
                params={"dates": formatted_date, "limit": ESPN_MAX_LIMIT},
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

    def fetch_game_summary(self, sport: str, league: str, event_id: str) -> Optional[Dict]:
        """Fetch the per-game summary (plays, boxscore) from the ESPN API.

        Hockey's goal scorer lives here and nowhere else: the scoreboard feed
        the rest of the plugin runs on carries the score but never who put the
        puck in. Only NHL answers with a `plays` array -- college hockey's
        summary has no play data at all -- which is why the goal-scorer card
        is gated on a league opting in (see espn_summary_sport_league)."""
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
        """Fetch a player's bio + season stats from ESPN's athlete endpoint.

        Returns a parsed dict (display_name, jersey, position, height, weight,
        age, birthplace, experience, team, headshot_url, stats) or None on any
        failure. The goal card renders from the play alone when this is
        unavailable, so a miss costs detail rather than the card."""
        if not player_id:
            return None
        try:
            url = f"{self._ATHLETE_BASE}/{sport}/{league}/athletes/{player_id}"
            response = self.session.get(url, headers=self.get_headers(), timeout=10)
            if response.status_code != 200:
                self.logger.debug(
                    f"Player bio HTTP {response.status_code} for "
                    f"{sport}/{league} {player_id}"
                )
                return None
            return self._parse_player_details(response.json())
        except Exception as e:
            self.logger.debug(f"Failed to fetch player details for {player_id}: {e}")
            return None

    @staticmethod
    def _parse_player_details(bio_data: Dict) -> Optional[Dict]:
        """Flatten ESPN's athlete record into the fields the card draws.

        Season stats come from `statsSummary`, which is ESPN's own
        position-appropriate pick -- G/A/PTS/+- for a skater, and save
        percentage and GAA for a goaltender -- already ordered for display.
        No separate stats request is needed."""
        try:
            athlete = bio_data.get("athlete") or bio_data
            if not isinstance(athlete, dict):
                return None

            position = athlete.get("position") or {}
            if isinstance(position, dict):
                position = (
                    position.get("abbreviation") or position.get("displayName") or ""
                )

            stat_pairs: List[Tuple[str, str]] = []
            summary = athlete.get("statsSummary") or {}
            for entry in summary.get("statistics") or []:
                if not isinstance(entry, dict):
                    continue
                label = (
                    entry.get("abbreviation")
                    or entry.get("shortDisplayName")
                    or entry.get("name")
                )
                value = entry.get("displayValue")
                if value is None:
                    value = entry.get("value")
                if label and value is not None:
                    stat_pairs.append((str(label), str(value)))

            team = athlete.get("team") or {}
            if not isinstance(team, dict):
                team = {}

            return {
                "player_id": athlete.get("id"),
                "display_name": athlete.get("displayName"),
                "jersey": athlete.get("jersey"),
                "position": position or "",
                "height": athlete.get("displayHeight") or athlete.get("height"),
                "weight": athlete.get("displayWeight") or athlete.get("weight"),
                "age": athlete.get("age"),
                "birthplace": athlete.get("displayBirthPlace"),
                "experience": athlete.get("displayExperience"),
                "headshot_url": (athlete.get("headshot") or {}).get("href"),
                "team_abbr": team.get("abbreviation"),
                "stat_pairs": stat_pairs,
                "stats_title": summary.get("displayName") if stat_pairs else None,
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
            games = data.get('dates', [{}])[0].get('games', [])
            
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
