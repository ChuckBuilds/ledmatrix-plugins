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
# 4x6-font is crisp only at multiples of 7 (its pixel grid, #480); at 6 the
# FreeType rasteriser anti-aliases to fake in-between stroke widths.
# render_preview.py loads the same face at the same size.
FONT_SIZE = 7

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


# Mirrors config_schema.json's cities default.
DEFAULT_CITIES = [
    {"name": "New York", "lat": 40.71, "lon": -74.01, "timezone": "America/New_York"},
]


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
        # Rendered map per (width, height). Vegas captures at a different
        # width than the panel, and a single entry thrashed between the two.
        self._map_cache = {}
        # Terminator grid, shared across sizes -- it is lat/lon, not pixels.
        self._darkness = None
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
        self.show_date = bool(config.get("show_date", True))
        self.show_date_line = bool(config.get("show_date_line", True))
        self.date_line_labels = config.get("date_line_labels", "bottom")
        if self.date_line_labels not in ("top", "bottom"):
            self.date_line_labels = "bottom"

        self.cities = list(config.get("cities", DEFAULT_CITIES))[:8]
        # The sidebar is sized to the timezone list, so it follows the clock format.
        # With the clock off there is nothing to put in it, so the map goes full width.
        self._sidebar_w = (gr.sidebar_width(self.font.getlength, self.clock_format)
                           if self.show_digital_clock else 0)

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
            pass
        # A typo must not blank the clock: fall back to the LEDMatrix timezone,
        # then the host's own zone.
        fallback = self._get_global_timezone()
        if fallback and fallback != self.timezone_str:
            try:
                tz = pytz.timezone(fallback)
                self.logger.warning(
                    "Invalid timezone '%s'. Falling back to the LEDMatrix timezone '%s'.",
                    self.timezone_str, fallback,
                )
                return tz
            except Exception:
                pass
        self.logger.warning(
            "Invalid timezone '%s'. Falling back to system time.", self.timezone_str
        )
        return datetime.now().astimezone().tzinfo

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

    def get_update_interval(self):
        """Seconds between update() calls: the configured update_interval.

        The core prefers a plugin's manifest update_interval (45) over its
        config unless the plugin answers here, so the setting was read and
        never used. The core clamps the answer to at least 5 seconds; the
        schema's minimum is 15. Attribute read only: the core calls this on
        every scheduling tick.
        """
        return self.update_interval

    def update(self):
        """Recompute the terminator and re-render every panel size in use.

        The map is cached per (width, height) rather than as a single image.
        The Vegas marquee captures this plugin through the display-capture
        fallback at a narrower width than the panel -- 153px against 512px on
        the rig this was measured on -- and the old single-entry cache
        mismatched on every switch. display() then re-rendered inline, which
        for a capture means on the render thread: 105ms recomputing a
        terminator that does not depend on size at all, plus ~150ms rendering
        the map, roughly 290ms of stalled marquee every time round.

        Re-rendering the sizes here, on the update worker, means the render
        thread finds a warm entry and pays nothing. The terminator is computed
        once and shared across sizes, since it is a lat/lon grid.
        """
        try:
            now_utc = datetime.now(timezone.utc)
            darkness, sub_lat, sub_lon = solar.compute_terminator(
                now_utc, worldmap.GRID_W, worldmap.GRID_H, show_bands=self.show_terminator_bands
            )
            self._subsolar_lat = sub_lat
            self._subsolar_lon = sub_lon
            self._last_update_utc = now_utc
            self._darkness = darkness

            # Whatever sizes have been asked for so far, plus the live panel.
            # Copy first: display() inserts a newly-seen size from the render
            # thread, and iterating the live dict could catch it mid-write.
            sizes = set(self._map_cache.copy())
            sizes.add((self.display_manager.width, self.display_manager.height))
            for size in sizes:
                self._render_for_size(size, darkness)
        except Exception as e:
            self.logger.error("Error updating geochron: %s", e, exc_info=True)

    def _render_for_size(self, size, darkness):
        """Render and cache the map for one panel size."""
        dw, dh = size
        layout = gr._layout(dw, dh, map_center_lon=self.map_center_longitude,
                            sidebar_w=self._sidebar_w)
        image = gr.render_map_image(
            self._base_map, darkness, layout, self.night_brightness,
            self.colors["night_tint_color"]
        )
        self._map_cache[size] = (layout, image)
        # Keep the single-entry attributes pointing at the live panel so
        # anything still reading them (get_info, tests) sees what is on screen.
        if (dw, dh) == (self.display_manager.width, self.display_manager.height):
            self._cached_layout = layout
            self._cached_map = image
        return layout, image

    def display(self, force_clear=False):
        try:
            if force_clear:
                self.display_manager.clear()

            dw = self.display_manager.width
            dh = self.display_manager.height

            cached = self._map_cache.get((dw, dh))
            if cached is None:
                # First time at this size. If the terminator has never been
                # computed there is nothing to render from, so fall back to a
                # full update; otherwise reuse it and render just this size.
                if self._darkness is None:
                    self.update()
                    cached = self._map_cache.get((dw, dh))
                else:
                    cached = self._render_for_size((dw, dh), self._darkness)

            if cached is None:
                return
            layout, map_image = cached

            self.display_manager.image.paste(map_image, (layout["map_x"], layout["map_y"]))
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
            if self.show_digital_clock or self.show_date_line:
                self._draw_readout(draw, layout)

            self.display_manager.update_display()
        except Exception as e:
            self.logger.error("Error displaying geochron: %s", e, exc_info=True)

    def _zones(self, now_utc):
        """Local zone plus every configured city that names a timezone."""
        local_dt = now_utc.astimezone(self.timezone) if self.timezone else None
        cities = []
        for city in self.cities:
            tz_name = city.get("timezone")
            # No zone, or a typo: the city is still a dot, just not a row.
            if not tz_name or tz_name not in pytz.all_timezones_set:
                continue
            city_dt = now_utc.astimezone(pytz.timezone(tz_name))
            cities.append({"label": gr.city_label(city), "local_dt": city_dt, "tz": tz_name})
        local_name = getattr(self.timezone, "zone", None) or self.timezone_str
        return gr.build_zones(local_dt, local_name, cities, self.clock_format)

    def _draw_readout(self, draw, layout):
        """The midnight line and the timezone list, both from one clock read."""
        now_utc = datetime.now(timezone.utc)
        readout = None
        if self.show_digital_clock:
            date_text = None
            if self.show_date and layout.get("sidebar_w"):
                local_dt = now_utc.astimezone(self.timezone) if self.timezone else now_utc
                date_text = gr.sidebar_date(local_dt, self.font.getlength, layout["sidebar_w"] - 4)
            readout = gr.build_readout(layout, now_utc, self._zones(now_utc), date_text=date_text)
        if self.show_date_line:
            # Drawn first so the corner readout sits on top; the weekdays keep
            # clear of it rather than hiding under it.
            avoid = gr.readout_box(draw, readout, self.font) if readout else None
            gr.draw_date_line(draw, layout, now_utc, self.font,
                              self.colors["sun_marker_color"], self.colors["text_primary_color"],
                              self.date_line_labels, avoid)
        if readout is not None:
            gr.draw_readout(draw, readout, self.font,
                            self.colors["text_primary_color"], self.colors["text_secondary_color"])

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

        # A bad timezone string is not fatal: _get_timezone() already warned and
        # fell back. Failing here made core refuse to load the plugin.
        try:
            pytz.timezone(self.timezone_str)
        except Exception:
            self.logger.warning("Invalid timezone '%s'; using the fallback zone", self.timezone_str)

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
                    # The readout skips a city whose zone does not resolve.
                    self.logger.warning("Invalid city timezone: %s", tz_name)

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
