"""Enrichment providers for the Flight Tracker plugin."""

import logging

from enrichment.base import EnrichmentProvider

logger = logging.getLogger(__name__)
from enrichment.opensky import OpenSkyEnrichment
from enrichment.flightaware import FlightAwareEnrichment
from enrichment.adsbnet import AdsbNetEnrichment
from enrichment.stub import StubEnrichment


def create_enrichment_provider(config: dict, cache_manager=None) -> EnrichmentProvider:
    """Factory: create the appropriate enrichment provider based on config.

    Priority:
      - ``"flightaware"`` + key present + paid calls enabled: FlightAware
        AeroAPI (paid)
      - ``"adsbnet"`` or ``"auto"`` (default): adsb.lol callsign lookup (free)
      - ``"opensky"``: OpenSky Network (legacy, kept for manual config compat)
      - Fallback: StubEnrichment (no-op)

    ``config`` must already be normalized by the manager
    (``FlightTrackerPlugin._normalize_flightaware_config``), which writes the
    resolved ``flightaware.enabled`` / ``flightaware.api_key`` onto the flat
    ``flight_plan_enabled`` / ``flightaware_api_key`` keys read here.

    The paid provider needs ``flight_plan_enabled`` as well as a key. Checking
    the key alone meant that switching "Enable paid FlightAware API calls" off
    kept every tracked-flight lookup billing, as long as the provider was still
    set to flightaware and the key was still saved.
    """
    provider = config.get("enrichment_provider", "adsbnet")
    fa_key = config.get("flightaware_api_key", "")
    fa_enabled = config.get("flight_plan_enabled", False) is True

    if provider == "flightaware":
        if fa_key and fa_enabled:
            return FlightAwareEnrichment(config, cache_manager)
        # Not configured or switched off: use the free adsbnet lookup rather
        # than silently doing nothing.
        if not fa_enabled:
            logger.info("[Flight Tracker] enrichment_provider=flightaware but paid FlightAware calls are "
                        "off (flightaware.enabled) — using adsbnet")
        else:
            logger.warning("[Flight Tracker] enrichment_provider=flightaware but no API key — falling back to adsbnet")
        provider = "adsbnet"

    if provider in ("adsbnet", "auto"):
        route_ttl = config.get("route_cache_ttl", 300)
        return AdsbNetEnrichment(cache_manager=cache_manager, route_cache_ttl=route_ttl)

    if provider == "opensky":
        username = config.get("opensky_username", "")
        password = config.get("opensky_password", "")
        route_ttl = config.get("route_cache_ttl", 300)
        return OpenSkyEnrichment(username=username, password=password,
                                 cache_manager=cache_manager, route_cache_ttl=route_ttl)

    return StubEnrichment()
