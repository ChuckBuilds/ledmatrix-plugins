"""
Static Image Plugin for LEDMatrix

Display static images with automatic scaling, aspect ratio preservation,
and transparency support. Perfect for displaying logos, artwork, or custom graphics.

Features:
- Automatic image scaling to fit display
- Aspect ratio preservation
- Transparency support (PNG, RGBA)
- Configurable background color
- Multiple image format support (PNG, JPG, BMP, GIF)

API Version: 1.0.0
"""

import logging
import os
import time
from typing import Dict, Any, Tuple, Optional
from PIL import Image
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class StaticImagePlugin(BasePlugin):
    """
    Static image display plugin for LED matrix.
    
    Supports image scaling, transparency handling, and configurable display options.
    
    Configuration options:
        image_path (str): Path to image file (relative or absolute)
        fit_to_display (bool): Auto-fit to display dimensions
        preserve_aspect_ratio (bool): Preserve aspect ratio when scaling
        background_color (list): RGB background color for transparent areas
        display_duration (float): Display duration in seconds
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the static image plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        self.image_path = config.get('image_path', 'assets/static_images/default.png')
        self.fit_to_display = config.get('fit_to_display', True)
        self.preserve_aspect_ratio = config.get('preserve_aspect_ratio', True)
        self.background_color = tuple(config.get('background_color', [0, 0, 0]))
        
        # State
        self.current_image = None
        self.image_loaded = False
        self.last_update_time = 0
        
        # Load initial image if path is provided
        if self.image_path:
            self._load_image()
        
        self.logger.info(f"Static image plugin initialized with image: {self.image_path}")

        # Register fonts
        self._register_fonts()

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Error message font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.error",
                family="press_start",
                size_px=8,
                color=(255, 0, 0)  # Red for errors
            )

            # Info font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.info",
                family="four_by_six",
                size_px=6,
                color=(150, 150, 150)
            )

            self.logger.info("Static image fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def _load_image(self) -> bool:
        """
        Load and process the image for display.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.image_path or not os.path.exists(self.image_path):
            self.logger.warning(f"Image file not found: {self.image_path}")
            return False
        
        try:
            # Load the image
            img = Image.open(self.image_path)
            
            # Convert to RGBA to handle transparency
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Get display dimensions
            display_width = self.display_manager.matrix.width
            display_height = self.display_manager.matrix.height
            
            # Calculate target size
            if self.fit_to_display and self.preserve_aspect_ratio:
                target_size = self._calculate_fit_size(img.size, (display_width, display_height))
            elif self.fit_to_display:
                target_size = (display_width, display_height)
            else:
                target_size = img.size
            
            # Resize image if needed
            if target_size != img.size:
                img = img.resize(target_size, Image.Resampling.LANCZOS)
            
            # Create display-sized canvas with background color
            canvas = Image.new('RGB', (display_width, display_height), self.background_color)
            
            # Calculate position to center the image
            paste_x = (display_width - img.width) // 2
            paste_y = (display_height - img.height) // 2
            
            # Handle transparency by compositing
            if img.mode == 'RGBA':
                # Create a temporary canvas with background color
                temp_canvas = Image.new('RGB', (display_width, display_height), self.background_color)
                temp_canvas.paste(img, (paste_x, paste_y), img)
                canvas = temp_canvas
            else:
                canvas.paste(img, (paste_x, paste_y))
            
            self.current_image = canvas
            self.image_loaded = True
            self.last_update_time = time.time()
            
            self.logger.info(f"Successfully loaded and processed image: {self.image_path}")
            self.logger.info(f"Original size: {Image.open(self.image_path).size}, "
                           f"Display size: {target_size}, Position: ({paste_x}, {paste_y})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading image {self.image_path}: {e}")
            self.image_loaded = False
            return False
    
    def _calculate_fit_size(self, image_size: Tuple[int, int], 
                           display_size: Tuple[int, int]) -> Tuple[int, int]:
        """
        Calculate size to fit image within display bounds while preserving aspect ratio.
        
        Args:
            image_size: Original image dimensions (width, height)
            display_size: Display dimensions (width, height)
        
        Returns:
            Calculated dimensions (width, height)
        """
        img_width, img_height = image_size
        display_width, display_height = display_size
        
        # Calculate scaling factor to fit within display
        scale_x = display_width / img_width
        scale_y = display_height / img_height
        scale = min(scale_x, scale_y)
        
        return (int(img_width * scale), int(img_height * scale))
    
    def update(self) -> None:
        """
        Update method - no continuous updates needed for static images.
        
        Static images don't change, so this method is a no-op.
        """
        pass
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display the static image on the LED matrix.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if not self.image_loaded or not self.current_image:
            self.logger.warning("No image loaded for display")
            self._display_error()
            return
        
        try:
            # Clear display if requested
            if force_clear:
                self.display_manager.clear()
            
            # Set the image on the display manager
            self.display_manager.image = self.current_image.copy()
            
            # Update the display
            self.display_manager.update_display()
            
            self.logger.debug(f"Displayed image: {self.image_path}")
            
        except Exception as e:
            self.logger.error(f"Error displaying image: {e}")
            self._display_error()
    
    def _display_error(self) -> None:
        """Display error message when image can't be loaded."""
        try:
            # Get error font from font manager
            error_font = None
            try:
                if hasattr(self.plugin_manager, 'font_manager'):
                    font_manager = self.plugin_manager.font_manager
                    error_font = font_manager.get_font(f"{self.plugin_id}.error")
            except Exception as e:
                self.logger.warning(f"Error getting font from font manager: {e}")

            img = Image.new('RGB',
                          (self.display_manager.matrix.width,
                           self.display_manager.matrix.height),
                          (0, 0, 0))

            if error_font:
                self.display_manager.image = img.copy()
                self.display_manager.draw_text("Image", x=5, y=12, font=error_font, centered=False)
                self.display_manager.draw_text("Error", x=5, y=20, font=error_font, centered=False)
            else:
                # Fallback to direct PIL if font manager fails
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(img)

                try:
                    font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
                except:
                    font = ImageFont.load_default()

                draw.text((5, 12), "Image", font=font, fill=(200, 0, 0))
                draw.text((5, 20), "Error", font=font, fill=(200, 0, 0))

                self.display_manager.image = img.copy()

            self.display_manager.update_display()
        except Exception as e:
            self.logger.error(f"Error displaying error message: {e}")
            pass
    
    def set_image_path(self, image_path: str) -> bool:
        """
        Set a new image path and load it.
        
        Args:
            image_path: Path to new image file
        
        Returns:
            True if successful, False otherwise
        """
        self.image_path = image_path
        return self._load_image()
    
    def reload_image(self) -> bool:
        """
        Reload the current image.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.image_path:
            self.logger.warning("No image path set for reload")
            return False
        
        return self._load_image()
    
    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 10.0)
    
    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        # Call parent validation first
        if not super().validate_config():
            return False
        
        # Validate image path exists
        if not self.image_path:
            self.logger.error("No image path specified")
            return False
        
        if not os.path.exists(self.image_path):
            self.logger.warning(f"Image file not found: {self.image_path}")
            # Don't fail validation, just warn - file might be added later
        
        # Validate background color
        if not isinstance(self.background_color, tuple) or len(self.background_color) != 3:
            self.logger.error("Invalid background_color: must be RGB tuple")
            return False
        
        if not all(0 <= c <= 255 for c in self.background_color):
            self.logger.error("Invalid background_color: values must be 0-255")
            return False
        
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'image_path': self.image_path,
            'image_loaded': self.image_loaded,
            'fit_to_display': self.fit_to_display,
            'preserve_aspect_ratio': self.preserve_aspect_ratio,
            'background_color': self.background_color
        })
        
        if self.current_image:
            info['display_size'] = self.current_image.size
        
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_image = None
        self.image_loaded = False
        self.logger.info("Static image plugin cleaned up")

