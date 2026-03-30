"""
FlightAware AeroAPI enrichment provider (PAID, optional).

Only used when ``flightaware_api_key`` is present in config_secrets.json.
Preserves the existing rate limiting and budget logic from the original manager.py.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from data_model import TrackedFlight
from enrichment.base import EnrichmentProvider

logger = logging.getLogger(__name__)


class FlightAwareEnrichment(EnrichmentProvider):
    """FlightAware AeroAPI enrichment (paid, $0.005/call)."""

    API_URL = "https://aeroapi.flightaware.com/aeroapi"

    def __init__(self, config: Dict[str, Any], cache_manager: Any = None):
        self.api_key = config.get("flightaware_api_key", "")
        self.cache_manager = cache_manager

        # Rate limiting
        self.max_calls_per_hour = config.get("max_api_calls_per_hour", 20)
        self.daily_budget = config.get("daily_api_budget", 60)
        self.api_call_timestamps: List[float] = []
        self.calls_today = 0
        self.last_reset_date: Optional[Any] = None
        self.cache_ttl = config.get("flight_plan_cache_ttl_hours", 12) * 3600

        if not self.api_key:
            logger.warning("[Flight Tracker] FlightAware API key not configured — enrichment disabled")

    def _check_rate_limit(self) -> bool:
        """Check hourly and daily rate limits."""
        now = time.time()
        today = datetime.now().date()

        if self.last_reset_date != today:
            self.calls_today = 0
            self.last_reset_date = today

        if self.calls_today >= self.daily_budget:
            return False

        hour_ago = now - 3600
        self.api_call_timestamps = [ts for ts in self.api_call_timestamps if ts > hour_ago]
        if len(self.api_call_timestamps) >= self.max_calls_per_hour:
            return False

        return True

    def _record_call(self) -> None:
        """Record an API call for rate tracking."""
        self.api_call_timestamps.append(time.time())
        self.calls_today += 1

    def _api_get(self, endpoint: str) -> Optional[Dict]:
        """Make an authenticated GET to FlightAware AeroAPI."""
        if not self.api_key:
            return None
        if not self._check_rate_limit():
            logger.warning("[Flight Tracker] FlightAware rate limit reached")
            return None

        url = f"{self.API_URL}{endpoint}"
        headers = {"x-apikey": self.api_key}
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            self._record_call()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"[Flight Tracker] FlightAware request failed ({endpoint}): {e}")
            return None

    def get_flight_route(self, callsign: str) -> Optional[Dict]:
        """Look up route data via FlightAware /flights/{ident}."""
        if not callsign or not self.api_key:
            return None

        # Check cache
        cache_key = f"fa_route_{callsign}"
        if self.cache_manager:
            cached = self.cache_manager.get(cache_key, max_age=self.cache_ttl)
            if cached:
                return cached

        data = self._api_get(f"/flights/{callsign}")
        if not data:
            return None

        flights = data.get("flights", [])
        if not flights:
            return None

        # Use the most recent flight
        flight = flights[0]
        result = {
            "origin": flight.get("origin", {}).get("code_iata", ""),
            "destination": flight.get("destination", {}).get("code_iata", ""),
            "aircraft_type": flight.get("aircraft_type", ""),
            "airline_name": flight.get("operator", ""),
            "scheduled_departure": flight.get("scheduled_out", ""),
            "estimated_arrival": flight.get("estimated_in", ""),
            "status": flight.get("status", ""),
            "progress_pct": flight.get("progress_percent"),
            "source": "flightaware",
        }

        if self.cache_manager:
            self.cache_manager.set(cache_key, result)

        return result

    def lookup_tracked_flight(self, identifier: str) -> Optional[TrackedFlight]:
        """Look up a tracked flight via FlightAware."""
        route = self.get_flight_route(identifier)
        if not route:
            return TrackedFlight(identifier=identifier, status="UNKNOWN")

        # Map FlightAware status to our status
        fa_status = route.get("status", "").lower()
        if "en route" in fa_status or "airborne" in fa_status:
            status = "AIRBORNE"
        elif "landed" in fa_status or "arrived" in fa_status:
            status = "LANDED"
        elif "scheduled" in fa_status or "filed" in fa_status:
            status = "SCHEDULED"
        else:
            status = "UNKNOWN"

        return TrackedFlight(
            identifier=identifier,
            status=status,
            origin=route.get("origin", ""),
            destination=route.get("destination", ""),
            departure_time=route.get("scheduled_departure", ""),
            arrival_time=route.get("estimated_arrival", ""),
            progress_pct=route.get("progress_pct"),
            last_updated=time.time(),
        )

    def get_airport_flights(self, airport_icao: str, mode: str = "arrival") -> List[Dict]:
        """Get recent arrivals/departures via FlightAware."""
        if not airport_icao or not self.api_key:
            return []

        endpoint = f"/airports/{airport_icao}/flights/{mode}s"
        data = self._api_get(endpoint)
        if not data:
            return []

        results = []
        key = "arrivals" if mode == "arrival" else "departures"
        for flight in data.get(key, []):
            results.append({
                "callsign": flight.get("ident", ""),
                "origin": flight.get("origin", {}).get("code_iata", ""),
                "destination": flight.get("destination", {}).get("code_iata", ""),
                "scheduled_departure": flight.get("scheduled_out", ""),
                "estimated_arrival": flight.get("estimated_in", ""),
                "status": flight.get("status", ""),
            })

        return results
