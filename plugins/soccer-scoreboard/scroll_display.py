"""
Scroll Display Handler for Soccer Scoreboard Plugin

Implements high-FPS horizontal scrolling of all matching games with league separator icons.
Uses ScrollHelper for efficient numpy-based scrolling and dynamic duration calculation.

Features:
- Pre-rendered game cards for smooth scrolling
- League separator icons (Premier League, La Liga, etc.) between different leagues
- Dynamic duration based on total content width
- FPS logging and performance monitoring
- Live priority support for scroll mode
"""

import logging
import time
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    ScrollHelper = None

from game_renderer import GameRenderer

logger = logging.getLogger(__name__)

# League names for display (matches manager.py LEAGUE_NAMES)
LEAGUE_NAMES = {
    'eng.1': 'Premier League',
    'esp.1': 'La Liga',
    'ger.1': 'Bundesliga',
    'ita.1': 'Serie A',
    'fra.1': 'Ligue 1',
    'usa.1': 'MLS',
    'mex.1': 'Liga MX',
    'ned.1': 'Eredivisie',
    'por.1': 'Primeira Liga',
    'sco.1': 'Scottish Premiership',
    'bel.1': 'Belgian Pro League',
    'tur.super_lig': 'Turkish Super Lig',
    'eng.2': 'Championship',
    'eng.league_cup': 'EFL Cup',
    'eng.fa': 'FA Cup',
    'uefa.champions': 'Champions League',
    'uefa.europa': 'Europa League',
    'uefa.europa.conf': 'Conference League',
    'fifa.friendly': 'International Friendly',
    'conmebol.libertadores': 'Copa Libertadores',
    'fifa.worldq.uefa': 'World Cup Qualifying (UEFA)',
    'uefa.nations': 'UEFA Nations League',
    'fifa.world': 'FIFA World Cup',
    'fifa.world.u20': 'FIFA U-20 World Cup',
    'concacaf.nations.league': 'CONCACAF Nations League',
    'concacaf.gold': 'CONCACAF Gold Cup',
    'concacaf.champions': 'CONCACAF Champions Cup',
    'conmebol.copa.america': 'Copa America',
    'uefa.euro': 'UEFA Euro',
    'club.friendly': 'Club Friendly',
}


