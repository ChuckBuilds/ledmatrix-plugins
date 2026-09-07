"""
Radar display: RainViewer precipitation over an OSM (or vector) basemap.

All layers — basemap tiles, radar tiles, and the WeatherStar-style vector
state map — are rendered through one shared MercatorViewport, so radar
returns line up with the map at every panel size. Every radar frame is a
mosaic of all tiles intersecting the viewport (not just the tile under the
center), fetched within a time budget and resumable across update ticks.

Frames: recent RainViewer "past" frames plus (optionally) short-term
"nowcast" forecast frames. Radar tiles and the frame index are cached so a
restart rebuilds the animation without refetching.

Named `weather_radar` (not `radar`) because manager.py imports it lazily,
after the plugin loader's namespace isolation — a generic bare name could
resolve to another plugin's module.
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from weather_map_tiles import BasemapTileFetcher, MercatorViewport, TILE_SIZE

logger = logging.getLogger(__name__)

_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
_HEADERS = {"User-Agent": "LEDMatrix-weather-plugin (+https://github.com/ChuckBuilds/ledmatrix-plugins)"}

# Path to bundled GeoJSON state boundaries (vector style + tile-failure fallback)
_GEOJSON_PATH = os.path.join(os.path.dirname(__file__), "data", "us-states.geojson")

# Core-repo font, resolved relative to this file (plugin dir -> plugins -> root),
# matching how manager.py locates assets. CWD-independent.
def _font_candidates():
    """Where the 4x6 face may live, best guess first.

    The plugin normally sits at <LEDMatrix>/plugin-repos/<id>, so three levels
    up is the core root -- but the plugins directory is configurable, and from
    anywhere else that guess finds nothing. The fallback is PIL's default font,
    which is taller than the 6px this overlay is laid out for, so the timestamp
    label ends up drawn past the bottom edge of the panel. Ask the imported
    core where it is first.
    """
    roots = []
    try:
        import src  # the LEDMatrix core package
        if getattr(src, "__file__", None):
            roots.append(Path(src.__file__).resolve().parent.parent)
    except Exception:  # nosec B110 - absence is expected off a real install
        pass
    roots.append(Path(__file__).resolve().parent.parent.parent)
    roots.append(Path.cwd())
    return [r / "assets" / "fonts" / "4x6-font.ttf" for r in roots]

_FETCH_BUDGET_SECONDS = 20   # per refresh_data() call; work resumes next tick
_NOWCAST_FRAMES = 3          # RainViewer publishes 3 nowcast frames (10/20/30 min)
_RADAR_TILE_MAX_AGE = 3 * 3600  # disk-cache purge horizon for radar tiles
_WORK_RETRY_SECONDS = 60     # backoff before retrying failed tile work

# RainViewer serves radar tiles only up to this slippy zoom; above it the API
# returns a "Zoom Level Not Supported" placeholder (a small dark label tile)
# rather than a transparent/precip tile. The basemap tile server (OSM) supports
# deeper zooms, so on small-range/large-panel combos the shared viewport can
# pick a zoom past this ceiling. We fetch radar at the capped zoom and upscale
# to the viewport so the placeholder never composites over the map.
_RAINVIEWER_MAX_ZOOM = 7

_NOWCAST_DOT = (255, 255, 0)
_NOWCAST_DOT_DIM = (90, 90, 0)
_PAST_DOT = (255, 255, 255)
_PAST_DOT_DIM = (60, 60, 60)


# ---------------------------------------------------------------------------
# Vector map renderer (WeatherStar style; US-only GeoJSON)
# ---------------------------------------------------------------------------

_geojson_cache: Dict[str, Any] = {}


def _load_geojson() -> Optional[Dict]:
    if "data" not in _geojson_cache:
        if os.path.exists(_GEOJSON_PATH):
            with open(_GEOJSON_PATH, "r", encoding="utf-8") as f:
                _geojson_cache["data"] = json.load(f)
        else:
            logger.warning("[Radar] GeoJSON not found at %s", _GEOJSON_PATH)
            _geojson_cache["data"] = {}
    return _geojson_cache["data"] or None


def render_vector_map(viewport: MercatorViewport,
                      line_color: Tuple[int, int, int] = (0, 130, 70),
                      fill_color: Optional[Tuple[int, int, int]] = (15, 25, 15)) -> Image.Image:
    """Render state boundaries at viewport resolution: black water, dark land
    fill, colored outlines — projected with the same viewport as the radar."""
    img = Image.new("RGB", (viewport.view_w, viewport.view_h), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    geojson = _load_geojson()
    if not geojson:
        return img

    w, h = viewport.view_w, viewport.view_h
    margin = max(w, h)
    for feature in geojson.get("features", []):
        geom = feature.get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        polygons = [coords] if gtype == "Polygon" else coords if gtype == "MultiPolygon" else []

        for polygon in polygons:
            for ring in polygon:
                pts = []
                for coord in ring:
                    vx, vy = viewport.latlon_to_view(coord[1], coord[0])
                    pts.append((int(vx), int(vy)))
                if len(pts) < 3:
                    continue
                if not any(-margin < x < w + margin and -margin < y < h + margin
                           for x, y in pts):
                    continue
                try:
                    if fill_color:
                        draw.polygon(pts, fill=fill_color)
                    draw.polygon(pts, outline=line_color)
                except (ValueError, TypeError) as e:
                    logger.debug("[Radar] Skipping unrenderable polygon: %s", e)
    return img


# ---------------------------------------------------------------------------
# Radar fetcher
# ---------------------------------------------------------------------------

@dataclass
class RadarFrame:
    ts: int
    path: str
    is_nowcast: bool
    image: Optional[Image.Image] = None  # RGBA mosaic at viewport size


class RadarFetcher:
    """Fetches and animates RainViewer radar over a shared-viewport basemap."""

    def __init__(self, lat: float, lon: float, range_miles: float = 50,
                 cache_manager: Any = None, *,
                 map_style: str = "osm",
                 custom_tile_server: Optional[str] = None,
                 line_color: Tuple[int, int, int] = (0, 130, 70),
                 fill_color: Optional[Tuple[int, int, int]] = (15, 25, 15),
                 map_brightness: float = 0.5,
                 show_nowcast: bool = True,
                 past_frames: int = 6,
                 frame_seconds: float = 0.5,
                 loop_pause_seconds: float = 1.5,
                 plugin_id: str = "ledmatrix-weather"):
        self.lat = lat
        self.lon = lon
        self.range_miles = max(5.0, float(range_miles))
        self.cache = cache_manager
        self.map_style = map_style
        self.line_color = line_color
        self.fill_color = fill_color
        self.map_brightness = map_brightness
        self.show_nowcast = show_nowcast
        self.past_frames = max(2, int(past_frames))
        self.frame_seconds = max(0.1, float(frame_seconds))
        self.loop_pause_seconds = max(0.0, float(loop_pause_seconds))
        self.plugin_id = plugin_id

        self._basemap_fetcher = BasemapTileFetcher(
            cache_manager, style=map_style,
            custom_tile_server=custom_tile_server, logger=logger)
        self._radar_cache_dir = self._resolve_radar_cache_dir(cache_manager)

        self._viewport: Optional[MercatorViewport] = None
        self._basemap: Optional[Image.Image] = None       # dimmed, view-sized
        self._basemap_retry_after = 0.0
        self._vector_map: Optional[Image.Image] = None    # fallback, view-sized
        self._frames: Dict[int, RadarFrame] = {}
        self._newest_past_ts: int = 0
        self._last_index_poll = 0.0
        self._next_work_retry = 0.0
        self._poll_interval = 180.0

        self._frame_index = 0
        self._last_frame_advance = 0.0
        self._loops_completed = 0
        self._panel_size: Optional[Tuple[int, int]] = None
        self._font = None

    # ---- caching ----------------------------------------------------------

    def _resolve_radar_cache_dir(self, cache_manager) -> Optional[Path]:
        base = getattr(cache_manager, "cache_dir", None)
        candidates = []
        if base:
            candidates.append(Path(base) / "weather_radar_tiles")
        candidates.append(Path(tempfile.gettempdir()) / "ledmatrix_weather_radar_tiles")
        for cand in candidates:
            try:
                cand.mkdir(parents=True, exist_ok=True)
                probe = cand / ".write_test"
                probe.write_bytes(b"x")
                probe.unlink()
                return cand
            except (PermissionError, OSError) as e:
                logger.warning(f"[Radar] Radar tile cache dir {cand} unusable: {e}")
        return None

    def _radar_tile_cache_path(self, path: str, zoom: int,
                               tx: int, ty: int) -> Optional[Path]:
        if self._radar_cache_dir is None:
            return None
        # Last path segment is unique per frame generation (past frames use the
        # timestamp; nowcast frames use a per-generation hash, so a regenerated
        # prediction never reuses a stale cached tile).
        seg = path.rstrip("/").rsplit("/", 1)[-1] or "frame"
        seg = "".join(c if c.isalnum() or c in "._-" else "_" for c in seg)
        return self._radar_cache_dir / f"{seg}_{zoom}_{tx}_{ty}.png"

    def _purge_radar_tile_cache(self) -> None:
        if self._radar_cache_dir is None:
            return
        try:
            cutoff = time.time() - _RADAR_TILE_MAX_AGE
            for f in self._radar_cache_dir.glob("*.png"):
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
        except OSError as e:
            logger.debug("[Radar] Radar tile cache purge failed: %s", e)

    def _index_cache_key(self) -> str:
        return f"{self.plugin_id}:radar:index"

    # ---- viewport / basemap -----------------------------------------------

    def _ensure_viewport(self, width: int, height: int) -> MercatorViewport:
        vp = self._viewport
        if vp is None or (width, height) != self._panel_size:
            vp = MercatorViewport.for_panel(self.lat, self.lon, self.range_miles,
                                            width, height)
            if self._viewport is None or vp.signature() != self._viewport.signature():
                logger.info(
                    f"[Radar] Viewport: zoom={vp.zoom} view={vp.view_w}x{vp.view_h} "
                    f"tiles={vp.num_tiles()} for panel {width}x{height}")
                self._viewport = vp
                self._basemap = None
                self._vector_map = None
                for frame in self._frames.values():
                    frame.image = None
            self._panel_size = (width, height)
        return self._viewport

    def _get_vector_map(self, viewport: MercatorViewport) -> Image.Image:
        if self._vector_map is None:
            self._vector_map = render_vector_map(
                viewport, line_color=self.line_color, fill_color=self.fill_color)
        return self._vector_map

    def _refresh_basemap(self, viewport: MercatorViewport,
                         deadline: Optional[float]) -> None:
        """Build the (dimmed) tile basemap; leaves None to fall back to vector."""
        if self.map_style == "vector" or self._basemap is not None:
            return
        if time.time() < self._basemap_retry_after:
            return
        raw = self._basemap_fetcher.get_basemap(viewport, deadline)
        if raw is not None:
            self._basemap = ImageEnhance.Brightness(raw).enhance(self.map_brightness)
            self._basemap_retry_after = 0.0
        else:
            # Server likely unreachable; don't burn the fetch budget on the
            # basemap every tick — the vector fallback covers the meantime.
            self._basemap_retry_after = time.time() + 300

    def _get_background(self, viewport: MercatorViewport) -> Image.Image:
        """Basemap for display: tiles when available, else vector fallback."""
        if self._basemap is not None:
            return self._basemap
        return self._get_vector_map(viewport)

    # ---- RainViewer index -------------------------------------------------

    def _fetch_index(self) -> Optional[Dict]:
        try:
            resp = requests.get(_MAPS_URL, timeout=10, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            if self.cache is not None:
                try:
                    self.cache.set(self._index_cache_key(), data, ttl=900)
                except Exception as e:
                    logger.debug("[Radar] Could not cache index: %s", e)
            return data
        except Exception as e:
            logger.warning(f"[Radar] RainViewer index fetch failed: {e}")
            if self.cache is not None:
                try:
                    cached = self.cache.get(self._index_cache_key(), max_age=900)
                    if cached:
                        logger.info("[Radar] Using cached RainViewer index")
                        return cached
                except Exception as cache_err:
                    logger.debug("[Radar] Cached index unavailable: %s", cache_err)
            return None

    def _wanted_frames(self, index: Dict) -> List[Tuple[str, int, bool]]:
        """(path, ts, is_nowcast) list: recent past frames + nowcast frames."""
        radar = index.get("radar", {}) or {}
        past = [f for f in (radar.get("past") or []) if f.get("path")]
        nowcast = [f for f in (radar.get("nowcast") or []) if f.get("path")]
        wanted = [(f["path"], int(f.get("time", 0)), False)
                  for f in past[-self.past_frames:]]
        if self.show_nowcast:
            wanted += [(f["path"], int(f.get("time", 0)), True)
                       for f in nowcast[:_NOWCAST_FRAMES]]
        return wanted

    # ---- radar tiles ------------------------------------------------------

    def _fetch_radar_tile(self, path: str, zoom: int, tx: int, ty: int,
                          deadline: Optional[float]) -> Optional[Image.Image]:
        cache_path = self._radar_tile_cache_path(path, zoom, tx, ty)
        if cache_path is not None and cache_path.exists():
            try:
                return Image.open(cache_path).convert("RGBA")
            except Exception as e:
                logger.debug("[Radar] Bad cached radar tile %s: %s", cache_path, e)
        if deadline is not None and time.time() > deadline:
            return None
        url = f"https://tilecache.rainviewer.com{path}/{TILE_SIZE}/{zoom}/{tx}/{ty}/2/1_1.png"
        try:
            resp = requests.get(url, timeout=10, headers=_HEADERS)
            resp.raise_for_status()
            if resp.content[:4] != b"\x89PNG":
                return None
            if cache_path is not None:
                try:
                    cache_path.write_bytes(resp.content)
                except (PermissionError, OSError) as e:
                    logger.debug("[Radar] Could not cache radar tile: %s", e)
            return Image.open(BytesIO(resp.content)).convert("RGBA")
        except Exception as e:
            logger.debug(f"[Radar] Tile fetch failed ({url}): {e}")
            return None

    def _build_frame_image(self, frame: RadarFrame, viewport: MercatorViewport,
                           deadline: Optional[float]) -> bool:
        """Mosaic every viewport tile for one frame. False if incomplete.

        When the shared viewport is zoomed deeper than RainViewer serves radar
        (`_RAINVIEWER_MAX_ZOOM`), the radar layer is fetched at the capped zoom
        through a same-center viewport with proportionally smaller view dims —
        which covers the identical geography — then upscaled to align exactly
        with the (deeper) basemap. This avoids RainViewer's "Zoom Level Not
        Supported" placeholder tile while keeping radar registered to the map.
        """
        rv = self._radar_viewport(viewport)
        x0, y0, x1, y1 = rv.tile_range()
        mosaic = Image.new("RGBA", (rv.view_w, rv.view_h), (0, 0, 0, 0))
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                tile = self._fetch_radar_tile(frame.path, rv.zoom,
                                              rv.wrap_tile_x(tx), ty, deadline)
                if tile is None:
                    return False
                mosaic.paste(tile, rv.tile_paste_offset(tx, ty))
        if (rv.view_w, rv.view_h) != (viewport.view_w, viewport.view_h):
            mosaic = mosaic.resize((viewport.view_w, viewport.view_h),
                                   Image.Resampling.NEAREST)
        frame.image = mosaic
        return True

    @staticmethod
    def _radar_viewport(viewport: MercatorViewport) -> MercatorViewport:
        """Viewport to fetch radar tiles through: the shared viewport unless it
        exceeds RainViewer's max zoom, in which case a same-center viewport at
        the capped zoom (with view dims halved per zoom step down) covering the
        identical geographic window."""
        if viewport.zoom <= _RAINVIEWER_MAX_ZOOM:
            return viewport
        scale = 2 ** (viewport.zoom - _RAINVIEWER_MAX_ZOOM)
        return MercatorViewport(viewport.center_lat, viewport.center_lon,
                                _RAINVIEWER_MAX_ZOOM,
                                viewport.view_w / scale, viewport.view_h / scale)

    # ---- refresh ----------------------------------------------------------

    def refresh_data(self, width: int, height: int) -> None:
        """Poll the frame index and fetch missing basemap/radar tiles.

        Bounded by a time budget; unfinished work resumes on the next update
        tick (needs_refresh() keeps returning True while work is pending).
        """
        deadline = time.time() + _FETCH_BUDGET_SECONDS
        viewport = self._ensure_viewport(width, height)

        # Basemap first — it's the backdrop for everything, and tiles are
        # usually already on disk after the first run.
        self._refresh_basemap(viewport, deadline)

        # Poll the index only when the interval has elapsed; tile work below
        # resumes regardless (a resumed-work tick must not re-hit the index).
        if time.time() - self._last_index_poll >= self._poll_interval:
            index = self._fetch_index()
            if index is not None:
                wanted = self._wanted_frames(index)
                if wanted:
                    self._reconcile_frames(wanted)
                    self._last_index_poll = time.time()
                    self._purge_radar_tile_cache()
                else:
                    logger.error("[Radar] RainViewer index contained no frames")
                    self._last_index_poll = time.time() - max(0.0, self._poll_interval - 60)
            else:
                # Retry the index in ~60s rather than a full interval.
                self._last_index_poll = time.time() - max(0.0, self._poll_interval - 60)

        # Fetch tiles for incomplete frames, newest past first (most useful),
        # then older past frames, then nowcast.
        pending = [f for f in self._frames.values() if f.image is None]
        pending.sort(key=lambda f: (f.is_nowcast,
                                    -f.ts if not f.is_nowcast else f.ts))
        built = 0
        for frame in pending:
            if time.time() > deadline:
                logger.info("[Radar] Tile fetch budget exhausted; resuming next tick")
                break
            if self._build_frame_image(frame, viewport, deadline):
                built += 1
        if built:
            complete = sum(1 for f in self._frames.values() if f.image is not None)
            logger.info(f"[Radar] {complete}/{len(self._frames)} frames ready "
                        f"({built} built this tick)")
        if self._has_pending_work():
            self._next_work_retry = time.time() + _WORK_RETRY_SECONDS

    def _reconcile_frames(self, wanted: List[Tuple[str, int, bool]]) -> None:
        """Sync self._frames to the wanted list, keeping built images."""
        wanted_ts = set()
        for path, ts, is_nowcast in wanted:
            wanted_ts.add(ts)
            existing = self._frames.get(ts)
            if existing is None or existing.path != path:
                self._frames[ts] = RadarFrame(ts=ts, path=path, is_nowcast=is_nowcast)
        for ts in list(self._frames.keys()):
            if ts not in wanted_ts:
                del self._frames[ts]
        past_ts = [f.ts for f in self._frames.values() if not f.is_nowcast]
        self._newest_past_ts = max(past_ts) if past_ts else 0
        # Keep playback position stable-ish across reconciles
        self._frame_index = min(self._frame_index, max(0, len(self._frames) - 1))

    def _has_pending_work(self) -> bool:
        if any(f.image is None for f in self._frames.values()):
            return True
        if (self.map_style != "vector" and self._basemap is None
                and self._viewport is not None
                and time.time() >= self._basemap_retry_after):
            return True
        return False

    def needs_refresh(self, interval: int = 180) -> bool:
        """True when the index poll is due or tile work is pending."""
        self._poll_interval = float(interval)
        if time.time() - self._last_index_poll >= interval:
            return True
        return self._has_pending_work() and time.time() >= self._next_work_retry

    # ---- playback ---------------------------------------------------------

    def _playback_frames(self) -> List[RadarFrame]:
        """Complete frames in chronological order (past ... nowcast)."""
        # dict.copy() first, not a comprehension over .values():
        # _reconcile_frames() runs on the update thread and can add or drop
        # entries while this iterates, and any lazy iteration -- including
        # list(d.values()) -- raises "dictionary changed size during iteration"
        # when that happens. copy() completes in one bytecode under the GIL,
        # so the other thread cannot interleave inside it.
        frames = [f for f in self._frames.copy().values() if f.image is not None]
        frames.sort(key=lambda f: f.ts)
        return frames

    def get_loop_duration(self) -> float:
        n = max(1, len(self._playback_frames()))
        return n * self.frame_seconds + self.loop_pause_seconds

    def is_loop_complete(self) -> bool:
        return self._loops_completed >= 1

    def reset_loop(self) -> None:
        self._loops_completed = 0
        self._frame_index = 0
        self._last_frame_advance = time.time()

    def _advance_frame(self, num_frames: int) -> int:
        now = time.time()
        if self._last_frame_advance == 0.0:
            self._last_frame_advance = now
        if self._frame_index >= num_frames:
            self._frame_index = 0
        dwell = self.frame_seconds
        if self._frame_index == num_frames - 1:
            dwell += self.loop_pause_seconds  # hold on the newest frame
        if now - self._last_frame_advance >= dwell:
            self._frame_index += 1
            if self._frame_index >= num_frames:
                self._frame_index = 0
                self._loops_completed += 1
            self._last_frame_advance = now
        return self._frame_index

    # ---- rendering --------------------------------------------------------

    def get_radar_image(self, width: int, height: int) -> Optional[Image.Image]:
        """Composite the current frame for display. Never blocks on HTTP —
        refresh_data() (called from the plugin's update loop) does the I/O."""
        viewport = self._ensure_viewport(width, height)
        background = self._get_background(viewport)
        frames = self._playback_frames()

        if not frames:
            img = background.resize((width, height), Image.Resampling.LANCZOS)
            return self._add_overlay(img, None, [], width, height, viewport)

        idx = self._advance_frame(len(frames))
        frame = frames[idx]

        # The background and the frame can come from different viewports.
        # refresh_data() runs on the update thread and get_radar_image() on the
        # display thread, both call _ensure_viewport(), and both are called
        # with different sizes: the plugin renders the full panel while the
        # Vegas adapter asks for a narrower slice (512x64 and 204x64 on the rig
        # this was found on). If the viewport is swapped between one thread
        # building a frame and the other compositing it, the two images differ
        # in size and alpha_composite raises ValueError("images do not match").
        # That propagates out of display(), so nothing new is drawn and the
        # panel sits on whatever was last composited -- the radar appears
        # frozen at an old timestamp, which is exactly how it was reported.
        # Showing the background alone for one tick is a far better outcome
        # than raising: the next tick has a consistent pair.
        # One read, held locally. refresh_data() can set frame.image to None
        # between the check and the composite, and re-reading the attribute
        # would then raise AttributeError instead of the ValueError this guard
        # was added for -- trading one crash for a narrower one. A local
        # reference keeps the image alive for the rest of this call whatever
        # the other thread does to the attribute.
        frame_image = frame.image
        if frame_image is None or frame_image.size != background.size:
            logger.info(
                "[Radar] Frame %s does not match background %dx%d "
                "(viewport changed mid-render); showing the map for this tick",
                (f"{frame_image.size[0]}x{frame_image.size[1]}"
                 if frame_image is not None else "gone"),
                background.size[0], background.size[1])
            for stale in self._frames.copy().values():
                stale.image = None
            img = background.resize((width, height), Image.Resampling.LANCZOS)
            return self._add_overlay(img, None, [], width, height, viewport)

        composite = Image.alpha_composite(background.convert("RGBA"), frame_image)
        img = composite.convert("RGB").resize((width, height),
                                              Image.Resampling.LANCZOS)
        return self._add_overlay(img, frame, frames, width, height, viewport)

    def _load_font(self):
        if self._font is None:
            for candidate in _font_candidates():
                try:
                    self._font = ImageFont.truetype(str(candidate), 6)
                    break
                except (OSError, ValueError):
                    continue
            if self._font is None:
                self._font = ImageFont.load_default()
        return self._font

    def _add_overlay(self, img: Image.Image, current: Optional[RadarFrame],
                     frames: List[RadarFrame], width: int, height: int,
                     viewport: MercatorViewport) -> Image.Image:
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Crosshair at the configured location's true projected position
        cx, cy = viewport.latlon_to_panel(self.lat, self.lon, width, height)
        draw.line([(cx - 3, cy), (cx + 3, cy)], fill=(255, 255, 255), width=1)
        draw.line([(cx, cy - 3), (cx, cy + 3)], fill=(255, 255, 255), width=1)

        font = self._load_font()

        if current is not None and current.is_nowcast:
            mins = max(0, round((current.ts - self._newest_past_ts) / 60)) \
                if self._newest_past_ts else 0
            label = f"FCST +{mins}m"
        else:
            ts = current.ts if current is not None else 0
            dt = datetime.fromtimestamp(ts) if ts > 0 else datetime.now()
            # %-I is glibc-only; strip the leading zero portably instead.
            label = "RADAR " + dt.strftime("%I:%M%p").lstrip("0").lower()
        draw.text((2, height - 8), label, font=font, fill=(180, 180, 180))

        # Frame progress dots: white for past, yellow for nowcast
        if len(frames) > 1:
            dot_y = height - 4
            shown = frames[-12:]
            for i, f in enumerate(shown):
                is_current = current is not None and f.ts == current.ts
                if f.is_nowcast:
                    color = _NOWCAST_DOT if is_current else _NOWCAST_DOT_DIM
                else:
                    color = _PAST_DOT if is_current else _PAST_DOT_DIM
                dot_x = width - 3 - (len(shown) - 1 - i) * 3
                draw.point((dot_x, dot_y), fill=color)
        return img
