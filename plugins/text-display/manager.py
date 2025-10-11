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
import time
import os
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

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
        scroll_speed (float): Scroll speed in pixels per second
        text_color (list): RGB text color
        background_color (list): RGB background color
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the text display plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        self.text = config.get('text', 'Hello, World!')
        self.font_path = config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        self.font_size = config.get('font_size', 8)
        self.scroll_enabled = config.get('scroll', True)
        self.scroll_speed = config.get('scroll_speed', 30)
        self.scroll_gap_width = config.get('scroll_gap_width', 32)
        self.text_color = tuple(config.get('text_color', [255, 255, 255]))
        self.bg_color = tuple(config.get('background_color', [0, 0, 0]))
        
        # State
        self.font = self._load_font()
        self.text_width = 0
        self.scroll_pos = 0.0
        self.last_update_time = time.time()
        self.text_image_cache = None
        
        # Calculate text dimensions
        self._calculate_text_dimensions()
        
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
        
        # Resolve relative paths
        if not os.path.isabs(font_path):
            # Try relative to project root
            if os.path.exists(font_path):
                pass
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
        """Pre-render the text onto an image for smooth scrolling."""
        if not self.text or self.text_width == 0:
            return
        
        try:
            # Total width is text width plus gap
            cache_width = self.text_width + self.scroll_gap_width
            cache_height = self.display_manager.matrix.height
            
            # Create cache image
            self.text_image_cache = Image.new('RGB', (cache_width, cache_height), self.bg_color)
            draw = ImageDraw.Draw(self.text_image_cache)
            
            # Calculate vertical centering
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            bbox = temp_draw.textbbox((0, 0), self.text, font=self.font)
            text_height = bbox[3] - bbox[1]
            y_pos = (cache_height - text_height) // 2 - bbox[1]
            
            # Draw text
            draw.text((0, y_pos), self.text, font=self.font, fill=self.text_color)
            
            self.logger.info(f"Created text cache: {cache_width}x{cache_height}")
        except Exception as e:
            self.logger.error(f"Failed to create text cache: {e}")
            self.text_image_cache = None
    
    def update(self) -> None:
        """Update scroll position if scrolling is enabled."""
        if not self.scroll_enabled or self.text_width <= self.display_manager.matrix.width:
            self.scroll_pos = 0.0
            return
        
        current_time = time.time()
        delta_time = current_time - self.last_update_time
        self.last_update_time = current_time
        
        # Update scroll position
        scroll_delta = delta_time * self.scroll_speed
        self.scroll_pos += scroll_delta
        
        # Reset when scrolled past end
        total_width = self.text_width + self.scroll_gap_width
        if self.scroll_pos >= total_width:
            self.scroll_pos = self.scroll_pos % total_width
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display the text on the LED matrix.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if not self.text:
            return
        
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            # Create display image
            img = Image.new('RGB', (matrix_width, matrix_height), self.bg_color)
            draw = ImageDraw.Draw(img)
            
            if self.scroll_enabled and self.text_width > matrix_width:
                # Scrolling text
                if not self.text_image_cache:
                    self._create_text_cache()
                
                if self.text_image_cache:
                    # Use cached image for scrolling
                    scroll_int = int(self.scroll_pos)
                    cache_width = self.text_image_cache.width
                    
                    if scroll_int + matrix_width <= cache_width:
                        # Simple crop
                        segment = self.text_image_cache.crop((scroll_int, 0, scroll_int + matrix_width, matrix_height))
                        img.paste(segment, (0, 0))
                    else:
                        # Wrap-around
                        width1 = cache_width - scroll_int
                        if width1 > 0:
                            segment1 = self.text_image_cache.crop((scroll_int, 0, cache_width, matrix_height))
                            img.paste(segment1, (0, 0))
                        
                        remaining = matrix_width - width1
                        if remaining > 0:
                            segment2 = self.text_image_cache.crop((0, 0, remaining, matrix_height))
                            img.paste(segment2, (width1, 0))
                else:
                    # Fallback: direct draw with offset
                    x_pos = matrix_width - int(self.scroll_pos)
                    bbox = draw.textbbox((0, 0), self.text, font=self.font)
                    text_height = bbox[3] - bbox[1]
                    y_pos = (matrix_height - text_height) // 2 - bbox[1]
                    draw.text((x_pos, y_pos), self.text, font=self.font, fill=self.text_color)
            else:
                # Static text (centered)
                bbox = draw.textbbox((0, 0), self.text, font=self.font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                x_pos = (matrix_width - text_width) // 2
                y_pos = (matrix_height - text_height) // 2 - bbox[1]
                draw.text((x_pos, y_pos), self.text, font=self.font, fill=self.text_color)
            
            # Update display
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            
        except Exception as e:
            self.logger.error(f"Error displaying text: {e}")
    
    def set_text(self, text: str):
        """Update the displayed text."""
        self.text = text
        self._calculate_text_dimensions()
        self.text_image_cache = None
        self.scroll_pos = 0.0
        self.logger.info(f"Text updated to: '{text[:30]}...'")
    
    def get_display_duration(self) -> float:
        """Get display duration from config."""
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
            if not all(0 <= c <= 255 for c in color_value):
                self.logger.error(f"Invalid {color_name}: values must be 0-255")
                return False
        
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'text': self.text[:50] if len(self.text) > 50 else self.text,
            'text_width': self.text_width,
            'scroll_enabled': self.scroll_enabled,
            'scroll_speed': self.scroll_speed,
            'font_path': self.font_path,
            'font_size': self.font_size
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.text_image_cache = None
        self.logger.info("Text display plugin cleaned up")

