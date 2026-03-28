"""
Unit conversion and formatting functions for the Flight Tracker plugin.

Handles imperial/metric conversions and display-friendly formatting for
altitude, speed, vertical rate, and distance.
"""

from typing import Any, Callable, Optional


# --- Null-safe formatting ---

def null_safe(value: Any, fmt_func: Optional[Callable] = None, default: str = "---") -> str:
    """Format a value safely, returning *default* if the value is None or missing."""
    if value is None:
        return default
    try:
        return fmt_func(value) if fmt_func else str(value)
    except (ValueError, TypeError):
        return default


# --- Unit conversions ---

def meters_to_feet(m: float) -> float:
    """Convert meters to feet."""
    return m * 3.28084


def feet_to_meters(ft: float) -> float:
    """Convert feet to meters."""
    return ft / 3.28084


def ms_to_knots(ms: float) -> float:
    """Convert meters/second to knots."""
    return ms * 1.94384


def knots_to_kmh(kts: float) -> float:
    """Convert knots to km/h."""
    return kts * 1.852


def ms_to_fpm(ms: float) -> float:
    """Convert meters/second to feet/minute."""
    return ms * 196.85


# --- System-aware conversions ---

def convert_altitude(feet: float, system: str = "imperial") -> float:
    """Convert altitude from feet to the target unit system."""
    if system == "metric":
        return feet_to_meters(feet)
    return feet


def convert_speed(knots: float, system: str = "imperial") -> float:
    """Convert speed from knots to the target unit system."""
    if system == "metric":
        return knots_to_kmh(knots)
    return knots


def convert_vrate(fpm: float, system: str = "imperial") -> float:
    """Convert vertical rate from ft/min to the target unit system."""
    if system == "metric":
        return fpm / 196.85  # back to m/s
    return fpm


def convert_distance(miles: float, system: str = "imperial") -> float:
    """Convert distance from miles to the target unit system."""
    if system == "metric":
        return miles * 1.60934
    return miles


# --- Display formatting ---

def format_altitude(feet: Optional[float], system: str = "imperial", compact: bool = True) -> str:
    """Format altitude for display.

    In compact mode, values >= 1000 are shown as e.g. ``38.6K``.
    Below 1000, the exact integer is shown.
    """
    if feet is None:
        return "---"
    val = convert_altitude(feet, system)
    unit = "m" if system == "metric" else "ft"
    if compact and abs(val) >= 1000:
        return f"{val / 1000:.1f}K"
    return f"{int(round(val))}{unit}"


def format_speed(knots: Optional[float], system: str = "imperial") -> str:
    """Format ground speed for display."""
    if knots is None:
        return "---"
    val = convert_speed(knots, system)
    unit = "km/h" if system == "metric" else "kt"
    return f"{int(round(val))}{unit}"


def format_track(degrees: Optional[float]) -> str:
    """Format track/heading for display."""
    if degrees is None:
        return "---"
    return f"{int(round(degrees)) % 360:03d}\u00b0"


def format_vrate(fpm: Optional[float], system: str = "imperial") -> str:
    """Format vertical rate with directional arrow.

    Uses a dead band of +/-50 ft/min (or ~0.25 m/s) for level flight.
    """
    if fpm is None:
        return "---"
    val = convert_vrate(fpm, system)
    threshold = 0.25 if system == "metric" else 50
    if val > threshold:
        arrow = "\u2191"  # ↑
    elif val < -threshold:
        arrow = "\u2193"  # ↓
    else:
        arrow = "\u2192"  # →
    return f"{arrow}{int(round(abs(val)))}"


def format_distance(miles: Optional[float], system: str = "imperial") -> str:
    """Format distance for display."""
    if miles is None:
        return "---"
    val = convert_distance(miles, system)
    unit = "km" if system == "metric" else "mi"
    if val < 1:
        return f"{val:.2f}{unit}"
    if val < 10:
        return f"{val:.1f}{unit}"
    return f"{int(round(val))}{unit}"


def altitude_unit(system: str = "imperial") -> str:
    """Return the altitude unit label for the given system."""
    return "m" if system == "metric" else "ft"


def speed_unit(system: str = "imperial") -> str:
    """Return the speed unit label for the given system."""
    return "km/h" if system == "metric" else "kt"


def vrate_unit(system: str = "imperial") -> str:
    """Return the vertical rate unit label for the given system."""
    return "m/s" if system == "metric" else "fpm"


def distance_unit(system: str = "imperial") -> str:
    """Return the distance unit label for the given system."""
    return "km" if system == "metric" else "mi"
