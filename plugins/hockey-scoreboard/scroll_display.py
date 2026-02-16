"""
Scroll Display Handler for Hockey Scoreboard Plugin

Implements high-FPS horizontal scrolling of all matching games with league separator icons.
Uses ScrollHelper for efficient numpy-based scrolling and dynamic duration calculation.

Features:
- Pre-rendered game cards for smooth scrolling
- League separator icons (NHL logo, NCAA hockey logos) between different leagues
- Dynamic duration based on total content width
- FPS logging and performance monitoring
- Live priority support for scroll mode
- Support for mixed game types in a single scroll
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

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class ScrollDisplay:
    """
    Handles scroll display mode for the hockey scoreboard plugin.

    This class:
    - Collects all games matching criteria (respecting live priority)
    - Pre-renders each game using GameRenderer
    - Adds league separator icons between different leagues
    - Composes a single wide image using ScrollHelper
    - Implements dynamic duration based on total content width
    - Logs FPS and game count during scrolling
    """

    # Paths to league separator icons
    NHL_SEPARATOR_ICON = "assets/sports/nhl_logos/NHL.png"
    NCAA_SEPARATOR_ICON = "assets/sports/ncaa_logos/NCAA.png"
    NCAAM_HOCKEY_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_hockey.png"
    NCAAW_HOCKEY_SEPARATOR_ICON = "assets/sports/ncaa_logos/ncaa_hockey.png"

    def __init__(
        self,
        display_manager,
        config: Dict[str, Any],
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the ScrollDisplay handler.

        Args:
            display_manager: Display manager instance
            config: Plugin configuration dictionary
            custom_logger: Optional custom logger instance
        """
        self.display_manager = display_manager
        self.config = config
        self.logger = custom_logger or logger

        # Get display dimensions
        if hasattr(display_manager, 'matrix') and display_manager.matrix is not None:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)

        # Initialize ScrollHelper
        if ScrollHelper:
            self.scroll_helper = ScrollHelper(
                self.display_width,
                self.display_height,
                self.logger
            )
            # Configure scroll settings
            self._configure_scroll_helper()
        else:
            self.scroll_helper = None
            self.logger.error("ScrollHelper not available - scroll mode will not work")

        # Shared logo cache for game renderer
        self._logo_cache: Dict[str, Image.Image] = {}

        # League separator icons cache
        self._separator_icons: Dict[str, Image.Image] = {}
        self._load_separator_icons()

        # Tracking state
        self._current_games: List[Dict] = []
        self._current_game_type: str = ""
        self._current_leagues: List[str] = []
        self._vegas_content_items: List[Image.Image] = []
        self._is_scrolling = False
        self._scroll_start_time: Optional[float] = None
        self._last_log_time: float = 0
        self._log_interval: float = 5.0  # Log every 5 seconds

        # Performance tracking
        self._frame_count: int = 0
        self._fps_sample_start: float = time.time()

    def _configure_scroll_helper(self) -> None:
        """Configure scroll helper with settings from config."""
        if not self.scroll_helper:
            return

        # Get global scroll settings, then per-league overrides
        scroll_settings = self._get_scroll_settings()

        # Set scroll speed (pixels per second in time-based mode)
        scroll_speed = scroll_settings.get("scroll_speed", 50.0)
        self.scroll_helper.set_scroll_speed(scroll_speed)

        # Set scroll delay
        scroll_delay = scroll_settings.get("scroll_delay", 0.01)
        self.scroll_helper.set_scroll_delay(scroll_delay)

        # Enable dynamic duration
        dynamic_duration = scroll_settings.get("dynamic_duration", True)
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=dynamic_duration,
            min_duration=30,
            max_duration=600,  # 10 minutes max
            buffer=0.2  # 20% buffer to ensure scroll completes fully off screen
        )

        # Use frame-based scrolling for better FPS control
        self.scroll_helper.set_frame_based_scrolling(True)

        # Convert scroll_speed from pixels/second to pixels/frame for frame-based mode
        # Formula: pixels_per_frame = (pixels/second) * (seconds/frame)
        if scroll_delay > 0:
            pixels_per_frame = scroll_speed * scroll_delay
        else:
            # Fallback: assume 100 FPS if delay is 0
            pixels_per_frame = scroll_speed / 100.0

        # Clamp to reasonable range (0.1 to 5 pixels per frame for smooth scrolling)
        pixels_per_frame = max(0.1, min(5.0, pixels_per_frame))
        self.scroll_helper.set_scroll_speed(pixels_per_frame)

        # Calculate effective pixels per second for logging
        effective_pps = pixels_per_frame / scroll_delay if scroll_delay > 0 else pixels_per_frame * 100

        self.logger.info(
            f"ScrollHelper configured: {pixels_per_frame:.2f} px/frame, delay={scroll_delay}s "
            f"(effective {effective_pps:.1f} px/s from {scroll_speed} px/s config), dynamic_duration={dynamic_duration}"
        )

    def _get_scroll_settings(self, league: Optional[str] = None) -> Dict[str, Any]:
        """Get scroll settings, optionally for a specific league."""
        # Default scroll settings
        defaults = {
            "scroll_speed": 50.0,
            "scroll_delay": 0.01,
            "gap_between_games": 48,
            "show_league_separators": True,
            "dynamic_duration": True
        }

        # Try to get league-specific settings first
        if league:
            league_config = self.config.get(league, {})
            league_scroll = league_config.get("scroll_settings", {})
            if league_scroll:
                return {**defaults, **league_scroll}

        # Fall back to NHL settings (usually first enabled)
        nhl_config = self.config.get("nhl", {})
        nhl_scroll = nhl_config.get("scroll_settings", {})
        if nhl_scroll:
            return {**defaults, **nhl_scroll}

        # Fall back to NCAA Men's settings (try both naming conventions)
        for league_key in ["ncaa_mens", "ncaam_hockey"]:
            ncaa_config = self.config.get(league_key, {})
            ncaa_scroll = ncaa_config.get("scroll_settings", {})
            if ncaa_scroll:
                return {**defaults, **ncaa_scroll}

        # Fall back to NCAA Women's settings (try both naming conventions)
        for league_key in ["ncaa_womens", "ncaaw_hockey"]:
            ncaa_config = self.config.get(league_key, {})
            ncaa_scroll = ncaa_config.get("scroll_settings", {})
            if ncaa_scroll:
                return {**defaults, **ncaa_scroll}

        return defaults

    def _load_separator_icons(self) -> None:
        """Load and resize league separator icons."""
        separator_height = self.display_height - 4  # Leave some padding

        # Load NHL icon
        if os.path.exists(self.NHL_SEPARATOR_ICON):
            try:
                # Use context manager to ensure file handle is closed
                with Image.open(self.NHL_SEPARATOR_ICON) as nhl_file:
                    # Convert creates a copy; if already RGBA, use copy() to detach from file
                    if nhl_file.mode != "RGBA":
                        nhl_icon = nhl_file.convert("RGBA")
                    else:
                        nhl_icon = nhl_file.copy()
                # Resize to fit height while maintaining aspect ratio (after file is closed)
                aspect = nhl_icon.width / nhl_icon.height
                new_width = int(separator_height * aspect)
                nhl_icon = nhl_icon.resize((new_width, separator_height), resample=RESAMPLE_FILTER)
                self._separator_icons["nhl"] = nhl_icon
                self.logger.debug(f"Loaded NHL separator icon: {new_width}x{separator_height}")
            except Exception:
                self.logger.exception("Error loading NHL separator icon")
        else:
            self.logger.warning(f"NHL separator icon not found at {self.NHL_SEPARATOR_ICON}")

        # Load NCAA icon (try sport-specific first, then generic)
        ncaa_icon_paths = [
            (self.NCAAM_HOCKEY_SEPARATOR_ICON, ["ncaam_hockey", "ncaa_mens"]),
            (self.NCAAW_HOCKEY_SEPARATOR_ICON, ["ncaaw_hockey", "ncaa_womens"]),
            (self.NCAA_SEPARATOR_ICON, ["ncaa"]),
        ]

        for icon_path, league_keys in ncaa_icon_paths:
            if os.path.exists(icon_path):
                try:
                    # Use context manager to ensure file handle is closed
                    with Image.open(icon_path) as ncaa_file:
                        # Convert creates a copy; if already RGBA, use copy() to detach from file
                        if ncaa_file.mode != "RGBA":
                            ncaa_icon = ncaa_file.convert("RGBA")
                        else:
                            ncaa_icon = ncaa_file.copy()
                    # Resize to fit height while maintaining aspect ratio (after file is closed)
                    aspect = ncaa_icon.width / ncaa_icon.height
                    new_width = int(separator_height * aspect)
                    ncaa_icon = ncaa_icon.resize((new_width, separator_height), resample=RESAMPLE_FILTER)
                    for key in league_keys:
                        self._separator_icons[key] = ncaa_icon
                    self.logger.debug(f"Loaded NCAA separator icon from {icon_path}: {new_width}x{separator_height}")
                except Exception:
                    self.logger.exception(f"Error loading NCAA separator icon from {icon_path}")

    def _determine_game_type(self, game: Dict) -> str:
        """
        Determine the game type from the game's status.

        Args:
            game: Game dictionary

        Returns:
            Game type: 'live', 'recent', or 'upcoming'
        """
        state = game.get('status', {}).get('state', '')
        if state == 'in':
            return 'live'
        elif state == 'post':
            return 'recent'
        elif state == 'pre':
            return 'upcoming'
        else:
            # Default to upcoming if state is unknown
            return 'upcoming'

    def prepare_scroll_content(
        self,
        games: List[Dict],
        game_type: str,
        leagues: List[str],
        rankings_cache: Optional[Dict[str, int]] = None
    ) -> bool:
        """
        Prepare scrolling content from a list of games.

        Args:
            games: List of game dictionaries with league info
            game_type: Type hint ('live', 'recent', 'upcoming', or 'mixed' for mixed types)
            leagues: List of leagues in order (e.g., ['nhl', 'ncaam_hockey', 'ncaaw_hockey'])
            rankings_cache: Optional team rankings cache

        Returns:
            True if content was prepared successfully, False otherwise
        """
        if not self.scroll_helper:
            self.logger.error("ScrollHelper not available")
            return False

        if not games:
            self.logger.debug("No games to prepare for scrolling")
            self.clear()  # Reset all scroll state, not just cache
            return False

        self._current_games = games
        self._current_game_type = game_type
        self._current_leagues = leagues

        # Get scroll settings using primary league from the provided leagues list
        primary_league = leagues[0] if leagues else None
        scroll_settings = self._get_scroll_settings(primary_league)
        gap_between_games = scroll_settings.get("gap_between_games", 24)
        show_separators = scroll_settings.get("show_league_separators", True)

        # Create game renderer
        renderer = GameRenderer(
            self.display_width,
            self.display_height,
            self.config,
            logo_cache=self._logo_cache,
            custom_logger=self.logger
        )
        if rankings_cache:
            renderer.set_rankings_cache(rankings_cache)

        # Pre-render all game cards
        content_items: List[Image.Image] = []
        current_league = None
        game_count = 0
        league_counts: Dict[str, int] = {}

        for game in games:
            game_league = game.get("league", "nhl")  # Default to NHL if not specified

            # Add league separator if switching leagues OR if this is the first league
            if show_separators:
                if current_league is None:
                    # First league - add separator at the start
                    separator = self._separator_icons.get(game_league)
                    if separator:
                        # Create a separator image with proper background
                        sep_img = Image.new('RGB', (separator.width + 8, self.display_height), (0, 0, 0))
                        # Center the separator vertically
                        y_offset = (self.display_height - separator.height) // 2
                        sep_img.paste(separator, (4, y_offset), separator)
                        content_items.append(sep_img)
                        self.logger.debug(f"Added {game_league} separator icon at start")
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
                        self.logger.debug(f"Added {game_league} separator icon")

            current_league = game_league

            # Render game card
            # Only determine type from game state when in 'mixed' mode; otherwise use the passed game_type
            try:
                if game_type == 'mixed':
                    individual_game_type = self._determine_game_type(game)
                else:
                    individual_game_type = game_type
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
            except Exception:
                self.logger.exception("Error rendering game card")
                continue

        if not content_items:
            self.logger.warning("No game cards rendered")
            return False

        # Store individual items for Vegas mode (avoids scroll_helper padding)
        self._vegas_content_items = list(content_items)

        # Create scrolling image using ScrollHelper
        self.scroll_helper.create_scrolling_image(
            content_items,
            item_gap=gap_between_games,
            element_gap=0  # No element gap - each item is a complete game card
        )

        # Log what we loaded
        league_summary = ", ".join([f"{league.upper()}({count})" for league, count in league_counts.items()])
        self.logger.info(
            f"[Hockey Scroll] Prepared {game_count} games for scrolling: {league_summary}"
        )
        self.logger.info(
            f"[Hockey Scroll] Total scroll width: {self.scroll_helper.total_scroll_width}px, "
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
            self._log_scroll_progress()
        except Exception:
            self.logger.exception("Error displaying scroll frame")
            return False
        else:
            return True

    def _log_scroll_progress(self) -> None:
        """Log scroll progress and FPS periodically."""
        current_time = time.time()

        if current_time - self._last_log_time >= self._log_interval:
            # Calculate FPS
            elapsed = current_time - self._fps_sample_start
            if elapsed > 0:
                fps = self._frame_count / elapsed

                # Get scroll info
                scroll_info = self.scroll_helper.get_scroll_info()

                self.logger.info(
                    f"[Hockey Scroll] FPS: {fps:.1f}, "
                    f"Position: {scroll_info['scroll_position']:.0f}/{scroll_info['total_width']}px, "
                    f"Elapsed: {scroll_info.get('elapsed_time', 0):.1f}s/{scroll_info['dynamic_duration']}s"
                )

            # Reset FPS tracking
            self._frame_count = 0
            self._fps_sample_start = current_time
            self._last_log_time = current_time

    def is_scroll_complete(self) -> bool:
        """Check if the scroll cycle is complete."""
        if not self.scroll_helper:
            return True
        return self.scroll_helper.is_scroll_complete()

    def reset_scroll(self) -> None:
        """Reset the scroll position to the beginning."""
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()
            self._frame_count = 0
            self._fps_sample_start = time.time()
            self.logger.debug("Scroll position reset")

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
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        self._current_games = []
        self._current_game_type = ""
        self._current_leagues = []
        self._is_scrolling = False
        self._scroll_start_time = None
        self.logger.debug("Scroll display cleared")


class ScrollDisplayManager:
    """
    Manages scroll display instances for different game types.

    This class provides a higher-level interface for the hockey plugin
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

        # Create scroll displays for each game type
        self._scroll_displays: Dict[str, ScrollDisplay] = {}
        self._current_game_type: Optional[str] = None

    def get_scroll_display(self, game_type: str) -> ScrollDisplay:
        """
        Get or create a scroll display for a game type.

        Args:
            game_type: Type of games ('live', 'recent', 'upcoming')

        Returns:
            ScrollDisplay instance for the game type
        """
        if game_type not in self._scroll_displays:
            self._scroll_displays[game_type] = ScrollDisplay(
                self.display_manager,
                self.config,
                self.logger
            )
        return self._scroll_displays[game_type]

    def prepare_and_display(
        self,
        games: List[Dict],
        game_type: str,
        leagues: List[str],
        rankings_cache: Optional[Dict[str, int]] = None
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

    def display_frame(self, game_type: Optional[str] = None) -> bool:
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

    def is_complete(self, game_type: Optional[str] = None) -> bool:
        """Check if the current scroll is complete."""
        if game_type is None:
            game_type = self._current_game_type

        if game_type is None:
            return True

        scroll_display = self._scroll_displays.get(game_type)
        if scroll_display is None:
            return True

        return scroll_display.is_scroll_complete()

    def get_dynamic_duration(self, game_type: Optional[str] = None) -> int:
        """Get the dynamic duration for the current scroll."""
        if game_type is None:
            game_type = self._current_game_type

        if game_type is None:
            return 60

        scroll_display = self._scroll_displays.get(game_type)
        if scroll_display is None:
            return 60

        return scroll_display.get_dynamic_duration()

    def get_all_vegas_content_items(self) -> list:
        """Collect _vegas_content_items from all scroll displays."""
        items = []
        for sd in self._scroll_displays.values():
            vegas_items = getattr(sd, '_vegas_content_items', None)
            if vegas_items:
                items.extend(vegas_items)
        return items

    def clear_all(self) -> None:
        """Clear all scroll displays."""
        for scroll_display in self._scroll_displays.values():
            scroll_display.clear()
        self._current_game_type = None
