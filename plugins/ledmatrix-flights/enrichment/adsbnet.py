"""
adsb.lol route enrichment provider (FREE).

Uses the adsb.lol callsign endpoint which returns aircraft state plus route
data from their accumulated flight database:
  - /v2/callsign/{callsign} — aircraft matching a callsign, with optional route

Route coverage is best for major commercial flights (AAL, UAL, DAL, etc.).
Charter/private/cargo flights may have no route data — the provider returns
whatever is available and gracefully omits missing fields.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from data_model import TrackedFlight
from enrichment.base import EnrichmentProvider

logger = logging.getLogger(__name__)


class AdsbNetEnrichment(EnrichmentProvider):
    """Free route enrichment via adsb.lol callsign lookup."""

    BASE_URL = "https://api.adsb.lol"

    def __init__(self, cache_manager: Any = None, route_cache_ttl: int = 300):
        self.cache_manager = cache_manager
        self.route_cache_ttl = route_cache_ttl

    def _get(self, endpoint: str) -> Optional[dict]:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"[Flight Tracker] adsbnet request failed ({endpoint}): {e}")
            return None

    def get_flight_route(self, callsign: str) -> Optional[Dict]:
        """Look up route + aircraft type for a callsign via adsb.lol.

        Returns a dict with available keys: origin, destination, aircraft_type, source.
        Returns None if the callsign is not found at all.
        """
        if not callsign:
            return None

        cs = callsign.strip().upper()
        cache_key = f"adsbnet_route_{cs}"

        if self.cache_manager:
            cached = self.cache_manager.get(cache_key, max_age=self.route_cache_ttl)
            if cached:
                return cached

        data = self._get(f"/v2/callsign/{cs}")
        if not data:
            return None

        aircraft = data.get("ac", [])
        if not aircraft:
            return None

        ac = aircraft[0]
        result: Dict[str, Any] = {"source": "adsbnet"}

        aircraft_type = (ac.get("t") or "").strip()
        if aircraft_type:
            result["aircraft_type"] = aircraft_type

        # route field: array like ["KJFK", "KLAX"] or ["KJFK-KLAX"] or absent
        route = ac.get("route")
        if isinstance(route, list) and len(route) >= 2:
            result["origin"] = route[0].strip()
            result["destination"] = route[-1].strip()
        elif isinstance(route, list) and len(route) == 1:
            # Sometimes packed as ["KJFK-KLAX"]
            parts = route[0].split("-")
            if len(parts) == 2:
                result["origin"] = parts[0].strip()
                result["destination"] = parts[1].strip()
        elif isinstance(route, str) and "-" in route:
            parts = route.split("-")
            if len(parts) >= 2:
                result["origin"] = parts[0].strip()
                result["destination"] = parts[-1].strip()

        if self.cache_manager:
            self.cache_manager.set(cache_key, result)

        return result

    def lookup_tracked_flight(self, identifier: str) -> Optional[TrackedFlight]:
        """Look up a tracked flight via adsb.lol."""
        if not identifier:
            return None

        route = self.get_flight_route(identifier)
        if not route:
            return TrackedFlight(identifier=identifier, status="UNKNOWN")

        return TrackedFlight(
            identifier=identifier,
            status="UNKNOWN",
            origin=route.get("origin", ""),
            destination=route.get("destination", ""),
            last_updated=time.time(),
        )

    def get_airport_flights(self, airport_icao: str, mode: str = "arrival") -> List[Dict]:
        """Not supported by adsb.lol — returns empty list."""
        return []
