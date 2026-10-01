"""The radar animates in the Vegas ticker (LEDMatrix 3.8.0 live elements).

The ticker gets the usual forecast cards plus one live 'radar' element, which
it redraws a few times a second while the radar scrolls past, without the
plugin's lock. Every frame is composed once, when the frames change
(RadarFetcher.compose_loop); a redraw only picks the frame for the moment, on
the full-screen radar's timing. Nothing here touches the network: the fetcher
is given frames by hand on the offline vector basemap.

Run: <core-venv>/bin/python -m pytest plugins/ledmatrix-weather/test_vegas_radar.py
"""
import os
import sys
import time

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))

import manager  # noqa: E402
from manager import WeatherPlugin  # noqa: E402
from weather_radar import RadarFetcher, RadarFrame  # noqa: E402

W, H = 128, 32
FRAME_S, PAUSE_S = 0.5, 1.5


def _fetcher(frames=3, size=(W, H)):
    fetcher = RadarFetcher(27.95, -82.46, 50, None, map_style="vector",
                           past_frames=frames, frame_seconds=FRAME_S,
                           loop_pause_seconds=PAUSE_S)
    viewport = fetcher._ensure_viewport(*size)
    for i in range(frames):
        image = Image.new("RGBA", (viewport.view_w, viewport.view_h), (0, 0, 0, 0))
        # A storm cell that moves, so every frame differs.
        x = 10 + 15 * i
        ImageDraw.Draw(image).ellipse((x, 5, x + 12, 17), fill=(0, 200, 60, 220))
        ts = 1_700_000_000 + 600 * i
        fetcher._frames[ts] = RadarFrame(ts=ts, path=f"/p{i}", is_nowcast=False, image=image)
    fetcher._newest_past_ts = max(fetcher._frames)
    return fetcher


# -- the loop -----------------------------------------------------------------


def test_the_loop_is_every_frame_finished_at_the_panel_size():
    loop = _fetcher().compose_loop()
    assert loop.size == (W, H) and len(loop.images) == 3
    assert all(img.size == (W, H) and img.mode == "RGB" for img in loop.images)
    assert len({img.tobytes() for img in loop.images}) == 3


@pytest.mark.parametrize("at, index", [
    (0.0, 0), (0.49, 0), (0.5, 1), (0.99, 1), (1.0, 2),
    (2.99, 2),                       # the newest frame holds through the pause
    (3.0, 0), (3.6, 1),              # and the loop starts again
])
def test_playback_follows_the_full_screen_timing(at, index):
    loop = _fetcher().compose_loop()
    assert loop.duration == 3 * FRAME_S + PAUSE_S
    assert loop.index_at(at) == index


def test_a_loop_frame_is_exactly_what_the_full_screen_radar_shows():
    fetcher = _fetcher()
    loop = fetcher.compose_loop()
    for k in range(3):
        fetcher._frame_index = k
        fetcher._last_frame_advance = time.time() + 60       # no advance now
        assert fetcher.get_radar_image(W, H).tobytes() == loop.images[k].tobytes()


def test_composing_changes_neither_viewport_nor_playback():
    fetcher = _fetcher()
    viewport, index, frames = fetcher._viewport, fetcher._frame_index, dict(fetcher._frames)
    fetcher.compose_loop()
    assert fetcher._viewport is viewport and fetcher._frame_index == index
    assert all(fetcher._frames[ts].image is frames[ts].image for ts in frames)


def test_the_key_moves_only_when_a_frame_or_the_map_changes():
    fetcher = _fetcher()
    key = fetcher.loop_key()
    assert fetcher.loop_key() == key
    newest = max(fetcher._frames)
    fetcher._frames[newest].image = fetcher._frames[newest].image.copy()
    assert fetcher.loop_key() != key


@pytest.mark.parametrize("why", ["no frames", "no viewport", "frame of another size"])
def test_no_loop_when_there_is_nothing_consistent_to_play(why):
    fetcher = _fetcher()
    if why == "no frames":
        fetcher._frames.clear()
    elif why == "no viewport":
        fetcher._viewport = None
    else:
        frame = next(iter(fetcher._frames.values()))
        frame.image = Image.new("RGBA", (5, 5))
    assert fetcher.compose_loop() is None


# -- the plugin's Vegas hooks ---------------------------------------------------------


class _Fetches:
    """Counts compose_loop calls on a real fetcher."""

    def __init__(self, fetcher):
        self.fetcher, self.composed = fetcher, 0

    def __getattr__(self, name):
        return getattr(self.fetcher, name)

    def compose_loop(self):
        self.composed += 1
        return self.fetcher.compose_loop()


def _plugin(fetcher=None, show_radar=True, radar_in_vegas=True):
    p = object.__new__(WeatherPlugin)
    p.show_radar = show_radar
    p.radar_in_vegas = radar_in_vegas
    p._radar_fetcher = _Fetches(fetcher or _fetcher())
    p._radar_panel_size = (W, H)
    p._vegas_radar_loop = None
    p.cards = [Image.new("RGB", (40, H), (200, 0, 0)), Image.new("RGB", (60, H), (0, 0, 200))]
    p.get_vegas_content = lambda: list(p.cards)
    return p


def test_the_ticker_gets_the_cards_then_the_animated_radar():
    elements = _plugin().get_vegas_elements()
    assert [(e.key, e.live) for e in elements] == [("card:0", False), ("card:1", False),
                                                    ("radar", True)]
    radar = elements[-1]
    assert radar.image.size == (W, H)
    assert radar.refresh_hz == 1.0 / FRAME_S


@pytest.mark.parametrize("why", ["radar off", "not in the ticker", "older core", "no frames"])
def test_otherwise_the_ticker_keeps_its_ordinary_content(why, monkeypatch):
    p = _plugin(show_radar=why != "radar off", radar_in_vegas=why != "not in the ticker")
    if why == "older core":
        monkeypatch.setattr(manager, "VegasElement", None)
    if why == "no frames":
        p._radar_fetcher.fetcher._frames.clear()
    assert p.get_vegas_elements() is None


def test_the_loop_is_composed_again_only_when_its_frames_change():
    p = _plugin()
    p.get_vegas_elements()
    p.get_vegas_elements()
    assert p._radar_fetcher.composed == 1
    frames = p._radar_fetcher.fetcher._frames
    newest = max(frames)
    frames[newest].image = frames[newest].image.copy()
    p.get_vegas_elements()
    assert p._radar_fetcher.composed == 2


def test_a_redraw_picks_the_frame_for_the_moment_and_nothing_else():
    p = _plugin()
    p.get_vegas_elements()
    loop = p._vegas_radar_loop

    class _Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"the lock-free redraw read the fetcher ({name})")

    p._radar_fetcher = _Untouchable()          # update() may be rebuilding it
    for at in (0.2, 0.7, 1.2, 2.5, 3.1):
        assert p.redraw_vegas_element("radar", W, H, at) is loop.frame_at(at)
    assert p.redraw_vegas_element("card:0", W, H, 0.2) is None
    assert p.redraw_vegas_element("radar", W + 1, H, 0.2) is None


def test_no_redraw_before_a_loop_exists():
    assert _plugin().redraw_vegas_element("radar", W, H, 0.0) is None


def test_the_setting_defaults_on_in_the_schema():
    import json
    with open(os.path.join(os.path.dirname(__file__), "config_schema.json"), encoding="utf-8") as f:
        prop = json.load(f)["properties"]["radar_in_vegas"]
    assert prop["type"] == "boolean" and prop["default"] is True
