"""
Leaderboard Plugin for LEDMatrix

Displays scrolling leaderboards and standings for multiple sports leagues.
Shows team rankings, records, and statistics in a scrolling ticker format.

Features:
- Multi-sport leaderboard display (NFL, NBA, MLB, NCAA, NHL)
- Conference and division filtering
- NCAA rankings vs standings
- Scrolling ticker format with dynamic duration
- Configurable scroll speed and display options
- Background data fetching

API Version: 1.0.0
"""

import time
import logging
from typing import Dict, Any, List, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin
from src.common.scroll_helper import ScrollHelper

from league_config import LeagueConfig
from data_fetcher import DataFetcher
from image_renderer import ImageRenderer

logger = logging.getLogger(__name__)


class LeaderboardPlugin(BasePlugin):
    """
    Leaderboard plugin for displaying sports standings and rankings.

    Supports multiple sports leagues with configurable display options,
    conference/division filtering, and scrolling ticker format.
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the leaderboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Get display dimensions
        self.display_width = display_manager.width
        self.display_height = display_manager.height
        
        # Configuration
        self.global_config = config.get('global', {})
        self.update_interval = self.global_config.get('update_interval', 3600)
        
        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        
        # Scroll speed configuration - prefer display object (granular control), fallback to scroll_pixels_per_second for backward compatibility
        display_config = self.global_config.get('display', {})
        if display_config and ('scroll_speed' in display_config or 'scroll_delay' in display_config):
            # New format: use display object for granular control
            self.scroll_speed = display_config.get('scroll_speed', 1.0)
            self.scroll_delay = display_config.get('scroll_delay', 0.01)
            self.scroll_pixels_per_second = None  # Not using pixels per second mode
            self.logger.info(f"Using global.display.scroll_speed={self.scroll_speed} px/frame, global.display.scroll_delay={self.scroll_delay}s (frame-based mode)")
        else:
            # Old format: use scroll_pixels_per_second (backward compatibility)
            self.scroll_pixels_per_second = self.global_config.get('scroll_pixels_per_second', 15.0)
            self.scroll_delay = self.global_config.get('scroll_delay', 0.01)
            if self.scroll_pixels_per_second is not None:
                self.logger.info(f"Using scroll_pixels_per_second={self.scroll_pixels_per_second} px/s (time-based mode, backward compatibility)")
            else:
                # Calculate from legacy scroll_speed/scroll_delay
                self.scroll_speed = self.global_config.get('scroll_speed', 1)
                self.logger.info(f"Using legacy scroll_speed={self.scroll_speed}, scroll_delay={self.scroll_delay} (backward compatibility)")
        self.dynamic_duration_settings = self._load_dynamic_duration_settings(
            self.global_config.get('dynamic_duration')
        )
        self.dynamic_duration_enabled = self.dynamic_duration_settings['enabled']
        self.min_duration = self.dynamic_duration_settings['min_duration_seconds']
        self.max_duration = self.dynamic_duration_settings['max_duration_seconds']
        self.duration_buffer = self.dynamic_duration_settings['buffer_ratio']
        self.dynamic_duration_cap = self.dynamic_duration_settings['controller_cap_seconds']
        # Determine loop behavior: scroll_mode takes precedence, then loop boolean
        scroll_mode = self.global_config.get('scroll_mode', 'one_shot')
        self.loop = scroll_mode == 'continuous' or bool(self.global_config.get('loop', False))
        
        # Request timeout
        self.request_timeout = self.global_config.get('request_timeout', 30)
        
        # Initialize components
        self.league_config = LeagueConfig(config, self.logger)
        self.data_fetcher = DataFetcher(cache_manager, self.logger, self.request_timeout)
        self.image_renderer = ImageRenderer(self.display_height, self.logger)
        
        # Initialize scroll helper
        self.scroll_helper = ScrollHelper(self.display_width, self.display_height, self.logger)
        
        # Configure ScrollHelper with plugin settings
        # Check if we should use frame-based scrolling (new format) or time-based (old format)
        use_frame_based = (self.scroll_pixels_per_second is None and 
                          display_config and 
                          ('scroll_speed' in display_config or 'scroll_delay' in display_config))
        
        if use_frame_based:
            # New format: use frame-based scrolling for finer control
            if hasattr(self.scroll_helper, 'set_frame_based_scrolling'):
                self.scroll_helper.set_frame_based_scrolling(True)
                self.logger.info(f"Frame-based scrolling enabled: {self.scroll_speed} px/frame, {self.scroll_delay}s delay")
            # In frame-based mode, scroll_speed is pixels per frame
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
            # Log effective pixels per second for reference
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s ({self.scroll_speed} px/frame at {1.0/self.scroll_delay:.0f} FPS)")
        else:
            # Old format: use time-based scrolling (backward compatibility)
            if self.scroll_pixels_per_second is not None:
                pixels_per_second = self.scroll_pixels_per_second
                self.logger.info(f"Using scroll_pixels_per_second: {pixels_per_second} px/s (time-based mode)")
            else:
                # Convert scroll_speed from pixels per frame to pixels per second (backward compatibility)
                pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
                self.logger.info(f"Calculated scroll speed: {pixels_per_second} px/s (from scroll_speed={self.scroll_speed}, scroll_delay={self.scroll_delay})")
            
            self.scroll_helper.set_scroll_speed(pixels_per_second)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
        
        # Set target FPS for high-performance scrolling (default 100 FPS)
        target_fps = self.global_config.get('target_fps') or self.global_config.get('scroll_target_fps', 100)
        if hasattr(self.scroll_helper, 'set_target_fps'):
            self.scroll_helper.set_target_fps(target_fps)
            self.logger.info(f"Target FPS set to: {target_fps} FPS")
        else:
            # Fallback for older ScrollHelper versions - set target_fps directly
            self.scroll_helper.target_fps = max(30.0, min(200.0, target_fps))
            self.scroll_helper.frame_time_target = 1.0 / self.scroll_helper.target_fps
            self.logger.debug(f"Target FPS set to: {self.scroll_helper.target_fps} FPS (using fallback method)")
        
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration_enabled,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            buffer=self.duration_buffer
        )
        
        # State
        self.leaderboard_data = []
        self.last_update = 0
        self.last_warning_time = 0
        self.last_no_leagues_warning_time = 0
        self.warning_cooldown = 300  # Only warn once every 5 minutes if data is unavailable
        self.no_leagues_warning_cooldown = 300  # Only warn once every 5 minutes about no leagues enabled
        
        # Enable scrolling for high FPS
        self.enable_scrolling = True
        
        # Log enabled leagues
        enabled_leagues = self.league_config.get_enabled_leagues()
        self.logger.info("Leaderboard plugin initialized")
        self.logger.info(f"Enabled leagues: {enabled_leagues}")
        self.logger.info(f"Display dimensions: {self.display_width}x{self.display_height}")
        # Log scroll speed (check if frame-based mode was used)
        if hasattr(self.scroll_helper, 'frame_based_scrolling') and self.scroll_helper.frame_based_scrolling:
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.logger.info(f"Scroll speed: {self.scroll_speed} px/frame, {self.scroll_delay}s delay ({pixels_per_second:.1f} px/s effective)")
        else:
            if hasattr(self, 'scroll_pixels_per_second') and self.scroll_pixels_per_second is not None:
                self.logger.info(f"Scroll speed: {self.scroll_pixels_per_second} px/s")
            else:
                pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
                self.logger.info(f"Scroll speed: {pixels_per_second:.1f} px/s")
        self.logger.info(f"Scroll mode: {'continuous' if self.loop else 'one_shot'}")
        self.logger.info(
            "Dynamic duration settings: enabled=%s, min=%ss, max=%ss, buffer=%.2f, controller_cap=%ss",
            self.dynamic_duration_enabled,
            self.min_duration,
            self.max_duration,
            self.duration_buffer,
            self.dynamic_duration_cap,
        )
        self._cycle_complete = False
        
        # Attempt initial data fetch (will use cached data if available)
        if enabled_leagues:
            self.logger.info("Attempting initial data fetch...")
            self.update(force=True)
        else:
            self.logger.warning("No leagues are enabled - leaderboard will not display any data")
    
    def update(self, force: bool = False) -> None:
        """
        Update standings data for all enabled leagues.
        
        Args:
            force: If True, bypass the time check and force an update
        """
        current_time = time.time()
        
        # Check if it's time to update (unless forced)
        if not force and current_time - self.last_update < self.update_interval:
            self.logger.debug(f"Skipping update - only {current_time - self.last_update:.1f}s since last update (interval: {self.update_interval}s)")
            return
        
        try:
            self.logger.info(f"Updating leaderboard data (force={force})")
            self.leaderboard_data = []
            
            # Fetch standings for each enabled league
            enabled_leagues = self.league_config.get_enabled_leagues()
            if not enabled_leagues:
                # Rate limit warning to avoid log spam
                current_time = time.time()
                if (current_time - self.last_no_leagues_warning_time) >= self.no_leagues_warning_cooldown:
                    self.logger.warning("No leagues are enabled in configuration")
                    self.last_no_leagues_warning_time = current_time
                return
            
            self.logger.info(f"Fetching data for {len(enabled_leagues)} enabled league(s): {enabled_leagues}")
            
            for league_key in enabled_leagues:
                league_config = self.league_config.get_league_config(league_key)
                if not league_config:
                    self.logger.warning(f"No configuration found for league: {league_key}")
                    continue
                
                self.logger.debug(f"Fetching standings for {league_key}")
                standings = self.data_fetcher.fetch_standings(league_config)
                
                if standings:
                    self.leaderboard_data.append({
                        'league': league_key,
                        'league_config': league_config,
                        'teams': standings
                    })
                    self.logger.info(f"Successfully fetched {len(standings)} teams for {league_key}")
                else:
                    self.logger.warning(f"No standings data returned for {league_key}")
            
            self.last_update = current_time
            
            # Clear scroll cache when data updates
            self.scroll_helper.clear_cache()
            
            total_teams = sum(len(d['teams']) for d in self.leaderboard_data)
            self.logger.info(f"Updated standings data: {len(self.leaderboard_data)} leagues, "
                           f"{total_teams} total teams")
            
            if not self.leaderboard_data:
                self.logger.error("No leaderboard data was fetched after attempting to update all enabled leagues")
            
        except Exception as e:
            self.logger.error(f"Error updating leaderboard data: {e}", exc_info=True)
    
    def display(self, force_clear: bool = False) -> None:
        """Display the scrolling leaderboard."""
        if not self.enabled:
            self.logger.debug("Leaderboard plugin is disabled")
            return
        
        if not self.leaderboard_data:
            current_time = time.time()
            should_warn = (current_time - self.last_warning_time) >= self.warning_cooldown
            
            if should_warn:
                self.logger.warning("No leaderboard data available. Attempting to force update...")
                self.last_warning_time = current_time
            
            self.update(force=True)
            if not self.leaderboard_data:
                if should_warn:
                    self.logger.warning("Still no data after forced update, showing fallback")
                    self.logger.debug("Will check again on next display() call - warning suppressed for 5 minutes")
                self._display_fallback_message()
                return
        
        # Create scrolling image if needed
        if not self.scroll_helper.cached_image or force_clear:
            self.logger.info("Creating leaderboard image...")
            self._create_leaderboard_image()
            if not self.scroll_helper.cached_image:
                self.logger.error("Failed to create leaderboard image, showing fallback")
                self._display_fallback_message()
                return
            self.logger.info("Leaderboard image created successfully")
            self._cycle_complete = False
        
        if force_clear:
            self.scroll_helper.reset_scroll()
            self._cycle_complete = False
        
        # In one-shot mode, stop scrolling once the cycle is complete
        if not self.loop and self._cycle_complete:
            self.display_manager.set_scrolling_state(False)
            return

        # Signal scrolling state
        self.display_manager.set_scrolling_state(True)
        self.display_manager.process_deferred_updates()

        # Update scroll position using the scroll helper
        self.scroll_helper.update_scroll_position()
        if self.scroll_helper.is_scroll_complete():
            if not self._cycle_complete:
                scroll_info = self.scroll_helper.get_scroll_info()
                elapsed_time = scroll_info.get('elapsed_time')
                self.logger.info(
                    "Leaderboard scroll cycle completed (elapsed=%.2fs, target=%.2fs)",
                    elapsed_time if elapsed_time is not None else -1.0,
                    scroll_info.get('dynamic_duration'),
                )
            self._cycle_complete = True
        
        # Get visible portion
        visible_portion = self.scroll_helper.get_visible_portion()
        if visible_portion:
            # Update display
            self.display_manager.image.paste(visible_portion, (0, 0))
            self.display_manager.update_display()
        
        # Log frame rate (less frequently to avoid spam)
        self.scroll_helper.log_frame_rate()
    
    def _create_leaderboard_image(self) -> None:
        """Create the scrolling leaderboard image."""
        try:
            leaderboard_image = self.image_renderer.create_leaderboard_image(self.leaderboard_data)
            
            if leaderboard_image:
                # Set up scroll helper with the image (properly initializes cached_array and state)
                self.scroll_helper.set_scrolling_image(leaderboard_image)
                # Dynamic duration is automatically calculated by set_scrolling_image()
                self._cycle_complete = False
                
                self.logger.info(f"Created leaderboard image: {leaderboard_image.width}x{leaderboard_image.height}")
                self.logger.info(f"Dynamic duration: {self.scroll_helper.get_dynamic_duration()}s")
            else:
                self.logger.error("Failed to create leaderboard image")
                self.scroll_helper.clear_cache()
                
        except Exception as e:
            self.logger.error(f"Error creating leaderboard image: {e}")
            self.scroll_helper.clear_cache()
    
    def _display_fallback_message(self) -> None:
        """Display a fallback message when no data is available."""
        try:
            width = self.display_width
            height = self.display_height
            
            image = Image.new('RGB', (width, height), (0, 0, 0))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            
            text = "No Leaderboard Data"
            # Use default font if available
            try:
                font = self.image_renderer.fonts['medium']
            except (KeyError, AttributeError):
                from PIL import ImageFont
                font = ImageFont.load_default()
            
            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            x = (width - text_width) // 2
            y = (height - text_height) // 2
            
            draw.text((x, y), text, font=font, fill=(255, 255, 255))
            
            self.display_manager.image = image
            self.display_manager.update_display()
            
        except Exception as e:
            self.logger.error(f"Error displaying fallback message: {e}")

    def _load_dynamic_duration_settings(self, dynamic_value: Any) -> Dict[str, Any]:
        """Normalize dynamic duration configuration with backward compatibility."""
        defaults = {
            'enabled': True,
            'min_duration_seconds': 45,
            'max_duration_seconds': 600,
            'buffer_ratio': 0.1,
            'controller_cap_seconds': 600,
        }
        settings = defaults.copy()

        if isinstance(dynamic_value, dict):
            settings['enabled'] = bool(dynamic_value.get('enabled', settings['enabled']))
            settings['min_duration_seconds'] = self._safe_int(
                dynamic_value.get('min_duration_seconds', dynamic_value.get('min_duration')),
                settings['min_duration_seconds'],
                min_value=10,
            )
            settings['max_duration_seconds'] = self._safe_int(
                dynamic_value.get('max_duration_seconds', dynamic_value.get('max_duration')),
                settings['max_duration_seconds'],
                min_value=30,
            )
            settings['buffer_ratio'] = self._safe_float(
                dynamic_value.get('buffer_ratio', dynamic_value.get('duration_buffer')),
                settings['buffer_ratio'],
                min_value=0.0,
                max_value=1.0,
            )
            settings['controller_cap_seconds'] = self._safe_int(
                dynamic_value.get('controller_cap_seconds', dynamic_value.get('max_display_time')),
                settings['controller_cap_seconds'],
                min_value=60,
            )
        elif isinstance(dynamic_value, bool):
            settings['enabled'] = dynamic_value
        elif dynamic_value is not None:
            try:
                settings['enabled'] = bool(dynamic_value)
            except (TypeError, ValueError):
                self.logger.debug("Unrecognized dynamic_duration value: %s", dynamic_value)

        # Legacy top-level overrides for existing configs
        legacy_overrides = {
            'min_duration': ('min_duration_seconds', self._safe_int, {'min_value': 10}),
            'max_duration': ('max_duration_seconds', self._safe_int, {'min_value': 30}),
            'duration_buffer': ('buffer_ratio', self._safe_float, {'min_value': 0.0, 'max_value': 1.0}),
            'max_display_time': ('controller_cap_seconds', self._safe_int, {'min_value': 60}),
        }

        for legacy_key, (target_key, converter, kwargs) in legacy_overrides.items():
            legacy_value = self.global_config.get(legacy_key)
            if legacy_value is not None:
                settings[target_key] = converter(legacy_value, settings[target_key], **kwargs)

        if settings['max_duration_seconds'] < settings['min_duration_seconds']:
            settings['max_duration_seconds'] = settings['min_duration_seconds']
        if settings['controller_cap_seconds'] < settings['max_duration_seconds']:
            settings['controller_cap_seconds'] = settings['max_duration_seconds']

        return settings

    @staticmethod
    def _safe_int(value: Any, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
        """Safely convert a value to int, enforcing optional bounds."""
        try:
            result = int(value)
        except (TypeError, ValueError):
            return default

        if min_value is not None:
            result = max(min_value, result)
        if max_value is not None:
            result = min(max_value, result)
        return result

    @staticmethod
    def _safe_float(value: Any, default: float, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
        """Safely convert a value to float, enforcing optional bounds."""
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default

        if min_value is not None:
            result = max(min_value, result)
        if max_value is not None:
            result = min(max_value, result)
        return result

    def supports_dynamic_duration(self) -> bool:
        """Indicate whether dynamic duration is active for this plugin."""
        return self.dynamic_duration_enabled

    def get_dynamic_duration_cap(self) -> Optional[float]:
        """Provide dynamic duration cap value for the display controller."""
        if not self.dynamic_duration_enabled:
            return None
        return float(self.dynamic_duration_cap) if self.dynamic_duration_cap else None

    def reset_cycle_state(self) -> None:
        """Reset scrolling state when the display controller restarts duration timing."""
        super().reset_cycle_state()
        self._cycle_complete = False
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()

    def is_cycle_complete(self) -> bool:
        """Report whether the scrolling cycle has completed at least once."""
        if not self.dynamic_duration_enabled:
            return True
        # In continuous loop mode, never report completion so the display
        # controller keeps this plugin active until its duration expires
        if self.loop:
            return False
        return self._cycle_complete
    
    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """
        Calculate the expected cycle duration based on content width and scroll speed.
        
        This implements dynamic duration scaling where:
        - Duration is calculated from total scroll distance and scroll speed
        - Includes buffer time for smooth cycling
        - Respects min/max duration limits
        
        Args:
            display_mode: The display mode (unused for leaderboard as it has a single mode)
        
        Returns:
            Calculated duration in seconds, or None if dynamic duration is disabled or not available
        """
        # display_mode is unused but kept for API consistency with other plugins
        _ = display_mode
        if not self.dynamic_duration_enabled:
            return None
        
        # Check if we have a cached image with calculated duration
        if self.scroll_helper and self.scroll_helper.cached_image:
            try:
                dynamic_duration = self.scroll_helper.get_dynamic_duration()
                if dynamic_duration and dynamic_duration > 0:
                    self.logger.debug(
                        "get_cycle_duration() returning calculated duration: %.1fs",
                        dynamic_duration
                    )
                    return float(dynamic_duration)
            except Exception as e:
                self.logger.warning(
                    "Error getting dynamic duration from scroll helper: %s",
                    e
                )
        
        # If no cached image yet, return None (will be calculated when image is created)
        self.logger.debug("get_cycle_duration() returning None (no cached image yet)")
        return None
    
    def get_display_duration(self) -> float:
        """Get display duration from config or dynamic calculation."""
        if self.dynamic_duration_enabled and self.scroll_helper.cached_image:
            return float(self.scroll_helper.get_dynamic_duration())
        return float(self.display_duration)
    
    def set_scroll_speed(self, speed: float) -> None:
        """Set the scroll speed (pixels per frame, 0.5-5.0)."""
        # Clamp to valid range
        self.scroll_speed = max(0.5, min(5.0, speed))
        self.logger.info(f"Scroll speed set to: {self.scroll_speed} pixels/frame")
        
        # Update ScrollHelper based on current mode
        if hasattr(self.scroll_helper, 'frame_based_scrolling') and self.scroll_helper.frame_based_scrolling:
            # Frame-based mode: set pixels per frame directly
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            # Log effective pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s")
        else:
            # Time-based mode: convert to pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.scroll_helper.set_scroll_speed(pixels_per_second)
    
    def set_scroll_delay(self, delay: float) -> None:
        """Set the scroll delay (seconds between frames, 0.001-0.1)."""
        # Clamp to valid range
        self.scroll_delay = max(0.001, min(0.1, delay))
        self.logger.info(f"Scroll delay set to: {self.scroll_delay}s")
        
        # Update ScrollHelper
        self.scroll_helper.set_scroll_delay(self.scroll_delay)
        
        # Recalculate pixels per second if in time-based mode
        if hasattr(self.scroll_helper, 'frame_based_scrolling') and self.scroll_helper.frame_based_scrolling:
            # Frame-based mode: log effective pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s ({self.scroll_speed} px/frame at {1.0/self.scroll_delay:.0f} FPS)")
        else:
            # Time-based mode: recalculate pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.scroll_helper.set_scroll_speed(pixels_per_second)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        
        leagues_config = {}
        for league_key in self.league_config.get_enabled_leagues():
            league_config = self.league_config.get_league_config(league_key)
            if league_config:
                leagues_config[league_key] = {
                    'enabled': True,
                    'top_teams': league_config.get('top_teams', 10)
                }
        
        info.update({
            'total_teams': sum(len(d['teams']) for d in self.leaderboard_data),
            'enabled_leagues': self.league_config.get_enabled_leagues(),
            'last_update': self.last_update,
            'display_duration': self.get_display_duration(),
            'scroll_speed': self.scroll_speed,
            'dynamic_duration': self.dynamic_duration_enabled,
            'dynamic_duration_settings': self.dynamic_duration_settings,
            'dynamic_duration_cap': self.dynamic_duration_cap,
            'min_duration': self.min_duration,
            'max_duration': self.max_duration,
            'leagues_config': leagues_config,
            'scroll_info': self.scroll_helper.get_scroll_info() if self.scroll_helper else None
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.leaderboard_data = []
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        self.logger.info("Leaderboard plugin cleaned up")
