"""Unit tests for the radar viewport math and frame handling (no network)."""

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weather_map_tiles import (
    MAX_TILES_PER_LAYER,
    MercatorViewport,
    TILE_SIZE,
    latlon_to_world_px,
    world_px_to_latlon,
)
from weather_radar import RadarFetcher, render_vector_map

MEMPHIS = (35.1495, -90.0490)
PANEL_SIZES = [(64, 32), (128, 32), (128, 64), (256, 32)]


class TestWorldPixelMath:
    def test_roundtrip(self):
        for lat, lon in [MEMPHIS, (0.0, 0.0), (-33.86, 151.21), (60.17, 24.94)]:
            for zoom in (3, 7, 12):
                wx, wy = latlon_to_world_px(lat, lon, zoom)
                back_lat, back_lon = world_px_to_latlon(wx, wy, zoom)
                assert back_lat == pytest.approx(lat, abs=1e-6)
                assert back_lon == pytest.approx(lon, abs=1e-6)

    def test_zoom_doubles_world_size(self):
        wx1, wy1 = latlon_to_world_px(*MEMPHIS, 5)
        wx2, wy2 = latlon_to_world_px(*MEMPHIS, 6)
        assert wx2 == pytest.approx(2 * wx1)
        assert wy2 == pytest.approx(2 * wy1)


class TestViewportForPanel:
    def test_zoom_increases_as_range_shrinks(self):
        zooms = [MercatorViewport.for_panel(*MEMPHIS, r, 128, 64).zoom
                 for r in (500, 200, 100, 50, 25, 10)]
        assert zooms == sorted(zooms)

    def test_tile_cap_honored_all_panels_and_ranges(self):
        for pw, ph in PANEL_SIZES:
            for r in (10, 25, 50, 100, 250, 500):
                vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], r, pw, ph)
                assert vp.num_tiles() <= MAX_TILES_PER_LAYER, \
                    f"{pw}x{ph} range={r} -> {vp.num_tiles()} tiles"

    def test_view_never_smaller_than_panel(self):
        for pw, ph in PANEL_SIZES:
            vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 50, pw, ph)
            assert vp.view_w >= pw
            assert vp.view_h >= ph - 1  # rounding

    def test_aspect_ratio_preserved(self):
        vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 50, 128, 64)
        assert vp.view_w / vp.view_h == pytest.approx(2.0, abs=0.05)


