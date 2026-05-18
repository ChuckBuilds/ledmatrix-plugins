"""
7-Segment Clock Plugin for LEDMatrix

Displays a retro-style 7-segment clock with configurable time formats
and customizable colors.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import pytz
from PIL import Image

from src.plugin_system.base_plugin import BasePlugin


class SevenSegmentClockPlugin(BasePlugin):
    """7-segment clock plugin with customizable colors."""

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager: Any,
        cache_manager: Any,
        plugin_manager: Any,
    ) -> None:
        """Initialize the 7-segment clock plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Get plugin directory for asset loading
        self.plugin_dir = Path(__file__).parent
        self.assets_dir = self.plugin_dir / "assets" / "images"

        # Load configuration
        self.is_24_hour_format = config.get("is_24_hour_format", True)
        self.has_leading_zero = config.get("has_leading_zero", False)
        self.has_flashing_separator = config.get("has_flashing_separator", True)
        self.color = self._hex_to_rgb(config.get("color", "#FFFFFF"))
        self.digit_spacing = config.get("digit_spacing", 2)  # Pixels between digits

        # Initialize timezone (inherits from main config if not specified)
        self._init_timezone()

        # Load digit and separator images
        self.number_images = self._load_number_images()
        self.separator_image = self._load_separator_image()

        # State variables (updated in update(), used in display())
        self.current_time: Optional[datetime] = None
        self.last_displayed_time_str: Optional[str] = None
        self.first_display: bool = True

        # Image dimensions (from loaded images)
        self.digit_width = 13
        self.digit_height = 32
        self.separator_width = 4
        self.separator_height = 14

        self.logger.info("7-segment clock plugin initialized")

    def _init_timezone(self) -> None:
        """Initialize timezone from plugin config, main config, or system default."""
        # First check plugin-specific config
        location_config = self.config.get("location", {})
        timezone_str = location_config.get("timezone") if isinstance(location_config, dict) else None
        
        # If not in plugin config, try to get from main LEDMatrix config
        if not timezone_str:
            timezone_str = self._get_global_timezone()
        
        # Fallback to UTC if still not found
        if not timezone_str:
            timezone_str = "UTC"
        
        try:
            self.timezone = pytz.timezone(timezone_str)
            self.logger.debug(f"Using timezone: {timezone_str}")
        except pytz.exceptions.UnknownTimeZoneError:
            self.logger.warning(f"Unknown timezone '{timezone_str}', using UTC")
            self.timezone = pytz.UTC
    
    def _get_global_timezone(self) -> str:
        """Get the global timezone from the main LEDMatrix config."""
        try:
            # Access the main config through the plugin manager's config_manager
            if hasattr(self.plugin_manager, 'config_manager') and self.plugin_manager.config_manager:
                main_config = self.plugin_manager.config_manager.load_config()
                return main_config.get('timezone', 'UTC')
        except Exception as e:
            self.logger.debug(f"Could not load timezone from main config: {e}")
        return None

    def _load_number_images(self) -> Dict[int, Image.Image]:
        """Load all number digit images (0-9)."""
        images = {}
        for i in range(10):
            image_path = self.assets_dir / f"number_{i}.png"
            try:
                if image_path.exists():
                    images[i] = Image.open(image_path).convert("RGBA")
                    self.logger.debug(f"Loaded number image: {i}")
                else:
                    self.logger.warning(f"Number image not found: {image_path}")
            except Exception as e:
                self.logger.error(f"Error loading number image {i}: {e}")
        
        if len(images) != 10:
            self.logger.error(f"Only loaded {len(images)}/10 number images")
        
        return images

    def _load_separator_image(self) -> Optional[Image.Image]:
        """Load the separator (colon) image."""
        image_path = self.assets_dir / "separator.png"
        try:
            if image_path.exists():
                image = Image.open(image_path).convert("RGBA")
                self.logger.debug("Loaded separator image")
                return image
            else:
                self.logger.warning(f"Separator image not found: {image_path}")
                return None
        except Exception as e:
            self.logger.error(f"Error loading separator image: {e}")
            return None

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color string to RGB tuple."""
        # Remove # if present
        hex_color = hex_color.lstrip("#")
        
        # Handle 3-digit hex (e.g., #FFF -> #FFFFFF)
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        
        # Convert to RGB
        try:
            return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        except (ValueError, IndexError):
            self.logger.warning(f"Invalid hex color '{hex_color}', using white")
            return (255, 255, 255)

    def _rgb_to_hex(self, r: int, g: int, b: int) -> str:
        """Convert RGB tuple to hex color string."""
        return f"#{r:02x}{g:02x}{b:02x}"

    def _format_time(self, dt: datetime) -> Tuple[str, bool]:
        """
        Format time string based on configuration.

        Args:
            dt: Datetime object

        Returns:
            Tuple of (time_string, separator_visible)
            - time_string: Formatted time (e.g., "12:34" or "09:05")
            - separator_visible: Whether separator should be visible (for flashing)
        """
        if self.is_24_hour_format:
            hour_str = dt.strftime("%H")
        else:
            hour_str = dt.strftime("%I")  # 12-hour format with leading zero
            if not self.has_leading_zero and hour_str[0] == "0":
                hour_str = hour_str[1:]  # Remove leading zero
        
        if not self.has_leading_zero and self.is_24_hour_format and hour_str[0] == "0":
            hour_str = hour_str[1:]  # Remove leading zero for 24-hour format too

        minute_str = dt.strftime("%M")

        # Determine separator visibility for flashing
        separator_visible = True
        if self.has_flashing_separator:
            # Flash on even seconds (separator visible on 0, 2, 4, etc.)
            separator_visible = (dt.second % 2) == 0

        return f"{hour_str}:{minute_str}", separator_visible

    def _render_digit(
        self, digit: int, color: Tuple[int, int, int], scale: float = 1.0
    ) -> Optional[Image.Image]:
        """
        Render a single digit with the specified color.

        Args:
            digit: Digit to render (0-9)
            color: RGB color tuple
            scale: Scale factor to apply to the image (default: 1.0)

        Returns:
            PIL Image with colored digit, or None if error
        """
        if digit not in self.number_images:
            self.logger.warning(f"Digit image not available: {digit}")
            return None

        # Get the base image (transparent foreground on black background)
        base_image = self.number_images[digit].copy()

        # Create a colored version with transparent background
        # The images have white/colored pixels for lit segments on transparent/black background
        colored_image = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
        
        # Apply color to visible pixels (non-transparent pixels that represent lit segments)
        for x in range(base_image.width):
            for y in range(base_image.height):
                pixel = base_image.getpixel((x, y))
                if len(pixel) == 4:  # RGBA
                    r, g, b, a = pixel
                    # If pixel has any alpha and is not pure black, it's a lit segment
                    # Apply the configured color to lit segments
                    if a > 0 and (r, g, b) != (0, 0, 0):
                        # This is a lit segment - apply the configured color with full opacity
                        colored_image.putpixel((x, y), (*color, 255))
                    else:
                        # Black or transparent pixel - keep fully transparent
                        colored_image.putpixel((x, y), (0, 0, 0, 0))
                else:
                    # Not RGBA format - convert and handle
                    if pixel != (0, 0, 0):  # Not black
                        colored_image.putpixel((x, y), (*color, 255))
                    else:
                        colored_image.putpixel((x, y), (0, 0, 0, 0))

        # Scale the image if needed
        if scale != 1.0:
            new_width = int(colored_image.width * scale)
            new_height = int(colored_image.height * scale)
            try:
                # Try new PIL API first
                colored_image = colored_image.resize(
                    (new_width, new_height), Image.Resampling.LANCZOS
                )
            except AttributeError:
                # Fall back to old PIL API
                colored_image = colored_image.resize(
                    (new_width, new_height), Image.LANCZOS
                )

        return colored_image

    def _render_separator(
        self, color: Tuple[int, int, int], scale: float = 1.0
    ) -> Optional[Image.Image]:
        """
        Render the separator (colon) with the specified color.

        Args:
            color: RGB color tuple
            scale: Scale factor to apply to the image (default: 1.0)

        Returns:
            PIL Image with colored separator, or None if error
        """
        if self.separator_image is None:
            return None

        # Similar to digit rendering
        base_image = self.separator_image.copy()
        colored_image = Image.new("RGBA", base_image.size, (0, 0, 0, 0))

        for x in range(base_image.width):
            for y in range(base_image.height):
                pixel = base_image.getpixel((x, y))
                if len(pixel) == 4:  # RGBA
                    r, g, b, a = pixel
                    # If pixel has any alpha and is not pure black, it's a lit segment
                    if a > 0 and (r, g, b) != (0, 0, 0):
                        # This is a lit segment - apply the configured color with full opacity
                        colored_image.putpixel((x, y), (*color, 255))
                    else:
                        # Black or transparent pixel - keep fully transparent
                        colored_image.putpixel((x, y), (0, 0, 0, 0))
                else:
                    # Not RGBA format - convert and handle
                    if pixel != (0, 0, 0):  # Not black
                        colored_image.putpixel((x, y), (*color, 255))
                    else:
                        colored_image.putpixel((x, y), (0, 0, 0, 0))

        # Scale the image if needed
        if scale != 1.0:
            new_width = int(colored_image.width * scale)
            new_height = int(colored_image.height * scale)
            try:
                # Try new PIL API first
                colored_image = colored_image.resize(
                    (new_width, new_height), Image.Resampling.LANCZOS
                )
            except AttributeError:
                # Fall back to old PIL API
                colored_image = colored_image.resize(
                    (new_width, new_height), Image.LANCZOS
                )

        return colored_image

    def update(self) -> None:
        """Update current time."""
        try:
            # Get current time in configured timezone
            now_utc = datetime.now(pytz.UTC)
            self.current_time = now_utc.astimezone(self.timezone)

            self.logger.debug(
                f"Updated: time={self.current_time.strftime('%H:%M:%S')}"
            )

        except Exception as e:
            self.logger.error(f"Error in update(): {e}", exc_info=True)
            # Fallback to current time
            self.current_time = datetime.now(self.timezone)

    def _calculate_scale_factor(
        self, display_width: int, display_height: int, digits: list
    ) -> float:
        """
        Calculate the optimal scale factor to fit the clock on the display.

        Args:
            display_width: Display width in pixels
            display_height: Display height in pixels
            digits: List of digits/separators to display

        Returns:
            Scale factor (1.0 = no scaling, >1.0 = scale up, <1.0 = scale down)
        """
        # Calculate base width needed for the time string
        base_width = 0
        for item in digits:
            if item == ":":
                base_width += self.separator_width
            elif item is not None:
                base_width += self.digit_width

        base_height = self.digit_height

        # Calculate scale factors for width and height
        # Leave some padding (5% on each side = 90% of display)
        available_width = display_width * 0.9
        available_height = display_height * 0.9

        scale_width = available_width / base_width if base_width > 0 else 1.0
        scale_height = available_height / base_height if base_height > 0 else 1.0

        # Use the smaller scale to ensure everything fits
        scale = min(scale_width, scale_height)

        # Don't scale down below 0.5x or up beyond 3x to maintain readability
        scale = max(0.5, min(3.0, scale))

        return scale

    def display(self, force_clear: bool = False) -> None:
        """Render the 7-segment clock display."""
        try:
            # Use cached time and color from update()
            if self.current_time is None:
                self.update()

            # Format time string
            time_str, separator_visible = self._format_time(self.current_time)
            
            # Check if time has changed (only compare HH:MM, not seconds)
            time_changed = (time_str != self.last_displayed_time_str)
            
            # Clear display on first display, force_clear, or when time changes
            should_clear = self.first_display or force_clear or time_changed
            
            if should_clear:
                self.display_manager.clear()
                if self.first_display:
                    self.first_display = False
                if time_changed:
                    self.last_displayed_time_str = time_str

            # Get display dimensions
            display_width = self.display_manager.width
            display_height = self.display_manager.height

            # Calculate total width of time display
            # Always include separator position to ensure we can clear it when hidden
            digits = []
            for char in time_str:
                if char == ":":
                    # Always include separator position, track visibility separately
                    digits.append(":")
                elif char.isdigit():
                    digits.append(int(char))

            # Safety check: ensure we have at least some digits to display
            if not any(item is not None for item in digits):
                self.logger.warning("No digits to display, skipping render")
                return

            # Calculate optimal scale factor to fit the display
            scale = self._calculate_scale_factor(display_width, display_height, digits)

            # Calculate scaled dimensions
            scaled_digit_width = int(self.digit_width * scale)
            scaled_digit_height = int(self.digit_height * scale)
            scaled_separator_width = int(self.separator_width * scale)
            scaled_separator_height = int(self.separator_height * scale)

            # Calculate total width with scaling and spacing
            # Add spacing between all elements (digits and separators) for uniform spacing
            total_width = 0
            element_count = sum(1 for item in digits if item is not None)
            
            for item in digits:
                if item == ":":
                    total_width += scaled_separator_width
                elif item is not None:
                    total_width += scaled_digit_width
            
            # Add spacing between all elements (not before first or after last)
            # Count gaps between all consecutive elements
            if element_count > 1:
                spacing_gaps = element_count - 1
                total_width += spacing_gaps * int(self.digit_spacing * scale)

            # Calculate starting X position to center the display
            start_x = (display_width - total_width) // 2
            # Center vertically
            start_y = (display_height - scaled_digit_height) // 2

            # Render each digit/separator with scaling and spacing
            # Add uniform spacing between all elements (digits and separators)
            current_x = start_x
            first_element = True
            for item in digits:
                if item is None:
                    continue
                
                # Add spacing before each element (except the first one) for uniform spacing
                if not first_element:
                    current_x += int(self.digit_spacing * scale)
                first_element = False
                if item == ":":
                    # Always paste something in separator position to clear old pixels
                    paste_y = start_y + (scaled_digit_height - scaled_separator_height) // 2
                    
                    if separator_visible and self.separator_image:
                        # Render and paste visible separator
                        sep_img = self._render_separator(self.color, scale)
                        if sep_img:
                            self.display_manager.image.paste(
                                sep_img, (current_x, paste_y), sep_img
                            )
                    else:
                        # Clear separator area by pasting a black image
                        # Create a black RGB image (not RGBA) to fully overwrite old pixels
                        clear_img = Image.new("RGB", (scaled_separator_width, scaled_separator_height), (0, 0, 0))
                        self.display_manager.image.paste(
                            clear_img, (current_x, paste_y)
                        )
                    
                    current_x += scaled_separator_width
                else:
                    # Render digit
                    digit_img = self._render_digit(item, self.color, scale)
                    if digit_img:
                        # Paste onto display image with alpha blending
                        self.display_manager.image.paste(
                            digit_img, (current_x, start_y), digit_img
                        )
                        current_x += scaled_digit_width

            # Update the display
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error in display(): {e}", exc_info=True)
            # Show error on display
            self.display_manager.clear()
            self.display_manager.draw_text(
                "Clock Error",
                x=10,
                y=10,
                color=(255, 0, 0)
            )
            self.display_manager.update_display()

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        # Check color
        color = self.config.get("color", "#FFFFFF")
        if not isinstance(color, str) or not color.startswith("#"):
            self.logger.warning("color should be a hex color (e.g., #FFFFFF)")

        # Check timezone if location config is provided (optional - will inherit from main config if not specified)
        location = self.config.get("location", {})
        if isinstance(location, dict) and "timezone" in location:
            timezone_str = location.get("timezone")
            try:
                pytz.timezone(timezone_str)
            except pytz.exceptions.UnknownTimeZoneError:
                self.logger.warning(f"Unknown timezone '{timezone_str}', will fall back to main config or UTC")

        return True

