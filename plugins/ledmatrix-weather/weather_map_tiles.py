"""
Web-Mercator viewport math and basemap tile fetching for the radar display.

A MercatorViewport is a single window in world-pixel space (at one zoom level)
that the basemap tiles, the RainViewer radar tiles, and the vector state-map
renderer all share — so every layer lands on exactly the same geography.

BasemapTileFetcher pulls slippy-map tiles (OSM-compatible `/z/x/y.png`
layout), preferring a self-hosted tile server when configured, with public
mirrors as fallback. Tiles are cached on disk (they rarely change) in the
same `map_tiles` directory layout the flight tracker plugin uses, so the two
plugins share cached tiles for the standard providers.

Named `weather_map_tiles` (not `map_tiles`) because it is imported after the
plugin loader's namespace isolation; a bare generic name could resolve to
another plugin's module.
"""

import logging
import math
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests
from PIL import Image

TILE_SIZE = 256

# Ceiling on tiles fetched per layer per frame; for_panel() lowers the zoom
# until the viewport fits. Keeps a full radar refresh (frames x tiles) within
# the update loop's time budget.
MAX_TILES_PER_LAYER = 8

_TILE_TTL_SECONDS = 8760 * 3600  # 1 year — basemap tiles rarely change

# OSM tile-usage policy asks for an identifying User-Agent.
_HEADERS = {"User-Agent": "LEDMatrix-weather-plugin (+https://github.com/ChuckBuilds/ledmatrix-plugins)"}

_MI_PER_DEG_LAT = 69.172