class ScrollDisplay:
    """
    Handles scroll mode display for the Soccer Scoreboard plugin.

    Coordinates with ScrollHelper for high-FPS scrolling and manages
    game card rendering and league separator icons.
    """

    def __init__(
        self,
        display_manager: Any,
        display_width: int,
        display_height: int,
        config: Dict[str, Any],
        plugin_dir: str
    ):
        """
        Initialize the ScrollDisplay handler.

        Args:
            display_manager: Display manager instance for rendering
            display_width: Width of the display in pixels
            display_height: Height of the display in pixels
            config: Plugin configuration dictionary
            plugin_dir: Path to the plugin directory for assets
        """
        self.display_manager = display_manager
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.plugin_dir = plugin_dir
        self.logger = logging.getLogger(__name__)

        # Initialize ScrollHelper if available
        self.scroll_helper: Optional[Any] = None
        if ScrollHelper:
            try:
                self.scroll_helper = ScrollHelper(
                    display_width=display_width,
                    display_height=display_height,
                    scroll_speed=self._get_scroll_speed(),
                    target_fps=self._get_target_fps()
                )
                self.logger.info(f"[Soccer Scroll] ScrollHelper initialized (speed={self._get_scroll_speed()}, fps={self._get_target_fps()})")
            except Exception as e:
                self.logger.error(f"Failed to initialize ScrollHelper: {e}")
                self.scroll_helper = None
        else:
            self.logger.warning("ScrollHelper not available - scroll mode will be limited")

        # State tracking
        self._current_games: List[Dict] = []
        self._current_game_type: str = ""
        self._current_leagues: List[str] = []
        self._is_scrolling: bool = False
        self._scroll_start_time: float = 0
        self._frame_count: int = 0
        self._fps_sample_start: float = 0

        # League separator icons cache
        self._separator_icons: Dict[str, Image.Image] = {}
        self._load_separator_icons()

    def _get_scroll_speed(self) -> float:
        """Get scroll speed from config with fallback."""
        scroll_config = self.config.get('scroll_mode', {})
        return scroll_config.get('scroll_speed', 50.0)

    def _get_target_fps(self) -> int:
        """Get target FPS from config with fallback."""
        scroll_config = self.config.get('scroll_mode', {})
        return scroll_config.get('target_fps', 30)

    def _get_scroll_settings(self) -> Dict[str, Any]:
        """Get scroll-related settings from config."""
        scroll_config = self.config.get('scroll_mode', {})
        return {
            'scroll_speed': scroll_config.get('scroll_speed', 50.0),
            'target_fps': scroll_config.get('target_fps', 30),
            'gap_between_games': scroll_config.get('gap_between_games', 24),
            'show_league_separators': scroll_config.get('show_league_separators', True),
            'min_duration': scroll_config.get('min_duration', 30),
            'max_duration': scroll_config.get('max_duration', 300),
        }

    def _load_separator_icons(self) -> None:
        """Load league separator icons from assets directory."""
        separator_dir = Path(self.plugin_dir) / "assets" / "separators"

        # Map league keys to separator icon filenames
        separator_files = {
            'eng.1': 'premier_league.png',
            'esp.1': 'la_liga.png',
            'ger.1': 'bundesliga.png',
            'ita.1': 'serie_a.png',
            'fra.1': 'ligue_1.png',
            'usa.1': 'mls.png',
            'mex.1': 'liga_mx.png',
            'ned.1': 'eredivisie.png',
            'por.1': 'primeira_liga.png',
            'sco.1': 'scottish_premiership.png',
            'bel.1': 'belgian_pro_league.png',
            'tur.super_lig': 'turkish_super_lig.png',
            'eng.2': 'championship.png',
            'eng.league_cup': 'efl_cup.png',
            'eng.fa': 'fa_cup.png',
            'uefa.champions': 'champions_league.png',
            'uefa.europa': 'europa_league.png',
            'uefa.europa.conf': 'conference_league.png',
            'fifa.friendly': 'international_friendly.png',
            'conmebol.libertadores': 'copa_libertadores.png',
            'fifa.worldq.uefa': 'world_cup_qualifying.png',
            'uefa.nations': 'nations_league.png',
            'fifa.world': 'world_cup.png',
            'fifa.world.u20': 'world_cup_u20.png',
            'concacaf.nations.league': 'concacaf_nations.png',
            'concacaf.gold': 'gold_cup.png',
            'concacaf.champions': 'concacaf_champions.png',
            'conmebol.copa.america': 'copa_america.png',
            'uefa.euro': 'euro.png',
            'club.friendly': 'club_friendly.png',
        }

        for league_key, filename in separator_files.items():
            icon_path = separator_dir / filename
            if icon_path.exists():
                try:
                    icon = Image.open(icon_path).convert('RGBA')
                    # Scale to fit display height if needed
                    if icon.height > self.display_height - 4:
                        scale = (self.display_height - 4) / icon.height
                        new_width = int(icon.width * scale)
                        new_height = int(icon.height * scale)
                        icon = icon.resize((new_width, new_height), Image.LANCZOS)
                    self._separator_icons[league_key] = icon
                    self.logger.debug(f"Loaded {LEAGUE_NAMES[league_key]} separator icon: {icon.size}")
                except Exception as e:
                    self.logger.error(f"Error loading {LEAGUE_NAMES[league_key]} separator icon: {e}")
            else:
                self.logger.debug(f"{LEAGUE_NAMES[league_key]} separator icon not found at {icon_path} (will skip separator)")

    def _determine_game_type(self, game: Dict, game_type: str = 'upcoming') -> str:
        """
        Determine the game type from the game's status or flags.

        Checks in order:
        1. Boolean flags (is_live, is_final/is_recent, is_upcoming)
        2. Status state mapping (in/post/pre)
        3. Explicit game_type hint from game dict
        4. Provided game_type parameter as fallback

        Args:
            game: Game dictionary
            game_type: Fallback game type if status is missing or unknown

        Returns:
            Game type: 'live', 'recent', or 'upcoming'
        """
        # First check boolean flags (pipeline game dicts)
        if game.get('is_live'):
            return 'live'
        if game.get('is_final') or game.get('is_recent'):
            return 'recent'
        if game.get('is_upcoming'):
            return 'upcoming'

        # Fall back to status.state mapping (with normalization)
        status = game.get('status')
        if isinstance(status, dict):
            state = status.get('state', '')
            if state == 'in':
                return 'live'
            elif state == 'post':
                return 'recent'
            elif state == 'pre':
                return 'upcoming'

        # Check for explicit game_type hint from game dict
        game_type_hint = game.get('game_type')
        if game_type_hint in ('live', 'recent', 'upcoming'):
            return game_type_hint

        # Return provided fallback if type cannot be determined
        return game_type

    def prepare_scroll_content(
        self,
        games: List[Dict],
        game_type: str,
        leagues: List[str],
        rankings_cache: Dict[str, int] = None
    ) -> bool:
        """
        Prepare scrolling content from a list of games.

        Args:
            games: List of game dictionaries with league info
            game_type: Type hint ('live', 'recent', 'upcoming', or 'mixed' for mixed types)
            leagues: List of leagues in order (e.g., ['eng.1', 'esp.1'])
            rankings_cache: Optional team rankings cache

        Returns:
            True if content was prepared successfully, False otherwise
        """
        if not self.scroll_helper:
            self.logger.error("ScrollHelper not available")
            return False

        if not games:
            self.logger.debug("No games to prepare for scrolling")
            self.scroll_helper.clear_cache()
            return False

        self._current_games = games
        self._current_game_type = game_type
        self._current_leagues = leagues

        # Get scroll settings
        scroll_settings = self._get_scroll_settings()
        gap_between_games = scroll_settings.get("gap_between_games", 24)
        show_separators = scroll_settings.get("show_league_separators", True)

        # Create game renderer
        renderer = GameRenderer(
            self.display_width,
            self.display_height,
            self.config,
            self.plugin_dir
        )
        if rankings_cache:
            renderer.set_rankings_cache(rankings_cache)

        # Pre-render all game cards
        content_items: List[Image.Image] = []
        current_league = None
        game_count = 0
        league_counts: Dict[str, int] = {}

        for game in games:
            game_league = game.get("league", "eng.1")  # Default to Premier League if not specified

            # Add league separator if switching leagues OR if this is the first league
            if show_separators:
                if current_league is None:
                    # First league - add separator
                    separator = self._separator_icons.get(game_league)
                    if separator:
                        sep_img = Image.new('RGB', (separator.width + 8, self.display_height), (0, 0, 0))
                        y_offset = (self.display_height - separator.height) // 2
                        sep_img.paste(separator, (4, y_offset), separator)
                        content_items.append(sep_img)
                        self.logger.debug(f"Added {LEAGUE_NAMES.get(game_league, game_league)} separator icon (first league)")
                elif game_league != current_league:
                    # Switching leagues - add separator
                    separator = self._separator_icons.get(game_league)
                    if separator:
                        # Create a separator image with proper background
                        sep_img = Image.new('RGB', (separator.width + 8, self.display_height), (0, 0, 0))
                        # Center the separator vertically
                        y_offset = (self.display_height - separator.height) // 2
                        sep_img.paste(separator, (4, y_offset), separator)
                        content_items.append(sep_img)
                        self.logger.debug(f"Added {LEAGUE_NAMES.get(game_league, game_league)} separator icon")

            current_league = game_league

            # Render game card - determine type from game state
            # Use caller's game_type as fallback (if valid), otherwise 'upcoming'
            try:
                fallback_type = game_type if game_type in ('live', 'recent', 'upcoming') else 'upcoming'
                individual_game_type = self._determine_game_type(game, fallback_type)
                game_img = renderer.render_game_card(game, individual_game_type)

                # Add horizontal padding to prevent logos from being cut off at edges
                # Logos are positioned at -10 and display_width+10, so we need padding
                padding = 12  # Padding on each side to ensure logos aren't cut off
                padded_width = game_img.width + (padding * 2)
                padded_img = Image.new('RGB', (padded_width, game_img.height), (0, 0, 0))
                padded_img.paste(game_img, (padding, 0))

                content_items.append(padded_img)
                game_count += 1
                league_counts[game_league] = league_counts.get(game_league, 0) + 1
            except Exception as e:
                self.logger.error(f"Error rendering game card: {e}")
                continue

        if not content_items:
            self.logger.warning("No game cards rendered")
            return False

        # Create scrolling image using ScrollHelper
        self.scroll_helper.create_scrolling_image(
            content_items,
            item_gap=gap_between_games,
            element_gap=0  # No element gap - each item is a complete game card
        )

        # Set cache_type marker for Vegas mode detection
        # This allows manager to verify the cache is Vegas mixed content vs. single-type
        self.scroll_helper.cache_type = game_type

        # Log what we loaded
        league_summary = ", ".join([f"{LEAGUE_NAMES.get(league, league)}({count})" for league, count in league_counts.items()])
        self.logger.info(
            f"[Soccer Scroll] Prepared {game_count} games for scrolling: {league_summary}"
        )
        self.logger.info(
            f"[Soccer Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
            f"Dynamic duration: {self.scroll_helper.calculated_duration}s"
        )

        # Reset tracking state
        self._is_scrolling = True
        self._scroll_start_time = time.time()
        self._frame_count = 0
        self._fps_sample_start = time.time()

        return True

    def display_scroll_frame(self) -> bool:
        """
        Display the next frame of the scrolling content.

        Returns:
            True if a frame was displayed, False if scroll is complete or no content
        """
        if not self.scroll_helper or not self.scroll_helper.cached_image:
            return False

        # Update scroll position
        self.scroll_helper.update_scroll_position()

        # Get visible portion
        visible = self.scroll_helper.get_visible_portion()
        if not visible:
            return False

        # Display the visible portion
        try:
            self.display_manager.image = visible
            self.display_manager.update_display()

            # Track frame rate
            self._frame_count += 1
            self.scroll_helper.log_frame_rate()

            # Periodic logging
            if self._frame_count % 300 == 0:  # Log every ~10 seconds at 30fps
                elapsed = time.time() - self._scroll_start_time
                avg_fps = self._frame_count / elapsed if elapsed > 0 else 0
                self.logger.debug(
                    f"[Soccer Scroll] Frame {self._frame_count}, "
                    f"elapsed: {elapsed:.1f}s, avg FPS: {avg_fps:.1f}"
                )

            return True
        except Exception as e:
            self.logger.error(f"Error displaying scroll frame: {e}")
            return False

    def is_scroll_complete(self) -> bool:
        """
        Check if the scroll cycle is complete.

        Returns:
            True if scroll has completed one full cycle
        """
        if not self.scroll_helper:
            return True
        return self.scroll_helper.is_complete()

    def get_scroll_duration(self) -> float:
        """
        Get the calculated scroll duration.

        Returns:
            Duration in seconds, or 0 if not available
        """
        if not self.scroll_helper:
            return 0
        return self.scroll_helper.calculated_duration

    def reset_scroll(self) -> None:
        """Reset scroll position to the beginning."""
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()
            self._scroll_start_time = time.time()
            self._frame_count = 0

    def clear_cache(self) -> None:
        """Clear the scroll cache."""
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        self._current_games = []
        self._current_game_type = ""
        self._current_leagues = []
        self._is_scrolling = False

    def has_content(self) -> bool:
        """
        Check if scroll content is available.

        Returns:
            True if content is ready for scrolling
        """
        return bool(self.scroll_helper and self.scroll_helper.cached_image)

    def get_current_game_count(self) -> int:
        """Get the number of games in the current scroll."""
        return len(self._current_games)

    def get_current_leagues(self) -> List[str]:
        """Get the list of leagues in the current scroll."""
        return self._current_leagues.copy()

    def get_scroll_info(self) -> Dict[str, Any]:
        """Get current scroll state information."""
        if not self.scroll_helper:
            return {"error": "ScrollHelper not available"}

        info = self.scroll_helper.get_scroll_info()
        info.update({
            "game_count": len(self._current_games),
            "game_type": self._current_game_type,
            "leagues": self._current_leagues,
            "is_scrolling": self._is_scrolling
        })
        return info

    def get_dynamic_duration(self) -> int:
        """Get the calculated dynamic duration for this scroll content."""
        if self.scroll_helper:
            return self.scroll_helper.get_dynamic_duration()
        return 60  # Default fallback

    def clear(self) -> None:
        """Clear scroll content and reset state."""
        self.clear_cache()


