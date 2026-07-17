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
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dynamic_team_resolver import DynamicTeamResolver  # noqa: E402


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
        # mock_data is a path (relative to the plugin dir) to the fixture
        # file, per the plugin safety harness convention - not inline data.
        self.assertIsInstance(h["mock_data"], str)
        mock = _load(h["mock_data"])
        events = mock["events"]
        states = {e["competitions"][0]["status"]["type"]["state"] for e in events}
        self.assertEqual(states, {"in", "post", "pre"})
        # league slug in mock must be "3"
        self.assertEqual(mock["leagues"][0]["slug"], "3")


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


def _mock_teams_response():
    """Minimal ESPN teams payload with a real collision: "NEW" is shared by
    Newcastle Knights and New Zealand Warriors, "CAN" by Canberra Raiders and
    Canterbury Bulldogs."""
    def team(team_id, abbr, display_name):
        return {
            "team": {
                "id": team_id,
                "abbreviation": abbr,
                "displayName": display_name,
                "shortDisplayName": display_name.split()[-1],
                "name": display_name.split()[-1],
                "location": " ".join(display_name.split()[:-1]),
            }
        }

    teams = [
        team("1", "NEW", "Newcastle Knights"),
        team("2", "NEW", "New Zealand Warriors"),
        team("3", "CAN", "Canberra Raiders"),
        team("4", "CAN", "Canterbury Bulldogs"),
        team("5", "BRI", "Brisbane Broncos"),
    ]
    return {"sports": [{"leagues": [{"teams": teams}]}]}


class TestDynamicTeamResolverAbbreviationCollisions(unittest.TestCase):
    """Locks in the fix for the reported bug: NRL has duplicate abbreviations
    ("NEW", "CAN") that must not be silently conflated. Favorite/exclude
    matching must resolve to unique ESPN team IDs, not abbreviations."""

    def setUp(self):
        # Each test gets a clean class-level cache.
        DynamicTeamResolver._teams_index_cache = {}
        DynamicTeamResolver._teams_index_timestamp = {}
        self.resolver = DynamicTeamResolver()
        self.get_patcher = mock.patch(
            "dynamic_team_resolver.requests.get",
            return_value=mock.Mock(
                status_code=200,
                json=lambda: _mock_teams_response(),
                raise_for_status=lambda: None,
            ),
        )
        self.get_patcher.start()
        self.addCleanup(self.get_patcher.stop)

    def test_ambiguous_abbreviation_is_not_silently_resolved(self):
        # "NEW" matches two teams - must not resolve to either one's ID.
        resolved = self.resolver.resolve_teams(["NEW"], sport="nrl")
        self.assertEqual(resolved, ["NEW"])
        self.assertNotIn(resolved[0], {"1", "2"})

        resolved = self.resolver.resolve_teams(["CAN"], sport="nrl")
        self.assertEqual(resolved, ["CAN"])
        self.assertNotIn(resolved[0], {"3", "4"})

    def test_full_team_name_disambiguates(self):
        self.assertEqual(
            self.resolver.resolve_teams(["Newcastle Knights"], sport="nrl"), ["1"]
        )
        self.assertEqual(
            self.resolver.resolve_teams(["New Zealand Warriors"], sport="nrl"), ["2"]
        )
        self.assertEqual(
            self.resolver.resolve_teams(["Canberra Raiders"], sport="nrl"), ["3"]
        )
        self.assertEqual(
            self.resolver.resolve_teams(["Canterbury Bulldogs"], sport="nrl"), ["4"]
        )

    def test_unique_abbreviation_still_resolves(self):
        self.assertEqual(self.resolver.resolve_teams(["BRI"], sport="nrl"), ["5"])

    def test_numeric_team_id_passes_through(self):
        self.assertEqual(self.resolver.resolve_teams(["5"], sport="nrl"), ["5"])

    def test_fetch_failure_falls_back_to_raw_value(self):
        DynamicTeamResolver._teams_index_cache = {}
        DynamicTeamResolver._teams_index_timestamp = {}
        with mock.patch(
            "dynamic_team_resolver.requests.get", side_effect=Exception("boom")
        ):
            resolved = self.resolver.resolve_teams(["Brisbane Broncos"], sport="nrl")
        self.assertEqual(resolved, ["Brisbane Broncos"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
