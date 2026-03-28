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

# Cache entries for route lookups
_CACHE_TTL = 300  # 5 minutes


class OpenSkyEnrichment(EnrichmentProvider):
    """Free enrichment via OpenSky Network REST API."""

    BASE_URL = "https://opensky-network.org/api"

    def __init__(self, username: str = "", password: str = "", cache_manager: Any = None):
        self.auth = (username, password) if username and password else None
        self.cache_manager = cache_manager
        self._route_cache: Dict[str, Dict] = {}
        self._route_cache_ts: Dict[str, float] = {}

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        """Make a GET request to OpenSky API."""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, params=params, auth=self.auth, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"[Flight Tracker] OpenSky enrichment request failed ({endpoint}): {e}")
            return None

    def get_flight_route(self, callsign: str) -> Optional[Dict]:
        """Look up route by searching recent arrivals/departures for a callsign.

        OpenSky doesn't have a direct "flight route" endpoint, so we search
        the /flights/all endpoint which returns flights within a time interval
        including their estDepartureAirport and estArrivalAirport.
        """
        if not callsign:
            return None

        # Check cache
        now = time.time()
        cached = self._route_cache.get(callsign)
        if cached and now - self._route_cache_ts.get(callsign, 0) < _CACHE_TTL:
            return cached

        # Query flights in the last 2 hours
        begin = int(now) - 7200
        end = int(now)

        data = self._get("/flights/all", {"begin": begin, "end": end})
        if not data:
            return None

        # Search for matching callsign
        cs_upper = callsign.upper().strip()
        for flight in data:
            flight_cs = (flight.get("callsign") or "").strip().upper()
            if flight_cs == cs_upper:
                result = {
                    "origin": flight.get("estDepartureAirport", ""),
                    "destination": flight.get("estArrivalAirport", ""),
                    "source": "opensky",
                }
                self._route_cache[callsign] = result
                self._route_cache_ts[callsign] = now
                return result

        return None

    def lookup_tracked_flight(self, identifier: str) -> Optional[TrackedFlight]:
        """Look up a tracked flight using OpenSky state vectors and route data."""
        if not identifier:
            return None

        # First try to find it in current state vectors
        now = time.time()
        ident_upper = identifier.upper().strip()

        # Search by callsign in state vectors
        data = self._get("/states/all", {})
        if not data or not data.get("states"):
            return TrackedFlight(identifier=identifier, status="UNKNOWN")

        matched_sv = None
        for sv in data["states"]:
            sv_callsign = (sv[1] or "").strip().upper()
            sv_icao = (sv[0] or "").strip().upper()
            if sv_callsign == ident_upper or sv_icao == ident_upper:
                matched_sv = sv
                break

        # Get route data
        route = self.get_flight_route(identifier)

        if matched_sv:
            on_ground = bool(matched_sv[8]) if matched_sv[8] is not None else False
            status = "AIRBORNE" if not on_ground else "LANDED"
            tf = TrackedFlight(
                identifier=identifier,
                status=status,
                origin=route.get("origin", "") if route else "",
                destination=route.get("destination", "") if route else "",
                last_updated=now,
            )
            return tf

        # Not currently in the air
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
        begin = now - 7200  # last 2 hours
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
