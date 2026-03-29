"""
Radar tile fetcher using the RainViewer API with OSM map background.

Composites precipitation radar over a map tile background (same approach
as the flights plugin map view). Supports animated playback of the last
~2 hours of radar frames.

RainViewer: free, worldwide, no API key. Updates every 10 minutes.
Map tiles: OpenStreetMap / CartoDB Dark (cached long-term).
"""

import logging
import math
import os
import time
from io import BytesIO
from typing import Any, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

logger = logging.getLogger(__name__)

_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
_TILE_SIZE = 256

# Map tile providers (same as flights plugin)
_MAP_TILE_URLS = {
    "carto_dark": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "carto": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}

_OSM_HEADERS = {
    "User-Agent": "LEDMatrix-Weather/2.2 (github.com/ChuckBuilds/ledmatrix-plugins)",
}


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convert lat/lon to tile x, y at a given zoom level."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def _frac_within_tile(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Get fractional pixel position within the tile for exact lat/lon."""
    n = 2 ** zoom
    tx, ty = _latlon_to_tile(lat, lon, zoom)
    frac_x = ((lon + 180) / 360 * n) - tx
    frac_y = ((1 - math.log(math.tan(math.radians(lat)) +
               1 / math.cos(math.radians(lat))) / math.pi) / 2 * n) - ty
    return frac_x, frac_y


