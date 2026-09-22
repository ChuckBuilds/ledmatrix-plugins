"""ESPN NFL team identity -> panel assets.

ESPN's leaders feed names a player's club by numeric id and, in most
responses, by a ``$ref`` URL rather than an inline team object. Resolving
each of those refs would be one extra HTTP request per leader per category
-- around fifty requests for a default configuration, on a Raspberry Pi,
every refresh.

The 32 franchise ids are stable and have been since ESPN's v2 API shipped,
so they are mapped here instead. The abbreviations are the filenames the
core already ships under ``assets/sports/nfl_logos/``, which is what makes
a crest loadable without any network access at all.

Module name is plugin-unique on purpose: the core loads a plugin's
top-level modules under their bare names, so a generic ``teams.py`` could
bind another plugin's module (monorepo CLAUDE.md non-negotiable #4).
"""

from typing import Dict, Optional
import re

#: ESPN franchise id -> the abbreviation used for logo filenames.
ESPN_TEAM_ID_TO_ABBR: Dict[str, str] = {
    "1": "ATL", "2": "BUF", "3": "CHI", "4": "CIN", "5": "CLE",
    "6": "DAL", "7": "DEN", "8": "DET", "9": "GB", "10": "TEN",
    "11": "IND", "12": "KC", "13": "LV", "14": "LAR", "15": "MIA",
    "16": "MIN", "17": "NE", "18": "NO", "19": "NYG", "20": "NYJ",
    "21": "PHI", "22": "ARI", "23": "PIT", "24": "LAC", "25": "SF",
    "26": "SEA", "27": "TB", "28": "WSH", "29": "CAR", "30": "JAX",
    "33": "BAL", "34": "HOU",
}

#: Abbreviations ESPN has used that differ from the shipped logo filenames.
#: ESPN itself is inconsistent across endpoints (``WAS`` and ``WSH`` both
#: appear), and a crest that fails to load leaves a blank column on the panel.
ABBR_ALIASES: Dict[str, str] = {
    "WAS": "WSH",
    "JAC": "JAX",
    "LA": "LAR",
    "SD": "LAC",
    "OAK": "LV",
    "STL": "LAR",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
}

#: Matches the team id in a ``$ref`` such as
#: ``http://sports.core.api.espn.com/v2/.../teams/2?lang=en&region=us``.
_TEAM_REF_ID = re.compile(r"/teams/(\d+)")


def normalize_abbr(abbr: Optional[str]) -> Optional[str]:
    """Return the logo-filename form of an ESPN abbreviation, or None."""
    if not abbr:
        return None
    upper = str(abbr).strip().upper()
    if not upper:
        return None
    return ABBR_ALIASES.get(upper, upper)


def abbr_from_team_id(team_id: Optional[str]) -> Optional[str]:
    """Map an ESPN franchise id to its abbreviation, or None if unknown."""
    if team_id is None:
        return None
    return ESPN_TEAM_ID_TO_ABBR.get(str(team_id).strip())


def abbr_from_ref(ref: Optional[str]) -> Optional[str]:
    """Pull the franchise id out of a ``$ref`` URL and map it.

    Returns None for anything that is not a team ref, so a caller can fall
    through to the next source without a special case.
    """
    if not ref:
        return None
    match = _TEAM_REF_ID.search(str(ref))
    if not match:
        return None
    return abbr_from_team_id(match.group(1))
