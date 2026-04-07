"""
Text Display Plugin for LEDMatrix

Display custom scrolling or static text messages with configurable fonts and colors.
Perfect for announcements, messages, or custom displays.

Features:
- Scrolling or static text display
- TTF and BDF font support
- Configurable colors and scroll speed
- Automatic text width calculation
- Smooth scrolling animation

API Version: 1.0.0
"""

import logging
import os
import time
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin
from src.common.scroll_helper import ScrollHelper

logger = logging.getLogger(__name__)


class TextDisplayPlugin(BasePlugin):
    """
    Text display plugin for showing custom messages.
    
    Supports scrolling and static text with custom fonts and colors.
    
    Configuration options:
        text (str): Message to display
        font_path (str): Path to TTF or BDF font file
        font_size (int): Font size in pixels
        scroll (bool): Enable scrolling animation
        scroll_speed (float): Scroll speed in pixels per frame (default: 1, range: 0.1-10)
        scroll_delay (float): Delay in seconds per frame (default: 0.01, range: 0.001-0.1)
        scroll_loop (bool): If true, text loops continuously (default: true)
        text_color (list): RGB text color
        background_color (list): RGB background color
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the text display plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        # Default kept in sync with config_schema.json — the schema is what
        # the auto-generated web UI form populates from, so the code default
        # must match what the form prefill shows.
        self.text = config.get('text', 'Subscribe to ChuckBuilds')
        self.font_path = config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        self.font_size = config.get('font_size', 8)
        self.scroll_enabled = config.get('scroll', True)
        # Signal to DisplayController that this plugin needs high-FPS treatment when scrolling
        self.enable_scrolling = self.scroll_enabled
        # Frame-based scrolling: pixels per frame
        self.scroll_speed = float(config.get('scroll_speed', 1))  # pixels per frame (like stock/leaderboard)
        self.scroll_delay = float(config.get('scroll_delay', 0.01))  # seconds per frame (default 0.01 = 100 FPS)
        self.target_fps = float(config.get('target_fps', 120))  # target FPS for smooth scrolling
        
        # Warn if scroll_speed seems too high (might be from old config when it was pixels/second)
        if self.scroll_speed > 5:
            self.logger.warning(
                f"scroll_speed is {self.scroll_speed} pixels/frame - this is very high and will cause large jumps. "
                f"Recommended range: 0.5-2 pixels/frame for smooth scrolling. "
                f"If you had an old config with pixels/second, divide by ~100 (e.g., 30 px/s -> 0.3 px/frame)"
            )
        self.scroll_loop = config.get('scroll_loop', True)  # Default to looping for backward compatibility
        self.scroll_gap_width = config.get('scroll_gap_width', 32)
        # Convert colors to integers to handle string values from JSON config
        try:
            text_color_raw = config.get('text_color', [255, 255, 255])
            bg_color_raw = config.get('background_color', [0, 0, 0])
            self.text_color = tuple(int(c) for c in text_color_raw)
            self.bg_color = tuple(int(c) for c in bg_color_raw)
        except (ValueError, TypeError) as e:
            self.logger.error(f"Invalid color values in config: {e}")
            # Use defaults if conversion fails
            self.text_color = (255, 255, 255)
            self.bg_color = (0, 0, 0)
        
        # State
        self.font = self._load_font()
        self.text_width = 0
        self.text_image_cache = None
        
        # Frame rate tracking for FPS logging
        self.frame_count = 0
        self.last_frame_time = None
        self.last_fps_log_time = None
        self.frame_times = []
        
        # Calculate text dimensions
        self._calculate_text_dimensions()
        
        # Initialize ScrollHelper for scrolling functionality
        display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') else 128
        display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') else 32
        self.scroll_helper = ScrollHelper(display_width, display_height, logger=self.logger)
        
        # Configure ScrollHelper with plugin settings
        # Use frame-based scrolling for smoother visual movement on LED matrix
        # This ignores time deltas and moves fixed pixels per step, throttled by scroll_delay
        
        # Check if method exists for backward compatibility
        if hasattr(self.scroll_helper, 'set_frame_based_scrolling'):
            self.scroll_helper.set_frame_based_scrolling(True)
            # In frame-based mode, scroll_speed is pixels per frame
            # Log the value before setting to help debug config issues
            self.logger.info(f"Config scroll_speed: {self.scroll_speed} pixels/frame, scroll_delay: {self.scroll_delay}s")
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            # Log the actual value after clamping (in case it was adjusted)
            if self.scroll_helper.scroll_speed != self.scroll_speed:
                self.logger.warning(
                    f"scroll_speed was clamped from {self.scroll_speed} to {self.scroll_helper.scroll_speed} pixels/frame "
                    f"(max 5 px/frame for smooth scrolling)"
                )
        else:
            # Fallback for older ScrollHelper: convert to pixels/second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.scroll_helper.set_scroll_speed(pixels_per_second)
            
        self.scroll_helper.set_scroll_delay(self.scroll_delay)
        
        # Set target FPS from config (clamp to valid range)
        target_fps = max(30.0, min(240.0, self.target_fps))
        self.scroll_helper.set_target_fps(target_fps)
        # Sub-pixel scrolling disabled - using high frame rate integer scrolling for smoothness
        # This matches the behavior of stock/leaderboard tickers
        
        # Calculate pixels per second for logging (even though we use frame-based mode)
        pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
        self.logger.info(f"Scroll settings: {self.scroll_speed} px/frame, {self.scroll_delay}s delay = {pixels_per_second:.1f} px/s, target FPS: {target_fps}")
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=True,
            min_duration=10,
            max_duration=300,
            buffer=0.1
        )
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Text display plugin initialized: '{self.text[:30]}...'")
        self.logger.info(f"Font: {self.font_path}, Size: {self.font_size}, Scroll: {self.scroll_enabled}")
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return
            
            font_manager = self.plugin_manager.font_manager
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.text",
                family="press_start",
                size_px=self.font_size,
                color=self.text_color
            )
            
            self.logger.info("Text display fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")
    
    def _load_font(self):
        """Load the specified font file (TTF or BDF)."""
        font_path = self.font_path
        
        # Resolve relative paths to project root
        if not os.path.isabs(font_path):
            # Try multiple resolution strategies
            resolved_path = None
            
            # Strategy 1: Try as-is (if running from project root)
            if os.path.exists(font_path):
                resolved_path = font_path
            else:
                # Strategy 2: Try relative to current working directory (project root)
                cwd_path = os.path.join(os.getcwd(), font_path)
                if os.path.exists(cwd_path):
                    resolved_path = cwd_path
                else:
                    # Strategy 3: Try relative to plugin directory's parent (project root)
                    # Get the plugin directory (assuming we're in plugins/text-display/)
                    plugin_dir = Path(__file__).parent
                    project_root = plugin_dir.parent.parent
                    project_path = project_root / font_path
                    if project_path.exists():
                        resolved_path = str(project_path)
            
            if resolved_path:
                font_path = resolved_path
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
                return ImageFont.load_default()
        
        if not os.path.exists(font_path):
            self.logger.warning(f"Font file not found: {font_path}, using default")
            return ImageFont.load_default()
        
        try:
            if font_path.lower().endswith('.ttf'):
                font = ImageFont.truetype(font_path, self.font_size)
                self.logger.info(f"Loaded TTF font: {font_path}")
                return font
            elif font_path.lower().endswith('.bdf'):
                # BDF fonts need freetype
                try:
                    import freetype
                    face = freetype.Face(font_path)
                    face.set_pixel_sizes(0, self.font_size)
                    self.logger.info(f"Loaded BDF font: {font_path}")
                    return face
                except ImportError:
                    self.logger.warning("freetype not available for BDF font, using default")
                    return ImageFont.load_default()
            else:
                self.logger.warning(f"Unsupported font type: {font_path}")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Failed to load font {font_path}: {e}")
            return ImageFont.load_default()
    
    def _calculate_text_dimensions(self):
        """Calculate text width for scrolling."""
        if not self.text or not self.font:
            self.text_width = 0
            return
        
        try:
            # Create temporary image to measure text
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            
            if isinstance(self.font, ImageFont.FreeTypeFont) or isinstance(self.font, ImageFont.ImageFont):
                bbox = temp_draw.textbbox((0, 0), self.text, font=self.font)
                self.text_width = bbox[2] - bbox[0]
            else:
                # Default fallback
                self.text_width = len(self.text) * 8
            
            self.logger.info(f"Text width calculated: {self.text_width}px for '{self.text[:30]}...'")
        except Exception as e:
            self.logger.error(f"Error calculating text width: {e}")
            self.text_width = len(self.text) * 8
    
    def _create_text_cache(self):
        """Pre-render the text onto an image for smooth scrolling using ScrollHelper."""
        if not self.text or self.text_width == 0:
            self.logger.warning("Cannot create text cache: text is empty or text_width is 0")
            return
        
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            # Total width: initial padding + text + final padding (so text scrolls completely off) + gap
            # Structure: [display_width padding] [text] [display_width padding] [gap]
            # This ensures text starts off-screen right and scrolls completely off-screen left
            cache_width = matrix_width + self.text_width + matrix_width + self.scroll_gap_width
            
            # Create cache image
            self.text_image_cache = Image.new('RGB', (cache_width, matrix_height), self.bg_color)
            draw = ImageDraw.Draw(self.text_image_cache)
            
            # Calculate vertical centering
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            bbox = temp_draw.textbbox((0, 0), self.text, font=self.font)
            text_height = bbox[3] - bbox[1]
            y_pos = (matrix_height - text_height) // 2 - bbox[1]
            
            # Draw text starting after the initial display_width padding
            draw.text((matrix_width, y_pos), self.text, font=self.font, fill=self.text_color)
            
            # Ensure image is in RGB mode (required for numpy conversion)
            if self.text_image_cache.mode != 'RGB':
                self.text_image_cache = self.text_image_cache.convert('RGB')
            
            # Set the scrolling image in ScrollHelper
            self.scroll_helper.set_scrolling_image(self.text_image_cache)
            
            # Verify it was set correctly
            if self.scroll_helper.cached_image is None:
                self.logger.error("Failed to set scrolling image in ScrollHelper")
            if self.scroll_helper.cached_array is None:
                self.logger.error("ScrollHelper cached_array is None after set_scrolling_image")
            
            self.logger.info(f"Created text cache: {cache_width}x{matrix_height} (text: {self.text_width}px + {matrix_width}px end buffer + {self.scroll_gap_width}px gap)")
            self.logger.debug(f"Text cache details: text_width={self.text_width}, matrix_width={matrix_width}, "
                           f"end_buffer={matrix_width}, scroll_gap_width={self.scroll_gap_width}, "
                           f"scroll_helper.total_scroll_width={self.scroll_helper.total_scroll_width}, "
                           f"scroll_helper.cached_image={'set' if self.scroll_helper.cached_image else 'None'}, "
                           f"scroll_helper.cached_array={'set' if self.scroll_helper.cached_array is not None else 'None'}")
        except Exception as e:
            self.logger.error(f"Failed to create text cache: {e}", exc_info=True)
            self.text_image_cache = None
    
    def update(self) -> None:
        """Update scroll position if scrolling is enabled using ScrollHelper."""
        if not self.scroll_enabled or self.text_width <= self.display_manager.matrix.width:
            # Reset scroll position if scrolling is disabled or text fits
            if self.scroll_helper:
                self.scroll_helper.reset_scroll()
            return
        
        # Ensure cache is created before updating scroll position
        if not self.text_image_cache:
            self._create_text_cache()
        
        # Use ScrollHelper to update scroll position
        if self.scroll_helper and self.text_image_cache:
            # Verify scroll_helper has the image set
            if self.scroll_helper.cached_image is None:
                self.logger.warning("ScrollHelper cached_image is None, re-setting scrolling image")
                self.scroll_helper.set_scrolling_image(self.text_image_cache)
            
            # In one-shot mode, don't update if scroll is complete
            if not self.scroll_loop and self.scroll_helper.is_scroll_complete():
                # One-shot mode and complete - don't update position
                return
            
            self.scroll_helper.update_scroll_position()
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display the text on the LED matrix using ScrollHelper.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if not self.text:
            return
        
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            if self.scroll_enabled and self.text_width > matrix_width:
                # Scrolling text - use ScrollHelper
                if not self.text_image_cache:
                    self._create_text_cache()
                
                if self.text_image_cache and self.scroll_helper:
                    # Verify scroll_helper has the image set
                    if self.scroll_helper.cached_image is None:
                        self.logger.warning("ScrollHelper cached_image is None in display(), re-setting scrolling image")
                        self.scroll_helper.set_scrolling_image(self.text_image_cache)
                    
                    # Update scroll position (handles time-based scrolling automatically)
                    # This ensures scroll position is updated every frame
                    was_complete = self.scroll_helper.is_scroll_complete()
                    
                    # In one-shot mode, don't update if scroll is already complete
                    if not self.scroll_loop and was_complete:
                        # One-shot mode and already complete - don't update position
                        is_now_complete = True
                    else:
                        # Update scroll position (will handle completion)
                        self.scroll_helper.update_scroll_position()
                        is_now_complete = self.scroll_helper.is_scroll_complete()
                        
                        # Handle scroll completion based on loop setting
                        if is_now_complete:
                            if self.scroll_loop:
                                # Continuous looping mode - reset when complete
                                self.scroll_helper.reset_scroll()
                                if not was_complete:
                                    # Just completed this frame
                                    self.logger.debug("Scroll completed and reset for continuous loop")
                                else:
                                    # Was already complete (shouldn't happen often, but handle it)
                                    self.logger.debug("Scroll reset for continuous loop (was already complete)")
                            else:
                                # One-shot mode - stop scrolling when complete
                                # Scroll position is already clamped by ScrollHelper, so just stop updating
                                if not was_complete:
                                    self.logger.info("Scroll completed in one-shot mode - stopping")
                    
                    # Signal scrolling state to display manager
                    if hasattr(self.display_manager, 'set_scrolling_state'):
                        # Only signal scrolling if not complete (or if looping and will reset)
                        if not self.scroll_helper.is_scroll_complete() or (self.scroll_loop and self.scroll_helper.is_scroll_complete()):
                            self.display_manager.set_scrolling_state(True)
                        else:
                            # One-shot mode and complete - stop scrolling
                            self.display_manager.set_scrolling_state(False)
                    
                    # Get visible portion from ScrollHelper
                    visible_image = self.scroll_helper.get_visible_portion()
                    
                    if visible_image:
                        # Ensure display_manager.image exists and is the right size
                        if not hasattr(self.display_manager, 'image') or self.display_manager.image is None:
                            self.display_manager.image = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                        
                        # Update display with visible portion (use paste like odds-ticker)
                        self.display_manager.image.paste(visible_image, (0, 0))
                        self.display_manager.update_display()
                        
                        # Log frame rate for scrolling text
                        self._log_frame_rate()
                        
                        self.logger.debug(f"Displayed visible portion: scroll_position={self.scroll_helper.scroll_position:.2f}, "
                                        f"image_size={visible_image.size}")
                    else:
                        self.logger.warning("ScrollHelper.get_visible_portion() returned None, using fallback")
                        # Fallback: direct draw
                        img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                        draw = ImageDraw.Draw(img)
                        bbox = draw.textbbox((0, 0), self.text, font=self.font)
                        text_height = bbox[3] - bbox[1]
                        y_pos = (matrix_height - text_height) // 2 - bbox[1]
                        draw.text((0, y_pos), self.text, font=self.font, fill=self.text_color)
                        if not hasattr(self.display_manager, 'image') or self.display_manager.image is None:
                            self.display_manager.image = img
                        else:
                            self.display_manager.image.paste(img, (0, 0))
                        self.display_manager.update_display()
                else:
                    # Fallback: static text if cache creation failed
                    img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                    draw = ImageDraw.Draw(img)
                    bbox = draw.textbbox((0, 0), self.text, font=self.font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    x_pos = (matrix_width - text_width) // 2
                    y_pos = (matrix_height - text_height) // 2 - bbox[1]
                    draw.text((x_pos, y_pos), self.text, font=self.font, fill=self.text_color)
                    self.display_manager.image = img
                    self.display_manager.update_display()
            else:
                # Static text (centered)
                img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
                draw = ImageDraw.Draw(img)
                bbox = draw.textbbox((0, 0), self.text, font=self.font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                x_pos = (matrix_width - text_width) // 2
                y_pos = (matrix_height - text_height) // 2 - bbox[1]
                draw.text((x_pos, y_pos), self.text, font=self.font, fill=self.text_color)
                self.display_manager.image = img
                self.display_manager.update_display()
            
        except Exception as e:
            self.logger.error(f"Error displaying text: {e}")
    
    def _log_frame_rate(self):
        """Log frame rate statistics for scrolling text."""
        if not self.scroll_enabled:
            return
        
        current_time = time.time()
        
        # Initialize timing on first call
        if self.last_frame_time is None:
            self.last_frame_time = current_time
            self.last_fps_log_time = current_time
            return
        
        # Calculate instantaneous frame time
        frame_time = current_time - self.last_frame_time
        self.frame_times.append(frame_time)
        
        # Keep only last 100 frames for average
        if len(self.frame_times) > 100:
            self.frame_times.pop(0)
        
        # Log FPS every 5 seconds to avoid spam
        if current_time - self.last_fps_log_time >= 5.0:
            avg_frame_time = sum(self.frame_times) / len(self.frame_times) if self.frame_times else frame_time
            avg_fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 0
            instant_fps = 1.0 / frame_time if frame_time > 0 else 0
            
            self.logger.info(
                f"Text display FPS - Avg: {avg_fps:.1f}, Current: {instant_fps:.1f}, "
                f"Frame time: {frame_time*1000:.2f}ms, Target: {self.target_fps:.0f} FPS"
            )
            self.last_fps_log_time = current_time
            self.frame_count = 0
        
        self.last_frame_time = current_time
        self.frame_count += 1
    
    def set_text(self, text: str):
        """Update the displayed text."""
        self.text = text
        self._calculate_text_dimensions()
        self.text_image_cache = None
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()
        self.logger.info(f"Text updated to: '{text[:30]}...'")
    
    def get_display_duration(self) -> float:
        """Get display duration from config or ScrollHelper's dynamic duration."""
        # If scrolling is enabled and ScrollHelper has calculated a duration, use it
        if self.scroll_enabled and self.scroll_helper and self.scroll_helper.total_scroll_width > 0:
            dynamic_duration = self.scroll_helper.get_dynamic_duration()
            if dynamic_duration > 0:
                return float(dynamic_duration)
        # Otherwise use config value or default
        return self.config.get('display_duration', 10.0)
    
    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False
        
        # Validate text is provided
        if not self.text:
            self.logger.error("No text specified")
            return False
        
        # Validate colors
        for color_name, color_value in [("text_color", self.text_color), ("background_color", self.bg_color)]:
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
    
    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Handle configuration changes at runtime."""
        super().on_config_change(new_config)
        
        # Update text if changed
        new_text = new_config.get('text', self.text)
        if new_text != self.text:
            self.set_text(new_text)
        
        # Update scroll settings
        old_scroll_enabled = self.scroll_enabled
        self.scroll_enabled = new_config.get('scroll', self.scroll_enabled)
        new_scroll_speed = new_config.get('scroll_speed', self.scroll_speed)
        new_scroll_delay = new_config.get('scroll_delay', self.scroll_delay)
        new_target_fps = new_config.get('target_fps', self.target_fps)
        self.scroll_loop = new_config.get('scroll_loop', self.scroll_loop)
        self.scroll_gap_width = new_config.get('scroll_gap_width', self.scroll_gap_width)
        
        # Update ScrollHelper settings if scroll speed, delay, or target_fps changed
        scroll_settings_changed = False
        if new_scroll_speed != self.scroll_speed:
            self.scroll_speed = float(new_scroll_speed)
            scroll_settings_changed = True
        if new_scroll_delay != self.scroll_delay:
            self.scroll_delay = float(new_scroll_delay)
            scroll_settings_changed = True
        if new_target_fps != self.target_fps:
            self.target_fps = float(new_target_fps)
            scroll_settings_changed = True
        
        if scroll_settings_changed and self.scroll_helper:
            # Check if frame-based scrolling is supported
            if hasattr(self.scroll_helper, 'set_frame_based_scrolling'):
                # Frame-based mode: speed is pixels per frame
                self.scroll_helper.set_scroll_speed(self.scroll_speed)
            else:
                # Fallback: calculate pixels per second
                pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
                self.scroll_helper.set_scroll_speed(pixels_per_second)
                
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
            # Clamp target FPS to valid range
            target_fps = max(30.0, min(240.0, self.target_fps))
            self.scroll_helper.set_target_fps(target_fps)
            self.logger.info(f"Scroll settings updated: speed={self.scroll_speed}, delay={self.scroll_delay}s, target FPS={target_fps}")
        
        # Reset scroll position if scroll was toggled
        if old_scroll_enabled != self.scroll_enabled:
            if self.scroll_helper:
                self.scroll_helper.reset_scroll()
            self.text_image_cache = None  # Invalidate cache when scroll state changes
            self.logger.info(f"Scroll {'enabled' if self.scroll_enabled else 'disabled'}")
        
        # Update font settings if changed
        new_font_path = new_config.get('font_path', self.font_path)
        new_font_size = new_config.get('font_size', self.font_size)
        if new_font_path != self.font_path or new_font_size != self.font_size:
            self.font_path = new_font_path
            self.font_size = new_font_size
            self.font = self._load_font()
            self._calculate_text_dimensions()
            self.text_image_cache = None  # Invalidate cache when font changes
            self._register_fonts()
        
        # Update colors if changed
        try:
            text_color_raw = new_config.get('text_color')
            if text_color_raw:
                self.text_color = tuple(int(c) for c in text_color_raw)
            
            bg_color_raw = new_config.get('background_color')
            if bg_color_raw:
                self.bg_color = tuple(int(c) for c in bg_color_raw)
                self.text_image_cache = None  # Invalidate cache when background color changes
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Invalid color values in config update: {e}")
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        # Calculate pixels per second for display
        pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
        info.update({
            'text': self.text[:50] if len(self.text) > 50 else self.text,
            'text_width': self.text_width,
            'scroll_enabled': self.scroll_enabled,
            'scroll_speed': self.scroll_speed,  # pixels per frame
            'scroll_delay': self.scroll_delay,  # seconds per frame
            'target_fps': self.target_fps,
            'pixels_per_second': round(pixels_per_second, 1),  # calculated from frame-based settings
            'scroll_loop': self.scroll_loop,
            'font_path': self.font_path,
            'font_size': self.font_size
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        if self.scroll_helper:
            self.scroll_helper.clear_cache()
        self.text_image_cache = None
        self.logger.info("Text display plugin cleaned up")

