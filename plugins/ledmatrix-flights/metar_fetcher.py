"""
NOAA Aviation Weather Center (AWC) fetcher for the Flight Tracker plugin.

Pulls aviation weather for user-chosen airports from the AWC Data API
(https://aviationweather.gov/api/data/) — a free, public service that needs
**no API key and no authentication**:

  - METAR (current observation)  ``/metar?ids=KTPA,KJFK&format=json``
  - TAF   (terminal forecast)     ``/taf?ids=KTPA&format=json``
  - PIREP  (pilot reports)        ``/pirep?id=KTPA&distance=200&format=json``
  - SIGMET/AIRMET (advisories)    ``/airsigmet?format=json``

Follows the same cache-first / serve-stale pattern as the ``enrichment/``
providers: reads through the injected ``cache_manager`` (``get(key, max_age=…)``
then ``set(key, data)``), serves the last-good cached copy on any network error,
and never raises to the caller. METAR/TAF requests are batched with a
comma-joined ``ids=`` so several airports cost a single request each.

Module name is plugin-unique (imported at the top of manager.py) per the
monorepo cross-plugin module-collision rule.
"""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = "LEDMatrix-FlightTracker/1.11 (+https://github.com/ChuckBuilds/ledmatrix-plugins)"

# Cloud covers that establish a ceiling (lowest broken/overcast/obscured layer).
_CEILING_COVERS = ("BKN", "OVC", "OVX")


