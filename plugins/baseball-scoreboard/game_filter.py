"""
Baseball Game Filter

Handles game filtering, sorting, and list management for live, recent, and upcoming modes.
Replicates logic from SportsLive, SportsRecent, and SportsUpcoming classes.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


class BaseballGameFilter:
    """Manages game filtering, sorting, and list management."""

    def __init__(self, logger: logging.Logger):
        """
        Initialize the game filter.

        Args:
            logger: Logger instance
        """
        self.logger = logger

    def is_favorite_game(self, game: Dict, favorite_teams: List[str]) -> bool:
        """
        Check if game involves a favorite team.

        Args:
            game: Game dictionary
            favorite_teams: List of favorite team abbreviations

        Returns:
            True if game involves a favorite team, False otherwise
        """
        if not favorite_teams:
            return False

        home_abbr = game.get('home_abbr', '')
        away_abbr = game.get('away_abbr', '')

        # Handle MiLB format (uses 'home_team' and 'away_team' instead of 'home_abbr'/'away_abbr')
        if not home_abbr:
            home_abbr = game.get('home_team', '')
        if not away_abbr:
            away_abbr = game.get('away_team', '')

        return home_abbr in favorite_teams or away_abbr in favorite_teams

    def _get_team_abbr(self, game: Dict, position: str) -> str:
        """Get team abbreviation, supporting both MLB and MiLB formats."""
        abbr = game.get(f'{position}_abbr', '')
        if not abbr:
            abbr = game.get(f'{position}_team', '')
        return abbr

    def _select_recent_games_for_display(
        self, processed_games: List[Dict], favorite_teams: List[str],
        recent_games_to_show: int = 1
    ) -> List[Dict]:
        """
        Single-pass game selection for recent games with proper deduplication.

        When a game involves two favorite teams, it counts toward BOTH teams' limits.
        Games are sorted by most recent first.
        """
        sorted_games = sorted(
            processed_games,
            key=lambda g: g.get('start_time_utc') or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        if not favorite_teams:
            return sorted_games

        selected_games = []
        selected_ids = set()
        team_counts = {team: 0 for team in favorite_teams}

        for game in sorted_games:
            game_id = game.get('id')
            if game_id in selected_ids:
                continue

            home = self._get_team_abbr(game, 'home')
            away = self._get_team_abbr(game, 'away')

            home_fav = home in favorite_teams
            away_fav = away in favorite_teams

            if not home_fav and not away_fav:
                continue

            home_needs = home_fav and team_counts[home] < recent_games_to_show
            away_needs = away_fav and team_counts[away] < recent_games_to_show

            if home_needs or away_needs:
                selected_games.append(game)
                selected_ids.add(game_id)
                if home_fav:
                    team_counts[home] += 1
                if away_fav:
                    team_counts[away] += 1

            if all(c >= recent_games_to_show for c in team_counts.values()):
                break

        self.logger.info(
            f"Selected {len(selected_games)} recent games for {len(favorite_teams)} "
            f"favorite teams: {team_counts}"
        )
        return selected_games

    def _select_upcoming_games_for_display(
        self, processed_games: List[Dict], favorite_teams: List[str],
        upcoming_games_to_show: int = 1
    ) -> List[Dict]:
        """
        Single-pass game selection for upcoming games with proper deduplication.

        When a game involves two favorite teams, it counts toward BOTH teams' limits.
        Games are sorted by earliest first.
        """
        sorted_games = sorted(
            processed_games,
            key=lambda g: g.get('start_time_utc') or datetime.max.replace(tzinfo=timezone.utc),
        )

        if not favorite_teams:
            return sorted_games

        selected_games = []
        selected_ids = set()
        team_counts = {team: 0 for team in favorite_teams}

        for game in sorted_games:
            game_id = game.get('id')
            if game_id in selected_ids:
                continue

            home = self._get_team_abbr(game, 'home')
            away = self._get_team_abbr(game, 'away')

            home_fav = home in favorite_teams
            away_fav = away in favorite_teams

            if not home_fav and not away_fav:
                continue

            home_needs = home_fav and team_counts[home] < upcoming_games_to_show
            away_needs = away_fav and team_counts[away] < upcoming_games_to_show

            if home_needs or away_needs:
                selected_games.append(game)
                selected_ids.add(game_id)
                if home_fav:
                    team_counts[home] += 1
                if away_fav:
                    team_counts[away] += 1

            if all(c >= upcoming_games_to_show for c in team_counts.values()):
                break

        self.logger.info(
            f"Selected {len(selected_games)} upcoming games for {len(favorite_teams)} "
            f"favorite teams: {team_counts}"
        )
        return selected_games

    def filter_live_games(self, games: List[Dict], league_config: Dict, 
                         league_key: str = None, data_manager=None) -> List[Dict]:
        """
        Filter and sort live games.

        Args:
            games: List of game dictionaries
            league_config: League-specific configuration
            league_key: League identifier (for MiLB-specific handling)
            data_manager: Optional data manager for MiLB live feed probing

        Returns:
            Filtered and sorted list of live games
        """
        favorite_teams = league_config.get('favorite_teams', [])
        show_favorite_teams_only = league_config.get('show_favorite_teams_only', False)
        show_all_live = league_config.get('show_all_live', False)

        live_games = []

        # MiLB-specific live detection logic
        if league_key == 'milb' and data_manager:
            for game in games:
                # MiLB uses different format - check status_state and status
                is_live_by_flags = (
                    game.get('status_state') == 'in' and 
                    game.get('status') == 'status_in_progress'
                )

                # Check detailed_state for hints
                detailed = str(game.get('detailed_state', '')).lower()
                is_live_by_detail_hint = any(
                    token in detailed for token in [
                        'in progress', 'game in progress', 'top of the', 
                        'bottom of the', 'middle of the', 'end of the'
                    ]
                )

                is_live = is_live_by_flags
                feed_confirmed = False

                # Probe live feed if needed
                game_pk = game.get('game_pk') or game.get('id')
                start_time_str = game.get('start_time')
                start_dt = None
                now_utc = datetime.now(timezone.utc)

                if start_time_str:
                    try:
                        start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        if start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        start_dt = None

                should_probe = False
                if is_live_by_detail_hint:
                    should_probe = True
                if is_live_by_flags and start_dt is not None:
                    future_seconds = (start_dt - now_utc).total_seconds()
                    if future_seconds > 5 * 60:
                        should_probe = True

                is_favorite_game = self.is_favorite_game(game, favorite_teams)
                if is_favorite_game:
                    if start_dt is None:
                        should_probe = True
                    else:
                        delta_sec = (now_utc - start_dt).total_seconds()
                        if -12 * 3600 <= delta_sec <= 12 * 3600:
                            should_probe = True

                if should_probe and start_dt is not None:
                    if abs((now_utc - start_dt).total_seconds()) > 12 * 3600:
                        should_probe = False

                if should_probe and game_pk:
                    if data_manager.probe_milb_live_feed(str(game_pk), game):
                        is_live = True
                        feed_confirmed = True

                if is_live and not feed_confirmed and start_dt is not None:
                    future_seconds = (start_dt - now_utc).total_seconds()
                    if future_seconds > 5 * 60:
                        is_live = False

                # Time sanity check
                if is_live:
                    if start_time_str:
                        try:
                            game_date = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            current_utc = datetime.now(timezone.utc)
                            hours_diff = (current_utc - game_date).total_seconds() / 3600
                            if hours_diff > 48:
                                continue
                        except Exception:
                            pass

                if is_live:
                    # Favorites-only filter
                    if show_favorite_teams_only and favorite_teams:
                        if not is_favorite_game:
                            continue

                    # Ensure scores are integers
                    try:
                        game['home_score'] = int(game.get('home_score', 0))
                        game['away_score'] = int(game.get('away_score', 0))
                    except (ValueError, TypeError):
                        pass

                    live_games.append(game)
        else:
            # ESPN leagues (MLB, NCAA Baseball)
            for game in games:
                # Check if live
                is_live = game.get('is_live', False) or game.get('status_state') == 'in'
                is_halftime = game.get('is_halftime', False)

                if is_live or is_halftime:
                    # Apply favorite teams filter (only when both flag is set AND favorites exist)
                    if show_favorite_teams_only and favorite_teams and not show_all_live:
                        if not self.is_favorite_game(game, favorite_teams):
                            continue
                    # Note: show_all_live overrides show_favorite_teams_only

                    live_games.append(game)

        # Sort live games
        live_games = self.sort_games(live_games, 'live')
        return live_games

    def filter_recent_games(self, games: List[Dict], league_config: Dict) -> List[Dict]:
        """
        Filter recent final games (within last 21 days).

        Args:
            games: List of game dictionaries
            league_config: League-specific configuration

        Returns:
            Filtered and sorted list of recent games
        """
        favorite_teams = league_config.get('favorite_teams', [])
        show_favorite_teams_only = league_config.get('show_favorite_teams_only', False)
        recent_games_to_show = league_config.get('recent_games_to_show', 5)

        # Define date range for "recent" games (last 21 days)
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=21)

        # Process games and filter for final games within date range
        processed_games = []
        for game in games:
            # Check if final
            is_final = game.get('is_final', False) or game.get('status_state') in ['post', 'final', 'completed']

            if is_final:
                # Check date range
                game_time = game.get('start_time_utc')
                if not game_time:
                    # Try parsing start_time if available
                    start_time_str = game.get('start_time')
                    if start_time_str:
                        try:
                            game_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            if game_time.tzinfo is None:
                                game_time = game_time.replace(tzinfo=timezone.utc)
                        except (ValueError, AttributeError):
                            game_time = None

                if game_time and game_time >= recent_cutoff:
                    processed_games.append(game)

        # Use single-pass algorithm for game selection
        # This properly handles games between two favorite teams (counts for both)
        if show_favorite_teams_only and favorite_teams:
            return self._select_recent_games_for_display(
                processed_games, favorite_teams, recent_games_to_show
            )
        else:
            # show_favorite_teams_only is False OR no favorites configured:
            # show N total games sorted by time (most recent first)
            processed_games.sort(
                key=lambda g: g.get('start_time_utc') or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True
            )
            return processed_games[:recent_games_to_show]

    def filter_upcoming_games(self, games: List[Dict], league_config: Dict) -> List[Dict]:
        """
        Filter upcoming games.

        Args:
            games: List of game dictionaries
            league_config: League-specific configuration

        Returns:
            Filtered and sorted list of upcoming games
        """
        favorite_teams = league_config.get('favorite_teams', [])
        show_favorite_teams_only = league_config.get('show_favorite_teams_only', False)
        upcoming_games_to_show = league_config.get('upcoming_games_to_show', 10)

        processed_games = []
        now_utc = datetime.now(timezone.utc)

        for game in games:
            # Check if upcoming
            is_upcoming = game.get('is_upcoming', False) or game.get('status_state') == 'pre'

            # For MiLB, also check if status indicates scheduled
            if not is_upcoming:
                status = game.get('status', '')
                status_state = game.get('status_state', '')
                if status in ['status_scheduled', 'status_other'] and status_state == 'pre':
                    is_upcoming = True

            if is_upcoming:
                # Validate it's actually in the future
                start_time_str = game.get('start_time')
                if start_time_str:
                    try:
                        game_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        if game_time.tzinfo is None:
                            game_time = game_time.replace(tzinfo=timezone.utc)

                        # Only include if in the future
                        if game_time <= now_utc:
                            continue

                        game['start_time_utc'] = game_time
                    except (ValueError, AttributeError):
                        pass

                # Apply favorite teams filter if enabled (only when both flag is set AND favorites exist)
                if show_favorite_teams_only and favorite_teams:
                    if not self.is_favorite_game(game, favorite_teams):
                        continue

                processed_games.append(game)

        # Use single-pass algorithm for game selection
        # This properly handles games between two favorite teams (counts for both)
        if show_favorite_teams_only and favorite_teams:
            return self._select_upcoming_games_for_display(
                processed_games, favorite_teams, upcoming_games_to_show
            )
        else:
            # No favorite teams: show N total games sorted by time (schedule view)
            processed_games.sort(
                key=lambda g: g.get('start_time_utc') or datetime.max.replace(tzinfo=timezone.utc)
            )
            return processed_games[:upcoming_games_to_show]

    def sort_games(self, games: List[Dict], mode: str) -> List[Dict]:
        """
        Sort games by priority (live status, favorites, time).

        Args:
            games: List of game dictionaries
            mode: Sort mode ('live', 'recent', 'upcoming')

        Returns:
            Sorted list of games
        """
        def sort_key_live(game):
            """Sort key for live games: prioritize favorites."""
            favorite_score = 0 if game.get('_is_favorite', False) else 1
            start_time = game.get('start_time_utc') or game.get('start_time', '')
            return (favorite_score, start_time)

        def sort_key_recent(game):
            """Sort key for recent games: most recent first."""
            start_time = game.get('start_time_utc') or game.get('start_time', '')
            if isinstance(start_time, str):
                try:
                    start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    start_time = datetime.min.replace(tzinfo=timezone.utc)
            if not isinstance(start_time, datetime):
                start_time = datetime.min.replace(tzinfo=timezone.utc)
            # Reverse to get most recent first
            return (-start_time.timestamp() if hasattr(start_time, 'timestamp') else 0,)

        def sort_key_upcoming(game):
            """Sort key for upcoming games: earliest first."""
            start_time = game.get('start_time_utc') or game.get('start_time', '')
            if isinstance(start_time, str):
                try:
                    start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    start_time = datetime.max.replace(tzinfo=timezone.utc)
            if not isinstance(start_time, datetime):
                start_time = datetime.max.replace(tzinfo=timezone.utc)
            return (start_time.timestamp() if hasattr(start_time, 'timestamp') else float('inf'),)

        if mode == 'live':
            games.sort(key=sort_key_live)
        elif mode == 'recent':
            games.sort(key=sort_key_recent)
        elif mode == 'upcoming':
            games.sort(key=sort_key_upcoming)

        return games

    def update_game_list(self, current_list: List[Dict], new_list: List[Dict], 
                        current_game: Optional[Dict] = None, current_index: int = 0) -> tuple[List[Dict], Optional[Dict], int]:
        """
        Update game list while maintaining current position if possible.

        Args:
            current_list: Current list of games
            new_list: New list of games
            current_game: Currently displayed game
            current_index: Current game index

        Returns:
            Tuple of (updated_list, updated_current_game, updated_index)
        """
        if not new_list:
            return [], None, 0

        # Check if list has changed
        new_game_ids = {g.get('id') for g in new_list if g.get('id')}
        current_game_ids = {g.get('id') for g in current_list if g.get('id')}

        if new_game_ids != current_game_ids:
            # List changed - try to maintain position
            if current_game and current_game.get('id') in new_game_ids:
                # Find new position of current game
                try:
                    new_index = next(i for i, g in enumerate(new_list) if g.get('id') == current_game.get('id'))
                    updated_game = new_list[new_index]
                    return new_list, updated_game, new_index
                except StopIteration:
                    pass

            # Reset to first game
            return new_list, new_list[0] if new_list else None, 0
        else:
            # List unchanged - just update current game data
            if current_game and current_game.get('id'):
                try:
                    new_index = next(i for i, g in enumerate(new_list) if g.get('id') == current_game.get('id'))
                    updated_game = new_list[new_index]
                    return new_list, updated_game, new_index
                except StopIteration:
                    pass

            # Fallback
            if current_index < len(new_list):
                return new_list, new_list[current_index], current_index

            return new_list, new_list[0] if new_list else None, 0

    def should_switch_game(self, games_list: List[Dict], current_index: int, 
                          last_switch_time: float, game_display_duration: float) -> bool:
        """
        Check if it's time to switch to the next game.

        Args:
            games_list: List of games
            current_index: Current game index
            last_switch_time: Time of last switch
            game_display_duration: Duration to display each game (seconds)

        Returns:
            True if should switch, False otherwise
        """
        if len(games_list) <= 1:
            return False

        current_time = time.time()
        return (current_time - last_switch_time) >= game_display_duration

    def get_next_game_index(self, games_list: List[Dict], current_index: int) -> int:
        """
        Get the next game index (with wraparound).

        Args:
            games_list: List of games
            current_index: Current game index

        Returns:
            Next game index
        """
        if not games_list:
            return 0
        return (current_index + 1) % len(games_list)

