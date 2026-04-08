"""
YouTube Stats Plugin for LEDMatrix

Display YouTube channel statistics including subscriber count, total views, and channel name.
Shows channel logo, name, subscriber count, and total views on the LED matrix.

API Version: 1.0.0
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
import requests

from src.plugin_system.base_plugin import BasePlugin

class YouTubeStatsPlugin(BasePlugin):
    """
    YouTube Stats plugin for LEDMatrix.
    
    Displays YouTube channel statistics including:
    - Channel name
    - Subscriber count
    - Total view count
    
    Configuration options:
        channel_id (str): YouTube channel ID (required)
        api_key (str): YouTube Data API v3 key (stored in secrets)
        update_interval (int): Update interval in seconds (default: 300)
        display_duration (float): Display duration in seconds (default: 15)
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the YouTube Stats plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        self.channel_id = config.get('channel_id', '')
        self.api_key = config.get('api_key', '')  # From merged secrets
        self.update_interval_config = config.get('update_interval', 300)
        
        # State
        self.channel_stats: Optional[Dict[str, Any]] = None
        self.font = None
        self.youtube_logo = None
        self.last_displayed_stats: Optional[Dict[str, Any]] = None  # Track last displayed to prevent unnecessary redraws
        self._api_key_error: Optional[str] = None  # Set when API key is bad/expired
        
        # Initialize display components
        if self.enabled:
            self._initialize_display()
            self.logger.info("YouTube Stats plugin initialized")
        else:
            self.logger.info("YouTube Stats plugin disabled")
    
    def _initialize_display(self):
        """Initialize display components (font and logo)."""
        try:
            # Load font - try multiple resolution strategies
            font_path = "assets/fonts/PressStart2P-Regular.ttf"
            resolved_font_path = None
            
            # Strategy 1: Try as-is (if running from project root)
            if os.path.exists(font_path):
                resolved_font_path = font_path
            else:
                # Strategy 2: Try relative to current working directory
                cwd_path = os.path.join(os.getcwd(), font_path)
                if os.path.exists(cwd_path):
                    resolved_font_path = cwd_path
                else:
                    # Strategy 3: Try relative to plugin directory's parent (project root)
                    plugin_dir = Path(__file__).parent
                    project_root = plugin_dir.parent.parent
                    project_path = project_root / font_path
                    if project_path.exists():
                        resolved_font_path = str(project_path)
            
            if resolved_font_path and os.path.exists(resolved_font_path):
                self.font = ImageFont.truetype(resolved_font_path, 8)
                self.logger.info(f"Loaded font: {resolved_font_path}")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
                self.font = ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading font: {e}")
            self.font = ImageFont.load_default()
        
        # Load YouTube logo
        try:
            logo_path = "assets/youtube_logo.png"
            resolved_logo_path = None
            
            # Try multiple resolution strategies
            if os.path.exists(logo_path):
                resolved_logo_path = logo_path
            else:
                cwd_path = os.path.join(os.getcwd(), logo_path)
                if os.path.exists(cwd_path):
                    resolved_logo_path = cwd_path
                else:
                    plugin_dir = Path(__file__).parent
                    project_root = plugin_dir.parent.parent
                    project_path = project_root / logo_path
                    if project_path.exists():
                        resolved_logo_path = str(project_path)
            
            if resolved_logo_path and os.path.exists(resolved_logo_path):
                self.youtube_logo = Image.open(resolved_logo_path)
                self.logger.info(f"Loaded YouTube logo: {resolved_logo_path}")
            else:
                self.logger.error(f"YouTube logo not found: {logo_path}")
                self.enabled = False
        except Exception as e:
            self.logger.error(f"Error loading YouTube logo: {e}")
            self.enabled = False
    
    def _get_channel_stats(self) -> Optional[Dict[str, Any]]:
        """Fetch channel statistics from YouTube API."""
        if not self.api_key:
            self.logger.error("YouTube API key not configured")
            return None
        
        if not self.channel_id:
            self.logger.error("YouTube channel ID not configured")
            return None
        
        # Try cache first
        cache_key = f"{self.plugin_id}_channel_stats"
        cached = self.cache_manager.get(cache_key, max_age=self.update_interval_config)
        if cached:
            self.logger.debug("Using cached channel stats")
            return cached
        
        url = f"https://www.googleapis.com/youtube/v3/channels?part=statistics,snippet&id={self.channel_id}&key={self.api_key}"
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            self._api_key_error = None  # Clear any previous error
            data = response.json()

            if 'items' in data and data['items']:
                channel = data['items'][0]
                stats = {
                    'title': channel['snippet']['title'],
                    'subscribers': int(channel['statistics']['subscriberCount']),
                    'views': int(channel['statistics']['viewCount'])
                }

                # Cache the result
                self.cache_manager.set(cache_key, stats, ttl=self.update_interval_config)
                self.logger.info(f"Fetched stats for channel: {stats['title']}")
                return stats
            else:
                self.logger.warning(f"No channel data found for channel ID: {self.channel_id}")
                return None
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (400, 401, 403):
                self._api_key_error = "YouTube API key is invalid or expired. Update your API key in Settings > Secrets."
                self.logger.error(self._api_key_error)
            else:
                self._api_key_error = None
                self.logger.error("Error fetching YouTube stats (HTTP %s)", status_code)
            return None
        except requests.exceptions.RequestException as e:
            self._api_key_error = None
            self.logger.error("Error fetching YouTube stats: %s", type(e).__name__)
            return None
        except (KeyError, ValueError, TypeError) as e:
            self._api_key_error = None
            self.logger.error("Error parsing YouTube API response: %s", e)
            return None
    
    def _create_display(self, channel_stats: Dict[str, Any]) -> Optional[Image.Image]:
        """Create the display image with channel statistics."""
        if not channel_stats or not self.youtube_logo or not self.font:
            return None
        
        try:
            # Create a new image with the matrix dimensions
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            image = Image.new('RGB', (matrix_width, matrix_height))
            draw = ImageDraw.Draw(image)
            
            # Calculate logo dimensions - 60% of display height to ensure text fits
            logo_height = int(matrix_height * 0.6)
            logo_width = int(self.youtube_logo.width * (logo_height / self.youtube_logo.height))
            resized_logo = self.youtube_logo.resize((logo_width, logo_height))
            
            # Position logo on the left with padding
            logo_x = 2  # Small padding from left edge
            logo_y = (matrix_height - logo_height) // 2  # Center vertically
            
            # Paste the logo
            image.paste(resized_logo, (logo_x, logo_y))
            
            # Calculate right section width and starting position
            right_section_x = logo_x + logo_width + 4  # Start after logo with some padding
            
            # Calculate text positions
            line_height = 10  # Approximate line height for PressStart2P font at size 8
            total_text_height = line_height * 3  # 3 lines of text
            start_y = (matrix_height - total_text_height) // 2
            
            # Draw channel name (top)
            channel_name = channel_stats['title']
            # Truncate channel name if too long
            max_chars = (matrix_width - right_section_x - 4) // 8  # 8 pixels per character
            if len(channel_name) > max_chars:
                channel_name = channel_name[:max_chars-3] + "..."
            name_bbox = draw.textbbox((0, 0), channel_name, font=self.font)
            name_width = name_bbox[2] - name_bbox[0]
            name_x = right_section_x + ((matrix_width - right_section_x - name_width) // 2)
            draw.text((name_x, start_y), channel_name, font=self.font, fill=(255, 255, 255))
            
            # Draw subscriber count (middle)
            subs_text = f"{channel_stats['subscribers']:,} subs"
            subs_bbox = draw.textbbox((0, 0), subs_text, font=self.font)
            subs_width = subs_bbox[2] - subs_bbox[0]
            subs_x = right_section_x + ((matrix_width - right_section_x - subs_width) // 2)
            draw.text((subs_x, start_y + line_height), subs_text, font=self.font, fill=(255, 255, 255))
            
            # Draw view count (bottom)
            views_text = f"{channel_stats['views']:,} views"
            views_bbox = draw.textbbox((0, 0), views_text, font=self.font)
            views_width = views_bbox[2] - views_bbox[0]
            views_x = right_section_x + ((matrix_width - right_section_x - views_width) // 2)
            draw.text((views_x, start_y + (line_height * 2)), views_text, font=self.font, fill=(255, 255, 255))
            
            return image
        except Exception as e:
            self.logger.error(f"Error creating display image: {e}", exc_info=True)
            return None
    
    def update(self) -> None:
        """Fetch/update data for this plugin."""
        if not self.enabled:
            return
        
        self.channel_stats = self._get_channel_stats()
    
    def display(self, force_clear: bool = False) -> None:
        """Render this plugin's display."""
        if not self.enabled:
            return
        
        # Fetch stats if we don't have them yet
        if not self.channel_stats:
            self.update()
        
        if self.channel_stats:
            # Check if we need to redraw (prevent flashing)
            # Only redraw if the stats changed or force_clear is True
            stats_changed = (
                self.last_displayed_stats is None or
                self.last_displayed_stats.get('subscribers') != self.channel_stats.get('subscribers') or
                self.last_displayed_stats.get('views') != self.channel_stats.get('views') or
                self.last_displayed_stats.get('title') != self.channel_stats.get('title')
            )
            
            if not force_clear and not stats_changed:
                return  # No change, skip redraw
            
            if force_clear:
                self.display_manager.clear()
            
            display_image = self._create_display(self.channel_stats)
            if display_image:
                self.display_manager.image = display_image
                self.display_manager.update_display()
                
                # Track what we displayed to prevent unnecessary redraws
                self.last_displayed_stats = self.channel_stats.copy()
                self.logger.debug(f"Displayed stats for channel: {self.channel_stats.get('title')}")
        else:
            if self._api_key_error:
                self.logger.warning(self._api_key_error)
                self._show_error_on_display("YT: Update API Key")
            else:
                self.logger.warning("No channel stats available to display")

    def _show_error_on_display(self, message: str) -> None:
        """Render a short error message on the LED matrix."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            image = Image.new('RGB', (matrix_width, matrix_height))
            draw = ImageDraw.Draw(image)
            font = self.font or ImageFont.load_default()
            bbox = draw.textbbox((0, 0), message, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (matrix_width - text_w) // 2
            y = (matrix_height - text_h) // 2
            draw.text((x, y), message, font=font, fill=(255, 80, 80))
            self.display_manager.image = image
            self.display_manager.update_display()
        except Exception as e:
            self.logger.debug(f"Could not show error on display: {e}")

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False
        
        # Check for required channel_id
        if not self.channel_id:
            self.logger.error("channel_id is required but not configured")
            return False
        
        # Check for API key (from merged secrets)
        if not self.api_key:
            self.logger.error("api_key is required but not configured in secrets")
            return False
        
        return True
