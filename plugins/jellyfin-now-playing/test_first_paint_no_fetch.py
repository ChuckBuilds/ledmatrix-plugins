#!/usr/bin/env python3
"""
Regression test: the first display() does not fetch.

display() called update() when nothing had been fetched yet, putting the
/Sessions request and the poster download on the render thread. It now draws a
placeholder, or the setup message when the URL or API key is missing (which is
known without a request), and leaves the fetch to update().

Run: python plugins/jellyfin-now-playing/test_first_paint_no_fetch.py
"""

import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if 'src' not in sys.modules:
    src = types.ModuleType('src')
    plugin_system = types.ModuleType('src.plugin_system')
    base_plugin = types.ModuleType('src.plugin_system.base_plugin')

    class _BasePlugin:
        def __init__(self, *args, **kwargs):
            pass

    base_plugin.BasePlugin = _BasePlugin
    plugin_system.base_plugin = base_plugin
    src.plugin_system = plugin_system
    sys.modules['src'] = src
    sys.modules['src.plugin_system'] = plugin_system
    sys.modules['src.plugin_system.base_plugin'] = base_plugin

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from manager import JellyfinNowPlayingPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


class FakeDM:
    def __init__(self, w=128, h=32):
        self.width, self.height = w, h
        self.matrix = types.SimpleNamespace(width=w, height=h)
        self.image = None
        self.frames = 0

    def clear(self):
        pass

    def update_display(self):
        self.frames += 1


def make_plugin(url, key):
    class _Shell(JellyfinNowPlayingPlugin):
        def __init__(self):
            pass

    p = _Shell()
    p.logger = logging.getLogger("jellyfin-first-paint")
    p.enabled = True
    p.jellyfin_url = url
    p.api_key = key
    p.display_manager = FakeDM()
    p.now_playing = None
    p._error = None
    p._has_fetched = False
    p._poster_image = None
    p._poster_key = None
    p._scroll_pos = {'title': 0, 'subtitle': 0}
    p._scroll_tick = {'title': 0, 'subtitle': 0}
    p._last_static_signature = None
    p.subtitle_font = ImageFont.load_default()
    p._measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    p.calls = []
    p._fetch_sessions = lambda: p.calls.append('sessions') or []
    return p


configured = make_plugin("http://jellyfin.local:8096", "abc")
configured.display()
check("configured: display() before any update() makes no request", configured.calls == [])
check("configured: a placeholder frame is drawn", configured.display_manager.frames == 1)
configured.update()
check("configured: update() does the fetch", configured.calls == ['sessions'])

unconfigured = make_plugin("", "")
unconfigured.display()
check("unconfigured: no request", unconfigured.calls == [])
check("unconfigured: the setup message shows on the first frame",
      unconfigured._error == "Jellyfin: Set URL/API Key"
      and unconfigured.display_manager.frames == 1)

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
