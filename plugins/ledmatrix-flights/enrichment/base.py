"""
Abstract base class for flight enrichment providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from data_model import TrackedFlight


class EnrichmentProvider(ABC):
    """Interface for enriching aircraft data with route and status information."""

    @abstractmethod
    def get_flight_route(self, callsign: str) -> Optional[Dict]:
        """Look up route data (origin, destination) for a callsign.

        Returns a dict with keys: origin, destination, aircraft_type, airline_name, source.
        Returns None if no data found.
        """
        ...

    @abstractmethod
    def lookup_tracked_flight(self, identifier: str) -> Optional[TrackedFlight]:
        """Look up a specific tracked flight by flight number, callsign, or tail number.

        Returns a TrackedFlight with route/status info populated, or None.
        """
        ...

    @abstractmethod
    def get_airport_flights(self, airport_icao: str, mode: str = "arrival") -> List[Dict]:
        """Get recent arrivals or departures at an airport.

        Args:
            airport_icao: ICAO airport code (e.g., 'KTPA').
            mode: 'arrival' or 'departure'.

        Returns list of dicts with callsign, origin/destination, timestamps.
        """
        ...
