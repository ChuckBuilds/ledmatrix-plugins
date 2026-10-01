"""
Utility functions for the Flight Tracker plugin.

Pure functions with no state — haversine distance, altitude-to-color mapping,
aircraft classification, callsign filtering, and position-age parsing.
"""

import email.utils
import math
from datetime import timezone
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


<<<<<<< HEAD
def plane_offset_miles(center_lat: float, center_lon: float,
                       lat: float, lon: float) -> Tuple[float, float]:
    """(east, north) statute miles from the centre to lat/lon, as the map places it.

    The map projection's own math (distance along the initial bearing), before
    it is scaled to pixels, so a difference of two of these is a displacement
    on the map at any panel size.
    """
    distance = haversine_miles(center_lat, center_lon, lat, lon)
    lat1 = math.radians(center_lat)
    lat2 = math.radians(lat)
    delta_lon = math.radians(lon - center_lon)
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    bearing = math.atan2(x, y)
    return distance * math.sin(bearing), distance * math.cos(bearing)


=======
>>>>>>> origin/main
# ---------------------------------------------------------------------------
# Position time
#
# Every source says how old each position was, by its own clock: readsb /
# SkyAware and adsb.fi / adsb.lol as seconds before the payload's ``now``,
# OpenSky and FR24 as epoch times. Recording that age (rather than assuming
# "now") is what lets the map later place an aircraft where it is between
# polls. The per-source helpers return the raw age in seconds, or None when
# the feed gave nothing usable; position_age() turns that into the recorded
# fields. The feeds are unofficial or loosely specified, so unusable is
# treated as fresh (0) instead of raising -- a bad age must never cost the
# aircraft itself.
# ---------------------------------------------------------------------------

#: Ceiling on a recorded position age; anything older is recorded at this and
#: flagged stale. A feed reporting minutes describes a stale target, not a
#: span worth moving an aircraft across.
MAX_POS_AGE_SECONDS = 30.0

#: How far in the future an FR24 position time may sit and still be believed
#: (as age 0): clocks drift. feed.js has no published layout; index 10 is the
#: position time in the layout the community documents, and a time further
#: ahead means the layout moved or a clock is wrong.
FR24_MAX_CLOCK_SKEW_SECONDS = 120.0

#: The feed.js query's ``maxage``: FR24 answers with positions up to this old,
#: so an index-10 time that far back is a real (stale) position. Further back
#: is not a time the query can return.
FR24_MAX_AGE_SECONDS = 14400

#: The longest a source plausibly holds a payload between stamping and sending
#: it. OpenSky's ``time`` is rounded down to its 5/10 s resolution and trails
#: the send by 5-15 s; readsb's ``now`` by a second or a few. A bigger gap is a
#: disagreeing clock, not a delay, and is ignored.
MAX_PAYLOAD_LAG_SECONDS = 60.0


def is_number(value) -> bool:
    """A finite int or float, not a bool (JSON true would otherwise pass)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        # JSON integers have no size limit; one too big for a float is garbage.
        return False


def clamp_pos_age(value) -> float:
    """A position age in seconds, clamped to 0..MAX_POS_AGE_SECONDS; garbage is 0."""
    if not is_number(value):
        return 0.0
    return min(max(float(value), 0.0), MAX_POS_AGE_SECONDS)


def position_age(raw) -> Tuple[float, bool]:
    """``(pos_age, pos_stale)`` for a raw position age in seconds.

    pos_age is clamped to 0..MAX_POS_AGE_SECONDS, so on its own it can no
    longer say a position was older than that; pos_stale keeps it (too old to
    carry the aircraft on from). Unusable (None, garbage) is ``(0.0, False)``.
    """
    if not is_number(raw):
        return 0.0, False
    return clamp_pos_age(raw), raw > MAX_POS_AGE_SECONDS


def http_date(response) -> Optional[float]:
    """A response's Date header as epoch seconds, or None if missing or unreadable.

    That is the server's clock when it answered, truncated to the second.
    """
    try:
        value = getattr(response, 'headers', None).get('Date')
        if not value:
            return None
        when = email.utils.parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.timestamp()
    except (AttributeError, TypeError, ValueError, IndexError, OverflowError):
        return None


def source_send_time(response, received_wall: float) -> float:
    """When the source sent ``response``, by its own clock where it says.

    The Date header drops the fraction of a second, so half of one is put
    back. Without a usable one, our clock at receipt stands in; payload_lag()
    bounds what a wrong clock can do with it.
    """
    sent = http_date(response)
    return sent + 0.5 if sent is not None else received_wall


def payload_lag(payload_time, sent_wall) -> float:
    """Seconds between a payload's own timestamp and its sending.

    A payload's ages count back from its own timestamp (readsb ``now``,
    OpenSky ``time``), so this is what they leave out. readsb's ``now`` is
    epoch seconds from SkyAware and adsb.fi but milliseconds from adsb.lol.
    0 when either time is unusable or the gap is not plausible.
    """
    if not (is_number(payload_time) and is_number(sent_wall)):
        return 0.0
    if payload_time > 1e11:  # epoch milliseconds (seconds reach 1e11 in the year 5138)
        payload_time = payload_time / 1000.0
    lag = sent_wall - payload_time
    return lag if 0.0 < lag <= MAX_PAYLOAD_LAG_SECONDS else 0.0


def seen_pos_age(ac: Dict, lag: float = 0.0) -> Optional[float]:
    """Raw position age from a readsb-style record (SkyAware, adsb.fi, adsb.lol).

    ``seen_pos`` is seconds since the last position message, counted back from
    the payload's ``now``; ``seen``, since the last message of any kind, stands
    in when a feed omits the first. ``lag`` (payload_lag) is how much older
    they all were by the time the payload was sent. None if neither is usable.
    """
    for key in ('seen_pos', 'seen'):
        value = ac.get(key)
        if is_number(value):
            return value + lag
    return None


def epoch_age(now, then) -> Optional[float]:
    """``now - then`` as a raw position age, or None if either is unusable."""
    if not (is_number(now) and is_number(then)):
        return None
    return now - then


def fr24_pos_age(entry, received_wall: float) -> Optional[float]:
    """Raw position age from an FR24 feed.js entry, or None if its time is implausible.

    A time up to FR24_MAX_AGE_SECONDS back is a real position, however old: it
    is recorded as stale rather than taken for fresh, so an older position can
    never look newer than a younger one. Further back, or more than
    FR24_MAX_CLOCK_SKEW_SECONDS ahead, is not a position time at all.
    """
    stamp = entry[10] if len(entry) > 10 else None
    if not is_number(stamp):
        return None
    age = received_wall - stamp
    if not -FR24_MAX_CLOCK_SKEW_SECONDS <= age <= FR24_MAX_AGE_SECONDS:
        return None
    return age


def is_real_track(value) -> bool:
    """True for a usable track/heading in degrees.

    Every source falls back to 0 when it has no track, and 0 is also due
    north, so the heading alone cannot say which it was; this is asked of the
    raw field before that fallback.
    """
    return is_number(value) and 0 <= value <= 360


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
