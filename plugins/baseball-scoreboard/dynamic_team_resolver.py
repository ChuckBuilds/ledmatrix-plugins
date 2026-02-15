"""
Simplified DynamicTeamResolver for plugin use
"""

import logging
import time
import requests
from typing import Dict, List, Set, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class DynamicTeamResolver:
    """
    Simplified resolver for dynamic team names to actual team abbreviations.

    This class handles special team names that represent dynamic groups
    like AP Top 25 rankings, which update automatically.
    """

    # Supported dynamic team patterns
    DYNAMIC_PATTERNS = {
        'AP_TOP_25': {'sport': 'college-baseball', 'limit': 25},
        'AP_TOP_10': {'sport': 'college-baseball', 'limit': 10},
        'AP_TOP_5': {'sport': 'college-baseball', 'limit': 5},
    }

    # Cache duration in seconds (1 hour)
    CACHE_DURATION = 3600

    def __init__(self, cache_manager=None, request_timeout: int = 30):
        """Initialize the dynamic team resolver.

        Args:
            cache_manager: Optional cache manager instance for storing rankings cache
            request_timeout: Timeout for API requests in seconds
        """
        self.cache_manager = cache_manager
        self.request_timeout = request_timeout
        self.logger = logger

    def resolve_teams(self, team_list: List[str], sport: str = 'college-baseball') -> List[str]:
        """
        Resolve a list of team names, expanding dynamic team names.

        Args:
            team_list: List of team names (can include dynamic names like "AP_TOP_25")
            sport: Sport type for context (default: 'college-baseball')

        Returns:
            List of resolved team abbreviations
        """
        if not team_list:
            return []

        resolved_teams = []

        for team in team_list:
            if team in self.DYNAMIC_PATTERNS:
                # Resolve dynamic team
                dynamic_teams = self._resolve_dynamic_team(team, sport)
                resolved_teams.extend(dynamic_teams)
                self.logger.info(f"Resolved {team} to {len(dynamic_teams)} teams: {dynamic_teams[:5]}{'...' if len(dynamic_teams) > 5 else ''}")
            elif self._is_potential_dynamic_team(team):
                # Unknown dynamic team, skip it
                self.logger.warning(f"Unknown dynamic team '{team}' - skipping")
            else:
                # Regular team name, add as-is
                resolved_teams.append(team)

        # Remove duplicates while preserving order
        seen = set()
        unique_teams = []
        for team in resolved_teams:
            if team not in seen:
                seen.add(team)
                unique_teams.append(team)

        return unique_teams

    def _resolve_dynamic_team(self, dynamic_team: str, sport: str) -> List[str]:
        """
        Resolve a dynamic team name to actual team abbreviations.

        Args:
            dynamic_team: Dynamic team name (e.g., "AP_TOP_25")
            sport: Sport type for context

        Returns:
            List of team abbreviations
        """
        try:
            pattern_config = self.DYNAMIC_PATTERNS[dynamic_team]
            pattern_sport = pattern_config['sport']
            limit = pattern_config['limit']

            # Check cache first (using cache_manager if available)
            cache_key = f"dynamic_teams_{pattern_sport}_{dynamic_team}"
            if self.cache_manager:
                cached_teams = self.cache_manager.get(cache_key)
                if cached_teams:
                    self.logger.debug(f"Using cached {dynamic_team} teams from cache_manager")
                    return cached_teams[:limit]

            # Fetch fresh rankings
            rankings = self._fetch_rankings(pattern_sport)
            if rankings:
                # Cache the results using cache_manager if available
                if self.cache_manager:
                    self.cache_manager.set(cache_key, rankings, ttl=self.CACHE_DURATION)

                self.logger.info(f"Fetched {len(rankings)} teams for {dynamic_team}")
                return rankings[:limit]
            else:
                self.logger.warning(f"Failed to fetch rankings for {dynamic_team}")
                return []

        except Exception as e:
            self.logger.error(f"Error resolving dynamic team {dynamic_team}: {e}")
            return []

    def _fetch_rankings(self, sport: str) -> List[str]:
        """
        Fetch current rankings from ESPN API.

        Args:
            sport: Sport type (e.g., 'college-baseball')

        Returns:
            List of team abbreviations in ranking order
        """
        try:
            # Map sport to ESPN API endpoint
            sport_mapping = {
                'college-baseball': 'baseball/college-baseball/rankings',
                'ncaa_fb': 'football/college-football/rankings',
            }

            endpoint = sport_mapping.get(sport)
            if not endpoint:
                self.logger.error(f"Unsupported sport for rankings: {sport}")
                return []

            url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint}"

            headers = {
                'User-Agent': 'LEDMatrix/1.0',
                'Accept': 'application/json'
            }

            response = requests.get(url, headers=headers, timeout=self.request_timeout)
            response.raise_for_status()

            data = response.json()

            # Extract team abbreviations from rankings
            teams = []
            if 'rankings' in data and data['rankings']:
                ranking = data['rankings'][0]  # Use first ranking (usually AP)
                if 'ranks' in ranking:
                    for rank_item in ranking['ranks']:
                        team_info = rank_item.get('team', {})
                        abbr = team_info.get('abbreviation', '')
                        if abbr:
                            teams.append(abbr)

            self.logger.debug(f"Fetched {len(teams)} ranked teams for {sport}")
            return teams

        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed for {sport} rankings: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error fetching rankings for {sport}: {e}")
            return []

    def _is_potential_dynamic_team(self, team: str) -> bool:
        """Check if a team name looks like a dynamic team pattern."""
        return team.startswith('AP_') or team.startswith('TOP_')
