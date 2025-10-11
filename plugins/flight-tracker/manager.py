"""
Flight Tracker Plugin for LEDMatrix

Advanced flight tracking with live ADS-B data, map visualization, and aircraft details.
Displays real-time aircraft positions with altitude-coded colors, flight statistics,
and detailed overhead aircraft information with optional map backgrounds.

Features:
- Live aircraft tracking from SkyAware/dump1090
- Map view with OpenStreetMap backgrounds
- Overhead view for closest aircraft
- Flight statistics (closest, fastest, highest)
- Optional flight plan data from FlightAware API
- Offline aircraft database for type lookups
- Cost-controlled API usage
- Proximity alerts for nearby aircraft

API Version: 1.0.0
"""

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

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class FlightTrackerPlugin(BasePlugin):
    """
    Flight Tracker plugin that displays live aircraft data from SkyAware.

    Supports three display modes:
    - flight-tracker-map: Map view with all aircraft
    - flight-tracker-overhead: Detailed view of closest aircraft
    - flight-tracker-stats: Rotating statistics (closest, fastest, highest)

    Configuration options:
        skyaware_url (str): URL to SkyAware aircraft.json endpoint
        center_latitude (float): Center latitude for display
        center_longitude (float): Center longitude for display
        map_radius_miles (float): Radius in miles to display
        zoom_factor (float): Zoom factor for map display
        show_trails (bool): Show aircraft position trails
        trail_length (int): Number of positions in trail
        map_background (dict): Map background configuration
        flight_plan_enabled (bool): Enable flight plan data fetching
        flightaware_api_key (str): FlightAware API key
        proximity_alert (dict): Proximity alert configuration
        use_offline_database (bool): Use offline aircraft database
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the flight tracker plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Flight tracker configuration
        self.update_interval = config.get('update_interval', 5)
        self.skyaware_url = config.get('skyaware_url', 'http://192.168.86.30/skyaware/data/aircraft.json')
        
        # Location configuration
        self.center_lat = config.get('center_latitude', 27.9506)
        self.center_lon = config.get('center_longitude', -82.4572)
        self.map_radius_miles = config.get('map_radius_miles', 10)
        self.zoom_factor = config.get('zoom_factor', 1.0)
        
        # Display configuration
        self.display_width = display_manager.matrix.width
        self.display_height = display_manager.matrix.height
        self.show_trails = config.get('show_trails', False)
        self.trail_length = config.get('trail_length', 10)
        
        # Map background configuration
        self.map_bg_config = config.get('map_background', {})
        self.map_bg_enabled = self.map_bg_config.get('enabled', True)
        self.tile_provider = self.map_bg_config.get('tile_provider', 'osm')
        self.tile_size = self.map_bg_config.get('tile_size', 256)
        self.cache_ttl_hours = self.map_bg_config.get('cache_ttl_hours', 8760)
        self.fade_intensity = self.map_bg_config.get('fade_intensity', 0.3)
        self.map_brightness = self.map_bg_config.get('brightness', 1.0)
        self.map_contrast = self.map_bg_config.get('contrast', 1.0)
        self.map_saturation = self.map_bg_config.get('saturation', 1.0)
        self.custom_tile_server = self.map_bg_config.get('custom_tile_server', None)
        self.disable_on_cache_error = self.map_bg_config.get('disable_on_cache_error', False)
        
        # Flight plan data configuration
        self.flight_plan_enabled = config.get('flight_plan_enabled', False)
        self.flightaware_api_key = config.get('flightaware_api_key', '')
        self.max_api_calls_per_hour = config.get('max_api_calls_per_hour', 20)
        self.cache_ttl_seconds = config.get('flight_plan_cache_ttl_hours', 12) * 3600
        self.min_callsign_length = config.get('min_callsign_length', 4)
        self.daily_api_budget = config.get('daily_api_budget', 60)
        self.airline_callsign_prefixes = config.get('airline_callsign_prefixes', [
            'AAL', 'UAL', 'DAL', 'SWA', 'JBU', 'ASQ', 'ENY', 'FFT', 'NKS', 'F9', 'G4', 'B6', 'WN', 'AA', 'UA', 'DL'
        ])
        
        # Proximity alert configuration
        self.proximity_config = config.get('proximity_alert', {})
        self.proximity_enabled = self.proximity_config.get('enabled', True)
        self.proximity_distance_miles = self.proximity_config.get('distance_miles', 0.1)
        self.proximity_duration = self.proximity_config.get('duration_seconds', 30)
        
        # Background service configuration
        self.background_service_enabled = config.get('background_service', {}).get('enabled', True)
        self.background_fetch_interval = config.get('background_service', {}).get('fetch_interval_hours', 4) * 3600
        self.max_background_calls_per_run = config.get('background_service', {}).get('max_calls_per_run', 10)
        
        # Offline aircraft database
        self.use_offline_db = config.get('use_offline_database', True)
        self.aircraft_db = None
        
        # Rate limiting and cost control
        self.api_call_timestamps = []
        self.api_calls_today = 0
        self.last_reset_date = None
        self.monthly_api_calls = 0
        self.cost_per_call = 0.005
        self.monthly_budget = 10.0
        self.budget_warning_threshold = 0.8
        
        # Runtime data
        self.aircraft_data = {}  # ICAO -> aircraft dict
        self.aircraft_trails = {}  # ICAO -> list of (lat, lon, timestamp) tuples
        self.last_update = 0
        self.last_fetch = 0
        self.last_background_fetch = 0
        self.pending_flight_plans = set()
        
        # Map tile cache
        cache_dir = cache_manager.cache_dir if hasattr(cache_manager, 'cache_dir') else None
        if cache_dir:
            self.tile_cache_dir = Path(cache_dir) / 'map_tiles'
        else:
            import tempfile
            self.tile_cache_dir = Path(tempfile.gettempdir()) / 'ledmatrix_map_tiles'
        
        try:
            self.tile_cache_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.tile_cache_dir / '.writetest'
            test_file.write_text('test')
            test_file.unlink()
            self.logger.info(f"Using map tile cache directory: {self.tile_cache_dir}")
        except (PermissionError, OSError) as e:
            self.logger.warning(f"Could not use map tile cache directory: {e}")
            import tempfile
            self.tile_cache_dir = Path(tempfile.gettempdir()) / 'ledmatrix_map_tiles'
            self.tile_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Cached map background
        self.cached_map_bg = None
        self.last_map_center = None
        self.last_map_zoom = None
        self.cached_pixels_per_mile = None
        
        # Cache error tracking
        self.cache_error_count = 0
        self.max_cache_errors = 5
        self.bounds_warning_cache = {}
        self.bounds_warning_interval = 30
        
        # Altitude color scale (standard aviation colors)
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
        
        # Current display mode
        self.current_mode = 'map'  # map, overhead, stats
        self.current_stat = 0  # For stats rotation
        self.last_stat_change = 0
        self.stat_duration = 10
        self.proximity_triggered_time = None
        
        # Fonts
        self.fonts = self._load_fonts()
        
        # Initialize offline database if enabled
        if self.use_offline_db:
            self._init_aircraft_database()
        
        self.logger.info(f"Flight Tracker initialized - Center: ({self.center_lat}, {self.center_lon}), Radius: {self.map_radius_miles}mi")
        self.logger.info(f"Display: {self.display_width}x{self.display_height}, SkyAware: {self.skyaware_url}")

    def _init_aircraft_database(self):
        """Initialize the offline aircraft database."""
        try:
            # Try to import the aircraft database module
            from src.aircraft_database import AircraftDatabase
            cache_dir = self.cache_manager.cache_dir if hasattr(self.cache_manager, 'cache_dir') else Path.home() / '.cache' / 'ledmatrix'
            self.aircraft_db = AircraftDatabase(cache_dir)
            stats = self.aircraft_db.get_stats()
            self.logger.info(f"Offline aircraft database loaded: {stats['total_aircraft']} aircraft, {stats['database_size_mb']:.1f}MB")
            if stats['last_update']:
                self.logger.info(f"Database last updated: {stats['last_update']}")
        except ImportError:
            self.logger.warning("Aircraft database module not available, skipping offline database")
            self.aircraft_db = None
        except Exception as e:
            self.logger.warning(f"Failed to load offline aircraft database: {e}")
            self.aircraft_db = None

    def _load_fonts(self) -> Dict[str, Any]:
        """Load fonts for text rendering."""
        fonts = {}
        try:
            # Load PressStart2P for titles
            if self.display_height >= 64:
                fonts['title_small'] = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 8)
                fonts['title_medium'] = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 10)
                fonts['title_large'] = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 12)
            else:
                fonts['title_small'] = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 6)
                fonts['title_medium'] = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 8)
                fonts['title_large'] = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 10)
            
            # Load 4x6 for data
            if self.display_height >= 64:
                fonts['data_small'] = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
                fonts['data_medium'] = ImageFont.truetype('assets/fonts/4x6-font.ttf', 10)
                fonts['data_large'] = ImageFont.truetype('assets/fonts/4x6-font.ttf', 12)
            else:
                fonts['data_small'] = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
                fonts['data_medium'] = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
                fonts['data_large'] = ImageFont.truetype('assets/fonts/4x6-font.ttf', 10)
            
            # Legacy aliases
            fonts['small'] = fonts['data_small']
            fonts['medium'] = fonts['data_medium']
            fonts['large'] = fonts['data_large']
            
            self.logger.info("Successfully loaded fonts: PressStart2P for titles, 4x6 for data")
        except Exception as e:
            self.logger.warning(f"Failed to load fonts: {e}, using defaults")
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

    def display(self, display_mode: str = None) -> None:
        """Display flight tracker data in the specified mode."""
        # Update aircraft data if needed
        self._update_aircraft_data()
        
        # Determine display mode
        if display_mode:
            if display_mode == 'flight-tracker-map':
                self.current_mode = 'map'
            elif display_mode == 'flight-tracker-overhead':
                self.current_mode = 'overhead'
            elif display_mode == 'flight-tracker-stats':
                self.current_mode = 'stats'
        
        # Check for proximity alert
        if self.proximity_enabled and self.current_mode == 'map':
            closest = self._get_closest_aircraft()
            if closest and closest['distance_miles'] <= self.proximity_distance_miles:
                if self.proximity_triggered_time is None:
                    self.proximity_triggered_time = time.time()
                    self.logger.info(f"Proximity alert triggered: {closest['callsign']} at {closest['distance_miles']:.2f}mi")
                
                # Show overhead view during proximity alert
                if time.time() - self.proximity_triggered_time < self.proximity_duration:
                    self.current_mode = 'overhead'
                else:
                    self.proximity_triggered_time = None
        
        # Display based on current mode
        if self.current_mode == 'map':
            self._display_map()
        elif self.current_mode == 'overhead':
            self._display_overhead()
        elif self.current_mode == 'stats':
            self._display_stats()

    def _update_aircraft_data(self) -> None:
        """Update aircraft data from SkyAware."""
        current_time = time.time()
        
        # Check if it's time to fetch new data
        if current_time - self.last_fetch >= self.update_interval:
            self.last_fetch = current_time
            self.logger.debug(f"Fetching aircraft data from {self.skyaware_url}")
            
            data = self._fetch_aircraft_data()
            if data:
                self._process_aircraft_data(data)
                self.logger.debug(f"Currently tracking {len(self.aircraft_data)} aircraft")
                self._queue_interesting_callsigns()
            
            self.last_update = current_time
        
        # Background service for flight plan data
        if self.background_service_enabled and current_time - self.last_background_fetch >= self.background_fetch_interval:
            self.logger.info("Running background service for flight plans")
            self._background_fetch_flight_plans()
            self.last_background_fetch = current_time

    def _fetch_aircraft_data(self) -> Optional[Dict]:
        """Fetch aircraft data from SkyAware API."""
        try:
            response = requests.get(self.skyaware_url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            # Cache the data
            self.cache_manager.set('flight_tracker_data', data)
            
            return data
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch aircraft data: {e}")
            
            # Try to use cached data
            cached_data = self.cache_manager.get('flight_tracker_data')
            if cached_data:
                self.logger.info("Using cached aircraft data")
                return cached_data
            
            return None

    def _process_aircraft_data(self, data: Dict) -> None:
        """Process and update aircraft data."""
        if not data or 'aircraft' not in data:
            self.logger.warning("No aircraft data in response")
            return
        
        current_time = time.time()
        active_icao = set()
        
        for aircraft in data['aircraft']:
            icao = aircraft.get('hex', '').upper()
            if not icao:
                continue
            
            lat = aircraft.get('lat')
            lon = aircraft.get('lon')
            if lat is None or lon is None:
                continue
            
            distance_miles = self._calculate_distance(lat, lon, self.center_lat, self.center_lon)
            
            if distance_miles > self.map_radius_miles:
                continue
            
            active_icao.add(icao)
            
            altitude = aircraft.get('alt_baro', aircraft.get('alt_geom', 0))
            if altitude == 'ground':
                altitude = 0
            
            callsign = aircraft.get('flight', '').strip() or icao
            speed = aircraft.get('gs', 0)
            heading = aircraft.get('track', aircraft.get('heading', 0))
            registration = aircraft.get('r', '')
            aircraft_type = aircraft.get('t', 'Unknown')
            
            color = self._altitude_to_color(altitude)
            
            aircraft_info = {
                'icao': icao,
                'callsign': callsign,
                'registration': registration,
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'speed': speed,
                'heading': heading,
                'aircraft_type': aircraft_type,
                'distance_miles': distance_miles,
                'color': color,
                'last_seen': current_time
            }
            
            self.aircraft_data[icao] = aircraft_info
            
            if self.show_trails:
                if icao not in self.aircraft_trails:
                    self.aircraft_trails[icao] = []
                
                self.aircraft_trails[icao].append((lat, lon, current_time))
                
                if len(self.aircraft_trails[icao]) > self.trail_length:
                    self.aircraft_trails[icao] = self.aircraft_trails[icao][-self.trail_length:]
        
        # Clean up old aircraft
        stale_icao = [icao for icao, info in self.aircraft_data.items() 
                      if current_time - info['last_seen'] > 60]
        for icao in stale_icao:
            del self.aircraft_data[icao]
            if icao in self.aircraft_trails:
                del self.aircraft_trails[icao]

    def _altitude_to_color(self, altitude: float) -> Tuple[int, int, int]:
        """Convert altitude to color using gradient interpolation."""
        breakpoints = sorted([(int(k), v) for k, v in self.altitude_colors.items()])
        
        if altitude <= breakpoints[0][0]:
            return tuple(breakpoints[0][1])
        if altitude >= breakpoints[-1][0]:
            return tuple(breakpoints[-1][1])
        
        for i in range(len(breakpoints) - 1):
            alt1, color1 = breakpoints[i]
            alt2, color2 = breakpoints[i + 1]
            
            if alt1 <= altitude <= alt2:
                ratio = (altitude - alt1) / (alt2 - alt1)
                
                r = int(color1[0] + (color2[0] - color1[0]) * ratio)
                g = int(color1[1] + (color2[1] - color1[1]) * ratio)
                b = int(color1[2] + (color2[2] - color1[2]) * ratio)
                
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                
                return (r, g, b)
        
        return (255, 255, 255)

    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in miles using Haversine formula."""
        R = 3959  # Earth's radius in miles
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c

    def _latlon_to_pixel(self, lat: float, lon: float) -> Optional[Tuple[int, int]]:
        """Convert lat/lon to pixel coordinates on the display."""
        effective_radius = self.map_radius_miles / self.zoom_factor
        pixels_per_mile = self.display_width / (effective_radius * 2)
        
        distance_miles = self._calculate_distance(self.center_lat, self.center_lon, lat, lon)
        
        lat1_rad = math.radians(self.center_lat)
        lat2_rad = math.radians(lat)
        delta_lon_rad = math.radians(lon - self.center_lon)
        
        x = math.sin(delta_lon_rad) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon_rad)
        bearing_rad = math.atan2(x, y)
        
        pixel_distance = distance_miles * pixels_per_mile
        offset_x = pixel_distance * math.sin(bearing_rad)
        offset_y = -pixel_distance * math.cos(bearing_rad)
        
        x_pixel = int(self.display_width / 2 + offset_x)
        y_pixel = int(self.display_height / 2 + offset_y)
        
        if 0 <= x_pixel < self.display_width and 0 <= y_pixel < self.display_height:
            return (x_pixel, y_pixel)
        
        return None

    def _get_closest_aircraft(self) -> Optional[Dict]:
        """Get the closest aircraft to the center point."""
        if not self.aircraft_data:
            return None
        
        closest = min(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
        return closest

    def _queue_interesting_callsigns(self):
        """Queue callsigns worth fetching flight plan data for."""
        # Implementation placeholder - can be expanded
        pass

    def _background_fetch_flight_plans(self):
        """Fetch flight plan data in background."""
        # Implementation placeholder - can be expanded
        pass

    def _display_map(self) -> None:
        """Display map view with aircraft."""
        # Get map background if enabled
        map_bg = self._get_map_background(self.center_lat, self.center_lon) if self.map_bg_enabled else None
        
        if map_bg:
            img = map_bg.copy()
        else:
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        
        draw = ImageDraw.Draw(img)
        
        # Draw center position marker
        center_pixel = self._latlon_to_pixel(self.center_lat, self.center_lon)
        if center_pixel:
            x, y = center_pixel
            draw.point((x, y), fill=(255, 255, 255))
        
        # Draw aircraft trails if enabled
        if self.show_trails:
            for icao, trail in self.aircraft_trails.items():
                if icao not in self.aircraft_data:
                    continue
                
                aircraft = self.aircraft_data[icao]
                trail_pixels = [self._latlon_to_pixel(lat, lon) for lat, lon, _ in trail if self._latlon_to_pixel(lat, lon)]
                
                if len(trail_pixels) >= 2:
                    for i in range(len(trail_pixels) - 1):
                        alpha = int(255 * (i + 1) / len(trail_pixels))
                        color = tuple(int(c * alpha / 255) for c in aircraft['color'])
                        draw.line([trail_pixels[i], trail_pixels[i + 1]], fill=color, width=1)
        
        # Draw aircraft
        for aircraft in self.aircraft_data.values():
            pixel = self._latlon_to_pixel(aircraft['lat'], aircraft['lon'])
            if not pixel:
                continue
            
            x, y = pixel
            base_color = aircraft['color']
            color = tuple(min(255, int(c * 1.3)) for c in base_color)
            draw.point((x, y), fill=color)
        
        # Draw aircraft count
        if len(self.aircraft_data) > 0:
            info_text = f"{len(self.aircraft_data)}"
            self._draw_text_smart(draw, info_text, (2, 2), self.fonts['small'], 
                                fill=(200, 200, 200), use_outline=False)
            
            bbox = draw.textbbox((0, 0), info_text, font=self.fonts['small'])
            text_width = bbox[2] - bbox[0]
            self._draw_airplane_icon(draw, 2 + text_width + 2, 2, color=(200, 200, 200))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _display_overhead(self) -> None:
        """Display detailed overhead view of closest aircraft."""
        closest = self._get_closest_aircraft()
        
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        if not closest:
            self._draw_text_with_outline(draw, "No Aircraft", 
                                       (self.display_width // 2 - 30, self.display_height // 2 - 4), 
                                       self.fonts['medium'], fill=(200, 200, 200))
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            return
        
        is_small_display = self.display_width <= 128 and self.display_height <= 32
        
        if is_small_display:
            y_offset = 2
            self._draw_text_smart(draw, f"{closest['callsign']}", (2, y_offset), 
                                self.fonts['data_medium'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])
            
            self._draw_text_smart(draw, f"ALT:{int(closest['altitude'])}ft", (2, y_offset), 
                                self.fonts['data_small'], fill=closest['color'], use_outline=False)
            self._draw_text_smart(draw, f"SPD:{int(closest['speed'])}kt", (self.display_width // 2, y_offset), 
                                self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_small'])
            
            self._draw_text_smart(draw, f"DIST:{closest['distance_miles']:.2f}mi", (2, y_offset), 
                                self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
            if closest['heading']:
                self._draw_text_smart(draw, f"HDG:{int(closest['heading'])}°", (self.display_width // 2, y_offset), 
                                    self.fonts['data_small'], fill=(200, 200, 200), use_outline=False)
        else:
            y_offset = 4
            self._draw_text_with_outline(draw, "OVERHEAD AIRCRAFT", (self.display_width // 2 - 40, y_offset), 
                                       self.fonts['title_large'], fill=(255, 200, 0))
            y_offset += self._calculate_line_spacing(self.fonts['title_large']) + 4
            
            self._draw_text_smart(draw, f"Callsign: {closest['callsign']}", (4, y_offset), 
                                self.fonts['data_large'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_large'])
            
            self._draw_text_smart(draw, f"Altitude: {int(closest['altitude'])} ft", (4, y_offset), 
                                self.fonts['data_medium'], fill=closest['color'], use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])
            
            self._draw_text_smart(draw, f"Speed: {int(closest['speed'])} knots", (4, y_offset), 
                                self.fonts['data_medium'], fill=(200, 200, 200), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_medium'])
            
            self._draw_text_smart(draw, f"Distance: {closest['distance_miles']:.2f} miles", (4, y_offset), 
                                self.fonts['data_medium'], fill=(255, 150, 0), use_outline=False)
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _display_stats(self) -> None:
        """Display flight statistics (rotating)."""
        if not self.aircraft_data:
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            self._draw_text_with_outline(draw, "No Aircraft", 
                                       (self.display_width // 2 - 30, self.display_height // 2 - 4), 
                                       self.fonts['medium'], fill=(200, 200, 200))
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            return
        
        # Rotate stats every 10 seconds
        current_time = time.time()
        if current_time - self.last_stat_change >= self.stat_duration:
            self.current_stat = (self.current_stat + 1) % 3
            self.last_stat_change = current_time
        
        # Get statistics
        if self.current_stat == 0:
            aircraft = min(self.aircraft_data.values(), key=lambda a: a['distance_miles'])
            title = "CLOSEST"
            title_color = (255, 100, 0)
        elif self.current_stat == 1:
            aircraft = max(self.aircraft_data.values(), key=lambda a: a['speed'])
            title = "FASTEST"
            title_color = (0, 255, 100)
        else:
            aircraft = max(self.aircraft_data.values(), key=lambda a: a['altitude'])
            title = "HIGHEST"
            title_color = (100, 150, 255)
        
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        is_small_display = self.display_width <= 128 and self.display_height <= 32
        
        if is_small_display:
            y_offset = 1
            self._draw_text_with_outline(draw, title, (2, y_offset), 
                                       self.fonts['title_medium'], fill=title_color)
            y_offset += self._calculate_line_spacing(self.fonts['title_medium'])
            
            self._draw_text_smart(draw, aircraft['callsign'], (2, y_offset), 
                                self.fonts['data_small'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_small'])
            
            if self.current_stat == 0:
                stat_text = f"{aircraft['distance_miles']:.2f}mi"
            elif self.current_stat == 1:
                stat_text = f"{int(aircraft['speed'])}kt"
            else:
                stat_text = f"{int(aircraft['altitude'])}ft"
            
            self._draw_text_smart(draw, stat_text, (2, y_offset), 
                                self.fonts['data_medium'], fill=aircraft['color'], use_outline=False)
        else:
            y_offset = 4
            self._draw_text_with_outline(draw, title, (self.display_width // 2 - 30, y_offset), 
                                       self.fonts['title_large'], fill=title_color)
            y_offset += self._calculate_line_spacing(self.fonts['title_large']) + 4
            
            self._draw_text_smart(draw, f"Callsign: {aircraft['callsign']}", (4, y_offset), 
                                self.fonts['data_large'], fill=(255, 255, 255), use_outline=False)
            y_offset += self._calculate_line_spacing(self.fonts['data_large'])
            
            if self.current_stat == 0:
                self._draw_text_smart(draw, f"Distance: {aircraft['distance_miles']:.2f} miles", (4, y_offset), 
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
            elif self.current_stat == 1:
                self._draw_text_smart(draw, f"Speed: {int(aircraft['speed'])} knots", (4, y_offset), 
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
            else:
                self._draw_text_smart(draw, f"Altitude: {int(aircraft['altitude'])} ft", (4, y_offset), 
                                    self.fonts['data_large'], fill=title_color, use_outline=False)
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _get_map_background(self, center_lat: float, center_lon: float) -> Optional[Image.Image]:
        """Get the map background for the current view."""
        # Simplified map background - full implementation would include tile fetching
        # For now, return None to use black background
        return None

    def _draw_text_with_outline(self, draw, text, position, font, fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with outline."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def _draw_text_smart(self, draw, text, position, font, fill=(255, 255, 255), use_outline=True):
        """Smart text drawing."""
        if use_outline:
            self._draw_text_with_outline(draw, text, position, font, fill)
        else:
            draw.text(position, text, font=font, fill=fill)

    def _draw_airplane_icon(self, draw: ImageDraw.Draw, x: int, y: int, color: Tuple[int, int, int] = (200, 200, 200)):
        """Draw a simple airplane icon."""
        airplane_pixels = [
            (2, 0), (2, 1),
            (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),
            (2, 3), (1, 4), (2, 4), (3, 4),
        ]
        
        for px, py in airplane_pixels:
            draw.point((x + px, y + py), fill=color)

    def _calculate_line_spacing(self, font, padding_factor: float = 1.2) -> int:
        """Calculate line spacing based on font height."""
        try:
            if hasattr(font, 'size'):
                return int(font.size * padding_factor)
            return 8
        except Exception:
            return 8

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.aircraft_data.clear()
        self.aircraft_trails.clear()
        self.logger.info("Flight tracker plugin cleaned up")

