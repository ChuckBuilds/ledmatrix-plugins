"""Solar position and day/night terminator computation.

Implements the NOAA simplified solar position algorithm (good to roughly
0.01 degrees, far more than needed for an LED panel) to find the subsolar
point - the location on Earth where the sun is directly overhead - for a
given UTC datetime, plus a vectorized terminator/twilight darkness mask over
a lat/lon grid.
"""

import math
from datetime import timezone
from functools import lru_cache

import numpy as np

# Twilight band boundaries: solar elevation (degrees below the horizon).
CIVIL_TWILIGHT_DEG = -6.0
NAUTICAL_TWILIGHT_DEG = -12.0
ASTRONOMICAL_TWILIGHT_DEG = -18.0
TWILIGHT_BAND_WIDTH_DEG = 6.0


def subsolar_point(dt):
    """Return (lat, lon, declination_rad) of the subsolar point for a UTC datetime.

    lat/lon are in degrees. declination_rad is also returned since the caller
    needs it for the terminator elevation calculation and it's cheap to reuse.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)

    day_of_year = dt.timetuple().tm_yday
    hour_utc = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour_utc - 12) / 24)

    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )  # minutes

    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )  # radians

    subsolar_lat = math.degrees(decl)

    true_solar_time_min = hour_utc * 60 + eqtime
    subsolar_lon = ((-15.0 * (true_solar_time_min / 60.0 - 12.0) + 180) % 360) - 180

    return subsolar_lat, subsolar_lon, decl


@lru_cache(maxsize=4)
def _grid(grid_w, grid_h):
    """Build (lat_grid, lon_grid) 2D arrays covering the whole world.

    Cached since the grid only depends on its dimensions, which are fixed
    constants in practice.
    """
    lons = np.linspace(-180, 180, grid_w, endpoint=False) + 180.0 / grid_w
    lats = np.linspace(90, -90, grid_h, endpoint=False) - 90.0 / grid_h
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    return lat_grid, lon_grid


def solar_elevation(lat_grid, lon_grid, decl, subsolar_lon):
    """Solar elevation angle (degrees) at every point of a lat/lon grid."""
    lat_rad = np.radians(lat_grid)
    sin_alt = np.sin(lat_rad) * math.sin(decl) + np.cos(lat_rad) * math.cos(decl) * np.cos(
        np.radians(lon_grid - subsolar_lon)
    )
    return np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))


def darkness_mask(alt_deg, show_bands=True):
    """Darkness factor d in [0, 1] for each grid point (0=day, 1=night).

    With show_bands, the terminator ramps smoothly through civil, nautical,
    and astronomical twilight (each a 6 degree band) instead of a hard line.
    """
    if not show_bands:
        return (alt_deg <= 0).astype(np.float64)

    w = TWILIGHT_BAND_WIDTH_DEG
    conditions = [
        alt_deg > 0,
        alt_deg > CIVIL_TWILIGHT_DEG,
        alt_deg > NAUTICAL_TWILIGHT_DEG,
        alt_deg > ASTRONOMICAL_TWILIGHT_DEG,
    ]
    choices = [
        np.zeros_like(alt_deg),
        (0 - alt_deg) / w * (1 / 3),
        (1 / 3) + (CIVIL_TWILIGHT_DEG - alt_deg) / w * (1 / 3),
        (2 / 3) + (NAUTICAL_TWILIGHT_DEG - alt_deg) / w * (1 / 3),
    ]
    return np.select(conditions, choices, default=1.0)


def compute_terminator(dt, grid_w, grid_h, show_bands=True):
    """Compute the darkness mask and subsolar point for a UTC datetime.

    Returns (darkness, subsolar_lat, subsolar_lon) where darkness is a
    (grid_h, grid_w) float array in [0, 1].
    """
    subsolar_lat, subsolar_lon, decl = subsolar_point(dt)
    lat_grid, lon_grid = _grid(grid_w, grid_h)
    alt_deg = solar_elevation(lat_grid, lon_grid, decl, subsolar_lon)
    darkness = darkness_mask(alt_deg, show_bands=show_bands)
    return darkness, subsolar_lat, subsolar_lon
