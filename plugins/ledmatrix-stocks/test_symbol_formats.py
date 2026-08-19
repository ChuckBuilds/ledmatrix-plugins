#!/usr/bin/env python3
"""Which symbols the ticker will accept, and what it asks Yahoo for.

Reported on Discord: gold could not be added because it is GC=F, and the
symbol field would not take it. The schema pattern was ^\\^?[A-Z]{1,5}$ --
letters only, so every futures contract (=F), class share (BRK-B), non-US
listing (7203.T) and index containing a digit (^N225) was rejected before it
ever reached Yahoo. Nothing in the plugin validates symbols, and the fetcher
interpolates them into the URL verbatim, so the pattern was the only gate:
each of those symbols returns live data from the endpoint this plugin already
calls.

Indexes were in fact already fine -- the caret was allowed -- and the tests
below pin that down so it does not regress while the rest is widened.

Run: <core-venv>/bin/python plugins/ledmatrix-stocks/test_symbol_formats.py
"""

import json
import re
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
SCHEMA = json.loads((PLUGIN_DIR / "config_schema.json").read_text(encoding="utf-8"))

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _pattern(*path):
    node = SCHEMA
    for key in path:
        node = node["properties"][key]
    return re.compile(node["items"]["pattern"])


# Symbols a user would reasonably enter, and what the ticker must do with them.
STOCK_ACCEPT = [
    ("AAPL", "plain ticker"),
    ("GOOGL", "five letters"),
    ("^GSPC", "S&P 500 index"),
    ("^DJI", "Dow index"),
    ("^VIX", "volatility index"),
    ("^N225", "Nikkei -- an index with digits"),
    ("GC=F", "gold futures -- the reported case"),
    ("CL=F", "crude oil futures"),
    ("SI=F", "silver futures"),
    ("BRK-B", "class share"),
    ("7203.T", "Toyota on the Tokyo exchange"),
    ("005930.KS", "Samsung on the Korea exchange"),
]
STOCK_REJECT = [
    ("aapl", "lowercase"),
    ("A B", "embedded space"),
    ("", "empty"),
    ("$AAPL", "leading dollar sign"),
    ("AA//BB", "path separators"),
    ("TOOLONGSYMBOL12345678", "far longer than any real ticker"),
]


def main():
    print("the stocks field accepts what Yahoo actually serves")
    stocks = _pattern("stocks", "symbols")
    for symbol, why in STOCK_ACCEPT:
        check(f"{symbol!r} is accepted ({why})", bool(stocks.match(symbol)))
    for symbol, why in STOCK_REJECT:
        check(f"{symbol!r} is rejected ({why})", not stocks.match(symbol))

    print("\nthe crypto field is not hard-coded to USD")
    crypto = _pattern("crypto", "symbols")
    for symbol in ("BTC-USD", "ETH-USD", "BTC-EUR", "ETH-GBP", "BTC"):
        check(f"{symbol!r} is accepted", bool(crypto.match(symbol)))
    for symbol in ("btc-usd", "BTC-", "-USD"):
        check(f"{symbol!r} is rejected", not crypto.match(symbol))

    print("\nthe defaults the plugin ships still validate")
    for field, pattern in (("stocks", stocks), ("crypto", crypto)):
        defaults = SCHEMA["properties"][field]["properties"]["symbols"]["default"]
        bad = [s for s in defaults if not pattern.match(s)]
        check(f"{field} defaults {defaults} all validate", not bad)

    print("\na quote currency is not appended twice")
    core = None
    for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                      PLUGIN_DIR.parents[2] / "LEDMatrix"):
        if (candidate / "src" / "common" / "__init__.py").exists():
            core = candidate
            break
    if core is None:
        print("  SKIP  no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    else:
        sys.path.insert(0, str(core))
        sys.path.insert(0, str(PLUGIN_DIR))
        import data_fetcher  # noqa: E402
        import inspect
        src = inspect.getsource(data_fetcher.StockDataFetcher.fetch_all_data)
        rule = [ln for ln in src.splitlines() if "api_symbol = symbol" in ln]
        check("the crypto branch derives api_symbol", len(rule) == 1)
        if rule:
            def api_symbol(symbol):
                return symbol if '-' in symbol else f"{symbol}-USD"
            check("'BTC' is quoted in USD", api_symbol("BTC") == "BTC-USD")
            check("'BTC-USD' is left alone", api_symbol("BTC-USD") == "BTC-USD")
            check("'BTC-EUR' keeps its own quote currency, not BTC-EUR-USD",
                  api_symbol("BTC-EUR") == "BTC-EUR")
            check("the shipped rule matches the one asserted here",
                  "'-' in symbol" in rule[0])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
