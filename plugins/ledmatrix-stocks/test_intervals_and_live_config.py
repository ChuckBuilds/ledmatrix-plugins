#!/usr/bin/env python3
"""
Regression tests for ledmatrix-stocks:

1. update_interval is honoured. Core prefers the manifest's 600 over the
   plugin's config unless the plugin implements get_update_interval().
2. crypto.update_interval does something: crypto quotes are cached for it, and
   update() is asked for at the shorter of the two intervals. It was read into
   the config manager and never used.
3. A web-UI save applies without a restart (there was no on_config_change) and
   re-runs the scroll resolver.
4. The "No Data Available" message fits the panel (136px in the 8px font on a
   128px panel, centred off both edges).

The network is never touched: the cache stub answers every quote.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-stocks/test_intervals_and_live_config.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from PIL import Image
    import src
    from src.common import scroll_config  # noqa: F401  (3.4.0 floor)
except ImportError as exc:
    print(f"SKIP: LEDMatrix core (3.4.0+) or Pillow not importable: {exc}")
    sys.exit(2)

# Fonts resolve relative to the core checkout, as on a real install.
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(src.__file__))))

from manager import StockTickerPlugin  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class FakeDisplay:
    refresh_hz = 100.0

    def __init__(self, width=128, height=32):
        self.width = width
        self.height = height
        self.image = Image.new("RGB", (width, height))
        self.calls = []

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def process_deferred_updates(self):
        pass

    def update_display(self):
        pass


class RecordingCache:
    """Answers every quote from 'cache' and records the max_age asked for."""

    def __init__(self):
        self.max_ages = {}

    def get(self, key, max_age=None, **kwargs):
        self.max_ages[key] = max_age
        return {"symbol": key, "price": 1.0, "change": 0.1, "change_percent": 1.0,
                "price_history": [], "is_crypto": "BTC" in key}

    def set(self, *args, **kwargs):
        pass


CONFIG = {
    "enabled": True,
    "update_interval": 900,
    "display": {"display_mode": "scroll", "scroll_speed": 1.0, "scroll_delay": 0.02},
    "stocks": {"enabled": True, "symbols": ["AAPL"]},
    "crypto": {"enabled": True, "symbols": ["BTC-USD"], "update_interval": 120},
}


def test_intervals():
    print("[update_interval and crypto.update_interval]")
    cache = RecordingCache()
    plugin = StockTickerPlugin("ledmatrix-stocks", CONFIG, FakeDisplay(), cache,
                               types.SimpleNamespace())
    interval = plugin.get_update_interval()
    check(interval == 120,
          f"update() is asked for at the shorter crypto interval, 120s (got {interval})")

    plugin.data_fetcher.fetch_stock_data("AAPL", is_crypto=False)
    plugin.data_fetcher.fetch_stock_data("BTC-USD", is_crypto=True)
    check(cache.max_ages.get("stock_data_AAPL") == 900,
          f"stock quotes are cached for update_interval (max_age {cache.max_ages.get('stock_data_AAPL')})")
    check(cache.max_ages.get("stock_data_BTC") == 120,
          f"crypto quotes are cached for crypto.update_interval (max_age {cache.max_ages.get('stock_data_BTC')})")


def test_live_config():
    print("[on_config_change]")
    display = FakeDisplay()
    plugin = StockTickerPlugin("ledmatrix-stocks", CONFIG, display, RecordingCache(),
                               types.SimpleNamespace())
    new_config = dict(CONFIG, update_interval=300,
                      display={"display_mode": "scroll", "scroll_speed": 1.0, "scroll_delay": 0.01},
                      stocks={"enabled": True, "symbols": ["AAPL", "MSFT"]},
                      crypto={"enabled": False})
    plugin.on_config_change(new_config)

    settings = getattr(plugin, "_scroll_settings", None)
    requested = getattr(settings, "requested_pixels_per_second", None)
    check(requested is not None and abs(requested - 100.0) < 0.01,
          f"the scroll resolver re-ran for the new 100 px/s (got {requested})")
    check(plugin.get_update_interval() == 300,
          f"the new update_interval applies without a restart (got {plugin.get_update_interval()})")
    check(plugin.config_manager.stock_symbols == ["AAPL", "MSFT"],
          f"new symbols apply without a restart (got {plugin.config_manager.stock_symbols})")
    check(plugin.data_fetcher.stock_symbols == ["AAPL", "MSFT"],
          f"the fetcher uses the new symbols (got {plugin.data_fetcher.stock_symbols})")


def test_error_display_fits():
    print("[No Data Available fallback]")
    display = FakeDisplay(128, 32)
    plugin = StockTickerPlugin("ledmatrix-stocks", CONFIG, display, RecordingCache(),
                               types.SimpleNamespace())
    image = plugin.display_renderer._create_error_display()
    box = image.getbbox()
    check(box is not None, "the message was drawn")
    if box:
        check(box[0] > 0 and box[2] < 128,
              f"the message fits the 128px panel (ink spans x={box[0]}..{box[2]})")


if __name__ == "__main__":
    for test in (test_intervals, test_live_config, test_error_display_fits):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
