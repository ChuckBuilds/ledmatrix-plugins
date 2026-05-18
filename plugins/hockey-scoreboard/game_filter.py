"""
Game Filter for Hockey Scoreboard Plugin

Handles game filtering, sorting, and prioritization logic for the hockey scoreboard plugin.
"""

import logging
from typing import Dict, List


class HockeyGameFilter:
    """Handles game filtering and sorting for hockey scoreboard plugin."""
    
    def __init__(self, logger: logging.Logger):
        """Initialize the game filter."""
        self.logger = logger
    
    def sort_games(self, games: List[Dict], mode: str = None) -> List[Dict]:
        """
        Sort games by priority and favorites.
        
        Args:
            games: List of game dictionaries
            mode: Display mode to determine sort order
            
        Returns:
            Sorted list of games
        """
        def sort_key(game):
            league_key = game.get('league')
            status = game.get('status', {})
            
            # Priority 1: Live games (check if league has live priority)
            is_live = status.get('state') == 'in'
            # For now, prioritize NHL live games
            if is_live and league_key == 'nhl':
                live_score = 0
            else:
                live_score = 1
            
            # Priority 2: Favorite teams
            favorite_score = 0 if self._is_favorite_game(game) else 1
            
            # Priority 3: Start time - reverse order for recent games
            start_time = game.get('start_time', '')
            # Normalize mode (handle both granular and legacy formats)
            mode_type = mode.replace('hockey_', '') if mode and mode.startswith('hockey_') else (mode or '')
            if mode_type == 'recent':
                # For recent games, we want most recent first (descending order)
                # Use negative timestamp for proper reverse sorting
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    time_score = -dt.timestamp()  # Negative for reverse order
                except Exception:
                    time_score = start_time  # Fallback to string
            else:
                # For live and upcoming, use normal order
                time_score = start_time
            
            return (live_score, favorite_score, time_score)
        
        sorted_games = sorted(games, key=sort_key)
        return sorted_games
    
    def filter_games_by_mode(self, games: List[Dict], mode: str) -> List[Dict]:
        """
        Filter games based on display mode and per-league settings.
        
        Args:
            games: List of game dictionaries
            mode: Display mode (live, recent, upcoming) or legacy (hockey_live, hockey_recent, hockey_upcoming)
            
        Returns:
            Filtered list of games
        """
        # Normalize mode name (handle both granular and legacy formats)
        mode_type = mode.replace('hockey_', '') if mode.startswith('hockey_') else mode
        
        # First, filter by game state
        state_filtered = []
        for game in games:
            league_config = game.get('league_config', {})
            status = game.get('status', {})
            state = status.get('state')
            
            # Check if this mode is enabled for this league
            display_modes = league_config.get('display_modes', {})
            # Support both new format (live, recent, upcoming) and legacy (hockey_live, etc.)
            mode_enabled = display_modes.get(mode_type, display_modes.get(mode, False))
            if not mode_enabled:
                continue
            
            # Filter by game state
            if mode_type == 'live' and state == 'in':
                state_filtered.append(game)
            elif mode_type == 'recent' and state == 'post':
                state_filtered.append(game)
            elif mode_type == 'upcoming' and state == 'pre':
                state_filtered.append(game)
        
        # Sort the state-filtered games first (use mode for sort key)
        sorted_games = self.sort_games(state_filtered, mode)
        
        # Then apply per-league limits
        filtered = []
        league_counts = {}
        
        for game in sorted_games:
            league_key = game.get('league')
            league_config = game.get('league_config', {})
            
            # Get the limit for this league and mode
            if mode_type == 'recent':
                limit = league_config.get('recent_games_to_show', 5)
            elif mode_type == 'upcoming':
                limit = league_config.get('upcoming_games_to_show', 10)
            else:  # live
                limit = league_config.get('live_games_to_show', 10)
            
            # Count games for this league
            current_count = league_counts.get(league_key, 0)
            if current_count < limit:
                filtered.append(game)
                league_counts[league_key] = current_count + 1
        
        return filtered
    
    def _is_favorite_game(self, game: Dict) -> bool:
        """Check if game involves a favorite team."""
        league_config = game.get('league_config', {})
        favorites = league_config.get('favorite_teams', [])
        
        if not favorites:
            return False
        
        home_abbrev = game.get('home_team', {}).get('abbrev')
        away_abbrev = game.get('away_team', {}).get('abbrev')
        
        return home_abbrev in favorites or away_abbrev in favorites
    
    def has_live_games(self, games: List[Dict]) -> bool:
        """Check if there are any live games available."""
        return any(game.get('status', {}).get('state') == 'in' for game in games)
    
    def has_recent_games(self, games: List[Dict]) -> bool:
        """Check if there are any recent games available."""
        return any(game.get('status', {}).get('state') == 'post' for game in games)
    
    def has_upcoming_games(self, games: List[Dict]) -> bool:
        """Check if there are any upcoming games available."""
        return any(game.get('status', {}).get('state') == 'pre' for game in games)
    
    def get_live_games(self, games: List[Dict]) -> List[Dict]:
        """Get all live games."""
        return [game for game in games if game.get('status', {}).get('state') == 'in']
    
    def get_recent_games(self, games: List[Dict]) -> List[Dict]:
        """Get all recent games."""
        return [game for game in games if game.get('status', {}).get('state') == 'post']
    
    def get_upcoming_games(self, games: List[Dict]) -> List[Dict]:
        """Get all upcoming games."""
        return [game for game in games if game.get('status', {}).get('state') == 'pre']
    
    def filter_by_favorite_teams(self, games: List[Dict], favorite_teams: List[str]) -> List[Dict]:
        """
        Filter games to only include those with favorite teams.
        
        Args:
            games: List of game dictionaries
            favorite_teams: List of favorite team abbreviations
            
        Returns:
            Filtered list of games
        """
        if not favorite_teams:
            return games
            
        filtered = []
        for game in games:
            home_abbrev = game.get('home_team', {}).get('abbrev')
            away_abbrev = game.get('away_team', {}).get('abbrev')
            
            if home_abbrev in favorite_teams or away_abbrev in favorite_teams:
                filtered.append(game)
                
        return filtered
    
    def limit_games_by_league(self, games: List[Dict], league_limits: Dict[str, int]) -> List[Dict]:
        """
        Limit games per league based on configuration.
        
        Args:
            games: List of game dictionaries
            league_limits: Dictionary mapping league keys to limits
            
        Returns:
            Limited list of games
        """
        limited = []
        league_counts = {}
        
        for game in games:
            league = game.get('league')
            current_count = league_counts.get(league, 0)
            limit = league_limits.get(league, float('inf'))
            
            if current_count < limit:
                limited.append(game)
                league_counts[league] = current_count + 1
                
        return limited
    
    def filter_favorite_teams_only(self, games: List[Dict], favorite_teams_only: bool) -> List[Dict]:
        """
        Filter games to show only favorite teams if enabled.
        
        Args:
            games: List of game dictionaries
            favorite_teams_only: If True, only show games with favorite teams
            
        Returns:
            Filtered list of games
        """
        if not favorite_teams_only:
            return games
            
        favorite_games = []
        for game in games:
            if self._is_favorite_game(game):
                favorite_games.append(game)
                
        return favorite_games