class ScrollDisplayManager:
    """
    Manages scroll display instances for different game types.

    This class provides a higher-level interface for the soccer plugin
    to manage scroll displays for live, recent, and upcoming games.
    """

    def __init__(
        self,
        display_manager,
        config: Dict[str, Any],
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the ScrollDisplayManager.

        Args:
            display_manager: Display manager instance
            config: Plugin configuration dictionary
            custom_logger: Optional custom logger instance
        """
        self.display_manager = display_manager
        self.config = config
        self.logger = custom_logger or logger

        # Determine plugin directory for asset loading
        self._plugin_dir = str(Path(__file__).parent)

        # Create scroll displays for each game type
        self._scroll_displays: Dict[str, ScrollDisplay] = {}
        self._current_game_type: Optional[str] = None

    def get_scroll_display(self, game_type: str) -> ScrollDisplay:
        """
        Get or create a scroll display for a game type.

        Args:
            game_type: Type of games ('live', 'recent', 'upcoming', 'mixed')

        Returns:
            ScrollDisplay instance for the game type
        """
        if game_type not in self._scroll_displays:
            display_width = self.display_manager.matrix.width
            display_height = self.display_manager.matrix.height
            self._scroll_displays[game_type] = ScrollDisplay(
                self.display_manager,
                display_width,
                display_height,
                self.config,
                self._plugin_dir
            )
        return self._scroll_displays[game_type]

    def prepare_and_display(
        self,
        games: List[Dict],
        game_type: str,
        leagues: List[str],
        rankings_cache: Dict[str, int] = None
    ) -> bool:
        """
        Prepare content and start displaying scroll.

        Args:
            games: List of game dictionaries
            game_type: Type of games
            leagues: List of leagues
            rankings_cache: Optional team rankings cache

        Returns:
            True if scroll was started successfully
        """
        scroll_display = self.get_scroll_display(game_type)

        success = scroll_display.prepare_scroll_content(
            games, game_type, leagues, rankings_cache
        )

        if success:
            self._current_game_type = game_type

        return success

    def display_frame(self, game_type: str = None) -> bool:
        """
        Display the next frame of the current scroll.

        Args:
            game_type: Optional game type (uses current if not specified)

        Returns:
            True if a frame was displayed
        """
        if game_type is None:
            game_type = self._current_game_type

        if game_type is None:
            return False

        scroll_display = self._scroll_displays.get(game_type)
        if scroll_display is None:
            return False

        return scroll_display.display_scroll_frame()

    def is_complete(self, game_type: str = None) -> bool:
        """Check if the current scroll is complete."""
        if game_type is None:
            game_type = self._current_game_type

        if game_type is None:
            return True

        scroll_display = self._scroll_displays.get(game_type)
        if scroll_display is None:
            return True

        return scroll_display.is_scroll_complete()

    def get_dynamic_duration(self, game_type: str = None) -> int:
        """Get the dynamic duration for the current scroll."""
        if game_type is None:
            game_type = self._current_game_type

        if game_type is None:
            return 60

        scroll_display = self._scroll_displays.get(game_type)
        if scroll_display is None:
            return 60

        return scroll_display.get_dynamic_duration()

    def has_cached_content(self) -> bool:
        """
        Check if any scroll display has cached content.

        Returns:
            True if any scroll display has a cached image ready for display
        """
        for scroll_display in self._scroll_displays.values():
            if hasattr(scroll_display, 'scroll_helper') and scroll_display.scroll_helper:
                if scroll_display.scroll_helper.cached_image is not None:
                    return True
        return False

    def clear_all(self) -> None:
        """Clear all scroll displays."""
        for scroll_display in self._scroll_displays.values():
            scroll_display.clear()
        self._current_game_type = None
