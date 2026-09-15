#!/usr/bin/env python3
"""
Regression tests for stock-news:

1. The plugin loads when display_manager.matrix is None (hardware init failed);
   it read display_manager.matrix.width and raised AttributeError.
2. Logos are never downloaded on the render path. _render_news_item -- reached
   from display() and get_vegas_content() -- downloaded a missing logo through
   a session that retries with backoff and a 10s timeout, stalling the scroll.
   They are now fetched in update() and only read from disk while drawing.
3. global.scroll_pixels_per_second reaches the core's scroll resolver. The
   resolver never looks inside ``global``, so every value resolved to its 100
   px/s default.
4. min_duration / max_duration reach the scroll helper (they were applied only
   on the pre-resolver path).
5. background_service.max_retries sets the session's retry count (hard-coded 4).

The network is stubbed throughout.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/stock-news/test_render_offline_and_settings.py
"""

import io
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from PIL import Image
    import defusedxml  # noqa: F401
    import src
    from src.common import scroll_config  # noqa: F401  (3.4.0 floor)
except ImportError as exc:
    print(f"SKIP: LEDMatrix core (3.4.0+), Pillow or defusedxml not importable: {exc}")
    sys.exit(2)

# Fonts resolve relative to the core checkout, as on a real install.
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(src.__file__))))

from manager import StockNewsTickerPlugin  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class FakeDisplay:
    refresh_hz = 100.0

    def __init__(self, width=128, height=32, matrix=True):
        self.width = width
        self.height = height
        self.matrix = types.SimpleNamespace(width=width, height=height) if matrix else None
        self.image = Image.new("RGB", (width, height))
        self.calls = []

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def process_deferred_updates(self):
        pass

    def update_display(self):
        pass


class FakeCache:
    def get(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        pass


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeSession:
    """Answers every GET with a small PNG and records the URL."""

    def __init__(self):
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return types.SimpleNamespace(status_code=200, content=png_bytes())

    def close(self):
        pass


def make(global_config=None, display=None):
    config = {"enabled": True, "feeds": {"stock_symbols": []},
              "global": dict(global_config or {})}
    return StockNewsTickerPlugin("stock-news", config, display or FakeDisplay(),
                                 FakeCache(), types.SimpleNamespace())


def test_loads_without_matrix():
    print("[display_manager.matrix is None]")
    try:
        plugin = make(display=FakeDisplay(192, 48, matrix=False))
        check(plugin.display_width == 192 and plugin.display_height == 48,
              "dimensions come from display_manager.width/height")
    except AttributeError as exc:
        check(False, f"plugin failed to load: {exc!r}")


def test_logos_not_downloaded_while_drawing():
    print("[logos on the render path]")
    plugin = make({"display_style": "logo_and_ticker", "logo_fetch_enabled": True})
    session = FakeSession()
    plugin._session = session
    plugin._logo_dir = Path(tempfile.mkdtemp())
    plugin.all_news_items = [{"symbol": "ZZTEST", "title": "Test headline",
                              "publisher": "Wire", "published_ts": 0}]

    plugin._create_scrolling_image()
    plugin._vegas_cache = None
    plugin.get_vegas_content()
    check(session.urls == [], f"building the strip and Vegas content made no requests (got {session.urls})")

    plugin.update()
    check(any("ZZTEST" in url for url in session.urls),
          f"update() downloads the missing logo (requests {session.urls})")
    check((plugin._logo_dir / "ZZTEST.png").exists(), "the logo is cached to disk by update()")

    session.urls.clear()
    plugin._vegas_cache = None
    rendered = plugin._render_news_item(plugin.all_news_items[0])
    check(session.urls == [], "drawing afterwards still makes no requests")
    check(rendered is not None and rendered.width > 32,
          "the story is drawn with the downloaded logo in front of it")


def test_settings_reach_the_helpers():
    print("[scroll_pixels_per_second, durations, max_retries]")
    plugin = make({"scroll_pixels_per_second": 20.0, "min_duration": 45, "max_duration": 200,
                   "dynamic_duration": True,
                   "background_service": {"request_timeout": 30, "max_retries": 2}})
    settings = plugin._scroll_settings
    check(abs(settings.requested_pixels_per_second - 20.0) < 0.01,
          f"the resolver was asked for the configured 20 px/s "
          f"(got {settings.requested_pixels_per_second:.1f} from {settings.source})")
    check(plugin.scroll_helper.min_duration == 45 and plugin.scroll_helper.max_duration == 200,
          f"min/max duration reach the scroll helper "
          f"(got {plugin.scroll_helper.min_duration}/{plugin.scroll_helper.max_duration})")
    retries = plugin._session.get_adapter("https://").max_retries.total
    check(retries == 2, f"background_service.max_retries sets the retry count (got {retries})")

    plugin.on_config_change({"enabled": True, "feeds": {"stock_symbols": []},
                             "global": {"scroll_pixels_per_second": 50.0,
                                        "background_service": {"max_retries": 5}}})
    check(abs(plugin._scroll_settings.requested_pixels_per_second - 50.0) < 0.01,
          "a saved speed change re-resolves")
    retries = plugin._session.get_adapter("https://").max_retries.total
    check(retries == 5, f"a saved max_retries change applies (got {retries})")


def test_static_frames_release_scroll_state():
    print("[no stories]")
    display = FakeDisplay()
    plugin = make(display=display)
    plugin.display()
    check(display.calls[-1:] == [(False, 1)],
          f"the no-news message releases the scroll state (calls {display.calls})")


if __name__ == "__main__":
    for test in (test_loads_without_matrix, test_logos_not_downloaded_while_drawing,
                 test_settings_reach_the_helpers, test_static_frames_release_scroll_state):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
