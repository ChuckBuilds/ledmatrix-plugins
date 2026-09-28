#!/usr/bin/env python3
"""
Headlines must refresh every ``global.update_interval`` seconds, not twice that.

Regression under test: each feed was cached with ``ttl=update_interval * 2``.
The core cache lets a stored ttl beat the reader's ``max_age``, so the
``max_age=update_interval`` on the read never applied: at the default 300 s a
feed was refetched every 600 s.

The cache here is the core's own MemoryCache holding records shaped like
CacheManager.set writes them, so the ttl-over-max_age rule is the core's, not
a copy of it.

Run: <core-venv>/bin/python plugins/news/test_refresh_follows_update_interval.py
"""

import logging
import os
import sys
from pathlib import Path
from unittest import mock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from src.cache.memory_cache import MemoryCache
except ImportError:
    print("SKIP: LEDMatrix core not found (set LEDMATRIX_CORE)")
    sys.exit(2)
from manager import NewsTickerPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class CoreShapedCache:
    """CacheManager.get/set over the core MemoryCache (memory tier only)."""

    def __init__(self):
        self.mem = MemoryCache()

    def set(self, key, data, ttl=None):
        record = {"timestamp": 0}
        if ttl is not None:
            record["ttl"] = ttl
        record["data"] = data
        self.mem.set(key, record)

    def get(self, key, max_age=300):
        record = self.mem.get(key, max_age=max_age)
        return record["data"] if record else None


RSS = b"""<rss><channel>
<item><title>Headline one</title><description>d</description></item>
</channel></rss>"""

INTERVAL = 300
ticker = object.__new__(NewsTickerPlugin)
ticker.logger = logging.getLogger("test-news")
ticker.cache_manager = CoreShapedCache()
ticker.global_config = {"update_interval": INTERVAL}
ticker.headlines_per_feed = 2
ticker.background_config = {"request_timeout": 5}

response = mock.Mock(content=RSS)
response.raise_for_status.return_value = None
clock = [1_700_000_000.0]
fixed_hour = mock.patch("manager.datetime")  # one hour bucket for the whole run

with mock.patch("manager.requests.get", return_value=response) as get, \
        mock.patch("src.cache.memory_cache.time.time", side_effect=lambda: clock[0]), \
        fixed_hour as dt:
    dt.now.return_value.strftime.return_value = "2026092712"
    dt.now.return_value.isoformat.return_value = "2026-09-27T12:00:00"

    first = ticker._fetch_feed_headlines("BBC", "http://feed")
    check("the first read fetches the feed", get.call_count == 1 and len(first) == 1)

    clock[0] += INTERVAL - 10
    ticker._fetch_feed_headlines("BBC", "http://feed")
    check("inside update_interval the cache is used", get.call_count == 1)

    clock[0] += 20  # now update_interval + 10 s after the fetch
    ticker._fetch_feed_headlines("BBC", "http://feed")
    check("just past update_interval the feed is fetched again", get.call_count == 2)

print()
print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
