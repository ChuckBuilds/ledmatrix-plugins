"""
OpenSky Network enrichment provider (FREE).

Uses the OpenSky REST API endpoints:
  - /flights/arrival?airport=ICAO&begin=T&end=T — arrivals at an airport
  - /flights/departure?airport=ICAO&begin=T&end=T — departures from an airport
  - /states/all?icao24=HEX — track a specific aircraft

These endpoints are free and do not require authentication (though auth gives higher limits).
"""

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from data_model import TrackedFlight
from enrichment.base import EnrichmentProvider

logger = logging.getLogger(__name__)


class OpenSkyEnrichment(EnrichmentProvider):
    """Free enrichment via OpenSky Network REST API."""

    BASE_URL = "https://opensky-network.org/api"

    def __init__(self, username: str = "", password: str = "",
                 cache_manager: Any = None, route_cache_ttl: int = 300):
        self.auth = (username, password) if username and password else None
        self.cache_manager = cache_manager
        self.route_cache_ttl = route_cache_ttl

        # Cached states snapshot (refreshed once per lookup cycle)
        self._states_cache: Optional[dict] = None
        self._states_cache_ts: float = 0.0
        self._states_cache_ttl = 30  # seconds

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        """Make a GET request to OpenSky API."""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, params=params, auth=self.auth, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"[Flight Tracker] OpenSky enrichment request failed ({endpoint}): {e}")
            return None

    def _get_states_snapshot(self) -> Optional[dict]:
        """Return cached /states/all snapshot, refreshing if stale."""
        now = time.time()
        if self._states_cache and now - self._states_cache_ts < self._states_cache_ttl:
            return self._states_cache
        data = self._get("/states/all", {})
        if data:
            self._states_cache = data
            self._states_cache_ts = now
        return self._states_cache

    def get_flight_route(self, callsign: str) -> Optional[Dict]:
        """Look up route by searching recent flights for a callsign.

        Uses cache_manager with route_cache_ttl if available.
        """
        if not callsign:
            return None

        cache_key = f"opensky_route_{callsign.upper().strip()}"

        # Check shared cache
        if self.cache_manager:
            cached = self.cache_manager.get(cache_key, max_age=self.route_cache_ttl)
            if cached:
                return cached

        now = time.time()
        begin = int(now) - 7200
        end = int(now)

        data = self._get("/flights/all", {"begin": begin, "end": end})
        if not data:
            return None

        cs_upper = callsign.upper().strip()
        for flight in data:
            flight_cs = (flight.get("callsign") or "").strip().upper()
            if flight_cs == cs_upper:
                result = {
                    "origin": flight.get("estDepartureAirport", ""),
                    "destination": flight.get("estArrivalAirport", ""),
                    "source": "opensky",
                }
                if self.cache_manager:
                    self.cache_manager.set(cache_key, result)
                return result

        return None

    def lookup_tracked_flight(self, identifier: str) -> Optional[TrackedFlight]:
        """Look up a tracked flight using OpenSky state vectors and route data.

        Matches by callsign, ICAO24 hex, or registration (tail number).
        Uses a cached states snapshot to avoid duplicate API calls.
        """
        if not identifier:
            return None

        now = time.time()
        ident_upper = identifier.upper().strip()

        # If identifier looks like a hex ICAO24 (6 hex chars), query directly
        is_hex = len(ident_upper) == 6 and all(c in "0123456789ABCDEF" for c in ident_upper)
        if is_hex:
            data = self._get("/states/all", {"icao24": ident_upper.lower()})
        else:
            data = self._get_states_snapshot()

        if not data or not data.get("states"):
            return TrackedFlight(identifier=identifier, status="UNKNOWN")

        matched_sv = None
        for sv in data["states"]:
            sv_callsign = (sv[1] or "").strip().upper()
            sv_icao = (sv[0] or "").strip().upper()
            if sv_callsign == ident_upper or sv_icao == ident_upper:
                matched_sv = sv
                break

        route = self.get_flight_route(identifier)

        if matched_sv:
            on_ground = bool(matched_sv[8]) if matched_sv[8] is not None else False
            status = "AIRBORNE" if not on_ground else "LANDED"
            return TrackedFlight(
                identifier=identifier,
                status=status,
                origin=route.get("origin", "") if route else "",
                destination=route.get("destination", "") if route else "",
                last_updated=now,
            )

        if route:
            return TrackedFlight(
                identifier=identifier,
                status="UNKNOWN",
                origin=route.get("origin", ""),
                destination=route.get("destination", ""),
                last_updated=now,
            )

        return TrackedFlight(identifier=identifier, status="UNKNOWN", last_updated=now)

    def get_airport_flights(self, airport_icao: str, mode: str = "arrival") -> List[Dict]:
        """Get recent arrivals or departures at an airport via OpenSky."""
        if not airport_icao:
            return []

        now = int(time.time())
        begin = now - 7200
        end = now

        endpoint = f"/flights/{mode}"
        data = self._get(endpoint, {"airport": airport_icao, "begin": begin, "end": end})
        if not data:
            return []

        results = []
        for flight in data:
            results.append({
                "callsign": (flight.get("callsign") or "").strip(),
                "icao24": flight.get("icao24", ""),
                "origin": flight.get("estDepartureAirport", ""),
                "destination": flight.get("estArrivalAirport", ""),
                "first_seen": flight.get("firstSeen"),
                "last_seen": flight.get("lastSeen"),
            })

        logger.info(f"[Flight Tracker] OpenSky {mode}s at {airport_icao}: {len(results)} flights")
        return results
