"""
Data source fetchers for the Flight Tracker plugin.

Each fetcher implements a common interface for retrieving aircraft positions
from different sources: local SkyAware ADS-B, FlightRadar24, and OpenSky Network.
"""

import logging
import math
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from utils import haversine_miles, altitude_to_color

logger = logging.getLogger(__name__)


class AircraftFetcher(ABC):
    """Base class for aircraft data source fetchers."""

    @abstractmethod
    def fetch(
        self,
        center_lat: float,
        center_lon: float,
        radius_miles: float,
        altitude_colors: Dict[str, List[int]],
    ) -> Optional[Dict[str, Dict]]:
        """Fetch aircraft within radius and return dict keyed by ICAO hex.

        Each value is a normalized aircraft dict compatible with the existing
        manager.py ``aircraft_data`` structure.  Returns None on complete failure.
        """
        ...


# ---------------------------------------------------------------------------
# SkyAware (local ADS-B receiver)
# ---------------------------------------------------------------------------

class SkyAwareFetcher(AircraftFetcher):
    """Fetch aircraft data from a local SkyAware / dump1090 JSON endpoint."""

    def __init__(self, skyaware_url: str, cache_manager: Any, request_timeout: int = 5):
        self.url = skyaware_url
        self.cache_manager = cache_manager
        self.timeout = request_timeout

    def fetch_raw(self) -> Optional[Dict]:
        """Fetch the raw JSON payload from SkyAware."""
        try:
            response = requests.get(self.url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            if self.cache_manager:
                self.cache_manager.set('flight_tracker_data', data)
            logger.debug(f"[Flight Tracker] SkyAware: {len(data.get('aircraft', []))} aircraft")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"[Flight Tracker] SkyAware fetch failed: {e}")
            if self.cache_manager:
                cached = self.cache_manager.get('flight_tracker_data')
                if cached:
                    logger.info("[Flight Tracker] Using cached SkyAware data")
                    return cached
            return None

    def fetch(self, center_lat, center_lon, radius_miles, altitude_colors):
        data = self.fetch_raw()
        if not data or 'aircraft' not in data:
            return None

        current_time = time.time()
        result: Dict[str, Dict] = {}

        for ac in data['aircraft']:
            icao = ac.get('hex', '').upper()
            if not icao:
                continue

            lat = ac.get('lat')
            lon = ac.get('lon')
            if lat is None or lon is None:
                continue

            distance_miles = haversine_miles(lat, lon, center_lat, center_lon)
            if distance_miles > radius_miles:
                continue

            altitude = ac.get('alt_baro', ac.get('alt_geom', 0))
            if altitude == 'ground':
                altitude = 0

            callsign = ac.get('flight', '').strip() or icao
            speed = ac.get('gs', 0)
            heading = ac.get('track', ac.get('heading', 0))
            registration = ac.get('r', '')
            aircraft_type = ac.get('t', 'Unknown')
            # SkyAware includes vertical rate in ft/min (baro_rate) or geom_rate
            vertical_rate = ac.get('baro_rate', ac.get('geom_rate'))

            color = altitude_to_color(altitude, altitude_colors)

            result[icao] = {
                'icao': icao,
                'callsign': callsign,
                'registration': registration,
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'speed': speed,
                'heading': heading,
                'aircraft_type': aircraft_type,
                'distance_miles': distance_miles,
                'color': color,
                'last_seen': current_time,
                'vertical_rate': vertical_rate,
            }

        logger.info(f"[Flight Tracker] SkyAware: {len(result)} aircraft in range ({radius_miles}mi)")
        return result


# ---------------------------------------------------------------------------
# FlightRadar24 (cloud feed.js)
# ---------------------------------------------------------------------------

_FR24_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "Origin": "https://www.flightradar24.com",
    "Referer": "https://www.flightradar24.com/",
}

