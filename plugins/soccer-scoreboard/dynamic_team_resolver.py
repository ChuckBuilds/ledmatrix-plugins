"""
Simplified DynamicTeamResolver for soccer plugin use
"""

import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

class DynamicTeamResolver:
    """
    Simplified resolver for dynamic team names to actual team abbreviations.
    
    This class handles special team names that represent dynamic groups
    for soccer leagues.
    """
    
    # Cache for rankings data
    _rankings_cache: Dict[str, List[str]] = {}
    _cache_timestamp: float = 0
    _cache_duration: int = 3600  # 1 hour cache
    
    def __init__(self, request_timeout: int = 30):
        """Initialize the dynamic team resolver."""
        self.request_timeout = request_timeout
        self.logger = logger
        
    def resolve_teams(self, team_list: List[str], sport: str = 'soccer') -> List[str]:
        """
        Resolve a list of team names, expanding dynamic team names.
        
        Args:
            team_list: List of team names
            sport: Sport type for context (default: 'soccer')
            
        Returns:
            List of resolved team abbreviations
        """
        if not team_list:
            return []
            
        resolved_teams = []
        
        for team in team_list:
            # For soccer, we just pass through team names as-is
            # No dynamic patterns like AP_TOP_25 for soccer
            resolved_teams.append(team)
                
        # Remove duplicates while preserving order
        seen = set()
        unique_teams = []
        for team in resolved_teams:
            if team not in seen:
                seen.add(team)
                unique_teams.append(team)
                
        return unique_teams
    
    def _is_cache_valid(self) -> bool:
        """Check if the rankings cache is still valid."""
        return time.time() - self._cache_timestamp < self._cache_duration

