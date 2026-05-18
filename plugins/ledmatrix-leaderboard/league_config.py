"""
League Configuration Manager

Manages league-specific configurations and settings for the leaderboard plugin.
Handles league definitions, API endpoints, logo paths, and filtering options.
"""

import logging
from typing import Dict, Any, List, Optional


class LeagueConfig:
    """Manages league configurations and settings."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize league configuration manager.
        
        Args:
            config: Plugin configuration dictionary
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # Get enabled_sports from config
        self.enabled_sports = config.get('enabled_sports', {})
        self.global_config = config.get('global', {})
        
        # Initialize league configurations with ESPN API endpoints
        self.league_configs = self._initialize_league_configs()
        
        self.logger.info(f"Initialized league configs with {len([k for k, v in self.league_configs.items() if v['enabled']])} enabled leagues")
    
    def _initialize_league_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Initialize league configurations with ESPN API endpoints.
        
        Default values match the config schema:
        - nfl: enabled=True (default)
        - ncaa_fb: enabled=True (default)
        - ncaam_hockey: enabled=True (default)
        - All others: enabled=False (default)
        """
        # Default enabled values per config schema
        DEFAULT_ENABLED = {
            'nfl': True,
            'ncaa_fb': True,
            'ncaam_hockey': True,
        }
        
        def get_enabled_default(league_key: str) -> bool:
            """Get enabled default value for a league, matching config schema."""
            return DEFAULT_ENABLED.get(league_key, False)
        
        return {
            'nfl': {
                'sport': 'football',
                'league': 'nfl',
                'logo_dir': 'assets/sports/nfl_logos',
                'league_logo': 'assets/sports/nfl_logos/nfl.png',
                'standings_url': 'https://site.api.espn.com/apis/v2/sports/football/nfl/standings',
                'enabled': self.enabled_sports.get('nfl', {}).get('enabled', get_enabled_default('nfl')),
                'top_teams': self.enabled_sports.get('nfl', {}).get('top_teams', 10),
                'season': self.enabled_sports.get('nfl', {}).get('season'),  # Only include if explicitly set
                'level': self.enabled_sports.get('nfl', {}).get('level', 1),
                'sort': self.enabled_sports.get('nfl', {}).get('sort', 'winpercent:desc,gamesbehind:asc')
            },
            'nba': {
                'sport': 'basketball',
                'league': 'nba',
                'logo_dir': 'assets/sports/nba_logos',
                'league_logo': 'assets/sports/nba_logos/nba.png',
                'teams_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams',
                'standings_url': 'https://site.api.espn.com/apis/v2/sports/basketball/nba/standings',
                'enabled': self.enabled_sports.get('nba', {}).get('enabled', get_enabled_default('nba')),
                'top_teams': self.enabled_sports.get('nba', {}).get('top_teams', 10)
            },
            'mlb': {
                'sport': 'baseball',
                'league': 'mlb',
                'logo_dir': 'assets/sports/mlb_logos',
                'league_logo': 'assets/sports/mlb_logos/mlb.png',
                'standings_url': 'https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings',
                'enabled': self.enabled_sports.get('mlb', {}).get('enabled', get_enabled_default('mlb')),
                'top_teams': self.enabled_sports.get('mlb', {}).get('top_teams', 10),
                'season': self.enabled_sports.get('mlb', {}).get('season'),  # Only include if explicitly set
                'level': self.enabled_sports.get('mlb', {}).get('level', 1),
                'sort': self.enabled_sports.get('mlb', {}).get('sort', 'winpercent:desc,gamesbehind:asc')
            },
            'ncaa_fb': {
                'sport': 'football',
                'league': 'college-football',
                'logo_dir': 'assets/sports/ncaa_logos',
                'league_logo': 'assets/sports/ncaa_logos/ncaa_fb.png',
                'teams_url': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams',
                'rankings_url': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings',
                'enabled': self.enabled_sports.get('ncaa_fb', {}).get('enabled', get_enabled_default('ncaa_fb')),
                'top_teams': self.enabled_sports.get('ncaa_fb', {}).get('top_teams', 25),
                'show_ranking': self.enabled_sports.get('ncaa_fb', {}).get('show_ranking', True)
            },
            'nhl': {
                'sport': 'hockey',
                'league': 'nhl',
                'logo_dir': 'assets/sports/nhl_logos',
                'league_logo': 'assets/sports/nhl_logos/nhl.png',
                'standings_url': 'https://site.api.espn.com/apis/v2/sports/hockey/nhl/standings',
                'enabled': self.enabled_sports.get('nhl', {}).get('enabled', get_enabled_default('nhl')),
                'top_teams': self.enabled_sports.get('nhl', {}).get('top_teams', 10),
                'season': self.enabled_sports.get('nhl', {}).get('season'),  # Only include if explicitly set
                'level': self.enabled_sports.get('nhl', {}).get('level', 1),
                'sort': self.enabled_sports.get('nhl', {}).get('sort', 'winpercent:desc,gamesbehind:asc')
            },
            'ncaam_basketball': {
                'sport': 'basketball',
                'league': 'mens-college-basketball',
                'logo_dir': 'assets/sports/ncaa_logos',
                'league_logo': 'assets/sports/ncaa_logos/ncaam.png',
                'teams_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams',
                'rankings_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings',
                'enabled': self.enabled_sports.get('ncaam_basketball', {}).get('enabled', get_enabled_default('ncaam_basketball')),
                'top_teams': self.enabled_sports.get('ncaam_basketball', {}).get('top_teams', 25),
                'show_ranking': self.enabled_sports.get('ncaam_basketball', {}).get('show_ranking', True)
            },
            'ncaaw_basketball': {
                'sport': 'basketball',
                'league': 'womens-college-basketball',
                'logo_dir': 'assets/sports/ncaa_womens_logos',
                'league_logo': 'assets/sports/ncaa_womens_logos/ncaaw.png',
                'teams_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/teams',
                'rankings_url': 'https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/rankings',
                'enabled': self.enabled_sports.get('ncaaw_basketball', {}).get('enabled', get_enabled_default('ncaaw_basketball')),
                'top_teams': self.enabled_sports.get('ncaaw_basketball', {}).get('top_teams', 25),
                'show_ranking': self.enabled_sports.get('ncaaw_basketball', {}).get('show_ranking', True)
            },
            'ncaa_baseball': {
                'sport': 'baseball',
                'league': 'college-baseball',
                'logo_dir': 'assets/sports/ncaa_logos',
                'league_logo': 'assets/sports/ncaa_logos/ncaa_baseball.png',
                'standings_url': 'https://site.api.espn.com/apis/v2/sports/baseball/college-baseball/standings',
                'scoreboard_url': 'https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard',
                'enabled': self.enabled_sports.get('ncaa_baseball', {}).get('enabled', get_enabled_default('ncaa_baseball')),
                'top_teams': self.enabled_sports.get('ncaa_baseball', {}).get('top_teams', 25),
                'season': self.enabled_sports.get('ncaa_baseball', {}).get('season'),  # Only include if explicitly set
                'level': self.enabled_sports.get('ncaa_baseball', {}).get('level', 1),
                'sort': self.enabled_sports.get('ncaa_baseball', {}).get('sort', 'winpercent:desc,gamesbehind:asc')
            },
            'ncaam_hockey': {
                'sport': 'hockey',
                'league': 'mens-college-hockey',
                'logo_dir': 'assets/sports/ncaa_logos',
                'league_logo': 'assets/sports/ncaa_logos/ncaah.png',
                'rankings_url': 'https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/rankings',
                'enabled': self.enabled_sports.get('ncaam_hockey', {}).get('enabled', get_enabled_default('ncaam_hockey')),
                'top_teams': self.enabled_sports.get('ncaam_hockey', {}).get('top_teams', 25)
            },
        }
    
    def get_enabled_leagues(self) -> List[str]:
        """Get list of enabled league keys."""
        return [k for k, v in self.league_configs.items() if v.get('enabled', False)]
    
    def get_league_config(self, league_key: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific league."""
        return self.league_configs.get(league_key)
    
    def is_league_enabled(self, league_key: str) -> bool:
        """Check if a league is enabled."""
        league_config = self.league_configs.get(league_key)
        return league_config is not None and league_config.get('enabled', False)
    
    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """Get all league configurations."""
        return self.league_configs.copy()

