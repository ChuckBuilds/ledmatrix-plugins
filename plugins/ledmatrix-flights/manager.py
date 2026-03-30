"""
Flight Tracker Plugin for LEDMatrix

Real-time aircraft tracking with ADS-B data, map backgrounds, flight plans, and proximity alerts.
Migrated from feature/flight-tracker-manager branch with flattened configuration structure for plugin compatibility.
"""

import json
import logging
import math
import time
import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# Import base plugin class
import sys
# Add parent directory to path to find base plugin
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.plugin_system.base_plugin import BasePlugin

# Import aircraft database
from aircraft_database import AircraftDatabase

# Import extracted utility modules
from utils import haversine_miles, altitude_to_color, categorize_aircraft, is_callsign_worth_fetching
from units import null_safe
from fetcher import create_fetcher, FR24DetailFetcher, _AIRLINE_ICAO_NAMES as AIRLINE_ICAO_NAMES_TABLE
from enrichment import create_enrichment_provider
from renderer import FlightRenderer
from data_model import TrackedFlight

logger = logging.getLogger(__name__)




class FlightTrackerPlugin(BasePlugin):
    """Flight tracker plugin for LEDMatrix."""
    
    def __init__(self, plugin_id: str, config: Dict[str, Any], display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.plugin_manager = plugin_manager
        
        # Config is already flattened (no flight_tracker wrapper)
        # Flight tracker configuration
        self.enabled = self.config.get('enabled', False)
        self.update_interval = self.config.get('update_interval', 5)
        self.skyaware_url = self.config.get('skyaware_url', 'http://192.168.86.30/skyaware/data/aircraft.json')
        
        # Flight plan data configuration
        self.flight_plan_enabled = self.config.get('flight_plan_enabled', False)
        
        # Get API key from flight_tracker config (secrets are merged by ConfigManager)
        self.flightaware_api_key = self.config.get('flightaware_api_key', '')
        
        # Rate limiting and cost control for FlightAware API
        self.api_call_timestamps = []  # Track API call timestamps for rate limiting
        self.max_api_calls_per_hour = self.config.get('max_api_calls_per_hour', 20)  # Reduced from 50 to 20 for cost control
        self.cache_ttl_seconds = self.config.get('flight_plan_cache_ttl_hours', 12) * 3600  # 12 hours for fresher data
        self.min_callsign_length = self.config.get('min_callsign_length', 4)  # Increased from 3 to 4 to filter more
        self.daily_api_budget = self.config.get('daily_api_budget', 60)  # Max 60 calls per day (1800/month)
        self.api_calls_today = 0
        self.last_reset_date = None
        self.airline_callsign_prefixes = self.config.get('airline_callsign_prefixes', [
            'AAL', 'UAL', 'DAL', 'SWA', 'JBU', 'ASQ', 'ENY', 'FFT', 'NKS', 'F9', 'G4', 'B6', 'WN', 'AA', 'UA', 'DL'
        ])  # Only fetch for known airline callsigns
        
        # Location configuration
        self.center_lat = self.config.get('center_latitude', 27.9506)
        self.center_lon = self.config.get('center_longitude', -82.4572)
        self.map_radius_miles = self.config.get('map_radius_miles', 10)  # Reduced from 50 to 10 miles for better visibility
        self.zoom_factor = self.config.get('zoom_factor', 1.0)  # Zoom factor to use more of the display
        
        # Map background configuration
        self.map_bg_config = self.config.get('map_background', {})
        self.map_bg_enabled = self.map_bg_config.get('enabled', True)
        self.tile_provider = self.map_bg_config.get('tile_provider', 'osm')
        self.tile_size = self.map_bg_config.get('tile_size', 256)
        # Cache tiles for 1 year by default - map tiles don't change frequently
        self.cache_ttl_hours = self.map_bg_config.get('cache_ttl_hours', 8760)
        self.fade_intensity = self.map_bg_config.get('fade_intensity', 0.3)
        self.map_brightness = self.map_bg_config.get('brightness', 1.0)
        self.map_contrast = self.map_bg_config.get('contrast', 1.0)
        self.map_saturation = self.map_bg_config.get('saturation', 1.0)
        self.disable_on_cache_error = self.map_bg_config.get('disable_on_cache_error', False)
        
        # Custom tile server URL (for self-hosted OSM servers)
        self.custom_tile_server = self.map_bg_config.get('custom_tile_server', None)
        
        # Log tile server configuration
        if self.custom_tile_server:
            logger.info(f"[Flight Tracker] Configured to use custom tile server: {self.custom_tile_server}")
        else:
            logger.info(f"[Flight Tracker] Configured to use tile provider: {self.tile_provider}")
        
        # Log map appearance settings
        logger.info(f"[Flight Tracker] Map appearance - Brightness: {self.map_brightness}, Contrast: {self.map_contrast}, Saturation: {self.map_saturation}, Fade: {self.fade_intensity}")
        
        # Track cache errors
        self.cache_error_count = 0
        self.max_cache_errors = 5  # Disable after 5 consecutive cache errors
        
        # Map tile cache directory - use the same cache system as the rest of the project
        cache_dir = cache_manager.cache_dir
        if cache_dir:
            self.tile_cache_dir = Path(cache_dir) / 'map_tiles'
            try:
                self.tile_cache_dir.mkdir(parents=True, exist_ok=True)
                # Test write access
                test_file = self.tile_cache_dir / '.writetest'
                test_file.write_text('test')
                test_file.unlink()
                logger.info(f"[Flight Tracker] Using map tile cache directory: {self.tile_cache_dir}")
            except (PermissionError, OSError) as e:
                logger.warning(f"[Flight Tracker] Could not use map tile cache directory {self.tile_cache_dir}: {e}")
                # Fallback to a temporary directory
                import tempfile
                self.tile_cache_dir = Path(tempfile.gettempdir()) / 'ledmatrix_map_tiles'
                self.tile_cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"[Flight Tracker] Using temporary map tile cache: {self.tile_cache_dir}")
        else:
            # No cache directory available, use temporary
            import tempfile
            self.tile_cache_dir = Path(tempfile.gettempdir()) / 'ledmatrix_map_tiles'
            self.tile_cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Flight Tracker] Using temporary map tile cache: {self.tile_cache_dir}")
        
        # Cached map background
        self.cached_map_bg = None
        self.last_map_center = None
        self.last_map_zoom = None
        self.cached_pixels_per_mile = None  # Actual scale of the cached map
        
        # Display configuration — read dynamically via properties so any matrix
        # resize is picked up without restarting the plugin.
        self._display_manager_ref = display_manager
        self.show_trails = self.config.get('show_trails', False)
        self.trail_length = self.config.get('trail_length', 10)
        
        # Logging rate limiting for bounds warnings
        self.bounds_warning_cache = {}
        self.bounds_warning_interval = 30  # Only log each unique coordinate once every 30 seconds
        
        # Altitude color configuration - matches the gradient from the image
        # This uses the standard aviation altitude color scale
        self.altitude_colors = {
            '0': [255, 100, 0],       # Deep orange-red (ground level)
            '500': [255, 120, 0],     # Slightly lighter orange-red
            '1000': [255, 140, 0],    # Distinct orange
            '2000': [255, 200, 0],    # Bright orange-yellow
            '4000': [255, 255, 0],    # Clear yellow
            '6000': [200, 255, 0],    # Yellowish-green
            '8000': [0, 255, 0],      # Vibrant green
            '10000': [0, 200, 150],   # Bright teal (bluish-green)
            '20000': [0, 150, 255],   # Clear bright blue
            '30000': [0, 0, 200],     # Deep royal blue
            '40000': [150, 0, 200],   # Vibrant purple
            '45000': [200, 0, 150]    # Distinct magenta/purple
        }
        
        
        # Proximity alert configuration
        self.proximity_config = self.config.get('proximity_alert', {})
        self.proximity_enabled = self.proximity_config.get('enabled', True)
        self.proximity_distance_miles = self.proximity_config.get('distance_miles', 0.1)
        self.proximity_duration = self.proximity_config.get('duration_seconds', 30)
        
        # Runtime data
        self.aircraft_data = {}  # ICAO -> aircraft dict
        self.aircraft_trails = {}  # ICAO -> list of (lat, lon, timestamp) tuples
        self.last_update = 0
        self.last_fetch = 0
        
        # Cost monitoring
        self.monthly_api_calls = 0
        self.cost_per_call = 0.005  # $0.005 per call based on your data
        self.monthly_budget = 10.0  # $10 monthly budget
        self.budget_warning_threshold = 0.8  # Warn at 80% of budget
        
        # Background service for flight plan data
        self.background_service_enabled = self.config.get('background_service', {}).get('enabled', True)
        self.background_fetch_interval = self.config.get('background_service', {}).get('fetch_interval_hours', 4) * 3600  # More frequent fetching
        self.last_background_fetch = 0
        self.pending_flight_plans = set()  # Callsigns to fetch in background
        self.max_background_calls_per_run = self.config.get('background_service', {}).get('max_calls_per_run', 10)  # More calls per background run
        
        # FR24 data source configuration
        self.data_source = self.config.get('data_source', 'skyaware')
        self.fr24_enrichment = self.config.get('fr24_enrichment', True)
        self.fr24_enrichment_interval = self.config.get('fr24_enrichment_interval', 60)
        self.last_fr24_enrichment = 0
        # Cache of FR24 data keyed by ICAO hex (for enrichment mode)
        self.fr24_enrichment_cache: Dict[str, Dict] = {}
        # Cache of FR24 detail data keyed by FR24 flight ID (for airline name / timing)
        self.fr24_detail_cache: Dict[str, Dict] = {}
        self.fr24_detail_cache_ttl = 12 * 3600  # 12 hours
        # Pending FR24 detail fetches keyed by FR24 flight ID -> icao
        self.pending_fr24_details: Dict[str, str] = {}

        # FR24 headers — use gzip only to avoid needing the Brotli package
        self._fr24_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Origin": "https://www.flightradar24.com",
            "Referer": "https://www.flightradar24.com/",
        }

        # Create data source fetcher (delegates to fetcher.py)
        self._fetcher = create_fetcher(self.config, cache_manager)
        # FR24 detail fetcher for enrichment (airline names, timing)
        self._fr24_detail_fetcher = FR24DetailFetcher(cache_ttl=self.fr24_detail_cache_ttl)
        # Route enrichment provider (OpenSky free, FlightAware paid optional)
        self._enrichment = create_enrichment_provider(self.config, cache_manager)

        # Flight records (all-time closest/farthest)
        self.flight_records_enabled = self.config.get('flight_records', {}).get('enabled', True)
        self._closest_record: Optional[Dict] = None
        self._farthest_record: Optional[Dict] = None
        records_cache_dir = Path(cache_manager.cache_dir) if cache_manager.cache_dir else Path.home() / '.cache' / 'ledmatrix'
        self._flight_records_path = records_cache_dir / 'flight_records.json'
        if self.flight_records_enabled:
            self._load_flight_records()

        # Display mode configuration
        self.display_mode = self.config.get('display_mode', 'auto')  # 'map', 'overhead', 'stats', 'area', 'flight_tracking', or 'auto'

        # Stats display variables (for stats mode)
        self.current_stat = 0
        self.last_stat_change = 0
        self.stat_duration = 10  # Show each stat for 10 seconds

        # Proximity alert variables (for overhead mode)
        self.proximity_triggered_time = None

        # Fonts
        self.fonts = self._load_fonts()

        # New display mode configuration (FR-01, FR-02, FR-05)
        self.units_system = self.config.get('units', 'imperial')
        self.max_aircraft = self.config.get('max_aircraft', 5)
        self.min_altitude_ft = self.config.get('min_altitude_ft', 0)
        self.max_altitude_ft = self.config.get('max_altitude_ft', 0)
        self.aircraft_categories = self.config.get('aircraft_categories', [])
        self.tracked_flights_cfg = self.config.get('tracked_flights', [])
        self.anchor_airport = self.config.get('anchor_airport', '')
        self.route_cache_ttl = self.config.get('route_cache_ttl', 300)
        self.tracked_flight_data: Dict[str, TrackedFlight] = {}
        self._area_page = 0
        self._area_last_page_change = 0.0
        self._tracking_index = 0
        self._tracking_last_change = 0.0
        self._last_tracked_update = 0.0

        # Create renderer for new display modes
        self._renderer = FlightRenderer(display_manager, self.fonts, self.config)
        
        # Initialize offline aircraft database (lazy-loaded on first use for faster startup)
        self.use_offline_db = self.config.get('use_offline_database', True)
        self.offline_db_auto_update = self.config.get('offline_database_auto_update', True)
        self.offline_db_update_interval_days = self.config.get('offline_database_update_interval_days', 30)
        self.aircraft_db = None
        self.aircraft_db_loaded = False  # Track if we've attempted to load the DB
        self.aircraft_db_cache_dir = cache_manager.cache_dir if cache_manager.cache_dir else Path.home() / '.cache' / 'ledmatrix'
        logger.debug("[Flight Tracker] Aircraft database will be lazy-loaded on first use")
        
        logger.info(f"[Flight Tracker] Initialized with center: ({self.center_lat}, {self.center_lon}), radius: {self.map_radius_miles}mi")
        if self.data_source == 'flightradar24':
            logger.info(f"[Flight Tracker] Display: {self.display_width}x{self.display_height}, Data source: FlightRadar24")
        else:
            logger.info(f"[Flight Tracker] Display: {self.display_width}x{self.display_height}, Data source: SkyAware ({self.skyaware_url}), FR24 enrichment: {self.fr24_enrichment}")
    
    @property
    def display_width(self) -> int:
        return self._display_manager_ref.matrix.width

    @property
    def display_height(self) -> int:
        return self._display_manager_ref.matrix.height

    def _load_fonts(self) -> Dict[str, Any]:
        """Load fonts for text rendering with mixed approach: PressStart2P for titles, 4x6 for data."""
        fonts = {}
        
        # Try multiple font path locations (plugin context vs main project context)
        font_paths = [
            'assets/fonts',  # Main project context
            '../assets/fonts',  # Plugin context (relative to plugin directory)
            '../../assets/fonts',  # Plugin submodule context
        ]
        
        def find_font_path(filename):
            """Find font file in available paths."""
            for base_path in font_paths:
                font_path = os.path.join(base_path, filename)
                if os.path.exists(font_path):
                    return font_path
            return None
        
        try:
            # Load PressStart2P for titles (larger, more readable for headers)
            press_start_path = find_font_path('PressStart2P-Regular.ttf')
            if press_start_path:
                if self.display_height >= 64:
                    fonts['title_small'] = ImageFont.truetype(press_start_path, 8)
                    fonts['title_medium'] = ImageFont.truetype(press_start_path, 10)
                    fonts['title_large'] = ImageFont.truetype(press_start_path, 12)
                else:
                    fonts['title_small'] = ImageFont.truetype(press_start_path, 6)
                    fonts['title_medium'] = ImageFont.truetype(press_start_path, 8)
                    fonts['title_large'] = ImageFont.truetype(press_start_path, 10)
            else:
                raise FileNotFoundError("PressStart2P-Regular.ttf not found")
            
            # Load 4x6 for data (smaller, more compact for detailed info)
            font_4x6_path = find_font_path('4x6-font.ttf')
            if font_4x6_path:
                if self.display_height >= 64:
                    fonts['data_small'] = ImageFont.truetype(font_4x6_path, 8)  # Larger for readability
                    fonts['data_medium'] = ImageFont.truetype(font_4x6_path, 10)
                    fonts['data_large'] = ImageFont.truetype(font_4x6_path, 12)
                else:
                    fonts['data_small'] = ImageFont.truetype(font_4x6_path, 6)
                    fonts['data_medium'] = ImageFont.truetype(font_4x6_path, 8)
                    fonts['data_large'] = ImageFont.truetype(font_4x6_path, 10)
            
            # Legacy aliases for backward compatibility
            fonts['small'] = fonts['data_small']
            fonts['medium'] = fonts['data_medium'] 
            fonts['large'] = fonts['data_large']
            
            logger.info("[Flight Tracker] Successfully loaded mixed fonts: PressStart2P for titles, 4x6 for data")
        except Exception as e:
            logger.warning(f"[Flight Tracker] Failed to load mixed fonts: {e}, using PressStart2P fallback")
            try:
                # Fallback to PressStart2P for everything
                press_start_path = find_font_path('PressStart2P-Regular.ttf')
                if press_start_path:
                    if self.display_height >= 64:
                        fonts['title_small'] = ImageFont.truetype(press_start_path, 8)
                        fonts['title_medium'] = ImageFont.truetype(press_start_path, 10)
                        fonts['title_large'] = ImageFont.truetype(press_start_path, 12)
                        fonts['data_small'] = ImageFont.truetype(press_start_path, 6)
                        fonts['data_medium'] = ImageFont.truetype(press_start_path, 8)
                        fonts['data_large'] = ImageFont.truetype(press_start_path, 10)
                    else:
                        fonts['title_small'] = ImageFont.truetype(press_start_path, 6)
                        fonts['title_medium'] = ImageFont.truetype(press_start_path, 8)
                        fonts['title_large'] = ImageFont.truetype(press_start_path, 10)
                        fonts['data_small'] = ImageFont.truetype(press_start_path, 5)
                        fonts['data_medium'] = ImageFont.truetype(press_start_path, 6)
                        fonts['data_large'] = ImageFont.truetype(press_start_path, 7)
                    
                    # Legacy aliases
                    fonts['small'] = fonts['data_small']
                    fonts['medium'] = fonts['data_medium']
                    fonts['large'] = fonts['data_large']
                    
                    logger.info("[Flight Tracker] Using PressStart2P fallback for all fonts")
                else:
                    raise FileNotFoundError("No fonts found")
            except Exception as e2:
                logger.warning(f"[Flight Tracker] All custom fonts failed: {e2}, using default")
                fonts['title_small'] = ImageFont.load_default()
                fonts['title_medium'] = ImageFont.load_default()
                fonts['title_large'] = ImageFont.load_default()
                fonts['data_small'] = ImageFont.load_default()
                fonts['data_medium'] = ImageFont.load_default()
                fonts['data_large'] = ImageFont.load_default()
                fonts['small'] = ImageFont.load_default()
                fonts['medium'] = ImageFont.load_default()
                fonts['large'] = ImageFont.load_default()
        return fonts

    def _display_size(self) -> str:
        """Return 'tiny', 'small', or 'large' based on current display dimensions.

        tiny  — 64 wide or narrower, or 32 tall or shorter
        small — up to 128×32 or 64×64 range
        large — 192+ wide or 96+ tall
        """
        w = self.display_width
        h = self.display_height
        if w >= 192 or h >= 64:
            return 'large'
        if w >= 65 or h >= 33:
            return 'small'
        return 'tiny'

    def _draw_text_with_outline(self, draw, text, position, font, fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        x, y = position
        # Draw outline
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        # Draw text
        draw.text((x, y), text, font=font, fill=fill)
    
    def _draw_text_pixel_perfect(self, draw, text, position, font, fill=(255, 255, 255)):
        """Draw text without outline for pixel-perfect rendering, especially for 4x6 font."""
        x, y = position
        draw.text((x, y), text, font=font, fill=fill)
    
    def _draw_text_smart(self, draw, text, position, font, fill=(255, 255, 255), outline_color=(0, 0, 0), use_outline=True):
        """Smart text drawing - uses outline for titles, pixel-perfect for data fonts."""
        # Check if this is a 4x6 font (data font) - use pixel-perfect rendering
        font_name = str(font).lower() if hasattr(font, '__str__') else ''
        is_4x6_font = '4x6' in font_name or 'data_' in str(font)
        
        if is_4x6_font and not use_outline:
            # Use pixel-perfect rendering for 4x6 data fonts
            self._draw_text_pixel_perfect(draw, text, position, font, fill)
        else:
            # Use outlined rendering for titles and when explicitly requested
            self._draw_text_with_outline(draw, text, position, font, fill, outline_color)
    
    def _draw_airplane_icon(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        color: Tuple[int, int, int] = (200, 200, 200),
    ) -> None:
        """Draw a simple airplane icon at the specified position with black outline.

        Args:
            draw: ImageDraw object to draw on
            x: X coordinate for the icon's top-left corner
            y: Y coordinate for the icon's top-left corner
            color: RGB color tuple for the icon
        """
        # Simple 5x5 pixel airplane icon
        # Format: (relative_x, relative_y)
        airplane_pixels = [
            (2, 0),  # Nose
            (2, 1),  # Body
            (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),  # Wings
            (2, 3),  # Body
            (1, 4), (2, 4), (3, 4),  # Tail
        ]

        airplane_set = set(airplane_pixels)

        # Draw black outline (all pixels adjacent to airplane pixels)
        outline_pixels = set()
        for px, py in airplane_pixels:
            # Check all 8 surrounding pixels
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue  # Skip the center pixel
                    neighbor = (px + dx, py + dy)
                    if neighbor not in airplane_set:
                        outline_pixels.add(neighbor)

        # Draw outline first
        for px, py in outline_pixels:
            draw.point((x + px, y + py), fill=(0, 0, 0))

        # Draw airplane on top
        for px, py in airplane_pixels:
            draw.point((x + px, y + py), fill=color)
    
    def _get_font_height(self, font) -> int:
        """Get the height of a font for proper spacing calculations."""
        try:
            if hasattr(font, 'size'):
                # For PIL ImageFont
                return font.size
            else:
                # For BDF fonts or other types, estimate based on common sizes
                return 8  # Default fallback
        except Exception:
            return 8  # Safe fallback
    
    def _calculate_line_spacing(self, font, padding_factor: float = 1.2) -> int:
        """Calculate proper line spacing based on font height with padding."""
        font_height = self._get_font_height(font)
        return int(font_height * padding_factor)
    
    def _is_callsign_worth_fetching(self, callsign: str) -> bool:
        """Determine if a callsign is worth fetching flight plan data for."""
        return is_callsign_worth_fetching(callsign, self.min_callsign_length, self.airline_callsign_prefixes)
    
    def _categorize_aircraft(self, callsign: str) -> str:
        """Categorize aircraft based on callsign patterns."""
        return categorize_aircraft(callsign, self.airline_callsign_prefixes)
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within API rate limits and daily budget."""
        current_time = time.time()
        current_date = datetime.now().date()
        
        # Reset daily counter if new day
        if self.last_reset_date != current_date:
            self.api_calls_today = 0
            self.last_reset_date = current_date
            logger.info(f"[Flight Tracker] Daily API budget reset: {self.daily_api_budget} calls available")
        
        # Check daily budget first (more restrictive)
        if self.api_calls_today >= self.daily_api_budget:
            logger.warning(f"[Flight Tracker] Daily API budget reached: {self.api_calls_today}/{self.daily_api_budget} calls today")
            return False
        
        # Check hourly rate limit
        hour_ago = current_time - 3600  # 1 hour ago
        self.api_call_timestamps = [ts for ts in self.api_call_timestamps if ts > hour_ago]
        
        if len(self.api_call_timestamps) >= self.max_api_calls_per_hour:
            logger.warning(f"[Flight Tracker] Hourly rate limit reached: {len(self.api_call_timestamps)}/{self.max_api_calls_per_hour} calls in the last hour")
            return False
        
        return True
    
    def _record_api_call(self):
        """Record an API call for rate limiting and cost monitoring."""
        current_time = time.time()
        self.api_call_timestamps.append(current_time)
        self.api_calls_today += 1
        self.monthly_api_calls += 1
        
        # Calculate current costs
        current_cost = self.monthly_api_calls * self.cost_per_call
        budget_usage = current_cost / self.monthly_budget
        
        # Log cost information
        logger.info(f"[Flight Tracker] API call recorded. Today: {self.api_calls_today}/{self.daily_api_budget}, "
                   f"Monthly: {self.monthly_api_calls} calls (${current_cost:.2f}), "
                   f"Budget usage: {budget_usage:.1%}")
        
        # Budget warning
        if budget_usage >= self.budget_warning_threshold:
            logger.warning(f"[Flight Tracker] BUDGET WARNING: {budget_usage:.1%} of monthly budget used "
                          f"(${current_cost:.2f}/${self.monthly_budget:.2f})")
        
        # Smart budget management - reduce daily budget as month progresses
        days_in_month = 30
        current_day = datetime.now().day
        if current_day > 15:  # After mid-month, be more conservative
            self.daily_api_budget = min(self.daily_api_budget, 40)  # Reduce to 40 calls/day
            logger.info(f"[Flight Tracker] Mid-month budget adjustment: {self.daily_api_budget} calls/day")
        
        # Emergency stop at 95% budget
        if budget_usage >= 0.95:
            logger.error(f"[Flight Tracker] EMERGENCY STOP: 95% of budget reached. Disabling API calls.")
            self.daily_api_budget = 0  # Effectively disable further calls
    
    
    def _fetch_aircraft_data(self) -> Optional[Dict]:
        """Fetch aircraft data from SkyAware API."""
        try:
            response = requests.get(self.skyaware_url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            # Cache the data
            self.cache_manager.set('flight_tracker_data', data)
            
            logger.debug(f"[Flight Tracker] Fetched data: {len(data.get('aircraft', []))} aircraft")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"[Flight Tracker] Failed to fetch aircraft data: {e}")
            
            # Try to use cached data
            cached_data = self.cache_manager.get('flight_tracker_data')
            if cached_data:
                logger.info("[Flight Tracker] Using cached aircraft data")
                return cached_data
            
            return None
    
    # -------------------------------------------------------------------------
    # FlightRadar24 data source methods
    # -------------------------------------------------------------------------

    # Compact lookup table: airline ICAO (3-char) -> short display name.
    # Used as a zero-cost fallback when FR24 detail has not been fetched yet.
    _AIRLINE_ICAO_NAMES: Dict[str, str] = {
        'AAL': 'American', 'UAL': 'United', 'DAL': 'Delta', 'SWA': 'Southwest',
        'JBU': 'JetBlue', 'ASQ': 'SkyWest', 'ENY': 'Envoy', 'FFT': 'Frontier',
        'NKS': 'Spirit', 'BAW': 'British', 'AFR': 'Air France', 'DLH': 'Lufthansa',
        'KLM': 'KLM', 'SAS': 'SAS', 'IBE': 'Iberia', 'EZY': 'easyJet',
        'RYR': 'Ryanair', 'AUA': 'Austrian', 'SWR': 'Swiss', 'AZA': 'Alitalia',
        'TAP': 'TAP Air', 'QFA': 'Qantas', 'SIA': 'Singapore', 'CCA': 'Air China',
        'CSN': 'China Southern', 'CES': 'China Eastern', 'KAL': 'Korean Air',
        'ANA': 'ANA', 'JAL': 'Japan Air', 'EAL': 'Emirates', 'UAE': 'Emirates',
        'QTR': 'Qatar', 'ETH': 'Ethiopian', 'THY': 'Turkish', 'SVA': 'Saudia',
        'UPS': 'UPS', 'FDX': 'FedEx', 'GTI': 'Atlas Air', 'DHL': 'DHL',
        'ABX': 'ABX Air', 'CPZ': 'CommuteAir', 'WN': 'Southwest', 'AA': 'American',
        'UA': 'United', 'DL': 'Delta', 'B6': 'JetBlue', 'NK': 'Spirit',
        'F9': 'Frontier', 'G4': 'Allegiant',
    }

    def _get_fr24_bounds(self) -> str:
        """Compute FR24 bounds string (laMax,laMin,loMin,loMax) from center + radius."""
        # Approximate degree offset for the configured radius
        lat_deg = self.map_radius_miles / 69.0
        lon_deg = self.map_radius_miles / (69.0 * math.cos(math.radians(self.center_lat)))
        la_max = round(self.center_lat + lat_deg, 6)
        la_min = round(self.center_lat - lat_deg, 6)
        lo_min = round(self.center_lon - lon_deg, 6)
        lo_max = round(self.center_lon + lon_deg, 6)
        return f"{la_max},{la_min},{lo_min},{lo_max}"

    def _fetch_fr24_feed(self) -> Optional[Dict[str, Dict]]:
        """Fetch real-time flight data from FlightRadar24 feed.js.

        Returns a dict keyed by ICAO hex with normalized aircraft dicts that
        match the format used by _process_aircraft_data output.  Also stores
        the raw FR24 flight ID inside each dict as 'fr24_id' so we can later
        call the detail endpoint if needed.
        """
        bounds = self._get_fr24_bounds()
        url = "https://data-cloud.flightradar24.com/zones/fcgi/feed.js"
        params = {
            "bounds": bounds,
            "faa": 1, "satellite": 1, "mlat": 1, "flarm": 1,
            "adsb": 1, "gnd": 0, "air": 1, "vehicles": 0,
            "estimated": 1, "maxage": 14400, "gliders": 0, "stats": 1,
        }
        try:
            response = requests.get(url, params=params, headers=self._fr24_headers, timeout=10)
            response.raise_for_status()
            raw = response.json()
        except Exception:
            logger.exception("[Flight Tracker] FR24 feed fetch failed")
            return None

        current_time = time.time()
        result: Dict[str, Dict] = {}

        for fr24_id, entry in raw.items():
            # The response contains metadata keys that are not flight arrays
            if not isinstance(entry, list) or len(entry) < 13:
                continue

            icao = str(entry[0]).upper() if entry[0] else ''
            if not icao:
                continue

            lat = entry[1] if isinstance(entry[1], (int, float)) else None
            lon = entry[2] if isinstance(entry[2], (int, float)) else None
            if lat is None or lon is None:
                continue

            distance_miles = self._calculate_distance(lat, lon, self.center_lat, self.center_lon)
            if distance_miles > self.map_radius_miles:
                continue

            heading = entry[3] if len(entry) > 3 else 0
            altitude = entry[4] if len(entry) > 4 else 0
            speed = entry[5] if len(entry) > 5 else 0
            aircraft_type_code = entry[8] if len(entry) > 8 else ''
            registration = entry[9] if len(entry) > 9 else ''
            origin_iata = entry[11] if len(entry) > 11 else ''
            destination_iata = entry[12] if len(entry) > 12 else ''
            flight_number = entry[13] if len(entry) > 13 else ''
            on_ground = bool(entry[14]) if len(entry) > 14 else False
            callsign = str(entry[16]).strip() if len(entry) > 16 and entry[16] else flight_number
            airline_icao = str(entry[18]).strip() if len(entry) > 18 and entry[18] else ''

            if not callsign:
                callsign = icao

            if on_ground:
                altitude = 0

            color = self._altitude_to_color(altitude)

            # Resolve a human-readable airline name from the lookup table
            airline_name = self._AIRLINE_ICAO_NAMES.get(airline_icao, '')

            result[icao] = {
                'icao': icao,
                'fr24_id': fr24_id,
                'callsign': callsign,
                'registration': registration,
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'speed': speed,
                'heading': heading,
                'aircraft_type': aircraft_type_code,
                'origin': origin_iata,
                'destination': destination_iata,
                'airline_icao': airline_icao,
                'airline_name': airline_name,
                'distance_miles': distance_miles,
                'color': color,
                'last_seen': current_time,
            }

        logger.info(f"[Flight Tracker] FR24 feed returned {len(result)} aircraft in range ({self.map_radius_miles}mi)")
        return result

    def _fetch_fr24_detail(self, fr24_id: str) -> Optional[Dict]:
        """Fetch flight detail from FR24 clickhandler endpoint.

        Returns parsed JSON or None on failure.  Results are cached internally
        for fr24_detail_cache_ttl seconds.
        """
        # Check internal cache first
        cached = self.fr24_detail_cache.get(fr24_id)
        if cached and time.time() - cached.get('_fetched_at', 0) < self.fr24_detail_cache_ttl:
            return cached

        url = "https://data-live.flightradar24.com/clickhandler/"
        try:
            response = requests.get(url, params={"flight": fr24_id}, headers=self._fr24_headers, timeout=8)
            response.raise_for_status()
            data = response.json()
            data['_fetched_at'] = time.time()
            self.fr24_detail_cache[fr24_id] = data
            return data
        except Exception as e:
            logger.warning(f"[Flight Tracker] FR24 detail fetch failed for {fr24_id}: {e}")
            return None

    def _enrich_aircraft_from_fr24_detail(self, aircraft: Dict) -> None:
        """Fetch FR24 detail for an aircraft and apply airline name + timing fields in-place."""
        fr24_id = aircraft.get('fr24_id')
        if not fr24_id:
            return

        detail = self._fetch_fr24_detail(fr24_id)
        if not detail:
            return

        # Full airline name
        airline = detail.get('airline') or {}
        if airline.get('name') and not aircraft.get('airline_name'):
            aircraft['airline_name'] = airline['name']

        # Full airport names for progress calculation
        airport = detail.get('airport') or {}
        origin_info = airport.get('origin') or {}
        dest_info = airport.get('destination') or {}
        origin_pos = origin_info.get('position') or {}
        dest_pos = dest_info.get('position') or {}
        if origin_pos.get('latitude') and origin_pos.get('longitude') and not aircraft.get('origin_lat'):
            aircraft['origin_lat'] = origin_pos['latitude']
            aircraft['origin_lon'] = origin_pos['longitude']
        if dest_pos.get('latitude') and dest_pos.get('longitude') and not aircraft.get('dest_lat'):
            aircraft['dest_lat'] = dest_pos['latitude']
            aircraft['dest_lon'] = dest_pos['longitude']

        # Timing / delay data
        time_data = detail.get('time') or {}
        aircraft['fr24_time'] = time_data

    def _update_from_fr24(self) -> None:
        """Fetch primary aircraft data from FR24 and update self.aircraft_data."""
        feed = self._fetch_fr24_feed()
        if feed is None:
            return

        current_time = time.time()
        for icao, new_info in feed.items():
            existing = self.aircraft_data.get(icao, {})
            # Preserve previously fetched detail fields
            for field in ('airline_name', 'origin_lat', 'origin_lon', 'dest_lat', 'dest_lon', 'fr24_time'):
                if field in existing and field not in new_info:
                    new_info[field] = existing[field]
            self.aircraft_data[icao] = new_info

            # Update trail
            if self.show_trails:
                if icao not in self.aircraft_trails:
                    self.aircraft_trails[icao] = []
                self.aircraft_trails[icao].append((new_info['lat'], new_info['lon'], current_time))
                if len(self.aircraft_trails[icao]) > self.trail_length:
                    self.aircraft_trails[icao] = self.aircraft_trails[icao][-self.trail_length:]

        # Remove stale aircraft
        stale = [icao for icao, info in self.aircraft_data.items()
                 if current_time - info['last_seen'] > 60]
        for icao in stale:
            del self.aircraft_data[icao]
            self.aircraft_trails.pop(icao, None)

        # Queue FR24 detail fetches for close/interesting aircraft
        for icao, info in sorted(self.aircraft_data.items(), key=lambda x: x[1]['distance_miles']):
            fr24_id = info.get('fr24_id')
            if fr24_id and fr24_id not in self.fr24_detail_cache:
                if self._is_callsign_worth_fetching(info.get('callsign', '')):
                    self.pending_fr24_details[fr24_id] = icao

        self._update_flight_records()

    def _maybe_refresh_fr24_enrichment(self) -> None:
        """Enrichment mode: call FR24 feed on a slower cadence to fill in
        origin/destination/aircraft type for aircraft already tracked via SkyAware."""
        current_time = time.time()
        if current_time - self.last_fr24_enrichment < self.fr24_enrichment_interval:
            return
        self.last_fr24_enrichment = current_time

        logger.info("[Flight Tracker] Refreshing FR24 enrichment data")
        feed = self._fetch_fr24_feed()
        if not feed:
            return

        # Index FR24 data by ICAO hex and update aircraft_data fields
        matched = 0
        for icao, fr24_info in feed.items():
            if icao in self.aircraft_data:
                ac = self.aircraft_data[icao]
                # Only fill in fields that are missing or unknown
                if not ac.get('origin') and fr24_info.get('origin'):
                    ac['origin'] = fr24_info['origin']
                if not ac.get('destination') and fr24_info.get('destination'):
                    ac['destination'] = fr24_info['destination']
                if (not ac.get('aircraft_type') or ac['aircraft_type'] == 'Unknown') and fr24_info.get('aircraft_type'):
                    ac['aircraft_type'] = fr24_info['aircraft_type']
                if not ac.get('airline_icao') and fr24_info.get('airline_icao'):
                    ac['airline_icao'] = fr24_info['airline_icao']
                if not ac.get('airline_name') and fr24_info.get('airline_name'):
                    ac['airline_name'] = fr24_info['airline_name']
                if not ac.get('fr24_id') and fr24_info.get('fr24_id'):
                    ac['fr24_id'] = fr24_info['fr24_id']
                matched += 1

        logger.info(f"[Flight Tracker] FR24 enrichment matched {matched}/{len(self.aircraft_data)} tracked aircraft")
        self._update_flight_records()

    def _background_fetch_fr24_details(self) -> None:
        """Fetch FR24 detail for queued flights (airline name, airport positions, timing)."""
        if not self.pending_fr24_details:
            return

        # Process up to 3 per update cycle to avoid blocking
        to_process = list(self.pending_fr24_details.items())[:3]
        for fr24_id, icao in to_process:
            if icao in self.aircraft_data:
                self._enrich_aircraft_from_fr24_detail(self.aircraft_data[icao])
            del self.pending_fr24_details[fr24_id]

    # -------------------------------------------------------------------------
    # Flight record tracking (all-time closest / farthest)
    # -------------------------------------------------------------------------

    def _load_flight_records(self) -> None:
        """Load persisted closest/farthest records from disk."""
        try:
            if self._flight_records_path.exists():
                with open(self._flight_records_path) as f:
                    data = json.load(f)
                self._closest_record = data.get('closest')
                self._farthest_record = data.get('farthest')
                logger.info(f"[Flight Tracker] Loaded flight records: closest={self._closest_record and self._closest_record.get('callsign')}, farthest={self._farthest_record and self._farthest_record.get('callsign')}")
        except Exception as e:
            logger.warning(f"[Flight Tracker] Could not load flight records: {e}")

    def _save_flight_records(self) -> None:
        """Persist closest/farthest records to disk."""
        try:
            self._flight_records_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._flight_records_path, 'w') as f:
                json.dump({'closest': self._closest_record, 'farthest': self._farthest_record}, f, indent=2)
        except Exception as e:
            logger.warning(f"[Flight Tracker] Could not save flight records: {e}")

    def _make_record_snapshot(self, aircraft: Dict) -> Dict:
        """Create a storable snapshot of a flight for record keeping."""
        return {
            'callsign': aircraft.get('callsign', ''),
            'distance_miles': aircraft.get('distance_miles', 0),
            'altitude': aircraft.get('altitude', 0),
            'speed': aircraft.get('speed', 0),
            'aircraft_type': aircraft.get('aircraft_type', ''),
            'origin': aircraft.get('origin', ''),
            'destination': aircraft.get('destination', ''),
            'airline_name': aircraft.get('airline_name', ''),
            'timestamp': datetime.now().isoformat(),
        }

    def _update_flight_records(self) -> None:
        """Check current aircraft against all-time closest/farthest records."""
        if not self.flight_records_enabled or not self.aircraft_data:
            return

        updated = False
        for ac in self.aircraft_data.values():
            dist = ac.get('distance_miles', 0)
            if self._closest_record is None or dist < self._closest_record['distance_miles']:
                self._closest_record = self._make_record_snapshot(ac)
                logger.info(f"[Flight Tracker] New closest record: {ac['callsign']} at {dist:.3f} miles")
                updated = True
            if self._farthest_record is None or dist > self._farthest_record['distance_miles']:
                self._farthest_record = self._make_record_snapshot(ac)
                logger.info(f"[Flight Tracker] New farthest record: {ac['callsign']} at {dist:.1f} miles")
                updated = True

        if updated:
            self._save_flight_records()

    # -------------------------------------------------------------------------
    # Flight progress / delay helpers
    # -------------------------------------------------------------------------

    def _compute_flight_progress(self, aircraft: Dict) -> Optional[float]:
        """Return flight progress as a 0.0-1.0 fraction if lat/lon for origin
        and destination are available, otherwise None."""
        origin_lat = aircraft.get('origin_lat')
        origin_lon = aircraft.get('origin_lon')
        dest_lat = aircraft.get('dest_lat')
        dest_lon = aircraft.get('dest_lon')
        if None in (origin_lat, origin_lon, dest_lat, dest_lon):
            return None

        total = self._calculate_distance(origin_lat, origin_lon, dest_lat, dest_lon)
        if total < 1:
            return None

        flown = self._calculate_distance(origin_lat, origin_lon, aircraft['lat'], aircraft['lon'])
        return max(0.0, min(1.0, flown / total))

    def _format_delay(self, aircraft: Dict) -> Optional[str]:
        """Return a short delay string like 'ON TIME', '+15m', or None."""
        time_data = aircraft.get('fr24_time') or {}
        # FR24 time structure varies; try scheduled vs actual arrival
        scheduled = time_data.get('scheduled') or {}
        real = time_data.get('real') or {}
        estimated = time_data.get('estimated') or {}

        scheduled_arrival = scheduled.get('arrival') or scheduled.get('arr')
        actual_arrival = real.get('arrival') or real.get('arr') or estimated.get('arrival') or estimated.get('arr')

        if not scheduled_arrival or not actual_arrival:
            return None

        try:
            delay_minutes = round((actual_arrival - scheduled_arrival) / 60)
        except (TypeError, ValueError):
            return None

        if delay_minutes <= 0:
            return 'ON TIME'
        return f'+{delay_minutes}m'

    def _delay_color(self, delay_str: Optional[str]) -> Tuple[int, int, int]:
        """Return a color for a delay string."""
        if not delay_str or delay_str == 'ON TIME':
            return (0, 200, 0)
        try:
            mins = int(delay_str.replace('+', '').replace('m', ''))
        except ValueError:
            return (200, 200, 200)
        if mins < 30:
            return (255, 255, 0)   # Yellow
        if mins < 60:
            return (255, 150, 0)   # Orange
        return (255, 50, 50)       # Red

    def _ensure_database_loaded(self) -> None:
        """Lazy-load the aircraft database on first use.
        
        This defers loading the 70MB database until it's actually needed,
        significantly speeding up plugin initialization.
        """
        if self.aircraft_db_loaded:
            return  # Already attempted to load (successful or not)
        
        self.aircraft_db_loaded = True
        
        if not self.use_offline_db:
            logger.debug("[Flight Tracker] Offline database disabled in config")
            return
        
        try:
            load_start = time.time()
            self.aircraft_db = AircraftDatabase(self.aircraft_db_cache_dir)
            load_time = time.time() - load_start
            stats = self.aircraft_db.get_stats()
            logger.info(f"[Flight Tracker] Offline aircraft database loaded: {stats['total_aircraft']} aircraft, {stats['database_size_mb']:.1f}MB in {load_time:.2f}s")
            if stats['last_update']:
                logger.info(f"[Flight Tracker] Database last updated: {stats['last_update']}")
        except Exception as e:
            logger.warning(f"[Flight Tracker] Failed to load offline aircraft database: {e}")
            self.aircraft_db = None
    
    def _get_aircraft_info_from_database(self, icao24: str, registration: str = None) -> Optional[Dict]:
        """Get aircraft information from offline database.
        
        Args:
            icao24: ICAO24 hex code
            registration: Optional registration number
            
        Returns:
            Dictionary with aircraft info or None
        """
        # Lazy-load database on first use
        self._ensure_database_loaded()
        
        if not self.aircraft_db:
            return None
        
        # Try ICAO24 first
        info = self.aircraft_db.lookup_by_icao24(icao24)
        
        # Try registration as fallback
        if not info and registration:
            info = self.aircraft_db.lookup_by_registration(registration)
        
        return info
    
    def _get_flight_plan_data(self, callsign: str, icao24: str = None) -> Dict[str, str]:
        """Get flight plan data for a callsign (origin/destination) and aircraft info.

        Priority order:
          1. FR24 enrichment cache (already in aircraft_data — free, no API)
          2. Offline FAA database (aircraft type only, no API)
          3. FlightAware AeroAPI (if enabled and key configured)

        Args:
            callsign: Flight callsign
            icao24: ICAO24 hex code for cache/database lookup

        Returns:
            Dictionary with origin, destination, and aircraft_type
        """
        # Always provide aircraft type categorization as fallback
        aircraft_category = self._categorize_aircraft(callsign)

        # Priority 0: Check aircraft_data for already-enriched FR24 data
        if icao24:
            icao_upper = icao24.upper()
            ac = self.aircraft_data.get(icao_upper)
            if ac:
                origin = ac.get('origin') or ''
                destination = ac.get('destination') or ''
                aircraft_type = ac.get('aircraft_type') or ''
                airline_name = ac.get('airline_name') or ''
                if origin or destination or aircraft_type:
                    logger.debug(f"[Flight Tracker] FR24 enrichment hit for {callsign}: {origin}->{destination} ({aircraft_type})")
                    return {
                        'origin': origin or 'Unknown',
                        'destination': destination or 'Unknown',
                        'aircraft_type': aircraft_type or aircraft_category,
                        'airline_name': airline_name,
                        'source': 'fr24',
                    }
        
        # Try offline database first for aircraft type info
        aircraft_type = 'Unknown'
        if self.aircraft_db and icao24:
            db_info = self._get_aircraft_info_from_database(icao24, callsign)
            if db_info:
                # Build aircraft type string from database info
                if db_info.get('manufacturer') and db_info.get('model'):
                    aircraft_type = f"{db_info['manufacturer']} {db_info['model']}"
                elif db_info.get('type_aircraft'):
                    aircraft_type = db_info['type_aircraft']
                elif db_info.get('model'):
                    aircraft_type = db_info['model']
                
                logger.debug(f"[Flight Tracker] Found {callsign} in offline DB: {aircraft_type}")
                
                # If we got aircraft type from database, return early without API call
                # We still don't have origin/destination, but that's okay for most use cases
                return {
                    'origin': 'Unknown',
                    'destination': 'Unknown', 
                    'aircraft_type': aircraft_type,
                    'registration': db_info.get('registration', 'Unknown'),
                    'operator': db_info.get('operator', 'Unknown'),
                    'source': 'offline_db'
                }
        
        if not self.flight_plan_enabled:
            logger.debug(f"[Flight Tracker] Flight plan disabled for {callsign} (flight_plan_enabled=False)")
            return {'origin': 'Unknown', 'destination': 'Unknown', 'aircraft_type': aircraft_type or aircraft_category}
        
        if not self.flightaware_api_key:
            logger.info(f"[Flight Tracker] No API key configured for {callsign}")
            return {'origin': 'Unknown', 'destination': 'Unknown', 'aircraft_type': aircraft_category}
        
        # Check if callsign is worth fetching (cost control)
        if not self._is_callsign_worth_fetching(callsign):
            logger.info(f"[Flight Tracker] Skipping flight plan fetch for {callsign} (not worth fetching - category: {aircraft_category})")
            return {'origin': 'Unknown', 'destination': 'Unknown', 'aircraft_type': aircraft_category}
        
        # Check rate limiting
        if not self._check_rate_limit():
            logger.warning(f"[Flight Tracker] Rate limit reached, skipping API call for {callsign}")
            return {'origin': 'Unknown', 'destination': 'Unknown', 'aircraft_type': aircraft_category}
        
        # Use cache manager for flight plan data
        cache_key = f"flight_plan_{callsign}"
        cached_data = self.cache_manager.get(cache_key, max_age=self.cache_ttl_seconds)
        
        if cached_data:
            logger.debug(f"[Flight Tracker] Using cached flight plan for {callsign}")
            return cached_data
        
        logger.info(f"[Flight Tracker] Fetching flight plan data for {callsign}")
        
        try:
            # FlightAware AeroAPI integration
            url = f"https://aeroapi.flightaware.com/aeroapi/flights/{callsign}"
            headers = {"x-apikey": self.flightaware_api_key}
            
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                # Handle the API response format - it returns an array of flights
                if 'flights' in data and data['flights']:
                    # Get the first (most recent) flight
                    flight = data['flights'][0]
                    
                    # Try multiple field names for aircraft type
                    aircraft_type = (
                        flight.get('aircraft_type') or 
                        flight.get('aircraft', {}).get('type') or
                        flight.get('type') or
                        'Unknown'
                    )
                    
                    flight_plan = {
                        'origin': flight.get('origin', {}).get('code', 'Unknown'),
                        'destination': flight.get('destination', {}).get('code', 'Unknown'),
                        'aircraft_type': aircraft_type
                    }
                    
                    # Log the full flight data for debugging (first time only)
                    logger.debug(f"[Flight Tracker] API response keys for {callsign}: {list(flight.keys())}")
                else:
                    # Fallback for single flight response format
                    aircraft_type = (
                        data.get('aircraft_type') or 
                        data.get('aircraft', {}).get('type') or
                        data.get('type') or
                        'Unknown'
                    )
                    
                    flight_plan = {
                        'origin': data.get('origin', {}).get('code', 'Unknown'),
                        'destination': data.get('destination', {}).get('code', 'Unknown'),
                        'aircraft_type': aircraft_type
                    }
                
                # Cache using the cache manager
                self.cache_manager.set(cache_key, flight_plan)
                self._record_api_call()
                logger.info(f"[Flight Tracker] Successfully fetched and cached flight plan for {callsign}: {flight_plan['origin']} -> {flight_plan['destination']} ({flight_plan['aircraft_type']})")
                return flight_plan
            else:
                logger.warning(f"[Flight Tracker] API returned status {response.status_code} for {callsign}: {response.text[:100]}")
                return {'origin': 'Unknown', 'destination': 'Unknown', 'aircraft_type': 'Unknown'}
                
        except Exception as e:
            logger.warning(f"[Flight Tracker] Failed to fetch flight plan for {callsign}: {e}")
            return {'origin': 'Unknown', 'destination': 'Unknown', 'aircraft_type': 'Unknown'}
    
    def _process_aircraft_data(self, data: Dict) -> None:
        """Process and update aircraft data."""
        if not data or 'aircraft' not in data:
            logger.warning("[Flight Tracker] No aircraft data in response")
            return
        
        total_aircraft = len(data['aircraft'])
        logger.info(f"[Flight Tracker] Processing {total_aircraft} aircraft from SkyAware")
        
        current_time = time.time()
        active_icao = set()
        aircraft_with_position = 0
        aircraft_in_range = 0
        
        for aircraft in data['aircraft']:
            # Extract required fields
            icao = aircraft.get('hex', '').upper()
            if not icao:
                continue
            
            # Check if aircraft has valid position
            lat = aircraft.get('lat')
            lon = aircraft.get('lon')
            if lat is None or lon is None:
                continue
            
            aircraft_with_position += 1
            
            # Calculate distance from center
            distance_miles = self._calculate_distance(lat, lon, self.center_lat, self.center_lon)
            
            # Filter by radius
            if distance_miles > self.map_radius_miles:
                continue
            
            aircraft_in_range += 1
            
            active_icao.add(icao)
            
            # Extract other fields
            altitude = aircraft.get('alt_baro', aircraft.get('alt_geom', 0))
            if altitude == 'ground':
                altitude = 0

            callsign = aircraft.get('flight', '').strip() or icao
            speed = aircraft.get('gs', 0)  # Ground speed in knots
            heading = aircraft.get('track', aircraft.get('heading', 0))
            registration = aircraft.get('r', '')  # Registration/tail number
            aircraft_type = aircraft.get('t', 'Unknown')
            on_ground = aircraft.get('alt_baro') == 'ground'
            category = aircraft.get('category', '')  # ICAO wake turbulence category
            # SkyAware baro_rate is ft/min, geom_rate is also ft/min
            vertical_rate = aircraft.get('baro_rate', aircraft.get('geom_rate'))

            # Calculate color based on altitude
            color = self._altitude_to_color(altitude)

            # Build aircraft dict
            aircraft_info = {
                'icao': icao,
                'callsign': callsign,
                'registration': registration,
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'speed': speed,
                'heading': heading,
                'vertical_rate': vertical_rate,
                'aircraft_type': aircraft_type,
                'distance_miles': distance_miles,
                'on_ground': on_ground,
                'category': category,
                'color': color,
                'last_seen': current_time
            }
            
            # Update aircraft data
            self.aircraft_data[icao] = aircraft_info
            
            # Update trail if enabled
            if self.show_trails:
                if icao not in self.aircraft_trails:
                    self.aircraft_trails[icao] = []
                
                self.aircraft_trails[icao].append((lat, lon, current_time))
                
                # Limit trail length
                if len(self.aircraft_trails[icao]) > self.trail_length:
                    self.aircraft_trails[icao] = self.aircraft_trails[icao][-self.trail_length:]
        
        # Clean up old aircraft (not seen in last 60 seconds)
        stale_icao = [icao for icao, info in self.aircraft_data.items() 
                      if current_time - info['last_seen'] > 60]
        for icao in stale_icao:
            del self.aircraft_data[icao]
            if icao in self.aircraft_trails:
                del self.aircraft_trails[icao]
        
        logger.info(f"[Flight Tracker] Summary - Total: {total_aircraft}, With position: {aircraft_with_position}, In range ({self.map_radius_miles}mi): {aircraft_in_range}, Tracking: {len(self.aircraft_data)}, Removed stale: {len(stale_icao)}")
        self._update_flight_records()
    
    def _altitude_to_color(self, altitude: float) -> Tuple[int, int, int]:
        """Convert altitude to color using smooth gradient interpolation matching the altitude scale."""
        return altitude_to_color(altitude, self.altitude_colors)
    
    def _calculate_zoom_level(self) -> int:
        """Calculate the appropriate zoom level for tile detail.
        
        This determines tile detail level, NOT the geographic area shown.
        The area is controlled by map_radius_miles independently.
        """
        effective_radius = self.map_radius_miles / self.zoom_factor
        
        # Choose zoom level based on desired detail, not scale
        # We'll scale the tiles to fit the desired radius afterward
        if effective_radius <= 5:
            return 12  # High detail for very local areas
        elif effective_radius <= 25:
            return 11  # Good detail for city/regional areas
        elif effective_radius <= 100:
            return 10  # Regional detail
        elif effective_radius <= 300:
            return 9   # State-level detail
        elif effective_radius <= 600:
            return 8   # Multi-state detail
        elif effective_radius <= 1200:
            return 7   # Country-level detail
        else:
            return 6   # Continental detail
    
    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two lat/lon points in miles using Haversine formula."""
        return haversine_miles(lat1, lon1, lat2, lon2)
    
    def _latlon_to_pixel(self, lat: float, lon: float) -> Optional[Tuple[int, int]]:
        """Convert lat/lon to pixel coordinates on the display."""
        # Calculate pixels per mile based on the DESIRED display radius
        # This ensures we show exactly map_radius_miles * 2 across the display
        
        effective_radius = self.map_radius_miles / self.zoom_factor
        
        # The display shows (effective_radius * 2) miles across
        # Calculate pixels per mile to fit this area
        pixels_per_mile = self.display_width / (effective_radius * 2)
        
        # Calculate distance in miles from center to aircraft
        distance_miles = self._calculate_distance(self.center_lat, self.center_lon, lat, lon)
        
        # Calculate bearing from center to aircraft (in radians)
        lat1_rad = math.radians(self.center_lat)
        lat2_rad = math.radians(lat)
        delta_lon_rad = math.radians(lon - self.center_lon)
        
        x = math.sin(delta_lon_rad) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon_rad)
        bearing_rad = math.atan2(x, y)
        
        # Convert distance and bearing to pixel offset from center
        pixel_distance = distance_miles * pixels_per_mile
        offset_x = pixel_distance * math.sin(bearing_rad)
        offset_y = -pixel_distance * math.cos(bearing_rad)  # Negative because screen Y increases downward
        
        # Map to display coordinates (center is at display_width/2, display_height/2)
        x_pixel = int(self.display_width / 2 + offset_x)
        y_pixel = int(self.display_height / 2 + offset_y)
        
        # Debug logging
        logger.debug(f"[Flight Tracker] Converting ({lat:.6f}, {lon:.6f}) to pixel ({x_pixel}, {y_pixel})")
        logger.debug(f"[Flight Tracker] Distance: {distance_miles:.2f}mi, Bearing: {math.degrees(bearing_rad):.1f}°, Pixels/mile: {pixels_per_mile:.2f}, Radius: {effective_radius:.1f}mi")
        
        # Check if within display bounds
        if 0 <= x_pixel < self.display_width and 0 <= y_pixel < self.display_height:
            return (x_pixel, y_pixel)
        
        # Rate limit bounds warnings to prevent spam
        coord_key = f"{lat:.6f},{lon:.6f}"
        current_time = time.time()
        
        if coord_key not in self.bounds_warning_cache or \
           current_time - self.bounds_warning_cache[coord_key] > self.bounds_warning_interval:
            logger.debug(f"[Flight Tracker] Coordinate ({lat}, {lon}) -> pixel ({x}, {y}) is outside display bounds {self.display_width}x{self.display_height}")
            self.bounds_warning_cache[coord_key] = current_time
        
        return None
    
    def _latlon_to_tile_coords(self, lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """Convert lat/lon to tile coordinates for a given zoom level."""
        n = 2.0 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
        return (x, y)
    
    def _get_tile_urls(self, x: int, y: int, zoom: int) -> List[str]:
        """Get multiple tile URLs to try in order of preference."""
        # If custom tile server is configured, use it for all requests
        if self.custom_tile_server:
            # Remove trailing slash if present
            base_url = self.custom_tile_server.rstrip('/')
            return [f"{base_url}/tile/{zoom}/{x}/{y}.png"]
        
        if self.tile_provider == 'osm':
            # Use multiple OSM mirrors to avoid blocking
            return [
                f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                f"https://a.tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                f"https://b.tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                f"https://c.tile.openstreetmap.org/{zoom}/{x}/{y}.png"
            ]
        elif self.tile_provider == 'carto':
            return [
                f"https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{zoom}/{x}/{y}.png",
                f"https://cartodb-basemaps-b.global.ssl.fastly.net/light_all/{zoom}/{x}/{y}.png",
                f"https://cartodb-basemaps-c.global.ssl.fastly.net/light_all/{zoom}/{x}/{y}.png",
                f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"  # Fallback to OSM
            ]
        elif self.tile_provider == 'carto_dark':
            return [
                f"https://cartodb-basemaps-a.global.ssl.fastly.net/dark_all/{zoom}/{x}/{y}.png",
                f"https://cartodb-basemaps-b.global.ssl.fastly.net/dark_all/{zoom}/{x}/{y}.png",
                f"https://cartodb-basemaps-c.global.ssl.fastly.net/dark_all/{zoom}/{x}/{y}.png",
                f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"  # Fallback to OSM
            ]
        elif self.tile_provider == 'stamen':
            return [
                f"https://stamen-tiles.a.ssl.fastly.net/terrain/{zoom}/{x}/{y}.png",
                f"https://stamen-tiles.b.ssl.fastly.net/terrain/{zoom}/{x}/{y}.png",
                f"https://stamen-tiles-c.a.ssl.fastly.net/terrain/{zoom}/{x}/{y}.png",
                f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"  # Fallback to OSM
            ]
        elif self.tile_provider == 'esri':
            return [
                f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{zoom}/{y}/{x}",
                f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{zoom}/{y}/{x}",
                f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"  # Fallback to OSM
            ]
        else:
            # Default to OSM with multiple mirrors
            return [
                f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                f"https://a.tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                f"https://b.tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                f"https://c.tile.openstreetmap.org/{zoom}/{x}/{y}.png"
            ]
    
    def _get_tile_url(self, x: int, y: int, zoom: int) -> str:
        """Get the URL for a map tile based on provider (backward compatibility)."""
        urls = self._get_tile_urls(x, y, zoom)
        return urls[0]  # Return first URL for backward compatibility
    
    def _get_tile_cache_path(self, x: int, y: int, zoom: int) -> Path:
        """Get the cache file path for a tile."""
        return self.tile_cache_dir / f"{self.tile_provider}_{zoom}_{x}_{y}.png"
    
    def _is_tile_cached(self, x: int, y: int, zoom: int) -> bool:
        """Check if a tile is cached and not expired."""
        cache_path = self._get_tile_cache_path(x, y, zoom)
        if not cache_path.exists():
            return False
        
        # Check if tile is not expired
        tile_age = time.time() - cache_path.stat().st_mtime
        return tile_age < (self.cache_ttl_hours * 3600)
    
    def _fetch_tile(self, x: int, y: int, zoom: int) -> Optional[Image.Image]:
        """Fetch a map tile, using cache if available."""
        from PIL import Image as PILImage
        
        cache_path = self._get_tile_cache_path(x, y, zoom)
        
        # Try to load from cache first
        if self._is_tile_cached(x, y, zoom):
            try:
                return PILImage.open(cache_path)
            except Exception as e:
                logger.warning(f"[Flight Tracker] Failed to load cached tile {x},{y},{zoom}: {e}")
        
        # Fetch from server - try multiple URLs
        urls = self._get_tile_urls(x, y, zoom)
        
        for i, url in enumerate(urls):
            try:
                logger.info(f"[Flight Tracker] Fetching tile {x},{y} at zoom {zoom} from: {url}")
                
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                # Check if we got an error page instead of a tile
                content_type = response.headers.get('content-type', '').lower()
                if 'text/html' in content_type or 'text/plain' in content_type:
                    logger.debug(f"[Flight Tracker] Got HTML/text response from {url}")
                    continue  # Try next URL
                
                # Check if response is too small (likely an error page)
                if len(response.content) < 2000:  # Tiles are usually much larger
                    logger.debug(f"[Flight Tracker] Tile response too small ({len(response.content)} bytes) from {url}")
                    # Try to read the error message
                    try:
                        error_text = response.content.decode('utf-8', errors='ignore')[:200]
                        logger.debug(f"[Flight Tracker] Error content: {error_text}")
                    except:
                        pass
                    continue  # Try next URL
                
                # Additional validation: try to load as image and check for text artifacts
                try:
                    import io
                    test_img = PILImage.open(io.BytesIO(response.content))
                    
                    # Check if image is too small (likely an error page rendered as image)
                    if test_img.size[0] < 100 or test_img.size[1] < 100:
                        logger.debug(f"[Flight Tracker] Tile image too small: {test_img.size}")
                        continue
                    
                    # Check for suspiciously uniform colors (error pages often have solid colors)
                    if test_img.mode == 'RGB':
                        # Convert to grayscale for analysis
                        gray_img = test_img.convert('L')
                        # Get pixel data
                        pixels = list(gray_img.getdata())
                        if len(pixels) > 0:
                            # Check if image is mostly one color (suspicious for error pages)
                            color_counts = {}
                            for pixel in pixels[::100]:  # Sample every 100th pixel for performance
                                color_counts[pixel] = color_counts.get(pixel, 0) + 1
                            
                            # If more than 80% of pixels are the same color, it's likely an error page
                            max_count = max(color_counts.values())
                            if max_count > len(pixels[::100]) * 0.8:
                                logger.debug(f"[Flight Tracker] Tile appears to be solid color (error page)")
                                continue
                    
                except Exception as e:
                    logger.debug(f"[Flight Tracker] Could not validate tile image: {e}")
                    # Continue anyway if we can't validate
                
                # If we get here, we have a valid tile
                logger.debug(f"[Flight Tracker] ✓ Successfully fetched tile from URL {i+1}: {url}")
                logger.debug(f"[Flight Tracker]   Tile size: {len(response.content)} bytes, Content-Type: {response.headers.get('content-type', 'unknown')}")
                
                # Save to cache
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(cache_path, 'wb') as f:
                        f.write(response.content)
                    logger.debug(f"[Flight Tracker] Cached tile {x},{y},{zoom}")
                    # Reset cache error count on successful cache
                    if self.cache_error_count > 0:
                        self.cache_error_count = 0
                    return PILImage.open(cache_path)
                except (PermissionError, OSError) as e:
                    logger.warning(f"[Flight Tracker] Could not save tile to cache {cache_path}: {e}")
                    # Track cache error
                    self.cache_error_count += 1
                    # Continue without caching - create a temporary file
                    import tempfile
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    temp_file.write(response.content)
                    temp_file.close()
                    return PILImage.open(temp_file.name)
                
            except Exception as e:
                logger.warning(f"[Flight Tracker] Failed to fetch tile from {url}: {e}")
                if i == len(urls) - 1:  # Last URL failed
                    return None
                continue  # Try next URL
        
        # If we get here, all URLs failed
        return None
    
    def _get_map_background(self, center_lat: float, center_lon: float) -> Optional[Image.Image]:
        """Get the map background for the current view."""
        if not self.map_bg_enabled:
            return None
        
        # Check if we should disable due to too many cache errors
        if self.disable_on_cache_error and self.cache_error_count >= self.max_cache_errors:
            logger.warning(f"[Flight Tracker] Disabling map background due to {self.cache_error_count} cache errors")
            return None
        
        # Calculate appropriate zoom level based on map radius and zoom factor
        zoom = self._calculate_zoom_level()
        effective_radius = self.map_radius_miles / self.zoom_factor
        
        logger.debug(f"[Flight Tracker] Map zoom calculation: radius={self.map_radius_miles}mi, zoom_factor={self.zoom_factor}, effective_radius={effective_radius:.2f}mi, zoom={zoom}")
        
        # Check if we can reuse the cached composite map
        current_center = (round(center_lat, 4), round(center_lon, 4))
        if (self.cached_map_bg is not None and 
            self.last_map_center == current_center and 
            self.last_map_zoom == zoom):
            # Location and zoom haven't changed, reuse cached composite
            return self.cached_map_bg
        
        # Calculate tile coordinates for center
        center_x, center_y = self._latlon_to_tile_coords(center_lat, center_lon, zoom)
        
        # Calculate how many tiles we need to cover the display
        # Each tile covers a certain lat/lon area, adjusted by zoom_factor
        lat_degrees = (effective_radius * 2) / 69.0
        lon_degrees = lat_degrees / math.cos(math.radians(center_lat))
        
        # Calculate tile coverage - optimize for reasonable number of tiles
        tiles_per_degree = 2 ** zoom
        
        # Calculate base tile coverage
        base_tiles_x = max(1, int(lon_degrees * tiles_per_degree / 360.0 * 2))
        base_tiles_y = max(1, int(lat_degrees * tiles_per_degree / 360.0 * 2))
        
        # Limit maximum tiles to prevent excessive fetching
        max_tiles = 16  # 4x4 maximum
        tiles_x = min(max_tiles, max(2, base_tiles_x + 2))  # Add 2 for buffer
        tiles_y = min(max_tiles, max(2, base_tiles_y + 2))  # Add 2 for buffer
        
        logger.info(f"[Flight Tracker] Tile calculation: base=({base_tiles_x}x{base_tiles_y}), final=({tiles_x}x{tiles_y}), total={tiles_x * tiles_y}")
        
        # Log tile server being used
        if self.custom_tile_server:
            logger.info(f"[Flight Tracker] Using custom tile server: {self.custom_tile_server}")
        else:
            logger.info(f"[Flight Tracker] Using tile provider: {self.tile_provider}")
        
        # Calculate tile bounds
        start_x = center_x - tiles_x // 2
        start_y = center_y - tiles_y // 2
        
        # Create composite image
        composite_width = tiles_x * self.tile_size
        composite_height = tiles_y * self.tile_size
        composite = Image.new('RGB', (composite_width, composite_height), (0, 0, 0))
        
        # Fetch and composite tiles
        tiles_fetched = 0
        failed_tiles = []
        
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                tile_x = start_x + tx
                tile_y = start_y + ty
                
                # Fetch tile (reduced logging for performance)
                tile_img = self._fetch_tile(tile_x, tile_y, zoom)
                if tile_img:
                    # Ensure tile is in RGB mode for proper compositing
                    if tile_img.mode != 'RGB':
                        tile_img = tile_img.convert('RGB')
                    
                    # Paste tile into composite
                    paste_x = tx * self.tile_size
                    paste_y = ty * self.tile_size
                    composite.paste(tile_img, (paste_x, paste_y))
                    tiles_fetched += 1
                    logger.debug(f"[Flight Tracker] ✓ Placed tile {tile_x},{tile_y} at ({paste_x},{paste_y})")
                else:
                    failed_tiles.append((tile_x, tile_y))
                    logger.warning(f"[Flight Tracker] ✗ Failed to fetch tile {tile_x},{tile_y}")
        
        if tiles_fetched == 0:
            logger.warning("[Flight Tracker] No map tiles could be fetched")
            return None
        
        # Log summary of failed tiles
        if failed_tiles:
            logger.warning(f"[Flight Tracker] Failed to fetch {len(failed_tiles)} tiles: {failed_tiles}")
            # If more than 50% of tiles failed, disable map background
            failure_rate = len(failed_tiles) / (tiles_x * tiles_y)
            if failure_rate > 0.5:
                logger.warning(f"[Flight Tracker] High tile failure rate ({failure_rate:.1%}), disabling map background")
                self.map_bg_enabled = False
                return None
        else:
            logger.info(f"[Flight Tracker] All tiles fetched successfully")
        
        # Calculate what geographic area the tiles natively show at this zoom level
        world_pixels_at_zoom = self.tile_size * (2 ** zoom)
        pixels_per_degree_lon_native = world_pixels_at_zoom / 360.0
        # Adjust for latitude (longitude degrees get smaller as you move away from equator)
        meters_per_degree_lat = 111000  # approximately 111km or 69 miles per degree
        miles_per_degree_lat = 69.0
        miles_per_degree_lon = miles_per_degree_lat * math.cos(math.radians(center_lat))
        
        pixels_per_mile_at_zoom = pixels_per_degree_lon_native / miles_per_degree_lon
        
        # Calculate what we WANT to show (effective_radius * 2 miles wide)
        desired_miles_wide = effective_radius * 2
        desired_pixels_per_mile = self.display_width / desired_miles_wide
        
        # Calculate how many pixels we need to crop from the composite to get the desired geographic area
        # maintaining the display aspect ratio to avoid stretching
        crop_width_needed = int(desired_miles_wide * pixels_per_mile_at_zoom)
        # Calculate height based on display aspect ratio to avoid stretching when we resize
        crop_height_needed = int(crop_width_needed * (self.display_height / self.display_width))
        
        # Find the center tile and position within it
        center_tile_x = center_x - start_x
        center_tile_y = center_y - start_y
        
        # Calculate position within the center tile
        center_lon_in_tile = (center_lon - self._tile_to_lon(start_x + center_tile_x, zoom)) / (self._tile_to_lon(start_x + center_tile_x + 1, zoom) - self._tile_to_lon(start_x + center_tile_x, zoom))
        center_lat_in_tile = (self._tile_to_lat(start_y + center_tile_y, zoom) - center_lat) / (self._tile_to_lat(start_y + center_tile_y, zoom) - self._tile_to_lat(start_y + center_tile_y + 1, zoom))
        
        # Calculate pixel position in composite
        center_pixel_x = int((center_tile_x + center_lon_in_tile) * self.tile_size)
        center_pixel_y = int((center_tile_y + center_lat_in_tile) * self.tile_size)
        
        # Calculate crop bounds centered on the center point, using the geographic-aware crop size
        crop_left = max(0, center_pixel_x - crop_width_needed // 2)
        crop_top = max(0, center_pixel_y - crop_height_needed // 2)
        crop_right = min(composite_width, crop_left + crop_width_needed)
        crop_bottom = min(composite_height, crop_top + crop_height_needed)
        
        # Adjust if we hit the edges
        if crop_right - crop_left < crop_width_needed:
            crop_width_needed = crop_right - crop_left
        if crop_bottom - crop_top < crop_height_needed:
            crop_height_needed = crop_bottom - crop_top
        
        # Crop to get the desired geographic area
        cropped = composite.crop((crop_left, crop_top, crop_right, crop_bottom))
        logger.debug(f"[Flight Tracker] Cropped size: {cropped.size} (wanted {crop_width_needed}x{crop_height_needed} pixels for {desired_miles_wide:.1f} miles)")
        
        # Now resize to display dimensions - this scales the geographic area to fit the display
        logger.debug(f"[Flight Tracker] Resizing from {cropped.size} to ({self.display_width}, {self.display_height})")
        cropped = cropped.resize((self.display_width, self.display_height), Image.Resampling.LANCZOS)
        
        # Apply fade effect
        if self.fade_intensity < 1.0:
            # Create a fade overlay
            fade_overlay = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            cropped = Image.blend(cropped, fade_overlay, 1.0 - self.fade_intensity)
        
        # Apply brightness adjustment
        if self.map_brightness != 1.0:
            enhancer = ImageEnhance.Brightness(cropped)
            cropped = enhancer.enhance(self.map_brightness)
            logger.debug(f"[Flight Tracker] Applied brightness: {self.map_brightness}")
        
        # Apply contrast adjustment
        if self.map_contrast != 1.0:
            enhancer = ImageEnhance.Contrast(cropped)
            cropped = enhancer.enhance(self.map_contrast)
            logger.debug(f"[Flight Tracker] Applied contrast: {self.map_contrast}")
        
        # Apply saturation adjustment
        if self.map_saturation != 1.0:
            enhancer = ImageEnhance.Color(cropped)
            cropped = enhancer.enhance(self.map_saturation)
            logger.debug(f"[Flight Tracker] Applied saturation: {self.map_saturation}")
        
        # Cache the result
        self.cached_map_bg = cropped
        self.last_map_center = current_center
        self.last_map_zoom = zoom
        
        # Calculate the geographic height coverage
        desired_miles_high = crop_height_needed / pixels_per_mile_at_zoom
        
        # Log the final map configuration
        logger.info(f"[Flight Tracker] Generated map background with {tiles_fetched} tiles at zoom {zoom}")
        logger.info(f"[Flight Tracker] Center: ({center_lat:.4f}, {center_lon:.4f}), Radius: {self.map_radius_miles}mi, Effective: {effective_radius:.2f}mi (zoom_factor: {self.zoom_factor})")
        logger.info(f"[Flight Tracker] Tile coverage: {tiles_x}x{tiles_y}, Crop: ({crop_left},{crop_top})-({crop_right},{crop_bottom})")
        logger.info(f"[Flight Tracker] Map displays {desired_miles_wide:.1f} miles wide x {desired_miles_high:.1f} miles high (no stretching)")
        logger.info(f"[Flight Tracker] Native tile scale: {pixels_per_mile_at_zoom:.3f} pixels/mile, cropped {crop_width_needed}x{crop_height_needed} pixels, scaled to {self.display_width}x{self.display_height}")
        
        # Debug: Save composite image to see what's happening
        try:
            debug_composite = Path("debug_composite.png")
            composite.save(debug_composite)
            logger.debug(f"[Flight Tracker] Saved composite to: {debug_composite}")
            
            debug_cropped = Path("debug_cropped.png")
            cropped.save(debug_cropped)
            logger.debug(f"[Flight Tracker] Saved cropped to: {debug_cropped}")
        except Exception as e:
            logger.debug(f"[Flight Tracker] Could not save debug images: {e}")
        
        return cropped
    
    def _tile_to_lat(self, y: int, zoom: int) -> float:
        """Convert tile Y coordinate to latitude."""
        n = 2.0 ** zoom
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        return math.degrees(lat_rad)
    
    def _tile_to_lon(self, x: int, zoom: int) -> float:
        """Convert tile X coordinate to longitude."""
        n = 2.0 ** zoom
        return x / n * 360.0 - 180.0
    
    def update(self) -> None:
        """Update aircraft data from the configured data source."""
        current_time = time.time()

        if current_time - self.last_fetch >= self.update_interval:
            self.last_fetch = current_time

            if self.data_source == 'flightradar24':
                logger.info("[Flight Tracker] Fetching aircraft data from FlightRadar24")
                self._update_from_fr24()
                logger.info(f"[Flight Tracker] Currently tracking {len(self.aircraft_data)} aircraft")
            else:
                logger.info(f"[Flight Tracker] Fetching aircraft data from {self.skyaware_url}")
                data = self._fetch_aircraft_data()
                if data:
                    logger.info("[Flight Tracker] Received data, processing aircraft...")
                    self._process_aircraft_data(data)
                    logger.info(f"[Flight Tracker] Currently tracking {len(self.aircraft_data)} aircraft")
                    # Queue interesting callsigns for background FlightAware fetching
                    self._queue_interesting_callsigns()
                else:
                    logger.warning("[Flight Tracker] No data received from SkyAware")

                # FR24 enrichment for SkyAware users
                if self.fr24_enrichment:
                    self._maybe_refresh_fr24_enrichment()

            self.last_update = current_time

        # Background FR24 detail fetches (airline name, timing, airport positions)
        if self.data_source == 'flightradar24' or self.fr24_enrichment:
            self._background_fetch_fr24_details()

        # Background service for FlightAware flight plan data (SkyAware mode, no FR24 enrichment)
        if (self.data_source == 'skyaware' and
                not self.fr24_enrichment and
                self.background_service_enabled and
                current_time - self.last_background_fetch >= self.background_fetch_interval):
            logger.info("[Flight Tracker] Running background service for flight plans")
            self._background_fetch_flight_plans()
            self.last_background_fetch = current_time

        # Update tracked flights (FR-02)
        if self.tracked_flights_cfg and current_time - self._last_tracked_update >= 60:
            self._update_tracked_flights()
            self._last_tracked_update = current_time
    
    def _update_tracked_flights(self) -> None:
        """Update tracked flight data from enrichment sources and live ADS-B."""
        from static_data import airports, cities

        for ident in self.tracked_flights_cfg[:3]:  # max 3 tracked flights
            ident_upper = ident.upper().strip()

            # Try to match against live ADS-B data first
            matched_ac = None
            for ac in self.aircraft_data.values():
                cs = (ac.get('callsign') or '').upper().strip()
                reg = (ac.get('registration') or '').upper().strip()
                if cs == ident_upper or reg == ident_upper:
                    matched_ac = ac
                    break

            # Get existing tracked flight or create new
            tf = self.tracked_flight_data.get(ident, TrackedFlight(identifier=ident))

            if matched_ac:
                tf.status = "AIRBORNE"
                tf.aircraft_state = matched_ac

                # Try to get route from the aircraft's enriched data
                if not tf.origin and matched_ac.get('origin'):
                    tf.origin = matched_ac['origin']
                if not tf.destination and matched_ac.get('destination'):
                    tf.destination = matched_ac['destination']

                # Compute progress from coordinates
                if tf.origin and tf.destination:
                    origin_coords = airports.coords(tf.origin)
                    dest_coords = airports.coords(tf.destination)
                    if origin_coords and dest_coords and matched_ac.get('lat') and matched_ac.get('lon'):
                        from utils import haversine_miles
                        total_dist = haversine_miles(origin_coords[0], origin_coords[1],
                                                     dest_coords[0], dest_coords[1])
                        remaining = haversine_miles(matched_ac['lat'], matched_ac['lon'],
                                                    dest_coords[0], dest_coords[1])
                        if total_dist > 0:
                            tf.progress_pct = max(0, min(100, (1 - remaining / total_dist) * 100))

                # City overfly
                if matched_ac.get('lat') and matched_ac.get('lon'):
                    city = cities.nearest_city(matched_ac['lat'], matched_ac['lon'])
                    if city:
                        tf.city_overfly = city

            elif tf.status != "LANDED":
                # Not found in live data — clear stale live fields
                tf.aircraft_state = None
                tf.progress_pct = None
                tf.city_overfly = ""
                if tf.status == "AIRBORNE":
                    tf.status = "UNKNOWN"
                # Try enrichment for route info
                try:
                    enriched = self._enrichment.lookup_tracked_flight(ident)
                    if enriched:
                        tf.status = enriched.status
                        if enriched.origin:
                            tf.origin = enriched.origin
                        if enriched.destination:
                            tf.destination = enriched.destination
                        if enriched.departure_time:
                            tf.departure_time = enriched.departure_time
                        if enriched.arrival_time:
                            tf.arrival_time = enriched.arrival_time
                except (requests.RequestException, KeyError, ValueError, TypeError) as e:
                    logger.warning(f"[Flight Tracker] Enrichment lookup failed for {ident}: {e}")

            tf.last_updated = time.time()
            self.tracked_flight_data[ident] = tf

    def _queue_interesting_callsigns(self):
        """Queue callsigns that are worth fetching flight plan data for, with priority."""
        # Sort aircraft by distance (closer = higher priority)
        sorted_aircraft = sorted(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
        
        for aircraft in sorted_aircraft:
            callsign = aircraft['callsign']
            if self._is_callsign_worth_fetching(callsign):
                # Check if we already have cached data
                cache_key = f"flight_plan_{callsign}"
                if not self.cache_manager.get(cache_key, max_age=self.cache_ttl_seconds):
                    # Add priority based on distance and aircraft type
                    priority = 1 if aircraft['distance_miles'] < 5 else 2  # Closer aircraft get priority
                    self.pending_flight_plans.add((priority, callsign))
    
    def _background_fetch_flight_plans(self):
        """Fetch flight plan data in background to avoid blocking display."""
        if not self.pending_flight_plans:
            return
        
        logger.info(f"[Flight Tracker] Background fetching {len(self.pending_flight_plans)} flight plans")
        
        # Sort by priority (lower number = higher priority)
        sorted_plans = sorted(self.pending_flight_plans, key=lambda x: x[0])
        
        # Process a limited number of callsigns per background run
        max_per_run = min(self.max_background_calls_per_run, len(sorted_plans))
        plans_to_process = sorted_plans[:max_per_run]
        
        for priority, callsign in plans_to_process:
            if self._check_rate_limit():
                # Fetch flight plan data
                flight_plan = self._get_flight_plan_data(callsign)
                if flight_plan and flight_plan.get('origin') != 'Unknown':
                    logger.info(f"[Flight Tracker] Background fetched (priority {priority}): {callsign} -> {flight_plan['origin']}-{flight_plan['destination']}")
                
                self.pending_flight_plans.remove((priority, callsign))
            else:
                logger.warning(f"[Flight Tracker] Rate limit reached, deferring {len(self.pending_flight_plans)} callsigns")
                break
    
    def get_closest_aircraft(self) -> Optional[Dict]:
        """Get the closest aircraft to the center point."""
        if not self.aircraft_data:
            return None
        
        closest = min(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
        return closest
    
    def get_vegas_content_type(self) -> str:
        """Return Vegas scroll content type based on effective display mode.

        Area, stats, and flight_tracking modes produce multiple cards.
        Map and overhead are single static blocks.
        """
        mode = self.display_mode
        if mode == 'auto':
            # Resolve auto to the effective mode
            has_airborne = any(tf.status == "AIRBORNE" for tf in self.tracked_flight_data.values())
            closest = self.get_closest_aircraft()
            if has_airborne:
                mode = 'flight_tracking'
            elif self.anchor_airport and self._get_anchor_aircraft():
                mode = 'area'
            elif self.aircraft_data:
                mode = 'map'
            else:
                mode = 'stats'
        if mode in ('area', 'stats', 'flight_tracking'):
            return 'multi'
        return 'static'

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """Return rendered frames for Vegas scroll mode.

        Map and overhead modes return a single image (static block).
        Area mode returns one full-screen card per aircraft for scrolling.
        Stats mode returns one image per stat card.
        Flight tracking returns one card per tracked flight.
        """
        try:
            w = self.display_width
            h = self.display_height

            mode = self.display_mode
            if mode == 'auto':
                has_airborne_tracked = any(
                    tf.status == "AIRBORNE" for tf in self.tracked_flight_data.values()
                )
                closest = self.get_closest_aircraft()
                if has_airborne_tracked:
                    mode = 'flight_tracking'
                elif self.proximity_enabled and closest and closest['distance_miles'] <= self.proximity_distance_miles:
                    mode = 'overhead'
                elif self.anchor_airport and self._get_anchor_aircraft():
                    mode = 'area'
                elif self.aircraft_data:
                    mode = 'map'
                else:
                    mode = 'stats'

            if mode == 'map':
                map_bg = self._get_map_background(self.center_lat, self.center_lon)
                img = map_bg.copy() if map_bg else Image.new('RGB', (w, h), (0, 0, 0))
                draw = ImageDraw.Draw(img)
                for aircraft in self.aircraft_data.values():
                    pixel = self._latlon_to_pixel(aircraft['lat'], aircraft['lon'])
                    if pixel:
                        color = tuple(min(255, int(c * 1.3)) for c in aircraft['color'])
                        draw.point(pixel, fill=color)
                return [img]

            if mode == 'overhead':
                self._display_overhead(force_clear=False)
                captured = self.display_manager.image
                if captured is not None:
                    return [captured.copy()]
                return None

            if mode == 'area':
                # One full-screen card per aircraft — scrolls individually in Vegas
                if self.anchor_airport:
                    anchor_list = self._get_anchor_aircraft()
                    other_list = [ac for ac in self._get_filtered_sorted_aircraft()
                                 if ac['icao'] not in {a['icao'] for a in anchor_list}]
                    aircraft_list = anchor_list + other_list
                else:
                    aircraft_list = self._get_filtered_sorted_aircraft()

                aircraft_list = aircraft_list[:self.max_aircraft]
                total = len(aircraft_list)
                images = []
                for i, ac in enumerate(aircraft_list):
                    img = self._renderer.render_area_card_image(ac, index=i, total_count=total)
                    images.append(img)
                return images if images else None

            if mode == 'flight_tracking':
                # One card per tracked flight
                images = []
                for tf in self.tracked_flight_data.values():
                    self._renderer.render_flight_tracking(tf)
                    captured = self.display_manager.image
                    if captured is not None:
                        images.append(captured.copy())
                return images if images else None

            # Stats mode — one card per stat slot
            images = []
            saved_stat = self.current_stat
            saved_time = self.last_stat_change
            num_stats = 3 + (2 if self.flight_records_enabled else 0)
            for slot in range(num_stats):
                self.current_stat = slot
                self.last_stat_change = time.time()
                try:
                    self._display_stats(force_clear=False)
                    captured = self.display_manager.image
                    if captured is not None:
                        images.append(captured.copy())
                except Exception as e:
                    logger.debug(f"[Flight Tracker] Failed to render stat slot {slot}: {e}", exc_info=True)
            self.current_stat = saved_stat
            self.last_stat_change = saved_time
            return images if images else None

        except Exception as e:
            logger.warning(f"[Flight Tracker] get_vegas_content() failed: {e}")
            return None

    def display(self, force_clear: bool = False, *, display_mode: Optional[str] = None) -> None:
        """Display flight tracker content based on display_mode configuration.

        Supports modes: map, overhead, stats, area, flight_tracking, auto.

        The ``display_mode`` parameter is passed by the LEDMatrix framework to
        indicate which manifest display mode is active.  It maps framework mode
        names (from manifest ``display_modes``) to our internal mode names.
        """
        aircraft_count = len(self.aircraft_data)
        closest = self.get_closest_aircraft()

        # The framework passes display_mode='flight_tracker' (the single
        # manifest mode name).  We always use our internal config setting
        # to decide which view to render (map, overhead, stats, area,
        # flight_tracking, or auto).
        mode = self.display_mode

        self.logger.debug(
            "[Flight Tracker] display() called: configured_mode=%s, framework_mode=%s, resolved=%s, aircraft=%s",
            self.display_mode, display_mode, mode, aircraft_count,
        )
        if mode == 'auto':
            # Auto mode priority:
            # 1. Tracked flight airborne → flight_tracking
            # 2. Proximity alert → overhead
            # 3. Anchor airport with matches → area
            # 4. Aircraft in range → map
            # 5. No aircraft → stats
            has_airborne_tracked = any(
                tf.status == "AIRBORNE" for tf in self.tracked_flight_data.values()
            )
            if has_airborne_tracked:
                mode = 'flight_tracking'
            elif self.proximity_enabled and closest and closest['distance_miles'] <= self.proximity_distance_miles:
                mode = 'overhead'
            elif self.anchor_airport and self._get_anchor_aircraft():
                mode = 'area'
            elif self.aircraft_data:
                mode = 'map'
            else:
                mode = 'stats'

            self.logger.debug(
                "[Flight Tracker] Auto mode selection: chosen_mode=%s (aircraft=%s)",
                mode, aircraft_count,
            )
        else:
            self.logger.debug("[Flight Tracker] Manual mode selection: chosen_mode=%s", mode)

        # Route to appropriate display method
        try:
            if mode == 'map':
                self._display_map(force_clear)
            elif mode == 'overhead':
                self._display_overhead(force_clear)
            elif mode == 'stats':
                self._display_stats(force_clear)
            elif mode == 'area':
                self._display_area(force_clear)
            elif mode == 'flight_tracking':
                self._display_flight_tracking(force_clear)
            else:
                self.logger.warning(f"Unknown display_mode: {mode!r}, using map")
                self._display_map(force_clear)
        except Exception:
            logger.exception("[Flight Tracker] display() error in mode %s", mode)
    
    # -------------------------------------------------------------------------
    # New display modes (delegated to renderer.py)
    # -------------------------------------------------------------------------

    def _get_filtered_sorted_aircraft(self) -> list:
        """Get aircraft list filtered by altitude/category and sorted by distance."""
        aircraft_list = list(self.aircraft_data.values())

        # Altitude filter
        if self.min_altitude_ft > 0 or self.max_altitude_ft > 0:
            def alt_in_range(ac):
                alt = ac.get('altitude', 0) or 0
                if self.min_altitude_ft > 0 and alt < self.min_altitude_ft:
                    return False
                if self.max_altitude_ft > 0 and alt > self.max_altitude_ft:
                    return False
                return True
            aircraft_list = [ac for ac in aircraft_list if alt_in_range(ac)]

        # Category filter
        if self.aircraft_categories:
            cats = set(c.upper() for c in self.aircraft_categories)
            aircraft_list = [ac for ac in aircraft_list if ac.get('category', '').upper() in cats]

        # Sort by distance (nearest first)
        aircraft_list.sort(key=lambda ac: ac.get('distance_miles', 999))

        return aircraft_list

    def _get_anchor_aircraft(self) -> list:
        """Get aircraft matching the anchor airport as origin or destination."""
        if not self.anchor_airport:
            return []
        anchor = self.anchor_airport.upper()
        matches = []
        for ac in self.aircraft_data.values():
            origin = (ac.get('origin') or '').upper()
            dest = (ac.get('destination') or '').upper()
            if anchor in (origin, dest):
                ac_copy = dict(ac)
                if dest == anchor:
                    ac_copy['_anchor_arrival'] = True
                elif origin == anchor:
                    ac_copy['_anchor_departure'] = True
                matches.append(ac_copy)
        return matches

    def _display_area(self, force_clear: bool = False) -> None:
        """Display area mode: one aircraft per full display, cycling through them."""
        if force_clear:
            self.display_manager.clear()

        # Get filtered + sorted aircraft
        if self.anchor_airport:
            anchor_list = self._get_anchor_aircraft()
            other_list = [ac for ac in self._get_filtered_sorted_aircraft()
                         if ac['icao'] not in {a['icao'] for a in anchor_list}]
            aircraft_list = anchor_list + other_list
        else:
            aircraft_list = self._get_filtered_sorted_aircraft()

        total_count = len(aircraft_list)
        if total_count == 0:
            self._renderer.render_error("No Aircraft")
            return

        # Limit to max_aircraft
        aircraft_list = aircraft_list[:self.max_aircraft]
        total_display = len(aircraft_list)

        # Cycle through one aircraft at a time every 5 seconds
        now = time.time()
        if now - self._area_last_page_change >= 5.0:
            self._area_page = (self._area_page + 1) % total_display
            self._area_last_page_change = now

        idx = self._area_page % total_display
        self._renderer.render_area_card(
            aircraft=aircraft_list[idx],
            index=idx,
            total_count=total_count,
        )

    def _display_flight_tracking(self, force_clear: bool = False) -> None:
        """Display flight tracking mode: detailed view of tracked flights."""
        if force_clear:
            self.display_manager.clear()

        if not self.tracked_flight_data:
            self._renderer.render_error("No Tracked Flights")
            return

        # Cycle through tracked flights every 10 seconds
        tracked_list = list(self.tracked_flight_data.values())
        now = time.time()
        if now - self._tracking_last_change >= 10.0:
            self._tracking_index = (self._tracking_index + 1) % len(tracked_list)
            self._tracking_last_change = now

        idx = self._tracking_index % len(tracked_list)
        self._renderer.render_flight_tracking(tracked_list[idx])

    # -------------------------------------------------------------------------
    # Original display modes (kept in manager.py for backward compatibility)
    # -------------------------------------------------------------------------

    def _display_map(self, force_clear: bool = False) -> None:
        """Display the flight map with aircraft and geographical background."""
        if force_clear:
            self.display_manager.clear()
        
        # Get map background if enabled
        map_bg = self._get_map_background(self.center_lat, self.center_lon)
        
        # Create image with background
        if map_bg:
            img = map_bg.copy()
        else:
            self.logger.debug("[Flight Tracker] Map background unavailable; using solid background")
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        
        draw = ImageDraw.Draw(img)
        
        # Draw center position marker (white dot at our lat/lon)
        center_pixel = self._latlon_to_pixel(self.center_lat, self.center_lon)
        if center_pixel:
            x, y = center_pixel
            # Draw white center dot
            draw.point((x, y), fill=(255, 255, 255))
        
        # Draw aircraft trails if enabled
        if self.show_trails:
            for icao, trail in self.aircraft_trails.items():
                if icao not in self.aircraft_data:
                    continue
                
                aircraft = self.aircraft_data[icao]
                trail_pixels = []
                
                for lat, lon, timestamp in trail:
                    pixel = self._latlon_to_pixel(lat, lon)
                    if pixel:
                        trail_pixels.append(pixel)
                
                # Draw trail with fading effect
                if len(trail_pixels) >= 2:
                    for i in range(len(trail_pixels) - 1):
                        # Fade from dim to bright
                        alpha = int(255 * (i + 1) / len(trail_pixels))
                        color = tuple(int(c * alpha / 255) for c in aircraft['color'])
                        draw.line([trail_pixels[i], trail_pixels[i + 1]], fill=color, width=1)
        
        # Draw aircraft
        for aircraft in self.aircraft_data.values():
            pixel = self._latlon_to_pixel(aircraft['lat'], aircraft['lon'])
            if not pixel:
                continue
            
            x, y = pixel
            # Brighten the plane colors by boosting RGB values
            base_color = aircraft['color']
            color = tuple(min(255, int(c * 1.3)) for c in base_color)
            
            # Draw single pixel for each aircraft
            draw.point((x, y), fill=color)
        
        # Draw info text with pixel-perfect rendering for better readability
        if len(self.aircraft_data) > 0:
            # Draw aircraft count
            info_text = f"{len(self.aircraft_data)}"
            self._draw_text_smart(draw, info_text, (2, 2), self.fonts['small'], 
                                fill=(200, 200, 200), use_outline=False)
            
            # Get text width to position the airplane icon
            bbox = draw.textbbox((0, 0), info_text, font=self.fonts['small'])
            text_width = bbox[2] - bbox[0]
            
            # Draw airplane icon after the count (with 2px spacing)
            self._draw_airplane_icon(draw, 2 + text_width + 2, 2, color=(200, 200, 200))
        
        # Display the image
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_overhead(self, force_clear: bool = False) -> None:
        """Display detailed overhead view of closest aircraft."""
        if force_clear:
            self.display_manager.clear()
        
        closest = self.get_closest_aircraft()
        if not closest:
            # No aircraft to display
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            self._draw_text_with_outline(draw, "No Aircraft", 
                                       (self.display_width // 2 - 30, self.display_height // 2 - 4), 
                                       self.fonts['medium'], fill=(200, 200, 200), outline_color=(0, 0, 0))
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            return
        
        # Create image
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Determine layout based on display size
        dsize = self._display_size()
        is_small_display = dsize in ('tiny', 'small')

        # Gather enriched fields for overhead display
        oh_origin = closest.get('origin') or ''
        oh_dest = closest.get('destination') or ''
        oh_airline = closest.get('airline_name') or ''
        oh_progress = self._compute_flight_progress(closest)
        oh_delay = self._format_delay(closest)

        if dsize == 'tiny':
            # Tiny display (≤64×32): callsign on top, altitude+distance on bottom
            self._draw_text_smart(draw, closest['callsign'], (1, 1),
                                self.fonts['data_small'], fill=(255, 255, 255), use_outline=False)
            line2 = f"{int(closest['altitude'])}ft {closest['distance_miles']:.1f}mi"
            y2 = self._calculate_line_spacing(self.fonts['data_small']) + 1
            if y2 < self.display_height:
                self._draw_text_smart(draw, line2, (1, y2),
                                    self.fonts['data_small'], fill=closest['color'], use_outline=False)
            # Route on third line if space
            if oh_origin and oh_dest:
                y3 = y2 + self._calculate_line_spacing(self.fonts['data_small'])
                if y3 < self.display_height:
                    self._draw_text_smart(draw, f"{oh_origin}-{oh_dest}", (1, y3),
                                        self.fonts['data_small'], fill=(150, 255, 150), use_outline=False)

        elif is_small_display:
            # Small display layout (128×32) with dynamic spacing
            y_offset = 2

            # Line 1: Callsign + optional airline ICAO
            callsign_text = closest['callsign']
            if closest.get('airline_icao') and self.display_width > 64:
                callsign_text = f"{closest['callsign']} {closest['airline_icao']}"
            self._draw_text_smart(draw, callsign_text, (2, y_offset),
                                self.fonts['data_medium'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Line 2: Altitude and Speed
            self._draw_text_smart(draw, f"ALT:{int(closest['altitude'])}ft", (2, y_offset),
                                self.fonts['data_small'], fill=closest['color'], use_outline=False)
            self._draw_text_smart(draw, f"SPD:{int(closest['speed'])}kt", (self.display_width // 2, y_offset),
                                self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_small'])

            # Line 3: Distance and Heading
            self._draw_text_smart(draw, f"DIST:{closest['distance_miles']:.2f}mi", (2, y_offset),
                                self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
            if closest['heading']:
                self._draw_text_smart(draw, f"HDG:{int(closest['heading'])}°", (self.display_width // 2, y_offset),
                                    self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_small'])

            # Line 4: Route or type (only if space)
            if y_offset + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                if oh_origin and oh_dest:
                    route_text = f"{oh_origin}->{oh_dest}"
                    if oh_progress is not None:
                        route_text += f" {int(oh_progress * 100)}%"
                    self._draw_text_smart(draw, route_text, (2, y_offset),
                                        self.fonts['data_small'], fill=(150, 255, 150), use_outline=False)
                else:
                    self._draw_text_smart(draw, f"TYPE:{closest['aircraft_type']}", (2, y_offset),
                                        self.fonts['data_small'], fill=(150, 150, 150), use_outline=False)
        else:
            # Large display layout (192x96 or bigger) with dynamic spacing
            y_offset = 4

            # Title
            self._draw_text_with_outline(draw, "OVERHEAD AIRCRAFT", (self.display_width // 2 - 40, y_offset),
                                       self.fonts['title_large'], fill=(255, 200, 0), outline_color=(0, 0, 0))
            y_offset += self._calculate_line_spacing(self.fonts['title_large']) + 4

            # Callsign + airline name (large displays only)
            callsign_line = f"Callsign: {closest['callsign']}"
            if oh_airline:
                callsign_line += f"  ({oh_airline})"
            self._draw_text_smart(draw, callsign_line, (4, y_offset),
                                self.fonts['data_large'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_large'])

            # Altitude
            self._draw_text_smart(draw, f"Altitude: {int(closest['altitude'])} ft", (4, y_offset),
                                self.fonts['data_medium'], fill=closest['color'], use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Speed
            self._draw_text_smart(draw, f"Speed: {int(closest['speed'])} knots", (4, y_offset),
                                self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Distance
            self._draw_text_smart(draw, f"Distance: {closest['distance_miles']:.2f} miles", (4, y_offset),
                                self.fonts['data_medium'], fill=(255, 150, 0), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Heading
            if closest['heading'] and y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Heading: {int(closest['heading'])}°", (4, y_offset),
                                    self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Route + progress
            if oh_origin and oh_dest and y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                route_text = f"Route: {oh_origin} -> {oh_dest}"
                if oh_progress is not None:
                    route_text += f"  ({int(oh_progress * 100)}%)"
                self._draw_text_smart(draw, route_text, (4, y_offset),
                                    self.fonts['data_medium'], fill=(150, 255, 150), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Delay status
            if oh_delay and y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                delay_color = self._delay_color(oh_delay)
                self._draw_text_smart(draw, f"Status: {oh_delay}", (4, y_offset),
                                    self.fonts['data_medium'], fill=delay_color, use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Aircraft type (only if there's space)
            if y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Type: {closest['aircraft_type']}", (4, y_offset),
                                    self.fonts['data_medium'], fill=(150, 150, 150), use_outline=False)
        
        # Display the image
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_stats(self, force_clear: bool = False) -> None:
        """Display flight statistics."""
        if force_clear:
            self.display_manager.clear()

        has_records = self.flight_records_enabled and (self._closest_record or self._farthest_record)

        if not self.aircraft_data and not has_records:
            # No aircraft and no records to display
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            self._draw_text_with_outline(draw, "No Aircraft",
                                       (self.display_width // 2 - 30, self.display_height // 2 - 4),
                                       self.fonts['medium'], fill=(200, 200, 200), outline_color=(0, 0, 0))
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            return

        # When no live aircraft but records exist, jump straight to a record slot
        if not self.aircraft_data and has_records:
            if self.current_stat < 3:
                self.current_stat = 3  # Jump to REC CLOSE
        
        # Rotate stats every 10 seconds
        # Slots: 0=Closest, 1=Fastest, 2=Highest, 3=Record Closest, 4=Record Farthest
        current_time = time.time()
        num_stats = 3 + (2 if self.flight_records_enabled else 0)
        if current_time - self.last_stat_change >= self.stat_duration:
            self.current_stat = (self.current_stat + 1) % num_stats
            self.last_stat_change = current_time

        # Create image
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Determine layout based on display size
        dsize = self._display_size()
        is_small_display = dsize in ('tiny', 'small')

        # Get statistics
        record_data = None

        if self.current_stat == 0:
            aircraft = min(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
            title = "CLOSEST"
            title_color = (255, 100, 0)
        elif self.current_stat == 1:
            aircraft = max(self.aircraft_data.values(), key=lambda a: a['speed'])
            title = "FASTEST"
            title_color = (0, 255, 100)
        elif self.current_stat == 2:
            aircraft = max(self.aircraft_data.values(), key=lambda a: a['altitude'])
            title = "HIGHEST"
            title_color = (100, 150, 255)
        elif self.current_stat == 3:
            # Record: all-time closest
            if self._closest_record:
                record_data = self._closest_record
                aircraft = None
                title = "REC CLOSE"
                title_color = (255, 80, 0)
            else:
                # No record yet — fall back to closest live
                aircraft = min(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
                title = "CLOSEST"
                title_color = (255, 100, 0)
        else:
            # Record: all-time farthest
            if self._farthest_record:
                record_data = self._farthest_record
                aircraft = None
                title = "REC FAR"
                title_color = (80, 150, 255)
            else:
                aircraft = max(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
                title = "FARTHEST"
                title_color = (80, 150, 255)
        
        # If showing a record snapshot, extract data directly from it
        if record_data:
            callsign_disp = record_data.get('callsign', '?')
            origin = record_data.get('origin') or 'Unknown'
            destination = record_data.get('destination') or 'Unknown'
            aircraft_type = record_data.get('aircraft_type') or 'Unknown'
            airline_name = record_data.get('airline_name') or ''
            dist_disp = f"{record_data['distance_miles']:.2f}mi"
            alt_disp = f"{int(record_data.get('altitude', 0))}ft"
            spd_disp = f"{int(record_data.get('speed', 0))}kt"
            rec_ts = record_data.get('timestamp', '')
            if rec_ts:
                try:
                    rec_ts = datetime.fromisoformat(rec_ts).strftime('%m/%d %H:%M')
                except ValueError:
                    pass
            manufacturer = 'Unknown'
            model = 'Unknown'
            if aircraft_type and aircraft_type != 'Unknown':
                parts = aircraft_type.split(' ', 1)
                manufacturer, model = (parts[0], parts[1]) if len(parts) == 2 else ('', aircraft_type)
            show_route = origin != 'Unknown' and destination != 'Unknown'
            operator = airline_name or 'Unknown'
            # Render record display and return early
            if is_small_display:
                y_offset = 1
                self._draw_text_with_outline(draw, title, (2, y_offset),
                                            self.fonts['title_medium'], fill=title_color, outline_color=(0, 0, 0))
                y_offset += self._calculate_line_spacing(self.fonts['title_medium'])
                self._draw_text_smart(draw, callsign_disp, (2, y_offset),
                                    self.fonts['data_small'], fill=(255, 255, 255), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_small'])
                self._draw_text_smart(draw, dist_disp, (2, y_offset),
                                    self.fonts['data_medium'], fill=title_color, use_outline=False)
                if show_route and y_offset + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                    right_x = self.display_width - 60
                    self._draw_text_smart(draw, f"FROM:{origin}", (right_x, 1),
                                        self.fonts['data_small'], fill=(150, 255, 150), use_outline=False)
                    self._draw_text_smart(draw, f"TO:{destination}", (right_x, 1 + self._calculate_line_spacing(self.fonts['data_small'])),
                                        self.fonts['data_small'], fill=(150, 255, 150), use_outline=False)
                if rec_ts:
                    self._draw_text_smart(draw, rec_ts, (2, self.display_height - 8),
                                        self.fonts['data_small'], fill=(120, 120, 120), use_outline=False)
            else:
                y_offset = 4
                self._draw_text_with_outline(draw, title, (self.display_width // 2 - 30, y_offset),
                                            self.fonts['title_large'], fill=title_color, outline_color=(0, 0, 0))
                y_offset += self._calculate_line_spacing(self.fonts['title_large']) + 4
                self._draw_text_smart(draw, f"Callsign: {callsign_disp}", (4, y_offset),
                                    self.fonts['data_large'], fill=(255, 255, 255), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_large'])
                self._draw_text_smart(draw, f"Distance: {dist_disp}", (4, y_offset),
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_large']) + 2
                if y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                    self._draw_text_smart(draw, f"Aircraft: {aircraft_type}", (4, y_offset),
                                        self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                    y_offset += self._calculate_line_spacing(self.fonts['data_medium'])
                if y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                    self._draw_text_smart(draw, f"{alt_disp}  {spd_disp}", (4, y_offset),
                                        self.fonts['data_medium'], fill=(180, 180, 255), use_outline=False)
                    y_offset += self._calculate_line_spacing(self.fonts['data_medium'])
                if show_route:
                    right_x = self.display_width - 80
                    right_y = 4
                    if right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                        self._draw_text_smart(draw, f"From: {origin}", (right_x, right_y),
                                            self.fonts['data_medium'], fill=(150, 255, 150), use_outline=False)
                        right_y += self._calculate_line_spacing(self.fonts['data_medium'])
                    if right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                        self._draw_text_smart(draw, f"To: {destination}", (right_x, right_y),
                                            self.fonts['data_medium'], fill=(150, 255, 150), use_outline=False)
                if rec_ts:
                    self._draw_text_smart(draw, rec_ts, (4, self.display_height - 10),
                                        self.fonts['data_small'], fill=(120, 120, 120), use_outline=False)
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            return

        # Get flight plan data once and cache it for this display cycle
        # Pass ICAO24 for offline database / FR24 enrichment lookup
        flight_plan = self._get_flight_plan_data(aircraft['callsign'], aircraft.get('icao'))
        origin = flight_plan.get('origin', 'Unknown')
        destination = flight_plan.get('destination', 'Unknown')
        aircraft_type = flight_plan.get('aircraft_type', 'Unknown')
        airline_name = flight_plan.get('airline_name') or aircraft.get('airline_name') or ''

        # Parse manufacturer and model from aircraft_type
        manufacturer = 'Unknown'
        model = 'Unknown'

        if aircraft_type and aircraft_type != 'Unknown':
            # Try to split manufacturer and model (e.g., "Boeing 737-800")
            parts = aircraft_type.split(' ', 1)
            if len(parts) == 2:
                manufacturer = parts[0]
                model = parts[1]
            else:
                # If we can't split, use aircraft_type as model
                model = aircraft_type

        # Get operator/owner from flight plan data or airline name
        operator = airline_name or flight_plan.get('operator', 'Unknown')
        if operator == 'Unknown':
            operator = flight_plan.get('owner_name', 'Unknown')

        # Log if we used offline database
        if flight_plan.get('source') == 'offline_db':
            logger.debug(f"[Flight Tracker] Using offline database for {aircraft['callsign']}: {manufacturer} {model}")

        # Improve aircraft type display with better categorization if still unknown
        if model == 'Unknown':
            categorized = self._categorize_aircraft(aircraft['callsign'])
            if categorized != 'Unknown':
                model = categorized
            # Log uncategorized aircraft for debugging
            if model == 'Unknown':
                logger.debug(f"[Flight Tracker] Unclassified aircraft: {aircraft['callsign']}")

        # Determine if we should show origin/destination
        # Show route if we have it from any source (FR24, FlightAware, or offline DB)
        show_route = (origin != 'Unknown' and destination != 'Unknown')

        # Flight progress
        progress = self._compute_flight_progress(aircraft)
        delay_str = self._format_delay(aircraft)
        
        if dsize == 'tiny':
            # Tiny display: title abbreviation + callsign + key stat only
            title_abbr = title[:4]  # e.g. "CLOS", "FAST", "HIGH"
            self._draw_text_smart(draw, f"{title_abbr}:{aircraft['callsign']}", (1, 1),
                                self.fonts['data_small'], fill=title_color, use_outline=False)
            if self.current_stat == 0:
                stat_text = f"{aircraft['distance_miles']:.1f}mi"
            elif self.current_stat == 1:
                stat_text = f"{int(aircraft['speed'])}kt"
            else:
                stat_text = f"{int(aircraft['altitude'])}ft"
            y2 = self._calculate_line_spacing(self.fonts['data_small']) + 1
            if y2 < self.display_height:
                self._draw_text_smart(draw, stat_text, (1, y2),
                                    self.fonts['data_small'], fill=aircraft['color'], use_outline=False)
            if show_route:
                y3 = y2 + self._calculate_line_spacing(self.fonts['data_small'])
                if y3 < self.display_height:
                    self._draw_text_smart(draw, f"{origin}-{destination}", (1, y3),
                                        self.fonts['data_small'], fill=(150, 255, 150), use_outline=False)

        elif is_small_display:
            # Small display layout with dynamic spacing
            y_offset = 1

            # Title
            self._draw_text_with_outline(draw, title, (2, y_offset),
                                       self.fonts['title_medium'], fill=title_color, outline_color=(0, 0, 0))
            y_offset += self._calculate_line_spacing(self.fonts['title_medium'])

            # Callsign
            self._draw_text_smart(draw, aircraft['callsign'], (2, y_offset),
                                self.fonts['data_small'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_small'])

            # Key stat
            if self.current_stat == 0:
                stat_text = f"{aircraft['distance_miles']:.2f}mi"
            elif self.current_stat == 1:
                stat_text = f"{int(aircraft['speed'])}kt"
            else:
                stat_text = f"{int(aircraft['altitude'])}ft"

            self._draw_text_smart(draw, stat_text, (2, y_offset),
                                self.fonts['data_medium'], fill=aircraft['color'], use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium']) + 1

            # Additional info only if space
            if y_offset + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                self._draw_text_smart(draw, f"ALT:{int(aircraft['altitude'])} SPD:{int(aircraft['speed'])}", (2, y_offset),
                                    self.fonts['data_small'], fill=(150, 150, 150), use_outline=False)

            # Right side info
            right_x = self.display_width - 60
            right_y = 1

            # Operator/airline
            if operator and operator != 'Unknown' and right_y + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                op_disp = operator[:12] if len(operator) > 12 else operator
                self._draw_text_smart(draw, f"OPR:{op_disp}", (right_x, right_y),
                                    self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_small'])

            # Model
            if model and model != 'Unknown' and right_y + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                self._draw_text_smart(draw, f"MDL:{model[:10]}", (right_x, right_y),
                                    self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_small'])

            # Route
            if show_route and right_y + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                route_disp = f"{origin}->{destination}"
                if progress is not None:
                    route_disp += f" {int(progress * 100)}%"
                self._draw_text_smart(draw, route_disp, (right_x, right_y),
                                    self.fonts['data_small'], fill=(150, 255, 150), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_small'])

            # Delay
            if delay_str and right_y + self._calculate_line_spacing(self.fonts['data_small']) <= self.display_height:
                self._draw_text_smart(draw, delay_str, (right_x, right_y),
                                    self.fonts['data_small'], fill=self._delay_color(delay_str), use_outline=False)
        else:
            # Large display layout with dynamic spacing
            y_offset = 4

            # Title
            self._draw_text_with_outline(draw, title, (self.display_width // 2 - 30, y_offset),
                                       self.fonts['title_large'], fill=title_color, outline_color=(0, 0, 0))
            y_offset += self._calculate_line_spacing(self.fonts['title_large']) + 4

            # Callsign + optional airline
            callsign_line = f"Callsign: {aircraft['callsign']}"
            if airline_name:
                callsign_line += f"  ({airline_name[:16]})"
            self._draw_text_smart(draw, callsign_line, (4, y_offset),
                                self.fonts['data_large'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_large'])

            # Key statistic
            if self.current_stat == 0:
                self._draw_text_smart(draw, f"Distance: {aircraft['distance_miles']:.2f} miles", (4, y_offset),
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
            elif self.current_stat == 1:
                self._draw_text_smart(draw, f"Speed: {int(aircraft['speed'])} knots", (4, y_offset),
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
            else:
                self._draw_text_smart(draw, f"Altitude: {int(aircraft['altitude'])} ft", (4, y_offset),
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_large']) + 2

            if y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Altitude: {int(aircraft['altitude'])} ft", (4, y_offset),
                                    self.fonts['data_medium'], fill=aircraft['color'], use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            if y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Speed: {int(aircraft['speed'])} knots", (4, y_offset),
                                    self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            if y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Distance: {aircraft['distance_miles']:.2f} miles", (4, y_offset),
                                    self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            if aircraft['heading'] and y_offset + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Heading: {int(aircraft['heading'])}°", (4, y_offset),
                                    self.fonts['data_medium'], fill=(150, 150, 150), use_outline=False)
                y_offset += self._calculate_line_spacing(self.fonts['data_medium'])

            # Right side info
            right_x = self.display_width - 80
            right_y = 4

            if manufacturer and manufacturer != 'Unknown' and right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Manufacturer: {manufacturer}", (right_x, right_y),
                                    self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_medium'])

            if model and model != 'Unknown' and right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Model: {model}", (right_x, right_y),
                                    self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_medium'])

            if operator and operator != 'Unknown' and right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                op_disp = operator[:20] if len(operator) > 20 else operator
                self._draw_text_smart(draw, f"Operator: {op_disp}", (right_x, right_y),
                                    self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_medium'])

            if show_route and right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                route_disp = f"From: {origin}  To: {destination}"
                if progress is not None:
                    route_disp += f"  ({int(progress * 100)}%)"
                self._draw_text_smart(draw, route_disp, (right_x, right_y),
                                    self.fonts['data_medium'], fill=(150, 255, 150), use_outline=False)
                right_y += self._calculate_line_spacing(self.fonts['data_medium'])

            if delay_str and right_y + self._calculate_line_spacing(self.fonts['data_medium']) <= self.display_height:
                self._draw_text_smart(draw, f"Status: {delay_str}", (right_x, right_y),
                                    self.fonts['data_medium'], fill=self._delay_color(delay_str), use_outline=False)
        
        # Display the image
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def has_live_content(self) -> bool:
        """Check if plugin has live/urgent content (proximity alerts)."""
        if not self.proximity_enabled:
            return False
        
        closest = self.get_closest_aircraft()
        if not closest:
            return False
        
        return closest['distance_miles'] <= self.proximity_distance_miles
    
    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False
        
        # Validate required configuration
        data_source = self.config.get('data_source', 'skyaware')
        if data_source == 'skyaware' and not self.config.get('skyaware_url'):
            self.logger.error("Missing required configuration: skyaware_url (required when data_source is 'skyaware')")
            return False
        
        # Validate location configuration
        center_lat = self.config.get('center_latitude')
        center_lon = self.config.get('center_longitude')
        if center_lat is None or center_lon is None:
            self.logger.error("Missing required configuration: center_latitude and center_longitude")
            return False
        
        if not (-90 <= center_lat <= 90):
            self.logger.error(f"Invalid center_latitude: {center_lat} (must be between -90 and 90)")
            return False
        
        if not (-180 <= center_lon <= 180):
            self.logger.error(f"Invalid center_longitude: {center_lon} (must be between -180 and 180)")
            return False
        
        # Validate map_radius_miles
        radius = self.config.get('map_radius_miles', 10)
        if not (1 <= radius <= 100):
            self.logger.error(f"Invalid map_radius_miles: {radius} (must be between 1 and 100)")
            return False
        
        # Validate update_interval
        interval = self.config.get('update_interval', 5)
        if not (1 <= interval <= 300):
            self.logger.error(f"Invalid update_interval: {interval} (must be between 1 and 300)")
            return False
        
        # Validate FlightAware API key if flight plans are enabled
        flight_plan_enabled = self.config.get('flight_plan_enabled', False)
        api_key = self.config.get('flightaware_api_key', '')
        if flight_plan_enabled and not api_key:
            self.logger.warning(
                "Flight plans are enabled but no FlightAware API key is configured. "
                "Flight plan features will not work. "
                "Get a free API key at https://flightaware.com/aeroapi/ and add it to config_secrets.json"
            )
            # Don't fail validation - just warn, as the plugin can work without flight plans
        
        return True




