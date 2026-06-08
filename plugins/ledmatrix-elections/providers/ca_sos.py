"""
California Secretary of State election provider (enhancement).

Supplements/overrides CA races with the authoritative county tally. CA-SoS has
no called flag and serves votes/percent as strings, so this provider strips and
derives those. The contest-list endpoints 403, so it carries a static list of
office slugs rather than enumerating them.

This is an advanced, opt-in county/statewide rollup. The NYT baseline already
carries CA's statewide, U.S. House, and state-legislature races with an accurate
"% of expected vote" estimate (eevp), so by default this provider contributes
nothing; it only fetches when its advanced knobs are set.

Endpoints (all verified 200 against the June 2 primary returns):
- statewide:   {base}/{office}                       -> dict
- county:      {base}/{office}/county/{county-slug}  -> list[dict] (one entry)
- all house:   {base}/us-rep/district/all            -> list[dict] (52)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

import requests

from data_model import (
    Candidate,
    Race,
    make_race_id,
    normalize_party,
    scope_for_office,
)
from providers import ElectionProvider

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.sos.ca.gov/returns"

# Statewide office slug -> NYT-matching office label (so the merge key lines up).
_OFFICE_LABELS = {
    "governor": "Governor",
    "lieutenant-governor": "Lieutenant Governor",
    "secretary-of-state": "Secretary of State",
    "attorney-general": "Attorney General",
    "treasurer": "Treasurer",
    "controller": "Controller",
    "insurance-commissioner": "Insurance Commissioner",
    "superintendent-of-public-instruction": "Superintendent of Public Instruction",
}

# Minimal city -> county-slug table for the configured-city rollup convenience.
# Kept intentionally small; a full CA geography table is out of scope.
_CITY_TO_COUNTY = {
    "los angeles": "los-angeles",
    "long beach": "los-angeles",
    "san diego": "san-diego",
    "san francisco": "san-francisco",
    "san jose": "santa-clara",
    "sacramento": "sacramento",
    "fresno": "fresno",
    "oakland": "alameda",
    "bakersfield": "kern",
    "anaheim": "orange",
    "santa ana": "orange",
    "riverside": "riverside",
}

_REPORTING_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DISTRICT_RE = re.compile(r"District\s+(\d+)", re.IGNORECASE)


class CaSosProvider(ElectionProvider):
    """Fetch + normalize CA SoS returns. CA-only; optional county/city rollup."""

    name = "ca_sos"

    def __init__(self, config: Dict[str, Any], cache_manager: Any = None,
                 request_timeout: int = 15):
        self.config = config or {}
        self.cache_manager = cache_manager
        self.timeout = request_timeout
        self.base_url = self.config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        # Advanced/opt-in: NYT already covers CA statewide, House, and state
        # legislature with an accurate eevp estimate, so this provider fetches
        # nothing unless its advanced knobs are set.
        self.offices = self.config.get("offices", [])
        self.include_house = self.config.get("include_house", False)
        self.advance_count = int(self.config.get("advance_count", 2))
        self.called_threshold = float(self.config.get("called_threshold", 99.0))
        self.county = self._resolve_county()

    def provides_states(self) -> Optional[Set[str]]:
        return {"CA"}

    def _resolve_county(self) -> str:
        """County slug from explicit config, else mapped from city, else ''."""
        county = (self.config.get("county") or "").strip().lower()
        if county:
            return county
        city = (self.config.get("city") or "").strip().lower()
        return _CITY_TO_COUNTY.get(city, "")

    # -- Fetch --------------------------------------------------------------

    def fetch(self, state: Optional[str] = None) -> List[Race]:
        if state and state.upper() != "CA":
            return []  # provider only supplements CA

        races: List[Race] = []
        now = time.time()

        for office_slug in self.offices:
            label = _OFFICE_LABELS.get(office_slug, office_slug.replace("-", " ").title())
            raw = self._fetch_office(office_slug)
            if raw is None:
                continue
            entry = raw[0] if isinstance(raw, list) else raw
            if not entry:
                continue
            race = self._parse_contest(entry, label, "CA", district=None, now=now)
            if race:
                races.append(race)

        if self.include_house:
            raw = self._fetch_json(f"{self.base_url}/us-rep/district/all", "ca_sos_house")
            for entry in (raw or []):
                district = self._district_from_title(entry.get("raceTitle", ""))
                race = self._parse_contest(entry, "U.S. House", "CA", district=district, now=now)
                if race:
                    races.append(race)

        return races

    def _fetch_office(self, office_slug: str) -> Optional[Any]:
        if self.county:
            url = f"{self.base_url}/{office_slug}/county/{self.county}"
            key = f"ca_sos_{office_slug}_{self.county}"
        else:
            url = f"{self.base_url}/{office_slug}"
            key = f"ca_sos_{office_slug}"
        return self._fetch_json(url, key)

    def _fetch_json(self, url: str, cache_key: str) -> Optional[Any]:
        try:
            resp = requests.get(url, timeout=self.timeout,
                                headers={"User-Agent": "LEDMatrix-Elections/1.0"})
            resp.raise_for_status()
            data = resp.json()
            if self.cache_manager:
                self.cache_manager.set(cache_key, data)
            return data
        except (requests.RequestException, ValueError) as e:
            logger.error("[Elections] CA-SoS fetch failed (%s): %s", url, e)
            if self.cache_manager:
                cached = self.cache_manager.get(cache_key)
                if cached:
                    logger.info("[Elections] CA-SoS: using cached data for %s", cache_key)
                    return cached
            return None

    # -- Parse (pure; unit-tested against fixtures) -------------------------

    def parse_office(self, entry_or_list: Any, office_label: str,
                     district: Optional[str] = None) -> Optional[Race]:
        """Public helper used by tests: parse one contest (dict or 1-item list)."""
        entry = entry_or_list[0] if isinstance(entry_or_list, list) else entry_or_list
        return self._parse_contest(entry, office_label, "CA", district, time.time())

    def parse_house_all(self, data: List[Dict[str, Any]]) -> List[Race]:
        """Public helper used by tests: parse the us-rep/district/all list."""
        now = time.time()
        out: List[Race] = []
        for entry in data or []:
            district = self._district_from_title(entry.get("raceTitle", ""))
            race = self._parse_contest(entry, "U.S. House", "CA", district, now)
            if race:
                out.append(race)
        return out

    def _parse_contest(self, entry: Dict[str, Any], office_label: str, state: str,
                       district: Optional[str], now: float) -> Optional[Race]:
        if not entry or "candidates" not in entry:
            return None

        pct_reporting = self._parse_reporting(entry.get("Reporting", ""))

        candidates: List[Candidate] = []
        for c in entry.get("candidates", []) or []:
            candidates.append(
                Candidate(
                    name=(c.get("Name") or "?").strip(),
                    party=normalize_party(c.get("Party")),
                    votes=self._parse_int(c.get("Votes")),
                    pct=self._parse_float(c.get("Percent")),
                    incumbent=bool(c.get("incumbent")),
                    is_winner=False,
                )
            )

        candidates.sort(key=lambda c: c.votes, reverse=True)

        # Derive called/winners: CA primaries are top-two; once reporting is
        # effectively complete, the top N advance.
        called = pct_reporting >= self.called_threshold
        if called:
            for c in candidates[: self.advance_count]:
                c.is_winner = True

        race = Race(
            id=make_race_id(office_label, state, district),
            office=office_label,
            state=state,
            scope=scope_for_office(office_label),
            candidates=candidates,
            pct_reporting=round(pct_reporting, 2),
            called=called,
            district=str(district) if district is not None else None,
            title=entry.get("raceTitle") or office_label,
            source=self.name,
            last_updated=now,
            reporting_basis="precincts",
        )
        return race

    @staticmethod
    def _parse_reporting(text: str) -> float:
        m = _REPORTING_PCT_RE.search(text or "")
        return float(m.group(1)) if m else 0.0

    @staticmethod
    def _district_from_title(title: str) -> Optional[str]:
        m = _DISTRICT_RE.search(title or "")
        return m.group(1) if m else None

    @staticmethod
    def _parse_int(value: Any) -> int:
        if value is None:
            return 0
        try:
            return int(str(value).replace(",", "").strip() or 0)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_float(value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(str(value).replace(",", "").strip() or 0.0)
        except (ValueError, TypeError):
            return 0.0
