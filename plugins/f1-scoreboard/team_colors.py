"""
F1 Team Color Definitions

Official team colors sourced from OpenF1 API and Formula 1 branding.
Used for team color accent bars and visual identification on LED matrix displays.
"""

# Official F1 team colors as RGB tuples
# Source: OpenF1 API driver endpoint team_colour field
F1_TEAM_COLORS = {
    "mclaren":       (244, 118, 0),    # #F47600 - Papaya Orange
    "red_bull":      (71, 129, 215),    # #4781D7 - Blue
    "mercedes":      (0, 215, 182),     # #00D7B6 - Teal
    "ferrari":       (237, 17, 49),     # #ED1131 - Red
    "williams":      (24, 104, 219),    # #1868DB - Blue
    "aston_martin":  (34, 153, 113),    # #229971 - British Racing Green
    "alpine":        (0, 161, 232),     # #00A1E8 - Blue
    "haas":          (156, 159, 162),   # #9C9FA2 - Silver/Grey
    "sauber":        (245, 5, 55),      # #F50537 - Red (Audi transition)
    "rb":            (102, 152, 255),   # #6698FF - Blue
    "cadillac":      (0, 190, 255),     # #00BEFF - Electric Blue (2026 TWO Andretti Cadillac)
}

# Aliases for different naming conventions across APIs
# Jolpi uses constructorId like "mclaren", ESPN may use different names
_CONSTRUCTOR_ALIASES = {
    # Alternate names from different sources
    "racing_bulls": "rb",
    "rb_f1_team": "rb",
    "visa_cash_app_rb": "rb",
    "kick_sauber": "sauber",
    "stake_f1_team": "sauber",
    "audi": "sauber",
    "haas_f1_team": "haas",
    "alphatauri": "rb",
    "alfa": "sauber",
    "alfa_romeo": "sauber",
    "toro_rosso": "rb",
    "force_india": "aston_martin",
    "racing_point": "aston_martin",
    "renault": "alpine",
    "red bull racing": "red_bull",
    "red bull": "red_bull",
    "aston martin": "aston_martin",
    "rb f1 team": "rb",
    "haas f1 team": "haas",
    "alpine f1 team": "alpine",
    # Cadillac aliases for 2026
    "andretti": "cadillac",
    "andretti cadillac": "cadillac",
    "two andretti": "cadillac",
    "cadillac f1": "cadillac",
}

# Podium accent colors (metallic)
PODIUM_COLORS = {
    1: (255, 215, 0),    # #FFD700 - Gold
    2: (192, 192, 192),  # #C0C0C0 - Silver
    3: (205, 127, 50),   # #CD7F32 - Bronze
}

# F1 brand red color
F1_RED = (229, 0, 0)  # #E50000


def normalize_constructor_id(constructor_id):
    """
    Normalize a constructor ID/name to our standard key format.

    Handles variations from different APIs (Jolpi, ESPN, OpenF1).

    Args:
        constructor_id: Raw constructor identifier from any API

    Returns:
        Normalized constructor key matching F1_TEAM_COLORS keys
    """
    if not constructor_id:
        return ""

    # Lowercase and strip whitespace
    key = constructor_id.lower().strip()

    # Check direct match first
    if key in F1_TEAM_COLORS:
        return key

    # Check aliases
    if key in _CONSTRUCTOR_ALIASES:
        return _CONSTRUCTOR_ALIASES[key]

    # Try replacing spaces/hyphens with underscores
    key_underscore = key.replace(" ", "_").replace("-", "_")
    if key_underscore in F1_TEAM_COLORS:
        return key_underscore
    if key_underscore in _CONSTRUCTOR_ALIASES:
        return _CONSTRUCTOR_ALIASES[key_underscore]

    return key


def get_team_color(constructor_id):
    """
    Get the RGB color tuple for a constructor/team.

    Args:
        constructor_id: Constructor identifier (any format)

    Returns:
        RGB tuple (r, g, b) or default white if not found
    """
    normalized = normalize_constructor_id(constructor_id)
    return F1_TEAM_COLORS.get(normalized, (200, 200, 200))