class MetarFetcher:
    """Fetch and normalize aviation weather from the free NOAA AWC API."""

    BASE_URL = "https://aviationweather.gov/api/data"

    def __init__(self, config: Optional[Dict[str, Any]] = None, cache_manager: Any = None):
        """Read the ``metar`` config block and set up the cache-backed HTTP session.
        Malformed numeric options fall back to safe defaults rather than raising, so
        a bad config can never crash plugin construction."""
        m = (config or {}).get("metar", {}) or {}
        self.cache_manager = cache_manager
        self.show_taf = bool(m.get("show_taf", True))
        try:
            self.pirep_distance_nm = int(m.get("pirep_distance_nm", 200))
        except (TypeError, ValueError):
            self.pirep_distance_nm = 200

        # TTLs: METAR follows the configured refresh cadence (obs update ~hourly);
        # TAF/PIREP/SIGMET change slowly so keep them a bit longer.
        try:
            refresh_min = int(m.get("update_interval_minutes", 10))
        except (TypeError, ValueError):
            refresh_min = 10
        self.metar_ttl = max(60, refresh_min * 60)
        self.taf_ttl = max(self.metar_ttl, 1800)
        self.pirep_ttl = 900
        self.sigmet_ttl = 900
        self.timeout = 8

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    # ------------------------------------------------------------------ HTTP

    def _get_json(self, path: str, params: Dict[str, Any], cache_key: str, ttl: int) -> Any:
        """Cache-first GET returning parsed JSON. On failure, serve the last-good
        cached copy (ignoring age); return None if nothing is cached."""
        if self.cache_manager is not None:
            cached = self.cache_manager.get(cache_key, max_age=ttl)
            if cached is not None:
                return cached

        url = f"{self.BASE_URL}/{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"[Flight Tracker] AWC request failed ({path} {params}): {e}")
            if self.cache_manager is not None:
                stale = self.cache_manager.get(cache_key)  # no max_age -> any age
                if stale is not None:
                    logger.info(f"[Flight Tracker] Serving stale AWC cache for {cache_key}")
                    return stale
            return None

        if self.cache_manager is not None:
            self.cache_manager.set(cache_key, data)
        return data

    # ------------------------------------------------------------- METAR/TAF

    def fetch_weather(self, icaos: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch METARs (and TAFs when enabled) for *icaos* in one batched call
        each. Returns a dict keyed by ICAO of normalized weather dicts."""
        codes = [c.strip().upper() for c in (icaos or []) if c and c.strip()]
        if not codes:
            return {}
        ids = ",".join(codes)

        result: Dict[str, Dict[str, Any]] = {}
        metars = self._get_json("metar", {"ids": ids, "format": "json"},
                                f"metar_wx_{ids}", self.metar_ttl)
        for obs in metars or []:
            if not isinstance(obs, dict):
                continue
            code = str(obs.get("icaoId") or obs.get("id") or "").upper()
            if code:
                result[code] = self._normalize_metar(obs)

        if self.show_taf:
            tafs = self._get_json("taf", {"ids": ids, "format": "json"},
                                  f"taf_wx_{ids}", self.taf_ttl)
            for t in tafs or []:
                if not isinstance(t, dict):
                    continue
                code = str(t.get("icaoId") or t.get("id") or "").upper()
                raw_taf = (t.get("rawTAF") or t.get("rawTaf") or "").strip()
                if not code:
                    continue
                if code in result:
                    result[code]["raw_taf"] = raw_taf
                else:
                    result[code] = {"icao": code, "name": "", "raw": "",
                                    "flt_cat": "", "raw_taf": raw_taf}
        return result

    def _normalize_metar(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten one AWC METAR object into the plugin's normalized schema."""
        clouds: List[tuple] = []
        ceiling_ft: Optional[int] = None
        for layer in obs.get("clouds") or []:
            if not isinstance(layer, dict):
                continue
            cover = str(layer.get("cover") or "").upper()
            base = layer.get("base")
            clouds.append((cover, base))
            if ceiling_ft is None and cover in _CEILING_COVERS and isinstance(base, (int, float)):
                ceiling_ft = int(base)

        # AWC reports altimeter in hectopascals (~950-1050). Convert to inHg
        # (~28-31) for the US pilot convention; guard against feeds already inHg.
        altim = obs.get("altim")
        altim_inhg: Optional[float] = None
        if isinstance(altim, (int, float)):
            altim_inhg = round(altim * 0.02953, 2) if altim > 100 else round(float(altim), 2)

        return {
            "icao": str(obs.get("icaoId") or obs.get("id") or "").upper(),
            "name": obs.get("name") or "",
            "raw": (obs.get("rawOb") or "").strip(),
            "flt_cat": str(obs.get("fltCat") or "").upper(),
            "wind_dir": obs.get("wdir"),
            "wind_spd": obs.get("wspd"),
            "wind_gust": obs.get("wgst"),
            "vis": obs.get("visib"),
            "wx_string": (obs.get("wxString") or "").strip(),
            "clouds": clouds,
            "ceiling_ft": ceiling_ft,
            "temp_c": obs.get("temp"),
            "dewp_c": obs.get("dewp"),
            "altim_inhg": altim_inhg,
            "obs_time": obs.get("obsTime"),
            "raw_taf": "",
        }

    # ---------------------------------------------------------------- PIREP

    def fetch_pireps(self, icao: str, distance_nm: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch recent pilot reports near *icao*. Returns a list of
        ``{raw, type}`` dicts (most recent first as returned by AWC)."""
        code = (icao or "").strip().upper()
        if not code:
            return []
        dist = int(distance_nm or self.pirep_distance_nm)
        data = self._get_json("pirep", {"id": code, "distance": dist, "format": "json"},
                              f"pirep_wx_{code}_{dist}", self.pirep_ttl)
        pireps: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for p in data:
                if not isinstance(p, dict):
                    continue
                raw = (p.get("rawOb") or p.get("raw") or p.get("report") or "").strip()
                if raw:
                    pireps.append({
                        "raw": raw,
                        "type": str(p.get("airepType") or p.get("obsType") or "").upper(),
                    })
        return pireps

    # -------------------------------------------------------- SIGMET/AIRMET

    def fetch_sigmets(self) -> List[Dict[str, Any]]:
        """Fetch active domestic SIGMET/AIRMET advisories. These are region-based
        (not airport-specific); returns a list of ``{type, hazard, raw}`` dicts."""
        data = self._get_json("airsigmet", {"format": "json"}, "airsigmet_wx", self.sigmet_ttl)
        sigmets: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for s in data:
                if not isinstance(s, dict):
                    continue
                sigmets.append({
                    "type": str(s.get("airSigmetType") or s.get("type") or "").upper(),
                    "hazard": str(s.get("hazard") or "").upper(),
                    "raw": (s.get("rawAirSigmet") or s.get("raw") or "").strip(),
                })
        return sigmets
