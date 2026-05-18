"""
Simplified DynamicTeamResolver for plugin use
"""

import logging
import time
import requests
from typing import Dict, List

logger = logging.getLogger(__name__)

class DynamicTeamResolver:
    """
    Simplified resolver for dynamic team names to actual team abbreviations.
    
    This class handles special team names that represent dynamic groups
    like AP Top 25 rankings, which update automatically.
    """
    
    # Cache for rankings data
    _rankings_cache: Dict[str, List[str]] = {}
    _cache_timestamp: float = 0
    _cache_duration: int = 3600  # 1 hour cache
    
    # Supported dynamic team patterns
    # Note: Hockey rankings may not be available via ESPN API like NCAA Football
    # These patterns are included for future support and consistency
    DYNAMIC_PATTERNS = {
        # NCAA Football patterns (for reference/compatibility)
        'AP_TOP_25': {'sport': 'ncaa_fb', 'limit': 25},
        'AP_TOP_10': {'sport': 'ncaa_fb', 'limit': 10}, 
        'AP_TOP_5': {'sport': 'ncaa_fb', 'limit': 5},
        # Hockey patterns (if rankings become available via ESPN API)
        # These are placeholders and may not work until ESPN provides hockey rankings
        'NCAA_MENS_TOP_25': {'sport': 'ncaa_mens_hockey', 'limit': 25},
        'NCAA_MENS_TOP_10': {'sport': 'ncaa_mens_hockey', 'limit': 10},
        'NCAA_WOMENS_TOP_25': {'sport': 'ncaa_womens_hockey', 'limit': 25},
        'NCAA_WOMENS_TOP_10': {'sport': 'ncaa_womens_hockey', 'limit': 10},
    }
    
    def __init__(self, request_timeout: int = 30):
        """Initialize the dynamic team resolver."""
        self.request_timeout = request_timeout
        self.logger = logger
        
    def resolve_teams(self, team_list: List[str], sport: str = 'ncaa_fb') -> List[str]:
        """
        Resolve a list of team names, expanding dynamic team names.
        
        Args:
            team_list: List of team names (can include dynamic names like "AP_TOP_25")
            sport: Sport type for context (default: 'ncaa_fb')
            
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
            
            # Check cache first
            cache_key = f"{pattern_sport}_{dynamic_team}"
            if self._is_cache_valid():
                cached_teams = self._rankings_cache.get(cache_key)
                if cached_teams:
                    self.logger.debug(f"Using cached {dynamic_team} teams")
                    return cached_teams[:limit]
            
            # Fetch fresh rankings
            rankings = self._fetch_rankings(pattern_sport)
            if rankings:
                # Cache the results
                self._rankings_cache[cache_key] = rankings
                self._cache_timestamp = time.time()
                
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
            sport: Sport type (e.g., 'ncaa_fb', 'ncaa_mens_hockey', 'ncaa_womens_hockey')
            
        Returns:
            List of team abbreviations in ranking order
        """
        try:
            # Map sport to ESPN API endpoint
            sport_mapping = {
                'ncaa_fb': 'football/college-football/rankings',
                # Hockey rankings endpoints (if available via ESPN API)
                'ncaa_mens_hockey': 'hockey/mens-college-hockey/rankings',  # May not exist
                'ncaa_womens_hockey': 'hockey/womens-college-hockey/rankings',  # May not exist
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
                self.logger.debug(f"No rankings found for {sport} (API may not support hockey rankings yet)")
            return teams
            
        except requests.exceptions.RequestException as e:
            # API may not support hockey rankings yet - this is expected
            self.logger.debug(f"API request failed for {sport} rankings (may not be available): {e}")
            return []
        except Exception as e:
            self.logger.debug(f"Error fetching rankings for {sport}: {e}")
            return []
    
    def _is_cache_valid(self) -> bool:
        """Check if the rankings cache is still valid."""
        return time.time() - self._cache_timestamp < self._cache_duration
    
    def _is_potential_dynamic_team(self, team: str) -> bool:
        """Check if a team name looks like a dynamic team pattern."""
        return team.startswith('AP_') or team.startswith('TOP_')
