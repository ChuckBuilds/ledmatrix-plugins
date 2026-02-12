"""
Data Fetcher for Leaderboard Plugin

Handles all ESPN API data fetching for standings and rankings.
Includes caching, error handling, and data processing.
"""

import time
import logging
import requests
from typing import Dict, Any, List, Optional

# Try to import API counter from web interface
try:
    from web_interface_v2 import increment_api_counter
except ImportError:
    # Fallback if web interface is not available
    def increment_api_counter(kind: str, count: int = 1):
        pass


class DataFetcher:
    """Handles fetching standings and rankings data from ESPN API."""
    
    def __init__(self, cache_manager, logger: Optional[logging.Logger] = None, 
                 request_timeout: int = 30):
        """
        Initialize data fetcher.
        
        Args:
            cache_manager: Cache manager instance
            logger: Optional logger instance
            request_timeout: Request timeout in seconds
        """
        self.cache_manager = cache_manager
        self.logger = logger or logging.getLogger(__name__)
        self.request_timeout = request_timeout
    
    def fetch_standings(self, league_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Fetch standings for a specific league from ESPN API with caching.

        Args:
            league_config: League configuration dictionary

        Returns:
            List of team standings dictionaries
        """
        league_key = league_config['league']

        # Each fetch method handles its own caching with league-specific keys
        if league_key == 'college-football':
            standings = self._fetch_ncaa_fb_rankings(league_config)
        elif league_key == 'mens-college-hockey':
            standings = self._fetch_ncaam_hockey_rankings(league_config)
        elif league_key in ['mens-college-basketball', 'womens-college-basketball']:
            standings = self._fetch_ncaa_basketball_rankings(league_config)
        elif league_key in ['nfl', 'mlb', 'nhl', 'college-baseball']:
            standings = self._fetch_standings_data(league_config)
        else:
            standings = self._fetch_teams_data(league_config)

        # Apply top_teams limit centrally so config changes take effect immediately
        top_teams = league_config.get('top_teams', 10)
        return standings[:top_teams]
    
    def _fetch_ncaa_fb_rankings(self, league_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch NCAA Football rankings from ESPN API using the rankings endpoint."""
        league_key = league_config['league']
        cache_key = f"leaderboard_{league_key}_rankings"
        
        # Try to get cached data first
        cached_data = self.cache_manager.get_cached_data_with_strategy(cache_key, 'leaderboard')
        if cached_data:
            self.logger.info(f"Using cached rankings data for {league_key}")
            return cached_data.get('standings', [])
        
        try:
            self.logger.info(f"Fetching fresh rankings data for {league_key}")
            rankings_url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
            
            response = requests.get(rankings_url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            increment_api_counter('sports', 1)
            
            rankings_data = data.get('rankings', [])
            if not rankings_data:
                self.logger.warning("No rankings data found")
                return []
            
            # Prefer AP Top 25, but fall back to first ranking if not found
            selected_ranking = None
            ranking_name = 'Unknown'
            
            # Look for AP Top 25 specifically
            for ranking in rankings_data:
                name = ranking.get('name', '').lower()
                ranking_type = ranking.get('type', '').lower()
                # Check for AP Top 25 by name or type
                if ('ap' in name and 'top' in name) or ranking_type == 'ap':
                    selected_ranking = ranking
                    ranking_name = ranking.get('name', 'AP Top 25')
                    self.logger.info(f"Found AP Top 25 ranking: {ranking_name}")
                    break
            
            # Fall back to first ranking if AP Top 25 not found
            if not selected_ranking:
                selected_ranking = rankings_data[0]
                ranking_name = selected_ranking.get('name', 'Unknown')
                self.logger.warning(f"AP Top 25 not found, using first available ranking: {ranking_name}")
            
            teams = selected_ranking.get('ranks', [])
            
            self.logger.info(f"Using ranking: {ranking_name}, found {len(teams)} teams")
            
            standings = []
            for team_data in teams:
                team_info = team_data.get('team', {})
                team_name = team_info.get('name', 'Unknown')
                team_id = team_info.get('id')
                team_abbr = team_info.get('abbreviation', 'Unknown')
                current_rank = team_data.get('current', 0)
                record_summary = team_data.get('recordSummary', '0-0')
                
                # Parse record
                wins, losses, ties, win_percentage = self._parse_record(record_summary)
                
                standings.append({
                    'name': team_name,
                    'id': team_id,
                    'abbreviation': team_abbr,
                    'rank': current_rank,
                    'wins': wins,
                    'losses': losses,
                    'ties': ties,
                    'win_percentage': win_percentage,
                    'record_summary': record_summary,
                    'ranking_name': ranking_name
                })
            
            # Cache the full results (top_teams slicing is applied in fetch_standings)
            cache_data = {
                'standings': standings,
                'timestamp': time.time(),
                'league': league_key,
                'ranking_name': ranking_name
            }
            self.cache_manager.save_cache(cache_key, cache_data)

            self.logger.info(f"Fetched and cached {len(standings)} teams for {league_key}")
            return standings

        except Exception as e:
            self.logger.error(f"Error fetching rankings for {league_key}: {e}")
            return []

    def _fetch_ncaam_hockey_rankings(self, league_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch NCAA Men's Hockey rankings from ESPN API."""
        league_key = league_config['league']
        cache_key = f"leaderboard_{league_key}_rankings"
        
        cached_data = self.cache_manager.get_cached_data_with_strategy(cache_key, 'leaderboard')
        if cached_data:
            self.logger.info(f"Using cached rankings data for {league_key}")
            return cached_data.get('standings', [])
        
        try:
            self.logger.info(f"Fetching fresh rankings data for {league_key}")
            rankings_url = "https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/rankings"
            
            response = requests.get(rankings_url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            increment_api_counter('sports', 1)
            
            rankings_data = data.get('rankings', [])
            if not rankings_data:
                self.logger.warning("No rankings data found")
                return []
            
            # Prefer first ranking (usually the main poll), but could be enhanced to prefer specific polls
            selected_ranking = rankings_data[0]
            ranking_name = selected_ranking.get('name', 'Unknown')
            teams = selected_ranking.get('ranks', [])
            
            self.logger.info(f"Using ranking: {ranking_name}, found {len(teams)} teams")
            
            standings = []
            for team_data in teams:
                team_info = team_data.get('team', {})
                team_name = team_info.get('name', 'Unknown')
                team_id = team_info.get('id')
                team_abbr = team_info.get('abbreviation', 'Unknown')
                current_rank = team_data.get('current', 0)
                record_summary = team_data.get('recordSummary', '0-0')
                
                wins, losses, ties, win_percentage = self._parse_record(record_summary)
                
                standings.append({
                    'name': team_name,
                    'id': team_id,
                    'abbreviation': team_abbr,
                    'rank': current_rank,
                    'wins': wins,
                    'losses': losses,
                    'ties': ties,
                    'win_percentage': win_percentage,
                    'record_summary': record_summary,
                    'ranking_name': ranking_name
                })
            
            # Cache the full results (top_teams slicing is applied in fetch_standings)
            cache_data = {
                'standings': standings,
                'timestamp': time.time(),
                'league': league_key,
                'ranking_name': ranking_name
            }
            self.cache_manager.save_cache(cache_key, cache_data)

            self.logger.info(f"Fetched and cached {len(standings)} teams for {league_key}")
            return standings

        except Exception as e:
            self.logger.error(f"Error fetching rankings for {league_key}: {e}")
            return []

    def _fetch_ncaa_basketball_rankings(self, league_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch NCAA Basketball rankings from ESPN API using the rankings endpoint."""
        league_key = league_config['league']
        cache_key = f"leaderboard_{league_key}_rankings"

        cached_data = self.cache_manager.get_cached_data_with_strategy(cache_key, 'leaderboard')
        if cached_data:
            self.logger.info(f"Using cached rankings data for {league_key}")
            return cached_data.get('standings', [])

        try:
            self.logger.info(f"Fetching fresh rankings data for {league_key}")
            sport = league_config['sport']
            rankings_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league_key}/rankings"

            response = requests.get(rankings_url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()

            increment_api_counter('sports', 1)

            rankings_data = data.get('rankings', [])
            if not rankings_data:
                self.logger.warning(f"No rankings data found for {league_key}")
                return []

            # Prefer AP Top 25, but fall back to first ranking if not found
            selected_ranking = None
            ranking_name = 'Unknown'

            # Look for AP Top 25 specifically
            for ranking in rankings_data:
                name = ranking.get('name', '').lower()
                ranking_type = ranking.get('type', '').lower()
                if ('ap' in name and 'top' in name) or ranking_type == 'ap':
                    selected_ranking = ranking
                    ranking_name = ranking.get('name', 'AP Top 25')
                    self.logger.info(f"Found AP Top 25 ranking: {ranking_name}")
                    break

            # Fall back to first ranking if AP Top 25 not found
            if not selected_ranking:
                selected_ranking = rankings_data[0]
                ranking_name = selected_ranking.get('name', 'Unknown')
                self.logger.warning(f"AP Top 25 not found, using first available ranking: {ranking_name}")

            teams = selected_ranking.get('ranks', [])

            self.logger.info(f"Using ranking: {ranking_name}, found {len(teams)} teams")

            standings = []
            for team_data in teams:
                team_info = team_data.get('team', {})
                team_name = team_info.get('name', 'Unknown')
                team_id = team_info.get('id')
                team_abbr = team_info.get('abbreviation', 'Unknown')
                current_rank = team_data.get('current', 0)
                record_summary = team_data.get('recordSummary', '0-0')

                wins, losses, ties, win_percentage = self._parse_record(record_summary)

                standings.append({
                    'name': team_name,
                    'id': team_id,
                    'abbreviation': team_abbr,
                    'rank': current_rank,
                    'wins': wins,
                    'losses': losses,
                    'ties': ties,
                    'win_percentage': win_percentage,
                    'record_summary': record_summary,
                    'ranking_name': ranking_name
                })

            # Cache the full results (top_teams slicing is applied in fetch_standings)
            cache_data = {
                'standings': standings,
                'timestamp': time.time(),
                'league': league_key,
                'ranking_name': ranking_name
            }
            self.cache_manager.save_cache(cache_key, cache_data)

            self.logger.info(f"Fetched and cached {len(standings)} teams for {league_key}")
            return standings

        except Exception as e:
            self.logger.error(f"Error fetching rankings for {league_key}: {e}")
            return []

    def _fetch_standings_data(self, league_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch standings data from ESPN API using the standings endpoint."""
        league_key = league_config['league']
        cache_key = f"leaderboard_{league_key}_standings"
        
        cached_data = self.cache_manager.get_cached_data_with_strategy(cache_key, 'leaderboard')
        if cached_data:
            cached_standings = cached_data.get('standings', [])
            self.logger.info(f"Using cached standings data for {league_key}: {len(cached_standings)} teams found")
            if len(cached_standings) == 0:
                self.logger.warning(f"Cached data for {league_key} has 0 teams - this may indicate a caching issue")
            return cached_standings
        
        try:
            self.logger.info(f"Fetching fresh standings data for {league_key}")
            
            standings_url = league_config['standings_url']
            params = {
                'level': league_config.get('level', 1),
                'sort': league_config.get('sort', 'winpercent:desc,gamesbehind:asc')
            }
            
            # Only include season if explicitly provided - otherwise ESPN defaults to current season
            if 'season' in league_config and league_config.get('season'):
                params['season'] = league_config['season']
            
            response = requests.get(standings_url, params=params, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            increment_api_counter('sports', 1)
            
            standings = []
            combined_from_multiple_sources = False
            
            # Parse standings structure
            if 'standings' in data and 'entries' in data['standings']:
                # Direct standings - API already returns these sorted by the 'sort' parameter
                entries = data['standings']['entries']
                self.logger.info(f"Found {len(entries)} entries in direct standings for {league_key}")
                for entry in entries:
                    standing = self._extract_team_standing(entry, league_key)
                    if standing:
                        standings.append(standing)
                self.logger.info(f"Extracted {len(standings)} standings from {len(entries)} entries for {league_key}")
                # API already sorted these, so we trust the order
            elif 'children' in data:
                # Children structure (divisions/conferences) - need to combine and re-sort
                children = data.get('children', [])
                self.logger.info(f"Found {len(children)} children in standings data for {league_key}")
                total_entries = 0
                for child in children:
                    entries = child.get('standings', {}).get('entries', [])
                    total_entries += len(entries)
                    for entry in entries:
                        standing = self._extract_team_standing(entry, league_key)
                        if standing:
                            standings.append(standing)
                self.logger.info(f"Extracted {len(standings)} standings from {total_entries} total entries across {len(children)} children for {league_key}")
                # When combining from multiple divisions/conferences, we need to re-sort
                combined_from_multiple_sources = len(children) > 1
            else:
                self.logger.warning(f"No standings data found for {league_key} - response keys: {list(data.keys())}")
                # Log a sample of the response structure for debugging
                self.logger.debug(f"Response structure sample: {str(data)[:500]}")
                return []
            
            if len(standings) == 0:
                self.logger.error(f"0 teams found in standings data for {league_key} after extraction")
                self.logger.error(f"This indicates a problem with the API response structure or extraction logic")
                return []
            
            # ESPN API already returns data sorted by the 'sort' parameter (winpercent:desc,gamesbehind:asc)
            # For direct standings, trust the API order. Only re-sort when combining from multiple divisions/conferences
            if combined_from_multiple_sources:
                self.logger.debug(f"Re-sorting {len(standings)} teams from multiple divisions/conferences")
                standings.sort(key=lambda x: x['win_percentage'], reverse=True)
            else:
                self.logger.debug(f"Trusting API sort order for {len(standings)} teams")
            
            # Cache the full results (top_teams slicing is applied in fetch_standings)
            cache_data = {
                'standings': standings,
                'timestamp': time.time(),
                'league': league_key,
                'level': params['level']
            }
            # Only include season in cache if it was explicitly provided
            if 'season' in params:
                cache_data['season'] = params['season']
            self.cache_manager.save_cache(cache_key, cache_data)

            self.logger.info(f"Fetched and cached {len(standings)} teams for {league_key}")
            return standings
            
        except Exception as e:
            self.logger.error(f"Error fetching standings for {league_key}: {e}")
            return []
    
    def _fetch_teams_data(self, league_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch team data using teams endpoint (for NBA, etc.)."""
        league_key = league_config['league']
        cache_key = f"leaderboard_{league_key}"
        
        cached_data = self.cache_manager.get_cached_data_with_strategy(cache_key, 'leaderboard')
        if cached_data:
            self.logger.info(f"Using cached leaderboard data for {league_key}")
            return cached_data.get('standings', [])
        
        try:
            self.logger.info(f"Fetching fresh leaderboard data for {league_key}")
            teams_url = league_config['teams_url']
            response = requests.get(teams_url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            increment_api_counter('sports', 1)
            
            standings = []
            sports = data.get('sports', [])
            
            if not sports or not sports[0].get('leagues', []):
                self.logger.warning(f"No teams data found for {league_config['league']}")
                return []
            
            teams = sports[0]['leagues'][0].get('teams', [])
            
            for team_data in teams:
                team = team_data.get('team', {})
                team_abbr = team.get('abbreviation')
                team_name = team.get('name', 'Unknown')
                
                if not team_abbr:
                    continue
                
                # Fetch individual team record
                team_record = self._fetch_team_record(team_abbr, league_config)
                
                if team_record:
                    standings.append({
                        'name': team_name,
                        'abbreviation': team_abbr,
                        'id': team.get('id'),
                        'wins': team_record.get('wins', 0),
                        'losses': team_record.get('losses', 0),
                        'ties': team_record.get('ties', 0),
                        'win_percentage': team_record.get('win_percentage', 0)
                    })
            
            standings.sort(key=lambda x: x['win_percentage'], reverse=True)

            # Cache the full results (top_teams slicing is applied in fetch_standings)
            cache_data = {
                'standings': standings,
                'timestamp': time.time(),
                'league': league_key
            }
            self.cache_manager.save_cache(cache_key, cache_data)

            self.logger.info(f"Fetched and cached {len(standings)} teams for {league_config['league']}")
            return standings
            
        except Exception as e:
            self.logger.error(f"Error fetching standings for {league_config['league']}: {e}")
            return []
    
    def _extract_team_standing(self, entry: Dict, league_key: str) -> Optional[Dict[str, Any]]:
        """Extract team standing from API entry."""
        try:
            team_data = entry.get('team', {})
            stats = entry.get('stats', [])
            
            if not team_data:
                self.logger.warning(f"Entry missing 'team' data: {entry.keys()}")
                return None
            
            team_name = team_data.get('displayName', 'Unknown')
            team_abbr = team_data.get('abbreviation', 'Unknown')
            team_id = team_data.get('id')
            
            if not team_abbr or team_abbr == 'Unknown':
                self.logger.warning(f"Team missing abbreviation: {team_data}")
                # Still return the standing, but log the issue
            
            wins = 0
            losses = 0
            ties = 0
            win_percentage = 0.0
            games_played = 0
            
            for stat in stats:
                stat_type = stat.get('type', '')
                stat_value = stat.get('value', 0)
                
                if stat_type == 'wins':
                    wins = int(stat_value)
                elif stat_type == 'losses':
                    losses = int(stat_value)
                elif stat_type == 'ties':
                    ties = int(stat_value)
                elif stat_type == 'winpercent':
                    win_percentage = float(stat_value)
                elif stat_type == 'overtimelosses' and league_key == 'nhl':
                    ties = int(stat_value)
                elif stat_type == 'gamesplayed' and league_key == 'nhl':
                    games_played = float(stat_value)
            
            if league_key == 'nhl' and win_percentage == 0.0 and games_played > 0:
                win_percentage = wins / games_played
            
            if ties > 0:
                record_summary = f"{wins}-{losses}-{ties}"
            else:
                record_summary = f"{wins}-{losses}"
            
            return {
                'name': team_name,
                'id': team_id,
                'abbreviation': team_abbr,
                'wins': wins,
                'losses': losses,
                'ties': ties,
                'win_percentage': win_percentage,
                'record_summary': record_summary
            }
        except Exception as e:
            self.logger.error(f"Error extracting team standing: {e}, entry keys: {list(entry.keys()) if isinstance(entry, dict) else 'not a dict'}")
            return None
    
    def _fetch_team_record(self, team_abbr: str, league_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetch individual team record from ESPN API with caching."""
        league = league_config['league']
        cache_key = f"team_record_{league}_{team_abbr}"
        
        cached_data = self.cache_manager.get_cached_data_with_strategy(cache_key, 'leaderboard')
        if cached_data:
            return cached_data.get('record')
        
        try:
            sport = league_config['sport']
            
            if league == 'college-football':
                url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_abbr}"
            else:
                url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_abbr}"
            
            response = requests.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            increment_api_counter('sports', 1)
            
            team_data = data.get('team', {})
            stats = team_data.get('stats', [])
            
            wins = 0
            losses = 0
            ties = 0
            
            for stat in stats:
                if stat.get('name') == 'wins':
                    wins = stat.get('value', 0)
                elif stat.get('name') == 'losses':
                    losses = stat.get('value', 0)
                elif stat.get('name') == 'ties':
                    ties = stat.get('value', 0)
            
            total_games = wins + losses + ties
            win_percentage = wins / total_games if total_games > 0 else 0
            
            record = {
                'wins': wins,
                'losses': losses,
                'ties': ties,
                'win_percentage': win_percentage
            }
            
            cache_data = {
                'record': record,
                'timestamp': time.time(),
                'team': team_abbr,
                'league': league
            }
            self.cache_manager.save_cache(cache_key, cache_data)
            
            return record
            
        except Exception as e:
            self.logger.error(f"Error fetching record for {team_abbr} in league {league}: {e}")
            return None
    
    def _parse_record(self, record_summary: str) -> tuple:
        """Parse record string (e.g., "12-1", "8-4", "10-2-1") into components."""
        wins = 0
        losses = 0
        ties = 0
        win_percentage = 0
        
        try:
            parts = record_summary.split('-')
            if len(parts) >= 2:
                wins = int(parts[0])
                losses = int(parts[1])
                if len(parts) == 3:
                    ties = int(parts[2])
                
                total_games = wins + losses + ties
                win_percentage = wins / total_games if total_games > 0 else 0
        except (ValueError, IndexError):
            self.logger.warning(f"Could not parse record: {record_summary}")
        
        return wins, losses, ties, win_percentage

