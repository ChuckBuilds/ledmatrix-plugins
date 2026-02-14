"""
Baseball Odds Manager

Handles odds fetching and display for baseball games.
"""

import logging
from typing import Any, Dict, Optional

from PIL import ImageDraw

try:
    from src.base_odds_manager import BaseOddsManager as OddsManager
except ImportError:
    OddsManager = None


class BaseballOddsManager:
    """Manages odds fetching and display for baseball games."""

    def __init__(self, cache_manager, config_manager=None, logger: logging.Logger = None):
        """
        Initialize the odds manager.

        Args:
            cache_manager: Cache manager instance
            config_manager: Configuration manager (optional)
            logger: Logger instance
        """
        self.cache_manager = cache_manager
        self.config_manager = config_manager or (cache_manager.config_manager if hasattr(cache_manager, 'config_manager') else None)
        self.logger = logger or logging.getLogger(__name__)

        # Initialize odds manager if available
        if OddsManager:
            try:
                self.odds_manager = OddsManager(cache_manager, self.config_manager)
            except Exception as e:
                self.logger.warning(f"Failed to initialize OddsManager: {e}")
                self.odds_manager = None
        else:
            self.odds_manager = None
            self.logger.warning("OddsManager not available - odds functionality disabled")

    def fetch_odds(self, game: Dict, league_config: Dict, sport: str = "baseball", 
                  league: str = None) -> Optional[Dict]:
        """
        Fetch odds for a specific game.

        Args:
            game: Game dictionary with 'id' field
            league_config: League-specific configuration
            sport: Sport name (default: "baseball")
            league: League identifier (e.g., "mlb", "ncaa_baseball")

        Returns:
            Odds data dictionary or None if unavailable
        """
        if not self.odds_manager:
            return None

        show_odds = league_config.get('show_odds', False)
        if not show_odds:
            return None

        try:
            game_id = game.get('id')
            if not game_id:
                return None

            # Determine update interval based on game state
            is_live = game.get('is_live', False) or game.get('status_state') == 'in'
            update_interval = (
                league_config.get("live_odds_update_interval", 60) if is_live
                else league_config.get("odds_update_interval", 3600)
            )

            # Fetch odds using OddsManager
            odds_data = self.odds_manager.get_odds(
                sport=sport,
                league=league,
                event_id=str(game_id),
                update_interval_seconds=update_interval
            )

            if odds_data:
                game['odds'] = odds_data
                self.logger.debug(f"Successfully fetched and attached odds for game {game_id}")
                return odds_data
            else:
                self.logger.debug(f"No odds data returned for game {game_id}")
                return None

        except Exception as e:
            self.logger.error(f"Error fetching odds for game {game.get('id', 'N/A')}: {e}")
            return None

    def render_odds(self, draw: ImageDraw.Draw, odds: Dict[str, Any], width: int, 
                   height: int, fonts: Dict) -> None:
        """
        Render odds on the scorebug with dynamic positioning.

        Replicates the logic from SportsCore._draw_dynamic_odds().

        Args:
            draw: ImageDraw instance
            odds: Odds data dictionary
            width: Display width
            height: Display height
            fonts: Font dictionary with 'detail' font
        """
        if not odds:
            return

        home_team_odds = odds.get('home_team_odds', {})
        away_team_odds = odds.get('away_team_odds', {})
        home_spread = home_team_odds.get('spread_odds')
        away_spread = away_team_odds.get('spread_odds')

        # Get top-level spread as fallback
        top_level_spread = odds.get('spread')

        # If we have a top-level spread and the individual spreads are missing, use the top-level
        if top_level_spread is not None:
            if home_spread is None:
                home_spread = top_level_spread
            if away_spread is None:
                away_spread = -top_level_spread

        # Determine which team is favored (has negative spread)
        home_favored = home_spread is not None and home_spread < 0
        away_favored = away_spread is not None and away_spread < 0

        # Only show the negative spread (favored team)
        favored_spread = None
        favored_side = None

        if home_favored:
            favored_spread = home_spread
            favored_side = 'home'
        elif away_favored:
            favored_spread = away_spread
            favored_side = 'away'

        # Show the negative spread on the appropriate side
        if favored_spread is not None:
            spread_text = str(favored_spread)
            font = fonts.get('detail', fonts.get('status'))
            
            try:
                spread_width = draw.textlength(spread_text, font=font)
            except AttributeError:
                # Fallback for older PIL versions
                bbox = draw.textbbox((0, 0), spread_text, font=font)
                spread_width = bbox[2] - bbox[0]

            if favored_side == 'home':
                # Home team is favored, show spread on right side
                spread_x = width - spread_width  # Top right
                spread_y = 0
                self._draw_text_with_outline(draw, spread_text, (spread_x, spread_y), font, fill=(0, 255, 0))
            else:
                # Away team is favored, show spread on left side
                spread_x = 0  # Top left
                spread_y = 0
                self._draw_text_with_outline(draw, spread_text, (spread_x, spread_y), font, fill=(0, 255, 0))

        # Show over/under on the opposite side of the favored team
        over_under = odds.get('over_under')
        if over_under is not None:
            ou_text = f"O/U: {over_under}"
            font = fonts.get('detail', fonts.get('status'))
            
            try:
                ou_width = draw.textlength(ou_text, font=font)
            except AttributeError:
                # Fallback for older PIL versions
                bbox = draw.textbbox((0, 0), ou_text, font=font)
                ou_width = bbox[2] - bbox[0]

            if favored_side == 'home':
                # Home team is favored, show O/U on left side (opposite of spread)
                ou_x = 0  # Top left
                ou_y = 0
            elif favored_side == 'away':
                # Away team is favored, show O/U on right side (opposite of spread)
                ou_x = width - ou_width  # Top right
                ou_y = 0
            else:
                # No clear favorite, show O/U in center
                ou_x = (width - ou_width) // 2
                ou_y = 0

            self._draw_text_with_outline(draw, ou_text, (ou_x, ou_y), font, fill=(0, 255, 0))

    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, 
                                font, fill=(255, 255, 255), outline_color=(0, 0, 0)) -> None:
        """
        Draw text with a black outline for better readability.

        Args:
            draw: ImageDraw instance
            text: Text to draw
            position: (x, y) position tuple
            font: Font to use
            fill: Text color (default: white)
            outline_color: Outline color (default: black)
        """
        x, y = position
        # Draw outline
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        # Draw main text
        draw.text((x, y), text, font=font, fill=fill)

