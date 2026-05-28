"""
Weather Icons Module for Weather Plugin

Handles loading and drawing weather icons from PNG files in assets/weather/.
Maps OWM-style icon codes (e.g. '01d', '10n') and WMO weather codes to icon files.
"""

import math
import logging
from pathlib import Path
from typing import Union
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class WeatherIcons:
    _PLUGIN_ICON_DIR = Path(__file__).resolve().parent / "assets" / "weather"
    _ROOT_ICON_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "weather"
    ICON_PATHS = [_PLUGIN_ICON_DIR, _ROOT_ICON_DIR]
    ICON_DIR = str(_PLUGIN_ICON_DIR)  # Maintained for backward compatibility
    DEFAULT_ICON = "not-available.png"
    DEFAULT_SIZE = 64  # Default size, should match icons but can be overridden

    # Mapping from OpenWeatherMap icon codes to our filenames
    # See: https://openweathermap.org/weather-conditions#Icon-list
    ICON_MAP = {
        # Day icons
        "01d": "clear-day.png",
        "02d": "partly-cloudy-day.png",  # Few clouds
        "03d": "cloudy.png",             # Scattered clouds
        "04d": "overcast-day.png",       # Broken clouds / Overcast
        "09d": "drizzle.png",            # Shower rain (using drizzle)
        "10d": "partly-cloudy-day-rain.png", # Rain
        "11d": "thunderstorms-day.png",  # Thunderstorm
        "13d": "partly-cloudy-day-snow.png", # Snow
        "50d": "mist.png",               # Mist (can use fog, haze etc. too)

        # Night icons
        "01n": "clear-night.png",
        "02n": "partly-cloudy-night.png",# Few clouds
        "03n": "cloudy.png",             # Scattered clouds (same as day)
        "04n": "overcast-night.png",     # Broken clouds / Overcast
        "09n": "drizzle.png",            # Shower rain (using drizzle, same as day)
        "10n": "partly-cloudy-night-rain.png", # Rain
        "11n": "thunderstorms-night.png", # Thunderstorm
        "13n": "partly-cloudy-night-snow.png", # Snow
        "50n": "mist.png",               # Mist (same as day)

        # Add mappings for specific conditions if needed, although OWM codes are preferred
        "tornado": "tornado.png",
        "hurricane": "hurricane.png",
        "wind": "wind.png", # Generic wind if code is not specific enough

        # Moon phase icons (used by almanac display)
        "moon-new": "moon-new.png",
        "moon-waxing-crescent": "moon-waxing-crescent.png",
        "moon-first-quarter": "moon-first-quarter.png",
        "moon-waxing-gibbous": "moon-waxing-gibbous.png",
        "moon-full": "moon-full.png",
        "moon-waning-gibbous": "moon-waning-gibbous.png",
        "moon-last-quarter": "moon-last-quarter.png",
        "moon-waning-crescent": "moon-waning-crescent.png",
    }

    # WMO weather interpretation codes → OWM-style icon keys
    # https://open-meteo.com/en/docs#weathervariables
    _WMO_DAY_MAP = {
        0: "01d", 1: "02d", 2: "03d", 3: "04d",
        45: "50d", 48: "50d",
        51: "09d", 53: "09d", 55: "09d", 56: "09d", 57: "09d",
        61: "10d", 63: "10d", 65: "10d", 66: "13d", 67: "13d",
        71: "13d", 73: "13d", 75: "13d", 77: "13d",
        80: "10d", 81: "10d", 82: "10d", 85: "13d", 86: "13d",
        95: "11d", 96: "11d", 99: "11d",
    }
    _WMO_NIGHT_MAP = {
        0: "01n", 1: "02n", 2: "03n", 3: "04n",
        45: "50n", 48: "50n",
        51: "09n", 53: "09n", 55: "09n", 56: "09n", 57: "09n",
        61: "10n", 63: "10n", 65: "10n", 66: "13n", 67: "13n",
        71: "13n", 73: "13n", 75: "13n", 77: "13n",
        80: "10n", 81: "10n", 82: "10n", 85: "13n", 86: "13n",
        95: "11n", 96: "11n", 99: "11n",
    }
    _WMO_CONDITION_MAP = {
        0: "Clear", 1: "Clear", 2: "Partly Cloudy", 3: "Overcast",
        45: "Fog", 48: "Fog",
        51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Drizzle", 57: "Drizzle",
        61: "Rain", 63: "Rain", 65: "Rain", 66: "Rain", 67: "Rain",
        71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
        80: "Showers", 81: "Showers", 82: "Showers",
        85: "Snow Showers", 86: "Snow Showers",
        95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
    }

    @classmethod
    def wmo_to_icon_code(cls, wmo_code: int, is_day: bool = True) -> str:
        """Convert a WMO weather code to an OWM-style icon code."""
        mapping = cls._WMO_DAY_MAP if is_day else cls._WMO_NIGHT_MAP
        return mapping.get(wmo_code, "01d" if is_day else "01n")

    @classmethod
    def wmo_to_condition(cls, wmo_code: int) -> str:
        """Convert a WMO weather code to a human-readable condition string."""
        return cls._WMO_CONDITION_MAP.get(wmo_code, "Unknown")

    @classmethod
    def _resolve_icon_path(cls, filename: str) -> Union[Path, None]:
        """Resolve the full path for an icon by checking known asset directories."""
        for base_path in cls.ICON_PATHS:
            if base_path and base_path.exists():
                candidate = base_path / filename
                if candidate.exists():
                    return candidate
        return None

    @classmethod
    def _get_icon_filename(cls, icon_code: str) -> str:
        """Maps an OpenWeatherMap icon code (e.g., '01d', '10n') to an icon filename."""
        filename = cls.ICON_MAP.get(icon_code, cls.DEFAULT_ICON)
        logger.debug(f"Mapping icon code '{icon_code}' to filename: '{filename}'")

        # Check if the mapped filename exists, otherwise use default
        potential_path = cls._resolve_icon_path(filename)
        if not potential_path:
            # If a specific icon was determined but not found, log warning and use default
            if filename != cls.DEFAULT_ICON:
                logger.warning(f"Mapped icon file '{filename}' not found in any icon directory. Falling back to default.")
                filename = cls.DEFAULT_ICON
            
            # Check if default exists
            default_path = cls._resolve_icon_path(cls.DEFAULT_ICON)
            if not default_path:
                logger.error("Default weather icon file not found in any icon directory")
                # Allow filename to remain DEFAULT_ICON name, load_weather_icon handles FileNotFoundError

        return filename

    @staticmethod
    def load_weather_icon(icon_code: str, size: int = DEFAULT_SIZE) -> Union[Image.Image, None]:
        """Loads, converts, and resizes the appropriate weather icon based on the OWM code. Returns None on failure."""
        filename = WeatherIcons._get_icon_filename(icon_code)
        icon_path_obj = WeatherIcons._resolve_icon_path(filename)
        if not icon_path_obj:
            logger.error(f"Unable to resolve path for weather icon '{filename}'")
            return None

        icon_path = str(icon_path_obj)

        try:
            # Open image and ensure it's RGBA for transparency handling
            icon_img = Image.open(icon_path).convert("RGBA")

            # Resize if necessary using high-quality downsampling (LANCZOS/ANTIALIAS)
            if icon_img.width != size or icon_img.height != size:
                icon_img = icon_img.resize((size, size), Image.Resampling.LANCZOS)

            return icon_img
        except FileNotFoundError:
            logger.error(f"Icon file not found: {icon_path}")
            # Don't try to load default here, _get_icon_filename already handled fallback logic
            return None
        except Exception as e:
            logger.error(f"Error processing icon {icon_path}: {e}")
            return None

    @staticmethod
    def draw_weather_icon(image: Image.Image, icon_code: str, x: int, y: int, size: int = DEFAULT_SIZE):
        """Loads the appropriate weather icon based on OWM code and pastes it onto the target PIL Image object."""
        icon_to_draw = WeatherIcons.load_weather_icon(icon_code, size)
        if icon_to_draw:
            try:
                # Paste the icon directly with its original alpha channel
                image.paste(icon_to_draw, (x, y), icon_to_draw)
            except Exception as e:
                logger.error(f"Error processing or pasting icon for code '{icon_code}' at ({x},{y}): {e}")
        else:
            logger.warning(f"Could not load icon for code '{icon_code}' to draw at ({x},{y})")

    # The following drawing methods are provided for fallback/programmatic icon generation
    # They are not currently used by the plugin but may be useful for future enhancements
    
    @staticmethod
    def draw_sun(draw: ImageDraw, x: int, y: int, size: int = 16, color: tuple = (255, 200, 0)):
        """Draw a sun icon with rays."""
        center_x = x + size // 2
        center_y = y + size // 2
        radius = size // 3
        
        # Draw main sun circle
        draw.ellipse([
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius
        ], fill=color)
        
        # Draw rays
        ray_length = size // 4
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            start_x = center_x + (radius * math.cos(rad))
            start_y = center_y + (radius * math.sin(rad))
            end_x = center_x + ((radius + ray_length) * math.cos(rad))
            end_y = center_y + ((radius + ray_length) * math.sin(rad))
            draw.line([start_x, start_y, end_x, end_y], fill=color, width=2)

    @staticmethod
    def draw_cloud(draw: ImageDraw, x: int, y: int, size: int = 16, color: tuple = (200, 200, 200)):
        """Draw a cloud icon."""
        # Draw multiple circles to form cloud shape
        circle_size = size // 2
        positions = [
            (x + size//4, y + size//3),
            (x + size//2, y + size//3),
            (x + size//3, y + size//6)
        ]
        
        for pos_x, pos_y in positions:
            draw.ellipse([
                pos_x, pos_y,
                pos_x + circle_size, pos_y + circle_size
            ], fill=color)

    @staticmethod
    def draw_rain(draw: ImageDraw, x: int, y: int, size: int = 16):
        """Draw rain icon with cloud and droplets."""
        # Draw cloud first
        WeatherIcons.draw_cloud(draw, x, y, size)
        
        # Draw rain drops
        drop_color = (0, 150, 255)  # Light blue
        drop_length = size // 3
        drop_spacing = size // 4
        
        for i in range(3):
            drop_x = x + size//4 + (i * drop_spacing)
            drop_y = y + size//2
            draw.line([
                drop_x, drop_y,
                drop_x - 2, drop_y + drop_length
            ], fill=drop_color, width=2)

    @staticmethod
    def draw_snow(draw: ImageDraw, x: int, y: int, size: int = 16):
        """Draw snow icon with cloud and snowflakes."""
        # Draw cloud first
        WeatherIcons.draw_cloud(draw, x, y, size)
        
        # Draw snowflakes
        snow_color = (200, 200, 255)  # Light blue-white
        flake_size = size // 6
        flake_spacing = size // 4
        
        for i in range(3):
            center_x = x + size//4 + (i * flake_spacing)
            center_y = y + size//2
            
            # Draw 6-point snowflake
            for angle in range(0, 360, 60):
                rad = math.radians(angle)
                end_x = center_x + (flake_size * math.cos(rad))
                end_y = center_y + (flake_size * math.sin(rad))
                draw.line([center_x, center_y, end_x, end_y], fill=snow_color, width=1)

    @staticmethod
    def draw_thunderstorm(draw: ImageDraw, x: int, y: int, size: int = 16):
        """Draw thunderstorm icon with cloud and lightning."""
        # Draw dark cloud
        WeatherIcons.draw_cloud(draw, x, y, size, color=(100, 100, 100))
        
        # Draw lightning bolt
        lightning_color = (255, 255, 0)  # Yellow
        bolt_points = [
            (x + size//2, y + size//3),
            (x + size//2 - size//4, y + size//2),
            (x + size//2, y + size//2),
            (x + size//2 - size//4, y + size//2 + size//4)
        ]
        draw.line(bolt_points, fill=lightning_color, width=2)

    @staticmethod
    def draw_mist(draw: ImageDraw, x: int, y: int, size: int = 16):
        """Draw mist/fog icon."""
        mist_color = (200, 200, 200)  # Light gray
        wave_height = size // 4
        wave_spacing = size // 3
        
        for i in range(3):
            wave_y = y + size//3 + (i * wave_spacing)
            draw.line([
                x + size//4, wave_y,
                x + size//4 + size//2, wave_y + wave_height
            ], fill=mist_color, width=2)

