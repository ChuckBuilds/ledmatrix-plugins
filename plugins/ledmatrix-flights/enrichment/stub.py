"""
No-op enrichment provider for when no API keys are configured.
"""

from typing import Dict, List, Optional

from data_model import TrackedFlight
from enrichment.base import EnrichmentProvider


class StubEnrichment(EnrichmentProvider):
    """Stub that returns no enrichment data. Used as fallback."""

    def get_flight_route(self, callsign: str) -> Optional[Dict]:
        return None

    def lookup_tracked_flight(self, identifier: str) -> Optional[TrackedFlight]:
        return TrackedFlight(identifier=identifier, status="UNKNOWN")

    def get_airport_flights(self, airport_icao: str, mode: str = "arrival") -> List[Dict]:
        return []
