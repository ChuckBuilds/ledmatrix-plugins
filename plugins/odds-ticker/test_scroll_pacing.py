#!/usr/bin/env python3
"""The ticker's frames are paced by the panel, for the whole time it is on screen.

Observed on hdpi (Pi 4, 256x64 at limit_refresh_rate_hz=100, core 3.4.0,
odds-ticker 1.7.0, display_options.loop false). The frame-stats line read
``113.3 fps | median 8.10ms`` while news and ledmatrix-stocks read
``100.0 fps | median 10.00ms`` on the same panel. Every odds-ticker slot in the
journal showed the same thing: 100 fps until "Odds ticker reached end - scroll
complete", then 8 ms frames (up to 123.7 fps) for the ~11s the controller keeps
the slot open to its minimum duration.

Cause. With loop off, display() called set_scrolling_state(False) once the
scroll finished, while it kept drawing the parked end frame on every tick of
the controller's high-FPS loop. Not scrolling, core's update_display() takes its
dirty-tracking skip: the frame is identical, so SwapOnVSync -- which is what
waits for the panel refresh -- is never called. Nothing waited for the panel,
so the loop ran at its own 8 ms deadline (display_interval = 0.008) and
log_frame_rate() counted every one of those unpresented frames. The frame hold
was dropped with the state. news and stocks keep set_scrolling_state(True,
frame_hold=...) on every frame their strip is on screen, parked or not, and so
stay on the refresh.

This drives the real display() through a copy of the controller's loop, against
core's real update_display() / set_scrolling_state() on a fake matrix whose
SwapOnVSync waits for a 100 Hz refresh on a virtual clock. It needs no timing
luck: the clock only moves when the loop, the work or the vsync moves it.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/odds-ticker/test_scroll_pacing.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import ast
import copy
import functools
import logging
import os
import statistics
import sys
import threading
import time
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
core_dir = None
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        core_dir = candidate
        break
if core_dir is None:
    print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
    sys.exit(2)
os.chdir(core_dir)  # fonts resolve as assets/fonts/..., as on a Pi
# display_manager imports rgbmatrix at module level; the emulator package
# stands in for it. Only update_display()'s pacing logic is used below, never
# the emulator itself: the matrix is the fake one defined in this file.
os.environ.setdefault("EMULATOR", "true")

from PIL import Image  # noqa: E402

try:
    from src.display_manager import DisplayManager  # noqa: E402
except ImportError as exc:  # no rgbmatrix and no emulator installed
    print("SKIP: cannot import core DisplayManager (%s)" % exc)
    sys.exit(2)
from src.common import scroll_config  # noqa: E402

import manager  # noqa: E402
from manager import OddsTickerPlugin  # noqa: E402

manager.get_background_service = lambda *a, **k: None  # no worker pool in a test

REFRESH_HZ = 100.0
WIDTH, HEIGHT = 256, 64          # hdpi's panel
CONTROLLER_INTERVAL = 0.008      # display_controller's high-FPS display_interval
RENDER_COST = 0.004              # per-frame work, as measured on a 2x128x64 chain

failures = []


class _ChecksFailed(AssertionError):
    """Raised after a test whose check() calls recorded failures."""


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ((": " + detail) if (detail and not ok) else ""))
    if not ok:
        failures.append(label)


def _fail_loudly(test):
    """Make a check() failure fail the test under pytest too."""
    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        before = len(failures)
        test(*args, **kwargs)
        if len(failures) > before:
            raise _ChecksFailed("; ".join(failures[before:]))
    return wrapper


# -- a clock that only moves when something waits ----------------------------

class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        if seconds > 0:
            self.now += seconds

    def next_refresh(self, hold):
        """Block like SwapOnVSync: to the next refresh, then hold-1 more."""
        period = 1.0 / REFRESH_HZ
        ticks = int(self.now / period + 1e-9) + 1
        self.now = (ticks + max(1, hold) - 1) * period


class _Patched:
    """Route time.time / perf_counter / sleep to the virtual clock."""

    def __init__(self, clock):
        self.clock = clock

    def __enter__(self):
        self.saved = (time.time, time.perf_counter, time.sleep)
        time.time = self.clock.time
        time.perf_counter = self.clock.time
        time.sleep = self.clock.sleep
        return self.clock

    def __exit__(self, *exc):
        time.time, time.perf_counter, time.sleep = self.saved


class _Canvas:
    def SetImage(self, image):
        pass


class _Matrix:
    width, height, brightness = WIDTH, HEIGHT, 80

    def __init__(self, clock):
        self.clock = clock
        self.swaps = 0

    def CreateFrameCanvas(self):
        return _Canvas()

    def SwapOnVSync(self, canvas, framerate_fraction=1):
        self.clock.next_refresh(framerate_fraction)
        self.swaps += 1
        return canvas


def _display_manager(clock):
    """Core's DisplayManager, with only the state update_display() reads.

    __init__ opens the hardware, so it is bypassed; update_display,
    set_scrolling_state, set_frame_hold, is_currently_scrolling and refresh_hz
    are core's own, unmodified.
    """
    dm = DisplayManager.__new__(DisplayManager)
    dm.config = {"display": {"hardware": {"limit_refresh_rate_hz": REFRESH_HZ}}}
    dm.matrix = _Matrix(clock)
    dm.image = Image.new("RGB", (WIDTH, HEIGHT))
    dm.offscreen_canvas, dm.current_canvas = _Canvas(), _Canvas()
    dm._update_lock = threading.RLock()
    dm._capture_state = threading.local()  # _capture_mode_active reads it
    dm._dirty_tracking_enabled = True
    dm._last_pushed_digest = None
    dm._double_sided = None
    dm._frame_hold = 1
    dm._scrolling_state = {
        "is_scrolling": False,
        "last_scroll_activity": 0,
        "scroll_inactivity_threshold": 2.0,
        "deferred_updates": [],
        "max_deferred_updates": 50,
        "deferred_update_ttl": 300.0,
    }
    dm._write_snapshot_if_due = lambda *a, **k: None
    dm.defer_update = lambda *a, **k: None
    dm.state_calls = []
    real = dm.set_scrolling_state

    def recording(is_scrolling, frame_hold=1):
        dm.state_calls.append((bool(is_scrolling), frame_hold))
        return real(is_scrolling, frame_hold=frame_hold)

    dm.set_scrolling_state = recording
    return dm


class _Cache:
    def get(self, *a, **k):
        return None

    def set(self, *a, **k):
        pass

    def get_cached_data(self, *a, **k):
        return None

    def get_with_auto_strategy(self, *a, **k):
        return None


class _StatsLog(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        message = record.getMessage()
        if "Scroll frame stats" in message:
            self.lines.append(message)


def _plugin(clock, scroll_speed, scroll_delay, loop):
    config = {
        "enabled": True,
        "display_options": {
            "scroll_speed": scroll_speed,
            "scroll_delay": scroll_delay,
            "loop": loop,
            "dynamic_duration": True,
            # hdpi still stores both deprecated keys; they must change nothing.
            "scroll_pixels_per_second": 100.0,
            "target_fps": 120,
        },
        "leagues": {"nfl": {"enabled": True}},
    }
    dm = _display_manager(clock)
    plugin = OddsTickerPlugin("odds-ticker", copy.deepcopy(config), dm, _Cache(), None)
    # Per-card rendering needs logos and fonts and has nothing to do with pacing.
    plugin._create_game_display = lambda game: Image.new("RGB", (120, HEIGHT), (40, 80, 120))
    plugin.games_data = [{"id": "g1"}, {"id": "g2"}]
    plugin._create_ticker_image()
    plugin._get_current_update_interval = lambda: 3600
    return plugin, dm


def _run_slot(scroll_speed=1.0, scroll_delay=0.01, loop=False, seconds=8.0):
    """One slot through the controller's high-FPS loop (display_controller #523).

    Returns per-frame records: (virtual time, swaps this frame, frame hold in
    effect, scroll complete) plus the plugin, display manager and stats lines.
    """
    clock = _Clock()
    plugin, dm = _plugin(clock, scroll_speed, scroll_delay, loop)
    handler = _StatsLog()
    helper_logger = plugin.scroll_helper.logger
    # Core hands the helper a PluginLoggerAdapter; handlers live underneath.
    helper_logger = getattr(helper_logger, "logger", helper_logger)
    helper_logger.addHandler(handler)
    old_level = helper_logger.level
    helper_logger.setLevel(logging.INFO)
    frames = []
    try:
        with _Patched(clock):
            plugin.last_update = clock.now  # no refresh is due during the slot
            start = clock.now
            first = True
            while clock.now - start < seconds:
                frame_start = time.perf_counter()
                swaps_before = dm.matrix.swaps
                clock.now += RENDER_COST
                plugin.display(force_clear=first)
                first = False
                frames.append((clock.now, dm.matrix.swaps - swaps_before,
                               dm._frame_hold,
                               plugin.scroll_helper.is_scroll_complete()))
                remaining = CONTROLLER_INTERVAL - (time.perf_counter() - frame_start)
                time.sleep(remaining if remaining > 0 else 0.001)
    finally:
        helper_logger.removeHandler(handler)
        helper_logger.setLevel(old_level)
    return frames, plugin, dm, handler.lines


def _intervals(frames):
    return [b[0] - a[0] for a, b in zip(frames, frames[1:])]


def _fps(line):
    return float(line.split("Scroll frame stats - ")[1].split(" fps")[0])


@_fail_loudly
def test_frame_hold_matches_resolver():
    print("the frame hold passed while scrolling is the resolver's")
    for speed, delay in ((1.0, 0.01), (1.0, 0.02), (1.0, 0.04)):
        frames, plugin, dm, _ = _run_slot(speed, delay, loop=True, seconds=1.0)
        settings = scroll_config.configure(
            type("H", (), {"set_scroll_speed": lambda s, v: None})(),
            plugin_config=plugin.odds_ticker_config, display_manager=dm)
        expected = settings.frame_hold
        holds = {hold for scrolling, hold in dm.state_calls if scrolling}
        check("%.0f px/s: set_scrolling_state(True, frame_hold=%d)"
              % (speed / delay, expected), holds == {expected},
              "holds passed %r" % sorted(holds))
        check("%.0f px/s: the hold is in effect on every frame" % (speed / delay),
              all(f[2] == expected for f in frames[1:]),
              "holds seen %r" % sorted({f[2] for f in frames}))


@_fail_loudly
def test_parked_end_frame_stays_on_the_refresh():
    print("\nloop off: the parked end frame stays paced by the panel (hdpi's case)")
    # 520 px of strip at 100 px/s parks at ~5.2s; the stats window closing at
    # 10s is then mostly the parked tail, which is where hdpi read 8.1ms.
    frames, plugin, dm, stats = _run_slot(1.0, 0.01, loop=False, seconds=11.0)
    scrolling = [f for f in frames if not f[3]]
    parked = [f for f in frames if f[3]]
    check("the scroll completes inside the slot", len(parked) > 100,
          "%d parked frames" % len(parked))
    check("every scrolling frame waited for one refresh",
          all(f[1] == 1 for f in scrolling[1:]))
    unpresented = sum(1 for f in parked if f[1] == 0)
    check("every parked frame waited for a refresh too",
          unpresented == 0, "%d of %d parked frames skipped vsync"
          % (unpresented, len(parked)))
    if len(parked) > 2:
        median = statistics.median(_intervals(parked))
        check("parked frames are 10.00ms apart at 100 Hz",
              abs(median - 0.010) < 1e-6, "median %.2fms" % (median * 1000))
    check("scroll state is never released while the strip is on screen",
          all(scrolling_ for scrolling_, _ in dm.state_calls),
          "calls included %r" % sorted(set(dm.state_calls)))
    check("the frame-stats line was logged", bool(stats))
    for line in stats:
        check("frame stats report ~100 fps (%s)" % line.split(" | ")[0],
              99.0 <= _fps(line) <= 101.0)


@_fail_loudly
def test_parked_end_frame_keeps_a_longer_hold():
    print("\nloop off at 50 px/s: the parked frame keeps the hold of 2")
    frames, plugin, dm, stats = _run_slot(1.0, 0.02, loop=False, seconds=16.0)
    parked = [f for f in frames if f[3]]
    check("the scroll completes inside the slot", len(parked) > 50,
          "%d parked frames" % len(parked))
    if len(parked) > 2:
        median = statistics.median(_intervals(parked))
        check("parked frames are 20.00ms apart (hold 2 at 100 Hz)",
              abs(median - 0.020) < 1e-6, "median %.2fms" % (median * 1000))
    check("hold 2 stays in effect while parked",
          all(f[2] == 2 for f in parked), "holds %r" % sorted({f[2] for f in parked}))
    for line in stats:
        check("frame stats report ~50 fps (%s)" % line.split(" | ")[0],
              49.0 <= _fps(line) <= 51.0)


@_fail_loudly
def test_no_plugin_side_timing():
    print("\nno plugin-side frame timing: core's loop and vsync pace the scroll")
    tree = ast.parse((plugin_dir / "manager.py").read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    reachable, frontier = {"display"}, {"display"}
    while frontier:
        nxt = set()
        for name in frontier:
            for node in ast.walk(funcs[name]):
                if isinstance(node, ast.Call):
                    callee = ast.unparse(node.func).split(".")[-1]
                    if callee in funcs and callee not in reachable:
                        reachable.add(callee)
                        nxt.add(callee)
        frontier = nxt
    sleeps = sorted(
        "%s:%d" % (name, node.lineno)
        for name in reachable for node in ast.walk(funcs[name])
        if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "sleep")
    check("nothing display() reaches sleeps", not sleeps, ", ".join(sleeps))


TESTS = (test_frame_hold_matches_resolver,
         test_parked_end_frame_stays_on_the_refresh,
         test_parked_end_frame_keeps_a_longer_hold,
         test_no_plugin_side_timing)


if __name__ == "__main__":
    for test in TESTS:
        try:
            test()
        except _ChecksFailed:
            pass  # its checks are already recorded in failures
        except Exception as exc:  # a crash is a failure, not a skip
            import traceback
            traceback.print_exc()
            failures.append("%s crashed: %s" % (test.__name__, exc))
    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    sys.exit(1 if failures else 0)
