"""
Radar display with WeatherStar-style vector map background.

Renders US state boundaries as colored lines on black (like the classic
Weather Channel WeatherStar 4000), then composites RainViewer precipitation
radar on top. Animated playback of the last ~2 hours of frames.

Map: GeoJSON state outlines rendered with PIL (no tile server dependency).
Radar: RainViewer API (free, worldwide, no API key).
"""

import json
import logging
import math
import os
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
_TILE_SIZE = 256

# Path to bundled GeoJSON state boundaries
_GEOJSON_PATH = os.path.join(os.path.dirname(__file__), "data", "us-states.geojson")


# ---------------------------------------------------------------------------
# Coordinate math
# ---------------------------------------------------------------------------

def _latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convert lat/lon to tile x, y at a given zoom level."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def _frac_within_tile(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Get fractional position within the tile for exact lat/lon."""
    n = 2 ** zoom
    tx, ty = _latlon_to_tile(lat, lon, zoom)
    frac_x = ((lon + 180) / 360 * n) - tx
    frac_y = ((1 - math.log(math.tan(math.radians(lat)) +
               1 / math.cos(math.radians(lat))) / math.pi) / 2 * n) - ty
    return frac_x, frac_y


def _latlon_to_pixel(lat: float, lon: float, center_lat: float, center_lon: float,
                     width: int, height: int, zoom: int) -> Tuple[int, int]:
    """Convert lat/lon to pixel position on an image centered at (center_lat, center_lon).

    Uses Web Mercator projection at the given zoom level.
    """
    n = 2 ** zoom
    # Pixels per degree at this zoom
    ppd_x = _TILE_SIZE * n / 360.0

    # Center pixel
    cx = (center_lon + 180) / 360 * _TILE_SIZE * n
    cy_center = math.radians(center_lat)
    cy = (1 - math.log(math.tan(cy_center) + 1 / math.cos(cy_center)) / math.pi) / 2 * _TILE_SIZE * n

    # Target pixel
    px = (lon + 180) / 360 * _TILE_SIZE * n
    py_rad = math.radians(lat)
    py = (1 - math.log(math.tan(py_rad) + 1 / math.cos(py_rad)) / math.pi) / 2 * _TILE_SIZE * n

    # Offset from center
    x = int((px - cx) + width / 2)
    y = int((py - cy) + height / 2)
    return x, y


# ---------------------------------------------------------------------------
# GeoJSON map renderer
# ---------------------------------------------------------------------------

def _load_geojson() -> Optional[Dict]:
    """Load US state boundaries GeoJSON."""
    if os.path.exists(_GEOJSON_PATH):
        with open(_GEOJSON_PATH, "r") as f:
            return json.load(f)
    logger.warning(f"[Radar] GeoJSON not found at {_GEOJSON_PATH}")
    return None


def render_vector_map(center_lat: float, center_lon: float, width: int, height: int,
                      zoom: int, line_color: Tuple[int, int, int] = (0, 100, 50),
                      fill_color: Optional[Tuple[int, int, int]] = (15, 20, 15)) -> Image.Image:
    """Render state boundaries as lines on a black background.

    Returns an RGB image with state outlines drawn in the WeatherStar style:
    black background (water), optional dark fill (land), colored outlines.
    """
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    geojson = _load_geojson()
    if not geojson:
        return img

    features = geojson.get("features", [])

    for feature in features:
        geom = feature.get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])

        polygons = []
        if gtype == "Polygon":
            polygons = [coords]
        elif gtype == "MultiPolygon":
            polygons = coords

        for polygon in polygons:
            for ring in polygon:
                # Convert GeoJSON [lon, lat] to pixel [x, y]
                pixel_points = []
                for coord in ring:
                    lon, lat = coord[0], coord[1]
                    px, py = _latlon_to_pixel(lat, lon, center_lat, center_lon,
                                              width, height, zoom)
                    pixel_points.append((px, py))

                if len(pixel_points) < 3:
                    continue

                # Check if any point is within a reasonable margin of the display
                margin = max(width, height)
                visible = any(-margin < x < width + margin and -margin < y < height + margin
                              for x, y in pixel_points)
                if not visible:
                    continue

                # Fill land area with subtle dark color
                if fill_color:
                    try:
                        draw.polygon(pixel_points, fill=fill_color)
                    except Exception:
                        pass

                # Draw boundary outline
                try:
                    draw.polygon(pixel_points, outline=line_color)
                except Exception:
                    pass

    return img


# ---------------------------------------------------------------------------
# Radar fetcher
# ---------------------------------------------------------------------------