class RadarFetcher:
    """Fetches radar tiles with map background from RainViewer + OSM."""

    def __init__(self, lat: float, lon: float, zoom: int = 6,
                 cache_manager: Any = None, map_provider: str = "carto_dark"):
        self.lat = lat
        self.lon = lon
        self.zoom = zoom
        self.cache = cache_manager
        self.map_provider = map_provider

        self._map_bg: Optional[Image.Image] = None
        self._radar_frames: List[Image.Image] = []
        self._frame_timestamps: List[int] = []  # unix timestamps per frame
        self._frame_index = 0
        self._last_fetch = 0.0
        self._last_frame_advance = 0.0

    def _fetch_map_tile(self) -> Optional[Image.Image]:
        """Fetch the OSM/CartoDB map tile for the background."""
        tx, ty = _latlon_to_tile(self.lat, self.lon, self.zoom)
        url_template = _MAP_TILE_URLS.get(self.map_provider, _MAP_TILE_URLS["carto_dark"])
        url = url_template.format(z=self.zoom, x=tx, y=ty)

        try:
            resp = requests.get(url, headers=_OSM_HEADERS, timeout=10)
            resp.raise_for_status()
            tile = Image.open(BytesIO(resp.content)).convert("RGB")
            # Dim the map enough for radar to stand out but still visible
            enhancer = ImageEnhance.Brightness(tile)
            tile = enhancer.enhance(0.55)
            return tile
        except Exception as e:
            logger.warning(f"[Weather Radar] Map tile fetch failed: {e}")
            return None

    def _fetch_radar_paths(self) -> List[Tuple[str, int]]:
        """Get available radar frame paths and timestamps from RainViewer.

        Returns list of (path, unix_timestamp) tuples.
        """
        try:
            resp = requests.get(_MAPS_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            radar = data.get("radar", {})
            past = radar.get("past", [])
            return [(f["path"], f.get("time", 0)) for f in past if f.get("path")]
        except Exception as e:
            logger.warning(f"[Weather Radar] RainViewer index fetch failed: {e}")
            return []

    def _fetch_radar_tile(self, path: str) -> Optional[Image.Image]:
        """Fetch a single radar tile PNG from RainViewer."""
        tx, ty = _latlon_to_tile(self.lat, self.lon, self.zoom)
        # Color scheme 2 (green/yellow/red), smooth=1, snow=1
        url = f"https://tilecache.rainviewer.com{path}/{_TILE_SIZE}/{self.zoom}/{tx}/{ty}/2/1_1.png"

        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            if resp.content[:4] != b"\x89PNG":
                return None
            return Image.open(BytesIO(resp.content)).convert("RGBA")
        except Exception as e:
            logger.debug(f"[Weather Radar] Tile fetch failed: {e}")
            return None

    def _composite_frame(self, map_bg: Image.Image, radar: Image.Image,
                         width: int, height: int) -> Image.Image:
        """Composite radar over map, crop to center, scale to display."""
        # Composite radar (RGBA) over map (RGB)
        map_rgba = map_bg.convert("RGBA")
        composite = Image.alpha_composite(map_rgba, radar)

        # Calculate crop centered on user's lat/lon within the tile
        frac_x, frac_y = _frac_within_tile(self.lat, self.lon, self.zoom)
        px = int(frac_x * _TILE_SIZE)
        py = int(frac_y * _TILE_SIZE)

        # Crop region sized proportionally to output
        aspect = width / height
        crop_h = min(_TILE_SIZE, max(height, _TILE_SIZE // 2))
        crop_w = min(_TILE_SIZE, int(crop_h * aspect))

        left = max(0, min(_TILE_SIZE - crop_w, px - crop_w // 2))
        top = max(0, min(_TILE_SIZE - crop_h, py - crop_h // 2))

        cropped = composite.crop((left, top, left + crop_w, top + crop_h))
        return cropped.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)

    def _add_overlay(self, img: Image.Image, frame_num: int = 0,
                     total_frames: int = 1, frame_ts: int = 0) -> Image.Image:
        """Add crosshair, RADAR label with frame timestamp, and frame indicator."""
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

        # RADAR label + frame timestamp (shows when this radar frame was captured)
        from datetime import datetime
        if frame_ts > 0:
            ts = datetime.fromtimestamp(frame_ts).strftime("%-I:%M%p").lower()
        else:
            ts = datetime.now().strftime("%-I:%M%p").lower()
        draw.text((2, h - 8), f"RADAR {ts}", font=font, fill=(180, 180, 180))

        # Frame progress indicator (small dots at bottom-right)
        if total_frames > 1:
            dot_y = h - 4
            for i in range(min(total_frames, 12)):
                dot_x = w - 3 - (total_frames - 1 - i) * 3
                color = (255, 255, 255) if i == frame_num else (60, 60, 60)
                draw.point((dot_x, dot_y), fill=color)

        return img

    def refresh_data(self) -> None:
        """Fetch new map background and all available radar frames."""
        # Map background (cache for a long time)
        if self._map_bg is None:
            self._map_bg = self._fetch_map_tile()
            if self._map_bg is None:
                # Fallback: black tile
                self._map_bg = Image.new("RGB", (_TILE_SIZE, _TILE_SIZE), (0, 0, 0))

        # Radar frames
        path_data = self._fetch_radar_paths()
        if not path_data:
            return

        # Fetch last N frames (6-12 frames = 1-2 hours)
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
            logger.info(f"[Weather Radar] Loaded {len(new_frames)} radar frames")

        self._last_fetch = time.time()

    def get_radar_image(self, width: int, height: int) -> Optional[Image.Image]:
        """Get the current radar frame composited over the map.

        Call this repeatedly — it auto-advances frames for animation
        and auto-refreshes data every 5 minutes.
        """
        now = time.time()

        # Refresh data if needed (every 5 minutes)
        if now - self._last_fetch >= 300:
            self.refresh_data()

        if not self._radar_frames:
            return None

        # Advance frame every 0.5 seconds for smooth animation
        if now - self._last_frame_advance >= 0.5:
            self._frame_index = (self._frame_index + 1) % len(self._radar_frames)
            self._last_frame_advance = now

        idx = self._frame_index
        radar = self._radar_frames[idx]
        frame_ts = self._frame_timestamps[idx] if idx < len(self._frame_timestamps) else 0
        frame = self._composite_frame(self._map_bg, radar, width, height)
        return self._add_overlay(frame, idx, len(self._radar_frames), frame_ts)
