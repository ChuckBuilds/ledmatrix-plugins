"""
Simple Clock Plugin for LEDMatrix

Displays current time and date with customizable formatting and colors.
Migrated from the original clock.py manager as a plugin example.

API Version: 1.0.0
"""

import time
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
        timezone (str): Timezone for display (inherits from global config if not specified)
        time_format (str): 12h or 24h format (default: 12h)
        show_seconds (bool): Show seconds in time (default: False)
        show_date (bool): Show date below time (default: True)
        date_format (str): Date format (default: MM/DD/YYYY)
        position (dict): X,Y position for display (default: 0,0)
        customization (dict): Nested configuration for display customization
            - time_text: Font and color settings for time display
            - date_text: Font and color settings for date display
            - ampm_text: Font and color settings for AM/PM indicator
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the clock plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Clock-specific configuration
        # Use plugin-specific timezone, or fall back to global timezone, or default to UTC
        # Handle None/null values from config schema
        plugin_timezone = config.get('timezone')
        if plugin_timezone is None or plugin_timezone == '':
            # No plugin-specific timezone set, inherit from global
            self.timezone_str = self._get_global_timezone() or 'UTC'
        else:
            # Use plugin-specific timezone
            self.timezone_str = plugin_timezone
        self.time_format = config.get('time_format', '12h')
        self.show_seconds = config.get('show_seconds', False)
        self.show_date = config.get('show_date', True)
        self.center_time_with_ampm = config.get('center_time_with_ampm', False)
        self.date_format = config.get('date_format', 'OLD_CLOCK')

        # Colors from nested customization, with fallback to defaults
        def _parse_color(color_value, default):
            if color_value is None:
                return default
            try:
                return tuple(int(c) for c in color_value)
            except (ValueError, TypeError):
                # If parsing fails, return the raw value (as tuple if possible, else raw)
                # This allows validate_config to detect and report the error properly
                # instead of crashing in __init__
                try:
                    return tuple(color_value)
                except TypeError:
                    return default

        customization = config.get('customization', {})
        time_text = customization.get('time_text', {})
        date_text = customization.get('date_text', {})
        ampm_text = customization.get('ampm_text', {})

        self.time_color = _parse_color(time_text.get('text_color'), [255, 255, 255])
        self.date_color = _parse_color(date_text.get('text_color'), [255, 128, 64])
        self.ampm_color = _parse_color(ampm_text.get('text_color'), [255, 255, 128])

        # Position - use flattened keys
        self.pos_x = config.get('position_x', 0)
        self.pos_y = config.get('position_y', 0)

        # Get timezone
        self.timezone = self._get_timezone()

        # Track the last-rendered content so display() knows when it needs to
        # clear the buffer (content changed) versus redraw the identical pixels.
        self.last_time_str = None
        self.last_ampm_str = None
        self.last_date_str = None
        self.last_weekday_str = None

        self.logger.info(f"Clock plugin initialized for timezone: {self.timezone_str}")

    def _get_global_timezone(self) -> str:
        """Get the global timezone from the main config."""
        try:
            # Try plugin_manager's config_manager first
            if hasattr(self.plugin_manager, 'config_manager') and self.plugin_manager.config_manager:
                return self.plugin_manager.config_manager.get_timezone()
            # Fallback to cache_manager's config_manager
            if hasattr(self.cache_manager, 'config_manager') and self.cache_manager.config_manager:
                return self.cache_manager.config_manager.get_timezone()
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

    def _get_ordinal_suffix(self, day: int) -> str:
        """Get the ordinal suffix for a day number (1st, 2nd, 3rd, etc.)."""
        if 10 <= day % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        return suffix

    def _format_date(self, dt: datetime) -> str:
        """Format date according to configured format."""
        if self.date_format == "MM/DD/YYYY":
            return dt.strftime("%m/%d/%Y")
        elif self.date_format == "DD/MM/YYYY":
            return dt.strftime("%d/%m/%Y")
        elif self.date_format == "YYYY-MM-DD":
            return dt.strftime("%Y-%m-%d")
        elif self.date_format == "OLD_CLOCK":
            # Match old clock format: "Month Day" with ordinal suffix (no leading zero on day)
            # This matches the original clock.py: current.strftime(f'%B %-d{day_suffix}')
            day_suffix = self._get_ordinal_suffix(dt.day)
            # Use day integer directly (no leading zero) to match original clock.py format
            return dt.strftime(f'%B {dt.day}{day_suffix}')
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
            
            # Store local_time for date formatting access
            self.current_dt = local_time

            # Get current seconds for comparison
            current_seconds = local_time.second
            
            if self.time_format == "12h":
                new_time, new_ampm = self._format_time_12h(local_time)
                # Store time without seconds for comparison
                if self.show_seconds:
                    # Remove seconds portion for comparison (format: "H:MM:SS" or "H:MM")
                    time_without_seconds = new_time.rsplit(':', 1)[0] if ':' in new_time else new_time
                else:
                    time_without_seconds = new_time
                
                # Only log if the time (without seconds) actually changed
                if not hasattr(self, 'current_time') or time_without_seconds != getattr(self, 'time_without_seconds', ''):
                    if not hasattr(self, '_last_time_log') or time.time() - getattr(self, '_last_time_log', 0) > 60:
                        self.logger.info(f"Clock updated: {new_time} {new_ampm}")
                        self._last_time_log = time.time()
                self.current_time = new_time
                self.time_without_seconds = time_without_seconds
                self.current_ampm = new_ampm
            else:
                new_time = self._format_time_24h(local_time)
                # Store time without seconds for comparison
                if self.show_seconds:
                    # Remove seconds portion for comparison (format: "HH:MM:SS" or "HH:MM")
                    time_without_seconds = new_time.rsplit(':', 1)[0] if ':' in new_time else new_time
                else:
                    time_without_seconds = new_time
                
                if not hasattr(self, 'current_time') or time_without_seconds != getattr(self, 'time_without_seconds', ''):
                    if not hasattr(self, '_last_time_log') or time.time() - getattr(self, '_last_time_log', 0) > 60:
                        self.logger.info(f"Clock updated: {new_time}")
                        self._last_time_log = time.time()
                self.current_time = new_time
                self.time_without_seconds = time_without_seconds

            if self.show_date:
                self.current_date = self._format_date(local_time)
                # Also get weekday for old clock layout
                self.current_weekday = local_time.strftime('%A')
            
            # Store seconds for comparison
            self.current_seconds = current_seconds

            self.last_update = time.time()

        except Exception as e:
            self.logger.error(f"Error updating clock: {e}")

    def display(self, force_clear: bool = False) -> None:
        """
        Display the clock.

        The plugin redraws its full content and pushes it on every call. The
        display buffer is only *cleared* when the on-screen content actually
        changes (e.g. the minute or date rolls over); otherwise the identical
        pixels are drawn in place. Redrawing on every tick — rather than
        returning early on unchanged frames — keeps the panel populated on every
        frame of the core's render loop, which is what prevents the clock from
        periodically flashing.

        Args:
            force_clear: If True, clear display before rendering
        """
        try:
            # Refresh the current time on every render tick.
            self.update()

            # Snapshot the strings we're about to render.
            current_time_str = getattr(self, 'current_time', '')
            current_ampm_str = getattr(self, 'current_ampm', '') if self.time_format == "12h" else ''
            current_date_str = getattr(self, 'current_date', '') if self.show_date else ''
            current_weekday_str = getattr(self, 'current_weekday', '') if (self.show_date and self.date_format == "OLD_CLOCK") else ''

            # Only clear the buffer when the visible content changed. Clearing
            # every tick would blank the panel between the clear and the redraw
            # on cores that push the buffer eagerly, which is the flash we're
            # fixing. When nothing changed we redraw the identical pixels in
            # place, so there is nothing to clear and no flash.
            content_changed = force_clear or (
                current_time_str != self.last_time_str or
                current_ampm_str != getattr(self, 'last_ampm_str', '') or
                current_date_str != self.last_date_str or
                current_weekday_str != getattr(self, 'last_weekday_str', '')
            )

            # Get display dimensions
            width = self.display_manager.width
            height = self.display_manager.height

            # Get font height for dynamic spacing calculations
            font_height = self.display_manager.get_font_height(self.display_manager.small_font)

            # Calculate dynamic positions based on display dimensions
            # Time position: Small fixed offset (4px) plus small percentage for larger displays
            # This keeps time near top on small displays, scales slightly on larger ones
            time_y = max(2, min(4 + int(height * 0.02), int(height * 0.1)))

            if content_changed:
                # Clear the display so stale glyphs (e.g. the old minute) don't
                # ghost underneath the new content.
                self.display_manager.clear()

            # Display time and AM/PM based on alignment toggle
            if self.time_format == "12h" and hasattr(self, 'current_ampm') and self.center_time_with_ampm:
                # Center time and AM/PM together as one block
                # Calculate widths of each component
                time_width = self.display_manager.get_text_width(
                    self.current_time,
                    self.display_manager.small_font
                )
                space_width = self.display_manager.get_text_width(
                    " ",
                    self.display_manager.small_font
                )
                ampm_width = self.display_manager.get_text_width(
                    self.current_ampm,
                    self.display_manager.small_font
                )
                
                # Total width of "Time AM/PM" block
                total_width = time_width + space_width + ampm_width
                
                # Calculate x position to center the entire "Time AM/PM" block
                time_x = (width - total_width) // 2
                
                # Draw time at calculated position
                self.display_manager.draw_text(
                    self.current_time,
                    x=time_x,
                    y=time_y,
                    color=self.time_color,
                    small_font=True
                )
                
                # Draw AM/PM right after time with proper spacing
                ampm_x = time_x + time_width + space_width
                self.display_manager.draw_text(
                    self.current_ampm,
                    x=ampm_x,
                    y=time_y,
                    color=self.ampm_color,
                    small_font=True
                )
            else:
                # Default behavior: center time first, then add AM/PM to the right
                # Draw time (large, centered, near top)
                self.display_manager.draw_text(
                    self.current_time,
                    y=time_y,
                    color=self.time_color,
                    small_font=True
                )

                # Display AM/PM indicator (12h format only) - positioned next to time
                if self.time_format == "12h" and hasattr(self, 'current_ampm'):
                    # Calculate AM/PM position: to the right of centered time
                    # Use the same font that's used for drawing (small_font)
                    time_width = self.display_manager.get_text_width(
                        self.current_time, 
                        self.display_manager.small_font
                    )
                    
                    # Spacing between time and AM/PM: ~2.5% of width, minimum 2px
                    ampm_spacing = max(2, int(width * 0.025))
                    ampm_x = (width + time_width) // 2 + ampm_spacing
                    self.display_manager.draw_text(
                        self.current_ampm,
                        x=ampm_x,
                        y=time_y,  # Align with time
                        color=self.ampm_color,
                        small_font=True
                    )

            # Display date
            if self.show_date and hasattr(self, 'current_date'):
                if self.date_format == "OLD_CLOCK" and hasattr(self, 'current_weekday'):
                    # Calculate date positions dynamically from bottom
                    # This ensures consistent positioning relative to bottom edge
                    # Weekday: ~18px from bottom (scales with display size)
                    weekday_offset = max(18, int(height * 0.28))
                    weekday_y = height - weekday_offset
                    
                    # Date: ~9px from bottom (scales with display size)
                    date_offset = max(9, int(height * 0.14))
                    date_y = height - date_offset
                    
                    # Ensure minimum spacing between lines (at least 1 font height)
                    min_line_spacing = font_height + 1
                    if date_y - weekday_y < min_line_spacing:
                        # Adjust to maintain minimum spacing
                        date_y = weekday_y + min_line_spacing
                        # Don't go past bottom of display
                        if date_y >= height:
                            date_y = height - 1
                    
                    # Weekday on first line
                    self.display_manager.draw_text(
                        self.current_weekday,
                        y=weekday_y,
                        color=self.date_color,
                        small_font=True
                    )
                    # Month and day on second line
                    self.display_manager.draw_text(
                        self.current_date,
                        y=date_y,
                        color=self.date_color,
                        small_font=True
                    )
                else:
                    # Other date formats: single line centered near bottom
                    # Position ~9px from bottom (scales with display size)
                    date_offset = max(9, int(height * 0.14))
                    date_y = height - date_offset
                    self.display_manager.draw_text(
                        self.current_date,
                        y=date_y,
                        color=self.date_color,
                        small_font=True
                    )

            # Push the freshly rendered frame to the panel every tick.
            self.display_manager.update_display()

            # Track what we just displayed so the next tick knows whether the
            # content changed (and therefore whether it needs to clear).
            self.last_time_str = current_time_str
            if self.time_format == "12h":
                self.last_ampm_str = current_ampm_str
            self.last_date_str = current_date_str
            if self.show_date and self.date_format == "OLD_CLOCK":
                self.last_weekday_str = current_weekday_str

            if content_changed:
                display_str = f"{current_time_str} {current_ampm_str}".strip()
                self.logger.debug(f"Clock displayed: {display_str} {current_date_str}")

        except Exception as e:
            self.logger.error(f"Error displaying clock: {e}", exc_info=True)
            # Show error message on display
            try:
                self.display_manager.clear()
                self.display_manager.draw_text(
                    "Clock Error",
                    x=5, y=15,
                    color=(255, 0, 0)
                )
                self.display_manager.update_display()
            except Exception as e:
                self.logger.exception("Fallback display failed: %s", e)

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
        if self.date_format not in ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "OLD_CLOCK"]:
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
            try:
                # Convert to integers and validate range
                color_ints = [int(c) for c in color_value]
                if not all(0 <= c <= 255 for c in color_ints):
                    self.logger.error(f"Invalid {color_name}: values must be 0-255")
                    return False
            except (ValueError, TypeError):
                self.logger.error(f"Invalid {color_name}: values must be numeric")
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
