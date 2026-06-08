"""
Election data providers.

Mirrors the multi-source pattern in ledmatrix-flights/fetcher.py: an
``ElectionProvider`` ABC plus a ``create_providers()`` factory that instantiates
only the providers enabled in config. Each provider normalizes its source into
the common ``Race`` model so the store/renderer never see provider details.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Set

from election_data_model import Race

logger = logging.getLogger(__name__)


class ElectionProvider(ABC):
    """Base class for election data providers."""

    #: Human-readable provider name; also stamped on each Race.source.
    name: str = "provider"

    @abstractmethod
    def fetch(self, state: Optional[str] = None) -> List[Race]:
        """Fetch and normalize races.

        ``state`` is the user's 2-letter state filter (or None for all). A
        provider may use it to scope its request; the store also filters again,
        so returning more than asked for is harmless.
        """
        ...

    def provides_states(self) -> Optional[Set[str]]:
        """States this provider covers.

        ``None`` means national / all states (NYT). A set like ``{"CA"}`` means
        the provider only supplements those states (CA-SoS). The store uses this
        to decide which provider wins the merge for a given state.
        """
        return None


def create_providers(config: dict, cache_manager: Any) -> List[ElectionProvider]:
    """Instantiate the NYT baseline plus the local source for the user's state.

    There's no per-provider on/off knob: NYT is the always-on national baseline,
    and a state's authoritative "local results" source auto-engages when
    ``local_races`` is on (default) and we support that state. Adding a new state
    source later means one entry in ``_LOCAL_PROVIDERS``, not a new config flag.
    """
    # Imported here to avoid a circular import at module load.
    from providers.nyt import NytStaticProvider
    from providers.ca_sos import CaSosProvider

    # State -> (config sub-key for that source's options, provider class).
    _LOCAL_PROVIDERS = {"CA": ("ca_sos", CaSosProvider)}

    providers: List[ElectionProvider] = []
    provider_cfg = config.get("providers", {})

    nyt_cfg = provider_cfg.get("nyt", {})
    if nyt_cfg.get("enabled", True):
        providers.append(NytStaticProvider(nyt_cfg, cache_manager))

    if config.get("local_races", True):
        state = (config.get("state") or "").upper()
        entry = _LOCAL_PROVIDERS.get(state)
        if entry:
            cfg_key, provider_cls = entry
            providers.append(provider_cls(provider_cfg.get(cfg_key, {}), cache_manager))

    if not providers:
        logger.warning("[Elections] No providers enabled in config")
    return providers
