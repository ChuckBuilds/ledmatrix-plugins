#!/usr/bin/env python3
"""
Regression test: a feed that fails keeps its headlines on the ticker.

update() rebuilt the headline list from scratch on every refresh and added a
feed only when its fetch returned something. A feed that timed out dropped
out of the ticker until it recovered, and with every feed down (the Pi's
network blipped) the panel switched to "No Headlines Available" instead of
showing what it had. Each feed's last good headlines now stand in for it.

Run: <core-venv>/bin/python plugins/news/test_failed_feed_keeps_headlines.py
"""

import logging
import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import NewsTickerPlugin  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  <- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def headline(feed, title):
    return {"feed_name": feed, "title": title, "link": "http://x"}


feeds = list(NewsTickerPlugin.DEFAULT_FEEDS)[:2]
ticker = object.__new__(NewsTickerPlugin)
ticker.logger = logging.getLogger("test-news")
ticker.initialized = True
ticker.feeds_config = {"enabled_feeds": feeds, "custom_feeds": []}
ticker.headlines_per_feed = 2
ticker.current_headlines = []
ticker._headlines_signature = None
ticker._page_start = 0
ticker.rotation_count = 0
ticker._headline_image_cache = {}

answers = {}
ticker._fetch_feed_headlines = lambda name, url: answers.get(name, [])

answers = {feeds[0]: [headline(feeds[0], "A1")], feeds[1]: [headline(feeds[1], "B1")]}
ticker.update()
check("both feeds' headlines are shown", [h["title"] for h in ticker.current_headlines] == ["A1", "B1"])

answers = {feeds[1]: [headline(feeds[1], "B2")]}
ticker.update()
check("a feed that fails keeps its last headlines, in its place",
      [h["title"] for h in ticker.current_headlines] == ["A1", "B2"],
      [h["title"] for h in ticker.current_headlines])

answers = {}
ticker.update()
check("with every feed down the ticker keeps what it had",
      [h["title"] for h in ticker.current_headlines] == ["A1", "B2"],
      [h["title"] for h in ticker.current_headlines])

fresh = object.__new__(NewsTickerPlugin)
fresh.__dict__.update({k: v for k, v in ticker.__dict__.items() if k != "_last_good_headlines"})
fresh.current_headlines = []
fresh._fetch_feed_headlines = lambda name, url: []
fresh.update()
check("a feed that has never answered contributes nothing", fresh.current_headlines == [])

print()
print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
