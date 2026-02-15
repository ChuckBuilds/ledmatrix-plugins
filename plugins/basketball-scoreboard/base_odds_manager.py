"""
BaseOddsManager - Base class for odds data fetching and management.

This base class provides core odds fetching functionality that can be inherited
by plugins that need odds data (odds ticker, scoreboards, etc.).

Follows LEDMatrix configuration management patterns:
- Single responsibility: Data fetching only
- Reusable: Other plugins can inherit from it
- Clean configuration: Separate config sections
- Maintainable: Changes to odds logic affect all plugins
"""

import time
import logging
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import pytz

# Import the API counter function from web interface
try:
    from web_interface_v2 import increment_api_counter
except ImportError:
    # Fallback if web interface is not available
    def increment_api_counter(kind: str, count: int = 1):
        pass


class BaseOddsManager:
    """
    Base class for odds data fetching and management.

    Provides core functionality for:
    - ESPN API odds fetching
    - Caching and data processing
    - Error handling and timeouts
    - League mapping and data extraction

    Plugins can inherit from this class to get odds functionality.
    """

    def __init__(self, cache_manager, config_manager=None):
        """
        Initialize the base odds manager.

        Args:
            cache_manager: Cache manager instance for data persistence
            config_manager: Configuration manager (optional)
        """
        self.cache_manager = cache_manager
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://sports.core.api.espn.com/v2/sports"

        # Configuration with defaults
        self.update_interval = 3600  # 1 hour default
        self.request_timeout = 30  # 30 seconds default

        # Load configuration if available
        if config_manager:
            self._load_configuration()

    def _load_configuration(self):
        """Load configuration from config manager."""
        if not self.config_manager:
            return

        try:
            config = self.config_manager.get_config()
            odds_config = config.get("base_odds_manager", {})

            self.update_interval = odds_config.get(
                "update_interval", self.update_interval
            )
            self.request_timeout = odds_config.get("timeout", self.request_timeout)

            self.logger.debug(
                f"BaseOddsManager configuration loaded: "
                f"update_interval={self.update_interval}s, "
                f"timeout={self.request_timeout}s"
            )

        except Exception as e:
            self.logger.warning(f"Failed to load BaseOddsManager configuration: {e}")

    def get_odds(
        self,
        sport: str | None,
        league: str | None,
        event_id: str,
        update_interval_seconds: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch odds data for a specific game.

        Args:
            sport: Sport name (e.g., 'football', 'basketball')
            league: League name (e.g., 'nfl', 'nba')
            event_id: ESPN event ID
            update_interval_seconds: Override default update interval

        Returns:
            Dictionary containing odds data or None if unavailable
        """
        if sport is None or league is None:
            raise ValueError("Sport and League cannot be None")

        # Use provided interval or default
        interval = update_interval_seconds or self.update_interval
        cache_key = f"odds_espn_{sport}_{league}_{event_id}"

        # Check cache first
        cached_data = self.cache_manager.get(cache_key)

        if cached_data:
            # Filter out the "no_odds" marker - it should not be returned
            # as valid odds data.  Treat it as a cache miss so a fresh API
            # call is made once the cache entry expires.
            if isinstance(cached_data, dict) and cached_data.get("no_odds"):
                self.logger.debug(f"Cached no-odds marker for {cache_key}, skipping")
            else:
                self.logger.info(f"Using cached odds from ESPN for {cache_key}")
                return cached_data

        self.logger.info(f"Cache miss - fetching fresh odds from ESPN for {cache_key}")

        try:
            # Map league names to ESPN API format
            league_mapping = {
                "ncaa_fb": "college-football",
                "nfl": "nfl",
                "nba": "nba",
                "wnba": "wnba",
                "ncaam": "mens-college-basketball",
                "ncaaw": "womens-college-basketball",
                "mens-college-basketball": "mens-college-basketball",
                "womens-college-basketball": "womens-college-basketball",
                "mlb": "mlb",
                "nhl": "nhl",
            }

            espn_league = league_mapping.get(league, league)
            url = f"{self.base_url}/{sport}/leagues/{espn_league}/events/{event_id}/competitions/{event_id}/odds"
            self.logger.info(f"Requesting odds from URL: {url}")

            response = requests.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            raw_data = response.json()

            # Increment API counter for odds data
            increment_api_counter("odds", 1)
            self.logger.debug(
                f"Received raw odds data from ESPN: {json.dumps(raw_data, indent=2)}"
            )

            odds_data = self._extract_espn_data(raw_data)
            if odds_data:
                self.logger.info(f"Successfully extracted odds data: {odds_data}")
            else:
                self.logger.debug("No odds data available for this game")

            if odds_data:
                self.cache_manager.set(cache_key, odds_data, ttl=interval)
                self.logger.info(f"Saved odds data to cache for {cache_key}")
            else:
                self.logger.debug(f"No odds data available for {cache_key}")
                # Cache the fact that no odds are available to avoid repeated API calls
                self.cache_manager.set(cache_key, {"no_odds": True}, ttl=interval)

            return odds_data

        except requests.exceptions.RequestException as e:
            self.logger.exception(f"Error fetching odds from ESPN API for {cache_key}")
        except json.JSONDecodeError:
            self.logger.exception(
                f"Error decoding JSON response from ESPN API for {cache_key}"
            )

        # Return cached odds on error, but filter out the no_odds sentinel
        cached = self.cache_manager.get(cache_key)
        if isinstance(cached, dict) and cached.get("no_odds"):
            return None
        return cached

    def _extract_espn_data(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract and format odds data from ESPN API response.

        Args:
            data: Raw ESPN API response data

        Returns:
            Formatted odds data dictionary or None
        """
        self.logger.debug(f"Extracting ESPN odds data. Data keys: {list(data.keys())}")

        if "items" in data and data["items"]:
            self.logger.debug(f"Found {len(data['items'])} items in odds data")
            item = data["items"][0]
            self.logger.debug(f"First item keys: {list(item.keys())}")

            # The ESPN API returns odds data directly in the item, not in a providers array
            # Extract the odds data directly from the item
            extracted_data = {
                "details": item.get("details"),
                "over_under": item.get("overUnder"),
                "spread": item.get("spread"),
                "home_team_odds": {
                    "money_line": item.get("homeTeamOdds", {}).get("moneyLine"),
                    "spread_odds": item.get("homeTeamOdds", {})
                    .get("current", {})
                    .get("pointSpread", {})
                    .get("value"),
                },
                "away_team_odds": {
                    "money_line": item.get("awayTeamOdds", {}).get("moneyLine"),
                    "spread_odds": item.get("awayTeamOdds", {})
                    .get("current", {})
                    .get("pointSpread", {})
                    .get("value"),
                },
            }
            self.logger.debug(
                f"Returning extracted odds data: {json.dumps(extracted_data, indent=2)}"
            )
            return extracted_data

        # Check if this is a valid empty response or an unexpected structure
        if (
            "count" in data
            and data["count"] == 0
            and "items" in data
            and data["items"] == []
        ):
            # This is a valid empty response - no odds available for this game
            self.logger.debug("Valid empty response - no odds available for this game")
            return None

        # Unexpected structure
        self.logger.warning(
            f"Unexpected odds data structure: {json.dumps(data, indent=2)}"
        )
        return None

    def get_multiple_odds(
        self,
        sport: str,
        league: str,
        event_ids: List[str],
        update_interval_seconds: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch odds data for multiple games.

        Args:
            sport: Sport name
            league: League name
            event_ids: List of ESPN event IDs
            update_interval_seconds: Override default update interval

        Returns:
            Dictionary mapping event_id to odds data
        """
        results = {}

        for event_id in event_ids:
            try:
                odds_data = self.get_odds(
                    sport, league, event_id, update_interval_seconds
                )
                if odds_data:
                    results[event_id] = odds_data
            except Exception as e:
                self.logger.error(f"Error fetching odds for event {event_id}: {e}")
                continue

        return results

    def clear_cache(self, sport: Optional[str] = None, league: Optional[str] = None, event_id: Optional[str] = None):
        """
        Clear odds cache for specific criteria.

        Args:
            sport: Sport name (optional)
            league: League name (optional)
            event_id: Event ID (optional)
        """
        if sport and league and event_id:
            # Clear specific event
            cache_key = f"odds_espn_{sport}_{league}_{event_id}"
            self.cache_manager.clear_cache(cache_key)
            self.logger.info(f"Cleared cache for {cache_key}")
        else:
            # Clear all odds cache
            self.cache_manager.clear_cache()
            self.logger.info("Cleared all cache")
