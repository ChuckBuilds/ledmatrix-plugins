"""Timezone resolution for the NRL scoreboard plugin.

Event start times arrive from ESPN in UTC and have to be converted to the user's
local zone before they are drawn. This module owns the "which zone?" decision so
every render path and the plugin manager all agree.

Resolution order, first valid wins:

1. ``timezone`` in the plugin's own config (explicit per-plugin override)
2. The LEDMatrix global timezone via ``plugin_manager.config_manager``
3. The LEDMatrix global timezone via ``cache_manager.config_manager``
4. The host system's zone (``TZ``, ``/etc/timezone``, ``/etc/localtime``)
5. UTC

Steps 2 and 3 matter because the core does not consistently hang
``config_manager`` off both objects -- reading only one of them is what made
this plugin fall through to UTC while the clock plugin (which checks
``plugin_manager`` first) showed the right time on the same device. Step 4 is
the backstop for cores that expose no ``config_manager`` at all: a Pi with its
system clock set correctly should never end up rendering UTC.

Module name is plugin-prefixed on purpose -- several plugins ship identically
named top-level modules and the core loads them as bare names (see
``scripts/check_module_collisions.py``).
"""

import logging
import os
from typing import Any, Dict, Optional

import pytz

logger = logging.getLogger(__name__)


def _from_config_manager(config_manager: Any, log: logging.Logger) -> Optional[str]:
    """Pull a timezone name out of a core ConfigManager, if it offers one."""
    if config_manager is None:
        return None

    getter = getattr(config_manager, "get_timezone", None)
    if callable(getter):
        try:
            name = getter()
            if name:
                return name
        except Exception:
            log.debug("config_manager.get_timezone() failed", exc_info=True)

    # Older cores expose the raw config instead of a get_timezone() helper.
    for loader_name in ("load_config", "get_config"):
        loader = getattr(config_manager, loader_name, None)
        if not callable(loader):
            continue
        try:
            main_config = loader() or {}
            name = main_config.get("timezone")
            if name:
                return name
        except Exception:
            log.debug("config_manager.%s() failed", loader_name, exc_info=True)

    return None


def system_timezone_name() -> Optional[str]:
    """Best-effort IANA name for the host's configured timezone."""
    name = os.environ.get("TZ")
    if name:
        return name

    # Debian / Raspberry Pi OS record the zone name here.
    try:
        with open("/etc/timezone", "r", encoding="utf-8") as handle:
            name = handle.read().strip()
        if name:
            return name
    except OSError:
        pass

    # Otherwise /etc/localtime is a symlink into the zoneinfo tree.
    try:
        path = os.path.realpath("/etc/localtime")
        marker = "zoneinfo" + os.sep
        if marker in path:
            return path.split(marker, 1)[1]
    except OSError:
        pass

    return None


def resolve_timezone_name(
    config: Optional[Dict[str, Any]] = None,
    plugin_manager: Any = None,
    cache_manager: Any = None,
    log: Optional[logging.Logger] = None,
) -> str:
    """Return the IANA timezone name to render game times in.

    Never raises and never returns an empty string; falls back to ``"UTC"``
    only when every source is missing or invalid.
    """
    log = log or logger

    def candidates():
        """Yield (source, name) lazily.

        The per-event ``_get_timezone()`` helper runs this once per event, and
        the answer
        is almost always the first candidate. Evaluating the sources on demand
        keeps the common case from calling into both config managers and
        stat-ing the host timezone files every time.
        """
        yield "plugin config", (config or {}).get("timezone")
        yield (
            "plugin_manager.config_manager",
            _from_config_manager(getattr(plugin_manager, "config_manager", None), log),
        )
        yield (
            "cache_manager.config_manager",
            _from_config_manager(getattr(cache_manager, "config_manager", None), log),
        )
        yield "system timezone", system_timezone_name()

    for source, name in candidates():
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name:
            continue
        try:
            pytz.timezone(name)
        except Exception:
            log.warning("Ignoring invalid timezone %r from %s", name, source)
            continue
        log.debug("Resolved timezone %s from %s", name, source)
        return name

    log.warning(
        "Could not determine a timezone from the plugin config, the LEDMatrix "
        "config or the system; game times will be shown in UTC. Set a timezone "
        "in the NRL scoreboard's Advanced Settings to override."
    )
    return "UTC"


def resolve_timezone(
    config: Optional[Dict[str, Any]] = None,
    plugin_manager: Any = None,
    cache_manager: Any = None,
    log: Optional[logging.Logger] = None,
):
    """``resolve_timezone_name`` as a ready-to-use tzinfo object."""
    return pytz.timezone(
        resolve_timezone_name(
            config=config,
            plugin_manager=plugin_manager,
            cache_manager=cache_manager,
            log=log,
        )
    )
