"""
Music Player Plugin for LEDMatrix

Real-time now playing display for Spotify and YouTube Music with album art,
scrolling text, and progress bars. Migrated from src/old_managers/music_manager.py
with flattened configuration structure for plugin compatibility.
"""

import time
import threading
from enum import Enum, auto
import logging
import json
import os
from io import BytesIO
import requests
from typing import Union, Dict, Any
from PIL import Image, ImageEnhance, ImageFont
import queue

# Import client modules
from spotify_client import SpotifyClient
from ytm_client import YTMClient

# Import base plugin class
from src.plugin_system.base_plugin import BasePlugin

# Adaptive layout system (opt-in via layout_mode: "adaptive"). Older
# LEDMatrix cores don't ship it — fall back silently to the classic layout.
# MusicPlugin is itself a BasePlugin, so it gets self.layout for free —
# unlike football-scoreboard's GameRenderer (a standalone helper class),
# no separate LayoutContext/FontManager wiring is needed here.
try:
    from src.adaptive_layout import FontStep, LADDER_ARCADE, media_row
    ADAPTIVE_AVAILABLE = True
    # TTF-only, same verified-crisp rungs as the other adaptive plugins:
    # PressStart2P only rasterizes without antialiasing at exact multiples
    # of its 8px design grid; 4x6-font is crisp only at 7px (not 6, despite
    # measuring the same ink height) — see measure_font_crispness.
    ADAPTIVE_LADDER_TEXT = LADDER_ARCADE + (
        FontStep("4x6-font", 7),
    )
except ImportError:
    ADAPTIVE_AVAILABLE = False
    ADAPTIVE_LADDER_TEXT = None

# Shared element-style resolver (newer cores): one implementation of font
# loading and the user-font-override check, referenced against this
# plugin's own config_schema.json. Older cores use the local code below.
try:
    from src.element_style import ElementStyleResolver, defaults_from_schema_file
    STYLE_AVAILABLE = True
except ImportError:
    STYLE_AVAILABLE = False

# Configure logging
logger = logging.getLogger(__name__)

class MusicSource(Enum):
    NONE = auto()
    SPOTIFY = auto()
    YTM = auto()

