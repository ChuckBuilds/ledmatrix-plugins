#!/usr/bin/env python3
"""
Regression test: a failing YouTube API must not be retried once per frame.

display() used to call update() whenever channel_stats was empty:

    if not self.channel_stats:
        self.update()

update() assigns the fetch result unconditionally, so any failure -- missing
key, HTTP error, quota exhaustion, network down -- left channel_stats empty and
the next frame tried again. That is one requests.get(timeout=10) per rendered
frame, on the render thread, against an API whose default quota is 10k
units/day. Quota exhaustion is itself an error, so the loop fed itself.

display() now gates on whether a fetch was ATTEMPTED, and update() is throttled
to update_interval, so a broken API costs one request per interval.

Run: <core-venv>/bin/python plugins/youtube-stats/test_no_per_frame_api_storm.py
"""

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

import logging  # noqa: E402
import time  # noqa: E402

from manager import YouTubeStatsPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


def make_plugin(update_interval=300):
    p = YouTubeStatsPlugin.__new__(YouTubeStatsPlugin)
    p.logger = logging.getLogger("test-youtube-storm")
    p.enabled = True
    p.channel_stats = None
    p.update_interval_config = update_interval
    p._has_fetched = False
    p._last_attempt = 0.0
    p._api_key_error = None
    return p


# --- a permanently failing API -------------------------------------------
plugin = make_plugin()
calls = []
plugin._get_channel_stats = lambda: calls.append(1) or None

# The core's own tick, then a burst of frames.
plugin.update()
for _ in range(200):
    if not plugin._has_fetched:
        plugin.update()

check("a failing fetch is attempted once per interval, not once per frame",
      len(calls) == 1)
check("the failure is recorded as attempted", plugin._has_fetched is True)
check("channel_stats stays empty (no fabricated data)", not plugin.channel_stats)

# --- the throttle expires -------------------------------------------------
plugin._last_attempt = time.monotonic() - 301
plugin.update()
check("a retry happens once the interval has elapsed", len(calls) == 2)

# --- the throttle does not block a successful first fetch ----------------
ok = make_plugin()
ok_calls = []
ok._get_channel_stats = lambda: ok_calls.append(1) or {"subscribers": 5}
ok.update()
check("a working API still populates stats", ok.channel_stats == {"subscribers": 5})
check("and cost exactly one call", len(ok_calls) == 1)

# --- the guard display() uses ---------------------------------------------
import inspect  # noqa: E402
disp = inspect.getsource(YouTubeStatsPlugin.display)
check("display() no longer gates on the result",
      "if not self.channel_stats:\n            self.update()" not in disp)
check("display() gates on whether a fetch was attempted",
      "self._has_fetched" in disp)

upd = inspect.getsource(YouTubeStatsPlugin.update)
check("update() uses monotonic (these Pis have no RTC)", "time.monotonic()" in upd)

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    for case in failed:
        print(f"  FAILED: {case}")
    sys.exit(1)
