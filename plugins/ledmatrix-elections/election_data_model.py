"""
Common data model for the Elections plugin.

Every provider normalizes its source feed into these structures so the rest of
the plugin (store, renderer, manager) never sees provider-specific shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Scope(Enum):
    """Geographic scope of a race. Drives the 'only my state' filter."""

    NATIONAL = "national"      # President — keep regardless of state filter
    STATEWIDE = "statewide"    # Senate, Governor, other statewide offices, ballot measures
    DISTRICT = "district"      # U.S. House (and state legislature) — rolled up under their state


# Office rank for the importance sort (lower = more important).
OFFICE_RANK = {
    "President": 0,
    "U.S. Senate": 1,
    "Governor": 2,
    "Ballot Measure": 3,
    "U.S. House": 4,
    "State Senate": 5,
    "State Assembly": 6,
}
_DEFAULT_OFFICE_RANK = 99

# State-legislature chamber detection, generalized across states. Chamber names
# vary ("State Senate"/"State Assembly" in CA/NV/NY/NJ/WI, "State House" or
# "House of Delegates" or "General Assembly" elsewhere), so we classify by
# keyword rather than an exact-name allowlist. Federal offices that share those
# words ("U.S. Senate", "U.S. House") are excluded first.
_FEDERAL_OFFICES = {"President", "U.S. Senate", "U.S. House"}
_LOWER_CHAMBER_WORDS = ("house", "assembly", "delegates")


def chamber_of_office(office: Optional[str]) -> Optional[str]:
    """Classify a state-legislature office as 'upper'/'lower', else None.

    Used to surface the user's own local legislative races by chamber district,
    regardless of how a given state names its chambers.
    """
    if not office or office in _FEDERAL_OFFICES:
        return None
    low = office.lower()
    if "senate" in low:
        return "upper"
    if any(w in low for w in _LOWER_CHAMBER_WORDS):
        return "lower"
    return None


def is_local_office(office: Optional[str]) -> bool:
    """True for a state-legislature race (either chamber)."""
    return chamber_of_office(office) is not None


def office_rank(office: str) -> int:
    return OFFICE_RANK.get(office, _DEFAULT_OFFICE_RANK)


@dataclass
class Candidate:
    name: str
    party: str            # "D" | "R" | "I" | "G" | "L" | "N" | "P" | "O" (normalized single letter)
    votes: int
    pct: float            # 0-100
    incumbent: bool = False
    is_winner: bool = False   # provider-reported "called" for this candidate


@dataclass
class Race:
    id: str               # stable: "president-US", "senate-CA", "house-CA-12", "ballot-CA-prop-1"
    office: str           # "President" | "U.S. Senate" | "Governor" | "U.S. House" | "Ballot Measure" | ...
    state: Optional[str]  # 2-letter; None for President (national)
    scope: Scope
    candidates: List[Candidate] = field(default_factory=list)
    pct_reporting: float = 0.0    # 0-100 (NYT eevp / CA-SoS reporting %)
    called: bool = False          # race has a declared winner/advancement
    district: Optional[str] = None    # "12" for House; None otherwise
    title: Optional[str] = None       # human title for display (falls back to office)
    source: str = ""              # provider name that produced/won the merge
    last_updated: float = 0.0
    called_at: Optional[float] = None  # unix ts when WE first observed called=True
    reporting_basis: str = "vote"  # "vote" = share of expected vote in (NYT eevp);
    #                                "precincts" = share of precincts reporting (CA-SoS),
    #                                which hits 100% while mail ballots are still counted

    def is_key_race(self) -> bool:
        """Whether a provider flagged this as a curated 'key' race (NYT key_races)."""
        return bool(getattr(self, "_key_race", False))

    @property
    def leader(self) -> Optional[Candidate]:
        """The candidate currently ahead (most votes), or None if no candidates."""
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.votes)

    def top_candidates(self, n: int = 2) -> List[Candidate]:
        """Top-N candidates by votes, descending."""
        return sorted(self.candidates, key=lambda c: c.votes, reverse=True)[:n]


# Normalize the many ways feeds spell a party down to a single letter.
# Keys cover both NYT nyt_id codes (DEM/GOP/GRN/NPP/NP/PFP/AIP/LIB) and the
# human abbreviations CA-SoS uses (Dem/Rep/Grn/...), upper-cased and de-dotted.
_PARTY_MAP = {
    "DEM": "D", "DEMOCRAT": "D", "DEMOCRATIC": "D", "D": "D",
    "REP": "R", "REPUBLICAN": "R", "GOP": "R", "R": "R",
    "IND": "I", "INDEPENDENT": "I", "I": "I", "NPP": "I", "AIP": "I", "NONE": "I",
    "NP": "N", "NONPARTISAN": "N",
    "GRN": "G", "GREEN": "G", "G": "G",
    "LIB": "L", "LIBERTARIAN": "L", "L": "L",
    "PFP": "P", "PAF": "P", "PEACE AND FREEDOM": "P",
}


# Map a (normalized) office label to a race-type token for the race_types filter.
_RACE_TYPE_OF_OFFICE = {
    "President": "president",
    "U.S. Senate": "senate",
    "Governor": "governor",
    "U.S. House": "house",
    "Ballot Measure": "ballot",
    "State Senate": "state-senate",
    "State Assembly": "state-assembly",
}


def race_type_token(office: str) -> str:
    """Token used by the race_types config filter; 'other' for downballot offices."""
    return _RACE_TYPE_OF_OFFICE.get(office, "other")


def slug(text: str) -> str:
    """Lowercase, hyphenate. Used to build stable, cross-provider race ids."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(text).lower())).strip("-")


def scope_for_office(office: str) -> Scope:
    """Infer geographic scope from the office label."""
    if office == "President":
        return Scope.NATIONAL
    if office == "U.S. House" or chamber_of_office(office) is not None:
        return Scope.DISTRICT
    return Scope.STATEWIDE


def make_race_id(office: str, state: Optional[str], district: Optional[str] = None,
                 special: bool = False) -> str:
    """Build a stable race id shared across providers for merge + dedup.

    e.g. ``governor-ca``, ``u-s-house-ca-12``, ``u-s-house-ca-1-special``.
    """
    parts = [slug(office)]
    parts.append(slug(state) if state else "us")
    if district:
        parts.append(slug(district))
    if special:
        parts.append("special")
    return "-".join(parts)


def normalize_party(raw: Optional[str]) -> str:
    """Map a free-form party string/abbreviation to a single-letter code."""
    if not raw:
        return "O"
    key = str(raw).strip().upper().rstrip(".")
    return _PARTY_MAP.get(key, "O")
