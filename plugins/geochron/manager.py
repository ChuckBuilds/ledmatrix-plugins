"""Geochron World Clock plugin.

Renders a real-time world map with a live day/night terminator (with
civil/nautical/astronomical twilight bands), the subsolar point, configurable
city markers, a lat/lon graticule, and a digital clock readout. Layout adapts
to the panel's aspect ratio - see geochron_renderer._layout().
"""

import os
from datetime import datetime, timezone

import pytz
from PIL import ImageFont

from src.plugin_system.base_plugin import BasePlugin

import geochron_renderer as gr
import solar
import worldmap

FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "fonts", "4x6-font.ttf")
FONT_SIZE = 6

DEFAULT_COLORS = {
    "ocean_color": (10, 35, 90),
    "land_color": (40, 110, 50),
    "coastline_color": (90, 160, 100),
    "night_tint_color": (10, 10, 40),
    "sun_marker_color": (255, 220, 0),
    "city_marker_color": (255, 60, 60),
    "grid_color": (70, 70, 70),
    "text_primary_color": (255, 255, 255),
    "text_secondary_color": (180, 180, 180),
}

BASE_MAP_COLORS = ("ocean_color", "land_color", "coastline_color")


def _load_font():
    try:
        return ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except OSError:
        return ImageFont.load_default()


