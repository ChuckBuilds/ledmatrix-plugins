#!/usr/bin/env python3
"""
Regression tests for the news ticker's font and scroll settings.

1. global.font_size applies. customization.headline_text.font_size (schema
   default 16) and source_text.font_size (8) were compared against 12 and 6 to
   decide whether they were customised, so merged schema defaults always
   counted as a customisation and a 16px override replaced global.font_size.
   on_config_change also defaulted font_size to 12 while __init__ used 16.
2. Default configs render as before: headline 16px, source label 8px.
3. The paging budget uses the speed the shared resolver applied (snapped to
   whole pixels), not the raw scroll_speed / scroll_delay.
4. The dynamic-duration settings reach the scroll helper; they were applied
   only on the pre-resolver path.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/news/test_font_size_and_scroll_settings.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from PIL import Image
    import src
    from src.common import scroll_config  # noqa: F401  (3.4.0 floor)
except ImportError as exc:
    print(f"SKIP: LEDMatrix core (3.4.0+) or Pillow not importable: {exc}")
    sys.exit(2)

CORE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(src.__file__)))
if not os.path.exists(os.path.join(CORE_ROOT, "assets", "fonts", "PressStart2P-Regular.ttf")):
    print("SKIP: core fonts not found")
    sys.exit(2)
os.chdir(CORE_ROOT)

from manager import NewsTickerPlugin  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class _ChecksFailed(AssertionError):
    """Raised after a test whose check() calls recorded failures."""


def _fail_loudly(test):
    """Make a check() failure fail the test under pytest too.

    check() records failures for script mode's exit code; without this, pytest
    collected each test_* as passing whatever it recorded.
    """
    import functools

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        before = len(failures)
        test(*args, **kwargs)
        if len(failures) > before:
            raise _ChecksFailed("; ".join(failures[before:]))
    return wrapper


class FakeDisplay:
    refresh_hz = 100.0

    def __init__(self, width=128, height=32):
        self.width = width
        self.height = height
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


def plugin_manager():
    payload = {"display": {}}
    config_manager = types.SimpleNamespace(load_config=lambda: payload, get_config=lambda: payload)
    return types.SimpleNamespace(font_manager=None, config_manager=config_manager)


#: customization exactly as the schema defaults it (what a saved config carries).
SCHEMA_CUSTOMIZATION = {
    "headline_text": {"font": "PressStart2P-Regular.ttf", "font_size": 16},
    "source_text": {"font": "PressStart2P-Regular.ttf", "font_size": 8,
                    "text_color": [150, 150, 150]},
}


def make(global_config, customization=None):
    config = {"enabled": True, "feeds": {"enabled_feeds": []},
              "global": global_config,
              "customization": customization if customization is not None else SCHEMA_CUSTOMIZATION}
    return NewsTickerPlugin("news", config, FakeDisplay(), FakeCache(), plugin_manager())


@_fail_loudly
def test_font_size():
    print("[global.font_size]")
    plugin = make({"font_size": 8})
    size = plugin.fonts["headline"].size
    check(size == 8, f"global.font_size 8 draws headlines at 8px with default customization (got {size})")

    plugin = make({"font_size": 16})
    check(plugin.fonts["headline"].size == 16 and plugin.fonts["info"].size == 8,
          f"schema defaults still draw headline 16px / source 8px "
          f"(got {plugin.fonts['headline'].size}/{plugin.fonts['info'].size})")

    plugin = make({"font_size": 16}, {"headline_text": {"font": "PressStart2P-Regular.ttf", "font_size": 24},
                                      "source_text": SCHEMA_CUSTOMIZATION["source_text"]})
    check(plugin.fonts["headline"].size == 24,
          f"a real customization.headline_text.font_size still overrides (got {plugin.fonts['headline'].size})")

    plugin = make({"font_size": 16})
    plugin.on_config_change({"enabled": True, "feeds": {"enabled_feeds": []}, "global": {},
                             "customization": SCHEMA_CUSTOMIZATION})
    check(plugin.font_size == 16,
          f"a live save without font_size keeps the 16 default, as at load (got {plugin.font_size})")

    # Web-UI saves before 1.6.0 wrote the old schema default, 12, beside the
    # PressStart2P @ 16 customization; those installs drew 16px and must still.
    plugin = make({"font_size": 12})
    check(plugin.font_size == 16 and plugin.fonts["headline"].size == 16,
          f"a saved config holding the old default 12 keeps drawing 16px "
          f"(got font_size {plugin.font_size}, headline {plugin.fonts['headline'].size})")
    plugin = make({"font_size": 16})
    plugin.on_config_change({"enabled": True, "feeds": {"enabled_feeds": []},
                             "global": {"font_size": 12}, "customization": SCHEMA_CUSTOMIZATION})
    check(plugin.fonts["headline"].size == 16,
          f"a live save holding 12 keeps 16px too (got {plugin.fonts['headline'].size})")


@_fail_loudly
def test_scroll_settings():
    print("[scroll speed and dynamic duration]")
    plugin = make({"display": {"scroll_speed": 1.0, "scroll_delay": 0.016},
                   "dynamic_duration": {"enabled": True, "min_duration_seconds": 45,
                                        "max_duration_seconds": 200, "buffer_ratio": 0.2}})
    applied = plugin._scroll_settings.pixels_per_second
    check(abs(applied - 62.5) > 0.5, f"precondition: the resolver snapped 62.5 px/s (applied {applied:.1f})")
    got = plugin._effective_pixels_per_second()
    check(abs(got - applied) < 0.01,
          f"the paging budget uses the applied {applied:.1f} px/s (got {got:.1f})")
    helper = plugin.scroll_helper
    check((helper.min_duration, helper.max_duration, helper.duration_buffer) == (45, 200, 0.2),
          f"dynamic-duration settings reach the scroll helper "
          f"(got {helper.min_duration}/{helper.max_duration}/{helper.duration_buffer})")


@_fail_loudly
def test_static_frames_release_scroll_state():
    print("[no headlines]")
    plugin = make({"font_size": 16})
    display = plugin.display_manager
    display.calls.clear()
    plugin.display()
    check(display.calls[-1:] == [(False, 1)],
          f"the no-headlines message releases the scroll state (calls {display.calls})")


if __name__ == "__main__":
    for test in (test_font_size, test_scroll_settings, test_static_frames_release_scroll_state):
        try:
            test()
        except _ChecksFailed:
            pass  # its checks are already recorded in failures
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
