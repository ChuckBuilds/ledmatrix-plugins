"""
Unit conversion and formatting functions for the Flight Tracker plugin.

Supports granular per-metric unit selection (altitude_unit, speed_unit,
track_format, vr_unit) as well as the legacy imperial/metric system toggle.
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


# --- Raw conversions (internal feet / knots / fpm) ---

def meters_to_feet(m: float) -> float:
    return m * 3.28084

def feet_to_meters(ft: float) -> float:
    return ft / 3.28084

def ms_to_knots(ms: float) -> float:
    return ms * 1.94384

def knots_to_kmh(kts: float) -> float:
    return kts * 1.852

def ms_to_fpm(ms: float) -> float:
    return ms * 196.85


# --- Altitude ---

_ALT_CONVERTERS = {
    "ft": lambda ft: ft,
    "m": feet_to_meters,
    "km": lambda ft: feet_to_meters(ft) / 1000,
    "nmi": lambda ft: ft / 6076.12,
}

_ALT_UNIT_LABELS = {"ft": "ft", "m": "m", "km": "km", "nmi": "nmi"}


def format_altitude(feet: Optional[float], unit: str = "ft", compact: bool = True) -> str:
    """Format altitude with configurable unit.

    ``unit`` is one of ``ft``, ``m``, ``km``, ``nmi``.
    Legacy: passing ``system="imperial"`` or ``system="metric"`` still works
    via the compatibility wrapper below.
    """
    if feet is None:
        return "---"
    try:
        feet = float(feet)
    except (TypeError, ValueError):
        return "---"
    conv = _ALT_CONVERTERS.get(unit, _ALT_CONVERTERS["ft"])
    val = conv(max(0, feet))  # clamp negative altitudes to 0
    u = _ALT_UNIT_LABELS.get(unit, unit)
    if compact and abs(val) >= 1000:
        return f"{val / 1000:.1f}K{u}"
    return f"{round(val)}{u}"


# --- Speed ---

_SPD_CONVERTERS = {
    "kn": lambda kts: kts,
    "mph": lambda kts: kts * 1.15078,
    "kmh": knots_to_kmh,
    "ms": lambda kts: kts / 1.94384,
    "mach": lambda kts: kts / 661.5,  # approximate at sea level
}

_SPD_UNIT_LABELS = {"kn": "kn", "mph": "mph", "kmh": "kmh", "ms": "m/s", "mach": "M"}


def format_speed(knots: Optional[float], unit: str = "kn") -> str:
    """Format ground speed with configurable unit."""
    if knots is None:
        return "---"
    try:
        knots = float(knots)
    except (TypeError, ValueError):
        return "---"
    conv = _SPD_CONVERTERS.get(unit, _SPD_CONVERTERS["kn"])
    val = conv(knots)
    u = _SPD_UNIT_LABELS.get(unit, unit)
    if unit == "mach":
        return f"{val:.2f}{u}"
    return f"{round(val)}{u}"


# --- Track ---

_CARDINAL_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def format_track(degrees: Optional[float], fmt: str = "deg") -> str:
    """Format track/heading. ``fmt`` is ``deg`` or ``cardinal``."""
    if degrees is None:
        return "---"
    try:
        degrees = float(degrees)
    except (TypeError, ValueError):
        return "---"
    d = int(round(degrees)) % 360
    if fmt == "cardinal":
        return _CARDINAL_16[round(d / 22.5) % 16]
    return f"{d:03d}deg"


# --- Vertical Rate ---

_VR_CONVERTERS = {
    "fpm": lambda fpm: fpm,
    "fts": lambda fpm: fpm / 60,
    "ms": lambda fpm: fpm / 196.85,
    "mph": lambda fpm: fpm * 60 / 5280,
    "kmh": lambda fpm: fpm * 60 / 5280 * 1.60934,
}

_VR_UNIT_LABELS = {"fpm": "fpm", "fts": "ft/s", "ms": "m/s", "mph": "mph", "kmh": "kmh"}


def format_vrate(fpm: Optional[float], unit: str = "fpm", use_arrows: bool = True) -> str:
    """Format vertical rate.

    When ``use_arrows`` is True (default, used by area cards), renders
    with arrow characters (↑/↓/→).  When False (used by flight detail
    layouts), renders with explicit +/- sign.
    """
    if fpm is None:
        return "---"
    try:
        fpm = float(fpm)
    except (TypeError, ValueError):
        return "---"
    conv = _VR_CONVERTERS.get(unit, _VR_CONVERTERS["fpm"])
    val = conv(fpm)
    u = _VR_UNIT_LABELS.get(unit, unit)
    # Threshold in native unit: ~50 fpm equivalent in each unit system
    _threshold_map = {"ms": 0.25, "fts": 0.85, "mph": 0.6, "kmh": 0.6}
    threshold = _threshold_map.get(unit, 50)

    if use_arrows:
        if val > threshold:
            return f"\u2191{round(abs(val))}"
        elif val < -threshold:
            return f"\u2193{round(abs(val))}"
        else:
            return f"\u2192{round(abs(val))}"
    else:
        sign = "+" if val >= 0 else "-"
        return f"{sign}{round(abs(val))}{u}"


# --- Distance ---

def format_distance(miles: Optional[float], system: str = "imperial") -> str:
    """Format distance for display."""
    if miles is None:
        return "---"
    if system == "metric":
        val = miles * 1.60934
        u = "km"
    else:
        val = miles
        u = "mi"
    if val < 1:
        return f"{val:.2f}{u}"
    if val < 10:
        return f"{val:.1f}{u}"
    return f"{int(round(val))}{u}"


# --- Legacy compatibility wrappers ---
# These map the old system="imperial"/"metric" interface to the new per-unit API.

def _alt_unit_from_system(system: str) -> str:
    return "m" if system == "metric" else "ft"

def _spd_unit_from_system(system: str) -> str:
    return "kmh" if system == "metric" else "kn"

def _vr_unit_from_system(system: str) -> str:
    return "ms" if system == "metric" else "fpm"


def convert_altitude(feet: float, system: str = "imperial") -> float:
    u = _alt_unit_from_system(system)
    return _ALT_CONVERTERS.get(u, lambda x: x)(feet)

def convert_speed(knots: float, system: str = "imperial") -> float:
    u = _spd_unit_from_system(system)
    return _SPD_CONVERTERS.get(u, lambda x: x)(knots)

def convert_vrate(fpm: float, system: str = "imperial") -> float:
    u = _vr_unit_from_system(system)
    return _VR_CONVERTERS.get(u, lambda x: x)(fpm)

def convert_distance(miles: float, system: str = "imperial") -> float:
    return miles * 1.60934 if system == "metric" else miles

def altitude_unit(system: str = "imperial") -> str:
    return "m" if system == "metric" else "ft"

def speed_unit(system: str = "imperial") -> str:
    return "kmh" if system == "metric" else "kn"

def vrate_unit(system: str = "imperial") -> str:
    return "m/s" if system == "metric" else "fpm"

def distance_unit(system: str = "imperial") -> str:
    return "km" if system == "metric" else "mi"