class GeochronPlugin(BasePlugin):
    """Real-time Geochron-style world map clock."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.font = _load_font()

        self._cached_map = None
        self._cached_layout = None
        self._subsolar_lat = 0.0
        self._subsolar_lon = 0.0
        self._last_update_utc = None

        self._load_config()
        self._render_base_map()

    # ------------------------------------------------------------------
    # Config handling
    # ------------------------------------------------------------------

    def _rgb(self, colors_cfg, key):
        default = DEFAULT_COLORS[key]
        value = colors_cfg.get(key, default)
        try:
            rgb = tuple(max(0, min(255, int(c))) for c in value)
            return rgb if len(rgb) == 3 else default
        except (TypeError, ValueError):
            return default

    def _load_config(self):
        config = self.config

        self.update_interval = int(config.get("update_interval", 45))
        self.show_terminator_bands = bool(config.get("show_terminator_bands", True))
        self.night_brightness = float(config.get("night_brightness", 0.20))
        self.show_grid = bool(config.get("show_grid", True))
        self.graticule_step_deg = int(config.get("graticule_step_deg", 30))
        self.show_sun_marker = bool(config.get("show_sun_marker", True))
        self.show_cities = bool(config.get("show_cities", True))
        self.show_digital_clock = bool(config.get("show_digital_clock", True))
        self.clock_format = config.get("clock_format", "24h")
        self.show_seconds = bool(config.get("show_seconds", True))

        self.cities = list(config.get("cities", []))[:8]

        colors_cfg = config.get("colors", {}) or {}
        self.colors = {key: self._rgb(colors_cfg, key) for key in DEFAULT_COLORS}

        plugin_timezone = config.get("timezone")
        self.timezone_str = plugin_timezone if plugin_timezone else (self._get_global_timezone() or "UTC")
        self.timezone = self._get_timezone()

        map_center = config.get("map_center_longitude")
        raw_center = float(map_center) if map_center is not None else self._derive_map_center_longitude()
        self.map_center_longitude = ((raw_center + 180.0) % 360.0) - 180.0

    def _get_global_timezone(self):
        try:
            if hasattr(self.plugin_manager, "config_manager") and self.plugin_manager.config_manager:
                return self.plugin_manager.config_manager.get_timezone()
            if hasattr(self.cache_manager, "config_manager") and self.cache_manager.config_manager:
                return self.cache_manager.config_manager.get_timezone()
        except Exception as e:
            self.logger.warning("Error getting global timezone: %s", e)
        return "UTC"

    def _get_timezone(self):
        try:
            return pytz.timezone(self.timezone_str)
        except Exception:
            self.logger.warning(
                "Invalid timezone '%s'. Falling back to UTC.", self.timezone_str
            )
            return pytz.utc

    def _derive_map_center_longitude(self):
        try:
            now_utc = datetime.now(timezone.utc)
            local_now = now_utc.astimezone(self.timezone)
            offset_hours = local_now.utcoffset().total_seconds() / 3600.0
            return max(-180.0, min(180.0, offset_hours * 15.0))
        except Exception:
            return 0.0

    def _render_base_map(self):
        self._base_map = worldmap.render_base_map(
            self.colors["ocean_color"],
            self.colors["land_color"],
            self.colors["coastline_color"],
        )

    # ------------------------------------------------------------------
    # BasePlugin hooks
    # ------------------------------------------------------------------

    def update(self):
        try:
            now_utc = datetime.now(timezone.utc)
            darkness, sub_lat, sub_lon = solar.compute_terminator(
                now_utc, worldmap.GRID_W, worldmap.GRID_H, show_bands=self.show_terminator_bands
            )
            self._subsolar_lat = sub_lat
            self._subsolar_lon = sub_lon
            self._last_update_utc = now_utc

            dw = self.display_manager.width
            dh = self.display_manager.height
            layout = gr._layout(dw, dh, map_center_lon=self.map_center_longitude)
            self._cached_layout = layout
            self._cached_map = gr.render_map_image(
                self._base_map, darkness, layout, self.night_brightness, self.colors["night_tint_color"]
            )
        except Exception as e:
            self.logger.error("Error updating geochron: %s", e, exc_info=True)

    def display(self, force_clear=False):
        try:
            if force_clear:
                self.display_manager.clear()

            dw = self.display_manager.width
            dh = self.display_manager.height

            layout = self._cached_layout
            if (
                layout is None
                or self._cached_map is None
                or layout["dw"] != dw
                or layout["dh"] != dh
            ):
                self.update()
                layout = self._cached_layout

            if layout is None or self._cached_map is None:
                return

            self.display_manager.image.paste(self._cached_map, (layout["map_x"], layout["map_y"]))
            draw = self.display_manager.draw

            if layout["sidebar_w"]:
                draw.rectangle(
                    [layout["sidebar_x"], 0, layout["dw"] - 1, layout["dh"] - 1],
                    fill=(10, 10, 10),
                )

            if self.show_grid:
                gr.draw_graticule(draw, layout, self.graticule_step_deg, self.colors["grid_color"])
            if self.show_sun_marker:
                gr.draw_sun_marker(draw, layout, self._subsolar_lat, self._subsolar_lon, self.colors["sun_marker_color"])
            if self.show_cities:
                gr.draw_cities(draw, layout, self.cities, self.colors["city_marker_color"])
            if self.show_digital_clock:
                self._draw_readout(draw, layout)

            self.display_manager.update_display()
        except Exception as e:
            self.logger.error("Error displaying geochron: %s", e, exc_info=True)

    def _draw_readout(self, draw, layout):
        now_utc = datetime.now(timezone.utc)
        local_dt = now_utc.astimezone(self.timezone) if self.timezone else None

        featured_city = None
        if self.cities:
            city = self.cities[0]
            tz_name = city.get("timezone")
            if tz_name:
                try:
                    city_tz = pytz.timezone(tz_name)
                    featured_city = {
                        "name": city.get("name", ""),
                        "local_dt": now_utc.astimezone(city_tz),
                    }
                except Exception:
                    featured_city = None

        readout = gr.build_readout(
            layout, now_utc, local_dt, self._subsolar_lat, self._subsolar_lon,
            featured_city, self.clock_format, self.show_seconds,
        )

        primary = self.colors["text_primary_color"]
        secondary = self.colors["text_secondary_color"]

        if readout["mode"] == "sidebar":
            x, y = readout["anchor"]
            for text, color_key in readout["rows"]:
                color = primary if color_key == "primary" else secondary
                draw.text((x, y), text, fill=color, font=self.font)
                y += readout["row_h"]
            return

        x, y = readout["anchor"]
        n = len(readout["rows"])
        max_w = max((draw.textlength(t, font=self.font) for t, _ in readout["rows"]), default=0)
        box_top = y - n * readout["row_h"]
        draw.rectangle([0, box_top, max_w + 2, layout["dh"] - 1], fill=(10, 10, 10))
        ty = box_top + 1
        for text, color_key in readout["rows"]:
            color = primary if color_key == "primary" else secondary
            draw.text((x, ty), text, fill=color, font=self.font)
            ty += readout["row_h"]

    def on_config_change(self, new_config):
        old_colors = getattr(self, "colors", None)
        super().on_config_change(new_config)
        self._load_config()

        if old_colors is None or any(self.colors[k] != old_colors[k] for k in BASE_MAP_COLORS):
            self._render_base_map()

        self.update()

    def validate_config(self):
        if not super().validate_config():
            return False

        try:
            pytz.timezone(self.timezone_str)
        except Exception:
            self.logger.error("Invalid timezone: %s", self.timezone_str)
            return False

        if self.clock_format not in ("12h", "24h"):
            self.logger.error("Invalid clock_format: %s", self.clock_format)
            return False

        if self.graticule_step_deg not in (15, 30, 45, 90):
            self.logger.error("Invalid graticule_step_deg: %s", self.graticule_step_deg)
            return False

        for city in self.cities:
            lat, lon = city.get("lat"), city.get("lon")
            if not isinstance(lat, (int, float)) or not (-90 <= lat <= 90):
                self.logger.error("Invalid city latitude: %s", city)
                return False
            if not isinstance(lon, (int, float)) or not (-180 <= lon <= 180):
                self.logger.error("Invalid city longitude: %s", city)
                return False
            tz_name = city.get("timezone")
            if tz_name:
                try:
                    pytz.timezone(tz_name)
                except Exception:
                    self.logger.error("Invalid city timezone: %s", tz_name)
                    return False

        for key, value in self.colors.items():
            if not (isinstance(value, tuple) and len(value) == 3 and all(0 <= c <= 255 for c in value)):
                self.logger.error("Invalid color %s: %s", key, value)
                return False

        return True

    def get_info(self):
        info = super().get_info()
        info.update({
            "subsolar_lat": self._subsolar_lat,
            "subsolar_lon": self._subsolar_lon,
            "last_update_utc": self._last_update_utc.isoformat() if self._last_update_utc else None,
            "map_center_longitude": self.map_center_longitude,
            "timezone": self.timezone_str,
        })
        return info
