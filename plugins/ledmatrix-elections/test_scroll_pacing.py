#!/usr/bin/env python3
"""
Regression test: the elections ticker paces its scroll only through the core's
shared resolver, and holds / releases the scroll state like the other tickers.

Before this fix:
- scroll_delay defaulted to 0.01 in code while the schema and README say 0.03,
  so a config without the key scrolled three times faster than documented.
- __init__ and on_config_change called set_target_fps(100) after the resolver
  had applied its pacing, overwriting the frames-per-second it chose.
- _one_pass_duration() used raw scroll_speed / scroll_delay, not the speed the
  resolver snapped to, so the rotation hand-off drifted from the real scroll.
- the ticker never called set_scrolling_state(False): not when it had nothing
  to show, and not while a static "race called" card was up.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-elections/test_scroll_pacing.py
"""

import os
import sys

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

# Bundled fonts resolve relative to the core checkout, as on a real install.
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(src.__file__))))

from manager import ElectionPlugin  # noqa: E402

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

    def update_display(self):
        pass


class FakeCache:
    def get(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        pass

    save_cache = set
    delete = set

    def get_cached_data(self, *args, **kwargs):
        return None

    get_cached_data_with_strategy = get_cached_data


def make(config, display=None):
    base = {"enabled": True, "state": "CA"}
    base.update(config)
    return ElectionPlugin("ledmatrix-elections", base, display or FakeDisplay(),
                          FakeCache(), object())


@_fail_loudly
def test_default_delay_matches_schema():
    print("[scroll_delay default]")
    plugin = make({"scroll_speed": 1.0})
    check(plugin.scroll_delay == 0.03,
          f"code default scroll_delay is the schema's 0.03 (got {plugin.scroll_delay})")
    requested = plugin._scroll_settings.requested_pixels_per_second
    check(abs(requested - 1.0 / 0.03) < 0.01,
          f"resolver was asked for 33.3 px/s (got {requested:.2f})")


@_fail_loudly
def test_resolver_pacing_not_overwritten():
    print("[no FPS write after the resolver]")
    plugin = make({"scroll_speed": 1.0, "scroll_delay": 0.03})
    crisp = plugin._scroll_settings.crisp
    check(abs(plugin.scroll_helper.target_fps - crisp.frames_per_second) < 0.01,
          f"helper FPS is the resolver's {crisp.frames_per_second:.1f} "
          f"(got {plugin.scroll_helper.target_fps:.1f})")

    plugin.on_config_change({"enabled": True, "state": "CA",
                             "scroll_speed": 2.0, "scroll_delay": 0.03})
    settings = plugin._scroll_settings
    check(abs(settings.requested_pixels_per_second - 2.0 / 0.03) < 0.01,
          "on_config_change re-resolved the new speed")
    check(abs(plugin.scroll_helper.target_fps - settings.crisp.frames_per_second) < 0.01,
          f"after a live edit the helper FPS is still the resolver's "
          f"{settings.crisp.frames_per_second:.1f} (got {plugin.scroll_helper.target_fps:.1f})")
    check(plugin.scroll_helper.fixed_pixels_per_frame == settings.crisp.pixels_per_frame,
          "after a live edit the resolver's whole-pixel step is still applied")


@_fail_loudly
def test_duration_uses_resolved_speed():
    print("[one-pass duration]")
    plugin = make({"scroll_speed": 1.0, "scroll_delay": 0.016})  # asks for 62.5 px/s
    applied = plugin._scroll_settings.pixels_per_second
    check(abs(applied - 62.5) > 0.5,
          f"precondition: snapping moved 62.5 px/s (applied {applied:.1f})")
    plugin.scroll_helper.total_scroll_width = 2000
    plugin._scroll_ready = True
    expected = max(6.0, 2000 / applied)
    got = plugin._one_pass_duration()
    check(abs(got - expected) < 0.01,
          f"duration uses the applied {applied:.1f} px/s: {expected:.2f}s (got {got:.2f}s)")


@_fail_loudly
def test_scroll_state_is_released():
    print("[scroll state held and released]")
    display = FakeDisplay()
    plugin = make({"test_mode": True}, display)

    shown = plugin.display()
    check(shown is False, "nothing to show before the first update")
    check(bool(display.calls) and display.calls[-1] == (False, 1),
          f"released the scroll state when there is nothing to show (calls {display.calls})")

    plugin.update()
    check(plugin._scroll_ready, "precondition: test_mode fixtures built a ticker")
    display.calls.clear()
    plugin.display(display_mode="election_ticker")
    check(display.calls[-1:] == [(True, plugin._scroll_settings.frame_hold)],
          f"scrolling passes the resolved frame hold (calls {display.calls})")

    check(bool(plugin.races), "precondition: the fixture has races to show")
    display.calls.clear()
    # The card renders any race; the fixture's visible races are all uncalled.
    plugin._display_called_card(plugin.races[0], False)
    check(display.calls[-1:] == [(False, 1)],
          f"a static called card releases the scroll state (calls {display.calls})")

    def _broken():
        raise RuntimeError("draw failed")

    plugin.scroll_helper.get_visible_portion = _broken
    display.calls.clear()
    shown = plugin.display(display_mode="election_ticker")
    check(shown is False and display.calls[-1:] == [(False, 1)],
          f"a frame that raises while drawing releases the scroll state (calls {display.calls})")


if __name__ == "__main__":
    for test in (test_default_delay_matches_schema, test_resolver_pacing_not_overwritten,
                 test_duration_uses_resolved_speed, test_scroll_state_is_released):
        try:
            test()
        except _ChecksFailed:
            pass  # its checks are already recorded in failures
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
