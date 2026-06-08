#!/usr/bin/env python3
"""
Regression tests for the overhead card's route<->model alternation.

The overhead card has a single secondary text row shared by the flight route
(e.g. "SEA>PHX") and the aircraft model. Before this change the route always
won and the model was never shown when a route was known. Now the row
alternates between them every `overhead_alt_interval` seconds, and the model is
rendered as a friendly name ("Boeing 737-900") rather than the raw ICAO type
code ("B739").

Run with the core venv:
    .venv/bin/python plugins/ledmatrix-flights/test/test_overhead_alternation.py
"""

import sys
import time as _time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

import PIL.ImageDraw as _ID  # noqa: E402
from renderer import FlightRenderer  # noqa: E402
from static_data import aircraft_types  # noqa: E402


class _FakeMatrix:
    def __init__(self, w, h):
        self.width = w
        self.height = h


class _FakeDM:
    def __init__(self, w, h):
        self.matrix = _FakeMatrix(w, h)
        self.image = None

    def update_display(self):
        pass


def make_renderer(w=128, h=32, config=None):
    return FlightRenderer(_FakeDM(w, h), {}, config or {})


def _aircraft(**over):
    ac = {
        "callsign": "ASA632",
        "airline_icao": "ASA",
        "altitude": 4700,
        "speed": 253,
        "distance_miles": 1.1,
        "heading": 180,
        "origin": "SEA",
        "destination": "PHX",
        "aircraft_type": "B739",
        "color": (0, 200, 255),
    }
    ac.update(over)
    return ac


def _capture_text(fn):
    captured = []
    orig = _ID.ImageDraw.text

    def rec(self, xy, text="", *a, **k):
        captured.append(text)
        return orig(self, xy, text, *a, **k)

    _ID.ImageDraw.text = rec
    try:
        fn()
    finally:
        _ID.ImageDraw.text = orig
    return captured


def _overhead_texts_at(r, now, **over):
    """Render the overhead card with time.time() frozen at *now*."""
    orig = _time.time
    _time.time = lambda: now
    try:
        return _capture_text(lambda: r.render_overhead_image(_aircraft(**over)))
    finally:
        _time.time = orig


# ---------------------------------------------------------------------------
# _alternating_pick: pure phase selection
# ---------------------------------------------------------------------------

def test_alternating_pick_cycles_each_interval():
    pick = FlightRenderer._alternating_pick
    a, b = "SEA>PHX", "Boeing 737-900"
    assert pick([a, b], 0.0, 4.0) == a
    assert pick([a, b], 3.9, 4.0) == a
    assert pick([a, b], 4.0, 4.0) == b
    assert pick([a, b], 7.9, 4.0) == b
    assert pick([a, b], 8.0, 4.0) == a


def test_alternating_pick_single_value_is_steady():
    pick = FlightRenderer._alternating_pick
    # A known route with no model never flickers to blank, and vice versa.
    assert pick(["SEA>PHX", ""], 0.0, 4.0) == "SEA>PHX"
    assert pick(["SEA>PHX", ""], 999.0, 4.0) == "SEA>PHX"
    assert pick(["", "Boeing 737-900"], 999.0, 4.0) == "Boeing 737-900"


def test_alternating_pick_empty_returns_blank():
    assert FlightRenderer._alternating_pick(["", ""], 5.0, 4.0) == ""
    assert FlightRenderer._alternating_pick([], 5.0, 4.0) == ""


def test_alternating_pick_disabled_interval_keeps_first():
    # interval <= 0 disables alternation: the route (first option) wins, as before.
    pick = FlightRenderer._alternating_pick
    assert pick(["SEA>PHX", "B739"], 999.0, 0.0) == "SEA>PHX"


# ---------------------------------------------------------------------------
# Friendly aircraft-model names
# ---------------------------------------------------------------------------

def test_friendly_name_maps_known_code():
    assert aircraft_types.name("B739") == "Boeing 737-900"
    assert aircraft_types.name("A20N") == "Airbus A320neo"


def test_friendly_name_is_case_insensitive():
    assert aircraft_types.name("b739") == "Boeing 737-900"


def test_friendly_name_falls_back_to_code():
    assert aircraft_types.name("ZZZZ") == "ZZZZ"
    assert aircraft_types.name("") == ""


# ---------------------------------------------------------------------------
# Rendered card actually alternates
# ---------------------------------------------------------------------------

def test_overhead_shows_route_then_model():
    r = make_renderer(128, 32, {"overhead_alt_interval": 4.0})
    phase_route = " ".join(_overhead_texts_at(r, 0.0))   # idx 0 -> route
    phase_model = _overhead_texts_at(r, 4.0)             # idx 1 -> model

    assert "SEA>PHX" in phase_route, phase_route
    assert "737-900" not in phase_route, phase_route

    joined_model = " ".join(phase_model)
    assert "SEA>PHX" not in joined_model, phase_model
    # On the compact 128x32 the full "Boeing 737-900" doesn't fit, so the
    # maker word is dropped to "737-900" (never a mid-number truncation).
    assert "737-900" in joined_model, phase_model
    assert "Boeing 737-90." not in joined_model, phase_model


def test_overhead_wide_panel_shows_full_model_name():
    # On a wide panel the full friendly name fits, so it is shown in full.
    r = make_renderer(256, 64, {"overhead_alt_interval": 4.0})
    saw_full = any(
        any(t == "Boeing 737-900" for t in _overhead_texts_at(r, now))
        for now in (0.0, 4.0, 8.0, 12.0)
    )
    assert saw_full, "full 'Boeing 737-900' never shown on a wide panel"


def test_overhead_model_falls_back_to_short_form():
    # The de-manufacturer fallback yields a clean short form on the compact panel.
    r = make_renderer(128, 32, {"overhead_alt_interval": 4.0})
    saw_short = any(
        "737-900" in " ".join(_overhead_texts_at(r, now))
        for now in (4.0, 12.0)
    )
    assert saw_short, "compact panel never shows the '737-900' short form"


def test_overhead_with_only_route_is_steady():
    # No known type -> route shows in every phase (no blank flicker).
    r = make_renderer(128, 32, {"overhead_alt_interval": 4.0})
    for now in (0.0, 4.0, 8.0):
        texts = _overhead_texts_at(r, now, aircraft_type="Unknown")
        assert "SEA>PHX" in " ".join(texts), (now, texts)


def test_overhead_default_interval_alternates():
    # Default config (no override) still alternates: model appears at some phase.
    r = make_renderer(128, 32)
    saw_model = any(
        "737-900" in " ".join(_overhead_texts_at(r, now))
        for now in (0.0, 4.0, 8.0, 12.0)
    )
    assert saw_model, "model never shown across phases with default interval"


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # pragma: no cover
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
