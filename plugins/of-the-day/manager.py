"""
Of The Day Plugin for LEDMatrix

Display daily featured content like Word of the Day, Bible verses, or custom items.
Supports multiple categories with automatic rotation and configurable data sources.

Features:
- Multiple category support (Word of the Day, Bible verses, etc.)
- Automatic daily updates
- Rotating display of title, definition, examples
- Configurable data sources via JSON files
- Multi-line text wrapping for long content

API Version: 1.0.0
"""

import os
import json
import logging
import time
from datetime import date
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class OfTheDayPlugin(BasePlugin):
    """
    Of The Day plugin for displaying daily featured content.
    
    Supports multiple categories with rotation between title, subtitle, and content.
    
    Configuration options:
        categories (dict): Dictionary of category configurations
        category_order (list): Order to display categories
        display_rotate_interval (float): Seconds between display rotations
        subtitle_rotate_interval (float): Seconds between subtitle rotations
        update_interval (float): Seconds between checking for new day
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the of-the-day plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        self.update_interval = config.get('update_interval', 3600)
        self.display_rotate_interval = config.get('display_rotate_interval', 20)
        self.subtitle_rotate_interval = config.get('subtitle_rotate_interval', 10)
        
        # Categories
        self.categories = config.get('categories', {})
        self.category_order = config.get('category_order', [])
        
        # State
        self.current_day = None
        self.current_items = {}
        self.current_category_index = 0
        self.rotation_state = 0  # 0 = title, 1 = content
        self.last_update = 0
        self.last_rotation_time = time.time()
        self.last_category_rotation_time = time.time()
        
        # Data files
        self.data_files = {}
        
        # Colors
        self.title_color = (255, 255, 255)
        self.subtitle_color = (200, 200, 200)
        self.content_color = (180, 180, 180)
        self.background_color = (0, 0, 0)
        
        # Load data files
        self._load_data_files()
        
        # Load today's items
        self._load_todays_items()
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Of The Day plugin initialized with {len(self.current_items)} categories")
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return
            
            font_manager = self.plugin_manager.font_manager
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.title",
                family="press_start",
                size_px=8,
                color=self.title_color
            )
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.content",
                family="four_by_six",
                size_px=6,
                color=self.content_color
            )
            
            self.logger.info("Of The Day fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")
    
    def _load_data_files(self):
        """Load all data files for enabled categories."""
        for category_name, category_config in self.categories.items():
            if not category_config.get('enabled', True):
                self.logger.debug(f"Skipping disabled category: {category_name}")
                continue
            
            data_file = category_config.get('data_file')
            if not data_file:
                self.logger.warning(f"No data file specified for category: {category_name}")
                continue
            
            try:
                # Try to locate the data file
                file_path = self._find_data_file(data_file)
                if not file_path:
                    self.logger.warning(f"Could not find data file: {data_file}")
                    continue
                
                # Load and parse JSON
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.data_files[category_name] = data
                self.logger.info(f"Loaded data for category '{category_name}': {len(data)} entries")
                
            except Exception as e:
                self.logger.error(f"Error loading data file for {category_name}: {e}")
    
    def _find_data_file(self, data_file: str) -> Optional[str]:
        """Find the data file in possible locations."""
        # Get plugin directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Possible paths to check (prioritize plugin directory)
        possible_paths = [
            os.path.join(plugin_dir, data_file),  # In plugin directory (preferred)
            data_file,  # Direct path (if absolute)
            os.path.join(os.getcwd(), data_file),  # Relative to cwd (fallback)
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                self.logger.info(f"Found data file at: {path}")
                return path
        
        self.logger.warning(f"Data file not found: {data_file}")
        return None
    
    def _load_todays_items(self):
        """Load items for today's date from all enabled categories."""
        today = date.today()
        
        if self.current_day == today and self.current_items:
            return  # Already loaded for today
        
        self.current_day = today
        self.current_items = {}
        
        for category_name, data in self.data_files.items():
            try:
                # Find today's entry
                today_key = today.strftime("%Y-%m-%d")
                
                if today_key in data:
                    self.current_items[category_name] = data[today_key]
                    self.logger.info(f"Loaded item for {category_name}: {data[today_key].get('word', data[today_key].get('title', 'N/A'))}")
                else:
                    self.logger.warning(f"No entry found for {today_key} in category {category_name}")
            
            except Exception as e:
                self.logger.error(f"Error loading today's item for {category_name}: {e}")
    
    def update(self) -> None:
        """Update items if it's a new day."""
        current_time = time.time()
        
        # Check if we need to update
        if current_time - self.last_update < self.update_interval:
            return
        
        self.last_update = current_time
        
        # Check if it's a new day
        today = date.today()
        if self.current_day != today:
            self.logger.info(f"New day detected, loading items for {today}")
            self._load_todays_items()
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display of-the-day content.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if not self.current_items:
            self._display_no_data()
            return
        
        try:
            # Get enabled categories in order
            enabled_categories = [cat for cat in self.category_order 
                                if cat in self.current_items and 
                                self.categories.get(cat, {}).get('enabled', True)]
            
            if not enabled_categories:
                self._display_no_data()
                return
            
            # Rotate categories
            current_time = time.time()
            if current_time - self.last_category_rotation_time >= self.display_rotate_interval:
                self.current_category_index = (self.current_category_index + 1) % len(enabled_categories)
                self.last_category_rotation_time = current_time
                self.rotation_state = 0  # Reset rotation when changing categories
                self.last_rotation_time = current_time
            
            # Get current category
            category_name = enabled_categories[self.current_category_index]
            category_config = self.categories.get(category_name, {})
            item_data = self.current_items.get(category_name, {})
            
            # Rotate display content
            if current_time - self.last_rotation_time >= self.subtitle_rotate_interval:
                self.rotation_state = (self.rotation_state + 1) % 2
                self.last_rotation_time = current_time
            
            # Display based on rotation state
            if self.rotation_state == 0:
                self._display_title(category_config, item_data)
            else:
                self._display_content(category_config, item_data)
        
        except Exception as e:
            self.logger.error(f"Error displaying of-the-day: {e}")
            self._display_error()
    
    def _display_title(self, category_config: Dict, item_data: Dict):
        """Display the title/word."""
        img = Image.new('RGB', (self.display_manager.matrix.width, 
                               self.display_manager.matrix.height), 
                       self.background_color)
        draw = ImageDraw.Draw(img)
        
        # Load fonts
        try:
            title_font = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 8)
            subtitle_font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
        except:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
        
        # Draw category name
        category_display = category_config.get('display_name', 'Of The Day')
        draw.text((2, 2), category_display, font=subtitle_font, fill=self.subtitle_color)
        
        # Draw word/title
        word = item_data.get('word', item_data.get('title', 'N/A'))
        bbox = draw.textbbox((0, 0), word, font=title_font)
        text_width = bbox[2] - bbox[0]
        x_pos = (self.display_manager.matrix.width - text_width) // 2
        draw.text((x_pos, 12), word, font=title_font, fill=self.title_color)
        
        # Draw pronunciation or type
        pronunciation = item_data.get('pronunciation', item_data.get('type', ''))
        if pronunciation:
            draw.text((2, self.display_manager.matrix.height - 8), pronunciation, 
                     font=subtitle_font, fill=self.subtitle_color)
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_content(self, category_config: Dict, item_data: Dict):
        """Display the definition/content."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       self.background_color)
        draw = ImageDraw.Draw(img)
        
        # Load font
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
        except:
            font = ImageFont.load_default()
        
        # Get definition or content
        content = item_data.get('definition', item_data.get('content', item_data.get('text', 'No content')))
        
        # Simple word wrapping
        words = content.split()
        lines = []
        current_line = []
        max_width = self.display_manager.matrix.width - 4
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        # Draw lines (max 4-5 lines depending on height)
        y_pos = 2
        line_height = 7
        max_lines = (self.display_manager.matrix.height - 4) // line_height
        
        for i, line in enumerate(lines[:max_lines]):
            draw.text((2, y_pos), line, font=font, fill=self.content_color)
            y_pos += line_height
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_no_data(self):
        """Display message when no data is available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       self.background_color)
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "No Data", font=font, fill=(200, 200, 200))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_error(self):
        """Display error message."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       self.background_color)
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "Error", font=font, fill=(255, 0, 0))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 40.0)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'current_day': str(self.current_day) if self.current_day else None,
            'categories_loaded': len(self.current_items),
            'enabled_categories': [cat for cat in self.category_order 
                                  if self.categories.get(cat, {}).get('enabled', True)]
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_items = {}
        self.data_files = {}
        self.logger.info("Of The Day plugin cleaned up")

