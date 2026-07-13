"""
Unit tests for the Cricket Scoreboard plugin.

Focus areas:
  * base-6 overs -> decimal overs conversion (the easy-to-get-wrong bit)
  * current/required run-rate math
  * renderer smoke tests for every format branch (live T20, live Test,
    recent, upcoming) using the mocked responses in test/harness.json
  * manager update/display smoke test with mock display + cache managers

Run:  python -m unittest test_cricket_plugin  (needs Pillow + requests)
"""

import json
import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from cricket_data_fetcher import (  # noqa: E402
    CricketDataFetcher,
    overs_to_decimal,
    overs_to_balls,
    current_run_rate,
    required_run_rate,
)


def _load_mock_matches():
    with open(_HERE / "test" / "harness.json", "r", encoding="utf-8") as f:
        return json.load(f)["mock_matches"]


class TestOversMath(unittest.TestCase):
    """Base-6 fractional overs conversion and run-rate math."""

    def test_18_4_overs_is_18_667_decimal(self):
        # 18.4 overs = 18 completed overs + 4 balls = 18 + 4/6 decimal overs.
        self.assertAlmostEqual(overs_to_decimal(18.4), 18 + 4 / 6, places=4)
        self.assertAlmostEqual(overs_to_decimal(18.4), 18.6667, places=4)

    def test_whole_overs_unchanged(self):
        self.assertAlmostEqual(overs_to_decimal(20.0), 20.0, places=6)
        self.assertEqual(overs_to_decimal(0.0), 0.0)

    def test_each_ball_is_one_sixth(self):
        for balls in range(6):
            self.assertAlmostEqual(overs_to_decimal(12 + balls / 10.0),
                                   12 + balls / 6.0, places=4)

    def test_float_noise_tolerant(self):
        # 18.399999 should still resolve to 4 balls, not 3.
        self.assertAlmostEqual(overs_to_decimal(18.399999), 18 + 4 / 6, places=4)

    def test_malformed_fraction_rolls_over(self):
        # A ".6" fraction is illegal (max 5 balls) -> roll into the next over.
        self.assertAlmostEqual(overs_to_decimal(4.6), 5.0, places=4)

    def test_overs_to_balls(self):
        self.assertEqual(overs_to_balls(18.4), 18 * 6 + 4)
        self.assertEqual(overs_to_balls(20.0), 120)
        self.assertEqual(overs_to_balls(0.0), 0)

    def test_current_run_rate(self):
        # 122 runs off 13.0 overs -> 9.3846 rpo.
        crr = current_run_rate(122, 13.0)
        self.assertAlmostEqual(crr, 122 / 13.0, places=4)
        # 100 runs off 18.4 overs uses decimal overs, NOT 18.4.
        crr2 = current_run_rate(100, 18.4)
        self.assertAlmostEqual(crr2, 100 / (18 + 4 / 6), places=4)
        # No overs bowled -> undefined.
        self.assertIsNone(current_run_rate(0, 0.0))

    def test_required_run_rate(self):
        # Chase: need 34 off 42 balls -> 34 / (42/6) = 4.857 rpo.
        rrr = required_run_rate(34, 42)
        self.assertAlmostEqual(rrr, 34 / (42 / 6.0), places=4)
        self.assertAlmostEqual(rrr, 4.8571, places=3)
        # No balls left -> undefined.
        self.assertIsNone(required_run_rate(10, 0))

    def test_parse_max_overs_and_target(self):
        self.assertEqual(
            CricketDataFetcher.parse_max_overs("161/5 (18/20 ov, target 156)", "T20"),
            20,
        )
        # Falls back to format default when no "x/y ov" hint.
        self.assertEqual(CricketDataFetcher.parse_max_overs("300/6", "ODI"), 50)
        target = CricketDataFetcher._parse_target(
            [{"score_str": "122/4 (13/20 ov, target 156)"}])
        self.assertEqual(target, 156)


