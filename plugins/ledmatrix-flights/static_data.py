"""
Static reference data loaders for the Flight Tracker plugin.

Loads bundled JSON datasets for airport, airline, and city lookups.
All data is loaded lazily on first access and cached in memory.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_json(filename: str) -> Any:
    """Load a JSON file from the data directory."""
    path = os.path.join(_DATA_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"[Flight Tracker] Static data file not found: {path}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"[Flight Tracker] Failed to parse {path}: {e}")
        return []


class AirportLookup:
    """Lookup airports by IATA, ICAO code, or nearest location."""

    def __init__(self):
        self._by_icao: Dict[str, Dict] = {}
        self._by_iata: Dict[str, Dict] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        data = _load_json("airports.json")
        for ap in data:
            icao = ap.get("icao", "")
            iata = ap.get("iata", "")
            if icao:
                self._by_icao[icao.upper()] = ap
            if iata:
                self._by_iata[iata.upper()] = ap
        self._loaded = True
        logger.info(f"[Flight Tracker] Loaded {len(self._by_icao)} airports (ICAO), {len(self._by_iata)} (IATA)")

    def by_icao(self, code: str) -> Optional[Dict]:
        """Look up an airport by ICAO code (e.g., 'KTPA')."""
        self._ensure_loaded()
        return self._by_icao.get(code.upper())

    def by_iata(self, code: str) -> Optional[Dict]:
        """Look up an airport by IATA code (e.g., 'TPA')."""
        self._ensure_loaded()
        return self._by_iata.get(code.upper())

    def coords(self, code: str) -> Optional[Tuple[float, float]]:
        """Return (lat, lon) for an airport code (tries IATA first, then ICAO)."""
        ap = self.by_iata(code) or self.by_icao(code)
        if ap and ap.get("lat") is not None and ap.get("lon") is not None:
            return (ap["lat"], ap["lon"])
        return None

    def name(self, code: str) -> str:
        """Return a short display name for an airport code."""
        ap = self.by_iata(code) or self.by_icao(code)
        if ap:
            return ap.get("name", code)
        return code


class AirlineLookup:
    """Lookup airlines by IATA, ICAO code, or callsign prefix."""

    def __init__(self):
        self._by_icao: Dict[str, Dict] = {}
        self._by_iata: Dict[str, Dict] = {}
        self._by_callsign: Dict[str, Dict] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        data = _load_json("airlines.json")
        for al in data:
            icao = al.get("icao", "")
            iata = al.get("iata", "")
            callsign = al.get("callsign", "")
            if icao:
                self._by_icao[icao.upper()] = al
            if iata:
                self._by_iata[iata.upper()] = al
            if callsign:
                self._by_callsign[callsign.upper()] = al
        self._loaded = True
        logger.info(f"[Flight Tracker] Loaded {len(self._by_icao)} airlines")

    def by_icao(self, code: str) -> Optional[Dict]:
        """Look up an airline by ICAO code (e.g., 'AAL')."""
        self._ensure_loaded()
        return self._by_icao.get(code.upper())

    def by_iata(self, code: str) -> Optional[Dict]:
        """Look up an airline by IATA code (e.g., 'AA')."""
        self._ensure_loaded()
        return self._by_iata.get(code.upper())

    def name(self, code: str) -> str:
        """Return airline name for an ICAO or IATA code."""
        al = self.by_icao(code) or self.by_iata(code)
        if al:
            return al.get("name", code)
        return code


class CityLookup:
    """Reverse-geocode a lat/lon to the nearest major city."""

    def __init__(self):
        self._cities: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._cities = _load_json("cities.json")
        self._loaded = True
        logger.info(f"[Flight Tracker] Loaded {len(self._cities)} cities for overfly lookup")

    def nearest_city(self, lat: float, lon: float, max_km: float = 80) -> Optional[str]:
        """Return the name of the nearest city within *max_km*, or None."""
        self._ensure_loaded()
        if not self._cities:
            return None

        from utils import haversine_km

        best_name = None
        best_dist = max_km
        for city in self._cities:
            clat = city.get("lat")
            clon = city.get("lon")
            if clat is None or clon is None:
                continue
            d = haversine_km(lat, lon, clat, clon)
            if d < best_dist:
                best_dist = d
                best_name = city.get("name", "")
        return best_name


# Module-level singletons (lazy-loaded on first use)
airports = AirportLookup()
airlines = AirlineLookup()
cities = CityLookup()