class TestViewportProjection:
    def test_center_projects_to_view_center(self):
        vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 50, 128, 64)
        vx, vy = vp.latlon_to_view(*MEMPHIS)
        assert vx == pytest.approx(vp.view_w / 2, abs=1)
        assert vy == pytest.approx(vp.view_h / 2, abs=1)

    def test_center_projects_to_panel_center(self):
        for pw, ph in PANEL_SIZES:
            vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 50, pw, ph)
            px, py = vp.latlon_to_panel(MEMPHIS[0], MEMPHIS[1], pw, ph)
            assert abs(px - pw // 2) <= 1
            assert abs(py - ph // 2) <= 1

    def test_tile_paste_offsets_are_consistent(self):
        """A world point inside a tile must land at paste_offset + in-tile pos."""
        vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 50, 128, 64)
        wx, wy = latlon_to_world_px(*MEMPHIS, vp.zoom)
        tx, ty = int(wx // TILE_SIZE), int(wy // TILE_SIZE)
        ox, oy = vp.tile_paste_offset(tx, ty)
        vx, vy = vp.latlon_to_view(*MEMPHIS)
        assert ox + (wx - tx * TILE_SIZE) == pytest.approx(vx, abs=1)
        assert oy + (wy - ty * TILE_SIZE) == pytest.approx(vy, abs=1)

    def test_tile_range_covers_view_corners(self):
        vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 100, 256, 32)
        x0, y0, x1, y1 = vp.tile_range()
        assert x0 * TILE_SIZE <= vp.origin_x
        assert (x1 + 1) * TILE_SIZE >= vp.origin_x + vp.view_w - 1
        assert y0 * TILE_SIZE <= vp.origin_y
        assert (y1 + 1) * TILE_SIZE >= vp.origin_y + vp.view_h - 1


class TestVectorMap:
    def test_renders_state_lines_at_viewport_size(self):
        vp = MercatorViewport.for_panel(MEMPHIS[0], MEMPHIS[1], 200, 128, 64)
        img = render_vector_map(vp)
        assert img.size == (vp.view_w, vp.view_h)
        # Memphis at 200mi range spans three states — outlines must be present
        colors = img.getcolors(maxcolors=100000)
        assert any(color != (0, 0, 0) and count > 10 for count, color in colors)


def make_fetcher(**kwargs):
    defaults = dict(map_style="vector", show_nowcast=True, past_frames=6)
    defaults.update(kwargs)
    return RadarFetcher(MEMPHIS[0], MEMPHIS[1], 50, None, **defaults)


def fake_index(num_past=13, num_nowcast=3):
    base = 1_750_000_000
    return {"radar": {
        "past": [{"path": f"/v2/radar/{base + i * 600}", "time": base + i * 600}
                 for i in range(num_past)],
        "nowcast": [{"path": f"/v2/radar/nowcast_h{i}", "time": base + (num_past + i) * 600}
                    for i in range(num_nowcast)],
    }}


class TestFrameSelection:
    def test_wanted_frames_past_plus_nowcast(self):
        f = make_fetcher()
        wanted = f._wanted_frames(fake_index())
        assert len(wanted) == 6 + 3
        assert sum(1 for _, _, nc in wanted if nc) == 3
        # past frames must be the newest six
        past_ts = [ts for _, ts, nc in wanted if not nc]
        assert past_ts == sorted(past_ts)
        assert past_ts[0] == fake_index()["radar"]["past"][-6]["time"]

    def test_wanted_frames_without_nowcast(self):
        f = make_fetcher(show_nowcast=False)
        wanted = f._wanted_frames(fake_index())
        assert len(wanted) == 6
        assert all(not nc for _, _, nc in wanted)

    def test_reconcile_keeps_built_images_and_drops_stale(self):
        f = make_fetcher()
        wanted = f._wanted_frames(fake_index())
        f._reconcile_frames(wanted)
        # mark one frame as built
        some_ts = wanted[2][1]
        f._frames[some_ts].image = Image.new("RGBA", (10, 10))
        # same frame list again: built image survives
        f._reconcile_frames(wanted)
        assert f._frames[some_ts].image is not None
        # a shifted window drops the oldest frame
        newer = fake_index(num_past=14)
        f._reconcile_frames(f._wanted_frames(newer))
        assert wanted[0][1] not in f._frames

    def test_reconcile_invalidates_frame_when_nowcast_path_rotates(self):
        f = make_fetcher()
        f._reconcile_frames(f._wanted_frames(fake_index()))
        nowcast_ts = [ts for ts, fr in f._frames.items() if fr.is_nowcast][0]
        f._frames[nowcast_ts].image = Image.new("RGBA", (10, 10))
        rotated = fake_index()
        for fr in rotated["radar"]["nowcast"]:
            fr["path"] = fr["path"] + "_regen"
        f._reconcile_frames(f._wanted_frames(rotated))
        assert f._frames[nowcast_ts].image is None

    def test_playback_order_is_chronological_with_nowcast_last(self):
        f = make_fetcher()
        f._reconcile_frames(f._wanted_frames(fake_index()))
        for fr in f._frames.values():
            fr.image = Image.new("RGBA", (10, 10))
        frames = f._playback_frames()
        assert [fr.ts for fr in frames] == sorted(fr.ts for fr in frames)
        assert not frames[0].is_nowcast
        assert frames[-1].is_nowcast


class TestRendering:
    def test_image_without_frames_uses_vector_fallback(self):
        f = make_fetcher()
        img = f.get_radar_image(128, 64)
        assert img is not None
        assert img.size == (128, 64)

    def test_image_with_frames_composites_and_overlays(self):
        f = make_fetcher()
        f._reconcile_frames(f._wanted_frames(fake_index()))
        vp = f._ensure_viewport(128, 64)
        for fr in f._frames.values():
            fr.image = Image.new("RGBA", (vp.view_w, vp.view_h), (0, 200, 0, 120))
        img = f.get_radar_image(128, 64)
        assert img is not None
        assert img.size == (128, 64)

    def test_all_panel_sizes_render(self):
        for pw, ph in PANEL_SIZES:
            f = make_fetcher()
            img = f.get_radar_image(pw, ph)
            assert img.size == (pw, ph)

    def test_panel_resize_invalidates_frames(self):
        f = make_fetcher()
        f._reconcile_frames(f._wanted_frames(fake_index()))
        vp = f._ensure_viewport(128, 64)
        for fr in f._frames.values():
            fr.image = Image.new("RGBA", (vp.view_w, vp.view_h))
        f._ensure_viewport(64, 32)
        assert all(fr.image is None for fr in f._frames.values())

    def test_loop_duration(self):
        f = make_fetcher(frame_seconds=0.5, loop_pause_seconds=1.5)
        f._reconcile_frames(f._wanted_frames(fake_index()))
        for fr in f._frames.values():
            fr.image = Image.new("RGBA", (10, 10))
        assert f.get_loop_duration() == pytest.approx(9 * 0.5 + 1.5)


class TestZoomBackCompat:
    """radar_zoom (deprecated) maps onto radar_range_miles equivalents."""
    ZOOM_TO_RANGE = {4: 200, 5: 100, 6: 50, 7: 25, 8: 12}

    def test_mapping_matches_manager(self):
        import re
        src = (Path(__file__).resolve().parent / "manager.py").read_text()
        match = re.search(r"_RADAR_ZOOM_TO_RANGE\s*=\s*\{([^}]*)\}", src)
        assert match, "manager.py must define _RADAR_ZOOM_TO_RANGE"
        parsed = dict(
            (int(k), int(v))
            for k, v in re.findall(r"(\d+)\s*:\s*(\d+)", match.group(1)))
        assert parsed == self.ZOOM_TO_RANGE

    def test_range_monotonic_in_zoom(self):
        ranges = [self.ZOOM_TO_RANGE[z] for z in sorted(self.ZOOM_TO_RANGE)]
        assert ranges == sorted(ranges, reverse=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
