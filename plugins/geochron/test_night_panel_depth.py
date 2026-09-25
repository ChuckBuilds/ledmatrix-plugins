#!/usr/bin/env python3
"""
Tests that the countries stay visible on the night side at low PWM depth.

Regression under test: night-side land is (9, 17, 22) and ocean (5, 8, 27) at
the defaults. rpi-rgb-led-matrix lights only the top pwm_bits of its 11
luminance-corrected bit planes, and at pwm_bits 7, brightness 80 both colours
land on the same step (0, 0, 1) -- the night side became one flat block. At 8
bits land kept a green step ocean lacked, which is why it only showed up after
a board went from 8 to 7 bits.

The fix remaps one channel of the night side just far enough to put land a
step clear of ocean, and only when the panel would otherwise merge them.

Run: <core-venv>/bin/python plugins/geochron/test_night_panel_depth.py
"""

import os
import sys
from pathlib import Path

import numpy as np

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
# LEDMATRIX_CORE is the runner's contract for "here is the core"; see
# test_per_size_map_cache.py for why it is honoured before guessing.
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

import geochron_renderer as gr  # noqa: E402
import worldmap  # noqa: E402
from manager import DEFAULT_COLORS, GeochronPlugin  # noqa: E402

LAND = DEFAULT_COLORS["land_color"]
OCEAN = DEFAULT_COLORS["ocean_color"]
COAST = DEFAULT_COLORS["coastline_color"]
TINT = DEFAULT_COLORS["night_tint_color"]
NIGHT = 0.20

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def levels(rgb, bits, brightness):
    return tuple(gr.panel_level(int(c), bits, brightness) for c in rgb)


def lift_for(bits, brightness, night=NIGHT):
    return gr.night_lift(LAND, OCEAN, night, TINT, bits, brightness)


def render(lift):
    base = worldmap.render_base_map(OCEAN, LAND, COAST)
    layout = gr._layout(128, 64)
    dark = np.ones((worldmap.GRID_H, worldmap.GRID_W))
    day = np.zeros((worldmap.GRID_H, worldmap.GRID_W))
    night_img = gr.render_map_image(base, dark, layout, NIGHT, TINT, lift=lift)
    day_img = gr.render_map_image(base, day, layout, NIGHT, TINT)
    return np.asarray(night_img).astype(int), np.asarray(day_img).astype(int)


def separated_share(night, day, bits, brightness):
    """Share of land-interior pixels that light differently from open ocean."""
    near = lambda a, c: np.all(np.abs(a - np.array(c)) <= 2, axis=-1)  # noqa: E731
    land = night[near(day, LAND)]
    ocean = night[near(day, OCEAN)]
    ocean_levels = {levels(p, bits, brightness) for p in ocean}
    if len(land) == 0 or len(ocean_levels) != 1:
        return None
    (ocean_level,) = ocean_levels
    return sum(levels(p, bits, brightness) != ocean_level for p in land) / len(land)


def main():
    print("panel_level matches the library's CIE1931 table")
    # luminance_cie1931(22, 80) = 16: the lowest step at 7 bits, nothing at 6.
    check("22 at brightness 80 is step 1 at 7 bits", gr.panel_level(22, 7, 80) == 1)
    check("22 at brightness 80 is off at 6 bits", gr.panel_level(22, 6, 80) == 0)
    check("255 at full brightness is the top step at 11 bits",
          gr.panel_level(255, 11, 100) == 2047)
    check("0 is off at any depth", gr.panel_level(0, 11, 100) == 0)

    print("\nthe bug: at 7 bits, brightness 80, land and ocean merge")
    land_n = gr.night_color(LAND, NIGHT, TINT)
    ocean_n = gr.night_color(OCEAN, NIGHT, TINT)
    check("night land and ocean light the same steps",
          levels(land_n, 7, 80) == levels(ocean_n, 7, 80))
    check("at 8 bits they did not", levels(land_n, 8, 80) != levels(ocean_n, 8, 80))

    print("\nno lift where the panel already separates them")
    check("11 bits, brightness 100", lift_for(11, 100) is None)
    check("8 bits, brightness 80", lift_for(8, 80) is None)
    check("night_brightness 0 stays all tint", lift_for(7, 80, night=0.0) is None)
    check("brightness 0", lift_for(7, 0) is None)
    check("an out-of-range pwm_bits", lift_for(12, 80) is None)

    for bits, brightness in ((7, 80), (8, 30), (6, 100)):
        name = "%d bits, brightness %d" % (bits, brightness)
        print("\n" + name)
        lift = lift_for(bits, brightness)
        check("a lift is needed", lift is not None)
        if lift is None:
            continue
        channel, low, high, target = lift
        check("it lifts green, where land and ocean differ most", channel == 1)
        check("the target is one step above ocean",
              gr.panel_level(target, bits, brightness)
              == gr.panel_level(int(low), bits, brightness) + 1)
        check("and is the lowest value that gets there",
              gr.panel_level(target - 1, bits, brightness)
              <= gr.panel_level(int(low), bits, brightness))

    print("\nthe whole map at 7 bits, brightness 80")
    night, day = render(None)
    before = separated_share(night, day, 7, 80)
    check("without the lift no land pixel stands out from ocean", before == 0)
    night, day = render(lift_for(7, 80))
    after = separated_share(night, day, 7, 80)
    check("with it nearly every land pixel does (%.0f%%)" % (100 * (after or 0)),
          after is not None and after >= 0.95)
    ocean_px = night[np.all(np.abs(day - np.array(OCEAN)) <= 2, axis=-1)]
    check("ocean is not brightened",
          int(ocean_px[:, 1].max()) <= int(ocean_n[1]) + 1)

    print("\n_panel_lift reads the panel from the display manager")

    class _DM:
        def __init__(self, brightness, bits):
            self._b = brightness
            self.config = {"display": {"hardware": {"pwm_bits": bits}}}

        def get_brightness(self):
            return self._b

    class _Logger:
        def debug(self, *a, **k):
            pass

    class _Geo:
        _panel_lift = GeochronPlugin._panel_lift

        def __init__(self, dm):
            self.display_manager = dm
            self.colors = dict(DEFAULT_COLORS)
            self.night_brightness = NIGHT
            self.logger = _Logger()

    saved = os.environ.pop("EMULATOR", None)
    try:
        check("7 bits at 80 lifts", _Geo(_DM(80, 7))._panel_lift() is not None)
        check("8 bits at 80 does not", _Geo(_DM(80, 8))._panel_lift() is None)
        check("no matrix (brightness -1) does not", _Geo(_DM(-1, 7))._panel_lift() is None)
        check("a display manager without get_brightness does not",
              _Geo(object())._panel_lift() is None)
        os.environ["EMULATOR"] = "true"
        check("the emulator does not", _Geo(_DM(80, 7))._panel_lift() is None)
    finally:
        os.environ.pop("EMULATOR", None)
        if saved is not None:
            os.environ["EMULATOR"] = saved

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
