#!/usr/bin/env python3
"""
Regression tests: quotes refresh on schedule, stock and crypto do not share
a cache entry, and a sub-cent coin is not drawn as $0.00.

1. The quote cache was read with max_age equal to the update interval. Each
   entry is written partway through an update, so at the next scheduled
   update it was still fresh and every symbol refreshed only every other
   time: quotes up to twice update_interval old.
2. Stock SOL and crypto SOL-USD both display as "SOL" and shared the key
   stock_data_SOL, so each could be served the other's quote.
3. Prices and changes were rounded to cents when fetched and drawn with
   :.2f, so a coin worth $0.00001234 read $0.00 +0.00.

Run: python plugins/ledmatrix-stocks/test_quote_cache_and_prices.py
Exit 0 pass, 1 fail, 2 skip.
"""

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
try:
    import data_fetcher as df  # noqa: E402
    from display_renderer import format_money  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


class RecordingCache:
    def __init__(self):
        self.store, self.reads = {}, []

    def get(self, key, max_age=300):
        self.reads.append((key, max_age))
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data


fetcher = object.__new__(df.StockDataFetcher)
fetcher.logger = logging.getLogger("test-stocks")
fetcher.cache_manager = RecordingCache()
fetcher.config_manager = SimpleNamespace(update_interval=600, crypto_update_interval=300)
fetched = []
fetcher._fetch_direct = lambda api, disp, is_crypto: fetched.append(api) or {
    "symbol": disp, "price": 1.0, "is_crypto": is_crypto}

fetcher.fetch_stock_data("SOL")
fetcher.fetch_stock_data("SOL-USD", is_crypto=True)
check("stock SOL and crypto SOL-USD are fetched separately",
      fetched == ["SOL", "SOL-USD"], fetched)
check("and cached under different keys",
      len(fetcher.cache_manager.store) == 2, sorted(fetcher.cache_manager.store))
check("the crypto entry is not the stock's",
      fetcher.cache_manager.store.get("crypto_data_SOL", {}).get("is_crypto") is True)
check("a stock quote is reused for at most half of update_interval",
      fetcher.cache_manager.reads[0][1] == 300, fetcher.cache_manager.reads[0])
check("a crypto quote for at most half of crypto.update_interval",
      fetcher.cache_manager.reads[1][1] == 150, fetcher.cache_manager.reads[1])

check("prices from $0.10 up draw as before", format_money(123.456) == "123.46"
      and format_money(0.1) == "0.10" and format_money(-1.5, signed=True) == "-1.50")
check("a sub-cent coin keeps its digits", format_money(0.00001234) == "0.00001234",
      format_money(0.00001234))
check("so does its change", format_money(-0.0000345, signed=True) == "-0.00003450",
      format_money(-0.0000345, signed=True))
check("the fetcher no longer rounds a sub-cent price to 0",
      df._round_money(0.00001234) == 0.00001234 and df._round_money(1.234) == 1.23)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
