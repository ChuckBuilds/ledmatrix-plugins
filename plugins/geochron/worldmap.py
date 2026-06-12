"""Vendored world map: load GeoJSON and rasterize an equirectangular base map.

The rasterized map is tiled horizontally so that crop windows spanning the
+-180 degree antimeridian (used by the square/tall layout, which can center
on any longitude) don't need special-case wraparound logic - they're just a
normal `Image.crop()` rectangle on the tiled canvas.
"""

import json
import os

import numpy as np
from PIL import Image, ImageDraw

# Internal rasterization resolution: 0.5 degrees/pixel.
GRID_W = 720
GRID_H = 360

# The padded canvas tiles the base map this many times horizontally,
# covering longitude [-GRID_W/2 * COPIES, GRID_W/2 * COPIES) degrees in the
# `lon_to_x` coordinate space. 3 copies covers +-540 degrees, which fits any
# crop window centered anywhere in [-180, 180) with an extent up to 360 deg.
PAD_COPIES = 3
PADDED_W = GRID_W * PAD_COPIES

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "world-countries.geojson")


def lon_to_x(lon, grid_w=GRID_W):
    """Map a longitude in degrees (may be outside [-180, 180)) to an x pixel
    coordinate in the padded canvas."""
    return (lon + 180.0) / 360.0 * grid_w + grid_w


def lat_to_y(lat, grid_h=GRID_H):
    """Map a latitude in degrees to a y pixel coordinate in the base/padded canvas."""
    return (90.0 - lat) / 180.0 * grid_h


def _project(lon, lat, grid_w, grid_h):
    return ((lon + 180.0) / 360.0 * grid_w, (90.0 - lat) / 180.0 * grid_h)


def _draw_ring(draw, ring, fill, outline, grid_w, grid_h):
    pts = [_project(lon, lat, grid_w, grid_h) for lon, lat in ring]
    if len(pts) >= 3:
        draw.polygon(pts, fill=fill, outline=outline)


def _load_geojson(path=None):
    with open(path or DATA_PATH) as f:
        return json.load(f)


def render_base_map(ocean_color, land_color, coastline_color, geojson_path=None,
                     grid_w=GRID_W, grid_h=GRID_H):
    """Rasterize the vendored world map.

    Returns a padded PIL RGB image of size (grid_w * PAD_COPIES, grid_h),
    with the world repeated PAD_COPIES times horizontally.
    """
    data = _load_geojson(geojson_path)

    base = Image.new("RGB", (grid_w, grid_h), tuple(ocean_color))
    draw = ImageDraw.Draw(base)

    for feature in data["features"]:
        geom = feature["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            _draw_ring(draw, poly[0], tuple(land_color), tuple(coastline_color), grid_w, grid_h)
            for hole in poly[1:]:
                _draw_ring(draw, hole, tuple(ocean_color), tuple(coastline_color), grid_w, grid_h)

    padded = Image.new("RGB", (grid_w * PAD_COPIES, grid_h))
    for i in range(PAD_COPIES):
        padded.paste(base, (i * grid_w, 0))
    return padded


def tile_padded(arr):
    """Tile a (GRID_H, GRID_W) array PAD_COPIES times horizontally to match
    the padded base map width."""
    return np.tile(arr, (1, PAD_COPIES))
