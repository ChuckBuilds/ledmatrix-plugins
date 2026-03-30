"""
Masters Tournament Data Source

Handles all data fetching from ESPN Golf API with proper caching.
Supports mock data mode for testing when Masters isn't live.
Enriches player data with real ESPN headshot URLs and country codes.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from masters_helpers import ESPN_HEADSHOT_URL, ESPN_PLAYER_IDS, get_espn_headshot_url, get_player_country

logger = logging.getLogger(__name__)


class MastersDataSource:
    """Fetches and caches Masters Tournament data from ESPN Golf API."""

    LEADERBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard"
    SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/schedule"
    NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/news"

    def __init__(self, cache_manager, config: Dict[str, Any]):
        self.cache_manager = cache_manager
        self.config = config
        self.mock_mode = config.get("mock_data", False)
        self.logger = logging.getLogger(__name__)

    def fetch_leaderboard(self) -> List[Dict]:
        """Fetch current Masters leaderboard with caching."""
        if self.mock_mode:
            return self._generate_mock_leaderboard()

        cache_key = "masters_leaderboard"
        ttl = self._get_cache_ttl()

        cached = self.cache_manager.get(cache_key, max_age=ttl)
        if cached:
            self.logger.debug("Using cached leaderboard data")
            return cached

        try:
            response = requests.get(
                self.LEADERBOARD_URL,
                timeout=10,
                headers={"User-Agent": "LEDMatrix Masters Plugin/2.0"},
            )
            response.raise_for_status()
            data = response.json()

            is_masters = self._is_masters_tournament(data)
            if not is_masters:
                self.logger.info("Masters not currently in ESPN API, using mock data")
                mock = self._generate_mock_leaderboard()
                self.cache_manager.set(cache_key, mock, ttl=3600)
                return mock

            parsed = self._parse_leaderboard(data)
            self.cache_manager.set(cache_key, parsed, ttl=ttl)
            return parsed

        except Exception as e:
            self.logger.error(f"Failed to fetch leaderboard: {e}")
            return self._get_fallback_data(cache_key)

    def fetch_schedule(self) -> List[Dict]:
        """Fetch Masters schedule with tee times and pairings."""
        if self.mock_mode:
            return self._generate_mock_schedule()

        cache_key = "masters_schedule"
        ttl = 300

        cached = self.cache_manager.get(cache_key, max_age=ttl)
        if cached:
            return cached

        try:
            response = requests.get(
                self.SCHEDULE_URL,
                timeout=10,
                headers={"User-Agent": "LEDMatrix Masters Plugin/2.0"},
            )
            response.raise_for_status()
            data = response.json()

            parsed = self._parse_schedule(data)
            self.cache_manager.set(cache_key, parsed, ttl=ttl)
            return parsed

        except Exception as e:
            self.logger.error(f"Failed to fetch schedule: {e}")
            return self._get_fallback_data(cache_key)

    def fetch_player_details(self, player_id: str) -> Optional[Dict]:
        """Fetch detailed player statistics."""
        cache_key = f"masters_player_{player_id}"
        ttl = self._get_cache_ttl()

        cached = self.cache_manager.get(cache_key, max_age=ttl)
        if cached:
            return cached

        return None

    def _is_masters_tournament(self, data: Dict) -> bool:
        """Check if the current tournament in ESPN data is the Masters."""
        try:
            events = data.get("events", [])
            if not events:
                return False
            name = events[0].get("name", "").lower()
            return any(kw in name for kw in ["masters", "augusta national", "augusta"])
        except Exception:
            return False

    def _parse_leaderboard(self, data: Dict) -> List[Dict]:
        """Extract and enrich fields from ESPN leaderboard API response."""
        players = []

        try:
            events = data.get("events", [])
            if not events:
                return players

            competitions = events[0].get("competitions", [])
            if not competitions:
                return players

            competitors = competitions[0].get("competitors", [])

            for entry in competitors:
                athlete = entry.get("athlete", {})
                status = entry.get("status", {})
                score_data = entry.get("score", {})

                player_name = athlete.get("displayName", "Unknown")
                player_id = athlete.get("id", "")

                # Get headshot - prefer ESPN API data, fall back to our DB
                headshot_url = athlete.get("headshot", {}).get("href")
                if not headshot_url:
                    headshot_url = get_espn_headshot_url(player_name)

                # Get country from our DB if not in API
                country = ""
                flag_data = athlete.get("flag", {})
                if flag_data:
                    country = flag_data.get("alt", "")
                    # Normalize to 3-letter code
                    if len(country) > 3:
                        country = get_player_country(player_name) or ""
                if not country:
                    country = get_player_country(player_name) or ""

                players.append({
                    "position": entry.get("position", 0),
                    "player": player_name,
                    "player_id": player_id,
                    "country": country,
                    "score": self._calculate_score_to_par(entry),
                    "today": self._get_today_score(score_data),
                    "thru": status.get("thru", "F"),
                    "rounds": self._extract_round_scores(entry),
                    "headshot_url": headshot_url,
                    "current_hole": status.get("hole"),
                    "status": status.get("displayValue", ""),
                })

        except Exception as e:
            self.logger.error(f"Error parsing leaderboard: {e}")

        return players

    def _calculate_score_to_par(self, entry: Dict) -> int:
        """Calculate player's score relative to par."""
        try:
            display_value = entry.get("score", {}).get("displayValue", "E")
            if display_value == "E":
                return 0
            elif display_value.startswith("+"):
                return int(display_value[1:])
            elif display_value.startswith("-"):
                return int(display_value)
            return 0
        except Exception:
            return 0

    def _get_today_score(self, score_data: Dict) -> Optional[int]:
        """Get today's round score relative to par."""
        try:
            value = score_data.get("value")
            if value is not None:
                return int(value)
        except Exception:
            pass
        return None

    def _extract_round_scores(self, entry: Dict) -> List[Optional[int]]:
        """Extract scores for each round."""
        rounds = [None, None, None, None]
        try:
            linescores = entry.get("linescores", [])
            for i, linescore in enumerate(linescores[:4]):
                value = linescore.get("value")
                if value is not None:
                    rounds[i] = int(value)
        except Exception:
            pass
        return rounds

    def _parse_schedule(self, data: Dict) -> List[Dict]:
        """Parse schedule data from ESPN API."""
        schedule = []
        try:
            events = data.get("events", [])
            if events:
                competitions = events[0].get("competitions", [])
                for comp in competitions:
                    tee_times = comp.get("teeTimes", [])
                    for tt in tee_times:
                        players_list = []
                        for competitor in tt.get("competitors", []):
                            athlete = competitor.get("athlete", {})
                            players_list.append(athlete.get("displayName", "Unknown"))
                        schedule.append({
                            "time": tt.get("startTime", "TBD"),
                            "players": players_list,
                        })
        except Exception as e:
            self.logger.error(f"Error parsing schedule: {e}")
        return schedule

    def _get_cache_ttl(self) -> int:
        """Get appropriate cache TTL based on tournament phase."""
        phase = self._detect_tournament_phase()
        if phase == "tournament":
            return 30
        elif phase == "practice":
            return 300
        return 3600

    def _detect_tournament_phase(self) -> str:
        """Detect if it's practice rounds, tournament, or off-season."""
        now = datetime.now()
        if now.month == 4:
            if 7 <= now.day <= 9:
                return "practice"
            elif 10 <= now.day <= 13:
                return "tournament"
        return "off-season"

    def _get_fallback_data(self, cache_key: str) -> List[Dict]:
        """Get stale cached data or mock data as fallback."""
        cached = self.cache_manager.get(cache_key, max_age=None)
        if cached:
            self.logger.warning("Using stale cached data for %s", cache_key)
            return cached

        self.logger.warning("No fallback data for %s, using mock", cache_key)
        if "leaderboard" in cache_key:
            return self._generate_mock_leaderboard()
        return []

    def _generate_mock_leaderboard(self) -> List[Dict]:
        """Generate realistic mock leaderboard with real player data."""
        players = [
            {"pos": 1,    "name": "Scottie Scheffler",  "score": -12, "today": -4, "thru": 15, "rounds": [68, 67, 69, None]},
            {"pos": 2,    "name": "Rory McIlroy",       "score": -10, "today": -3, "thru": 16, "rounds": [70, 68, 68, None]},
            {"pos": 3,    "name": "Jon Rahm",           "score": -9,  "today": -2, "thru": 14, "rounds": [69, 69, 69, None]},
            {"pos": "T4", "name": "Brooks Koepka",      "score": -7,  "today": -1, "thru": 15, "rounds": [71, 68, 70, None]},
            {"pos": "T4", "name": "Viktor Hovland",     "score": -7,  "today": -2, "thru": 13, "rounds": [70, 69, 70, None]},
            {"pos": 6,    "name": "Xander Schauffele",  "score": -6,  "today": 0,  "thru": 16, "rounds": [68, 71, 69, None]},
            {"pos": 7,    "name": "Collin Morikawa",    "score": -5,  "today": -1, "thru": 14, "rounds": [72, 68, 69, None]},
            {"pos": 8,    "name": "Jordan Spieth",      "score": -4,  "today": 0,  "thru": 15, "rounds": [70, 70, 70, None]},
            {"pos": "T9", "name": "Patrick Cantlay",    "score": -3,  "today": -1, "thru": 12, "rounds": [71, 70, 70, None]},
            {"pos": "T9", "name": "Ludvig Aberg",       "score": -3,  "today": +1, "thru": 14, "rounds": [69, 71, 71, None]},
            {"pos": 11,   "name": "Tiger Woods",        "score": -2,  "today": 0,  "thru": 13, "rounds": [72, 70, 70, None]},
            {"pos": 12,   "name": "Hideki Matsuyama",   "score": -1,  "today": +1, "thru": 15, "rounds": [70, 72, 69, None]},
            {"pos": "T13","name": "Tommy Fleetwood",    "score": 0,   "today": 0,  "thru": 14, "rounds": [71, 71, 70, None]},
            {"pos": "T13","name": "Shane Lowry",        "score": 0,   "today": -1, "thru": 12, "rounds": [73, 70, 69, None]},
            {"pos": 15,   "name": "Adam Scott",         "score": +1,  "today": +2, "thru": 16, "rounds": [72, 70, 73, None]},
        ]

        result = []
        for p in players:
            name = p["name"]
            pid_info = ESPN_PLAYER_IDS.get(name, {})
            player_id = pid_info.get("id", f"mock_{name.replace(' ', '_')}")
            country = pid_info.get("country", "USA")
            headshot_url = get_espn_headshot_url(name)

            result.append({
                "position": p["pos"],
                "player": name,
                "player_id": player_id,
                "country": country,
                "score": p["score"],
                "today": p["today"],
                "thru": p["thru"],
                "rounds": p["rounds"],
                "headshot_url": headshot_url,
                "current_hole": p["thru"] + 1 if isinstance(p["thru"], int) and p["thru"] < 18 else None,
                "status": f"Thru {p['thru']}",
            })

        return result

    def _generate_mock_schedule(self) -> List[Dict]:
        """Generate mock schedule data."""
        return [
            {"time": "8:00 AM",  "players": ["Tiger Woods", "Phil Mickelson", "Adam Scott"]},
            {"time": "8:15 AM",  "players": ["Scottie Scheffler", "Rory McIlroy", "Jon Rahm"]},
            {"time": "8:30 AM",  "players": ["Brooks Koepka", "Viktor Hovland", "Xander Schauffele"]},
            {"time": "8:45 AM",  "players": ["Jordan Spieth", "Collin Morikawa", "Patrick Cantlay"]},
            {"time": "9:00 AM",  "players": ["Ludvig Aberg", "Hideki Matsuyama", "Tommy Fleetwood"]},
            {"time": "9:15 AM",  "players": ["Shane Lowry", "Tony Finau", "Max Homa"]},
        ]
