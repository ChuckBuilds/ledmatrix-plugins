#!/usr/bin/env python3
"""
Regression test: the ticker works through a pool of stories instead of
repeating each feed's top two.

headlines_per_feed was both the number of stories fetched and the number
shown, so the strip carried the same six headlines every cycle until a feed
published something new, and "rotation" only changed which of them led. The
plugin now fetches headline_pool_size stories per feed and each cycle, or
page, shows the ones shown least recently.

Run: <core-venv>/bin/python plugins/news/test_headlines_rotate_through_pool.py
"""

import logging
import os
import sys
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
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


def story(feed, n, age_hours=1.0):
    published = format_datetime(datetime.now(timezone.utc) - timedelta(hours=age_hours))
    return {"feed_name": feed, "title": f"{feed} story {n}", "published": published}


FEEDS = list(NewsTickerPlugin.DEFAULT_FEEDS)[:2]


def ticker(pools_by_feed, paging=False, per_feed=2):
    t = object.__new__(NewsTickerPlugin)
    t.logger = logging.getLogger("test-news-pool")
    t.initialized = True
    t.feeds_config = {"enabled_feeds": list(pools_by_feed), "custom_feeds": []}
    t.headlines_per_feed = per_feed
    t.headline_pool_size = 10
    t.max_headline_age_hours = 48
    t.current_headlines = []
    t._headlines_signature = None
    t._page_start = 0
    t._page_count = 0
    t.rotation_count = 0
    t.rotation_threshold = 1
    t.rotation_enabled = True
    t.paging_enabled = paging
    t._headline_image_cache = {}
    t._fetch_feed_headlines = lambda name, url: list(pools_by_feed.get(name, []))
    t.update()
    return t


def titles(t):
    return [h["title"] for h in t.current_headlines]


def pass_done(t):
    # The completion handler logs scroll info; only the rotation branch matters here.
    t.scroll_helper = type("S", (), {
        "get_scroll_info": lambda self: {"elapsed_time": 0, "dynamic_duration": 0},
        "clear_cache": lambda self: None,
    })()
    t._on_scroll_cycle_complete()


# -- a cycle moves on to the next two stories of each feed
pools = {f: [story(f, n) for n in range(6)] for f in FEEDS}
t = ticker(pools)
first = titles(t)
check("the first cycle shows each feed's two newest", first == [
    f"{FEEDS[0]} story 0", f"{FEEDS[0]} story 1", f"{FEEDS[1]} story 0", f"{FEEDS[1]} story 1"], first)
pass_done(t)
second = titles(t)
check("the next cycle shows the next two of each", second == [
    f"{FEEDS[0]} story 2", f"{FEEDS[0]} story 3", f"{FEEDS[1]} story 2", f"{FEEDS[1]} story 3"], second)
pass_done(t)
pass_done(t)
check("after the pool is used up it starts over", titles(t) == first, titles(t))

# -- a refresh between cycles does not undo the rotation
t = ticker(pools)
pass_done(t)
moved = titles(t)
t.update()
check("update() keeps the stories the rotation moved to", titles(t) == moved, titles(t))

# -- a story two feeds carry is shown once
shared = {"feed_name": FEEDS[0], "title": "Big trade", "published": story(FEEDS[0], 0)["published"]}
pools = {FEEDS[0]: [shared, story(FEEDS[0], 1)],
         FEEDS[1]: [dict(shared, feed_name=FEEDS[1]), story(FEEDS[1], 1)]}
t = ticker(pools, per_feed=1)
check("a duplicate across feeds is shown once", titles(t).count("Big trade") == 1, titles(t))
check("the second feed shows its next story instead", f"{FEEDS[1]} story 1" in titles(t), titles(t))

# -- stale stories only fill the gaps
pools = {FEEDS[0]: [story(FEEDS[0], 0, age_hours=300), story(FEEDS[0], 1, age_hours=3)]}
t = ticker(pools, per_feed=1)
check("a fresh story beats a stale one", titles(t) == [f"{FEEDS[0]} story 1"], titles(t))
t = ticker(pools, per_feed=2)
check("a stale story still fills a feed with too few fresh ones", len(titles(t)) == 2, titles(t))

# -- a feed with nothing unseen still changes its lead story
pools = {FEEDS[0]: [story(FEEDS[0], 0), story(FEEDS[0], 1)]}
t = ticker(pools, per_feed=2)
before = titles(t)
pass_done(t)
check("nothing unseen: the order rotates", titles(t) == before[1:] + before[:1], titles(t))

# -- paging walks the selection, then picks the next unseen stories
pools = {f: [story(f, n) for n in range(6)] for f in FEEDS}
t = ticker(pools, paging=True)
t._page_start, t._page_count = 0, 2
t._advance_page()
check("a page advances through the chosen headlines", t._page_start == 2 and len(titles(t)) == 4)
t._page_count = 2
t._advance_page()
check("coming back round picks the next unseen stories", titles(t) == [
    f"{FEEDS[0]} story 2", f"{FEEDS[0]} story 3", f"{FEEDS[1]} story 2", f"{FEEDS[1]} story 3"], titles(t))
check("and starts that lap from the first of them", t._page_start == 0)

# -- the fetch reads the pool, not just what is shown
check("the pool is wider than what is shown", t._pool_size() == 10)
t.headline_pool_size = 1
check("never fewer than are shown", t._pool_size() == 2)

print()
print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
