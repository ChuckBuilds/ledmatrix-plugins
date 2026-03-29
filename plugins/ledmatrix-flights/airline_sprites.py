"""
Airline logo pixel art sprites for LED matrix display.

Each sprite is an 8×8 pixel design stored as a list of (x, y, r, g, b) tuples.
Multi-color sprites use per-pixel colors; single-color sprites can be tinted
at render time.

Sprites are designed to be recognizable at 4mm pixel pitch on a 128×32 matrix.
These are original geometric designs inspired by airline brand colors —
not copies of trademarked logos.
"""

from typing import Any, Dict, List, Optional, Tuple


# Type alias: each pixel is (x, y, r, g, b)
SpritePixel = Tuple[int, int, int, int, int]
# Type alias: sprite definition
SpriteData = Dict[str, Any]


def _mono(pixels: List[Tuple[int, int]], r: int, g: int, b: int) -> List[SpritePixel]:
    """Helper: convert (x,y) list + single color to [(x,y,r,g,b), ...]."""
    return [(x, y, r, g, b) for x, y in pixels]


# ---------------------------------------------------------------------------
# Airline sprite definitions (8×8 grid, origin top-left)
# ---------------------------------------------------------------------------

SPRITES: Dict[str, SpriteData] = {

    # --- US Major Airlines ---

    "delta": {
        "name": "Delta",
        "icao": ["DAL"],
        "iata": ["DL"],
        "pixels": _mono([
            # Blue triangle/widget pointing up
                        (3, 0), (4, 0),
                   (2, 1), (3, 1), (4, 1), (5, 1),
              (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),
         (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3),
         # Lower half: red accent stripe
         (0, 4), (1, 4), (2, 4),                (5, 4), (6, 4), (7, 4),
              (1, 5), (2, 5),                (5, 5), (6, 5),
        ], 0, 48, 135),  # Delta blue
    },

    "american": {
        "name": "American",
        "icao": ["AAL"],
        "iata": ["AA"],
        "pixels": [
            # Simplified eagle/flight symbol: angled wing shape
            # Blue top section
            (3, 0, 0, 47, 108), (4, 0, 0, 47, 108),
            (2, 1, 0, 47, 108), (3, 1, 0, 47, 108), (4, 1, 0, 47, 108), (5, 1, 0, 47, 108),
            # White stripe
            (1, 2, 200, 200, 200), (2, 2, 200, 200, 200), (3, 2, 200, 200, 200),
            (4, 2, 200, 200, 200), (5, 2, 200, 200, 200), (6, 2, 200, 200, 200),
            # Red bottom section
            (0, 3, 180, 0, 0), (1, 3, 180, 0, 0), (2, 3, 180, 0, 0), (3, 3, 180, 0, 0),
            (4, 3, 180, 0, 0), (5, 3, 180, 0, 0), (6, 3, 180, 0, 0), (7, 3, 180, 0, 0),
            # Tail fin
            (3, 4, 180, 0, 0), (4, 4, 180, 0, 0),
            (3, 5, 0, 47, 108), (4, 5, 0, 47, 108),
        ],
    },

    "united": {
        "name": "United",
        "icao": ["UAL"],
        "iata": ["UA"],
        "pixels": [
            # Globe/tulip shape in blue
            (2, 0, 0, 40, 120), (3, 0, 0, 40, 120), (4, 0, 0, 40, 120), (5, 0, 0, 40, 120),
            (1, 1, 0, 40, 120), (2, 1, 0, 80, 180), (3, 1, 0, 80, 180), (4, 1, 0, 80, 180),
            (5, 1, 0, 80, 180), (6, 1, 0, 40, 120),
            (1, 2, 0, 40, 120), (2, 2, 0, 80, 180), (3, 2, 255, 255, 255), (4, 2, 255, 255, 255),
            (5, 2, 0, 80, 180), (6, 2, 0, 40, 120),
            (1, 3, 0, 40, 120), (2, 3, 0, 80, 180), (3, 3, 0, 80, 180), (4, 3, 0, 80, 180),
            (5, 3, 0, 80, 180), (6, 3, 0, 40, 120),
            (2, 4, 0, 40, 120), (3, 4, 0, 40, 120), (4, 4, 0, 40, 120), (5, 4, 0, 40, 120),
        ],
    },

    "southwest": {
        "name": "Southwest",
        "icao": ["SWA"],
        "iata": ["WN"],
        "pixels": [
            # Heart shape in Southwest colors
            (1, 0, 255, 0, 0), (2, 0, 255, 0, 0),         (5, 0, 255, 0, 0), (6, 0, 255, 0, 0),
            (0, 1, 255, 0, 0), (1, 1, 255, 80, 0), (2, 1, 255, 80, 0), (3, 1, 255, 0, 0),
            (4, 1, 255, 0, 0), (5, 1, 255, 80, 0), (6, 1, 255, 80, 0), (7, 1, 255, 0, 0),
            (0, 2, 255, 200, 0), (1, 2, 255, 200, 0), (2, 2, 255, 200, 0), (3, 2, 255, 200, 0),
            (4, 2, 255, 200, 0), (5, 2, 255, 200, 0), (6, 2, 255, 200, 0), (7, 2, 255, 200, 0),
            (1, 3, 255, 200, 0), (2, 3, 255, 200, 0), (3, 3, 255, 200, 0),
            (4, 3, 255, 200, 0), (5, 3, 255, 200, 0), (6, 3, 255, 200, 0),
            (2, 4, 0, 100, 200), (3, 4, 0, 100, 200), (4, 4, 0, 100, 200), (5, 4, 0, 100, 200),
            (3, 5, 0, 100, 200), (4, 5, 0, 100, 200),
        ],
    },

    "jetblue": {
        "name": "JetBlue",
        "icao": ["JBU"],
        "iata": ["B6"],
        "pixels": _mono([
            # Rounded blue shape (tail design)
            (2, 0), (3, 0), (4, 0), (5, 0),
            (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
            (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2),
            (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3),
            (1, 4), (2, 4), (3, 4), (4, 4), (5, 4), (6, 4),
            (2, 5), (3, 5), (4, 5), (5, 5),
        ], 0, 80, 200),  # JetBlue blue
    },

    "spirit": {
        "name": "Spirit",
        "icao": ["NKS"],
        "iata": ["NK"],
        "pixels": _mono([
            # Bold yellow S-curve / swoosh
            (2, 0), (3, 0), (4, 0), (5, 0), (6, 0),
            (1, 1), (2, 1),
            (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
                                    (4, 3), (5, 3), (6, 3),
                                              (5, 4), (6, 4),
            (1, 5), (2, 5), (3, 5), (4, 5), (5, 5),
        ], 255, 200, 0),  # Spirit yellow
    },

    "frontier": {
        "name": "Frontier",
        "icao": ["FFT"],
        "iata": ["F9"],
        "pixels": _mono([
            # Animal face silhouette (simplified)
            (2, 0), (3, 0),         (5, 0), (6, 0),
            (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
            (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),
            (2, 3),                         (5, 3),
            (1, 4), (2, 4), (3, 4), (4, 4), (5, 4), (6, 4),
            (2, 5), (3, 5), (4, 5), (5, 5),
        ], 0, 150, 80),  # Frontier green
    },

    # --- International Airlines ---

    "british": {
        "name": "British Airways",
        "icao": ["BAW"],
        "iata": ["BA"],
        "pixels": [
            # Union Jack simplified: red cross on blue with white edges
            (0, 0, 0, 0, 128), (1, 0, 0, 0, 128), (2, 0, 0, 0, 128), (3, 0, 255, 255, 255),
            (4, 0, 255, 255, 255), (5, 0, 0, 0, 128), (6, 0, 0, 0, 128), (7, 0, 0, 0, 128),
            (0, 1, 0, 0, 128), (1, 1, 0, 0, 128), (2, 1, 0, 0, 128), (3, 1, 200, 0, 0),
            (4, 1, 200, 0, 0), (5, 1, 0, 0, 128), (6, 1, 0, 0, 128), (7, 1, 0, 0, 128),
            (0, 2, 255, 255, 255), (1, 2, 255, 255, 255), (2, 2, 255, 255, 255), (3, 2, 200, 0, 0),
            (4, 2, 200, 0, 0), (5, 2, 255, 255, 255), (6, 2, 255, 255, 255), (7, 2, 255, 255, 255),
            (0, 3, 200, 0, 0), (1, 3, 200, 0, 0), (2, 3, 200, 0, 0), (3, 3, 200, 0, 0),
            (4, 3, 200, 0, 0), (5, 3, 200, 0, 0), (6, 3, 200, 0, 0), (7, 3, 200, 0, 0),
            (0, 4, 255, 255, 255), (1, 4, 255, 255, 255), (2, 4, 255, 255, 255), (3, 4, 200, 0, 0),
            (4, 4, 200, 0, 0), (5, 4, 255, 255, 255), (6, 4, 255, 255, 255), (7, 4, 255, 255, 255),
            (0, 5, 0, 0, 128), (1, 5, 0, 0, 128), (2, 5, 0, 0, 128), (3, 5, 200, 0, 0),
            (4, 5, 200, 0, 0), (5, 5, 0, 0, 128), (6, 5, 0, 0, 128), (7, 5, 0, 0, 128),
        ],
    },

    "lufthansa": {
        "name": "Lufthansa",
        "icao": ["DLH"],
        "iata": ["LH"],
        "pixels": [
            # Crane in circle: simplified to bird shape in yellow circle
            (2, 0, 0, 30, 80), (3, 0, 0, 30, 80), (4, 0, 0, 30, 80), (5, 0, 0, 30, 80),
            (1, 1, 0, 30, 80), (2, 1, 255, 200, 0), (3, 1, 255, 200, 0), (4, 1, 255, 200, 0),
            (5, 1, 255, 200, 0), (6, 1, 0, 30, 80),
            (0, 2, 0, 30, 80), (1, 2, 255, 200, 0), (2, 2, 255, 255, 100), (3, 2, 255, 200, 0),
            (4, 2, 255, 200, 0), (5, 2, 255, 255, 100), (6, 2, 255, 200, 0), (7, 2, 0, 30, 80),
            (0, 3, 0, 30, 80), (1, 3, 255, 200, 0), (2, 3, 255, 200, 0), (3, 3, 255, 255, 100),
            (4, 3, 255, 255, 100), (5, 3, 255, 200, 0), (6, 3, 255, 200, 0), (7, 3, 0, 30, 80),
            (1, 4, 0, 30, 80), (2, 4, 255, 200, 0), (3, 4, 255, 200, 0), (4, 4, 255, 200, 0),
            (5, 4, 255, 200, 0), (6, 4, 0, 30, 80),
            (2, 5, 0, 30, 80), (3, 5, 0, 30, 80), (4, 5, 0, 30, 80), (5, 5, 0, 30, 80),
        ],
    },

    "ryanair": {
        "name": "Ryanair",
        "icao": ["RYR"],
        "iata": ["FR"],
        "pixels": _mono([
            # Harp simplified: vertical lines with curve
            (1, 0), (3, 0), (5, 0), (7, 0),
            (1, 1), (3, 1), (5, 1), (7, 1),
            (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2),
            (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3),
            (1, 4), (3, 4), (5, 4), (7, 4),
            (1, 5), (3, 5), (5, 5),
        ], 0, 50, 150),  # Ryanair dark blue
    },

    "emirates": {
        "name": "Emirates",
        "icao": ["UAE"],
        "iata": ["EK"],
        "pixels": _mono([
            # Simplified Arabic calligraphy / swoosh in red
                        (3, 0), (4, 0), (5, 0), (6, 0),
                  (2, 1), (3, 1),
            (1, 2), (2, 2),
            (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3),
                                    (4, 4), (5, 4), (6, 4),
                              (3, 5), (4, 5),
        ], 200, 0, 0),  # Emirates red
    },

    # --- Cargo Airlines ---

    "fedex": {
        "name": "FedEx",
        "icao": ["FDX"],
        "iata": ["FX"],
        "pixels": [
            # Purple and orange split with arrow
            (0, 0, 75, 0, 130), (1, 0, 75, 0, 130), (2, 0, 75, 0, 130), (3, 0, 75, 0, 130),
            (0, 1, 75, 0, 130), (1, 1, 75, 0, 130), (2, 1, 75, 0, 130), (3, 1, 75, 0, 130),
            (0, 2, 75, 0, 130), (1, 2, 75, 0, 130), (2, 2, 75, 0, 130), (3, 2, 75, 0, 130),
            # Arrow shape pointing right
            (4, 0, 255, 102, 0), (5, 0, 255, 102, 0),
            (4, 1, 255, 102, 0), (5, 1, 255, 102, 0), (6, 1, 255, 102, 0),
            (4, 2, 255, 102, 0), (5, 2, 255, 102, 0), (6, 2, 255, 102, 0), (7, 2, 255, 102, 0),
            (4, 3, 255, 102, 0), (5, 3, 255, 102, 0), (6, 3, 255, 102, 0),
            (4, 4, 255, 102, 0), (5, 4, 255, 102, 0),
            (0, 3, 75, 0, 130), (1, 3, 75, 0, 130), (2, 3, 75, 0, 130), (3, 3, 75, 0, 130),
            (0, 4, 75, 0, 130), (1, 4, 75, 0, 130), (2, 4, 75, 0, 130), (3, 4, 75, 0, 130),
        ],
    },

    "ups": {
        "name": "UPS",
        "icao": ["UPS"],
        "iata": ["5X"],
        "pixels": [
            # Brown shield with gold bow
            (2, 0, 100, 65, 23), (3, 0, 100, 65, 23), (4, 0, 100, 65, 23), (5, 0, 100, 65, 23),
            (1, 1, 100, 65, 23), (2, 1, 255, 200, 0), (3, 1, 255, 200, 0),
            (4, 1, 255, 200, 0), (5, 1, 255, 200, 0), (6, 1, 100, 65, 23),
            (0, 2, 100, 65, 23), (1, 2, 100, 65, 23), (2, 2, 100, 65, 23),
            (3, 2, 100, 65, 23), (4, 2, 100, 65, 23), (5, 2, 100, 65, 23),
            (6, 2, 100, 65, 23), (7, 2, 100, 65, 23),
            (0, 3, 100, 65, 23), (1, 3, 100, 65, 23), (2, 3, 100, 65, 23),
            (3, 3, 100, 65, 23), (4, 3, 100, 65, 23), (5, 3, 100, 65, 23),
            (6, 3, 100, 65, 23), (7, 3, 100, 65, 23),
            (1, 4, 100, 65, 23), (2, 4, 100, 65, 23), (3, 4, 100, 65, 23),
            (4, 4, 100, 65, 23), (5, 4, 100, 65, 23), (6, 4, 100, 65, 23),
            (2, 5, 100, 65, 23), (3, 5, 100, 65, 23), (4, 5, 100, 65, 23), (5, 5, 100, 65, 23),
        ],
    },

    # --- Generic fallback ---

    "generic_plane": {
        "name": "Aircraft",
        "icao": [],
        "iata": [],
        "pixels": _mono([
            # 8×8 airplane silhouette (larger version of the 5×5)
                        (3, 0), (4, 0),
                        (3, 1), (4, 1),
            (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2),
                  (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3),
                        (3, 4), (4, 4),
                  (1, 5), (2, 5), (3, 5), (4, 5), (5, 5), (6, 5),
                        (3, 6), (4, 6),
        ], 200, 200, 200),
    },
}

# Build lookup indices once at module load
_BY_ICAO: Dict[str, str] = {}
_BY_IATA: Dict[str, str] = {}

for _key, _data in SPRITES.items():
    for _code in _data.get("icao", []):
        _BY_ICAO[_code.upper()] = _key
    for _code in _data.get("iata", []):
        _BY_IATA[_code.upper()] = _key


def get_sprite_key(airline_icao: str = "", airline_iata: str = "", callsign: str = "") -> Optional[str]:
    """Resolve an airline to a sprite key using ICAO code, IATA code, or callsign prefix.

    Returns the sprite key (e.g., 'delta') or None if no match found.
    """
    if airline_icao:
        key = _BY_ICAO.get(airline_icao.upper())
        if key:
            return key

    if airline_iata:
        key = _BY_IATA.get(airline_iata.upper())
        if key:
            return key

    # Try matching callsign prefix against ICAO codes
    if callsign and len(callsign) >= 3:
        prefix = callsign[:3].upper()
        key = _BY_ICAO.get(prefix)
        if key:
            return key

    return None


def get_sprite(key: str) -> Optional[List[SpritePixel]]:
    """Get the pixel data for a sprite by key."""
    data = SPRITES.get(key)
    if data:
        return data.get("pixels", [])
    return None


def get_sprite_for_aircraft(
    airline_icao: str = "",
    airline_iata: str = "",
    callsign: str = "",
    fallback: str = "generic_plane",
) -> List[SpritePixel]:
    """Get the best sprite for an aircraft, with fallback to generic plane."""
    key = get_sprite_key(airline_icao, airline_iata, callsign)
    if key:
        pixels = get_sprite(key)
        if pixels:
            return pixels

    # Fallback
    return get_sprite(fallback) or []
