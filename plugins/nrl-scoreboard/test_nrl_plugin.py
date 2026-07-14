"""
Self-contained smoke tests for the NRL Scoreboard plugin.

These validate the plugin's static artifacts (manifest, config schema, test
harness) and the invariants that are easy to break during maintenance — most
importantly that the ESPN NRL league slug stays the literal "3" and is never
"fixed" to "nrl". They intentionally avoid importing manager.py / nrl_managers.py
directly, because those pull in the main LEDMatrix `src.*` packages that only
exist inside a full LEDMatrix checkout. Run with: python3 test_nrl_plugin.py
"""

import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as f:
        return json.load(f)


class TestManifest(unittest.TestCase):
    def test_manifest_fields(self):
        m = _load("manifest.json")
        self.assertEqual(m["id"], "nrl-scoreboard")
        self.assertEqual(m["class_name"], "NrlScoreboardPlugin")
        self.assertEqual(m["entry_point"], "manager.py")
        self.assertEqual(m["category"], "sports")
        self.assertEqual(
            m["display_modes"], ["nrl_live", "nrl_recent", "nrl_upcoming"]
        )
        self.assertIn("nrl", m["tags"])
        self.assertIn("rugby-league", m["tags"])
        self.assertEqual(m["config_schema"], "config_schema.json")


class TestConfigSchema(unittest.TestCase):
    def test_schema_parses_and_core_fields(self):
        s = _load("config_schema.json")
        self.assertEqual(s["type"], "object")
        self.assertFalse(s["additionalProperties"])
        props = s["properties"]
        for key in (
            "enabled",
            "favorite_teams",
            "exclude_teams",
            "display_modes",
            "live_priority",
            "live_game_duration",
            "recent_game_duration",
            "upcoming_game_duration",
            "dynamic_duration",
            "mode_durations",
            "celebration_enabled",
            "background_service",
        ):
            self.assertIn(key, props, f"missing schema field: {key}")
        # customization block is a root-level sibling (parity with soccer)
        self.assertIn("customization", s)
        # display_modes toggles use live/recent/upcoming (not nrl_-prefixed)
        dm = props["display_modes"]["properties"]
        for key in ("live", "recent", "upcoming",
                    "live_display_mode", "recent_display_mode", "upcoming_display_mode"):
            self.assertIn(key, dm)

    def test_no_soccer_leftovers(self):
        blob = json.dumps(_load("config_schema.json"))
        for bad in ("soccer", "Soccer", "Premier League", "La Liga", "eng.1"):
            self.assertNotIn(bad, blob, f"leftover soccer reference: {bad}")


class TestLeagueSlug(unittest.TestCase):
    def test_slug_is_three_not_nrl(self):
        """ESPN's NRL league slug is the literal '3' — guard against a rename."""
        with open(os.path.join(HERE, "nrl_managers.py"), "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn('NRL_LEAGUE_SLUG = "3"', src)
        self.assertIn("rugby-league", src)
        # The scoreboard URL must resolve to .../rugby-league/3/scoreboard
        self.assertIn("apis/site/v2/sports/rugby-league", src)


class TestHarness(unittest.TestCase):
    def test_harness_has_live_recent_upcoming(self):
        h = _load("test/harness.json")
        events = h["mock_data"]["events"]
        states = {e["competitions"][0]["status"]["type"]["state"] for e in events}
        self.assertEqual(states, {"in", "post", "pre"})
        # league slug in mock must be "3"
        self.assertEqual(h["mock_data"]["leagues"][0]["slug"], "3")


class TestPeriodMapping(unittest.TestCase):
    """Replicates the NRL period_text mapping to lock in the two-halves model."""

    @staticmethod
    def period_text(state, period, name="", clock=""):
        if state == "halftime" or name == "STATUS_HALFTIME":
            text = "HALF"
        elif state == "in":
            text = {0: "Start", 1: "1H", 2: "2H"}.get(period)
            if text is None:
                text = "ET" if period >= 3 else f"P{period}"
        elif state == "post":
            text = "Final"
        else:
            text = ""
        if clock and state == "in":
            text = f"{text} {clock}" if text else clock
        return text

    def test_mappings(self):
        self.assertEqual(self.period_text("in", 1, clock="20'"), "1H 20'")
        self.assertEqual(self.period_text("in", 2, clock="52'"), "2H 52'")
        self.assertEqual(self.period_text("in", 3, clock="83'"), "ET 83'")
        self.assertEqual(self.period_text("in", 0), "Start")
        self.assertEqual(self.period_text("post", 2), "Final")
        self.assertEqual(self.period_text("in", 2, name="STATUS_HALFTIME"), "HALF")
        # NRL uses halves, never quarters
        self.assertNotIn("Q", self.period_text("in", 1, clock="20'"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
