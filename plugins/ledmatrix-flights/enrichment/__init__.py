"""Enrichment providers for the Flight Tracker plugin."""

from enrichment.base import EnrichmentProvider
from enrichment.opensky import OpenSkyEnrichment
from enrichment.flightaware import FlightAwareEnrichment
from enrichment.stub import StubEnrichment


def create_enrichment_provider(config: dict, cache_manager=None) -> EnrichmentProvider:
    """Factory: create the appropriate enrichment provider based on config.

    Priority:
      - If ``enrichment_provider`` is ``"flightaware"`` AND a key is present: FlightAware
      - If ``enrichment_provider`` is ``"opensky"`` or ``"auto"``: OpenSky (free)
      - Fallback: StubEnrichment (no-op)
    """
    provider = config.get("enrichment_provider", "auto")
    fa_key = config.get("flightaware_api_key", "")

    if provider == "flightaware" and fa_key:
        return FlightAwareEnrichment(config, cache_manager)

    if provider in ("auto", "opensky"):
        # In auto mode, prefer OpenSky (free) but also return FlightAware if key is present
        # The manager can chain them
        username = config.get("opensky_username", "")
        password = config.get("opensky_password", "")
        route_ttl = config.get("route_cache_ttl", 300)
        return OpenSkyEnrichment(username=username, password=password,
                                 cache_manager=cache_manager, route_cache_ttl=route_ttl)

    return StubEnrichment()