# Compact airline name lookup (zero-cost fallback)
_AIRLINE_ICAO_NAMES: Dict[str, str] = {
    'AAL': 'American', 'UAL': 'United', 'DAL': 'Delta', 'SWA': 'Southwest',
    'JBU': 'JetBlue', 'ASQ': 'SkyWest', 'ENY': 'Envoy', 'FFT': 'Frontier',
    'NKS': 'Spirit', 'BAW': 'British', 'AFR': 'Air France', 'DLH': 'Lufthansa',
    'KLM': 'KLM', 'SAS': 'SAS', 'IBE': 'Iberia', 'EZY': 'easyJet',
    'RYR': 'Ryanair', 'AUA': 'Austrian', 'SWR': 'Swiss', 'AZA': 'Alitalia',
    'TAP': 'TAP Air', 'QFA': 'Qantas', 'SIA': 'Singapore', 'CCA': 'Air China',
    'CSN': 'China Southern', 'CES': 'China Eastern', 'KAL': 'Korean Air',
    'ANA': 'ANA', 'JAL': 'Japan Air', 'EAL': 'Emirates', 'UAE': 'Emirates',
    'QTR': 'Qatar', 'ETH': 'Ethiopian', 'THY': 'Turkish', 'SVA': 'Saudia',
    'UPS': 'UPS', 'FDX': 'FedEx', 'GTI': 'Atlas Air', 'DHL': 'DHL',
    'ABX': 'ABX Air', 'CPZ': 'CommuteAir', 'WN': 'Southwest', 'AA': 'American',
    'UA': 'United', 'DL': 'Delta', 'B6': 'JetBlue', 'NK': 'Spirit',
    'F9': 'Frontier', 'G4': 'Allegiant',
}


def _fr24_bounds(center_lat: float, center_lon: float, radius_miles: float) -> str:
    """Compute FR24 bounds string (laMax,laMin,loMin,loMax)."""
    lat_deg = radius_miles / 69.0
    lon_deg = radius_miles / (69.0 * math.cos(math.radians(center_lat)))
    la_max = round(center_lat + lat_deg, 6)
    la_min = round(center_lat - lat_deg, 6)
    lo_min = round(center_lon - lon_deg, 6)
    lo_max = round(center_lon + lon_deg, 6)
    return f"{la_max},{la_min},{lo_min},{lo_max}"


class FR24Fetcher(AircraftFetcher):
    """Fetch aircraft data from FlightRadar24 feed.js (free, unofficial)."""

    def __init__(self, request_timeout: int = 10):
        self.timeout = request_timeout

    def fetch(self, center_lat, center_lon, radius_miles, altitude_colors):
        bounds = _fr24_bounds(center_lat, center_lon, radius_miles)
        url = "https://data-cloud.flightradar24.com/zones/fcgi/feed.js"
        params = {
            "bounds": bounds,
            "faa": 1, "satellite": 1, "mlat": 1, "flarm": 1,
            "adsb": 1, "gnd": 0, "air": 1, "vehicles": 0,
            "estimated": 1, "maxage": 14400, "gliders": 0, "stats": 1,
        }
        try:
            response = requests.get(url, params=params, headers=_FR24_HEADERS, timeout=self.timeout)
            response.raise_for_status()
            raw = response.json()
        except Exception:
            logger.exception("[Flight Tracker] FR24 feed fetch failed")
            return None

        current_time = time.time()
        result: Dict[str, Dict] = {}

        for fr24_id, entry in raw.items():
            if not isinstance(entry, list) or len(entry) < 13:
                continue

            icao = str(entry[0]).upper() if entry[0] else ''
            if not icao:
                continue

            lat = entry[1] if isinstance(entry[1], (int, float)) else None
            lon = entry[2] if isinstance(entry[2], (int, float)) else None
            if lat is None or lon is None:
                continue

            distance_miles_val = haversine_miles(lat, lon, center_lat, center_lon)
            if distance_miles_val > radius_miles:
                continue

            heading = entry[3] if len(entry) > 3 else 0
            altitude = entry[4] if len(entry) > 4 else 0
            speed = entry[5] if len(entry) > 5 else 0
            aircraft_type_code = entry[8] if len(entry) > 8 else ''
            registration = entry[9] if len(entry) > 9 else ''
            origin_iata = entry[11] if len(entry) > 11 else ''
            destination_iata = entry[12] if len(entry) > 12 else ''
            flight_number = entry[13] if len(entry) > 13 else ''
            on_ground = bool(entry[14]) if len(entry) > 14 else False
            callsign = str(entry[16]).strip() if len(entry) > 16 and entry[16] else flight_number
            airline_icao = str(entry[18]).strip() if len(entry) > 18 and entry[18] else ''

            if not callsign:
                callsign = icao
            if on_ground:
                altitude = 0

            color = altitude_to_color(altitude, altitude_colors)
            airline_name = _AIRLINE_ICAO_NAMES.get(airline_icao, '')

            result[icao] = {
                'icao': icao,
                'fr24_id': fr24_id,
                'callsign': callsign,
                'registration': registration,
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'speed': speed,
                'heading': heading,
                'aircraft_type': aircraft_type_code,
                'origin': origin_iata,
                'destination': destination_iata,
                'airline_icao': airline_icao,
                'airline_name': airline_name,
                'distance_miles': distance_miles_val,
                'color': color,
                'last_seen': current_time,
            }

        logger.info(f"[Flight Tracker] FR24: {len(result)} aircraft in range ({radius_miles}mi)")
        return result


