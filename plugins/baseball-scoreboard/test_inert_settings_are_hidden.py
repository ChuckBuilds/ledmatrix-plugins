#!/usr/bin/env python3
"""
Tests that settings which cannot do anything here are not drawn as if they can.

A config form is a promise. Five settings in this schema broke it:

  * ``other_games_divisions`` -- FBS / FCS / Other, offered under MLB, MiLB and
    NCAA Baseball alike. ESPN publishes division rosters for college-football
    only (``sports.py _DIVISION_GROUPS_BY_LEAGUE``); every baseball league
    resolves nothing, the filter fails open, and no combination of boxes can
    change one game on the board.
  * ``other_games_min_quality`` on MLB and MiLB -- "ranked" needs a poll, and
    ``_league_has_rankings`` matches college leagues only, so it lets
    everything through and the setting has exactly one meaningful value.
  * ``show_ranking`` on MLB and MiLB -- worse than inert. The rank table is
    always empty there, and a rank badge *replaces* the record outright, so
    ticking it erased the records ``show_records`` was drawing.
  * ``scroll_delay`` -- its own description has said "ignored" for releases;
    it was still an editable number.
  * ``customization.layout.ranking`` -- no reader anywhere. The rank badge
    shares the records row and is positioned by ``layout.record``.

Each is now ``"x-display": "hidden"``: still declared, so a config that
already carries it keeps validating and nothing is lost on upgrade, but no
control is drawn for it. That mechanism is the core's
(``plugin_config.html`` ``prop_is_hidden`` / ``api_v3._is_hidden_prop``), not
this plugin's invention.

These checks pin the hiding, the code-side consequences that make it safe, and
-- as the other half of the same promise -- that the settings which DO work in
a league are still offered there.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_inert_settings_are_hidden.py
"""

# A test harness: it reaches into protected members on purpose.
# pylint: disable=protected-access,unused-argument,broad-exception-caught

import json
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402

SCHEMA = json.loads((plugin_dir / "config_schema.json").read_text("utf-8"))
LEAGUES = ("mlb", "milb", "ncaa_baseball")

failures = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    if not ok:
        failures.append(label)


def prop(path):
    """A schema property by dotted path, walking `properties` at each step."""
    node = SCHEMA
    for part in path.split("."):
        node = node["properties"][part]
    return node


def hidden(path):
    return prop(path).get("x-display") == "hidden"


def test_divisions_are_hidden_everywhere():
    print("FBS/FCS is a college FOOTBALL taxonomy -- inert in all three leagues")
    for league in LEAGUES:
        check("%s: other_games_divisions is hidden" % league,
              hidden("%s.game_limits.other_games_divisions" % league))
        check("%s: but still declared, so saved configs keep validating" % league,
              "other_games_divisions"
              in prop("%s.game_limits" % league)["properties"])

    check("the code agrees: division rosters exist for one league only",
          set(sports.SportsCore._DIVISION_GROUPS_BY_LEAGUE) == {"college-football"},
          set(sports.SportsCore._DIVISION_GROUPS_BY_LEAGUE))
    for league in ("mlb", "minor-league-baseball", "college-baseball"):
        check("%s has no division groups to look up" % league,
              league not in sports.SportsCore._DIVISION_GROUPS_BY_LEAGUE)


def test_poll_settings_hidden_on_every_league():
    print("\nrank-based settings: no baseball league has a poll, including NCAA")
    # NCAA Baseball was left visible in the first pass, on the reasonable-
    # sounding assumption that a college league must publish a poll. Measured
    # 2026-09-24: baseball/college-baseball/rankings answers 404 while
    # /scoreboard and /standings on the same slug answer 200, so the slug is
    # right and the endpoint is simply absent. Out of season is not the
    # explanation -- men's college lacrosse and hockey are equally out of
    # season and both answer 200 with real poll blocks.
    for league in LEAGUES:
        check("%s: show_ranking is hidden" % league,
              hidden("%s.display_options.show_ranking" % league))
        check("%s: other_games_min_quality is hidden" % league,
              hidden("%s.game_limits.other_games_min_quality" % league))

    check("no league defaults to 'ranked' any more",
          all(prop("%s.game_limits.other_games_min_quality" % lg).get("default")
              == "any" for lg in LEAGUES),
          {lg: prop("%s.game_limits.other_games_min_quality" % lg).get("default")
           for lg in LEAGUES})


