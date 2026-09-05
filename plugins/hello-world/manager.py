"""
Hello World Plugin

A simple test plugin that displays a customizable greeting message
on the LED matrix. Used to demonstrate and test the plugin system.
"""

from src.plugin_system.base_plugin import BasePlugin
import time
from datetime import datetime
import os

try:
    import freetype
except ImportError:
    freetype = None


class HelloWorldPlugin(BasePlugin):
    """
    Simple Hello World plugin for LEDMatrix.
    
    Displays a customizable greeting message with the current time.
    Demonstrates basic plugin functionality.
    """

    # (family, size_px) for each registered element. Kept in one place so the
    # register_manager_font() call and the resolve_font() lookup cannot drift:
    # resolve_font takes the family and size the element was registered with,
    # and a mismatch there is silent.
    MESSAGE_FONT = ("press_start", 10)
    TIME_FONT = ("press_start", 8)

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        """Initialize the Hello World plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Plugin-specific configuration
        self.message = config.get('message', 'Hello, World!')
        self.show_time = config.get('show_time', True)
        self.color = tuple(config.get('color', [255, 255, 255]))
        self.time_color = tuple(config.get('time_color', [0, 255, 255]))

        # Load the 6x9 BDF font
        self._load_font()

        # State
        self.last_update = None
        self.current_time_str = ""

        self.logger.info(f"Hello World plugin initialized with message: '{self.message}'")

        # Register fonts
        self._register_fonts()

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Message font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.message",
                family=self.MESSAGE_FONT[0],
                size_px=self.MESSAGE_FONT[1],
                color=self.color
            )

            # Time font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.time",
                family=self.TIME_FONT[0],
                size_px=self.TIME_FONT[1],
                color=self.time_color
            )

            self.logger.info("Hello World fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def _load_font(self):
        """Load the 6x9 BDF font for text rendering."""
        if freetype is None:
            self.logger.warning("freetype not available, font rendering disabled")
            self.bdf_font = None
            return

        try:
            font_path = "assets/fonts/6x9.bdf"
            if not os.path.exists(font_path):
                self.logger.error(f"Font file not found: {font_path}")
                self.bdf_font = None
                return

            self.bdf_font = freetype.Face(font_path)
            self.logger.info(f"6x9 BDF font loaded successfully from {font_path}")
        except Exception as e:
            self.logger.error(f"Failed to load 6x9 BDF font: {e}")
            self.bdf_font = None

    def update(self):
        """
        Update plugin data.
        
        For this simple plugin, we just update the current time string.
        In a real plugin, this would fetch data from APIs, databases, etc.
        """
        try:
            self.last_update = time.time()
            
            if self.show_time:
                now = datetime.now()
                new_time_str = now.strftime("%I:%M %p")
                
                # Only log if the time actually changed (reduces spam from sub-minute updates)
                if new_time_str != self.current_time_str:
                    self.current_time_str = new_time_str
                    # Only log time changes occasionally
                    if not hasattr(self, '_last_time_log') or time.time() - self._last_time_log > 60:
                        self.logger.info(f"Time updated: {self.current_time_str}")
                        self._last_time_log = time.time()
                else:
                    self.current_time_str = new_time_str
                
        except Exception as e:
            self.logger.error(f"Error during update: {e}", exc_info=True)
    
    def display(self, force_clear=False):
        """
        Render the plugin display.
        
        Displays the configured message and optionally the current time.
        """
        try:
            # Clear display if requested
            if force_clear:
                self.display_manager.clear()
            
            # Get display dimensions
            width = self.display_manager.width
            height = self.display_manager.height
            
            # Get fonts from font manager
            message_font = None
            time_font = None

            try:
                if hasattr(self.plugin_manager, 'font_manager'):
                    font_manager = self.plugin_manager.font_manager
                    # resolve_font() is the accessor for a registered element --
                    # it honours user overrides and takes the same (family,
                    # size_px) the element was registered with. get_font() is
                    # the lower-level family lookup and needs a family name plus
                    # a size; calling it with an element key and no size raised
                    # TypeError on every frame, so this whole branch was dead
                    # and the bundled BDF was always used instead.
                    message_font = font_manager.resolve_font(
                        f"{self.plugin_id}.message", self.MESSAGE_FONT[0],
                        self.MESSAGE_FONT[1], plugin_id=self.plugin_id)
                    time_font = font_manager.resolve_font(
                        f"{self.plugin_id}.time", self.TIME_FONT[0],
                        self.TIME_FONT[1], plugin_id=self.plugin_id)
            except Exception as e:
                self.logger.warning(f"Error getting fonts from font manager: {e}")

            # draw_text treats x as the LEFT edge unless centered=True is
            # passed, so x=width // 2 alone starts the text at the midpoint and
            # runs it off the right. Passing centered=True makes x the centre,
            # which is what the layout below assumes.
            if self.show_time:
                # Display message at top, time at bottom
                message_y = height // 3
                time_y = (2 * height) // 3

                # Draw the greeting message. The font manager's face is used
                # when there is one, and the bundled BDF otherwise -- but the
                # configured colour is passed either way. Selecting the font in
                # a branch that also dropped `color` is how a custom colour
                # silently stopped applying on any install that has a font
                # manager.
                self.display_manager.draw_text(
                    self.message,
                    x=width // 2,
                    y=message_y,
                    color=self.color,
                    font=message_font or self.bdf_font,
                    centered=True
                )

                # Draw the current time
                if self.current_time_str:
                    self.display_manager.draw_text(
                        self.current_time_str,
                        x=width // 2,
                        y=time_y,
                        color=self.time_color,
                        font=time_font or self.bdf_font,
                        centered=True
                    )
            else:
                # Message only, on the vertical centre line
                self.display_manager.draw_text(
                    self.message,
                    x=width // 2,
                    y=height // 2,
                    color=self.color,
                    font=message_font or self.bdf_font,
                    centered=True
                )
            
            # Update the physical display
            self.display_manager.update_display()
                
        except Exception as e:
            self.logger.error(f"Error during display: {e}", exc_info=True)
            # Show error message on display
            try:
                self.display_manager.clear()
                self.display_manager.draw_text(
                    "Error!",
                    x=width // 2,
                    y=height // 2,
                    color=(255, 0, 0),
                    font=self.bdf_font
                )
                self.display_manager.update_display()
            except Exception:
                pass  # If we can't even show error, just log it
    
    def validate_config(self):
        """
        Validate plugin configuration.
        
        Ensures the configuration values are valid.
        """
        # Call parent validation
        if not super().validate_config():
            return False
        
        # Validate message
        if 'message' in self.config:
            if not isinstance(self.config['message'], str):
                self.logger.error("'message' must be a string")
                return False
            if len(self.config['message']) > 50:
                self.logger.warning("'message' is very long, may not fit on display")
        
        # Validate colors
        for color_key in ['color', 'time_color']:
            if color_key in self.config:
                color = self.config[color_key]
                if not isinstance(color, (list, tuple)) or len(color) != 3:
                    self.logger.error(f"'{color_key}' must be an RGB array [R, G, B]")
                    return False
                if not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
                    self.logger.error(f"'{color_key}' values must be integers 0-255")
                    return False
        
        # Validate show_time
        if 'show_time' in self.config:
            if not isinstance(self.config['show_time'], bool):
                self.logger.error("'show_time' must be a boolean")
                return False
        
        self.logger.info("Configuration validated successfully")
        return True
    
    def get_info(self):
        """
        Return plugin information for web UI.
        """
        info = super().get_info()
        info['message'] = self.message
        info['show_time'] = self.show_time
        info['last_update'] = self.last_update
        return info
    
    def cleanup(self):
        """
        Cleanup resources when plugin is unloaded.
        """
        self.logger.info("Cleaning up Hello World plugin")
        super().cleanup()

