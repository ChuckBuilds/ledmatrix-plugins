#!/usr/bin/env python3
"""
Regression test: rebuilding the league registry must not be visible mid-flight.

``on_config_change`` runs on the core's ``ConfigService-Watcher`` thread, not
the render thread. It rebuilds the league registry, while the display path
iterates that same dict:

    _display_scroll_mode -> _get_enabled_leagues_for_mode
        -> for league_id, league_data in self._league_registry.items()

The rebuild used to clear the live dict and repopulate it key by key, so saving
config while a soccer frame was rendering could show a frame with no leagues,
or raise "dictionary changed size during iteration" inside display().

``_initialize_league_registry`` now builds into a local and publishes it with a
single attribute rebind, which is atomic. A reader sees either the whole old
registry or the whole new one.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_league_registry_atomic_swap.py
"""

import os
import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    mod("src")
    mod("src.common")
    mod("src.plugin_system")
    mod("src.logo_downloader", LogoDownloader=object, download_missing_logo=lambda *a, **k: None)
    mod("src.common.scroll_helper", ScrollHelper=object)
    mod("src.plugin_system.base_plugin", BasePlugin=None, VegasDisplayMode=object)
    mod("src.background_data_service", get_background_service=lambda *a, **k: None)

    # The stubs above are plain ModuleTypes, so `from src.common.X import Y`
    # fails with "'src.common' is not a package" even when a real core is on
    # the path. Giving them a __path__ lets genuine submodules -- sports_shared,
    # sports_card -- resolve from the core while the stubbed ones stay stubbed.
    # Stubbing those too would make this test pass against dummies instead of
    # the code under test.
    _core = os.environ.get("LEDMATRIX_CORE") or next(
        (p for p in sys.path
         if p and os.path.isdir(os.path.join(p, "src", "common"))), None)
    if _core:
        if "src" in sys.modules and not hasattr(sys.modules["src"], "__path__"):
            sys.modules["src"].__path__ = [os.path.join(_core, "src")]
        if ("src.common" in sys.modules
                and not hasattr(sys.modules["src.common"], "__path__")):
            sys.modules["src.common"].__path__ = [
                os.path.join(_core, "src", "common")]


_stub_core_src()

import logging  # noqa: E402
import inspect  # noqa: E402

from manager import SoccerScoreboardPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


def make_plugin():
    p = SoccerScoreboardPlugin.__new__(SoccerScoreboardPlugin)
    p.logger = logging.getLogger("test-soccer-registry-swap")
    p.config = {"enabled": True, "custom_leagues": []}
    p.display_manager = None
    p.cache_manager = None
    p.plugin_manager = None
    p.league_enabled = {}
    p.league_live_priority = {}
    p._league_registry = {}
    p.custom_league_map = {}
    return p


plugin = make_plugin()
plugin._initialize_league_registry()
first = plugin._league_registry
check("registry is populated", len(first) > 0)

# The old dict must survive the rebuild intact: a display thread that grabbed a
# reference before the swap keeps iterating a complete registry.
snapshot = plugin._league_registry
before_len = len(snapshot)
plugin._initialize_league_registry()

check("rebuild rebinds rather than mutating in place",
      plugin._league_registry is not snapshot)
check("the previously-published dict is left intact",
      len(snapshot) == before_len)
check("new registry is complete", len(plugin._league_registry) == before_len)

# Guard the mechanism itself, so a later refactor can't quietly reintroduce
# in-place mutation of the published dict.
src = inspect.getsource(SoccerScoreboardPlugin._initialize_league_registry)
check("no in-place writes to the published registry",
      "self._league_registry[" not in src)
check("publishes with a single rebind",
      src.count("self._league_registry = registry") == 1)

occ_src = inspect.getsource(SoccerScoreboardPlugin.on_config_change)
check("on_config_change no longer clears the live registry",
      "self._league_registry.clear()" not in occ_src)

# --- a reader must survive a replacement landing mid-selection ------------
# _get_enabled_leagues_for_mode iterates the registry, then sorts and logs
# using it again. If those later reads re-fetched self._league_registry, a
# config save that drops a custom league between the iteration and the sort
# would raise KeyError on the render thread.
swapped = make_plugin()
swapped._league_registry = {
    "eng.1": {"enabled": True, "priority": 1, "is_custom": False, "managers": {}},
    "cus.1": {"enabled": True, "priority": 2, "is_custom": True, "managers": {}},
}
swapped._get_league_config = lambda lid, data: {}

original_items = swapped._league_registry.items


class _SwapOnIterate(dict):
    """Rebinds the plugin's registry the moment the selection iterates it,
    standing in for on_config_change landing on the watcher thread."""

    def items(self):
        # The replacement no longer has the custom league.
        swapped._league_registry = {
            "eng.1": {"enabled": True, "priority": 1, "is_custom": False, "managers": {}},
        }
        return original_items()


swapped._league_registry = _SwapOnIterate(swapped._league_registry)
try:
    selected = swapped._get_enabled_leagues_for_mode("live")
    raised = None
except KeyError as exc:
    selected, raised = None, exc

check("a registry replacement mid-selection does not raise KeyError", raised is None)
check("the selection reflects the registry it started from",
      selected is not None and "cus.1" in selected)

# The membership test and lookup in _get_league_manager_for_mode must also
# agree with each other.
mgr_plugin = make_plugin()
mgr_plugin._league_registry = {"eng.1": {"enabled": True, "managers": {"live": "M"}}}
check("manager lookup returns from the same snapshot it tested",
      mgr_plugin._get_league_manager_for_mode("eng.1", "live") == "M")

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    for case in failed:
        print(f"  FAILED: {case}")
    sys.exit(1)