def latlon_to_world_px(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Project lat/lon to Web-Mercator world pixels at the given zoom."""
    n = TILE_SIZE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def world_px_to_latlon(wx: float, wy: float, zoom: int) -> Tuple[float, float]:
    """Inverse of latlon_to_world_px."""
    n = TILE_SIZE * (2 ** zoom)
    lon = wx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * wy / n))))
    return lat, lon


class MercatorViewport:
    """A world-pixel window centered on a location, shared by all map layers."""

    def __init__(self, center_lat: float, center_lon: float, zoom: int,
                 view_w: int, view_h: int):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.zoom = zoom
        self.view_w = max(1, int(round(view_w)))
        self.view_h = max(1, int(round(view_h)))
        cx, cy = latlon_to_world_px(center_lat, center_lon, zoom)
        self.origin_x = cx - self.view_w / 2.0
        self.origin_y = cy - self.view_h / 2.0

    @classmethod
    def for_panel(cls, center_lat: float, center_lon: float, range_miles: float,
                  panel_w: int, panel_h: int,
                  max_tiles: int = MAX_TILES_PER_LAYER) -> "MercatorViewport":
        """Pick a zoom so `range_miles` from center reaches the panel's edge.

        Chooses the smallest zoom whose view is at least panel-width wide (so
        the final resize only ever downscales), then backs off while the tile
        count exceeds `max_tiles`.
        """
        cos_lat = max(0.05, math.cos(math.radians(center_lat)))

        def px_per_mile(z: int) -> float:
            return TILE_SIZE * (2 ** z) / 360.0 / (_MI_PER_DEG_LAT * cos_lat)

        def build(z: int) -> "MercatorViewport":
            vw = max(panel_w, 2.0 * range_miles * px_per_mile(z))
            vh = vw * panel_h / panel_w
            return cls(center_lat, center_lon, z, vw, vh)

        zoom = 12
        for z in range(3, 13):
            zoom = z
            if 2.0 * range_miles * px_per_mile(z) >= panel_w:
                break
        vp = build(zoom)
        while zoom > 3 and vp.num_tiles() > max_tiles:
            zoom -= 1
            vp = build(zoom)
        return vp

    def tile_range(self) -> Tuple[int, int, int, int]:
        """Inclusive (x0, y0, x1, y1) of slippy tiles intersecting the view."""
        n = 2 ** self.zoom
        x0 = int(math.floor(self.origin_x / TILE_SIZE))
        y0 = int(math.floor(self.origin_y / TILE_SIZE))
        x1 = int(math.floor((self.origin_x + self.view_w - 1) / TILE_SIZE))
        y1 = int(math.floor((self.origin_y + self.view_h - 1) / TILE_SIZE))
        # Clamp y to the valid tile grid; x wraps at the antimeridian.
        y0 = max(0, min(n - 1, y0))
        y1 = max(0, min(n - 1, y1))
        return x0, y0, x1, y1

    def wrap_tile_x(self, tx: int) -> int:
        """Wrap a tile x index across the antimeridian."""
        n = 2 ** self.zoom
        return tx % n

    def tile_paste_offset(self, tx: int, ty: int) -> Tuple[int, int]:
        """Top-left pixel where tile (tx, ty) lands inside the view."""
        return (int(round(tx * TILE_SIZE - self.origin_x)),
                int(round(ty * TILE_SIZE - self.origin_y)))

    def num_tiles(self) -> int:
        x0, y0, x1, y1 = self.tile_range()
        return (x1 - x0 + 1) * (y1 - y0 + 1)

    def latlon_to_view(self, lat: float, lon: float) -> Tuple[float, float]:
        """Project lat/lon to view-local pixels (may fall outside the view)."""
        wx, wy = latlon_to_world_px(lat, lon, self.zoom)
        return wx - self.origin_x, wy - self.origin_y

    def latlon_to_panel(self, lat: float, lon: float,
                        panel_w: int, panel_h: int) -> Tuple[int, int]:
        """Project lat/lon to panel pixels after the view→panel downscale."""
        vx, vy = self.latlon_to_view(lat, lon)
        return (int(vx / self.view_w * panel_w), int(vy / self.view_h * panel_h))

    def signature(self) -> Tuple:
        """Hashable identity — layers cached against one viewport are invalid
        for any viewport with a different signature."""
        return (round(self.center_lat, 5), round(self.center_lon, 5),
                self.zoom, self.view_w, self.view_h)


class BasemapTileFetcher:
    """Fetches and disk-caches basemap tiles, composing them per viewport."""

    def __init__(self, cache_manager=None, style: str = "osm",
                 custom_tile_server: Optional[str] = None, logger=None):
        self.style = style
        self.custom_tile_server = (custom_tile_server or "").strip().rstrip("/") or None
        self.logger = logger or logging.getLogger(__name__)
        self._cache_dir = self._resolve_cache_dir(cache_manager)
        self._last_good: Optional[Tuple[Tuple, Image.Image]] = None

    def _resolve_cache_dir(self, cache_manager) -> Optional[Path]:
        base = getattr(cache_manager, "cache_dir", None)
        candidates = []
        if base:
            candidates.append(Path(base) / "map_tiles")
        candidates.append(Path(tempfile.gettempdir()) / "ledmatrix_map_tiles")
        for cand in candidates:
            try:
                cand.mkdir(parents=True, exist_ok=True)
                probe = cand / ".write_test"
                probe.write_bytes(b"x")
                probe.unlink()
                return cand
            except (PermissionError, OSError) as e:
                self.logger.warning(f"[Radar] Tile cache dir {cand} unusable: {e}")
        return None

    def _cache_key(self) -> str:
        if self.style == "osm" and self.custom_tile_server:
            host = urlparse(self.custom_tile_server).netloc or "custom"
            return "custom-" + "".join(c if c.isalnum() or c in ".-" else "_"
                                       for c in host)
        return self.style

    def _tile_urls(self, tx: int, ty: int, zoom: int) -> List[str]:
        urls = []
        if self.style == "osm":
            if self.custom_tile_server:
                urls.append(f"{self.custom_tile_server}/tile/{zoom}/{tx}/{ty}.png")
            urls += [
                f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
                f"https://a.tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
                f"https://b.tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
            ]
        elif self.style in ("carto", "carto_dark"):
            layer = "light_all" if self.style == "carto" else "dark_all"
            urls += [
                f"https://a.basemaps.cartocdn.com/{layer}/{zoom}/{tx}/{ty}.png",
                f"https://b.basemaps.cartocdn.com/{layer}/{zoom}/{tx}/{ty}.png",
                f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
            ]
        elif self.style == "esri":
            urls += [
                # Note the swapped z/y/x order in the ArcGIS REST tile scheme.
                f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{zoom}/{ty}/{tx}",
                f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
            ]
        return urls

    def _tile_cache_path(self, tx: int, ty: int, zoom: int) -> Optional[Path]:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{self._cache_key()}_{zoom}_{tx}_{ty}.png"

    def _fetch_tile(self, tx: int, ty: int, zoom: int,
                    deadline: Optional[float] = None) -> Optional[Image.Image]:
        cache_path = self._tile_cache_path(tx, ty, zoom)
        if cache_path is not None and cache_path.exists():
            if time.time() - cache_path.stat().st_mtime < _TILE_TTL_SECONDS:
                try:
                    return Image.open(cache_path).convert("RGB")
                except Exception as e:
                    self.logger.warning(f"[Radar] Bad cached tile {cache_path}: {e}")

        for url in self._tile_urls(tx, ty, zoom):
            if deadline is not None and time.time() > deadline:
                return None
            try:
                resp = requests.get(url, timeout=10, headers=_HEADERS)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").lower()
                if "text/html" in content_type or "text/plain" in content_type:
                    continue  # error page, try next mirror
                img = Image.open(BytesIO(resp.content))
                if img.size != (TILE_SIZE, TILE_SIZE):
                    self.logger.debug(f"[Radar] Unexpected tile size {img.size} from {url}")
                    continue
                if cache_path is not None:
                    try:
                        cache_path.write_bytes(resp.content)
                    except (PermissionError, OSError) as e:
                        self.logger.warning(f"[Radar] Could not cache tile: {e}")
                return img.convert("RGB")
            except Exception as e:
                self.logger.debug(f"[Radar] Basemap tile fetch failed from {url}: {e}")
        return None

    def get_basemap(self, viewport: MercatorViewport,
                    deadline: Optional[float] = None) -> Optional[Image.Image]:
        """Compose the basemap for a viewport; None if any tile is missing.

        Keeps the last successfully composed basemap and returns it when the
        viewport is unchanged, so tiles are only stitched once per view.
        """
        sig = viewport.signature() + (self._cache_key(),)
        if self._last_good is not None and self._last_good[0] == sig:
            return self._last_good[1]

        x0, y0, x1, y1 = viewport.tile_range()
        composite = Image.new("RGB", (viewport.view_w, viewport.view_h), (0, 0, 0))
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                tile = self._fetch_tile(viewport.wrap_tile_x(tx), ty,
                                        viewport.zoom, deadline)
                if tile is None:
                    self.logger.info(
                        f"[Radar] Basemap tile {viewport.zoom}/{tx}/{ty} unavailable; "
                        "falling back to vector map")
                    return None
                composite.paste(tile, viewport.tile_paste_offset(tx, ty))
        self._last_good = (sig, composite)
        return composite
