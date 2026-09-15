#!/usr/bin/env python3
"""
Regression tests for three display-path problems.

1. display() called update() on the first paint, so the YouTube API request
   (timeout 10 s) ran on the render thread. It now draws a placeholder.
2. Channels that hide their subscriber count get no `subscriberCount` from the
   API. Indexing it raised KeyError, so those channels never displayed.
3. With stats missing, display() logged a WARNING on every frame.

Run: python plugins/youtube-stats/test_first_paint_hidden_subs_log_throttle.py
"""

import logging
import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    mod("src")
    mod("src.plugin_system")
    mod("src.plugin_system.base_plugin", BasePlugin=object, VegasDisplayMode=object)


_stub_core_src()

from PIL import Image, ImageFont  # noqa: E402

import manager  # noqa: E402
from manager import YouTubeStatsPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


class FakeDM:
    def __init__(self, w=128, h=32):
        self.matrix = types.SimpleNamespace(width=w, height=h)
        self.image = None
        self.frames = 0

    def clear(self):
        pass

    def update_display(self):
        self.frames += 1


class FakeCache:
    def get(self, key, max_age=None):
        return None

    def set(self, key, value, ttl=None):
        pass


class CountingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.warnings = 0

    def emit(self, record):
        if record.levelno == logging.WARNING:
            self.warnings += 1


def make_plugin(name):
    # object.__new__: the stub makes BasePlugin `object` (see the sibling test).
    p = object.__new__(YouTubeStatsPlugin)
    p.logger = logging.getLogger(name)
    p.logger.propagate = False
    p.enabled = True
    p.plugin_id = "youtube-stats"
    p.channel_id = "UCx"
    p.api_key = "key"
    p.update_interval_config = 300
    p.cache_manager = FakeCache()
    p.display_manager = FakeDM()
    p.channel_stats = None
    p.last_displayed_stats = None
    p._has_fetched = False
    p._last_attempt = 0.0
    p._api_key_error = None
    p.font = ImageFont.load_default()
    p.youtube_logo = Image.new("RGB", (20, 14), (255, 0, 0))
    p.name_font_override = p.subs_font_override = p.views_font_override = None
    p.name_color = p.subs_color = p.views_color = (255, 255, 255)
    return p


# --- 1. first paint does not fetch ----------------------------------------
p = make_plugin("yt-first-paint")
calls = []
p.update = lambda: calls.append(1)
p.display()
check("display() before any update() does not call update()", calls == [])
check("display() before any update() draws a placeholder", p.display_manager.frames == 1)

# --- 2. hidden subscriber count -------------------------------------------
class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"items": [{
            "snippet": {"title": "Hidden Subs"},
            "statistics": {"viewCount": "1234", "hiddenSubscriberCount": True},
        }]}


real_get = manager.requests.get
manager.requests.get = lambda *a, **k: FakeResponse()
try:
    p = make_plugin("yt-hidden")
    stats = p._get_channel_stats()
finally:
    manager.requests.get = real_get
check("a channel with a hidden subscriber count still returns stats", stats is not None)
check("its subscriber count is None and views parse",
      bool(stats) and stats.get("subscribers") is None and stats.get("views") == 1234)
check("the stats screen renders for it",
      bool(stats) and p._create_display(stats) is not None)

# --- 3. warning throttle ---------------------------------------------------
p = make_plugin("yt-throttle")
handler = CountingHandler()
p.logger.addHandler(handler)
p._has_fetched = True  # a fetch was attempted and produced nothing
for _ in range(100):
    p.display()
check("100 frames without stats log at most one WARNING", handler.warnings <= 1)
check("the missing-stats frame still draws something", p.display_manager.frames == 100)

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    for case in failed:
        print(f"  FAILED: {case}")
    sys.exit(1)
