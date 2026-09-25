"""NFL clubs as Fantasy Blitz needs them: two abbreviations, names and LED colours.

Sleeper and ESPN agree on every club abbreviation but one -- Washington is
``WAS`` on Sleeper and ``WSH`` on ESPN -- so everything inside the plugin is
keyed on Sleeper's spelling and converted at the ESPN boundary.

The colours are chosen for an LED panel, not copied from a style guide.
``primary`` fills card backdrops and jersey chips; ``accent`` draws jersey
numbers and rim light. Clubs whose official primary is black (Raiders,
Steelers, Saints) swap to their second colour, because black is an unlit LED
and a black chip is an empty hole in the panel.
"""

from typing import Dict, Optional, Tuple

RGB = Tuple[int, int, int]


def _hex(value: str) -> RGB:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# abbr: (espn_abbr, full name, nickname, primary, accent)
_TEAMS = {
    "ARI": ("ARI", "Arizona Cardinals", "Cardinals", "a40227", "ffffff"),
    "ATL": ("ATL", "Atlanta Falcons", "Falcons", "a71930", "a5acaf"),
    "BAL": ("BAL", "Baltimore Ravens", "Ravens", "29126f", "9e7c0c"),
    "BUF": ("BUF", "Buffalo Bills", "Bills", "00338d", "c60c30"),
    "CAR": ("CAR", "Carolina Panthers", "Panthers", "0085ca", "bfc0bf"),
    "CHI": ("CHI", "Chicago Bears", "Bears", "0b162a", "c83803"),
    "CIN": ("CIN", "Cincinnati Bengals", "Bengals", "fb4f14", "ffffff"),
    "CLE": ("CLE", "Cleveland Browns", "Browns", "311d00", "ff3c00"),
    "DAL": ("DAL", "Dallas Cowboys", "Cowboys", "003594", "b0b7bc"),
    "DEN": ("DEN", "Denver Broncos", "Broncos", "0a2343", "fb4f14"),
    "DET": ("DET", "Detroit Lions", "Lions", "0076b6", "b0b7bc"),
    "GB": ("GB", "Green Bay Packers", "Packers", "203731", "ffb612"),
    "HOU": ("HOU", "Houston Texans", "Texans", "03202f", "a71930"),
    "IND": ("IND", "Indianapolis Colts", "Colts", "002c5f", "ffffff"),
    "JAX": ("JAX", "Jacksonville Jaguars", "Jaguars", "006778", "d7a22a"),
    "KC": ("KC", "Kansas City Chiefs", "Chiefs", "e31837", "ffb81c"),
    "LAC": ("LAC", "Los Angeles Chargers", "Chargers", "0080c6", "ffc20e"),
    "LAR": ("LAR", "Los Angeles Rams", "Rams", "003594", "ffd100"),
    "LV": ("LV", "Las Vegas Raiders", "Raiders", "a5acaf", "000000"),
    "MIA": ("MIA", "Miami Dolphins", "Dolphins", "008e97", "fc4c02"),
    "MIN": ("MIN", "Minnesota Vikings", "Vikings", "4f2683", "ffc62f"),
    "NE": ("NE", "New England Patriots", "Patriots", "002244", "c60c30"),
    "NO": ("NO", "New Orleans Saints", "Saints", "d3bc8d", "101820"),
    "NYG": ("NYG", "New York Giants", "Giants", "0b2265", "a71930"),
    "NYJ": ("NYJ", "New York Jets", "Jets", "125740", "ffffff"),
    "PHI": ("PHI", "Philadelphia Eagles", "Eagles", "004c54", "a5acaf"),
    "PIT": ("PIT", "Pittsburgh Steelers", "Steelers", "ffb612", "101820"),
    "SEA": ("SEA", "Seattle Seahawks", "Seahawks", "002244", "69be28"),
    "SF": ("SF", "San Francisco 49ers", "49ers", "aa0000", "b3995d"),
    "TB": ("TB", "Tampa Bay Buccaneers", "Buccaneers", "d50a0a", "ffffff"),
    "TEN": ("TEN", "Tennessee Titans", "Titans", "0c2340", "4b92db"),
    "WAS": ("WSH", "Washington Commanders", "Commanders", "5a1414", "ffb612"),
}

TEAMS: Dict[str, Dict[str, object]] = {
    abbr: {
        "abbr": abbr,
        "espn": espn,
        "name": name,
        "nickname": nickname,
        "primary": _hex(primary),
        "accent": _hex(accent),
    }
    for abbr, (espn, name, nickname, primary, accent) in _TEAMS.items()
}

_ESPN_TO_SLEEPER = {team["espn"]: abbr for abbr, team in TEAMS.items()}

#: Used when a feed names a club this table does not know -- a relocation,
#: or a typo in a fixture. Neutral slate rather than a crash.
UNKNOWN_TEAM = {
    "abbr": "",
    "espn": "",
    "name": "",
    "nickname": "",
    "primary": (70, 80, 100),
    "accent": (220, 225, 235),
}


def team(abbr: Optional[str]) -> Dict[str, object]:
    """The club for a Sleeper (or ESPN) abbreviation, never None."""
    if not abbr:
        return UNKNOWN_TEAM
    key = str(abbr).upper()
    if key in TEAMS:
        return TEAMS[key]
    sleeper = _ESPN_TO_SLEEPER.get(key)
    if sleeper:
        return TEAMS[sleeper]
    return UNKNOWN_TEAM


def from_espn(abbr: Optional[str]) -> str:
    """Sleeper's abbreviation for an ESPN one (``WSH`` -> ``WAS``)."""
    if not abbr:
        return ""
    key = str(abbr).upper()
    return _ESPN_TO_SLEEPER.get(key, key)


def to_espn(abbr: Optional[str]) -> str:
    """ESPN's abbreviation for a Sleeper one (``WAS`` -> ``WSH``)."""
    if not abbr:
        return ""
    key = str(abbr).upper()
    found = TEAMS.get(key)
    return str(found["espn"]) if found else key
