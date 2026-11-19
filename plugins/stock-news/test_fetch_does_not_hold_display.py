#!/usr/bin/env python3
"""update() must not do network I/O: the core holds the plugin lock around it.

Regression: update() fetched Yahoo/RSS headlines and logos inline. The core runs
update() holding this plugin's lock and display() skips every frame while that
lock is held, so each fetch froze the scrolling strip for the length of one
HTTPS round trip -- 300-750 ms on a Pi 4, every time a symbol came due
("Display of stock-news held 723 ms by its update()" in the journal), and for
the whole retry/timeout chain during an outage. Now update() only schedules;
a worker thread does the network and queues results, which update(), display()
and get_vegas_content() apply under the lock.

    python plugins/stock-news/test_fetch_does_not_hold_display.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Shares that test's fakes, and its core lookup and SKIP (exit 2) when the
# core, Pillow or defusedxml is not importable.
from test_render_offline_and_settings import FakeCache, FakeDisplay  # noqa: E402
from manager import StockNewsTickerPlugin  # noqa: E402

failures: list[str] = []
SLOW = 0.6   # one Yahoo round trip as measured on the Pi


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


class SlowYahoo:
    """A session whose every GET takes SLOW seconds, like Yahoo from a Pi."""

    def __init__(self):
        self.urls: list[str] = []
        self.release = threading.Event()

    def get(self, url, params=None, **kwargs):
        self.urls.append(url)
        self.release.wait(SLOW)
        symbol = (params or {}).get("q", "ZZ")
        body = {"quotes": [], "news": [
            {"title": f"{symbol} headline", "publisher": "Wire",
             "providerPublishTime": time.time(), "link": "https://example.invalid/x"}]}
        return types.SimpleNamespace(status_code=200, content=b"",
                                     raise_for_status=lambda: None, json=lambda: body)

    def close(self):
        pass


def make():
    config = {"enabled": True,
              "feeds": {"stock_symbols": ["AAA"]},
              "global": {"display_style": "ticker_only", "logo_fetch_enabled": False,
                         "eager_fetch_on_startup": True}}
    plugin = StockNewsTickerPlugin("stock-news", config, FakeDisplay(), FakeCache(),
                                   types.SimpleNamespace(get_plugin=lambda _id: None))
    plugin._session = SlowYahoo()
    return plugin


def test_update_returns_before_the_network():
    print("[update() with a slow network]")
    plugin = make()
    t0 = time.monotonic()
    plugin.update()
    took = time.monotonic() - t0
    check(took < SLOW / 3, f"update() returns without waiting for the fetch ({took * 1000:.0f} ms)")
    check(plugin._fetch_thread is not None and plugin._fetch_thread.is_alive(),
          "the fetch is running on the worker thread")

    t0 = time.monotonic()
    plugin.display()
    took = time.monotonic() - t0
    check(took < SLOW / 3, f"display() draws while the fetch runs ({took * 1000:.0f} ms)")

    plugin.update()   # worker still busy: must not schedule a second batch
    check(len(plugin._session.urls) == 1, f"one batch at a time ({len(plugin._session.urls)} requests)")

    plugin._wait_for_fetches()
    check(not plugin.all_news_items, "nothing changes until the result is applied under the lock")
    plugin.display()
    titles = [i.get("title") for i in plugin.all_news_items]
    check(titles == ["AAA headline"], f"display() applies the finished fetch ({titles})")
    check(plugin._symbol_data.get("AAA"), "the headlines are stored for the symbol")


def test_failed_fetch_keeps_headlines():
    print("[a failed fetch on the worker]")
    plugin = make()
    plugin.update()
    plugin._wait_for_fetches()
    plugin.update()
    before = list(plugin._symbol_data["AAA"])

    def boom(*a, **k):
        raise __import__("requests").ConnectionError("network down")
    plugin._session.get = boom
    plugin._last_symbol_fetch = 0           # make the symbol due again
    plugin.update()
    plugin._wait_for_fetches()
    plugin.update()
    check(plugin._symbol_data["AAA"] == before, "an outage on the worker keeps the last headlines")
    check(plugin._fetch_thread is None or not plugin._fetch_thread.is_alive(),
          "the worker ends after a failed fetch")


if __name__ == "__main__":
    for test in (test_update_returns_before_the_network, test_failed_fetch_keeps_headlines):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