class MusicPlugin(BasePlugin):
    """
    Music Player Plugin for LEDMatrix
    
    Displays real-time now playing information from Spotify and YouTube Music
    with album art, scrolling text, and progress bars. Supports both sources
    with automatic switching and seamless display updates.
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any], 
                 display_manager, cache_manager, plugin_manager):
        """Initialize the music plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Music-specific state
        self.spotify = None
        self.ytm = None
        self.current_track_info = None
        self.current_source = MusicSource.NONE
        self.polling_interval = 2  # Default
        self.preferred_source = "spotify"  # Default
        self.stop_event = threading.Event()
        self.track_info_lock = threading.Lock()
        
        # Display related attributes
        self.album_art_image = None
        self.last_album_art_url = None
        self.scroll_position_title = 0
        self.scroll_position_artist = 0
        self.scroll_position_album = 0
        self.title_scroll_tick = 0
        
        # Track update logging throttling
        self.last_track_log_time = 0
        self.last_logged_track_title = None
        self.track_log_interval = 5.0  # Log track updates every 5 seconds max
        self.artist_scroll_tick = 0
        self.album_scroll_tick = 0
        
        # Scroll configuration (will be loaded from config)
        self.scroll_config = {
            'title': {'enabled': True, 'speed': 5, 'separator': '   ', 'initial_pause_frames': 0, 'end_pause_frames': 0},
            'artist': {'enabled': True, 'speed': 5, 'separator': '   ', 'initial_pause_frames': 0, 'end_pause_frames': 0},
            'album': {'enabled': True, 'speed': 5, 'separator': '   ', 'initial_pause_frames': 0, 'end_pause_frames': 0}
        }
        
        # Scroll state tracking for pause logic
        self.title_initial_pause_counter = 0
        self.title_end_pause_counter = 0
        self.title_at_end = False
        self.artist_initial_pause_counter = 0
        self.artist_end_pause_counter = 0
        self.artist_at_end = False
        self.album_initial_pause_counter = 0
        self.album_end_pause_counter = 0
        self.album_at_end = False
        self.is_music_display_active = False
        self.is_currently_showing_nothing_playing = False
        self._needs_immediate_full_refresh = False
        self.ytm_event_data_queue = queue.Queue(maxsize=1)
        
        self.poll_thread = None
        
        # Additional attributes for display management
        self.last_periodic_refresh_time = 0
        self._last_nothing_playing_log_time = 0
        
        # Track 'Nothing Playing' duration for logging
        self._nothing_playing_since_ts = None
        
        # Load configuration with flattened access
        self._load_config()
        self._initialize_clients()

        # Load custom fonts from config
        self._load_custom_fonts()

        # Adaptive layout (beta, opt-in): scales title/artist/album fonts to
        # the panel instead of the classic fixed sizes. Default "classic"
        # renders byte-identically to previous releases.
        self.layout_mode = config.get('layout_mode', 'classic')
        self._adaptive = ADAPTIVE_AVAILABLE and self.layout_mode == 'adaptive'
        if self.layout_mode == 'adaptive' and not ADAPTIVE_AVAILABLE:
            self.logger.warning(
                "layout_mode 'adaptive' requires a LEDMatrix core with the "
                "adaptive layout system; falling back to classic layout"
            )
        
        self.logger.info(f"Music plugin initialized - Source: {self.preferred_source}, Enabled: {self.enabled}, Live Priority: {self.config.get('live_priority', False)}")

    def _load_config(self):
        """Load configuration with flattened access (no nested 'music' key)."""
        default_interval = 2
        self.enabled = False  # Assume disabled until config proves otherwise

        if self.config is None:
            self.logger.warning("No config provided to MusicPlugin. Music plugin disabled.")
            return

        try:
            # Flattened config access - no nested 'music' key
            self.enabled = self.config.get("enabled", False)
            if not self.enabled:
                self.logger.info("Music plugin is disabled in config.")
                return

            self.polling_interval = self.config.get("polling_interval_seconds", default_interval)
            configured_source = self.config.get("preferred_source", "spotify").lower()

            if configured_source in ["spotify", "ytm"]:
                self.preferred_source = configured_source
                self.logger.info(f"Music plugin enabled. Polling interval: {self.polling_interval}s. Preferred source: {self.preferred_source}")
            else:
                self.logger.warning(f"Invalid 'preferred_source' ('{configured_source}') in config. Must be 'spotify' or 'ytm'. Music plugin disabled.")
                self.enabled = False
                return
            
            # Load scroll configuration
            scroll_config_raw = self.config.get("text_scrolling", {})
            for field in ['title', 'artist', 'album']:
                field_config = scroll_config_raw.get(field, {})
                self.scroll_config[field] = {
                    'enabled': field_config.get('enabled', True),
                    'speed': field_config.get('speed', 5),
                    'separator': field_config.get('separator', '   '),
                    'initial_pause_frames': field_config.get('initial_pause_frames', 0),
                    'end_pause_frames': field_config.get('end_pause_frames', 0)
                }
                self.logger.debug(f"Scroll config for {field}: {self.scroll_config[field]}")

        except Exception as e:
            self.logger.error(f"Error loading music config: {e}. Music plugin disabled.")
            self.enabled = False
    
    def _load_custom_font_from_element_config(self, element_config: Dict[str, Any], default_size: int = 8) -> ImageFont.FreeTypeFont:
        """
        Load a custom font from an element configuration dictionary.
        
        Args:
            element_config: Configuration dict for a single element containing 'font' and 'font_size' keys
            default_size: Default font size if not specified in config
            
        Returns:
            PIL ImageFont object
        """
        # Get font name and size, with defaults
        font_name = element_config.get('font', 'PressStart2P-Regular.ttf')
        font_size = int(element_config.get('font_size', default_size))  # Ensure integer for PIL
        
        # Build font path
        font_path = os.path.join('assets', 'fonts', font_name)
        
        # Try to load the font
        try:
            if os.path.exists(font_path):
                # Try loading as TTF first (works for both TTF and some BDF files with PIL)
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    self.logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    # PIL's ImageFont.truetype() can sometimes handle BDF files
                    # If it fails, we'll fall through to the default font
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        self.logger.debug(f"Loaded BDF font: {font_name} at size {font_size}")
                        return font
                    except Exception:
                        self.logger.warning(f"Could not load BDF font {font_name} with PIL, using default")
                        # Fall through to default
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, using default")
        
        # Fall back to default font
        default_font_path = os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf')
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                self.logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()
    
    def _load_custom_fonts(self):
        """Load custom fonts from config customization section."""
        # Initialize font attributes with defaults (will be overridden if config exists)
        self.title_font = None
        self.artist_font = None
        self.album_font = None
        
        # Get customization config, with backward compatibility
        customization = self.config.get('customization', {})
        
        if not customization:
            # No customization config, use display_manager fonts as fallback
            self.logger.debug("No customization config found, using display_manager fonts")
            return
        
        if STYLE_AVAILABLE:
            resolver = self._get_element_style_resolver()
            self.title_font = resolver.style(
                'title_text', classic_font='PressStart2P-Regular.ttf',
                classic_size=8).font
            self.artist_font = resolver.style(
                'artist_text', classic_font='PressStart2P-Regular.ttf',
                classic_size=7).font
            self.album_font = resolver.style(
                'album_text', classic_font='PressStart2P-Regular.ttf',
                classic_size=7).font
            self.logger.info("Loaded custom fonts via element-style resolver")
            return

        # Older cores (no src.element_style): the original local loader.
        # Load fonts from config with defaults for backward compatibility
        title_config = customization.get('title_text', {})
        artist_config = customization.get('artist_text', {})
        album_config = customization.get('album_text', {})

        try:
            self.title_font = self._load_custom_font_from_element_config(title_config, default_size=8)
            self.artist_font = self._load_custom_font_from_element_config(artist_config, default_size=7)
            self.album_font = self._load_custom_font_from_element_config(album_config, default_size=7)
            self.logger.info("Successfully loaded custom fonts from config")
        except Exception as e:
            self.logger.error(f"Error loading custom fonts: {e}, using display_manager fonts")

    def _get_element_style_resolver(self):
        """Shared resolver, referenced against this plugin's own
        config_schema.json so the user-override check works in every context
        (production, harness, dev server — no schema manager needed).

        NOTE: deliberately NOT BasePlugin.style_resolver — that property
        sources defaults from plugin_manager.schema_manager, which is absent
        under the test harness's mocks, and it caches on _style_resolver,
        which this must not collide with. Rebuilt when the config dict is
        swapped (on_config_change replaces self.config).
        """
        resolver = getattr(self, '_element_style_resolver', None)
        if resolver is None or resolver._config is not self.config:
            schema_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'config_schema.json')
            resolver = ElementStyleResolver(
                self.config, defaults_from_schema_file(schema_path))
            self._element_style_resolver = resolver
        return resolver

    # (font filename, size) the config_schema.json declares as each
    # element's default — matching these, not merely a key being *present*,
    # is what "user set it" has to mean, because the web UI's save flow
    # (schema_manager.merge_with_defaults) writes the FULL schema default
    # object into config.json on every save, for every plugin, whether or
    # not the user touched that section. Only used on older cores — with
    # src.element_style available, the resolver reads the schema file itself.
    _CLASSIC_FONT_DEFAULTS = {
        'title_text': ('PressStart2P-Regular.ttf', 8),
        'artist_text': ('5x7.bdf', 7),
        'album_text': ('5x7.bdf', 7),
    }

    def _user_font_set(self, element_key: str) -> bool:
        """True when the user's configured font/font_size for this element
        genuinely differs from the schema default — adaptive mode must
        respect a real override, but not a schema default that merely
        happens to be present in a saved config."""
        if STYLE_AVAILABLE:
            classic_font, classic_size = self._CLASSIC_FONT_DEFAULTS.get(
                element_key, ('PressStart2P-Regular.ttf', 8))
            return self._get_element_style_resolver().style(
                element_key, classic_font=classic_font,
                classic_size=classic_size).user_forced
        element_config = self.config.get('customization', {}).get(element_key, {})
        default_font, default_size = self._CLASSIC_FONT_DEFAULTS.get(element_key, (None, None))
        configured_font = element_config.get('font')
        configured_size = element_config.get('font_size')
        font_differs = configured_font is not None and configured_font != default_font
        try:
            size_differs = configured_size is not None and int(configured_size) != default_size
        except (TypeError, ValueError):
            size_differs = False
        return font_differs or size_differs

    def _adaptive_text_layout(self, font_title, font_artist, font_album,
                              title_layout_config, artist_layout_config, album_layout_config,
                              text_area_x_start, text_area_width, matrix_height,
                              progress_bar_height, safe_y_percent):
        """Adaptive font + Y-position pick for the title/artist/album rows.

        Splits the vertical space above the progress bar into three equal
        rows and sizes each row's font to the largest crisp ladder rung
        whose LINE HEIGHT fits that row — height-only, not width, because
        long titles/artists/albums scroll rather than shrink to fit, the
        same way the album art already scales by height alone
        (album_art_size = matrix_height). User-forced fonts (an explicit
        customization.<element>.font/font_size) win over auto-sizing, and
        an explicit y_percent still overrides the row position, exactly
        like classic mode.
        """
        from src.adaptive_layout import Region

        top_margin = self.layout.px(1, minimum=1)
        gap = self.layout.px(1, minimum=1)
        available_h = max(3, matrix_height - progress_bar_height - top_margin - 1)
        rows = Region(text_area_x_start, top_margin, text_area_width, available_h).split_v(
            1, 1, 1, gap=gap)
        title_row, artist_row, album_row = rows

        def pick(element_key, classic_font, row):
            if self._user_font_set(element_key):
                return classic_font
            return self.layout.font_for_rows(1, row.h, ladder=ADAPTIVE_LADDER_TEXT).font

        font_title = pick('title_text', font_title, title_row)
        font_artist = pick('artist_text', font_artist, artist_row)
        font_album = pick('album_text', font_album, album_row)

        y_title = title_row.y
        y_artist = artist_row.y
        y_album = album_row.y
        if 'y_percent' in title_layout_config:
            y_title = int(matrix_height * safe_y_percent(title_layout_config['y_percent'], y_title / matrix_height))
        if 'y_percent' in artist_layout_config:
            y_artist = int(matrix_height * safe_y_percent(artist_layout_config['y_percent'], y_artist / matrix_height))
        if 'y_percent' in album_layout_config:
            y_album = int(matrix_height * safe_y_percent(album_layout_config['y_percent'], y_album / matrix_height))

        return font_title, font_artist, font_album, y_title, y_artist, y_album

    def _initialize_clients(self):
        """Initialize music clients based on configuration."""
        if not self.enabled:
            self.spotify = None
            self.ytm = None
            return

        self.logger.info("Initializing music clients...")

        # Initialize Spotify Client if needed
        if self.preferred_source == "spotify":
            try:
                self.spotify = SpotifyClient()
                if not self.spotify.is_authenticated():
                    self.logger.warning("Spotify client initialized but not authenticated. Please run authenticate_spotify.py if you want to use Spotify.")
                else:
                    self.logger.info("Spotify client authenticated.")
            except Exception as e:
                self.logger.error(f"Failed to initialize Spotify client: {e}")
                self.spotify = None
        else:
            self.spotify = None

        # Initialize YTM Client if needed
        if self.preferred_source == "ytm":
            try:
                self.ytm = YTMClient(update_callback=self._handle_ytm_direct_update)
                self.logger.info(f"YTMClient initialized. Connection will be managed on-demand. Configured URL: {self.ytm.base_url}")
            except Exception as e:
                self.logger.error(f"Failed to initialize YTM client: {e}")
                self.ytm = None
        else:
            self.ytm = None

    def _process_ytm_data_update(self, ytm_data, source_description: str):
        """
        Core processing logic for YTM data.
        Updates self.current_track_info, handles album art, queues data for display,
        and determines if the update is significant.

        Args:
            ytm_data: The raw data from YTM.
            source_description: A string for logging (e.g., "YTM Event", "YTM Activate Sync").

        Returns:
            tuple: (simplified_info, significant_change_detected)
        """
        # Verbose diagnostics about incoming event/state
        try:
            title_log = ytm_data.get('video', {}).get('title') if isinstance(ytm_data, dict) else None
            author_log = ytm_data.get('video', {}).get('author') if isinstance(ytm_data, dict) else None
            state_log = (ytm_data.get('player', {}).get('trackState') == 1) if isinstance(ytm_data, dict) else None
            self.logger.debug(f"_process_ytm_data_update[{source_description}]: incoming title='{title_log}', artist='{author_log}', is_playing={state_log}")
        except Exception:
            pass

        if not ytm_data:
            simplified_info = self.get_simplified_track_info(None, MusicSource.NONE)
        else:
            ytm_player_info = ytm_data.get('player', {})
            is_actually_playing_ytm = (ytm_player_info.get('trackState') == 1) and not ytm_player_info.get('adPlaying', False)
            simplified_info = self.get_simplified_track_info(ytm_data if is_actually_playing_ytm else None,
                                                           MusicSource.YTM if is_actually_playing_ytm else MusicSource.NONE)

        significant_change_detected = False
        processed_a_meaningful_update = False

        with self.track_info_lock:
            current_track_info_before_update_str = json.dumps(self.current_track_info) if self.current_track_info else "None"
            simplified_info_str = json.dumps(simplified_info)
            self.logger.debug(f"MusicPlugin._process_ytm_data_update ({source_description}): PRE-COMPARE - SimplifiedInfo: {simplified_info_str}, CurrentTrackInfo: {current_track_info_before_update_str}")

            if self.current_track_info is None and simplified_info.get('title') != 'Nothing Playing':
                significant_change_detected = True
                self.logger.debug(f"({source_description}): First valid track data, marking as significant.")
            elif self.current_track_info is not None and (
                simplified_info.get('title') != self.current_track_info.get('title') or
                simplified_info.get('artist') != self.current_track_info.get('artist') or
                simplified_info.get('album_art_url') != self.current_track_info.get('album_art_url') or
                simplified_info.get('is_playing') != self.current_track_info.get('is_playing')
            ):
                significant_change_detected = True
                self.logger.debug(f"({source_description}): Significant change (title/artist/art/is_playing) detected.")

            if simplified_info != self.current_track_info:
                processed_a_meaningful_update = True
                old_album_art_url = self.current_track_info.get('album_art_url') if self.current_track_info else None
                
                self.current_track_info = simplified_info
                self.logger.debug(f"MusicPlugin._process_ytm_data_update ({source_description}): POST-UPDATE (inside lock) - self.current_track_info now: {json.dumps(self.current_track_info)}")

                # Determine current source based on this update
                if simplified_info.get('source') == 'YouTube Music' and simplified_info.get('is_playing'):
                    self.current_source = MusicSource.YTM
                elif self.current_source == MusicSource.YTM and not simplified_info.get('is_playing'):
                    self.current_source = MusicSource.NONE
                elif simplified_info.get('source') == 'None':
                    self.current_source = MusicSource.NONE
                
                new_album_art_url = simplified_info.get('album_art_url')

                self.logger.debug(f"({source_description}) Track info comparison: simplified_info != self.current_track_info was TRUE.")
                self.logger.debug(f"({source_description}) Old Album Art URL: {old_album_art_url}, New Album Art URL: {new_album_art_url}")

                if new_album_art_url != old_album_art_url:
                    self.logger.info(f"({source_description}) Album art URL changed. Clearing self.album_art_image to force re-fetch.")
                    self.album_art_image = None
                    self.last_album_art_url = new_album_art_url
                elif not self.last_album_art_url and new_album_art_url:
                    self.logger.info(f"({source_description}) New album art URL appeared. Clearing image.")
                    self.album_art_image = None
                    self.last_album_art_url = new_album_art_url
                elif new_album_art_url is None and old_album_art_url is not None:
                    self.logger.info(f"({source_description}) Album art URL disappeared. Clearing image and URL.")
                    self.album_art_image = None
                    self.last_album_art_url = None
                elif self.current_track_info and self.current_track_info.get('album_art_url') and not self.last_album_art_url:
                    self.last_album_art_url = self.current_track_info.get('album_art_url')
                    self.album_art_image = None

                display_title = self.current_track_info.get('title', 'None')
                
                # Throttle track update logging to reduce spam
                current_time = time.time()
                should_log = False
                
                if (display_title != self.last_logged_track_title or 
                    current_time - self.last_track_log_time >= self.track_log_interval):
                    should_log = True
                    self.last_track_log_time = current_time
                    self.last_logged_track_title = display_title
                
                if should_log:
                    self.logger.info(f"({source_description}) Track info updated. Source: {self.current_source.name}. New Track: {display_title}")
                else:
                    self.logger.debug(f"({source_description}) Track info updated (throttled). Source: {self.current_source.name}. Track: {display_title}")
            else:
                processed_a_meaningful_update = False
                self.logger.debug(f"({source_description}) No change in simplified track info (simplified_info == self.current_track_info).")
                if self.current_track_info is None and simplified_info.get('title') != 'Nothing Playing':
                    significant_change_detected = True
                    processed_a_meaningful_update = True
                    self.current_track_info = simplified_info
                    display_title = simplified_info.get('title', 'None')
                    current_time = time.time()
                    
                    self.logger.info(f"({source_description}) First valid track data received (was None), marking significant. Track: {display_title}")
                    self.last_track_log_time = current_time
                    self.last_logged_track_title = display_title

        # Queueing logic for events
        if source_description in ["YTM Event", "YTM Activate Sync"]:
            try:
                while not self.ytm_event_data_queue.empty():
                    self.ytm_event_data_queue.get_nowait()
                self.ytm_event_data_queue.put_nowait(simplified_info)
                self.logger.debug(f"MusicPlugin._process_ytm_data_update ({source_description}): Put simplified_info (Title: {simplified_info.get('title')}) into ytm_event_data_queue.")
            except queue.Full:
                self.logger.warning(f"MusicPlugin._process_ytm_data_update ({source_description}): ytm_event_data_queue was full.")

        if significant_change_detected:
            self.logger.info(f"({source_description}) Significant track change detected. Signaling for an immediate full refresh of MusicPlugin display.")
            self._needs_immediate_full_refresh = True
        elif processed_a_meaningful_update:
            self.logger.debug(f"({source_description}) Minor track data update (e.g. progress). Display will update without full refresh.")

        return simplified_info, significant_change_detected

    def activate_music_display(self):
        """Activate music display and connect YTM if needed."""
        self.logger.info("Music display activated.")
        self.is_music_display_active = True
        
        if self.ytm and self.preferred_source == "ytm":
            if not self.ytm.is_connected:
                self.logger.info("Attempting to connect YTM client due to music display activation.")
                if self.ytm.connect_client(timeout=10):
                    self.logger.info("YTM client connected successfully on display activation.")
                    latest_data = self.ytm.get_current_track()
                    if latest_data:
                        self.logger.debug("YTM Activate Sync: Processing current track data after successful connection.")
                        self._process_ytm_data_update(latest_data, "YTM Activate Sync")
                else:
                    self.logger.warning("YTM client failed to connect on display activation.")
            else:
                self.logger.debug("YTM client already connected during music display activation. Syncing state.")
                latest_data = self.ytm.get_current_track()
                if latest_data:
                    self._process_ytm_data_update(latest_data, "YTM Activate Sync")
                else:
                    self.logger.debug("YTM Activate Sync: No track data available from connected YTM client.")
                    self._process_ytm_data_update(None, "YTM Activate Sync (No Data)")

    def deactivate_music_display(self):
        """Deactivate music display and disconnect YTM."""
        self.logger.info("Music display deactivated.")
        self.is_music_display_active = False
        
        if self.ytm and self.ytm.is_connected:
            self.logger.info("Disconnecting YTM client due to music display deactivation.")
            self.ytm.disconnect_client()

    def _handle_ytm_direct_update(self, ytm_data):
        """Handle a direct state update from YTMClient."""
        raw_title_from_event = ytm_data.get('video', {}).get('title', 'No Title') if isinstance(ytm_data, dict) else 'Data not a dict'
        self.logger.debug(f"MusicPlugin._handle_ytm_direct_update: RAW EVENT DATA - Title: '{raw_title_from_event}'")

        if not self.enabled or not self.is_music_display_active:
            self.logger.debug("Skipping YTM direct update: Plugin disabled or music display not active.")
            return

        if self.preferred_source != "ytm":
            self.logger.debug(f"Skipping YTM direct update: Preferred source is '{self.preferred_source}', not 'ytm'.")
            return
        
        # Process the data and get outcomes
        self._process_ytm_data_update(ytm_data, "YTM Event")

    def _fetch_and_resize_image(self, url: str, target_size: tuple) -> Union[Image.Image, None]:
        """Fetch an image from a URL, resize it, and return a PIL Image object."""
        if not url:
            return None
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()

            img_data = BytesIO(response.content)
            img = Image.open(img_data)
            
            # Ensure image is RGB for compatibility with the matrix
            img = img.convert("RGB") 
            
            img.thumbnail(target_size, Image.Resampling.LANCZOS)

            # Enhance contrast
            enhancer_contrast = ImageEnhance.Contrast(img)
            img = enhancer_contrast.enhance(1.3)

            # Enhance saturation (Color)
            enhancer_saturation = ImageEnhance.Color(img)
            img = enhancer_saturation.enhance(1.3)
            
            final_img = Image.new("RGB", target_size, (0,0,0))
            paste_x = (target_size[0] - img.width) // 2
            paste_y = (target_size[1] - img.height) // 2
            final_img.paste(img, (paste_x, paste_y))
            
            return final_img
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching image from {url}: {e}")
            return None
        except IOError as e:
            self.logger.error(f"Error processing image from {url}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching/processing image {url}: {e}")
            return None

    def _poll_music_data(self):
        """Continuously poll music sources for updates, respecting preferences."""
        if not self.enabled:
            self.logger.warning("Polling attempted while music plugin is disabled. Stopping polling thread.")
            return

        while not self.stop_event.is_set():
            significant_change_for_callback = False
            simplified_info_for_callback = None

            if self.preferred_source == "spotify" and self.spotify and self.spotify.is_authenticated():
                try:
                    spotify_track = self.spotify.get_current_track()
                    if spotify_track and spotify_track.get('is_playing'):
                        simplified_info_poll = self.get_simplified_track_info(spotify_track, MusicSource.SPOTIFY)
                        
                        with self.track_info_lock:
                            if simplified_info_poll != self.current_track_info:
                                # Check for significant changes
                                significant_change_detected = False
                                if self.current_track_info is None and simplified_info_poll.get('title') != 'Nothing Playing':
                                    significant_change_detected = True
                                    self.logger.debug("Polling Spotify: First valid track data, marking as significant.")
                                elif self.current_track_info is not None and (
                                    simplified_info_poll.get('title') != self.current_track_info.get('title') or
                                    simplified_info_poll.get('artist') != self.current_track_info.get('artist') or
                                    simplified_info_poll.get('album_art_url') != self.current_track_info.get('album_art_url') or
                                    simplified_info_poll.get('is_playing') != self.current_track_info.get('is_playing')
                                ):
                                    significant_change_detected = True
                                    self.logger.debug("Polling Spotify: Significant change (title/artist/art/is_playing) detected.")
                                else:
                                    self.logger.debug("Polling Spotify: Only progress changed, not significant.")
                                
                                self.current_track_info = simplified_info_poll
                                self.current_source = MusicSource.SPOTIFY
                                significant_change_for_callback = significant_change_detected
                                simplified_info_for_callback = simplified_info_poll.copy()
                                
                                if significant_change_detected:
                                    self._needs_immediate_full_refresh = True
                                    self.logger.info("Polling Spotify: Significant change detected.")
                                    
                                else:
                                    self.logger.debug("Polling Spotify: Minor update (progress only), no full refresh needed.")
                                
                                # Handle album art for Spotify
                                old_album_art_url = self.current_track_info.get('album_art_url_prev_spotify')
                                new_album_art_url = simplified_info_poll.get('album_art_url')
                                if new_album_art_url != old_album_art_url:
                                    self.album_art_image = None
                                    self.last_album_art_url = new_album_art_url
                                self.current_track_info['album_art_url_prev_spotify'] = new_album_art_url

                                self.logger.debug(f"Polling Spotify: Active track - {spotify_track.get('item', {}).get('name')}")
                            else:
                                self.logger.debug("Polling Spotify: No change in simplified track info.")
                        
                    else:
                        self.logger.debug("Polling Spotify: No active track or player paused.")
                        # If Spotify was playing and now it's not
                        with self.track_info_lock:
                            if self.current_source == MusicSource.SPOTIFY:
                                simplified_info_for_callback = self.get_simplified_track_info(None, MusicSource.NONE)
                                self.current_track_info = simplified_info_for_callback
                                self.current_source = MusicSource.NONE
                                significant_change_for_callback = True
                                self._needs_immediate_full_refresh = True
                                self.album_art_image = None
                                self.last_album_art_url = None
                                self.logger.info("Polling Spotify: Player stopped. Updating to Nothing Playing.")
                                

                except Exception as e:
                    self.logger.error(f"Error polling Spotify: {e}")
                    if "token" in str(e).lower():
                        self.logger.warning("Spotify auth token issue detected during polling.")
            
            elif self.preferred_source == "ytm" and self.ytm:
                if self.ytm.is_connected:
                    try:
                        ytm_track_data = self.ytm.get_current_track()
                        simplified_info_for_callback, significant_change_for_callback = self._process_ytm_data_update(ytm_track_data, "YTM Poll")
                        if significant_change_for_callback:
                            self.logger.debug(f"Polling YTM: Change detected via _process_ytm_data_update. Title: {simplified_info_for_callback.get('title')}")
                            
                        else:
                            self.logger.debug(f"Polling YTM: No change detected via _process_ytm_data_update. Title: {simplified_info_for_callback.get('title')}")

                    except Exception as e:
                        self.logger.error(f"Error during YTM poll processing: {e}")
                else:
                    self.logger.debug("Skipping YTM poll: Client not connected. Will attempt reconnect on next cycle if display active.")
                    if self.is_music_display_active:
                        self.logger.info("YTM is preferred and display active, attempting reconnect during poll cycle.")
                        if self.ytm.connect_client(timeout=5):
                            self.logger.info("YTM reconnected during poll cycle. Will process data on next poll/event.")
                            latest_data = self.ytm.get_current_track()
                            if latest_data:
                                simplified_info_for_callback, significant_change_for_callback = self._process_ytm_data_update(latest_data, "YTM Poll Reconnect Sync")
                        else:
                            self.logger.warning("YTM failed to reconnect during poll cycle.")
                            with self.track_info_lock:
                                if self.current_source == MusicSource.YTM:
                                    simplified_info_for_callback = self.get_simplified_track_info(None, MusicSource.NONE)
                                    self.current_track_info = simplified_info_for_callback
                                    self.current_source = MusicSource.NONE
                                    significant_change_for_callback = True
                                    self.album_art_image = None
                                    self.last_album_art_url = None
                                    self.logger.info("Polling YTM: Reconnect failed. Updating to Nothing Playing.")
                                    
            
            time.sleep(self.polling_interval)

    def get_simplified_track_info(self, track_data, source):
        """Provide a consistent format for track info regardless of source."""
        
        # Default "Nothing Playing" structure
        nothing_playing_info = {
            'source': 'None',
            'title': 'Nothing Playing',
            'artist': '',
            'album': '',
            'album_art_url': None,
            'duration_ms': 0,
            'progress_ms': 0,
            'is_playing': False,
        }

        if source == MusicSource.SPOTIFY and track_data:
            item = track_data.get('item', {})
            is_playing_spotify = track_data.get('is_playing', False)

            if not item or not is_playing_spotify:
                return nothing_playing_info.copy()

            return {
                'source': 'Spotify',
                'title': item.get('name'),
                'artist': ', '.join([a['name'] for a in item.get('artists', [])]),
                'album': item.get('album', {}).get('name'),
                'album_art_url': item.get('album', {}).get('images', [{}])[0].get('url') if item.get('album', {}).get('images') else None,
                'duration_ms': item.get('duration_ms'),
                'progress_ms': track_data.get('progress_ms'),
                'is_playing': is_playing_spotify,
            }
        elif source == MusicSource.YTM and track_data:
            video_info = track_data.get('video', {})
            player_info = track_data.get('player', {})

            title = video_info.get('title')
            artist = video_info.get('author')
            thumbnails = video_info.get('thumbnails', [])
            album_art_url = thumbnails[0].get('url') if thumbnails else None

            # Primary conditions for "Nothing Playing" for YTM
            if player_info.get('adPlaying', False):
                self.logger.debug("YTM (get_simplified_track_info): Ad is playing, reporting as Nothing Playing.")
                return nothing_playing_info.copy()
            
            if not title or not artist:
                self.logger.debug(f"YTM (get_simplified_track_info): No title ('{title}') or artist ('{artist}'), reporting as Nothing Playing.")
                return nothing_playing_info.copy()

            # Determine playback state
            track_state = player_info.get('trackState')
            is_playing_ytm = (track_state == 1)

            album = video_info.get('album')
            duration_seconds = video_info.get('durationSeconds')
            duration_ms = int(duration_seconds * 1000) if duration_seconds is not None else 0
            progress_seconds = player_info.get('videoProgress')
            progress_ms = int(progress_seconds * 1000) if progress_seconds is not None else 0

            return {
                'source': 'YouTube Music',
                'title': title,
                'artist': artist,
                'album': album if album else '',
                'album_art_url': album_art_url,
                'duration_ms': duration_ms,
                'progress_ms': progress_ms,
                'is_playing': is_playing_ytm,
            }
        else:
            return nothing_playing_info.copy()

    def get_current_display_info(self):
        """Return the currently stored track information for display."""
        with self.track_info_lock:
            return self.current_track_info.copy() if self.current_track_info else None

    def start_polling(self):
        """Start polling for music data."""
        if not self.enabled:
            self.logger.info("Music plugin disabled, polling not started.")
            return

        if not self.poll_thread or not self.poll_thread.is_alive():
            if not self.spotify and not self.ytm:
                self.logger.warning("Cannot start polling: No music clients initialized or available.")
                return

            self.stop_event.clear()
            self.poll_thread = threading.Thread(target=self._poll_music_data, daemon=True)
            self.poll_thread.start()
            self.logger.info("Music polling started.")

    def stop_polling(self):
        """Stop the music polling thread."""
        self.logger.info("Music plugin: Stopping polling thread...")
        self.stop_event.set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=self.polling_interval + 1)
        if self.poll_thread and self.poll_thread.is_alive():
            self.logger.warning("Music plugin: Polling thread did not terminate cleanly.")
        else:
            self.logger.info("Music plugin: Polling thread stopped.")
        self.poll_thread = None
        
        if self.ytm:
            self.logger.info("MusicPlugin: Shutting down YTMClient resources.")
            if self.ytm.is_connected:
                self.ytm.disconnect_client()
            self.ytm.shutdown()

    def update(self) -> None:
        """Update music data - called by plugin system."""
        if not self.enabled:
            return
            
        # Start polling if not already running
        if not self.poll_thread or not self.poll_thread.is_alive():
            self.start_polling()

    def _clip_text_to_width(self, text, font, max_width):
        """Trim trailing characters so the rendered text fits within max_width px.

        The scrolling marquee rotates which characters lead, but the drawn
        string is still full-length; without this clip it overflows the right
        edge of the panel. This keeps the text inside its viewport, which
        matters most on narrow 64px-wide displays where the text area is only
        ~29px wide.
        """
        if max_width <= 0:
            # No horizontal room for text (e.g. a square panel where the album
            # art fills the full width) — draw nothing rather than overflow.
            return ""
        if not text:
            return text
        if self.display_manager.get_text_width(text, font) <= max_width:
            return text
        clipped = text
        while clipped and self.display_manager.get_text_width(clipped, font) > max_width:
            clipped = clipped[:-1]
        return clipped

    def _truncate_text_with_ellipsis(self, text, font, max_width):
        """Truncate text to fit max_width px, appending "..." when trimmed.

        Used by the scrolling-disabled branches. Reserves room for the
        ellipsis before clipping, so the result already fits the viewport and
        survives the draw-time _clip_text_to_width pass unchanged — otherwise
        that pass would trim the trailing "..." back off and drop the
        truncation indicator.
        """
        if max_width <= 0:
            return ""
        if not text:
            return text
        if self.display_manager.get_text_width(text, font) <= max_width:
            return text
        ellipsis = "..."
        ellipsis_width = self.display_manager.get_text_width(ellipsis, font)
        if ellipsis_width >= max_width:
            # Not even room for the ellipsis — clip the raw text instead.
            return self._clip_text_to_width(text, font, max_width)
        clipped = self._clip_text_to_width(text, font, max_width - ellipsis_width)
        return clipped + ellipsis

    def display(self, force_clear: bool = False) -> None:
        """Display music information - called by plugin system."""
        perform_full_refresh_this_cycle = force_clear
        art_url_currently_in_cache = None
        image_currently_in_cache = None
        
        # Ensure music display is activated on first entry so YTM can connect
        if not self.is_music_display_active:
            self.logger.debug("MusicPlugin.display: Activating music display on entry (ensures YTM connection attempt).")
            self.activate_music_display()

        # Check if an event previously signaled a need for immediate refresh
        initial_data_from_queue_due_to_event = None
        if self._needs_immediate_full_refresh:
            self.logger.debug("MusicPlugin.display: _needs_immediate_full_refresh is True (event-driven).")
            perform_full_refresh_this_cycle = True
            try:
                initial_data_from_queue_due_to_event = self.ytm_event_data_queue.get_nowait()
                self.logger.info(f"MusicPlugin.display: Got data from ytm_event_data_queue (due to event flag): Title {initial_data_from_queue_due_to_event.get('title') if initial_data_from_queue_due_to_event else 'None'}")
            except queue.Empty:
                self.logger.warning("MusicPlugin.display: _needs_immediate_full_refresh was true, but queue empty. Will refresh with current_track_info.")
            self._needs_immediate_full_refresh = False

        current_track_info_snapshot = None

        if perform_full_refresh_this_cycle:
            log_msg_detail = f"force_clear_from_DC={force_clear}, event_driven_refresh_attempted={'Yes' if initial_data_from_queue_due_to_event is not None else 'No'}"
            self.logger.debug(f"MusicPlugin.display: Performing full refresh cycle. Details: {log_msg_detail}")
            
            self.display_manager.clear()
            self.activate_music_display()
            self.last_periodic_refresh_time = time.time()
            
            data_from_queue_post_activate = None
            try:
                data_from_queue_post_activate = self.ytm_event_data_queue.get_nowait()
                self.logger.info(f"MusicPlugin.display (Full Refresh): Got data from queue POST activate_music_display: Title {data_from_queue_post_activate.get('title') if data_from_queue_post_activate else 'None'}")
            except queue.Empty:
                self.logger.debug("MusicPlugin.display (Full Refresh): Queue empty POST activate_music_display.")

            if data_from_queue_post_activate:
                current_track_info_snapshot = data_from_queue_post_activate
            elif initial_data_from_queue_due_to_event: 
                current_track_info_snapshot = initial_data_from_queue_due_to_event
                self.logger.debug("MusicPlugin.display (Full Refresh): Using data from initial event queue for snapshot.")
            else:
                with self.track_info_lock:
                    current_track_info_snapshot = self.current_track_info.copy() if self.current_track_info else None
                self.logger.debug("MusicPlugin.display (Full Refresh): Using self.current_track_info for snapshot.")
        else:
            with self.track_info_lock:
                current_track_info_snapshot = self.current_track_info.copy() if self.current_track_info else None

        # Update cache variables after snapshot is finalized
        with self.track_info_lock:
            art_url_currently_in_cache = self.last_album_art_url
            image_currently_in_cache = self.album_art_image

        snapshot_title_for_log = current_track_info_snapshot.get('title', 'N/A') if current_track_info_snapshot else 'N/A'
        if perform_full_refresh_this_cycle: 
            self.logger.debug(f"MusicPlugin.display (Full Refresh Render): Using snapshot - Title: '{snapshot_title_for_log}'")
        
        # Nothing Playing Logic
        if not current_track_info_snapshot or current_track_info_snapshot.get('title') == 'Nothing Playing':
            if not hasattr(self, '_last_nothing_playing_log_time') or time.time() - getattr(self, '_last_nothing_playing_log_time', 0) > 10:
                # Add rich diagnostic context so we can see exactly why we're showing Nothing Playing
                debug_ctx = {
                    'preferred_source': self.preferred_source,
                    'is_music_display_active': self.is_music_display_active,
                    'ytm_connected': bool(self.ytm and self.ytm.is_connected),
                    'have_current_track_info': bool(self.current_track_info),
                    'snapshot_exists': bool(current_track_info_snapshot),
                }
                if current_track_info_snapshot:
                    debug_ctx.update({
                        'snapshot_title': current_track_info_snapshot.get('title'),
                        'snapshot_artist': current_track_info_snapshot.get('artist'),
                        'snapshot_is_playing': current_track_info_snapshot.get('is_playing'),
                        'snapshot_source': current_track_info_snapshot.get('source'),
                    })
                self.logger.debug(f"Music Screen (MusicPlugin): Nothing playing. Context: {debug_ctx}")
                self._last_nothing_playing_log_time = time.time()

            # Track 'Nothing Playing' duration for logging
            now_ts = time.time()
            if self._nothing_playing_since_ts is None:
                self._nothing_playing_since_ts = now_ts

            if not self.is_currently_showing_nothing_playing or perform_full_refresh_this_cycle:
                if perform_full_refresh_this_cycle or not self.is_currently_showing_nothing_playing:
                    self.display_manager.clear()
                
                np_text = self._clip_text_to_width("Nothing Playing", self.display_manager.regular_font, self.display_manager.matrix.width)
                text_width = self.display_manager.get_text_width(np_text, self.display_manager.regular_font)
                x_pos = max(0, (self.display_manager.matrix.width - text_width) // 2)
                y_pos = (self.display_manager.matrix.height // 2) - 4
                self.display_manager.draw_text(np_text, x=x_pos, y=y_pos, font=self.display_manager.regular_font)
                self.display_manager.update_display()
                self.is_currently_showing_nothing_playing = True

            with self.track_info_lock: 
                self.scroll_position_title = 0
                self.scroll_position_artist = 0
                self.scroll_position_album = 0
                self.title_scroll_tick = 0
                self.artist_scroll_tick = 0
                self.album_scroll_tick = 0
                if self.album_art_image is not None or self.last_album_art_url is not None:
                    self.logger.debug("Clearing album art cache as 'Nothing Playing' is displayed.")
                    self.album_art_image = None
                    self.last_album_art_url = None
            return

        self.is_currently_showing_nothing_playing = False 
        # Reset NP timer when we have valid track info
        self._nothing_playing_since_ts = None

        if perform_full_refresh_this_cycle: 
            title_being_displayed = current_track_info_snapshot.get('title','N/A') if current_track_info_snapshot else "N/A"
            self.logger.debug(f"MusicPlugin: Resetting scroll positions for track '{title_being_displayed}' due to full refresh signal (periodic or event-driven).")
            self.scroll_position_title = 0
            self.scroll_position_artist = 0
            self.scroll_position_album = 0
            # Reset pause counters
            self.title_initial_pause_counter = 0
            self.title_end_pause_counter = 0
            self.title_at_end = False
            self.artist_initial_pause_counter = 0
            self.artist_end_pause_counter = 0
            self.artist_at_end = False
            self.album_initial_pause_counter = 0
            self.album_end_pause_counter = 0
            self.album_at_end = False

        if not self.is_music_display_active and not perform_full_refresh_this_cycle: 
            self.logger.warning("MusicPlugin.display called when music display not active and not a full refresh. Aborting draw.")
            return
        elif not self.is_music_display_active and perform_full_refresh_this_cycle:
            pass

        if not perform_full_refresh_this_cycle: 
            self.display_manager.draw.rectangle([0, 0, self.display_manager.matrix.width, self.display_manager.matrix.height], fill=(0, 0, 0))

        matrix_height = self.display_manager.matrix.height
        matrix_width = self.display_manager.matrix.width
        
        # Album art should always fill the full height of the display
        album_art_size = matrix_height
        
        album_art_target_size = (album_art_size, album_art_size)
        album_art_x = 0
        album_art_y = 0
        text_area_x_start = album_art_x + album_art_size + 2
        text_area_width = matrix_width - text_area_x_start - 1 

        image_to_render_this_cycle = None
        target_art_url_for_current_track = current_track_info_snapshot.get('album_art_url')

        if target_art_url_for_current_track:
            if image_currently_in_cache and art_url_currently_in_cache == target_art_url_for_current_track:
                image_to_render_this_cycle = image_currently_in_cache
            else:
                self.logger.info(f"MusicPlugin: Fetching album art for: {target_art_url_for_current_track}")
                fetched_image = self._fetch_and_resize_image(target_art_url_for_current_track, album_art_target_size)
                if fetched_image:
                    self.logger.info(f"MusicPlugin: Album art for {target_art_url_for_current_track} fetched successfully.")
                    with self.track_info_lock:
                        latest_known_art_url_in_live_info = self.current_track_info.get('album_art_url') if self.current_track_info else None
                        if target_art_url_for_current_track == latest_known_art_url_in_live_info:
                            self.album_art_image = fetched_image
                            self.last_album_art_url = target_art_url_for_current_track 
                            image_to_render_this_cycle = fetched_image
                            self.logger.debug(f"Cached and will render new art for {target_art_url_for_current_track}")
                        else:
                            self.logger.info(f"MusicPlugin: Discarding fetched art for {target_art_url_for_current_track}; "
                                        f"track changed to '{self.current_track_info.get('title', 'N/A')}' "
                                        f"with art '{latest_known_art_url_in_live_info}' during fetch.")
                else:
                    self.logger.warning(f"MusicPlugin: Failed to fetch or process album art for {target_art_url_for_current_track}.")
                    with self.track_info_lock:
                        if self.last_album_art_url == target_art_url_for_current_track:
                            self.album_art_image = None 
        else:
            with self.track_info_lock:
                if self.album_art_image is not None or self.last_album_art_url is not None:
                    self.album_art_image = None
                    self.last_album_art_url = None 

        if image_to_render_this_cycle:
            self.display_manager.image.paste(image_to_render_this_cycle, (album_art_x, album_art_y))
        else:
            self.display_manager.draw.rectangle([album_art_x, album_art_y, 
                                                 album_art_x + album_art_size -1, album_art_y + album_art_size -1],
                                                 outline=(50,50,50), fill=(10,10,10))

        title = current_track_info_snapshot.get('title', ' ')
        artist = current_track_info_snapshot.get('artist', ' ')
        album = current_track_info_snapshot.get('album', ' ')
        
        # Debug logging for album display
        self.logger.debug(f"MusicPlugin.display: Track info - Title: '{title}', Artist: '{artist}', Album: '{album}'") 

        # Use custom fonts if loaded, otherwise fall back to display_manager fonts
        font_title = self.title_font if self.title_font else self.display_manager.small_font
        font_artist = self.artist_font if self.artist_font else self.display_manager.bdf_5x7_font
        font_album = self.album_font if self.album_font else self.display_manager.bdf_5x7_font

        # Read per-element layout overrides from customization config.
        customization_layout = self.config.get('customization', {})
        title_layout_config = customization_layout.get('title_text', {})
        artist_layout_config = customization_layout.get('artist_text', {})
        album_layout_config = customization_layout.get('album_text', {})

        def _safe_y_percent(value, fallback):
            """Normalize optional y_percent values to 0.0-1.0 range."""
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return fallback

        # Get actual font heights for layout
        title_height = self.display_manager.get_font_height(font_title)
        artist_height = self.display_manager.get_font_height(font_artist)
        album_height = self.display_manager.get_font_height(font_album)

        # Calculate progress bar position (needed for layout validation)
        if matrix_height <= 32:
            progress_bar_height = 3
        elif matrix_height <= 64:
            progress_bar_height = 4
        else:
            progress_bar_height = max(4, int(matrix_height * 0.06))
        progress_bar_y = matrix_height - progress_bar_height - 1

        if self._adaptive:
            # Adaptive layout (beta, opt-in): font sizes scale with the
            # panel instead of the classic fixed sizes; classic branch
            # below is untouched when declined.
            (font_title, font_artist, font_album,
             y_pos_title_top, y_pos_artist_top, y_pos_album_top) = self._adaptive_text_layout(
                font_title, font_artist, font_album,
                title_layout_config, artist_layout_config, album_layout_config,
                text_area_x_start, text_area_width, matrix_height,
                progress_bar_height, _safe_y_percent)
            title_height = self.display_manager.get_font_height(font_title)
            artist_height = self.display_manager.get_font_height(font_artist)
            album_height = self.display_manager.get_font_height(font_album)
        else:
            # Top-down stacking with proportional gaps
            top_padding = max(1, matrix_height // 32)
            line_gap = max(1, matrix_height // 16)

            # Auto-compute positions from font metrics
            auto_y_title = top_padding
            auto_y_artist = auto_y_title + title_height + line_gap
            auto_y_album = auto_y_artist + artist_height + line_gap

            # Allow explicit y_percent override from user config
            if 'y_percent' in title_layout_config:
                y_pos_title_top = int(matrix_height * _safe_y_percent(title_layout_config['y_percent'], 0.03))
            else:
                y_pos_title_top = auto_y_title

            if 'y_percent' in artist_layout_config:
                y_pos_artist_top = int(matrix_height * _safe_y_percent(artist_layout_config['y_percent'], 0.34))
            else:
                y_pos_artist_top = auto_y_artist

            if 'y_percent' in album_layout_config:
                y_pos_album_top = int(matrix_height * _safe_y_percent(album_layout_config['y_percent'], 0.60))
            else:
                y_pos_album_top = auto_y_album

        # Validate album doesn't overlap progress bar
        max_album_y = progress_bar_y - album_height - 1
        if y_pos_album_top > max_album_y:
            y_pos_album_top = max_album_y
            self.logger.warning("MusicPlugin: Clamped album Y to avoid progress bar overlap")

        # Debug logging for scaling calculations
        self.logger.debug(
            f"MusicPlugin.display: Display scaling - matrix: {matrix_width}x{matrix_height}, "
            f"album_art: {album_art_size}px, font_heights: title={title_height}, artist={artist_height}, album={album_height}, "
            f"positions - title: {y_pos_title_top}, artist: {y_pos_artist_top}, album: {y_pos_album_top}, progress_bar: {progress_bar_y}"
        )

        # Title scrolling with configurable settings
        title_config = self.scroll_config['title']
        title_width = self.display_manager.get_text_width(title, font_title)
        current_title_display_text = title
        
        if title_width > text_area_width and title_config['enabled']:
            # Check if we're in initial pause
            if self.title_initial_pause_counter < title_config['initial_pause_frames']:
                self.title_initial_pause_counter += 1
                current_title_display_text = title  # Show full text during initial pause
            else:
                # Check if we're at the end and need to pause
                max_scroll_pos = len(title) - 1
                if self.scroll_position_title >= max_scroll_pos:
                    if not self.title_at_end:
                        self.title_at_end = True
                        self.title_end_pause_counter = 0
                    
                    if self.title_end_pause_counter < title_config['end_pause_frames']:
                        self.title_end_pause_counter += 1
                        # Show end of text during end pause
                        current_title_display_text = title[self.scroll_position_title:] + title_config['separator'] + title[:self.scroll_position_title]
                    else:
                        # Reset and wrap around
                        self.scroll_position_title = 0
                        self.title_initial_pause_counter = 0
                        self.title_end_pause_counter = 0
                        self.title_at_end = False
                        current_title_display_text = title + title_config['separator'] + title[:self.scroll_position_title]
                else:
                    self.title_at_end = False
                    current_title_display_text = title[self.scroll_position_title:] + title_config['separator'] + title[:self.scroll_position_title]
                
                # Advance scroll position based on speed
                self.title_scroll_tick += 1
                if self.title_scroll_tick >= title_config['speed']:
                    if not self.title_at_end or self.title_end_pause_counter >= title_config['end_pause_frames']:
                        self.scroll_position_title = (self.scroll_position_title + 1) % len(title)
                    self.title_scroll_tick = 0
        elif title_width > text_area_width and not title_config['enabled']:
            # Scrolling disabled - truncate to the viewport with an ellipsis
            current_title_display_text = self._truncate_text_with_ellipsis(title, font_title, text_area_width)
            self.scroll_position_title = 0
            self.title_scroll_tick = 0
        else:
            # Text fits, no scrolling needed
            self.scroll_position_title = 0
            self.title_scroll_tick = 0
            self.title_initial_pause_counter = 0
            self.title_end_pause_counter = 0
            self.title_at_end = False
        
        self.display_manager.draw_text(self._clip_text_to_width(current_title_display_text, font_title, text_area_width),
                                     x=text_area_x_start, y=y_pos_title_top, color=(255, 255, 255), font=font_title)

        # Artist scrolling with configurable settings
        artist_config = self.scroll_config['artist']
        artist_width = self.display_manager.get_text_width(artist, font_artist)
        current_artist_display_text = artist
        
        if artist_width > text_area_width and artist_config['enabled']:
            # Check if we're in initial pause
            if self.artist_initial_pause_counter < artist_config['initial_pause_frames']:
                self.artist_initial_pause_counter += 1
                current_artist_display_text = artist  # Show full text during initial pause
            else:
                # Check if we're at the end and need to pause
                max_scroll_pos = len(artist) - 1
                if self.scroll_position_artist >= max_scroll_pos:
                    if not self.artist_at_end:
                        self.artist_at_end = True
                        self.artist_end_pause_counter = 0
                    
                    if self.artist_end_pause_counter < artist_config['end_pause_frames']:
                        self.artist_end_pause_counter += 1
                        # Show end of text during end pause
                        current_artist_display_text = artist[self.scroll_position_artist:] + artist_config['separator'] + artist[:self.scroll_position_artist]
                    else:
                        # Reset and wrap around
                        self.scroll_position_artist = 0
                        self.artist_initial_pause_counter = 0
                        self.artist_end_pause_counter = 0
                        self.artist_at_end = False
                        current_artist_display_text = artist + artist_config['separator'] + artist[:self.scroll_position_artist]
                else:
                    self.artist_at_end = False
                    current_artist_display_text = artist[self.scroll_position_artist:] + artist_config['separator'] + artist[:self.scroll_position_artist]
                
                # Advance scroll position based on speed
                self.artist_scroll_tick += 1
                if self.artist_scroll_tick >= artist_config['speed']:
                    if not self.artist_at_end or self.artist_end_pause_counter >= artist_config['end_pause_frames']:
                        self.scroll_position_artist = (self.scroll_position_artist + 1) % len(artist)
                    self.artist_scroll_tick = 0
        elif artist_width > text_area_width and not artist_config['enabled']:
            # Scrolling disabled - truncate to the viewport with an ellipsis
            current_artist_display_text = self._truncate_text_with_ellipsis(artist, font_artist, text_area_width)
            self.scroll_position_artist = 0
            self.artist_scroll_tick = 0
        else:
            # Text fits, no scrolling needed
            self.scroll_position_artist = 0
            self.artist_scroll_tick = 0
            self.artist_initial_pause_counter = 0
            self.artist_end_pause_counter = 0
            self.artist_at_end = False

        self.display_manager.draw_text(self._clip_text_to_width(current_artist_display_text, font_artist, text_area_width),
                                     x=text_area_x_start, y=y_pos_artist_top, color=(180, 180, 180), font=font_artist)
            
        # Album
        available_height_for_album = matrix_height - y_pos_album_top
        self.logger.debug(f"MusicPlugin.display: Album display check - matrix_height: {matrix_height}, y_pos_album_top: {y_pos_album_top}, available_height: {available_height_for_album}, album_height: {album_height}")

        if available_height_for_album >= album_height: 
            album_width = self.display_manager.get_text_width(album, font_album)
            self.logger.debug(f"MusicPlugin.display: Album '{album}' - width: {album_width}, text_area_width: {text_area_width}")
            
            # Display album if it fits or can be scrolled (maintains original behavior but adds scrolling)
            album_config = self.scroll_config['album']
            if album_width <= text_area_width:
                # Album fits without scrolling - display normally
                self.logger.debug(f"MusicPlugin.display: Drawing album '{album}' at ({text_area_x_start}, {y_pos_album_top}) - fits without scrolling")
                self.display_manager.draw_text(self._clip_text_to_width(album, font_album, text_area_width),
                                             x=text_area_x_start, y=y_pos_album_top, color=(150, 150, 150), font=font_album)
                self.scroll_position_album = 0
                self.album_scroll_tick = 0
                self.album_initial_pause_counter = 0
                self.album_end_pause_counter = 0
                self.album_at_end = False
            elif album_width > text_area_width:
                # Album is too wide - scroll it (if enabled)
                current_album_display_text = album
                
                if album_config['enabled']:
                    # Check if we're in initial pause
                    if self.album_initial_pause_counter < album_config['initial_pause_frames']:
                        self.album_initial_pause_counter += 1
                        current_album_display_text = album  # Show full text during initial pause
                    else:
                        # Check if we're at the end and need to pause
                        max_scroll_pos = len(album) - 1
                        if self.scroll_position_album >= max_scroll_pos:
                            if not self.album_at_end:
                                self.album_at_end = True
                                self.album_end_pause_counter = 0
                            
                            if self.album_end_pause_counter < album_config['end_pause_frames']:
                                self.album_end_pause_counter += 1
                                # Show end of text during end pause
                                current_album_display_text = album[self.scroll_position_album:] + album_config['separator'] + album[:self.scroll_position_album]
                            else:
                                # Reset and wrap around
                                self.scroll_position_album = 0
                                self.album_initial_pause_counter = 0
                                self.album_end_pause_counter = 0
                                self.album_at_end = False
                                current_album_display_text = album + album_config['separator'] + album[:self.scroll_position_album]
                        else:
                            self.album_at_end = False
                            current_album_display_text = album[self.scroll_position_album:] + album_config['separator'] + album[:self.scroll_position_album]
                        
                        # Advance scroll position based on speed
                        self.album_scroll_tick += 1
                        if self.album_scroll_tick >= album_config['speed']:
                            if not self.album_at_end or self.album_end_pause_counter >= album_config['end_pause_frames']:
                                self.scroll_position_album = (self.scroll_position_album + 1) % len(album)
                            self.album_scroll_tick = 0
                else:
                    # Scrolling disabled - truncate to the viewport with an ellipsis
                    current_album_display_text = self._truncate_text_with_ellipsis(album, font_album, text_area_width)
                    self.scroll_position_album = 0
                    self.album_scroll_tick = 0
                
                self.logger.debug(f"MusicPlugin.display: Drawing scrolling album '{current_album_display_text}' at ({text_area_x_start}, {y_pos_album_top}) - position: {self.scroll_position_album}")
                self.display_manager.draw_text(self._clip_text_to_width(current_album_display_text, font_album, text_area_width),
                                             x=text_area_x_start, y=y_pos_album_top, color=(150, 150, 150), font=font_album)
        else:
            self.logger.debug(f"MusicPlugin.display: Album '{album}' not displayed - insufficient height (available: {available_height_for_album}, needed: {album_height})")

        # Progress Bar (position already calculated earlier for layout validation)
        duration_ms = current_track_info_snapshot.get('duration_ms', 0)
        progress_ms = current_track_info_snapshot.get('progress_ms', 0)

        if duration_ms > 0 and text_area_width > 0:
            bar_total_width = text_area_width
            filled_ratio = progress_ms / duration_ms
            filled_width = int(filled_ratio * bar_total_width)

            self.display_manager.draw.rectangle([
                text_area_x_start, progress_bar_y, 
                text_area_x_start + bar_total_width -1, progress_bar_y + progress_bar_height -1
            ], outline=(60, 60, 60), fill=(30,30,30)) 
            
            if filled_width > 0:
                self.display_manager.draw.rectangle([
                    text_area_x_start, progress_bar_y, 
                    text_area_x_start + filled_width -1, progress_bar_y + progress_bar_height -1
                ], fill=(200, 200, 200)) 

        self.display_manager.update_display()

    def has_live_priority(self) -> bool:
        """
        Check if this plugin has live priority enabled.
        
        Live priority allows music to take over the display when it's actively playing.
        
        Returns:
            True if live_priority is enabled in config, False otherwise
        """
        if not self.enabled:
            return False
        return self.config.get("live_priority", False)

    def has_live_content(self) -> bool:
        """
        Check if this plugin currently has live content to display.

        Music is considered "live" when it's actively playing and should interrupt
        normal display rotation when live priority is enabled.

        Returns:
            True if music is currently playing, False otherwise
        """
        # Music is considered "live" when it's actively playing
        # Check if we have current track info and if music is playing
        has_content = self.current_track_info and self.current_track_info.get('is_playing', False)
        self.logger.debug(f"has_live_content() called - returning {has_content}, track: {self.current_track_info.get('title', 'None') if self.current_track_info else 'None'}")
        return has_content

    def get_live_modes(self) -> list:
        """
        Return the list of modes that should be displayed when live content is available.

        Returns:
            List of mode names (typically ["now_playing"])
        """
        return ["now_playing"]

    def cleanup(self) -> None:
        """Clean up resources when plugin is unloaded."""
        self.logger.info("Music plugin: Cleaning up resources...")
        self.stop_polling()
        super().cleanup()
