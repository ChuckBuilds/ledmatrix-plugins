"""Timezone resolution for the football scoreboard plugin.

Game start times arrive from ESPN/MLB in UTC and have to be converted to the
user's local zone before they are drawn. This module owns the "which zone?"
decision so the switch-mode scorebug (``sports.py``), the scroll-mode game card
(``game_renderer.py``) and the plugin manager all agree.

The resolution itself is core's ``src.common.sports_timezone``: the plugin's
own ``timezone`` setting, then the LEDMatrix global timezone, then the host's
zone, then UTC (its docstring has the details and the traps it avoids). This
module binds it to this plugin: the name in its "could not determine a
timezone" warning, whether this plugin ever wrote a resolved timezone back into
the saved config, and this module's logger, which is where the records go when
the caller passes no ``log``.

Module name is plugin-prefixed on purpose -- several plugins ship identically
named top-level modules and the core loads them as bare names (see
``scripts/check_module_collisions.py``).
"""

import logging
from typing import Any, Dict, Optional

import src.common.sports_timezone as _core

logger = logging.getLogger(__name__)

# Part of this module's API; resolution reads core's own binding of it.
system_timezone_name = _core.system_timezone_name

_CORE_ARGS: Dict[str, Any] = {
    "plugin_label": "football scoreboard",
    # Before 2.9.0 this plugin wrote "timezone": "UTC" into the saved config
    # whenever resolution failed, and it stuck. Core therefore honours a bare
    # plugin-level "UTC" only when nothing downstream disagrees, and names this
    # release in the warning when it overrides one ("Etc/UTC" always wins).
    "writeback_fixed_in": "2.9.0",
}


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
    return _core.resolve_timezone_name(
        config, plugin_manager, cache_manager, log or logger, **_CORE_ARGS)


def resolve_timezone(
    config: Optional[Dict[str, Any]] = None,
    plugin_manager: Any = None,
    cache_manager: Any = None,
    log: Optional[logging.Logger] = None,
):
    """``resolve_timezone_name`` as a ready-to-use tzinfo object."""
    return _core.resolve_timezone(
        config, plugin_manager, cache_manager, log or logger, **_CORE_ARGS)
