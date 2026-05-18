"""
Simplified DynamicTeamResolver for plugin use
"""

import logging
import time
import requests
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

class DynamicTeamResolver:
    """
    Simplified resolver for dynamic team names to actual team abbreviations.

    This class handles special team names that represent dynamic groups
    like AP Top 25 rankings, which update automatically.
    """

    # Cache for rankings data. Each entry is keyed by (sport, token) and
    # carries its own fetched-at timestamp so different tokens age
    # independently. Historically this was a single shared timestamp, which
    # meant fetching one token could extend the apparent freshness of
    # unrelated ones.
    _rankings_cache: Dict[str, Tuple[List[str], float]] = {}
    _cache_duration: int = 3600  # 1 hour cache
    
    # Supported dynamic team patterns.
    #
    # NCAA men's lacrosse is ranked via the Inside Lacrosse Division I Men's
    # Lacrosse Poll (20 teams). NCAA women's lacrosse is ranked via the
    # Inside Lacrosse/IWLCA Coaches Top 25 Poll. Both are exposed by ESPN at
    #   /sports/lacrosse/{mens,womens}-college-lacrosse/rankings
    DYNAMIC_PATTERNS = {
        # NCAA Men's Lacrosse (Inside Lacrosse Poll — top 20)
        'NCAA_MENS_TOP_20': {'sport': 'ncaa_mens_lacrosse', 'limit': 20},
        'NCAA_MENS_TOP_10': {'sport': 'ncaa_mens_lacrosse', 'limit': 10},
        'NCAA_MENS_TOP_5':  {'sport': 'ncaa_mens_lacrosse', 'limit': 5},
        # NCAA Women's Lacrosse (Inside Lacrosse/IWLCA Top 25 Poll)
        'NCAA_WOMENS_TOP_25': {'sport': 'ncaa_womens_lacrosse', 'limit': 25},
        'NCAA_WOMENS_TOP_10': {'sport': 'ncaa_womens_lacrosse', 'limit': 10},
        'NCAA_WOMENS_TOP_5':  {'sport': 'ncaa_womens_lacrosse', 'limit': 5},
    }
    
    def __init__(self, request_timeout: int = 30):
        """Initialize the dynamic team resolver."""
        self.request_timeout = request_timeout
        self.logger = logger
        
    def resolve_teams(self, team_list: List[str], sport: str = 'ncaam_lacrosse') -> List[str]:
        """
        Resolve a list of team names, expanding dynamic team names.

        Args:
            team_list: List of team names (can include dynamic names like
                "NCAA_MENS_TOP_20" or "NCAA_WOMENS_TOP_25")
            sport: Sport type for context (default: 'ncaam_lacrosse'). The pattern
                itself carries the endpoint key, so this argument is informational.

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
            
            # Check cache first (per-token TTL)
            cache_key = f"{pattern_sport}_{dynamic_team}"
            entry = self._rankings_cache.get(cache_key)
            if entry is not None:
                cached_teams, cached_at = entry
                if cached_teams and (time.time() - cached_at) < self._cache_duration:
                    self.logger.debug(f"Using cached {dynamic_team} teams")
                    return cached_teams[:limit]

            # Fetch fresh rankings
            rankings = self._fetch_rankings(pattern_sport)
            if rankings:
                # Cache the results with this token's own timestamp
                self._rankings_cache[cache_key] = (rankings, time.time())

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
            sport: Sport type (e.g., 'ncaa_fb', 'ncaa_mens_lacrosse', 'ncaa_womens_lacrosse')
            
        Returns:
            List of team abbreviations in ranking order
        """
        try:
            # Map sport to ESPN API endpoint
            sport_mapping = {
                'ncaa_mens_lacrosse': 'lacrosse/mens-college-lacrosse/rankings',
                'ncaa_womens_lacrosse': 'lacrosse/womens-college-lacrosse/rankings',
            }
            
            endpoint = sport_mapping.get(sport)
            if not endpoint:
                self.logger.warning(f"Unsupported sport for rankings: {sport} - rankings may not be available")
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
            elif 'teams' in data:
                # Alternative format - try to extract from teams array if rankings structure differs
                for team_item in data.get('teams', []):
                    abbr = team_item.get('abbreviation', '')
                    if abbr:
                        teams.append(abbr)
            
            if teams:
                self.logger.debug(f"Fetched {len(teams)} ranked teams for {sport}")
            else:
                self.logger.debug(f"No rankings found for {sport} (API may not support lacrosse rankings yet)")
            return teams
            
        except requests.exceptions.RequestException as e:
            # API may not support lacrosse rankings yet - this is expected
            self.logger.debug(f"API request failed for {sport} rankings (may not be available): {e}")
            return []
        except Exception as e:
            self.logger.debug(f"Error fetching rankings for {sport}: {e}")
            return []

    def _is_potential_dynamic_team(self, team: str) -> bool:
        """Check if a team name looks like a dynamic team pattern."""
        return (
            team.startswith('AP_')
            or team.startswith('TOP_')
            or team.startswith('NCAA_MENS_')
            or team.startswith('NCAA_WOMENS_')
        )
