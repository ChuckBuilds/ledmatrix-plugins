"""
NYT static-JSON election provider (baseline).

Reads the NYT elections-assets per-state results feed and normalizes it into the
common ``Race`` model. This is a personal-use, best-effort read of NYT's own
front-end feed (see README); the provider abstraction means swapping to AP/DDHQ
later is a new file, not a rewrite.

Feed slug is built from config (election_date + election_type + state), never
hardcoded, so it can be pointed at the current cycle without a code change.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

import requests

from data_model import (
    Candidate,
    Race,
    make_race_id,
    normalize_party,
    scope_for_office,
    slug,
)
from providers import ElectionProvider

logger = logging.getLogger(__name__)

# A normal browser UA — NYT blocks unknown crawlers but serves plain requests.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_DEFAULT_BASE_URL = "https://static01.nyt.com/elections-assets/pages/data"

# NYT per-state feed slugs use the full state name (hyphenated, lowercased),
# e.g. results-california-primary.json — NOT the 2-letter code.
_STATE_SLUGS = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "DC": "district-of-columbia", "FL": "florida", "GA": "georgia", "HI": "hawaii",
    "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
    "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode-island", "SC": "south-carolina",
    "SD": "south-dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west-virginia",
    "WI": "wisconsin", "WY": "wyoming",
}


class NytStaticProvider(ElectionProvider):
    """Fetch + normalize the NYT static results JSON for a single state."""

    name = "nyt"

    def __init__(self, config: Dict[str, Any], cache_manager: Any = None,
                 request_timeout: int = 15):
        self.config = config or {}
        self.cache_manager = cache_manager
        self.timeout = request_timeout
        self.base_url = self.config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        self.election_date = self.config.get("election_date", "")
        self.election_type = self.config.get("election_type", "primary")
        # Overrides the manager sets per-update for non-standard feeds:
        #   feed_url_override -> exact URL, bypasses all building
        #   feed_filename     -> non-standard slug under {base}/{date}/ (specials)
        self.feed_url_override = self.config.get("feed_url") or None
        self.feed_filename = self.config.get("feed_filename") or None

    def provides_states(self) -> Optional[Set[str]]:
        # NYT covers everything; None means "baseline for all states".
        return None

    # -- URL construction ---------------------------------------------------

    def build_url(self, state: Optional[str]) -> Optional[str]:
        """Build the per-state results feed URL.

        Exact override:  feed_url_override (used verbatim)
        Non-standard:    {base}/{date}/{feed_filename}   (specials/runoffs)
        Primary:         results-{state}-primary.json
        General:         results-{state}.json
        """
        if self.feed_url_override:
            return self.feed_url_override
        if not self.election_date:
            return None
        if self.feed_filename:
            return f"{self.base_url}/{self.election_date}/{self.feed_filename}"
        if not state:
            return None
        # NYT slugs use the full state name; fall back to the lowercased input
        # for anything not in the map (already a name, or a future addition).
        state_slug = _STATE_SLUGS.get(state.strip().upper(), state.strip().lower())
        if self.election_type == "primary":
            fname = f"results-{state_slug}-primary.json"
        else:
            fname = f"results-{state_slug}.json"
        return f"{self.base_url}/{self.election_date}/{fname}"

    # -- Fetch --------------------------------------------------------------

    def fetch(self, state: Optional[str] = None) -> List[Race]:
        url = self.build_url(state)
        if not url:
            logger.warning("[Elections] NYT: missing election_date or state; cannot build URL")
            return []

        cache_key = f"elections_nyt_{state}_{self.election_date}_{self.election_type}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if self.cache_manager:
                self.cache_manager.set(cache_key, data)
        except (requests.RequestException, ValueError) as e:
            logger.error("[Elections] NYT fetch failed (%s): %s", url, e)
            if self.cache_manager:
                cached = self.cache_manager.get(cache_key)
                if cached:
                    logger.info("[Elections] NYT: using cached data")
                    data = cached
                else:
                    return []
            else:
                return []

        return self.parse(data)

    # -- Parse (pure; unit-tested against the fixture) ----------------------

    def parse(self, data: Dict[str, Any]) -> List[Race]:
        """Normalize a NYT results document into a list of ``Race``."""
        races_raw = data.get("races", []) or []
        key_race_ids = set(
            data.get("pageConfig", {})
            .get("collections", {})
            .get("key_races", []) or []
        )
        now = time.time()

        # Disambiguate genuine duplicates (e.g. multiple local "Mayor" races with
        # the same office+state+no-district) with a STABLE, content-derived suffix
        # so the same physical race keeps its id across fetches. NYT reorders
        # results between pulls; an order-derived counter would reshuffle the
        # suffixes, so diff_newly_called would see "new" ids every cycle and
        # re-fire the called-race interrupt forever.
        parsed = [
            (r, race)
            for r, race in ((r, self._parse_race(r, now)) for r in races_raw)
            if race is not None
        ]
        id_counts: Dict[str, int] = {}
        for _, race in parsed:
            id_counts[race.id] = id_counts.get(race.id, 0) + 1

        races: List[Race] = []
        fallback_seen: Dict[str, int] = {}
        for r, race in parsed:
            if id_counts[race.id] > 1:
                # Collision: suffix every member with NYT's stable per-race id.
                nyt_id = r.get("nyt_id")
                if nyt_id:
                    race.id = f"{race.id}-{slug(str(nyt_id))}"
                else:
                    fallback_seen[race.id] = fallback_seen.get(race.id, 0) + 1
                    race.id = f"{race.id}-{fallback_seen[race.id]}"
            if r.get("nyt_id") in key_race_ids:
                race._key_race = True  # type: ignore[attr-defined]
            races.append(race)
        return races

    def _parse_race(self, r: Dict[str, Any], now: float) -> Optional[Race]:
        office = r.get("office")
        tru = r.get("top_reporting_unit") or {}
        if not office or not tru:
            return None

        state = tru.get("state_postal") or tru.get("state_abb")
        state = state.upper() if state else None
        district = r.get("seat_number")  # e.g. "1"; None for statewide

        race_type = (r.get("type") or "").lower()
        is_special = "special" in race_type

        race_id = make_race_id(office, state, district, special=is_special)

        outcome = r.get("outcome") or {}
        won = set(outcome.get("won") or [])
        advanced = set(outcome.get("advanced_to_runoff") or [])
        called = bool(won or advanced)
        winner_ids = won | advanced

        total_votes = tru.get("total_votes") or 0
        metadata = r.get("candidate_metadata") or {}

        candidates: List[Candidate] = []
        for c in tru.get("candidates", []) or []:
            cid = c.get("nyt_id")
            meta = metadata.get(cid, {}) if cid else {}
            votes = (c.get("votes") or {}).get("total", 0) or 0
            pct = (votes / total_votes * 100.0) if total_votes else 0.0
            party_obj = meta.get("party") or {}
            party = normalize_party(party_obj.get("nyt_id") or party_obj.get("abbreviation"))
            name = self._candidate_name(meta) or (cid or "?")
            candidates.append(
                Candidate(
                    name=name,
                    party=party,
                    votes=int(votes),
                    pct=round(pct, 1),
                    incumbent=bool(meta.get("incumbent")),
                    is_winner=cid in winner_ids,
                )
            )

        candidates.sort(key=lambda c: c.votes, reverse=True)

        eevp = tru.get("eevp")
        pct_reporting = float(eevp) if eevp is not None else 0.0

        race = Race(
            id=race_id,
            office=office,
            state=state,
            scope=scope_for_office(office),
            candidates=candidates,
            pct_reporting=round(pct_reporting, 2),
            called=called,
            district=str(district) if district is not None else None,
            title=r.get("seat") or office,
            source=self.name,
            last_updated=now,
        )
        race.nyt_id = r.get("nyt_id")  # type: ignore[attr-defined]
        return race

    @staticmethod
    def _candidate_name(meta: Dict[str, Any]) -> str:
        """Prefer 'Last' for tickers; fall back to full name."""
        last = (meta.get("last_name") or "").strip()
        first = (meta.get("first_name") or "").strip()
        suffix = (meta.get("suffix") or "").strip()
        if last:
            name = last
            if suffix:
                name = f"{name} {suffix}"
            return name
        return f"{first} {last}".strip()


def fetch_called_slugs(base_url: str, election_date: str, feed_uuid: str,
                       timeout: int = 10) -> Optional[Set[str]]:
    """Cheap poll of the tiny generated-race-calls feed (~3.6 KB).

    Returns the set of called race nyt_ids, or None on failure. Lets interrupt
    mode detect new calls fast without re-pulling the ~1.7 MB results doc.
    The ``feed_uuid`` comes from ``pageConfig.feeds['generated-race-calls']``.
    """
    url = f"{base_url.rstrip('/')}/feeds/{feed_uuid}/generated-race-calls/{election_date}.json"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("[Elections] NYT race-calls poll failed: %s", e)
        return None
    return parse_called_slugs(data)


def parse_called_slugs(data: Any) -> Set[str]:
    """Extract called race nyt_ids (upper-cased) from a generated-race-calls payload.

    Each entry's ``slug`` looks like ``generated-rc-<uuid8>-ca-app-h-11-2026-06-02``;
    we strip the ``generated-rc-<uuid8>-`` prefix to recover the nyt_id.
    """
    payload = data.get("data", data) if isinstance(data, dict) else data
    slugs: Set[str] = set()
    if isinstance(payload, list):
        for item in payload:
            raw = item if isinstance(item, str) else (
                item.get("nyt_id") or item.get("race_id") or item.get("slug")
                or item.get("id") if isinstance(item, dict) else None
            )
            nyt_id = _nyt_id_from_call_slug(raw)
            if nyt_id:
                slugs.add(nyt_id)
    elif isinstance(payload, dict):
        for k in payload.keys():
            nyt_id = _nyt_id_from_call_slug(str(k))
            if nyt_id:
                slugs.add(nyt_id)
    return slugs


def _nyt_id_from_call_slug(raw: Optional[str]) -> Optional[str]:
    """Recover an upper-cased nyt_id from a race-call slug (or a bare nyt_id)."""
    if not raw:
        return None
    s = str(raw)
    if s.lower().startswith("generated-rc-"):
        rest = s[len("generated-rc-"):]
        # rest = "<uuid8>-ca-app-h-11-2026-06-02" -> drop the uuid8 segment
        parts = rest.split("-", 1)
        s = parts[1] if len(parts) == 2 else rest
    return s.upper()
