"""
Utility functions for the Flight Tracker plugin.

Pure functions with no state — haversine distance, altitude-to-color mapping,
aircraft classification, and callsign filtering.
"""

import math
from typing import Dict, List, Optional, Tuple


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two lat/lon points in miles."""
    R = 3959  # Earth's radius in miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two lat/lon points in kilometers."""
    return haversine_miles(lat1, lon1, lat2, lon2) * 1.60934


def altitude_to_color(altitude: float, color_bands: Dict[str, List[int]]) -> Tuple[int, int, int]:
    """Convert altitude (feet) to an RGB color using smooth gradient interpolation.

    Args:
        altitude: Altitude in feet.
        color_bands: Dict mapping altitude strings to [R, G, B] lists.
                     e.g. {'0': [255, 100, 0], '10000': [0, 200, 150]}

    Returns:
        (R, G, B) tuple.
    """
    breakpoints = sorted([(int(k), v) for k, v in color_bands.items()])

    if altitude <= breakpoints[0][0]:
        return tuple(breakpoints[0][1])
    if altitude >= breakpoints[-1][0]:
        return tuple(breakpoints[-1][1])

    for i in range(len(breakpoints) - 1):
        alt1, color1 = breakpoints[i]
        alt2, color2 = breakpoints[i + 1]

        if alt1 <= altitude <= alt2:
            ratio = (altitude - alt1) / (alt2 - alt1)
            r = max(0, min(255, int(color1[0] + (color2[0] - color1[0]) * ratio)))
            g = max(0, min(255, int(color1[1] + (color2[1] - color1[1]) * ratio)))
            b = max(0, min(255, int(color1[2] + (color2[2] - color1[2]) * ratio)))
            return (r, g, b)

    return (255, 255, 255)


def categorize_aircraft(callsign: str, airline_prefixes: Optional[List[str]] = None) -> str:
    """Categorize aircraft based on callsign patterns.

    Returns one of: 'Military', 'Cargo', 'Airline', 'International',
    'Commercial', 'Private', 'General Aviation', 'Unknown'.
    """
    if not callsign:
        return "Unknown"

    cs = callsign.upper()
    if airline_prefixes is None:
        airline_prefixes = []

    # Military
    if cs.startswith(('C-', 'CF-', 'AF-', 'NATO-', 'USAF-', 'USN-', 'USMC-', 'USCG-', 'RAZOR', 'VADER', 'SPIRIT')):
        return "Military"

    # Cargo
    cargo = ['UPS', 'FDX', 'GTI', 'ABX', 'CPZ', 'DHL', 'TNT', 'CARGO']
    for prefix in cargo:
        if cs.startswith(prefix):
            return "Cargo"

    # Major airlines (includes QFA=Qantas, SIA=Singapore, CAL=China Airlines)
    major = ['AAL', 'UAL', 'DAL', 'SWA', 'JBU', 'B6', 'WN', 'AA', 'UA', 'DL', 'QFA', 'SIA', 'CAL']
    for prefix in major:
        if cs.startswith(prefix):
            return "Airline"

    # User-configured airline prefixes
    for prefix in airline_prefixes:
        if cs.startswith(prefix):
            return "Airline"

    # International registrations
    if cs.startswith(('G-', 'F-', 'D-', 'I-', 'HB-', 'OE-', 'PH-', 'SE-', 'LN-', 'OY-',
                      'VH-', 'C-G', 'C-F', 'JA-', 'B-', 'HL-', '9V-', 'A6-', 'VT-', 'PK-',
                      'HS-', 'RP-', 'ZS-', '4X-', 'SU-', 'RA-', 'UR-', 'EW-', 'S7-', 'U6-',
                      'FV-', 'DP-', 'P4-', 'P5-', 'P6-', 'P7-', 'P8-', 'P9-', 'P0-',
                      'P1-', 'P2-', 'P3-')):
        return "International"

    # N-prefix (US registration)
    if cs.startswith('N') and len(callsign) >= 4:
        return "Commercial" if len(callsign) >= 6 else "Private"

    # General length heuristics
    if len(callsign) >= 4:
        if any(c.isdigit() for c in cs):
            return "Commercial" if len(callsign) >= 6 else "General Aviation"
        if len(callsign) >= 5:
            return "Commercial"
        return "General Aviation"

    if len(callsign) <= 3:
        return "Unknown"

    return "General Aviation"


def is_callsign_worth_fetching(
    callsign: str,
    min_length: int = 4,
    airline_prefixes: Optional[List[str]] = None,
) -> bool:
    """Determine if a callsign is worth fetching flight plan data for.

    Filters out military, private, and unknown callsigns to save API budget.
    """
    if not callsign or len(callsign) < min_length:
        return False

    cs = callsign.upper()

    # Major US airlines
    major_us = ['AAL', 'UAL', 'DAL', 'SWA', 'JBU', 'B6', 'WN', 'AA', 'UA', 'DL', 'ASQ', 'ENY', 'FFT', 'NKS', 'F9', 'G4']
    for prefix in major_us:
        if cs.startswith(prefix):
            return True

    # International airlines
    intl = ['BAW', 'AFR', 'LUF', 'KLM', 'SAS', 'IBE', 'EZY', 'RYR', 'WZZ', 'EIN',
            'DLH', 'AUA', 'SWR', 'AZA', 'IBB', 'VLG', 'TAP']
    for prefix in intl:
        if cs.startswith(prefix):
            return True

    # Cargo airlines
    cargo = ['UPS', 'FDX', 'GTI', 'ABX', 'CPZ', 'DHL', 'TNT']
    for prefix in cargo:
        if cs.startswith(prefix):
            return True

    # Asia-Pacific airlines (QFA=Qantas, SIA=Singapore, CAL=China Airlines)
    apac = ['QFA', 'SIA', 'CAL']
    for prefix in apac:
        if cs.startswith(prefix):
            return True

    # User-configured prefixes
    if airline_prefixes:
        for prefix in airline_prefixes:
            if cs.startswith(prefix):
                return True

    # International registrations
    if cs.startswith(('G-', 'F-', 'D-', 'I-', 'HB-', 'OE-', 'PH-', 'SE-', 'LN-', 'OY-',
                      'VH-', 'C-G', 'C-F', 'JA-', 'B-', 'HL-', '9V-', 'A6-', 'VT-', 'PK-',
                      'HS-', 'RP-', 'ZS-', '4X-', 'SU-', 'RA-', 'UR-', 'EW-', 'S7-', 'U6-',
                      'FV-', 'DP-')):
        return True

    # Skip military and private registrations
    # Note: N-registrations with 6+ chars are treated as Commercial by
    # categorize_aircraft(), so only exclude short N-callsigns (GA aircraft)
    if cs.startswith('N') and len(cs) < 6:
        return False
    if cs.startswith(('C-', 'CF-', 'AF-', 'NATO-', 'USAF-', 'USN-', 'USMC-', 'USCG-')):
        return False

    return False
