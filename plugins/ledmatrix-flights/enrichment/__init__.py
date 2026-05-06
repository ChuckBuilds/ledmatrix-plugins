"""Enrichment providers for the Flight Tracker plugin."""

from enrichment.base import EnrichmentProvider
from enrichment.opensky import OpenSkyEnrichment
from enrichment.flightaware import FlightAwareEnrichment
from enrichment.adsbnet import AdsbNetEnrichment
from enrichment.stub import StubEnrichment


def create_enrichment_provider(config: dict, cache_manager=None) -> EnrichmentProvider:
    """Factory: create the appropriate enrichment provider based on config.

    Priority:
      - ``"flightaware"`` + key present: FlightAware AeroAPI (paid)
      - ``"adsbnet"`` or ``"auto"`` (default): adsb.lol callsign lookup (free)
      - ``"opensky"``: OpenSky Network (legacy, kept for manual config compat)
      - Fallback: StubEnrichment (no-op)
    """
    provider = config.get("enrichment_provider", "adsbnet")
    fa_key = config.get("flightaware_api_key", "")

    if provider == "flightaware" and fa_key:
        return FlightAwareEnrichment(config, cache_manager)

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
