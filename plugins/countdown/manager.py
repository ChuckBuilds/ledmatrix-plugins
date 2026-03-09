"""
Countdown Plugin for LEDMatrix

Display customizable countdowns with images. Perfect for birthdays, holidays,
events, and special occasions.

Features:
- Multiple countdown entries with individual enable/disable
- Path-based image selection for each countdown
- Configurable fonts, colors, and display settings
- Image on left 1/3rd, text on right 2/3rds layout
- Automatic rotation through enabled countdowns

API Version: 1.0.0
"""

import logging
import os
import time
import uuid
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, date
from PIL import Image, ImageDraw
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class CountdownPlugin(BasePlugin):
    """
    Countdown display plugin for LED matrix.

    Supports multiple countdowns with path-based images, configurable fonts,
    and automatic rotation through enabled entries.

    Configuration options:
        countdowns (list): Array of countdown entries
        font_family (str): Font family for countdown text
        font_size (int): Font size in pixels
        font_color (list): RGB color for countdown value
        name_font_size (int): Font size for countdown name
        name_font_color (list): RGB color for countdown name
        fit_to_display (bool): Auto-fit images to display dimensions
        preserve_aspect_ratio (bool): Preserve aspect ratio when scaling
        background_color (list): RGB background color
        display_duration (float): Display duration per countdown in seconds
        show_expired (bool): Show countdowns that have already passed
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the countdown plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Configuration
        self.fit_to_display = config.get('fit_to_display', True)
        self.preserve_aspect_ratio = config.get('preserve_aspect_ratio', True)
        self.show_expired = config.get('show_expired', False)

        # Handle background_color
        bg_color = config.get('background_color', [0, 0, 0])
        self.background_color = self._parse_color(bg_color, (0, 0, 0))

        # Font configuration
        self.font_family = config.get('font_family', 'press_start')
        self.font_size = config.get('font_size', 8)
        self.font_color = self._parse_color(config.get('font_color', [255, 255, 255]), (255, 255, 255))
        self.name_font_size = config.get('name_font_size', 8)
        self.name_font_color = self._parse_color(config.get('name_font_color', [200, 200, 200]), (200, 200, 200))

        # Countdown entries
        self.countdowns = self._normalize_countdowns(config.get('countdowns', []))

        # Cache signature lets us invalidate image cache when countdown metadata changes.
        self._countdown_signature = self._build_countdown_signature(self.countdowns)

        # Rotation state
        self.current_countdown_index = 0
        self.last_rotation_time = time.time()

        # Cached images
        self.cached_images = {}  # {countdown_id: PIL.Image}

        # Countdown calculations cache
        self.countdown_values = {}  # {countdown_id: {'days': int, 'hours': int, 'minutes': int, 'text': str}}

        self.logger.info(f"Countdown plugin initialized with {len(self.countdowns)} countdown(s)")

        # Register fonts
        self._register_fonts()

    def _parse_color(self, color_value: Any, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Parse color value from config (handles lists, tuples, strings)."""
        if isinstance(color_value, (list, tuple)) and len(color_value) == 3:
            try:
                color_numeric = []
                for c in color_value:
                    if isinstance(c, str):
                        c = int(float(c))
                    elif isinstance(c, float):
                        c = int(c)
                    elif not isinstance(c, int):
                        raise ValueError(f"Invalid color value type: {type(c)}")
                    if not (0 <= c <= 255):
                        raise ValueError(f"Color value {c} out of range 0-255")
                    color_numeric.append(c)
                return tuple(color_numeric)
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Invalid color values: {e}, using default")
                return default
        else:
            self.logger.warning(f"Invalid color type: {type(color_value)}, using default")
            return default

    def _parse_bool(self, value: Any, default: bool = True) -> bool:
        """Parse booleans safely, including common string forms."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("false", "0", "off", "no", ""):
                return False
            if normalized in ("true", "1", "on", "yes"):
                return True
            return default
        if isinstance(value, (int, float)):
            return value != 0
        return bool(value)

    def _generate_unique_countdown_id(self, used_ids: set, preferred_id: str = "") -> str:
        """Return a unique countdown ID, preserving preferred_id when available."""
        candidate = preferred_id.strip()
        if candidate and candidate not in used_ids:
            used_ids.add(candidate)
            return candidate

        base = candidate if candidate else "countdown"
        suffix = 1
        while True:
            if candidate:
                unique_id = f"{base}-{suffix}"
            else:
                unique_id = f"cd_{uuid.uuid4().hex[:12]}"
            if unique_id not in used_ids:
                used_ids.add(unique_id)
                return unique_id
            suffix += 1

    def _normalize_countdowns(self, raw_countdowns: Any) -> List[Dict[str, Any]]:
        """
        Normalize countdown entries for consistent runtime behavior.

        - Ensures list/dict structure
        - Generates unique IDs
        - Parses booleans robustly (including string values)
        - Migrates legacy image array format to image_path
        """
        if not isinstance(raw_countdowns, list):
            self.logger.warning(f"Countdowns is not a list: {type(raw_countdowns)}, defaulting to empty")
            return []

        normalized_countdowns: List[Dict[str, Any]] = []
        incoming_ids = {
            str(item.get("id", "")).strip()
            for item in raw_countdowns
            if isinstance(item, dict)
        }
        incoming_ids.discard("")

        used_ids = set()
        # Include existing runtime IDs to avoid cache key collisions during hot reloads.
        # Exclude IDs present in incoming config so they are not treated as collisions.
        if isinstance(getattr(self, "cached_images", None), dict):
            used_ids.update(
                str(k) for k in self.cached_images.keys()
                if str(k) not in incoming_ids
            )
        if isinstance(getattr(self, "countdown_values", None), dict):
            used_ids.update(
                str(k) for k in self.countdown_values.keys()
                if str(k) not in incoming_ids
            )

        for index, item in enumerate(raw_countdowns):
            if not isinstance(item, dict):
                self.logger.warning(f"Skipping invalid countdown item at index {index}: {item}")
                continue

            normalized = dict(item)
            provided_id = str(normalized.get("id", "")).strip()
            normalized["id"] = self._generate_unique_countdown_id(used_ids, provided_id)
            normalized["enabled"] = self._parse_bool(normalized.get("enabled", True), default=True)

            try:
                normalized["display_order"] = int(normalized.get("display_order", 0))
            except (ValueError, TypeError):
                normalized["display_order"] = 0

            normalized["name"] = str(normalized.get("name", "")).strip()
            normalized["target_date"] = str(normalized.get("target_date", "")).strip()

            image_path = normalized.get("image_path")
            if not image_path:
                legacy_images = normalized.get("image", [])
                if (
                    isinstance(legacy_images, list)
                    and legacy_images
                    and isinstance(legacy_images[0], dict)
                ):
                    image_path = legacy_images[0].get("path")
            normalized["image_path"] = str(image_path).strip() if image_path else ""

            normalized_countdowns.append(normalized)

        normalized_countdowns.sort(key=lambda x: x.get("display_order", 0))
        return normalized_countdowns

    def _build_countdown_signature(self, countdowns: Optional[List[Dict[str, Any]]] = None) -> Tuple[Any, ...]:
        """Build a config signature used to detect cache-relevant changes."""
        if countdowns is None:
            countdowns = self.countdowns
        countdown_items = tuple(
            (
                c.get("id", ""),
                c.get("name", ""),
                c.get("target_date", ""),
                c.get("enabled", True),
                c.get("display_order", 0),
                c.get("image_path", ""),
            )
            for c in countdowns
        )
        return (
            self.fit_to_display,
            self.preserve_aspect_ratio,
            self.background_color,
            self.show_expired,
            countdown_items,
        )

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Countdown value font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.countdown_value",
                family=self.font_family,
                size_px=self.font_size,
                color=self.font_color
            )

            # Countdown name font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.countdown_name",
                family=self.font_family,
                size_px=self.name_font_size,
                color=self.name_font_color
            )

            # Error message font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.error",
                family="press_start",
                size_px=8,
                color=(255, 0, 0)
            )

            self.logger.info("Countdown fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def _resolve_image_path(self, image_path: str) -> Optional[str]:
        """
        Resolve image path to absolute path.
        Handles both absolute paths and relative paths (from project root).
        """
        if not image_path:
            return None

        # If already absolute, check if it exists
        if os.path.isabs(image_path):
            if os.path.exists(image_path):
                return image_path

        # Try relative to current working directory
        if os.path.exists(image_path):
            return os.path.abspath(image_path)

        # Try relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent
        project_path = project_root / image_path
        if project_path.exists():
            return str(project_path)

        return image_path

    def _load_and_scale_image(self, image_path: str, target_width: int, target_height: int) -> Optional[Image.Image]:
        """
        Load and scale an image to fit the target dimensions.

        Args:
            image_path: Path to image file
            target_width: Target width in pixels
            target_height: Target height in pixels

        Returns:
            PIL Image or None if loading fails
        """
        if not image_path:
            return None

        # Resolve path
        resolved_path = self._resolve_image_path(image_path)

        if not resolved_path or not os.path.exists(resolved_path):
            self.logger.warning(f"Image file not found: {image_path} (resolved: {resolved_path})")
            return None

        try:
            # Load the image
            img = Image.open(resolved_path)

            # Convert to RGBA to handle transparency
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            # Calculate target size
            if self.fit_to_display and self.preserve_aspect_ratio:
                target_size = self._calculate_fit_size(img.size, (target_width, target_height))
            elif self.fit_to_display:
                target_size = (target_width, target_height)
            else:
                target_size = img.size

            # Resize image if needed
            if target_size != img.size:
                img = img.resize(target_size, Image.Resampling.LANCZOS)

            # Create canvas with background color
            canvas = Image.new('RGB', (target_width, target_height), self.background_color)

            # Calculate position to center the image
            paste_x = (target_width - img.width) // 2
            paste_y = (target_height - img.height) // 2

            # Handle transparency by compositing
            if img.mode == 'RGBA':
                temp_canvas = Image.new('RGB', (target_width, target_height), self.background_color)
                temp_canvas.paste(img, (paste_x, paste_y), img)
                canvas = temp_canvas
            else:
                canvas.paste(img, (paste_x, paste_y))

            # Close the image file
            img.close()

            self.logger.debug(f"Successfully loaded and scaled image: {image_path}")
            return canvas

        except Exception as e:
            self.logger.error(f"Error loading image {image_path}: {e}")
            return None

    def _calculate_fit_size(self, image_size: Tuple[int, int],
                           display_size: Tuple[int, int]) -> Tuple[int, int]:
        """
        Calculate size to fit image within display bounds while preserving aspect ratio.
        """
        img_width, img_height = image_size
        display_width, display_height = display_size

        # Calculate scaling factor to fit within display
        scale_x = display_width / img_width
        scale_y = display_height / img_height
        scale = min(scale_x, scale_y)

        return (int(img_width * scale), int(img_height * scale))

    def _calculate_time_remaining(self, target_date_str: str) -> Dict[str, Any]:
        """
        Calculate time remaining until target date.

        Args:
            target_date_str: Target date in YYYY-MM-DD format

        Returns:
            Dictionary with days, hours, minutes, is_expired, and formatted text
        """
        try:
            # Parse target date
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            today = date.today()

            # Calculate difference
            delta = target_date - today

            if delta.days < 0:
                # Past date
                return {
                    'days': abs(delta.days),
                    'hours': 0,
                    'minutes': 0,
                    'is_expired': True,
                    'is_today': False,
                    'text': f"{abs(delta.days)}d ago"
                }
            elif delta.days == 0:
                # Today
                return {
                    'days': 0,
                    'hours': 0,
                    'minutes': 0,
                    'is_expired': False,
                    'is_today': True,
                    'text': "TODAY!"
                }
            elif delta.days == 1:
                # Tomorrow
                return {
                    'days': 1,
                    'hours': 0,
                    'minutes': 0,
                    'is_expired': False,
                    'is_today': False,
                    'text': "1 Day"
                }
            else:
                # Future date
                return {
                    'days': delta.days,
                    'hours': 0,
                    'minutes': 0,
                    'is_expired': False,
                    'is_today': False,
                    'text': f"{delta.days} Days"
                }

        except Exception as e:
            self.logger.error(f"Error calculating time remaining for {target_date_str}: {e}")
            return {
                'days': 0,
                'hours': 0,
                'minutes': 0,
                'is_expired': False,
                'is_today': False,
                'text': "Error"
            }

    def _get_enabled_countdowns(self) -> List[Dict[str, Any]]:
        """Get list of enabled countdowns, filtered by show_expired setting."""
        enabled = []
        for countdown in self.countdowns:
            if not countdown.get('enabled', True):
                continue

            # Check if expired
            countdown_id = countdown.get('id')
            if countdown_id in self.countdown_values:
                is_expired = self.countdown_values[countdown_id].get('is_expired', False)
                if is_expired and not self.show_expired:
                    continue

            enabled.append(countdown)

        return enabled

    def _get_current_countdown(self) -> Optional[Dict[str, Any]]:
        """Get the current countdown to display based on rotation."""
        enabled = self._get_enabled_countdowns()

        if not enabled:
            return None

        # Ensure index is within bounds
        if self.current_countdown_index >= len(enabled):
            self.current_countdown_index = 0

        return enabled[self.current_countdown_index]

    def _rotate_to_next_countdown(self) -> None:
        """Rotate to the next enabled countdown."""
        enabled = self._get_enabled_countdowns()

        if not enabled:
            return

        self.current_countdown_index = (self.current_countdown_index + 1) % len(enabled)
        self.last_rotation_time = time.time()
        self.logger.debug(f"Rotated to countdown index {self.current_countdown_index}")

    def update(self) -> None:
        """
        Update countdown calculations.
        Recalculates time remaining for all countdowns.
        """
        try:
            # Recalculate all countdown values
            for countdown in self.countdowns:
                countdown_id = countdown.get('id')
                target_date = countdown.get('target_date')

                if countdown_id and target_date:
                    self.countdown_values[countdown_id] = self._calculate_time_remaining(target_date)

            self.logger.debug(f"Updated {len(self.countdown_values)} countdown values")

        except Exception as e:
            self.logger.error(f"Error updating countdowns: {e}")

    def display(self, force_clear: bool = False) -> None:
        """
        Display the current countdown on the LED matrix.

        Layout: Image on left 1/3rd, text on right 2/3rds

        Args:
            force_clear: If True, clear display before rendering
        """
        # Get current countdown
        current_countdown = self._get_current_countdown()

        if not current_countdown:
            self._display_no_countdowns()
            return

        try:
            # Get display dimensions
            display_width = self.display_manager.matrix.width
            display_height = self.display_manager.matrix.height

            # Calculate layout: left 1/3 for image, right 2/3 for text
            image_width = display_width // 3
            text_width = display_width - image_width

            # Create base canvas
            canvas = Image.new('RGB', (display_width, display_height), self.background_color)

            # Get countdown info
            countdown_id = current_countdown.get('id')
            countdown_name = current_countdown.get('name', 'Countdown')

            # Countdown image path is normalized in _normalize_countdowns.
            countdown_image = current_countdown.get('image_path')

            # Load and draw image on left 1/3rd
            if countdown_image:
                # Check cache first
                if countdown_id not in self.cached_images:
                    loaded_img = self._load_and_scale_image(countdown_image, image_width, display_height)
                    if loaded_img:
                        self.cached_images[countdown_id] = loaded_img

                # Paste cached image
                if countdown_id in self.cached_images:
                    canvas.paste(self.cached_images[countdown_id], (0, 0))

            # Get countdown value
            countdown_data = self.countdown_values.get(countdown_id, {'text': '---', 'is_today': False})
            countdown_text = countdown_data.get('text', '---')
            is_today = countdown_data.get('is_today', False)

            # Clear display if requested
            if force_clear:
                self.display_manager.clear()

            # Set canvas on display manager
            self.display_manager.image = canvas.copy()

            # Get fonts
            try:
                if hasattr(self.plugin_manager, 'font_manager'):
                    font_manager = self.plugin_manager.font_manager

                    name_font = font_manager.resolve_font(
                        element_key=f"{self.plugin_id}.countdown_name",
                        family=self.font_family,
                        size_px=self.name_font_size
                    )

                    value_font = font_manager.resolve_font(
                        element_key=f"{self.plugin_id}.countdown_value",
                        family=self.font_family,
                        size_px=self.font_size
                    )
                else:
                    name_font = None
                    value_font = None
            except Exception as e:
                self.logger.warning(f"Error getting fonts: {e}")
                name_font = None
                value_font = None

            # Draw text on right 2/3rds
            text_x_start = image_width
            text_center_x = text_x_start + (text_width // 2)

            # Position name in upper portion of text area
            name_y = display_height // 3

            # Position countdown value in lower portion of text area
            value_y = (display_height * 2) // 3

            # Draw countdown name
            if name_font:
                self.display_manager.draw_text(
                    countdown_name,
                    x=text_center_x,
                    y=name_y,
                    font=name_font,
                    centered=True
                )

            # Draw countdown value (highlight if today)
            if value_font:
                # Use different color if today
                if is_today:
                    # Create a special "today" font with bright color
                    try:
                        if hasattr(self.plugin_manager, 'font_manager'):
                            today_font = self.plugin_manager.font_manager.resolve_font(
                                element_key=f"{self.plugin_id}.countdown_value",
                                family=self.font_family,
                                size_px=self.font_size,
                                color=(255, 255, 0)  # Bright yellow for today
                            )
                            value_font = today_font
                    except Exception:
                        pass

                self.display_manager.draw_text(
                    countdown_text,
                    x=text_center_x,
                    y=value_y,
                    font=value_font,
                    centered=True
                )

            # Update the display
            self.display_manager.update_display()

            self.logger.debug(f"Displayed countdown: {countdown_name} - {countdown_text}")

        except Exception as e:
            self.logger.error(f"Error displaying countdown: {e}")
            self._display_error()

    def _display_no_countdowns(self) -> None:
        """Display message when no countdowns are enabled."""
        try:
            display_width = self.display_manager.matrix.width
            display_height = self.display_manager.matrix.height

            img = Image.new('RGB', (display_width, display_height), self.background_color)
            self.display_manager.image = img.copy()

            # Get font
            try:
                if hasattr(self.plugin_manager, 'font_manager'):
                    font = self.plugin_manager.font_manager.resolve_font(
                        element_key=f"{self.plugin_id}.countdown_name",
                        family=self.font_family,
                        size_px=self.name_font_size
                    )
                else:
                    font = None
            except Exception:
                font = None

            if font:
                self.display_manager.draw_text(
                    "No Active",
                    x=display_width // 2,
                    y=display_height // 3,
                    font=font,
                    centered=True
                )
                self.display_manager.draw_text(
                    "Countdowns",
                    x=display_width // 2,
                    y=(display_height * 2) // 3,
                    font=font,
                    centered=True
                )

            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying no countdowns message: {e}")

    def _display_error(self) -> None:
        """Display error message when something goes wrong."""
        try:
            display_width = self.display_manager.matrix.width
            display_height = self.display_manager.matrix.height

            img = Image.new('RGB', (display_width, display_height), (0, 0, 0))
            self.display_manager.image = img.copy()

            # Get error font
            try:
                if hasattr(self.plugin_manager, 'font_manager'):
                    error_font = self.plugin_manager.font_manager.resolve_font(
                        element_key=f"{self.plugin_id}.error",
                        family="press_start",
                        size_px=8
                    )
                else:
                    error_font = None
            except Exception:
                error_font = None

            if error_font:
                self.display_manager.draw_text(
                    "Countdown",
                    x=display_width // 2,
                    y=display_height // 3,
                    font=error_font,
                    centered=True
                )
                self.display_manager.draw_text(
                    "Error",
                    x=display_width // 2,
                    y=(display_height * 2) // 3,
                    font=error_font,
                    centered=True
                )

            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying error message: {e}")

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 15.0)

    def supports_dynamic_duration(self) -> bool:
        """Support dynamic duration for countdown rotation."""
        return True

    def is_cycle_complete(self) -> bool:
        """Check if we should rotate to next countdown."""
        current_time = time.time()
        elapsed = current_time - self.last_rotation_time
        duration = self.get_display_duration()

        if elapsed >= duration:
            self._rotate_to_next_countdown()
            return True

        return False

    def reset_cycle_state(self) -> None:
        """Reset rotation state."""
        self.last_rotation_time = time.time()

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False

        # Validate countdowns. IDs are auto-generated during normalization.
        for countdown in self.countdowns:
            if not isinstance(countdown, dict):
                self.logger.error(f"Countdown entry must be a dict: {countdown}")
                return False

            if not countdown.get('name'):
                self.logger.error(f"Countdown {countdown.get('id')} missing 'name' field")
                return False

            if not countdown.get('target_date'):
                self.logger.error(f"Countdown {countdown.get('id')} missing 'target_date' field")
                return False

            # Validate date format
            try:
                datetime.strptime(countdown['target_date'], '%Y-%m-%d')
            except ValueError:
                self.logger.error(f"Invalid date format for countdown {countdown.get('id')}: {countdown['target_date']}")
                return False

        return True

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Called when plugin configuration is updated."""
        super().on_config_change(new_config)

        old_signature = getattr(self, "_countdown_signature", None)

        # Update image-related settings that affect rendering/cache.
        self.fit_to_display = self._parse_bool(self.config.get('fit_to_display', True), default=True)
        self.preserve_aspect_ratio = self._parse_bool(self.config.get('preserve_aspect_ratio', True), default=True)
        self.show_expired = self._parse_bool(self.config.get('show_expired', False), default=False)
        self.background_color = self._parse_color(self.config.get('background_color', [0, 0, 0]), (0, 0, 0))

        # Update countdowns using normalization.
        self.countdowns = self._normalize_countdowns(self.config.get('countdowns', []))

        # Update font settings
        self.font_family = self.config.get('font_family', 'press_start')
        self.font_size = self.config.get('font_size', 8)
        self.font_color = self._parse_color(self.config.get('font_color', [255, 255, 255]), (255, 255, 255))
        self.name_font_size = self.config.get('name_font_size', 8)
        self.name_font_color = self._parse_color(self.config.get('name_font_color', [200, 200, 200]), (200, 200, 200))

        # Re-register fonts
        self._register_fonts()

        # Clear image cache if countdown metadata or image-affecting settings changed.
        self._countdown_signature = self._build_countdown_signature(self.countdowns)
        if self._countdown_signature != old_signature:
            self.cached_images.clear()
            self.current_countdown_index = 0

        # Recalculate countdown values
        self.update()

        self.logger.info(f"Config updated: {len(self.countdowns)} countdowns")

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'countdown_count': len(self.countdowns),
            'enabled_count': len(self._get_enabled_countdowns()),
            'current_index': self.current_countdown_index,
            'cached_images': len(self.cached_images)
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.cached_images.clear()
        self.countdown_values.clear()
        self.logger.info("Countdown plugin cleaned up")
