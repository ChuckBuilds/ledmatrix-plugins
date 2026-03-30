"""
Data model definitions for the Flight Tracker plugin.

Dataclasses representing aircraft state, tracked flights, and flight records.
These provide type-safe alternatives to the raw dicts used internally.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AircraftState:
    """Unified aircraft state from any data source (SkyAware, FR24, OpenSky).

    Field units match the internal convention:
      - altitude: feet
      - speed: knots (ground speed)
      - heading: degrees from north (0-360)
      - vertical_rate: feet/minute
      - distance_miles: statute miles from configured center
    """
    icao: str
    callsign: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    vertical_rate: Optional[float] = None
    distance_miles: Optional[float] = None
    color: Tuple[int, int, int] = (255, 255, 255)
    on_ground: bool = False
    category: str = ""
    registration: str = ""
    aircraft_type: str = "Unknown"
    origin: str = ""
    destination: str = ""
    airline_icao: str = ""
    airline_name: str = ""
    fr24_id: str = ""
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    fr24_time: Optional[Dict[str, Any]] = None
    last_seen: float = 0.0

    # --- dict bridge methods (backward compat with existing code) ---

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AircraftState":
        """Create an AircraftState from a legacy aircraft info dict."""
        return cls(
            icao=d.get("icao", ""),
            callsign=d.get("callsign", ""),
            lat=d.get("lat"),
            lon=d.get("lon"),
            altitude=d.get("altitude"),
            speed=d.get("speed"),
            heading=d.get("heading"),
            vertical_rate=d.get("vertical_rate"),
            distance_miles=d.get("distance_miles"),
            color=tuple(d.get("color", (255, 255, 255))),
            on_ground=d.get("on_ground", False),
            category=d.get("category", ""),
            registration=d.get("registration", ""),
            aircraft_type=d.get("aircraft_type", "Unknown"),
            origin=d.get("origin", ""),
            destination=d.get("destination", ""),
            airline_icao=d.get("airline_icao", ""),
            airline_name=d.get("airline_name", ""),
            fr24_id=d.get("fr24_id", ""),
            origin_lat=d.get("origin_lat"),
            origin_lon=d.get("origin_lon"),
            dest_lat=d.get("dest_lat"),
            dest_lon=d.get("dest_lon"),
            fr24_time=d.get("fr24_time"),
            last_seen=d.get("last_seen", 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to a legacy aircraft info dict."""
        d = {
            "icao": self.icao,
            "callsign": self.callsign,
            "lat": self.lat,
            "lon": self.lon,
            "altitude": self.altitude,
            "speed": self.speed,
            "heading": self.heading,
            "distance_miles": self.distance_miles,
            "color": self.color,
            "last_seen": self.last_seen,
            "registration": self.registration,
            "aircraft_type": self.aircraft_type,
        }
        # Only include optional enrichment fields if non-default
        if self.vertical_rate is not None:
            d["vertical_rate"] = self.vertical_rate
        if self.on_ground:
            d["on_ground"] = self.on_ground
        if self.category:
            d["category"] = self.category
        if self.origin:
            d["origin"] = self.origin
        if self.destination:
            d["destination"] = self.destination
        if self.airline_icao:
            d["airline_icao"] = self.airline_icao
        if self.airline_name:
            d["airline_name"] = self.airline_name
        if self.fr24_id:
            d["fr24_id"] = self.fr24_id
        if self.origin_lat is not None:
            d["origin_lat"] = self.origin_lat
            d["origin_lon"] = self.origin_lon
        if self.dest_lat is not None:
            d["dest_lat"] = self.dest_lat
            d["dest_lon"] = self.dest_lon
        if self.fr24_time is not None:
            d["fr24_time"] = self.fr24_time
        return d


@dataclass
class TrackedFlight:
    """A user-configured flight to track specifically.

    Populated from enrichment sources (OpenSky routes, FR24 detail, FlightAware).
    """
    identifier: str
    status: str = "UNKNOWN"  # SCHEDULED, AIRBORNE, LANDED, UNKNOWN
    origin: str = ""
    destination: str = ""
    origin_name: str = ""
    destination_name: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    progress_pct: Optional[float] = None
    aircraft_state: Optional[AircraftState] = None
    city_overfly: str = ""
    last_updated: float = 0.0


@dataclass
class FlightRecord:
    """Snapshot of an aircraft for closest/farthest records."""
    callsign: str = ""
    registration: str = ""
    aircraft_type: str = ""
    altitude: float = 0.0
    speed: float = 0.0
    distance_miles: float = 0.0
    origin: str = ""
    destination: str = ""
    airline_name: str = ""
    timestamp: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FlightRecord":
        """Create from a saved record dict."""
        return cls(
            callsign=d.get("callsign", ""),
            registration=d.get("registration", ""),
            aircraft_type=d.get("aircraft_type", ""),
            altitude=d.get("altitude", 0.0),
            speed=d.get("speed", 0.0),
            distance_miles=d.get("distance_miles", 0.0),
            origin=d.get("origin", ""),
            destination=d.get("destination", ""),
            airline_name=d.get("airline_name", ""),
            timestamp=d.get("timestamp", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "callsign": self.callsign,
            "registration": self.registration,
            "aircraft_type": self.aircraft_type,
            "altitude": self.altitude,
            "speed": self.speed,
            "distance_miles": self.distance_miles,
            "origin": self.origin,
            "destination": self.destination,
            "airline_name": self.airline_name,
            "timestamp": self.timestamp,
        }