def test_the_gate_matches_what_the_schema_claims():
    print("\nthe league gate is what makes hiding those correct")
    # A real subclass, not an ad-hoc object: the override calls super() to
    # reach the shared heuristic, so a stub that merely borrows the function
    # cannot run it. Abstract methods are stubbed from the class rather than
    # named, the way scripts/test_poll_choice.py does it; none is reached here.
    base = sports.SportsCore
    stubs = dict((name, lambda self, *a, **k: None)
                 for name in getattr(base, "__abstractmethods__", ()))
    probe_cls = type("RankingGateProbe", (base,), stubs)

    for league, expected in (("mlb", False),
                             ("minor-league-baseball", False),
                             # The measured exception: matches the shared
                             # "college" heuristic, has no /rankings endpoint.
                             ("college-baseball", False),
                             # Not baseball's, but proof the narrowing is a
                             # set membership and not a blanket "no college".
                             ("college-football", True),
                             ("mens-college-basketball", True),
                             (None, False)):
        probe = probe_cls.__new__(probe_cls)
        probe.league = league
        check("_league_has_rankings(%r) is %s" % (league, expected),
              probe._league_has_rankings() is expected)

    check("the exception names exactly one league",
          sports.SportsCore._NO_POLL_COLLEGE_LEAGUES == frozenset({"college-baseball"}),
          sports.SportsCore._NO_POLL_COLLEGE_LEAGUES)


def test_scroll_delay_is_hidden():
    print("\nscroll_delay: documented as ignored, now not drawn either")
    for league in LEAGUES:
        node = prop("%s.scroll_settings.scroll_delay" % league)
        check("%s: hidden" % league, node.get("x-display") == "hidden")
        check("%s: the description still says why" % league,
              "ignored" in node.get("description", "").lower())
        check("%s: scroll_speed is still offered" % league,
              not hidden("%s.scroll_settings.scroll_speed" % league))


def test_layout_ranking_is_hidden():
    print("\ncustomization.layout.ranking has no reader; record positions the badge")
    check("layout.ranking is hidden", hidden("customization.layout.ranking"))
    check("layout.record is not", not hidden("customization.layout.record"))
    check("and record's description now says it moves the rank badge too",
          "rank" in prop("customization.layout.record")
          .get("description", "").lower())
    for element in ("home_logo", "away_logo", "score", "date", "status", "odds"):
        check("layout.%s is still offered" % element,
              not hidden("customization.layout.%s" % element))


def test_hidden_props_carry_their_reason():
    print("\nevery hidden setting explains itself to whoever reads the schema next")
    found = []

    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        for key, value in (node.get("properties") or {}).items():
            where = "%s.%s" % (path, key) if path else key
            if isinstance(value, dict):
                if value.get("x-display") == "hidden":
                    found.append((where, value.get("description", "")))
                walk(value, where)

    walk(SCHEMA)
    check("something is actually hidden", bool(found))
    for where, description in found:
        check("%s says why" % where, "HIDDEN" in description, description[:60])


def test_nothing_else_got_hidden_by_accident():
    print("\nthe settings that work are still reachable")
    live = [
        "mlb.favorite_teams", "mlb.game_limits.recent_games_to_show",
        "mlb.display_options.show_records", "mlb.display_options.show_odds",
        "milb.sport_ids", "milb.favorite_teams",
        "ncaa_baseball.favorite_teams",
        "scroll_card.date_format", "scroll_card.recent_show_date",
        "scroll_card.recent_date_position",
        "scroll_card.switch_recent_show_date",
        "customization.favorite_result_colors.enabled",
    ]
    for path in live:
        try:
            check("%s is offered" % path, not hidden(path))
        except KeyError:
            check("%s is offered" % path, False, "not declared at all")


def main():
    test_divisions_are_hidden_everywhere()
    test_poll_settings_hidden_on_every_league()
    test_the_gate_matches_what_the_schema_claims()
    test_scroll_delay_is_hidden()
    test_layout_ranking_is_hidden()
    test_hidden_props_carry_their_reason()
    test_nothing_else_got_hidden_by_accident()

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