class RadarFetcher:
    """Fetches radar tiles with vector map background from RainViewer + GeoJSON."""

    def __init__(self, lat: float, lon: float, zoom: int = 6,
                 cache_manager: Any = None, map_provider: str = "vector",
                 line_color: Tuple[int, int, int] = (0, 100, 50),
                 fill_color: Optional[Tuple[int, int, int]] = (15, 20, 15)):
        self.lat = lat
        self.lon = lon
        self.zoom = zoom
        self.cache = cache_manager
        self.line_color = line_color
        self.fill_color = fill_color

        self._map_bg: Optional[Image.Image] = None
        self._radar_frames: List[Image.Image] = []
        self._frame_timestamps: List[int] = []
        self._frame_index = 0
        self._last_fetch = 0.0
        self._last_frame_advance = 0.0

    def _render_map(self, width: int, height: int) -> Image.Image:
        """Render the vector map background at display resolution."""
        return render_vector_map(
            self.lat, self.lon, width, height, self.zoom,
            line_color=self.line_color, fill_color=self.fill_color,
        )

    def _fetch_radar_paths(self) -> List[Tuple[str, int]]:
        """Get available radar frame paths and timestamps from RainViewer."""
        try:
            resp = requests.get(_MAPS_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            past = data.get("radar", {}).get("past", [])
            return [(f["path"], f.get("time", 0)) for f in past if f.get("path")]
        except Exception as e:
            logger.warning(f"[Radar] RainViewer index fetch failed: {e}")
            return []

    def _fetch_radar_tile(self, path: str) -> Optional[Image.Image]:
        """Fetch a single radar tile PNG from RainViewer."""
        tx, ty = _latlon_to_tile(self.lat, self.lon, self.zoom)
        url = f"https://tilecache.rainviewer.com{path}/{_TILE_SIZE}/{self.zoom}/{tx}/{ty}/2/1_1.png"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            if resp.content[:4] != b"\x89PNG":
                return None
            return Image.open(BytesIO(resp.content)).convert("RGBA")
        except Exception as e:
            logger.debug(f"[Radar] Tile fetch failed: {e}")
            return None

    def _composite_frame(self, map_bg: Image.Image, radar: Image.Image,
                         width: int, height: int) -> Image.Image:
        """Composite radar tile over vector map, cropping to center."""
        # The radar tile is 256x256 covering one map tile.
        # Crop it centered on our location, then scale to display.
        frac_x, frac_y = _frac_within_tile(self.lat, self.lon, self.zoom)
        px = int(frac_x * _TILE_SIZE)
        py = int(frac_y * _TILE_SIZE)

        aspect = width / height
        crop_h = min(_TILE_SIZE, max(height, _TILE_SIZE // 2))
        crop_w = min(_TILE_SIZE, int(crop_h * aspect))

        left = max(0, min(_TILE_SIZE - crop_w, px - crop_w // 2))
        top = max(0, min(_TILE_SIZE - crop_h, py - crop_h // 2))

        cropped_radar = radar.crop((left, top, left + crop_w, top + crop_h))
        scaled_radar = cropped_radar.resize((width, height), Image.Resampling.LANCZOS)

        # Composite radar (RGBA) over map background (RGB)
        map_rgba = map_bg.copy().convert("RGBA")
        composite = Image.alpha_composite(map_rgba, scaled_radar)
        return composite.convert("RGB")

    def _add_overlay(self, img: Image.Image, frame_num: int = 0,
                     total_frames: int = 1, frame_ts: int = 0) -> Image.Image:
        """Add crosshair, RADAR label with frame timestamp, and frame dots."""
        draw = ImageDraw.Draw(img)
        w, h = img.size

        # Center crosshair
        cx, cy = w // 2, h // 2
        draw.line([(cx - 3, cy), (cx + 3, cy)], fill=(255, 255, 255), width=1)
        draw.line([(cx, cy - 3), (cx, cy + 3)], fill=(255, 255, 255), width=1)

        # Font
        try:
            font = None
            for base in ["assets/fonts", "../assets/fonts", "../../assets/fonts"]:
                p = os.path.join(base, "4x6-font.ttf")
                if os.path.exists(p):
                    font = ImageFont.truetype(p, 6)
                    break
            if not font:
                font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        # Timestamp from radar frame
        from datetime import datetime
        if frame_ts > 0:
            ts = datetime.fromtimestamp(frame_ts).strftime("%-I:%M%p").lower()
        else:
            ts = datetime.now().strftime("%-I:%M%p").lower()
        draw.text((2, h - 8), f"RADAR {ts}", font=font, fill=(180, 180, 180))

        # Frame progress dots
        if total_frames > 1:
            dot_y = h - 4
            for i in range(min(total_frames, 12)):
                dot_x = w - 3 - (total_frames - 1 - i) * 3
                color = (255, 255, 255) if i == frame_num else (60, 60, 60)
                draw.point((dot_x, dot_y), fill=color)

        return img

    def refresh_data(self, width: int, height: int) -> None:
        """Fetch new map and radar frames."""
        # Render vector map (only once — it's static)
        if self._map_bg is None or self._map_bg.size != (width, height):
            logger.info("[Radar] Rendering vector map background")
            self._map_bg = self._render_map(width, height)

        # Fetch radar frames
        path_data = self._fetch_radar_paths()
        if not path_data:
            return

        frames_to_fetch = path_data[-12:]
        new_frames = []
        new_timestamps = []
        for path, ts in frames_to_fetch:
            tile = self._fetch_radar_tile(path)
            if tile:
                new_frames.append(tile)
                new_timestamps.append(ts)

        if new_frames:
            self._radar_frames = new_frames
            self._frame_timestamps = new_timestamps
            self._frame_index = 0
            logger.info(f"[Radar] Loaded {len(new_frames)} radar frames")

        self._last_fetch = time.time()

    def get_radar_image(self, width: int, height: int) -> Optional[Image.Image]:
        """Get current radar frame composited over vector map.

        Auto-advances frames for animation and auto-refreshes every 5 minutes.
        """
        now = time.time()

        if now - self._last_fetch >= 300:
            self.refresh_data(width, height)

        if self._map_bg is None:
            self._map_bg = self._render_map(width, height)

        if not self._radar_frames:
            # Show map with overlay even without radar data
            img = self._map_bg.copy()
            return self._add_overlay(img)

        # Advance frame every 0.5s
        if now - self._last_frame_advance >= 0.5:
            self._frame_index = (self._frame_index + 1) % len(self._radar_frames)
            self._last_frame_advance = now

        idx = self._frame_index
        radar = self._radar_frames[idx]
        frame_ts = self._frame_timestamps[idx] if idx < len(self._frame_timestamps) else 0
        frame = self._composite_frame(self._map_bg, radar, width, height)
        return self._add_overlay(frame, idx, len(self._radar_frames), frame_ts)