class TestFormatNormalization(unittest.TestCase):
    def test_formats(self):
        n = CricketDataFetcher._normalize_format
        self.assertEqual(n("T20"), "T20")
        self.assertEqual(n("Twenty20"), "T20")
        self.assertEqual(n("T20I"), "T20I")
        self.assertEqual(n("ODI"), "ODI")
        self.assertEqual(n("Test"), "Test")
        self.assertEqual(n("First-class"), "First-class")
        self.assertEqual(n(""), "T20")  # defensive default


class TestRenderer(unittest.TestCase):
    """Every format branch must render to a correctly-sized image."""

    def setUp(self):
        from cricket_renderer import CricketRenderer
        self.matches = {m["id"]: m for m in _load_mock_matches()}
        self.renderer = CricketRenderer(128, 32, {"show_venue": True})

    def _check(self, image):
        from PIL import Image
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(image.size, (128, 32))

    def test_live_limited_overs(self):
        self._check(self.renderer.render_live_limited_overs(self.matches["live-t20"]))

    def test_live_test(self):
        self._check(self.renderer.render_live_test(self.matches["live-test"]))

    def test_recent(self):
        self._check(self.renderer.render_recent(self.matches["recent-t20"]))

    def test_upcoming(self):
        self._check(self.renderer.render_upcoming(self.matches["upcoming-t20i"]))

    def test_all_sizes(self):
        from cricket_renderer import CricketRenderer
        for size in [(64, 32), (128, 32), (128, 64), (256, 32)]:
            r = CricketRenderer(size[0], size[1], {})
            img = r.render_live_limited_overs(self.matches["live-t20"])
            self.assertEqual(img.size, size)


class _MockMatrix:
    def __init__(self, w, h):
        self.width = w
        self.height = h


class _MockDisplayManager:
    def __init__(self, w=128, h=32):
        from PIL import Image
        self.matrix = _MockMatrix(w, h)
        self.image = Image.new("RGB", (w, h), (0, 0, 0))
        self.updated = False

    def clear(self):
        from PIL import Image
        self.image = Image.new("RGB", (self.matrix.width, self.matrix.height), (0, 0, 0))

    def update_display(self):
        self.updated = True


class _MockCacheManager:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


class TestManager(unittest.TestCase):
    def _make_plugin(self):
        from manager import CricketScoreboardPlugin
        cfg = _load_harness_config()
        dm = _MockDisplayManager()
        plugin = CricketScoreboardPlugin("cricket-scoreboard", cfg, dm,
                                         _MockCacheManager(), None)
        # Inject mocked matches directly, bypassing the network fetcher.
        matches = _load_mock_matches()
        plugin.live_matches = [m for m in matches if m["state"] == "in"]
        plugin.recent_matches = [m for m in matches if m["state"] == "post"]
        plugin.upcoming_matches = [m for m in matches if m["state"] == "pre"]
        return plugin, dm

    def test_display_live(self):
        plugin, dm = self._make_plugin()
        self.assertTrue(plugin.display("cricket_live", force_clear=True))
        self.assertTrue(dm.updated)

    def test_display_recent_and_upcoming(self):
        plugin, dm = self._make_plugin()
        self.assertTrue(plugin.display("cricket_recent"))
        self.assertTrue(plugin.display("cricket_upcoming"))

    def test_live_priority_and_content(self):
        plugin, _ = self._make_plugin()
        self.assertTrue(plugin.has_live_priority())
        self.assertTrue(plugin.has_live_content())
        self.assertEqual(plugin.get_live_modes(), ["cricket_live"])

    def test_vegas_hooks(self):
        plugin, _ = self._make_plugin()
        self.assertEqual(plugin.get_vegas_content_type(), "multi")
        cards = plugin.get_vegas_content()
        self.assertTrue(cards and len(cards) >= 4)

    def test_get_cycle_duration(self):
        plugin, _ = self._make_plugin()
        self.assertGreater(plugin.get_cycle_duration("cricket_recent"), 0)

    def test_validate_config(self):
        plugin, _ = self._make_plugin()
        self.assertTrue(plugin.validate_config())


def _load_harness_config():
    with open(_HERE / "test" / "harness.json", "r", encoding="utf-8") as f:
        return json.load(f)["config"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
