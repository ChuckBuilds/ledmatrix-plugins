"""
Weather Plugin for LEDMatrix

Comprehensive weather display with current conditions, hourly forecast, and daily forecast.
Uses OpenWeatherMap API to provide accurate weather information with beautiful icons.

Features:
- Current weather conditions with temperature, humidity, wind speed
- Hourly forecast (next 24-48 hours)
- Daily forecast (next 7 days)
- Weather icons matching conditions
- UV index display
- Automatic error handling and retry logic

API Version: 1.0.0
"""

import logging
import requests
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class WeatherPlugin(BasePlugin):
    """
    Weather plugin that displays current conditions and forecasts.
    
    Supports three display modes:
    - weather: Current conditions
    - hourly_forecast: Hourly forecast for next 48 hours
    - daily_forecast: Daily forecast for next 7 days
    
    Configuration options:
        api_key (str): OpenWeatherMap API key
        location (dict): City, state, country for weather data
        units (str): 'imperial' (F) or 'metric' (C)
        update_interval (int): Seconds between API updates
        display_modes (dict): Enable/disable specific display modes
    """
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the weather plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Weather configuration
        self.api_key = config.get('api_key', 'YOUR_OPENWEATHERMAP_API_KEY')
        self.location = config.get('location', {})
        self.units = config.get('units', 'imperial')
        self.update_interval = config.get('update_interval', 1800)
        
        # Display modes
        self.display_modes_config = config.get('display_modes', {})
        self.show_current = self.display_modes_config.get('weather', True)
        self.show_hourly = self.display_modes_config.get('hourly_forecast', True)
        self.show_daily = self.display_modes_config.get('daily_forecast', True)
        
        # Data storage
        self.weather_data = None
        self.forecast_data = None
        self.hourly_forecast = None
        self.daily_forecast = None
        self.last_update = 0
        
        # Error handling
        self.consecutive_errors = 0
        self.last_error_time = 0
        self.error_backoff_time = 60
        self.max_consecutive_errors = 5
        
        # Layout constants
        self.PADDING = 1
        self.ICON_SIZE = {
            'extra_large': 40,
            'large': 30,
            'medium': 24,
            'small': 14
        }
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
        
        # Weather icons path
        self.icons_dir = Path('assets/weather')
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Weather plugin initialized for {self.location.get('city', 'Unknown')}")
        self.logger.info(f"Units: {self.units}, Update interval: {self.update_interval}s")
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
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
            
            self.logger.info("Weather plugin fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")
    
    def update(self) -> None:
        """
        Update weather data from OpenWeatherMap API.
        
        Fetches current conditions and forecast data, respecting
        update intervals and error backoff periods.
        """
        current_time = time.time()
        
        # Check if we need to update
        if current_time - self.last_update < self.update_interval:
            return
        
        # Check if we're in error backoff period
        if self.consecutive_errors >= self.max_consecutive_errors:
            if current_time - self.last_error_time < self.error_backoff_time:
                self.logger.debug(f"In error backoff period, retrying in {self.error_backoff_time - (current_time - self.last_error_time):.0f}s")
                return
            else:
                # Reset error count after backoff
                self.consecutive_errors = 0
                self.error_backoff_time = 60
        
        # Validate API key
        if not self.api_key or self.api_key == "YOUR_OPENWEATHERMAP_API_KEY":
            self.logger.warning("No valid OpenWeatherMap API key configured")
            return
        
        # Try to fetch weather data
        try:
            self._fetch_weather()
            self.last_update = current_time
            self.consecutive_errors = 0
        except Exception as e:
            self.logger.error(f"Error updating weather: {e}")
            self.consecutive_errors += 1
            self.last_error_time = current_time
            if self.consecutive_errors >= 3:
                self.error_backoff_time = min(self.error_backoff_time * 2, 3600)
    
    def _fetch_weather(self) -> None:
        """Fetch weather data from OpenWeatherMap API."""
        # Check cache first
        cache_key = 'weather'
        cached_data = self.cache_manager.get(cache_key)
        if cached_data:
            self.weather_data = cached_data.get('current')
            self.forecast_data = cached_data.get('forecast')
            if self.weather_data and self.forecast_data:
                self._process_forecast_data(self.forecast_data)
                self.logger.info("Using cached weather data")
                return
        
        # Fetch fresh data
        city = self.location.get('city', 'Dallas')
        state = self.location.get('state', 'Texas')
        country = self.location.get('country', 'US')
        
        # Get coordinates using geocoding API
        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},{state},{country}&limit=1&appid={self.api_key}"
        
        response = requests.get(geo_url, timeout=10)
        response.raise_for_status()
        geo_data = response.json()
        
        if not geo_data:
            self.logger.error(f"Could not find coordinates for {city}, {state}")
            return
        
        lat = geo_data[0]['lat']
        lon = geo_data[0]['lon']
        
        # Get weather data using One Call API
        one_call_url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&exclude=minutely,alerts&appid={self.api_key}&units={self.units}"
        
        response = requests.get(one_call_url, timeout=10)
        response.raise_for_status()
        one_call_data = response.json()
        
        # Store current weather data
        self.weather_data = {
            'main': {
                'temp': one_call_data['current']['temp'],
                'temp_max': one_call_data['daily'][0]['temp']['max'],
                'temp_min': one_call_data['daily'][0]['temp']['min'],
                'humidity': one_call_data['current']['humidity'],
                'pressure': one_call_data['current']['pressure'],
                'uvi': one_call_data['current'].get('uvi', 0)
            },
            'weather': one_call_data['current']['weather'],
            'wind': {
                'speed': one_call_data['current']['wind_speed']
            }
        }
        
        # Store forecast data
        self.forecast_data = one_call_data
        
        # Process forecast data
        self._process_forecast_data(self.forecast_data)
        
        # Cache the data
        self.cache_manager.set(cache_key, {
            'current': self.weather_data,
            'forecast': self.forecast_data
        })
        
        self.logger.info(f"Weather data updated for {city}: {self.weather_data['main']['temp']}°")
    
    def _process_forecast_data(self, forecast_data: Dict) -> None:
        """Process forecast data into hourly and daily lists."""
        # Process hourly forecast
        if 'hourly' in forecast_data:
            self.hourly_forecast = []
            for hour_data in forecast_data['hourly'][:24]:
                self.hourly_forecast.append({
                    'dt': hour_data['dt'],
                    'temp': hour_data['temp'],
                    'weather': hour_data['weather'][0],
                    'pop': hour_data.get('pop', 0) * 100
                })
        
        # Process daily forecast
        if 'daily' in forecast_data:
            self.daily_forecast = []
            for day_data in forecast_data['daily'][:7]:
                self.daily_forecast.append({
                    'dt': day_data['dt'],
                    'temp_max': day_data['temp']['max'],
                    'temp_min': day_data['temp']['min'],
                    'weather': day_data['weather'][0],
                    'pop': day_data.get('pop', 0) * 100
                })
    
    def display(self, display_mode: str = None) -> None:
        """
        Display weather information.
        
        Args:
            display_mode: One of 'weather', 'hourly_forecast', or 'daily_forecast'
        """
        if not self.weather_data:
            self._display_no_data()
            return
        
        # Determine which mode to display
        if display_mode == 'hourly_forecast' and self.show_hourly:
            self._display_hourly_forecast()
        elif display_mode == 'daily_forecast' and self.show_daily:
            self._display_daily_forecast()
        else:
            self._display_current_weather()
    
    def _display_no_data(self) -> None:
        """Display a message when no weather data is available."""
        img = Image.new('RGB', (self.display_manager.matrix.width, self.display_manager.matrix.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Simple text display
        from PIL import ImageFont
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "No Weather", font=font, fill=(200, 200, 200))
        draw.text((5, 20), "Data", font=font, fill=(200, 200, 200))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_current_weather(self) -> None:
        """Display current weather conditions."""
        img = Image.new('RGB', (self.display_manager.matrix.width, self.display_manager.matrix.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Load font
        from PIL import ImageFont
        try:
            font_large = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 12)
            font_small = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        # Get weather info
        temp = int(self.weather_data['main']['temp'])
        condition = self.weather_data['weather'][0]['main']
        humidity = self.weather_data['main']['humidity']
        
        # Draw temperature (large, centered)
        temp_str = f"{temp}°"
        bbox = draw.textbbox((0, 0), temp_str, font=font_large)
        temp_width = bbox[2] - bbox[0]
        x_pos = (self.display_manager.matrix.width - temp_width) // 2
        draw.text((x_pos, 2), temp_str, font=font_large, fill=self.COLORS['text'])
        
        # Draw condition (small, centered below temp)
        bbox = draw.textbbox((0, 0), condition, font=font_small)
        cond_width = bbox[2] - bbox[0]
        x_pos = (self.display_manager.matrix.width - cond_width) // 2
        draw.text((x_pos, 18), condition, font=font_small, fill=self.COLORS['highlight'])
        
        # Draw humidity (small, bottom right)
        humidity_str = f"H:{humidity}%"
        draw.text((2, self.display_manager.matrix.height - 8), humidity_str, font=font_small, fill=self.COLORS['dim'])
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_hourly_forecast(self) -> None:
        """Display hourly forecast."""
        if not self.hourly_forecast:
            self._display_no_data()
            return
        
        img = Image.new('RGB', (self.display_manager.matrix.width, self.display_manager.matrix.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Load font
        from PIL import ImageFont
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
        except:
            font = ImageFont.load_default()
        
        # Draw title
        draw.text((2, 2), "Hourly Forecast", font=font, fill=self.COLORS['highlight'])
        
        # Draw first 4 hours
        y_offset = 10
        for i, hour_data in enumerate(self.hourly_forecast[:4]):
            hour_time = datetime.fromtimestamp(hour_data['dt']).strftime('%I%p')
            temp = int(hour_data['temp'])
            
            hour_str = f"{hour_time}: {temp}°"
            draw.text((2, y_offset), hour_str, font=font, fill=self.COLORS['text'])
            y_offset += 6
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_daily_forecast(self) -> None:
        """Display daily forecast."""
        if not self.daily_forecast:
            self._display_no_data()
            return
        
        img = Image.new('RGB', (self.display_manager.matrix.width, self.display_manager.matrix.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Load font
        from PIL import ImageFont
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
        except:
            font = ImageFont.load_default()
        
        # Draw title
        draw.text((2, 2), "7-Day Forecast", font=font, fill=self.COLORS['highlight'])
        
        # Draw first 3 days
        y_offset = 10
        for i, day_data in enumerate(self.daily_forecast[:3]):
            day_name = datetime.fromtimestamp(day_data['dt']).strftime('%a')
            temp_high = int(day_data['temp_max'])
            temp_low = int(day_data['temp_min'])
            
            day_str = f"{day_name}: {temp_high}°/{temp_low}°"
            draw.text((2, y_offset), day_str, font=font, fill=self.COLORS['text'])
            y_offset += 7
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'location': self.location,
            'units': self.units,
            'api_key_configured': bool(self.api_key),
            'last_update': self.last_update,
            'current_temp': self.weather_data.get('main', {}).get('temp') if self.weather_data else None,
            'current_humidity': self.weather_data.get('main', {}).get('humidity') if self.weather_data else None,
            'current_description': self.weather_data.get('weather', [{}])[0].get('description', '') if self.weather_data else '',
            'forecast_available': bool(self.forecast_data),
            'daily_forecast_count': len(self.daily_forecast) if hasattr(self, 'daily_forecast') else 0,
            'hourly_forecast_count': len(self.hourly_forecast) if hasattr(self, 'hourly_forecast') else 0
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.weather_data = None
        self.forecast_data = None
        self.logger.info("Weather plugin cleaned up")