class FR24DetailFetcher:
    """Fetch enrichment details from FR24 clickhandler endpoint (free)."""

    MAX_CACHE_SIZE = 200

    def __init__(self, cache_ttl: int = 43200, request_timeout: int = 8):
        self.cache: Dict[str, Dict] = {}
        self.cache_ttl = cache_ttl
        self.timeout = request_timeout

    def _evict_stale(self) -> None:
        """Remove expired entries and enforce max cache size."""
        now = time.time()
        # Remove expired
        expired = [k for k, v in self.cache.items()
                   if now - v.get('_fetched_at', 0) >= self.cache_ttl]
        for k in expired:
            del self.cache[k]
        # Enforce max size by evicting oldest
        if len(self.cache) > self.MAX_CACHE_SIZE:
            sorted_keys = sorted(self.cache, key=lambda k: self.cache[k].get('_fetched_at', 0))
            for k in sorted_keys[:len(self.cache) - self.MAX_CACHE_SIZE]:
                del self.cache[k]

    def fetch_detail(self, fr24_id: str) -> Optional[Dict]:
        """Fetch flight detail for a given FR24 flight ID."""
        cached = self.cache.get(fr24_id)
        if cached and time.time() - cached.get('_fetched_at', 0) < self.cache_ttl:
            return cached

        url = "https://data-live.flightradar24.com/clickhandler/"
        try:
            response = requests.get(url, params={"flight": fr24_id}, headers=_FR24_HEADERS, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            data['_fetched_at'] = time.time()
            self._evict_stale()
            self.cache[fr24_id] = data
            return data
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"[Flight Tracker] FR24 detail fetch failed for {fr24_id}: {e}")
            return None

    def enrich_aircraft(self, aircraft: Dict) -> None:
        """Fetch FR24 detail for an aircraft and apply airline/timing fields in-place."""
        fr24_id = aircraft.get('fr24_id')
        if not fr24_id:
            return

        detail = self.fetch_detail(fr24_id)
        if not detail:
            return

        airline = detail.get('airline') or {}
        if airline.get('name') and not aircraft.get('airline_name'):
            aircraft['airline_name'] = airline['name']

        airport = detail.get('airport') or {}
        origin_info = airport.get('origin') or {}
        dest_info = airport.get('destination') or {}
        origin_pos = origin_info.get('position') or {}
        dest_pos = dest_info.get('position') or {}
        if origin_pos.get('latitude') and not aircraft.get('origin_lat'):
            aircraft['origin_lat'] = origin_pos['latitude']
            aircraft['origin_lon'] = origin_pos['longitude']
        if dest_pos.get('latitude') and not aircraft.get('dest_lat'):
            aircraft['dest_lat'] = dest_pos['latitude']
            aircraft['dest_lon'] = dest_pos['longitude']

        time_data = detail.get('time') or {}
        aircraft['fr24_time'] = time_data


# ---------------------------------------------------------------------------
# OpenSky Network (free REST API)
# ---------------------------------------------------------------------------

