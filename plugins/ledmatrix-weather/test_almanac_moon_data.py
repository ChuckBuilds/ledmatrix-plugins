#!/usr/bin/env python3
"""Regression tests for the almanac (moon) page DATA, not its layout.

Two bugs this guards against:

1. Missing moonset. astral only searches a single calendar day, so on the one
   day a month the event straddles midnight it raises "Moon never sets on this
   date" and the page drew "---" (sffjunkie/astral #88, #105, open as of the
   latest release 3.2). Federal Way, WA on 2026-06-11 is exactly such a day:
   the moon rises 02:24 and sets ~17:23, but astral.moonset() raises. The
   fallback must recover an afternoon moonset, and must still agree with astral
   to the minute on a normal day.

2. The "illumination %" actually showed the cycle fraction: a waning crescent
   read "86%" when it's ~13% lit. _moon_illumination must convert phase ->
   lit fraction.

Run with the core venv from a LEDMatrix checkout so astral resolves:
    LEDMatrix/.venv/bin/python <thisfile>
"""
import datetime
import os
import sys
import zoneinfo

sys.path.insert(0, os.path.dirname(__file__))
from manager import WeatherPlugin  # noqa: E402

from astral import moon as astral_moon, Observer  # noqa: E402


# Federal Way, WA — the board's configured location.
TZ = zoneinfo.ZoneInfo("America/Los_Angeles")
OBS = Observer(latitude=47.3223, longitude=-122.3126)


def check_moonset_fallback():
    """astral fails on 2026-06-11; the fallback recovers the real afternoon
    moonset (independently confirmed ~17:23 local)."""
    plugin = object.__new__(WeatherPlugin)
    fails = []
    d = datetime.date(2026, 6, 11)

    # Document the underlying astral bug: it raises the specific "never sets"
    # ValueError on this date.
    astral_raised = False
    try:
        astral_moon.moonset(OBS, d, tzinfo=TZ)
    except ValueError as exc:
        astral_raised = "never sets" in str(exc)
    if not astral_raised:
        fails.append("astral.moonset no longer raises 'never sets' on "
                     "2026-06-11 — the fallback may be untested; revisit this "
                     "guard")

    got = plugin._moon_event_fallback(OBS, d, TZ, rising=False)
    if got is None:
        fails.append("fallback returned None for 2026-06-11 moonset")
    else:
        local = got.astimezone(TZ)
        if local.date() != d:
            fails.append(f"moonset landed on {local.date()}, expected {d}")
        if not (12 <= local.hour < 20):  # afternoon, between 10th & 12th sets
            fails.append(f"moonset {local:%H:%M} outside expected afternoon window")
    return fails


def check_fallback_matches_astral():
    """On a normal day the fallback agrees with astral to within a minute, so
    swapping in fallback values never produces a visible discontinuity."""
    plugin = object.__new__(WeatherPlugin)
    fails = []
    d = datetime.date(2026, 6, 12)  # astral succeeds: rise 02:49, set 18:50
    for rising, label in ((True, "moonrise"), (False, "moonset")):
        try:
            ref = (astral_moon.moonrise if rising else astral_moon.moonset)(
                OBS, d, tzinfo=TZ)
        except Exception as exc:
            fails.append(f"astral {label} unexpectedly failed on {d}: {exc}")
            continue
        got = plugin._moon_event_fallback(OBS, d, TZ, rising=rising)
        if got is None:
            fails.append(f"fallback returned None for {label} on {d}")
            continue
        delta = abs((got - ref).total_seconds())
        if delta > 90:
            fails.append(f"{label} fallback off by {delta:.0f}s from astral")
    return fails


def check_illumination():
    """Lit fraction, not cycle progress. Agreement at the quarters, divergence
    everywhere else — especially the crescents that motivated the fix."""
    fails = []
    # (phase, expected lit %)
    cases = [
        (0.0, 0),     # new
        (0.25, 50),   # first quarter
        (0.5, 100),   # full
        (0.75, 50),   # last quarter
        (0.857, 19),  # the photo: waning crescent — NOT 86%
        (0.60, 90),   # waning gibbous — NOT 60%
    ]
    for phase, expected in cases:
        pct = int(round(WeatherPlugin._moon_illumination(phase) * 100))
        if pct != expected:
            fails.append(f"phase {phase}: illumination {pct}%, expected {expected}%")
    # The whole point: it must differ from the old cycle-fraction display for
    # a crescent.
    if int(round(WeatherPlugin._moon_illumination(0.857) * 100)) == 86:
        fails.append("illumination still equals cycle fraction (0.857 -> 86%)")
    return fails


def main():
    total_fail = 0
    for fn in (check_moonset_fallback, check_fallback_matches_astral,
               check_illumination):
        fails = fn()
        tag = fn.__name__
        if fails:
            total_fail += 1
            print(f"FAIL {tag}:")
            for f in fails:
                print(f"       {f}")
        else:
            print(f"PASS {tag}")
    if total_fail:
        print(f"\n{total_fail} check(s) failed")
        sys.exit(1)
    print("\nAlmanac moon data: moonset fallback + true illumination OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
