"""
Music Plugin for LEDMatrix

Display now playing music from Spotify or YouTube Music with album art and track information.
Shows current song, artist, album, and playback status with smooth scrolling.

Features:
- Spotify integration
- YouTube Music integration
- Album artwork display
- Scrolling text for long titles
- Real-time playback status
- Auto-updating track info

API Version: 1.0.0
"""

import logging
import time
import threading
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import requests
from io import BytesIO

from src.plugin_system.base_plugin import BasePlugin

# Import music clients from plugin directory
import os
import sys

# Add plugin directory to path to import local clients
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from spotify_client import SpotifyClient
    from ytm_client import YTMClient
except ImportError:
    SpotifyClient = None
    YTMClient = None

logger = logging.getLogger(__name__)


class MusicPlugin(BasePlugin):
    """
    Music now playing plugin for displaying current playback.
    
    Supports Spotify and YouTube Music with automatic polling and updates.
    
    Configuration options:
        preferred_source (str): 'spotify' or 'ytm'
        POLLING_INTERVAL_SECONDS (float): Update polling interval
        YTM_COMPANION_URL (str): URL for YTM companion server
        show_album_art (bool): Display album artwork
        scroll_long_text (bool): Enable scrolling for long text
        scroll_speed (int): Speed of text scrolling
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the music plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        self.preferred_source = config.get('preferred_source', 'ytm')
        self.polling_interval = config.get('POLLING_INTERVAL_SECONDS', 2)
        self.ytm_url = config.get('YTM_COMPANION_URL', 'http://192.168.86.12:9863')
        self.show_album_art = config.get('show_album_art', True)
        self.scroll_long_text = config.get('scroll_long_text', True)
        self.scroll_speed = config.get('scroll_speed', 1)
        
        # State
        self.current_track_info = None
        self.album_art_image = None
        self.last_album_art_url = None
        self.scroll_position = 0
        self.last_update_time = 0
        
        # Music clients
        self.spotify = None
        self.ytm = None
        
        # Threading
        self.stop_event = threading.Event()
        self.poll_thread = None
        self.track_lock = threading.Lock()
        
        # Initialize clients
        self._initialize_clients()
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Music plugin initialized - Source: {self.preferred_source}")
    
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
                size_px=10,
                color=(255, 255, 255)
            )
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.artist",
                family="four_by_six",
                size_px=8,
                color=(200, 200, 200)
            )
            
            self.logger.info("Music plugin fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")
    
    def _initialize_clients(self):
        """Initialize music service clients."""
        if self.preferred_source == 'spotify' and SpotifyClient:
            try:
                # Get credentials from config or environment
                client_id = self.config.get('spotify_client_id') or os.environ.get('SPOTIFY_CLIENT_ID')
                client_secret = self.config.get('spotify_client_secret') or os.environ.get('SPOTIFY_CLIENT_SECRET')
                redirect_uri = self.config.get('spotify_redirect_uri') or os.environ.get('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')
                
                self.spotify = SpotifyClient(client_id, client_secret, redirect_uri)
                if not self.spotify.is_authenticated():
                    self.logger.warning("Spotify client not authenticated")
                    self.logger.warning("Run authenticate_spotify.py in the plugin directory")
                else:
                    self.logger.info("Spotify client initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize Spotify: {e}")
        
        elif self.preferred_source == 'ytm' and YTMClient:
            try:
                self.ytm = YTMClient(base_url=self.ytm_url)
                # Try to connect
                if self.ytm.connect_client(timeout=5):
                    self.logger.info("YTM client initialized and connected")
                else:
                    self.logger.warning("YTM client initialized but not connected")
                    self.logger.warning("Run authenticate_ytm.py in the plugin directory")
            except Exception as e:
                self.logger.error(f"Failed to initialize YTM: {e}")
    
    def _start_polling(self):
        """Start background polling thread."""
        if self.poll_thread is None or not self.poll_thread.is_alive():
            self.stop_event.clear()
            self.poll_thread = threading.Thread(target=self._poll_music, daemon=True)
            self.poll_thread.start()
            self.logger.info("Started music polling thread")
    
    def _stop_polling(self):
        """Stop background polling thread."""
        if self.poll_thread and self.poll_thread.is_alive():
            self.stop_event.set()
            self.poll_thread.join(timeout=5)
            self.logger.info("Stopped music polling thread")
    
    def _poll_music(self):
        """Background thread for polling music status."""
        while not self.stop_event.is_set():
            try:
                self.update()
                time.sleep(self.polling_interval)
            except Exception as e:
                self.logger.error(f"Error in polling thread: {e}")
                time.sleep(self.polling_interval)
    
    def update(self) -> None:
        """Update current track information."""
        try:
            track_info = None
            
            if self.preferred_source == 'spotify' and self.spotify:
                track_info = self._get_spotify_track()
            elif self.preferred_source == 'ytm' and self.ytm:
                track_info = self._get_ytm_track()
            
            with self.track_lock:
                if track_info != self.current_track_info:
                    self.current_track_info = track_info
                    self.scroll_position = 0  # Reset scroll on track change
                    
                    # Load album art if URL changed
                    if track_info:
                        art_url = track_info.get('album_art_url')
                        if art_url and art_url != self.last_album_art_url:
                            self._load_album_art(art_url)
                    
                    if track_info and track_info.get('is_playing'):
                        self.logger.info(f"Now playing: {track_info.get('title')} - {track_info.get('artist')}")
            
        except Exception as e:
            self.logger.error(f"Error updating music: {e}")
    
    def _get_spotify_track(self) -> Optional[Dict]:
        """Get current track from Spotify."""
        try:
            if not self.spotify or not self.spotify.is_authenticated():
                return None
            
            playback = self.spotify.get_current_playback()
            if not playback or not playback.get('is_playing'):
                return None
            
            item = playback.get('item', {})
            return {
                'title': item.get('name', 'Unknown'),
                'artist': ', '.join([artist['name'] for artist in item.get('artists', [])]),
                'album': item.get('album', {}).get('name', 'Unknown'),
                'album_art_url': item.get('album', {}).get('images', [{}])[0].get('url'),
                'is_playing': playback.get('is_playing', False),
                'source': 'Spotify'
            }
        except Exception as e:
            self.logger.error(f"Error getting Spotify track: {e}")
            return None
    
    def _get_ytm_track(self) -> Optional[Dict]:
        """Get current track from YouTube Music."""
        try:
            if not self.ytm:
                return None
            
            # YTM client has its own polling mechanism
            track_data = self.ytm.get_current_track()
            if not track_data or not track_data.get('is_playing'):
                return None
            
            return {
                'title': track_data.get('title', 'Unknown'),
                'artist': track_data.get('artist', 'Unknown'),
                'album': track_data.get('album', 'Unknown'),
                'album_art_url': track_data.get('album_art_url'),
                'is_playing': track_data.get('is_playing', False),
                'source': 'YouTube Music'
            }
        except Exception as e:
            self.logger.error(f"Error getting YTM track: {e}")
            return None
    
    def _load_album_art(self, url: str):
        """Load album artwork from URL."""
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            img = Image.open(BytesIO(response.content))
            
            # Resize to fit half of display
            art_size = min(self.display_manager.matrix.height, 
                          self.display_manager.matrix.width // 2)
            img = img.resize((art_size, art_size), Image.Resampling.LANCZOS)
            
            # Slightly dim the album art so text is more visible
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(0.7)
            
            self.album_art_image = img
            self.last_album_art_url = url
            
        except Exception as e:
            self.logger.error(f"Error loading album art: {e}")
            self.album_art_image = None
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display music information.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        with self.track_lock:
            track_info = self.current_track_info
        
        if not track_info or not track_info.get('is_playing'):
            self._display_nothing_playing()
            return
        
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            # Create display image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            
            # Draw album art if available
            art_offset = 0
            if self.show_album_art and self.album_art_image:
                img.paste(self.album_art_image, (0, 0))
                art_offset = self.album_art_image.width + 2
            
            # Draw text info
            draw = ImageDraw.Draw(img)
            
            # Load fonts
            try:
                title_font = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 8)
                info_font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
            except:
                title_font = ImageFont.load_default()
                info_font = ImageFont.load_default()
            
            # Draw title
            title = track_info.get('title', 'Unknown')
            if self.scroll_long_text:
                title = self._draw_scrolling_text(draw, title, art_offset + 2, 2, 
                                                 matrix_width - art_offset - 4, title_font, (255, 255, 255))
            else:
                draw.text((art_offset + 2, 2), title[:20], font=title_font, fill=(255, 255, 255))
            
            # Draw artist
            artist = track_info.get('artist', 'Unknown')
            draw.text((art_offset + 2, 12), artist[:30], font=info_font, fill=(200, 200, 200))
            
            # Draw album
            album = track_info.get('album', 'Unknown')
            draw.text((art_offset + 2, 20), album[:30], font=info_font, fill=(150, 150, 150))
            
            # Update scroll position
            if self.scroll_long_text:
                self.scroll_position += self.scroll_speed
            
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            
        except Exception as e:
            self.logger.error(f"Error displaying music: {e}")
    
    def _draw_scrolling_text(self, draw, text, x, y, max_width, font, color):
        """Draw scrolling text if it exceeds max width."""
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        
        if text_width <= max_width:
            draw.text((x, y), text, font=font, fill=color)
            return text
        
        # Calculate scroll position
        scroll_offset = self.scroll_position % (text_width + max_width)
        draw_x = x + max_width - scroll_offset
        
        draw.text((draw_x, y), text, font=font, fill=color)
        return text
    
    def _display_nothing_playing(self):
        """Display message when nothing is playing."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "No Music", font=font, fill=(150, 150, 150))
        draw.text((5, 20), "Playing", font=font, fill=(150, 150, 150))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def on_enable(self) -> None:
        """Called when plugin is enabled."""
        super().on_enable()
        self._start_polling()
    
    def on_disable(self) -> None:
        """Called when plugin is disabled."""
        super().on_disable()
        self._stop_polling()
    
    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 30.0)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        with self.track_lock:
            info.update({
                'preferred_source': self.preferred_source,
                'is_playing': bool(self.current_track_info and self.current_track_info.get('is_playing')),
                'current_track': self.current_track_info.get('title') if self.current_track_info else None,
                'current_artist': self.current_track_info.get('artist') if self.current_track_info else None
            })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self._stop_polling()
        self.current_track_info = None
        self.album_art_image = None
        self.logger.info("Music plugin cleaned up")