class OpenSkyFetcher(AircraftFetcher):
    """Fetch aircraft from OpenSky Network REST API.

    Supports both anonymous and authenticated access.
    Anonymous: ~100 req/day, 10s position resolution.
    Authenticated: 4000 credits/day, 5s resolution.
    """

    API_URL = "https://opensky-network.org/api/states/all"

    def __init__(self, username: str = "", password: str = "", request_timeout: int = 15):
        self.auth = (username, password) if username and password else None
        self.timeout = request_timeout
        if self.auth:
            logger.info("[Flight Tracker] OpenSky: using authenticated access")
        else:
            logger.info("[Flight Tracker] OpenSky: using anonymous access (reduced rate limits)")

    def fetch(self, center_lat, center_lon, radius_miles, altitude_colors):
        # Convert radius to bounding box
        lat_deg = radius_miles / 69.0
        lon_deg = radius_miles / (69.0 * math.cos(math.radians(center_lat)))

        params = {
            "lamin": round(center_lat - lat_deg, 6),
            "lamax": round(center_lat + lat_deg, 6),
            "lomin": round(center_lon - lon_deg, 6),
            "lomax": round(center_lon + lon_deg, 6),
            "extended": 1,
        }

        try:
            response = requests.get(
                self.API_URL,
                params=params,
                auth=self.auth,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.exception("[Flight Tracker] OpenSky fetch failed")
            return None

        states = data.get("states")
        if not states:
            logger.info("[Flight Tracker] OpenSky: no aircraft in bounding box")
            return {}

        current_time = time.time()
        result: Dict[str, Dict] = {}

        for sv in states:
            # State vector indices (extended=1):
            # 0:icao24  1:callsign  2:origin_country  3:time_position
            # 4:last_contact  5:longitude  6:latitude  7:baro_altitude
            # 8:on_ground  9:velocity(m/s)  10:true_track  11:vertical_rate(m/s)
            # 12:sensors  13:geo_altitude  14:squawk  15:spi  16:position_source
            # 17:category
            try:
                icao = str(sv[0]).upper().strip()
                if not icao:
                    continue

                lon = sv[5]
                lat = sv[6]
                if lat is None or lon is None:
                    continue

                distance = haversine_miles(lat, lon, center_lat, center_lon)
                if distance > radius_miles:
                    continue

                # Convert from metric (OpenSky native) to imperial (internal convention)
                baro_alt_m = sv[7]
                geo_alt_m = sv[13]
                alt_m = baro_alt_m if baro_alt_m is not None else geo_alt_m
                altitude_ft = alt_m * 3.28084 if alt_m is not None else 0

                on_ground = bool(sv[8]) if sv[8] is not None else False
                if on_ground:
                    altitude_ft = 0

                velocity_ms = sv[9]
                speed_kts = velocity_ms * 1.94384 if velocity_ms is not None else 0

                true_track = sv[10]  # degrees from north
                heading = true_track if true_track is not None else 0

                vr_ms = sv[11]
                vr_fpm = vr_ms * 196.85 if vr_ms is not None else None

                callsign = str(sv[1]).strip() if sv[1] else icao
                category = str(sv[17]) if len(sv) > 17 and sv[17] is not None else ""

                color = altitude_to_color(altitude_ft, altitude_colors)

                result[icao] = {
                    'icao': icao,
                    'callsign': callsign,
                    'lat': lat,
                    'lon': lon,
                    'altitude': altitude_ft,
                    'speed': speed_kts,
                    'heading': heading,
                    'vertical_rate': vr_fpm,
                    'distance_miles': distance,
                    'color': color,
                    'on_ground': on_ground,
                    'category': category,
                    'aircraft_type': 'Unknown',
                    'registration': '',
                    'last_seen': current_time,
                }
            except (IndexError, TypeError, ValueError) as e:
                logger.debug(f"[Flight Tracker] OpenSky: skipping malformed state vector: {e}")
                continue

        logger.info(f"[Flight Tracker] OpenSky: {len(result)} aircraft in range ({radius_miles}mi)")
        return result


def create_fetcher(config: Dict[str, Any], cache_manager: Any) -> AircraftFetcher:
    """Factory: create the appropriate fetcher based on config['data_source']."""
    source = config.get('data_source', 'skyaware')

    if source == 'flightradar24':
        return FR24Fetcher()
    elif source == 'opensky':
        username = config.get('opensky_username', '')
        password = config.get('opensky_password', '')
        return OpenSkyFetcher(username=username, password=password)
    else:
        url = config.get('skyaware_url', 'http://192.168.86.30/skyaware/data/aircraft.json')
        return SkyAwareFetcher(url, cache_manager)
