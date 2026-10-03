#!/usr/bin/env python3
"""
Regression test: the ticker works through a pool of stories instead of
repeating the top one.

Each symbol fetched max_headlines_per_symbol stories (1 by default) and the
strip showed all of them on every pass; "rotation" only reordered them. With
eight symbols that was the same eight headlines until Yahoo published
something new, and a story carried by two tickers showed twice. The plugin now
fetches headline_pool_size stories per symbol and each pass shows the ones
shown least recently.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/stock-news/test_headlines_rotate_through_pool.py
Exit 0 pass, 1 fail, 2 skip.
"""

import logging
import os
import sys
import time

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


def story(symbol, n, age_hours=1.0):
    return {"symbol": symbol, "title": f"{symbol} story {n}",
            "published_ts": time.time() - age_hours * 3600}


def plugin(pools, per_symbol=1):
    p = object.__new__(StockNewsTickerPlugin)
    p.logger = logging.getLogger("test-stock-news-pool")
    p.feeds_config = {"stock_symbols": list(pools)}
    p.sync_with_stocks_plugin = False
    p.max_headlines_per_symbol = per_symbol
    p.headlines_per_rotation = 2
    p.shuffle_headlines = False
    p.headline_pool_size = 10
    p.max_headline_age_hours = 48
    p._get_custom_feeds = lambda: {}
    p._symbol_data = {sym: list(items) for sym, items in pools.items()}
    p.all_news_items = []
    p._vegas_cache = None
    p._items_rotated = 0
    p._strip_items = []
    return p


def titles(p):
    return [i["title"] for i in p.all_news_items]


# -- a pass moves on to the next story, and comes back round only after all of them
pools = {"AAPL": [story("AAPL", n) for n in range(3)],
         "MSFT": [story("MSFT", n) for n in range(3)]}
p = plugin(pools)
p.all_news_items = p._select_items()[0]
seen = [titles(p)]
for _ in range(5):
    p._strip_items = list(p.all_news_items)
    p._rotate_headlines()
    seen.append(titles(p))
check("the first pass shows each symbol's newest story", seen[0] == ["AAPL story 0", "MSFT story 0"], seen[0])
check("the next passes walk down each symbol's pool",
      seen[1] == ["AAPL story 1", "MSFT story 1"] and seen[2] == ["AAPL story 2", "MSFT story 2"], seen[:3])
check("after the pool is used up it starts over with the longest-unseen",
      seen[3] == ["AAPL story 0", "MSFT story 0"], seen[3])
check("no story repeats within one lap of the pool",
      len({t for s in seen[:3] for t in s}) == 6)

# -- a story carried by two tickers is one story
shared = story("NVDA", 0)
shared["title"] = "Chipmakers rally"
pools = {"NVDA": [shared, story("NVDA", 1)],
         "SMCI": [dict(shared, symbol="SMCI"), story("SMCI", 1)]}
p = plugin(pools)
items, _, _ = p._select_items()
check("a story two symbols carry is shown once",
      [i["title"] for i in items].count("Chipmakers rally") == 1, [i["title"] for i in items])
check("the other symbol takes its next story instead",
      "SMCI story 1" in [i["title"] for i in items], [i["title"] for i in items])

# -- newer stories beat a stale one that has never been shown
pools = {"VOO": [story("VOO", 0, age_hours=200), story("VOO", 1, age_hours=2)]}
p = plugin(pools)
check("a fresh story is picked over a never-shown stale one",
      [i["title"] for i in p._select_items()[0]] == ["VOO story 1"])
p.max_headline_age_hours = 0
check("with the age check off the feed's own order wins",
      [i["title"] for i in p._select_items()[0]] == ["VOO story 0"])
p.max_headline_age_hours = 48
p.max_headlines_per_symbol = 2
check("a stale story still fills a symbol that has too few fresh ones",
      sorted(i["title"] for i in p._select_items()[0]) == ["VOO story 0", "VOO story 1"])

# -- a pool with nothing new falls back to shifting the order
pools = {"AAPL": [story("AAPL", 0)], "MSFT": [story("MSFT", 0)]}
p = plugin(pools)
p.all_news_items = p._select_items()[0]
p._strip_items = list(p.all_news_items)
p._rotate_headlines()
check("with nothing unseen the lead headline still changes", titles(p) == ["MSFT story 0", "AAPL story 0"], titles(p))

# -- shown marks do not outlive the stories
pools = {"AAPL": [story("AAPL", 0), story("AAPL", 1)]}
p = plugin(pools)
p.all_news_items = p._select_items()[0]
p._strip_items = list(p.all_news_items)
p._rotate_headlines()
p._symbol_data["AAPL"] = [story("AAPL", 5)]
p._select_items()
check("a story that left the pool is forgotten", set(p._shown_headlines) <= {"aapl story 5"}, p._shown_headlines)

# -- the pool is fetched deeper than what is shown
p = plugin({"AAPL": []})
check("the fetch asks for the whole pool", p._pool_size(1) == 10)
p.headline_pool_size = 2
check("never fewer than are shown", p._pool_size(5) == 5)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
