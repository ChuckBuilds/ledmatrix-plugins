"""
Simple Clock Plugin for LEDMatrix

Displays current time and date with customizable formatting and colors.
Migrated from the original clock.py manager as a plugin example.

API Version: 1.0.0
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Tuple
from src.plugin_system.base_plugin import BasePlugin

try:
    import pytz
except ImportError:
    pytz = None


class SimpleClock(BasePlugin):
    """
    Simple clock plugin that displays current time and date.

    Configuration options:
        timezone (str): Timezone for display (default: UTC)
        time_format (str): 12h or 24h format (default: 12h)
        show_seconds (bool): Show seconds in time (default: False)
        show_date (bool): Show date below time (default: True)
        date_format (str): Date format (default: MM/DD/YYYY)
        time_color (list): RGB color for time [R, G, B] (default: [255, 255, 255])
        date_color (list): RGB color for date [R, G, B] (default: [255, 128, 64])
        ampm_color (list): RGB color for AM/PM [R, G, B] (default: [255, 255, 128])
        position (dict): X,Y position for display (default: 0,0)
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the clock plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Clock-specific configuration
        # Use plugin-specific timezone, or fall back to global timezone, or default to UTC
        self.timezone_str = config.get('timezone') or self._get_global_timezone() or 'UTC'
        self.time_format = config.get('time_format', '12h')
        self.show_seconds = config.get('show_seconds', False)
        self.show_date = config.get('show_date', True)
        self.date_format = config.get('date_format', 'MM/DD/YYYY')

        # Colors
        self.time_color = tuple(config.get('time_color', [255, 255, 255]))
        self.date_color = tuple(config.get('date_color', [255, 128, 64]))
        self.ampm_color = tuple(config.get('ampm_color', [255, 255, 128]))

        # Position - handle both dict and legacy string/invalid formats
        position = config.get('position', {'x': 0, 'y': 0})
        if isinstance(position, dict):
            self.pos_x = position.get('x', 0)
            self.pos_y = position.get('y', 0)
        else:
            # Fallback for invalid/legacy position format
            self.logger.warning(f"Invalid position format: {type(position)}. Using defaults (0, 0)")
            self.pos_x = 0
            self.pos_y = 0

        # Get timezone
        self.timezone = self._get_timezone()

        # Track last display for optimization
        self.last_time_str = None
        self.last_date_str = None

        self.logger.info(f"Clock plugin initialized for timezone: {self.timezone_str}")

    def _get_global_timezone(self) -> str:
        """Get the global timezone from the main config."""
        try:
            # Access the main config through the plugin manager's config_manager
            if hasattr(self.plugin_manager, 'config_manager') and self.plugin_manager.config_manager:
                main_config = self.plugin_manager.config_manager.load_config()
                return main_config.get('timezone', 'UTC')
        except Exception as e:
            self.logger.warning(f"Error getting global timezone: {e}")
        return 'UTC'

    def _get_timezone(self):
        """Get timezone from configuration."""
        if pytz is None:
            self.logger.warning("pytz not available, using UTC timezone only")
            return None

        try:
            return pytz.timezone(self.timezone_str)
        except Exception:
            self.logger.warning(
                f"Invalid timezone '{self.timezone_str}'. Falling back to UTC. "
                "Valid timezones can be found at: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
            )
            return pytz.utc

    def _format_time_12h(self, dt: datetime) -> Tuple[str, str]:
        """Format time in 12-hour format."""
        time_str = dt.strftime("%I:%M")
        if self.show_seconds:
            time_str += dt.strftime(":%S")

        # Remove leading zero from hour
        if time_str.startswith("0"):
            time_str = time_str[1:]

        ampm = dt.strftime("%p")
        return time_str, ampm

    def _format_time_24h(self, dt: datetime) -> str:
        """Format time in 24-hour format."""
        time_str = dt.strftime("%H:%M")
        if self.show_seconds:
            time_str += dt.strftime(":%S")
        return time_str

    def _format_date(self, dt: datetime) -> str:
        """Format date according to configured format."""
        if self.date_format == "MM/DD/YYYY":
            return dt.strftime("%m/%d/%Y")
        elif self.date_format == "DD/MM/YYYY":
            return dt.strftime("%d/%m/%Y")
        elif self.date_format == "YYYY-MM-DD":
            return dt.strftime("%Y-%m-%d")
        else:
            return dt.strftime("%m/%d/%Y")  # fallback

    def update(self) -> None:
        """
        Update clock data.

        For a clock, we don't need to fetch external data, but we can
        prepare the current time for display optimization.
        """
        try:
            # Get current time
            if pytz and self.timezone:
                # Use timezone-aware datetime
                utc_now = datetime.now(pytz.utc)
                local_time = utc_now.astimezone(self.timezone)
            else:
                # Use local system time (no timezone conversion)
                local_time = datetime.now()

            if self.time_format == "12h":
                new_time, new_ampm = self._format_time_12h(local_time)
                # Only log if the time actually changed
                if not hasattr(self, 'current_time') or new_time != self.current_time:
                    if not hasattr(self, '_last_time_log') or time.time() - getattr(self, '_last_time_log', 0) > 60:
                        self.logger.info(f"Clock updated: {new_time} {new_ampm}")
                        self._last_time_log = time.time()
                self.current_time = new_time
                self.current_ampm = new_ampm
            else:
                new_time = self._format_time_24h(local_time)
                if not hasattr(self, 'current_time') or new_time != self.current_time:
                    if not hasattr(self, '_last_time_log') or time.time() - getattr(self, '_last_time_log', 0) > 60:
                        self.logger.info(f"Clock updated: {new_time}")
                        self._last_time_log = time.time()
                self.current_time = new_time

            if self.show_date:
                self.current_date = self._format_date(local_time)

            self.last_update = time.time()

        except Exception as e:
            self.logger.error(f"Error updating clock: {e}")

    def display(self, force_clear: bool = False) -> None:
        """
        Display the clock.

        Args:
            force_clear: If True, clear display before rendering
        """
        try:
            if force_clear:
                self.display_manager.clear()

            # Get display dimensions
            width = self.display_manager.width
            height = self.display_manager.height

            # Center the clock display
            center_x = width // 2
            center_y = height // 2

            # Display time (centered)
            self.display_manager.draw_text(
                self.current_time,
                x=center_x,
                y=center_y - 8,
                color=self.time_color,
                centered=True
            )

            # Display AM/PM indicator (12h format only)
            if self.time_format == "12h" and hasattr(self, 'current_ampm'):
                self.display_manager.draw_text(
                    self.current_ampm,
                    x=center_x + 40,  # Position to the right of time
                    y=center_y - 8,
                    color=self.ampm_color,
                    centered=False
                )

            # Display date (below time, if enabled)
            if self.show_date and hasattr(self, 'current_date'):
                self.display_manager.draw_text(
                    self.current_date,
                    x=center_x,
                    y=center_y + 8,
                    color=self.date_color,
                    centered=True
                )

            # Update the physical display
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying clock: {e}")
            # Show error message on display
            try:
                self.display_manager.clear()
                self.display_manager.draw_text(
                    "Clock Error",
                    x=5, y=15,
                    color=(255, 0, 0)
                )
                self.display_manager.update_display()
            except:
                pass  # If display fails, don't crash

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 15.0)

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        # Call parent validation first
        if not super().validate_config():
            return False

        # Validate timezone
        if pytz is not None:
            try:
                pytz.timezone(self.timezone_str)
            except Exception:
                self.logger.error(f"Invalid timezone: {self.timezone_str}")
                return False
        else:
            self.logger.warning("pytz not available, timezone validation skipped")

        # Validate time format
        if self.time_format not in ["12h", "24h"]:
            self.logger.error(f"Invalid time format: {self.time_format}")
            return False

        # Validate date format
        if self.date_format not in ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD"]:
            self.logger.error(f"Invalid date format: {self.date_format}")
            return False

        # Validate colors
        for color_name, color_value in [
            ("time_color", self.time_color),
            ("date_color", self.date_color),
            ("ampm_color", self.ampm_color)
        ]:
            if not isinstance(color_value, tuple) or len(color_value) != 3:
                self.logger.error(f"Invalid {color_name}: must be RGB tuple")
                return False
            if not all(0 <= c <= 255 for c in color_value):
                self.logger.error(f"Invalid {color_name}: values must be 0-255")
                return False

        return True

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'current_time': getattr(self, 'current_time', None),
            'timezone': self.timezone_str,
            'time_format': self.time_format,
            'show_seconds': self.show_seconds,
            'show_date': self.show_date,
            'date_format': self.date_format
        })
        return info
