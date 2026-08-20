#!/usr/bin/env python3
"""A viewport swapped mid-render must not freeze the radar.

Observed on a live 512x64 rig while switching the radar map style: the panel
stopped updating and sat on an old frame. The log showed a hard exception on
every render:

    File "weather_radar.py", line 517, in get_radar_image
        composite = Image.alpha_composite(background.convert("RGBA"), frame.image)
    ValueError: images do not match

Two threads share the viewport. refresh_data() runs on the plugin's update
thread and get_radar_image() on the display thread; both call
_ensure_viewport(), which rebuilds self._viewport and drops the cached basemap,
vector map and every frame image when the requested panel size changes. And the
two are called with different sizes -- the plugin renders the full panel while
the Vegas adapter asks for a narrower slice:

    [Radar] Viewport: zoom=9 view=894x112 tiles=5 for panel 512x64
    [Radar] Viewport: zoom=7 view=223x70  tiles=2 for panel 204x64

Build a frame under one viewport, swap to the other before compositing, and the
two images no longer agree. alpha_composite raises, the exception leaves
display(), and nothing new reaches the panel -- so it holds the last good
frame and looks frozen at an old timestamp.

The composite now checks the pair first and shows the map alone for that tick,
dropping the stale frame images so the next tick rebuilds them consistently.

Run: <core-venv>/bin/python plugins/ledmatrix-weather/test_radar_viewport_race.py
"""

import sys
from pathlib import Path

from PIL import Image

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "common" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        break

import weather_radar  # noqa: E402  # pylint: disable=wrong-import-position
from weather_radar import RadarFetcher  # noqa: E402  # pylint: disable=wrong-import-position

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Frame:
    def __init__(self, image, ts=1_000_000):
        self.image = image
        self.ts = ts
        self.is_nowcast = False


def _fetcher():
    """A RadarFetcher without its network-touching __init__.

    Attribute defaults are read out of the real __init__ rather than listed by
    hand, so a new attribute there cannot leave this harness silently stale.
    """
    f = object.__new__(RadarFetcher)
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(RadarFetcher.__init__).lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "attr", None)
                and getattr(node.targets[0].value, "id", None) == "self"):
            name = node.targets[0].attr
            try:
                setattr(f, name, ast.literal_eval(node.value))
            except (ValueError, SyntaxError):
                setattr(f, name, None)
    f.lat, f.lon = 27.95, -82.46
    f.range_miles = 100.0
    f.map_style = "vector"
    f.map_brightness = 0.5
    f.line_color = (60, 60, 60)
    f.fill_color = (10, 10, 10)
    f._viewport = None
    f._panel_size = None
    f._basemap = None
    f._vector_map = None
    f._basemap_retry_after = 0.0
    f._frames = {}
    f._frame_index = 0
    f._font = None
    f._newest_past_ts = 0
    f._last_frame_switch = 0.0
    f.frame_seconds = 0.5
    f.loop_pause_seconds = 2.0
    f.show_nowcast = False
    return f


