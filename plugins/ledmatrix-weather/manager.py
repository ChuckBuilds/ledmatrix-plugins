"""
Weather Plugin for LEDMatrix

Comprehensive weather display with current conditions, hourly forecast, and daily forecast.
Uses Open-Meteo API (free, no API key required) with RainViewer for precipitation radar.

Features:
- Current weather conditions with temperature, humidity, wind speed
- Hourly forecast (next 24-48 hours)
- Daily forecast (next 7 days)
- Weather icons matching conditions
- UV index display
- Automatic error handling and retry logic
"""

import requests
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

# Import weather icons from local module
try:
    # Try relative import first (if module is loaded as package)
    from .weather_icons import WeatherIcons
except ImportError:
    try:
        # Fallback to direct import (plugin dir is in sys.path)
        import weather_icons
        WeatherIcons = weather_icons.WeatherIcons
    except ImportError:
        # Fallback if weather icons not available
        class WeatherIcons:
            @staticmethod
            def draw_weather_icon(image, icon_code, x, y, size):
                # Simple fallback - just draw a circle
                draw = ImageDraw.Draw(image)
                draw.ellipse([x, y, x + size, y + size], outline=(255, 255, 255), width=2)

# Import API counter function

class WeatherPlugin(BasePlugin):
    """
    Weather plugin that displays current conditions and forecasts.

    Supports display modes: weather, hourly_forecast, daily_forecast, almanac, radar.

    Configuration options:
        location (dict): City, state, country for weather data
        units (str): 'imperial' (F) or 'metric' (C)
        update_interval (int): Seconds between API updates
        display_modes (dict): Enable/disable specific display modes
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the weather plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Location - read from flat format (location_city, location_state, location_country)
        # These are the fields defined in config_schema.json for the web interface
        self.location = {
            'city': config.get('location_city', 'Dallas'),
            'state': config.get('location_state', 'Texas'),
            'country': config.get('location_country', 'US')
        }
        
        self.units = config.get('units', 'imperial')
        
        # Handle update_interval - ensure it's an int
        update_interval = config.get('update_interval', 1800)
        try:
            self.update_interval = int(update_interval)
        except (ValueError, TypeError):
            self.update_interval = 1800
        
        # Display modes - read from flat boolean fields
        # These are the fields defined in config_schema.json for the web interface
        self.show_current = config.get('show_current_weather', True)
        self.show_hourly = config.get('show_hourly_forecast', True)
        self.show_daily = config.get('show_daily_forecast', True)
        self.show_almanac = config.get('show_almanac', True)
        self.show_radar = config.get('show_radar', True)
        self.show_alerts = config.get('show_alerts', True)

        # Enhanced current conditions toggles
        self.show_feels_like = config.get('show_feels_like', True)
        self.show_dew_point = config.get('show_dew_point', True)
        self.show_visibility = config.get('show_visibility', True)
        self.show_pressure = config.get('show_pressure', True)

        # Radar config
        self.radar_zoom = config.get('radar_zoom', 6)
        self.radar_update_interval = config.get('radar_update_interval', 600)
        
        # Data storage
        self.weather_data = None
        self.forecast_data = None
        self.hourly_forecast = None
        self.daily_forecast = None
        self.last_update = 0
        
        # Error handling and throttling
        self.consecutive_errors = 0
        self.last_error_time = 0
        self.error_backoff_time = 60
        self.max_consecutive_errors = 5
        self.error_log_throttle = 300  # Only log errors every 5 minutes
        self.last_error_log_time = 0
        self._last_error_hint = None  # Human-readable hint for diagnostic display
        
        # State caching for display optimization
        self.last_weather_state = None
        self.last_hourly_state = None
        self.last_daily_state = None
        self.current_display_mode = None  # Track current mode to detect switches
        
        # Internal mode cycling (similar to hockey plugin)
        # Build list of enabled modes in order
        self.modes = []
        if self.show_current:
            self.modes.append('weather')
        if self.show_hourly:
            self.modes.append('hourly_forecast')
        if self.show_daily:
            self.modes.append('daily_forecast')
        if self.show_almanac:
            self.modes.append('almanac')
        if self.show_radar:
            self.modes.append('radar')
        
        # Default to first mode if none enabled
        if not self.modes:
            self.modes = ['weather']
        
        self.current_mode_index = 0
        self.last_mode_switch = 0
        self.display_duration = config.get('display_duration', 30)
        
        # Layout constants
        self.PADDING = 1
        self.COLORS = {
            'text': (255, 255, 255),
            'highlight': (255, 200, 0),
            'separator': (64, 64, 64),
            'temp_high': (255, 100, 100),
            'temp_low': (100, 100, 255),
            'dim': (180, 180, 180),
            'extra_dim': (120, 120, 120),
            'uv_low': (0, 150, 0),
            'uv_moderate': (255, 200, 0),
            'uv_high': (255, 120, 0),
            'uv_very_high': (200, 0, 0),
            'uv_extreme': (150, 0, 200)
        }
        
        # Resolve project root path (plugin_dir -> plugins -> project_root)
        self.project_root = Path(__file__).resolve().parent.parent.parent
        
        # Weather icons path (Note: WeatherIcons class resolves paths itself, this is just for reference)
        self.icons_dir = self.project_root / 'assets' / 'weather'
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Weather plugin initialized for {self.location.get('city', 'Unknown')}")
        self.logger.info(f"Units: {self.units}, Update interval: {self.update_interval}s")
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager') or self.plugin_manager.font_manager is None:
                self.logger.warning("Font manager not available")
                return
            
            font_manager = self.plugin_manager.font_manager
            
            # Register fonts for different elements
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.temperature",
                family="press_start",
                size_px=16,
                color=self.COLORS['text']
            )
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.condition",
                family="four_by_six",
                size_px=8,
                color=self.COLORS['highlight']
            )
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.forecast_label",
                family="four_by_six",
                size_px=6,
                color=self.COLORS['dim']
            )
            
            self.logger.info("Weather plugin fonts registered successfully")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def _get_layout(self) -> dict:
        """Return cached layout parameters (computed once on first call).

        Icon sizes scale proportionally with display height.
        Text spacing stays fixed because fonts are fixed-size bitmaps.
        Reference baseline: 128x32 display.
        """
        if hasattr(self, '_layout_cache'):
            return self._layout_cache

        width = self.display_manager.matrix.width
        height = self.display_manager.matrix.height
        h_scale = height / 32.0

        # Fixed font metrics (do not change with display size)
        small_font_h = 8
        extra_small_font_h = 7

        margin = max(1, round(1 * h_scale))

        # --- Current weather mode ---
        current_icon_size = max(14, round(40 * h_scale))
        current_icon_x = margin
        current_available_h = (height * 2) // 3
        current_icon_y = (current_available_h - current_icon_size) // 2

        # Text rows on right side (fixed spacing since fonts are fixed)
        condition_y = margin
        temp_y = condition_y + small_font_h
        high_low_y = temp_y + small_font_h
        bottom_bar_y = height - extra_small_font_h

        # --- Forecast modes (hourly + daily) ---
        # Scale with height but cap by narrowest column width to prevent overflow
        min_column_width = width // 4
        forecast_icon_size = max(14, min(round(30 * h_scale), min_column_width))
        forecast_top_y = margin
        forecast_icon_y = max(0, (height - forecast_icon_size) // 2)
        forecast_bottom_y = height - small_font_h

        self._layout_cache = {
            'current_icon_size': current_icon_size,
            'current_icon_x': current_icon_x,
            'current_icon_y': current_icon_y,
            'condition_y': condition_y,
            'temp_y': temp_y,
            'high_low_y': high_low_y,
            'bottom_bar_y': bottom_bar_y,
            'right_margin': margin,
            'forecast_icon_size': forecast_icon_size,
            'forecast_top_y': forecast_top_y,
            'forecast_icon_y': forecast_icon_y,
            'forecast_bottom_y': forecast_bottom_y,
            'margin': margin,
        }
        return self._layout_cache

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Handle live configuration updates."""
        self.config = new_config
        self.location = {
            'city': new_config.get('location_city', self.location.get('city', 'Dallas')),
            'state': new_config.get('location_state', self.location.get('state', 'Texas')),
            'country': new_config.get('location_country', self.location.get('country', 'US')),
        }
        self.units = new_config.get('units', self.units)
        self.show_current = new_config.get('show_current_weather', self.show_current)
        self.show_hourly = new_config.get('show_hourly_forecast', self.show_hourly)
        self.show_daily = new_config.get('show_daily_forecast', self.show_daily)
        self.show_almanac = new_config.get('show_almanac', self.show_almanac)
        self.show_radar = new_config.get('show_radar', self.show_radar)

        # Rebuild mode list and reset index so IndexError can't occur
        self.modes = []
        if self.show_current:
            self.modes.append('weather')
        if self.show_hourly:
            self.modes.append('hourly_forecast')
        if self.show_daily:
            self.modes.append('daily_forecast')
        if self.show_almanac:
            self.modes.append('almanac')
        if self.show_radar:
            self.modes.append('radar')
        if not self.modes:
            self.modes = ['weather']
        self.current_mode_index = 0
        self.current_display_mode = None

        self._layout_cache = None  # Invalidate layout cache on config change
        self.logger.info("Configuration updated")

    def update(self) -> None:
        """
        Update weather data from Open-Meteo API.

        Fetches current conditions and forecast data, respecting
        update intervals and error backoff periods.
        """
        # Refresh radar tiles unconditionally (uses RainViewer, separate from weather data)
        self._update_radar()

        current_time = time.time()

        # Check if we need to update
        if current_time - self.last_update < self.update_interval:
            return

        # Check if we're in error backoff period
        if self.consecutive_errors >= self.max_consecutive_errors:
            if current_time - self.last_error_time < self.error_backoff_time:
                self.logger.debug(f"In error backoff period, retrying in {self.error_backoff_time - (current_time - self.last_error_time):.0f}s")
                # Still reprocess forecast so past hours drop off the display
                if self.forecast_data:
                    self._process_forecast_data(self.forecast_data)
                return
            else:
                # Reset error count after backoff
                self.consecutive_errors = 0
                self.error_backoff_time = 60

        # Try to fetch weather data
        try:
            self._fetch_weather()
            self.last_update = current_time
            self.consecutive_errors = 0
            self._last_error_hint = None
        except Exception as e:
            self.consecutive_errors += 1
            self.last_error_time = current_time
            if not self._last_error_hint:
                self._last_error_hint = str(e)[:40]

            # Exponential backoff: double the backoff time (max 1 hour)
            self.error_backoff_time = min(self.error_backoff_time * 2, 3600)

            # Only log errors periodically to avoid spam
            if current_time - self.last_error_log_time > self.error_log_throttle:
                self.logger.error(f"Error updating weather (attempt {self.consecutive_errors}/{self.max_consecutive_errors}): {e}")
                if self.consecutive_errors >= self.max_consecutive_errors:
                    self.logger.error(f"Weather API disabled for {self.error_backoff_time} seconds due to repeated failures")
                self.last_error_log_time = current_time

            # Re-filter existing forecast data so past hours drop off the
            # hourly display even when API calls are failing.
            if self.forecast_data:
                self._process_forecast_data(self.forecast_data)

    def _update_radar(self) -> None:
        """Refresh radar data in the update loop so display() never blocks on HTTP."""
        if not self.show_radar:
            return
        try:
            self._ensure_radar_fetcher()
            if hasattr(self, '_radar_fetcher') and self._radar_fetcher.needs_refresh(self.radar_update_interval):
                width = self.display_manager.matrix.width
                height = self.display_manager.matrix.height
                self._radar_fetcher.refresh_data(width, height)
        except Exception:
            self.logger.exception("Error refreshing radar data")

    def _ensure_radar_fetcher(self) -> None:
        """Create or recreate the RadarFetcher when config or coordinates change."""
        lat = None
        lon = None
        if self.forecast_data:
            lat = self.forecast_data.get('lat')
            lon = self.forecast_data.get('lon')
        if lat is None or lon is None:
            return

        line_color = tuple(self.config.get('radar_line_color', [0, 130, 70]))
        fill_color = tuple(self.config.get('radar_fill_color', [15, 25, 15]))

        # Reuse existing fetcher if config hasn't changed
        if hasattr(self, '_radar_fetcher'):
            f = self._radar_fetcher
            if (f.lat == lat and f.lon == lon and f.zoom == self.radar_zoom
                    and f.line_color == line_color and f.fill_color == fill_color):
                return
            self.logger.info("Radar config changed, recreating RadarFetcher")

        from radar import RadarFetcher
        self._radar_fetcher = RadarFetcher(
            lat, lon, self.radar_zoom, self.cache_manager,
            line_color=line_color, fill_color=fill_color,
        )

    def _fetch_weather(self) -> None:
        """Fetch weather data from Open-Meteo API (free, no API key required)."""
        city = self.location.get('city', 'Dallas')
        state = self.location.get('state', 'Texas')
        country = self.location.get('country', 'US')
        cache_key = f"{self.plugin_id}:{city}:{state}:{country}:{self.units}:weather"
        cached_data = self.cache_manager.get(cache_key, max_age=self.update_interval)
        if cached_data:
            self.weather_data = cached_data.get('current')
            self.forecast_data = cached_data.get('forecast')
            if self.weather_data and self.forecast_data:
                # Backfill sun/moon/alerts from forecast_data if missing from older cache
                if 'sun' not in self.weather_data and 'current' in self.forecast_data:
                    fc = self.forecast_data['current']
                    self.weather_data['sun'] = {
                        'sunrise': fc.get('sunrise'),
                        'sunset': fc.get('sunset'),
                    }
                if 'moon' not in self.weather_data and self.forecast_data.get('daily'):
                    d0 = self.forecast_data['daily'][0]
                    self.weather_data['moon'] = {
                        'phase': d0.get('moon_phase'),
                        'moonrise': d0.get('moonrise'),
                        'moonset': d0.get('moonset'),
                    }
                if 'alerts' not in self.weather_data:
                    self.weather_data['alerts'] = self.forecast_data.get('alerts', [])
                if 'timezone_offset' not in self.weather_data:
                    self.weather_data['timezone_offset'] = self.forecast_data.get('timezone_offset', 0)
                self._process_forecast_data(self.forecast_data)
                self.logger.info("Using cached weather data")
                return

        # Step A: Geocoding via Open-Meteo geocoding API
        from urllib.parse import quote_plus
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={quote_plus(city)}&count=5&language=en&format=json"
        try:
            response = requests.get(geo_url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            self._last_error_hint = f"Geo API error {status}"
            self.logger.error(f"Open-Meteo geocoding HTTP error {status}: {e}")
            raise

        results = response.json().get('results', [])
        if not results:
            self._last_error_hint = f"Unknown: {city}"
            msg = f"Could not find coordinates for {city}, {state}, {country}"
            self.logger.error(msg)
            raise ValueError(msg)

        # Pick the best result by matching country code
        country_upper = country.upper() if country else ''
        lat, lon = results[0]['latitude'], results[0]['longitude']
        for r in results:
            if r.get('country_code', '').upper() == country_upper:
                lat, lon = r['latitude'], r['longitude']
                break

        # Step B: Fetch forecast from Open-Meteo
        temp_unit = "fahrenheit" if self.units == "imperial" else "celsius"
        wind_unit = "mph" if self.units == "imperial" else "kmh"
        forecast_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"dew_point_2m,surface_pressure,cloud_cover,visibility,"
            f"wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,weather_code,is_day"
            f"&hourly=temperature_2m,weather_code,is_day"
            f"&daily=temperature_2m_max,temperature_2m_min,weather_code,sunrise,sunset,uv_index_max"
            f"&temperature_unit={temp_unit}"
            f"&wind_speed_unit={wind_unit}"
            f"&timezone=auto"
            f"&forecast_days=7"
        )
        try:
            response = requests.get(forecast_url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            self._last_error_hint = f"Weather API error {status}"
            self.logger.error(f"Open-Meteo forecast HTTP error {status}: {e}")
            raise

        om_data = response.json()
        current = om_data['current']

        wmo_code = current.get('weather_code', 0)
        is_day = bool(current.get('is_day', 1))
        icon_code = WeatherIcons.wmo_to_icon_code(wmo_code, is_day)
        condition = WeatherIcons.wmo_to_condition(wmo_code)

        daily_list = self._map_om_daily(om_data)
        daily_today = daily_list[0] if daily_list else {}

        tz_offset = om_data.get('utc_offset_seconds', 0)

        self.weather_data = {
            'main': {
                'temp': current.get('temperature_2m'),
                'temp_max': daily_today.get('temp', {}).get('max'),
                'temp_min': daily_today.get('temp', {}).get('min'),
                'humidity': current.get('relative_humidity_2m'),
                'pressure': current.get('surface_pressure'),
                'uvi': current.get('uv_index', 0),
                'feels_like': current.get('apparent_temperature'),
                'dew_point': current.get('dew_point_2m'),
                'visibility': current.get('visibility'),
                'clouds': current.get('cloud_cover'),
            },
            'weather': [{'main': condition, 'icon': icon_code, 'description': condition.lower()}],
            'wind': {
                'speed': current.get('wind_speed_10m', 0),
                'deg': current.get('wind_direction_10m', 0),
                'gust': current.get('wind_gusts_10m'),
            },
            'sun': {
                'sunrise': daily_today.get('sunrise'),
                'sunset': daily_today.get('sunset'),
            },
            'moon': {
                'phase': daily_today.get('moon_phase'),
                'moonrise': daily_today.get('moonrise'),
                'moonset': daily_today.get('moonset'),
            },
            'alerts': [],
            'timezone_offset': tz_offset,
        }

        self.forecast_data = {
            'lat': lat,
            'lon': lon,
            'timezone': om_data.get('timezone', 'UTC'),
            'timezone_offset': tz_offset,
            'current': {
                'sunrise': daily_today.get('sunrise'),
                'sunset': daily_today.get('sunset'),
            },
            'daily': daily_list,
            'hourly': self._map_om_hourly(om_data),
            'alerts': [],
        }

        # Step C: NWS alerts (US-only)
        alerts = self._fetch_nws_alerts(lat, lon) if country_upper == 'US' else []
        self.weather_data['alerts'] = alerts
        self.forecast_data['alerts'] = alerts

        self._process_forecast_data(self.forecast_data)

        self.cache_manager.set(cache_key, {
            'current': self.weather_data,
            'forecast': self.forecast_data,
        })

        self.logger.info(f"Weather data updated for {city}: {self.weather_data['main']['temp']}°")

    def _map_om_hourly(self, om_data: Dict) -> List[Dict]:
        """Convert Open-Meteo hourly arrays to OWM-compatible hourly list."""
        import zoneinfo
        hourly = om_data.get('hourly', {})
        times = hourly.get('time', [])
        temps = hourly.get('temperature_2m', [])
        codes = hourly.get('weather_code', [])
        is_days = hourly.get('is_day', [])
        tz_name = om_data.get('timezone', 'UTC')
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo('UTC')
        result = []
        for i, t in enumerate(times):
            try:
                ts = int(datetime.fromisoformat(t).replace(tzinfo=tz).timestamp())
            except (ValueError, OverflowError, OSError) as exc:
                self.logger.debug("Skipping hourly entry with unparseable time %r: %s", t, exc)
                continue
            code = codes[i] if i < len(codes) else 0
            is_day = bool(is_days[i]) if i < len(is_days) else True
            result.append({
                'dt': ts,
                'temp': temps[i] if i < len(temps) else 0,
                'weather': [{'main': WeatherIcons.wmo_to_condition(code),
                              'icon': WeatherIcons.wmo_to_icon_code(code, is_day)}],
            })
        return result

    def _map_om_daily(self, om_data: Dict) -> List[Dict]:
        """Convert Open-Meteo daily arrays to OWM-compatible daily list.

        Moon phase / moonrise / moonset are computed via astral since
        Open-Meteo does not provide those variables.
        """
        from astral import moon as astral_moon, Observer
        import zoneinfo

        daily = om_data.get('daily', {})
        times = daily.get('time', [])
        lat = om_data.get('latitude', 0)
        lon = om_data.get('longitude', 0)
        tz_name = om_data.get('timezone', 'UTC')
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo('UTC')
        observer = Observer(latitude=lat, longitude=lon)

        def parse_ts(s):
            if not s:
                return None
            try:
                return int(datetime.fromisoformat(s).replace(tzinfo=tz).timestamp())
            except Exception:
                return None

        result = []
        for i, t in enumerate(times):
            try:
                dt = datetime.fromisoformat(t).replace(tzinfo=tz)
                ts = int(dt.timestamp())
                d = dt.date()
            except (ValueError, OverflowError, OSError) as exc:
                self.logger.debug("Skipping daily entry with unparseable time %r: %s", t, exc)
                continue
            code = daily['weather_code'][i] if i < len(daily.get('weather_code', [])) else 0

            # Moon phase: astral returns 0-28; normalize to 0-1 to match OWM convention
            moon_phase = astral_moon.phase(d) / 28.0
            try:
                moonrise_dt = astral_moon.moonrise(observer, d, tzinfo=tz)
                moonrise_ts = int(moonrise_dt.timestamp()) if moonrise_dt else None
            except Exception:
                moonrise_ts = None
            try:
                moonset_dt = astral_moon.moonset(observer, d, tzinfo=tz)
                moonset_ts = int(moonset_dt.timestamp()) if moonset_dt else None
            except Exception:
                moonset_ts = None

            result.append({
                'dt': ts,
                'temp': {
                    'max': daily['temperature_2m_max'][i] if i < len(daily.get('temperature_2m_max', [])) else 0,
                    'min': daily['temperature_2m_min'][i] if i < len(daily.get('temperature_2m_min', [])) else 0,
                },
                'weather': [{'main': WeatherIcons.wmo_to_condition(code),
                              'icon': WeatherIcons.wmo_to_icon_code(code, True)}],
                'sunrise': parse_ts(daily['sunrise'][i] if i < len(daily.get('sunrise', [])) else None),
                'sunset': parse_ts(daily['sunset'][i] if i < len(daily.get('sunset', [])) else None),
                'moonrise': moonrise_ts,
                'moonset': moonset_ts,
                'moon_phase': moon_phase,
            })
        return result

    def _fetch_nws_alerts(self, lat: float, lon: float) -> List[Dict]:
        """Fetch active weather alerts from NWS API (US-only, free, no API key)."""
        try:
            url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
            headers = {'User-Agent': 'LEDMatrix-Weather/2.3.0 (github.com/ChuckBuilds/ledmatrix-plugins)'}
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code == 200:
                return [
                    {
                        'event': f.get('properties', {}).get('event', ''),
                        'sender_name': f.get('properties', {}).get('senderName', ''),
                        'description': f.get('properties', {}).get('description', ''),
                    }
                    for f in response.json().get('features', [])
                ]
        except Exception:
            pass
        return []
    
    def _process_forecast_data(self, forecast_data: Dict) -> None:
        """Process forecast data into hourly and daily lists."""
        if not forecast_data:
            return

        import zoneinfo
        tz_name = forecast_data.get('timezone', 'UTC')
        try:
            location_tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            location_tz = zoneinfo.ZoneInfo('UTC')

        # Process hourly forecast (next 5 hours, excluding current hour)
        hourly_list = forecast_data.get('hourly', [])

        # Filter out the current hour - get current timestamp rounded down to the hour
        current_time = time.time()
        current_hour_timestamp = int(current_time // 3600) * 3600  # Round down to nearest hour

        # Filter out entries that are in the current hour or past
        future_hourly = [
            hour_data for hour_data in hourly_list
            if hour_data.get('dt', 0) > current_hour_timestamp
        ]

        # Get next 5 hours
        hourly_list = future_hourly[:5]
        self.hourly_forecast = []

        for hour_data in hourly_list:
            dt = datetime.fromtimestamp(hour_data['dt'], tz=location_tz)
            temp = round(hour_data['temp'])
            condition = hour_data['weather'][0]['main']
            icon_code = hour_data['weather'][0]['icon']
            self.hourly_forecast.append({
                'hour': dt.strftime('%I:00 %p').lstrip('0'),  # Format as "2:00 PM"
                'temp': temp,
                'condition': condition,
                'icon': icon_code
            })

        # Process daily forecast — filter to future days from today so stale cached
        # data doesn't show past days (mirrors the hourly filter above).
        today = datetime.now().date()
        daily_list = [
            day for day in forecast_data.get('daily', [])
            if datetime.fromtimestamp(day.get('dt', 0)).date() > today
        ][:3]
        self.daily_forecast = []
        
        for day_data in daily_list:
            dt = datetime.fromtimestamp(day_data['dt'])
            temp_high = round(day_data['temp']['max'])
            temp_low = round(day_data['temp']['min'])
            condition = day_data['weather'][0]['main']
            icon_code = day_data['weather'][0]['icon']
            
            self.daily_forecast.append({
                'date': dt.strftime('%a'),  # Day name (Mon, Tue, etc.)
                'date_str': dt.strftime('%m/%d'),  # Date (4/8, 4/9, etc.)
                'temp_high': temp_high,
                'temp_low': temp_low,
                'condition': condition,
                'icon': icon_code
            })
    
    def display(self, force_clear: bool = False, display_mode: Optional[str] = None) -> None:
        """
        Display weather information with internal mode cycling.
        
        The display controller registers each mode separately (weather, hourly_forecast, daily_forecast)
        but calls display() without passing the mode name. This plugin handles mode cycling internally
        similar to the hockey plugin, advancing through enabled modes based on time.
        
        Args:
            display_mode: Optional mode name (not currently used, kept for compatibility)
            force_clear: If True, clear the display before rendering (ignored, kept for compatibility)
        """
        if not self.weather_data:
            self._display_no_data()
            return
        
        # Note: force_clear is handled by display_manager, not needed here
        # This parameter is kept for compatibility with BasePlugin interface
        
        current_mode = None

        # If a specific mode is requested (compatibility methods), honor it
        if display_mode and display_mode in self.modes:
            try:
                requested_index = self.modes.index(display_mode)
            except ValueError:
                requested_index = None

            if requested_index is not None:
                current_mode = self.modes[requested_index]
                if current_mode != self.current_display_mode:
                    self.current_mode_index = requested_index
                    self._on_mode_changed(current_mode)
        else:
            # Default rotation synchronized with display controller
            if self.current_display_mode is None:
                current_mode = self.modes[self.current_mode_index]
                self._on_mode_changed(current_mode)
            elif force_clear:
                self.current_mode_index = (self.current_mode_index + 1) % len(self.modes)
                current_mode = self.modes[self.current_mode_index]
                self._on_mode_changed(current_mode)
            else:
                current_mode = self.modes[self.current_mode_index]
        
        # Ensure we have a mode even if none of the above paths triggered a change
        if current_mode is None:
            current_mode = self.current_display_mode or self.modes[self.current_mode_index]
        
        # Display the current mode
        if current_mode == 'hourly_forecast' and self.show_hourly:
            self._display_hourly_forecast()
        elif current_mode == 'daily_forecast' and self.show_daily:
            self._display_daily_forecast()
        elif current_mode == 'almanac' and self.show_almanac:
            self._display_almanac()
        elif current_mode == 'radar' and self.show_radar:
            self._display_radar()
        elif current_mode == 'weather' and self.show_current:
            self._display_current_weather()
        else:
            self._display_current_weather()
    
    def _on_mode_changed(self, new_mode: str) -> None:
        """Handle logic needed when switching display modes."""
        if new_mode == self.current_display_mode:
            return

        self.logger.info(f"Display mode changed from {self.current_display_mode} to {new_mode}")
        if new_mode == 'hourly_forecast':
            self.last_hourly_state = None
            self.logger.debug("Reset hourly state cache for mode switch")
        elif new_mode == 'daily_forecast':
            self.last_daily_state = None
            self.logger.debug("Reset daily state cache for mode switch")
        else:
            self.last_weather_state = None
            self.logger.debug("Reset weather state cache for mode switch")

        self.current_display_mode = new_mode
        self.last_mode_switch = time.time()
    
    def _display_no_data(self) -> None:
        """Display a diagnostic message when no weather data is available."""
        img = Image.new('RGB', (self.display_manager.matrix.width, self.display_manager.matrix.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        from PIL import ImageFont
        try:
            font_path = self.project_root / 'assets' / 'fonts' / '4x6-font.ttf'
            font = ImageFont.truetype(str(font_path), 8)
        except Exception:
            font = ImageFont.load_default()

        if self._last_error_hint:
            draw.text((2, 4), "Weather Err", font=font, fill=(200, 200, 200))
            hint = self._last_error_hint[:22]
            draw.text((2, 14), hint, font=font, fill=(255, 100, 100))
        else:
            draw.text((5, 8), "No Weather", font=font, fill=(200, 200, 200))
            draw.text((5, 18), "Data", font=font, fill=(200, 200, 200))

        self.display_manager.image = img
        self.display_manager.update_display()
    
    def _render_current_weather_image(self) -> Optional[Image.Image]:
        """Render current weather conditions to an Image without display side effects."""
        try:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            img = Image.new('RGB', (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Get weather info
            temp = int(self.weather_data['main']['temp'])
            condition = self.weather_data['weather'][0]['main']
            icon_code = self.weather_data['weather'][0]['icon']
            humidity = self.weather_data['main']['humidity']
            wind_speed = self.weather_data['wind'].get('speed', 0)
            wind_deg = self.weather_data['wind'].get('deg', 0)
            uv_index = self.weather_data['main'].get('uvi', 0)
            temp_high = int(self.weather_data['main']['temp_max'])
            temp_low = int(self.weather_data['main']['temp_min'])

            layout = self._get_layout()

            # --- Top Left: Weather Icon ---
            icon_size = layout['current_icon_size']
            icon_x = layout['current_icon_x']
            icon_y = layout['current_icon_y']
            WeatherIcons.draw_weather_icon(img, icon_code, icon_x, icon_y, size=icon_size)

            # --- Top Right: Condition Text ---
            condition_font = self.display_manager.small_font
            condition_text_width = draw.textlength(condition, font=condition_font)
            condition_x = width - condition_text_width - layout['right_margin']
            condition_y = layout['condition_y']
            draw.text((condition_x, condition_y), condition, font=condition_font, fill=self.COLORS['text'])

            # --- Right Side: Current Temperature ---
            temp_text = f"{temp}°"
            temp_font = self.display_manager.small_font
            temp_text_width = draw.textlength(temp_text, font=temp_font)
            temp_x = width - temp_text_width - layout['right_margin']
            temp_y = layout['temp_y']
            draw.text((temp_x, temp_y), temp_text, font=temp_font, fill=self.COLORS['highlight'])

            # --- Right Side: High/Low Temperature ---
            high_low_text = f"{temp_low}°/{temp_high}°"
            high_low_font = self.display_manager.small_font
            high_low_width = draw.textlength(high_low_text, font=high_low_font)
            high_low_x = width - high_low_width - layout['right_margin']
            high_low_y = layout['high_low_y']
            draw.text((high_low_x, high_low_y), high_low_text, font=high_low_font, fill=self.COLORS['dim'])

            # --- Bottom: Additional Metrics ---
            # Build list of enabled metric items, then distribute evenly across rows.
            # Each item is (text, color). Rows fill from left to right, each item
            # centered in its equal-width section (same pattern as original UV/H/W bar).
            font = self.display_manager.extra_small_font

            # Gather all enabled bottom-bar items
            feels_like = self.weather_data['main'].get('feels_like')
            dew_point = self.weather_data['main'].get('dew_point')
            visibility_m = self.weather_data['main'].get('visibility')
            pressure = self.weather_data['main'].get('pressure')
            wind_dir = self._get_wind_direction(wind_deg)
            wind_gust = self.weather_data['wind'].get('gust')

            all_items = []  # list of (text, color)

            # Core items (always shown)
            uv_color = self._get_uv_color(uv_index)
            all_items.append((f"UV:{uv_index:.0f}", uv_color))
            all_items.append((f"H:{humidity}%", self.COLORS['dim']))
            if wind_gust and wind_gust > wind_speed * 1.3:
                all_items.append((f"W:{wind_speed:.0f}g{wind_gust:.0f}{wind_dir}", self.COLORS['dim']))
            else:
                all_items.append((f"W:{wind_speed:.0f}{wind_dir}", self.COLORS['dim']))

            # Extra items — merged into same row (no degree symbol, font can't render it)
            if self.show_feels_like and feels_like is not None:
                all_items.append((f"FL:{int(feels_like)}", self.COLORS['dim']))
            if self.show_dew_point and dew_point is not None:
                all_items.append((f"Dew:{int(dew_point)}", self.COLORS['dim']))
            if self.show_visibility and visibility_m is not None:
                vis_val = visibility_m / 1609.34 if self.units == 'imperial' else visibility_m / 1000
                vis_u = "mi" if self.units == 'imperial' else "km"
                all_items.append((f"Vis:{vis_val:.0f}{vis_u}", self.COLORS['dim']))
            if self.show_pressure and pressure is not None:
                if self.units == 'imperial':
                    pv = pressure * 0.02953
                    all_items.append((f"P:{pv:.2f}\"", self.COLORS['dim']))
                else:
                    all_items.append((f"P:{int(pressure)}hPa", self.COLORS['dim']))

            # Single bottom bar with all items
            if all_items:
                sec_w = width // len(all_items)
                for i, (text, color) in enumerate(all_items):
                    tw = draw.textlength(text, font=font)
                    x = i * sec_w + (sec_w - tw) // 2
                    draw.text((max(0, x), layout['bottom_bar_y']), text, font=font, fill=color)

            return img
        except Exception:
            self.logger.exception("Error rendering current weather")
            return None

    def _display_current_weather(self) -> None:
        """Display current weather conditions using comprehensive layout with icons."""
        try:
            current_state = self._get_weather_state()
            if current_state == self.last_weather_state:
                self.display_manager.update_display()
                return

            self.display_manager.clear()
            img = self._render_current_weather_image()
            if img:
                self.display_manager.image = img
                self.display_manager.update_display()
                self.last_weather_state = current_state
        except Exception as e:
            self.logger.error(f"Error displaying current weather: {e}")
    
    def _get_wind_direction(self, degrees: float) -> str:
        """Convert wind degrees to cardinal direction."""
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        index = round(degrees / 45) % 8
        return directions[index]

    def _get_uv_color(self, uv_index: float) -> tuple:
        """Get color based on UV index value."""
        if uv_index <= 2:
            return self.COLORS['uv_low']
        elif uv_index <= 5:
            return self.COLORS['uv_moderate']
        elif uv_index <= 7:
            return self.COLORS['uv_high']
        elif uv_index <= 10:
            return self.COLORS['uv_very_high']
        else:
            return self.COLORS['uv_extreme']
    
    def _get_weather_state(self) -> Dict[str, Any]:
        """Get current weather state for comparison."""
        if not self.weather_data:
            return None
        return {
            'temp': round(self.weather_data['main']['temp']),
            'condition': self.weather_data['weather'][0]['main'],
            'humidity': self.weather_data['main']['humidity'],
            'uvi': self.weather_data['main'].get('uvi', 0)
        }

    def _get_hourly_state(self) -> List[Dict[str, Any]]:
        """Get current hourly forecast state for comparison."""
        if not self.hourly_forecast:
            return None
        return [
            {'hour': f['hour'], 'temp': round(f['temp']), 'condition': f['condition']}
            for f in self.hourly_forecast[:3]
        ]

    def _get_daily_state(self) -> List[Dict[str, Any]]:
        """Get current daily forecast state for comparison."""
        if not self.daily_forecast:
            return None
        return [
            {
                'date': f['date'],
                'temp_high': round(f['temp_high']),
                'temp_low': round(f['temp_low']),
                'condition': f['condition']
            }
            for f in self.daily_forecast[:4]
        ]
    
    def _render_hourly_forecast_image(self) -> Optional[Image.Image]:
        """Render hourly forecast to an Image without display side effects."""
        try:
            if not self.hourly_forecast:
                return None

            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            img = Image.new('RGB', (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            layout = self._get_layout()
            hours_to_show = min(4, len(self.hourly_forecast))
            section_width = width // hours_to_show
            padding = max(2, section_width // 6)

            for i in range(hours_to_show):
                forecast = self.hourly_forecast[i]
                x = i * section_width + padding
                center_x = x + (section_width - 2 * padding) // 2

                # Hour at top
                hour_text = forecast['hour']
                hour_text = hour_text.replace(":00 ", "").replace("PM", "p").replace("AM", "a")
                hour_width = draw.textlength(hour_text, font=self.display_manager.small_font)
                draw.text((center_x - hour_width // 2, layout['forecast_top_y']),
                         hour_text,
                         font=self.display_manager.small_font,
                         fill=self.COLORS['text'])

                # Weather icon
                icon_size = layout['forecast_icon_size']
                icon_y = layout['forecast_icon_y']
                icon_x = center_x - icon_size // 2
                WeatherIcons.draw_weather_icon(img, forecast['icon'], icon_x, icon_y, icon_size)

                # Temperature at bottom
                temp_text = f"{forecast['temp']}°"
                temp_width = draw.textlength(temp_text, font=self.display_manager.small_font)
                temp_y = layout['forecast_bottom_y']
                draw.text((center_x - temp_width // 2, temp_y),
                         temp_text,
                         font=self.display_manager.small_font,
                         fill=self.COLORS['text'])

            return img
        except Exception:
            self.logger.exception("Error rendering hourly forecast")
            return None

    def _display_hourly_forecast(self) -> None:
        """Display hourly forecast with weather icons."""
        try:
            if not self.hourly_forecast:
                self.logger.warning("No hourly forecast data available, showing no data message")
                self._display_no_data()
                return

            current_state = self._get_hourly_state()
            if current_state == self.last_hourly_state:
                self.display_manager.update_display()
                return

            self.display_manager.clear()
            img = self._render_hourly_forecast_image()
            if img:
                self.display_manager.image = img
                self.display_manager.update_display()
                self.last_hourly_state = current_state
        except Exception as e:
            self.logger.error(f"Error displaying hourly forecast: {e}")
    
    def _render_daily_forecast_image(self) -> Optional[Image.Image]:
        """Render daily forecast to an Image without display side effects."""
        try:
            if not self.daily_forecast:
                return None

            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            img = Image.new('RGB', (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            layout = self._get_layout()
            days_to_show = min(3, len(self.daily_forecast))
            if days_to_show == 0:
                draw.text((2, 2), "No daily forecast", font=self.display_manager.small_font, fill=self.COLORS['dim'])
            else:
                section_width = width // days_to_show

                for i in range(days_to_show):
                    forecast = self.daily_forecast[i]
                    center_x = i * section_width + section_width // 2

                    # Day name at top
                    day_text = forecast['date']
                    day_width = draw.textlength(day_text, font=self.display_manager.small_font)
                    draw.text((center_x - day_width // 2, layout['forecast_top_y']),
                             day_text,
                             font=self.display_manager.small_font,
                             fill=self.COLORS['text'])

                    # Weather icon
                    icon_size = layout['forecast_icon_size']
                    icon_y = layout['forecast_icon_y']
                    icon_x = center_x - icon_size // 2
                    WeatherIcons.draw_weather_icon(img, forecast['icon'], icon_x, icon_y, icon_size)

                    # High/low temperatures at bottom
                    temp_text = f"{forecast['temp_low']} / {forecast['temp_high']}"
                    temp_width = draw.textlength(temp_text, font=self.display_manager.extra_small_font)
                    temp_y = layout['forecast_bottom_y']
                    draw.text((center_x - temp_width // 2, temp_y),
                             temp_text,
                             font=self.display_manager.extra_small_font,
                             fill=self.COLORS['text'])

            return img
        except Exception:
            self.logger.exception("Error rendering daily forecast")
            return None

    def _display_daily_forecast(self) -> None:
        """Display daily forecast with weather icons."""
        try:
            if not self.daily_forecast:
                self._display_no_data()
                return

            current_state = self._get_daily_state()
            if current_state == self.last_daily_state:
                self.display_manager.update_display()
                return

            self.display_manager.clear()
            img = self._render_daily_forecast_image()
            if img:
                self.display_manager.image = img
                self.display_manager.update_display()
                self.last_daily_state = current_state
        except Exception as e:
            self.logger.error(f"Error displaying daily forecast: {e}")
    
    # --- Almanac Display Mode ---

    def _get_moon_phase_name(self, phase: float) -> str:
        """Convert moon phase float (0-1) to a name."""
        if phase is None:
            return "---"
        if phase == 0:
            return "New Moon"
        elif phase < 0.25:
            return "Wax Crescent"
        elif phase == 0.25:
            return "First Quarter"
        elif phase < 0.5:
            return "Wax Gibbous"
        elif phase == 0.5:
            return "Full Moon"
        elif phase < 0.75:
            return "Wan Gibbous"
        elif phase == 0.75:
            return "Last Quarter"
        else:
            return "Wan Crescent"

    def _get_moon_icon_code(self, phase: float) -> str:
        """Map moon phase float (0-1) to one of 8 icon filename stems."""
        if phase is None:
            return "moon-new"
        # 8 phases, each covering ~0.0625 of the cycle centered on the named phase
        if phase < 0.0625:
            return "moon-new"
        elif phase < 0.1875:
            return "moon-waxing-crescent"
        elif phase < 0.3125:
            return "moon-first-quarter"
        elif phase < 0.4375:
            return "moon-waxing-gibbous"
        elif phase < 0.5625:
            return "moon-full"
        elif phase < 0.6875:
            return "moon-waning-gibbous"
        elif phase < 0.8125:
            return "moon-last-quarter"
        elif phase < 0.9375:
            return "moon-waning-crescent"
        else:
            return "moon-new"

    def _format_unix_time(self, ts, offset=0):
        """Format a unix timestamp to local time string like '6:42a'."""
        if not ts:
            return "---"
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(seconds=offset)))
        h = dt.hour
        m = dt.minute
        ampm = "a" if h < 12 else "p"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{ampm}"

    def _truncate_to_width(self, draw, text, font, max_w):
        """Trim trailing characters until `text` fits within `max_w` pixels."""
        if max_w <= 0:
            return ""
        while text and draw.textlength(text, font=font) > max_w:
            text = text[:-1]
        return text

    def _almanac_layout(self, draw, width, height, text_x, phase_name, show_pct):
        """Choose fonts and row positions for the almanac page so nothing
        overflows the panel or collides with the illumination %.

        The 8px title font is wide (PressStart2P): a name like "Wax Gibbous"
        is 88px, which doesn't fit the ~94px text column next to a right-aligned
        %, and longer names run clean off a 128-wide panel. Short panels also
        can't stack a 9px title plus three 7px rows in 32px of height. This
        sizes both axes to the actual panel.

        Returns a dict with `title_font`, `title_text` (fitted), `pct_font`,
        and `rows` — a list of four y-positions (title, sun, moon, day) where
        an entry is None if that row would spill past the bottom edge.
        """
        title_font = self.display_manager.small_font        # 8px PressStart2P
        body_font = self.display_manager.extra_small_font   # 6px 4x6
        title_h, body_h = 8, 6

        col_w = width - text_x
        pct_w = (int(draw.textlength("100%", font=body_font)) + 2) if show_pct else 0
        name_budget = col_w - pct_w

        # Prefer the bold 8px title, but drop to the 6px font when the name
        # (with room reserved for the %) won't fit, or when the panel is too
        # short to spare the extra height. Truncate as a last resort.
        compact = height < 40
        if compact or draw.textlength(phase_name, font=title_font) > name_budget:
            title_font = body_font
            title_h = body_h
        title_text = self._truncate_to_width(draw, phase_name, title_font, name_budget)

        # Stack rows top-down, dropping any that would spill past the bottom.
        row_gap = 1 if compact else 2
        rows = []
        y = 1 if compact else 2
        for h in (title_h, body_h, body_h, body_h):
            if y + h <= height:
                rows.append(y)
                y += h + row_gap
            else:
                rows.append(None)

        return {
            "title_font": title_font,
            "title_text": title_text,
            "pct_font": body_font,
            "rows": rows,
        }

    def _display_almanac(self) -> None:
        """Display almanac: sunrise/sunset, moon phase, day length."""
        try:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            img = Image.new('RGB', (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            font_sm = self.display_manager.extra_small_font  # 6px - secondary rows
            tz_offset = self.weather_data.get('timezone_offset', 0) if self.weather_data else 0
            sun = self.weather_data.get('sun', {}) if self.weather_data else {}
            moon = self.weather_data.get('moon', {}) if self.weather_data else {}

            sunrise_ts = sun.get('sunrise')
            sunset_ts = sun.get('sunset')
            moonrise_ts = moon.get('moonrise')
            moonset_ts = moon.get('moonset')
            moon_phase = moon.get('phase')

            sunrise = self._format_unix_time(sunrise_ts, tz_offset)
            sunset = self._format_unix_time(sunset_ts, tz_offset)
            moonrise = self._format_unix_time(moonrise_ts, tz_offset)
            moonset = self._format_unix_time(moonset_ts, tz_offset)
            phase_name = self._get_moon_phase_name(moon_phase)

            # Day length
            day_len = ""
            if sunrise_ts and sunset_ts:
                diff = sunset_ts - sunrise_ts
                dh = int(diff // 3600)
                dm = int((diff % 3600) // 60)
                day_len = f"{dh}h{dm}m"

            # Moon phase icon (left side) — use most of the height
            moon_icon_code = self._get_moon_icon_code(moon_phase)
            icon_size = height - 6

            try:
                moon_icon = WeatherIcons.load_weather_icon(moon_icon_code, icon_size)
                if moon_icon:
                    iy = (height - moon_icon.height) // 2
                    img.paste(moon_icon, (2, iy), moon_icon)
            except Exception:
                pass

            # Text area starts after the icon
            text_x = icon_size + 8
            col_w = width - text_x

            # Size fonts and rows to the actual panel so nothing overflows the
            # edge or collides with the illumination %.
            layout = self._almanac_layout(
                draw, width, height, text_x, phase_name, moon_phase is not None)
            rows = layout["rows"]
            pct_font = layout["pct_font"]

            def draw_pair(y, left, left_fill, right, right_fill):
                """Left-aligned + right-aligned text on one row, each clamped to
                the text column so neither bleeds off-panel."""
                draw.text((text_x, y), self._truncate_to_width(draw, left, font_sm, col_w),
                          font=font_sm, fill=left_fill)
                right = self._truncate_to_width(draw, right, font_sm, col_w)
                rx = max(text_x, width - draw.textlength(right, font=font_sm) - 2)
                draw.text((rx, y), right, font=font_sm, fill=right_fill)

            # Row 1: Phase name (+ illumination %)
            if rows[0] is not None:
                draw.text((text_x, rows[0]), layout["title_text"],
                          font=layout["title_font"], fill=(200, 200, 255))
                if moon_phase is not None:
                    pct = f"{int(moon_phase * 100)}%"
                    pct_w = draw.textlength(pct, font=pct_font)
                    draw.text((width - pct_w - 2, rows[0]), pct,
                              font=pct_font, fill=(140, 140, 180))

            # Row 2: Sunrise / Sunset
            if rows[1] is not None:
                draw_pair(rows[1], f"Rise {sunrise}", (255, 200, 0),
                          f"Set {sunset}", (255, 120, 50))

            # Row 3: Moonrise / Moonset
            if rows[2] is not None:
                draw_pair(rows[2], f"MR {moonrise}", (180, 180, 220),
                          f"MS {moonset}", (140, 140, 180))

            # Row 4: Day length
            if day_len and rows[3] is not None:
                draw.text((text_x, rows[3]), f"Day {day_len}", font=font_sm,
                          fill=self.COLORS['dim'])

            self.display_manager.image = img
            self.display_manager.update_display()
        except Exception:
            self.logger.exception("Error displaying almanac")

    # --- Radar Display Mode ---

    def _display_radar(self) -> None:
        """Display animated radar imagery composited over map background.

        Radar tile fetching is handled by _update_radar() in the update loop.
        This method only composites and displays cached frames.
        """
        try:
            self._ensure_radar_fetcher()
            if not hasattr(self, '_radar_fetcher'):
                self._display_no_data()
                return

            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            img = self._radar_fetcher.get_radar_image(width, height)

            if img:
                self.display_manager.image = img
                self.display_manager.update_display()
            else:
                self._display_no_data()
        except Exception:
            self.logger.exception("Error displaying radar")
            self._display_no_data()

    # --- Weather Alerts Display ---

    def _display_alerts(self) -> None:
        """Display active weather alerts if any."""
        try:
            alerts = []
            if self.weather_data:
                alerts = self.weather_data.get('alerts', [])
            if not alerts:
                return  # No alerts — skip silently

            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            img = Image.new('RGB', (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            font = self.display_manager.extra_small_font
            font_h = 7
            alert = alerts[0]  # Show first alert

            event = alert.get('event', 'Weather Alert')
            sender = alert.get('sender_name', '')
            description = alert.get('description', '')

            y = 1
            # Row 1: Alert type in red/yellow
            draw.text((2, y), event[:30], font=font, fill=(255, 80, 0))
            y += font_h + 1

            # Row 2: Sender
            if sender:
                draw.text((2, y), sender[:30], font=font, fill=(200, 200, 200))
                y += font_h + 1

            # Row 3+: Description (truncated to fit)
            if description:
                desc_short = description.replace('\n', ' ')[:60]
                draw.text((2, y), desc_short, font=font, fill=(180, 180, 180))

            self.display_manager.image = img
            self.display_manager.update_display()
        except Exception:
            self.logger.exception("Error displaying alerts")

    def has_live_content(self) -> bool:
        """Return True if there are active severe weather alerts."""
        if not self.show_alerts or not self.weather_data:
            return False
        alerts = self.weather_data.get('alerts', [])
        return len(alerts) > 0

    def get_vegas_content(self):
        """Return images for all enabled weather display modes."""
        if not self.weather_data:
            return None

        images = []

        if self.show_current:
            img = self._render_current_weather_image()
            if img:
                images.append(img)

        if self.show_hourly and self.hourly_forecast:
            img = self._render_hourly_forecast_image()
            if img:
                images.append(img)

        if self.show_daily and self.daily_forecast:
            img = self._render_daily_forecast_image()
            if img:
                images.append(img)

        if images:
            total_width = sum(img.width for img in images)
            self.logger.info(
                "[Weather Vegas] Returning %d image(s), %dpx total",
                len(images), total_width
            )
            return images

        return None

    def display_weather(self, force_clear: bool = False) -> None:
        """Display current weather (compatibility method for display controller)."""
        self.display(force_clear=force_clear, display_mode='weather')

    def display_hourly_forecast(self, force_clear: bool = False) -> None:
        """Display hourly forecast (compatibility method for display controller)."""
        self.display(force_clear=force_clear, display_mode='hourly_forecast')

    def display_daily_forecast(self, force_clear: bool = False) -> None:
        """Display daily forecast (compatibility method for display controller)."""
        self.display(force_clear=force_clear, display_mode='daily_forecast')

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'location': self.location,
            'units': self.units,
            'last_update': self.last_update,
            'current_temp': self.weather_data.get('main', {}).get('temp') if self.weather_data else None,
            'current_humidity': self.weather_data.get('main', {}).get('humidity') if self.weather_data else None,
            'current_description': self.weather_data.get('weather', [{}])[0].get('description', '') if self.weather_data else '',
            'forecast_available': bool(self.forecast_data),
            'daily_forecast_count': len(self.daily_forecast) if hasattr(self, 'daily_forecast') and self.daily_forecast is not None else 0,
            'hourly_forecast_count': len(self.hourly_forecast) if hasattr(self, 'hourly_forecast') and self.hourly_forecast is not None else 0
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.weather_data = None
        self.forecast_data = None
        self.logger.info("Weather plugin cleaned up")

