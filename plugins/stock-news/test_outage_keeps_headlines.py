#!/usr/bin/env python3
"""
Regression tests: an outage does not empty the ticker, and a fetch does not
restart it mid-pass.

1. Every failure path in _fetch_stock_news (network error, request budget
   spent, empty RSS fallback) returns []. update() stored that over the
   symbol's last headlines, so during an outage the ticker emptied one symbol
   at a time -- and the rebuild that followed reset last_update, so the
   dimming meant to flag stale data never switched on.
2. _rebuild_all_news_items ran after every single-symbol fetch and reset the
   scroll, so the ticker restarted from its first headline mid-pass.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/stock-news/test_outage_keeps_headlines.py
Exit 0 pass, 1 fail, 2 skip.
"""

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)
try:
    from manager import StockNewsTickerPlugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


class Strip:
    def __init__(self):
        self.cached_image = "built"
        self.resets = 0

    def clear_cache(self):
        self.cached_image = None

    def reset_scroll(self):
        self.resets += 1


def plugin():
    p = object.__new__(StockNewsTickerPlugin)
    p.logger = logging.getLogger("test-stock-news")
    p._symbol_data = {}
    p.feeds_config = {"stock_symbols": ["AAPL", "MSFT"]}
    p.sync_with_stocks_plugin = False
    p.max_headlines_per_symbol = 2
    p.headlines_per_rotation = 2
    p.shuffle_headlines = False
    p._get_custom_feeds = lambda: {}
    p.scroll_helper = Strip()
    p._strip_rebuild_pending = False
    p.last_update = 0.0
    return p


headline = {"title": "Apple beats", "symbol": "AAPL"}

p = plugin()
check("a fetch that returns headlines stores them and asks for a rebuild",
      p._store_items("AAPL", [headline]) is True and p._symbol_data["AAPL"] == [headline])
check("a failed fetch keeps the symbol's last headlines",
      p._store_items("AAPL", []) is False and p._symbol_data["AAPL"] == [headline])
check("a first fetch that fails is still recorded, so the eager fill moves on",
      p._store_items("MSFT", []) is False and p._symbol_data.get("MSFT") == [])

p = plugin()
p._symbol_data = {"AAPL": [headline]}
p._rebuild_all_news_items()
check("new headlines do not reset the scroll mid-pass", p.scroll_helper.resets == 0,
      "reset %d time(s)" % p.scroll_helper.resets)
check("the strip is kept until the pass ends", p.scroll_helper.cached_image == "built")
check("a rebuild is queued for the end of the pass", p._strip_rebuild_pending is True)
check("the headlines themselves are updated", p.all_news_items == [headline])

p = plugin()
p.scroll_helper.cached_image = None
p._rebuild_all_news_items()
check("with no strip yet nothing is queued; the next frame builds one",
      p._strip_rebuild_pending is False)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