def main():
    print("a frame from the wrong viewport must not raise")
    f = _fetcher()

    # Establish the narrow viewport, as the Vegas adapter would.
    viewport = f._ensure_viewport(204, 64)
    background = f._get_background(viewport)
    check("a background exists for the 204px viewport", background is not None)

    # A frame built under the full-panel viewport: deliberately the wrong size.
    wrong = Image.new("RGBA", (background.size[0] + 671,
                               background.size[1] + 42), (0, 0, 0, 0))
    f._frames = {1: _Frame(wrong)}
    check("the frame really does disagree with the background",
          wrong.size != background.size)

    try:
        img = f.get_radar_image(204, 64)
        raised = None
    except Exception as exc:  # noqa: BLE001
        img, raised = None, exc

    check("get_radar_image does not raise (%s)" % (type(raised).__name__ if raised else "no exception"),
          raised is None)
    check("it still returns an image to draw", img is not None)
    if img is not None:
        check("at the requested size", img.size == (204, 64))
    check("and the stale frame image is dropped so the next tick rebuilds",
          all(fr.image is None for fr in f._frames.values()))

    print("\nmatching sizes still composite normally")
    f2 = _fetcher()
    viewport2 = f2._ensure_viewport(204, 64)
    bg2 = f2._get_background(viewport2)
    good = Image.new("RGBA", bg2.size, (0, 0, 0, 0))
    f2._frames = {1: _Frame(good)}
    try:
        img2 = f2.get_radar_image(204, 64)
        ok = img2 is not None and img2.size == (204, 64)
    except Exception as exc:  # noqa: BLE001
        print(f"        raised {type(exc).__name__}: {exc}")
        ok = False
    check("a well-formed frame is composited and returned", ok)
    check("and its image is kept, not discarded",
          all(fr.image is not None for fr in f2._frames.values()))

    print("\nthe update thread may null a frame image mid-render")
    # Raised in review: refresh_data() can clear frame.image between the guard
    # selecting the frame and reading its size, so re-reading the attribute
    # would raise AttributeError instead of the ValueError the guard exists
    # for. The image must be read once and held.
    f3 = _fetcher()
    vp3 = f3._ensure_viewport(204, 64)
    bg3 = f3._get_background(vp3)

    class _VanishingFrame(_Frame):
        """Returns an image once, then reports None, as the other thread would."""

        def __init__(self, image):
            super().__init__(image)
            self._reads = 0

        @property
        def image(self):
            self._reads += 1
            return self._image if self._reads <= 1 else None

        @image.setter
        def image(self, value):
            self._image = value

    f3._frames = {1: _VanishingFrame(Image.new("RGBA", bg3.size, (0, 0, 0, 0)))}
    try:
        img3 = f3.get_radar_image(204, 64)
        raised3 = None
    except Exception as exc:  # noqa: BLE001
        img3, raised3 = None, exc
    check("a frame image nulled mid-render does not raise (%s)"
          % (type(raised3).__name__ if raised3 else "no exception"),
          raised3 is None)
    check("and a frame is still returned", img3 is not None)

    print("\nthe frame map may be mutated while it is read")
    # Also raised in review. Tested with real threads rather than a fake dict:
    # the failure is CPython raising "dictionary changed size during iteration"
    # when another thread inserts mid-iteration, and only a real dict under a
    # real interleaving demonstrates that a snapshot is taken atomically.
    import threading

    f4 = _fetcher()
    f4._ensure_viewport(204, 64)
    bg4 = f4._get_background(f4._viewport)
    f4._frames = {i: _Frame(Image.new("RGBA", bg4.size, (0, 0, 0, 0)), ts=i)
                  for i in range(1, 9)}

    errors = []
    stop = threading.Event()

    def churn():
        n = 10_000
        while not stop.is_set():
            n += 1
            f4._frames[n] = _Frame(None, ts=n)
            f4._frames.pop(n - 1, None)

    def render():
        try:
            for _ in range(400):
                f4.get_radar_image(204, 64)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    churner = threading.Thread(target=churn, daemon=True)
    renderer = threading.Thread(target=render)
    churner.start(); renderer.start()
    renderer.join(30)
    stop.set(); churner.join(2)

    check("400 renders against a concurrently mutated frame map raise nothing "
          "(%s)" % (f"{type(errors[0]).__name__}: {errors[0]}" if errors else "none"),
          not errors)

    # The stress above is a smoke check and cannot prove absence: the
    # interleaving needs the other thread to insert between two nexts, which
    # the GIL makes rare enough that 400 renders routinely miss it. Reverting
    # to lazy iteration still passes it. So pin the property structurally --
    # this is what actually catches a regression.
    import inspect

    import weather_radar as wr
    for name, fn in (("_playback_frames", wr.RadarFetcher._playback_frames),
                     ("get_radar_image", wr.RadarFetcher.get_radar_image)):
        src = inspect.getsource(fn)
        if "_frames" not in src:
            continue
        lazy = [ln.strip() for ln in src.splitlines()
                if "self._frames.values()" in ln and ".copy()" not in ln]
        check(f"{name}() snapshots the frame map instead of iterating it live"
              + (f" ({lazy[0]})" if lazy else ""), not lazy)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
