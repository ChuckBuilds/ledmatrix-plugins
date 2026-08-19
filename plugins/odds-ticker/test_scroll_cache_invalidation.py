#!/usr/bin/env python3
"""The ticker must rebuild after something else clears its scroll cache.

Regression under test, observed on a live 512x64 rig: the panel intermittently
showed "No odds data" while ESPN was returning games perfectly well. Over three
days of logs there were ten such frames and *zero* occurrences of the two
conditions that message is supposed to mean -- games_data was never empty and
ticker_image was never None. Every one came from
``ScrollHelper.get_visible_portion()`` returning None.

Vegas invalidates a plugin's scroll cache whenever the plugin reports an
update, by setting ``scroll_helper.cached_image`` and ``cached_array`` to None
(``PluginAdapter.invalidate_plugin_scroll_cache``). That is deliberate: it is
what stops last night's live game being redrawn this morning. On the rig it
fired about once a minute.

It cannot clear ``self.ticker_image`` -- that attribute is private to this
plugin. ``display()`` decided whether to rebuild by testing ``ticker_image``
alone, so between the invalidation and this plugin's own next rebuild (an hour
away, ``base_update_interval``, whenever no game is live) it skipped the
rebuild, got None back from the helper, and drew the fallback.

The methods run against a stand-in ``self`` carrying only what display()
touches, with a real ScrollHelper, so the cache behaviour under test is the
real one. Only per-game rendering is stubbed -- it needs fonts and logos and
has nothing to do with this.

Run: <core-venv>/bin/python plugins/odds-ticker/test_scroll_cache_invalidation.py
"""

import sys
import time
from pathlib import Path

from PIL import Image

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import OddsTickerPlugin  # noqa: E402
from src.common.scroll_helper import ScrollHelper  # noqa: E402
from src.vegas_mode.plugin_adapter import PluginAdapter  # noqa: E402

WIDTH, HEIGHT = 128, 32
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Matrix:
    width, height = WIDTH, HEIGHT


class _DisplayManager:
    def __init__(self):
        self.matrix = _Matrix()
        self.image = Image.new('RGB', (WIDTH, HEIGHT), (0, 0, 0))
        self.updated = 0

    def update_display(self):
        self.updated += 1

    def set_scrolling_state(self, state):
        pass


class _Ticker:
    """A stand-in ``self`` carrying only what display() touches."""

    # The methods under test, unmodified.
    display = OddsTickerPlugin.display
    _create_ticker_image = OddsTickerPlugin._create_ticker_image

    def __init__(self):
        self.is_enabled = True
        self.loop = True
        self.display_manager = _DisplayManager()
        self.scroll_helper = ScrollHelper(WIDTH, HEIGHT)
        self.games_data = [{"id": "g1"}, {"id": "g2"}]
        self.ticker_image = None
        self.dynamic_duration = 30
        self.current_game_index = 0
        self.total_scroll_width = 0
        self._display_start_time = None
        self._end_reached_logged = False
        self._insufficient_time_warning_logged = False
        self.fallbacks = 0
        # No update is due: this is the window between the plugin's own
        # rebuilds, which is exactly when the bug bites.
        self.last_update = time.time()

    # -- stubs, none of which touch the caching under test -----------------
    def _create_game_display(self, game):
        return Image.new('RGB', (60, HEIGHT), (10, 20, 30))

    def _get_current_update_interval(self):
        return 3600

    def _perform_update(self, preserve_scroll=False):
        raise AssertionError("no update is due; display() must not call this")

    def _display_fallback_message(self):
        self.fallbacks += 1


def _invalidate_like_vegas(ticker):
    """Exactly what Vegas does when the plugin reports an update.

    Calls the real PluginAdapter method rather than reimplementing it, so a
    change to how core invalidates is picked up here instead of leaving this
    test asserting against a stale copy.
    """
    adapter = object.__new__(PluginAdapter)
    return PluginAdapter.invalidate_plugin_scroll_cache(
        adapter, ticker, 'odds-ticker')


def main():
    print("the invalidation this plugin has to survive")
    ticker = _Ticker()
    ticker._create_ticker_image()
    check("a ticker image is built from the games data",
          ticker.ticker_image is not None)
    check("and the scroll helper is populated",
          ticker.scroll_helper.cached_image is not None)

    cleared = _invalidate_like_vegas(ticker)
    check("core's invalidation finds and clears this plugin's cache", cleared)
    check("the helper's image is gone",
          ticker.scroll_helper.cached_image is None)
    check("the helper's array is gone too",
          ticker.scroll_helper.cached_array is None)
    check("but ticker_image is untouched -- core cannot see it",
          ticker.ticker_image is not None)

    print("\nthe next frame must rebuild rather than give up")
    ticker.display()
    check("no 'No odds data' fallback is drawn (%d drawn)" % ticker.fallbacks,
          ticker.fallbacks == 0)
    check("the scroll cache was rebuilt",
          ticker.scroll_helper.cached_image is not None)
    check("and a frame reached the display",
          ticker.display_manager.updated > 0)

    print("\nrepeated invalidation keeps working, not just the first")
    for _ in range(3):
        _invalidate_like_vegas(ticker)
        ticker.display()
    check("three more invalidate/display cycles drew no fallback",
          ticker.fallbacks == 0)

    print("\nan empty games list still reports honestly")
    empty = _Ticker()
    empty.games_data = []
    empty._create_ticker_image()
    empty.display()
    check("with no games at all, the fallback is what should appear",
          empty.fallbacks >= 1)

    print("\nan untouched cache is reused, not rebuilt every frame")
    warm = _Ticker()
    warm._create_ticker_image()
    first = warm.scroll_helper.cached_image
    warm.display()
    check("the same cached image object is still in place",
          warm.scroll_helper.cached_image is first)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
