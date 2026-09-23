#!/usr/bin/env python3
"""
Regression tests for the soccer goal-scorer card.

Soccer is the cheapest of these cards to feed: ESPN puts goal events straight
into the scoreboard payload the plugin already downloads, so identifying the
scorer costs no request. There is no headshot -- ESPN publishes none for
soccer -- so the card is text-only by design.

Covers:
  1. extract_goals: scorer off a real-shaped scoreboard detail, entries that
     name nobody, and non-scoring details (cards, subs).
  2. _goal_kind_badge / latest_goal: PEN/OG/SO badges, backward scan, team
     filtering.
  3. _build_goal_card_rows: rows from the scoreboard feed alone, enriched by
     the bio, both name spellings, and stat prioritisation.
  4. _prioritise_stats: goals and assists lead, unknown labels keep order.
  5. _fit_segments / _readable_on.
  6. The arming gate -- opt-in, its own score baseline (so the card works
     with the celebration switched off), its own favourites scope -- and the
     display window with and without a takeover.
  7. Render smoke across every harness size.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_goal_scorer_card.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from soccer_goal_card import (  # noqa: E402
    SoccerGoalCardMixin, _goal_kind_badge, _prioritise_stats, extract_goals,
    latest_goal)

# Shaped exactly like a real ESPN soccer scoreboard event.
_EVENT = {"competitions": [{"details": [
    {"type": {"id": "93", "text": "Yellow Card"}, "scoringPlay": False,
     "yellowCard": True, "athletesInvolved": [{"id": "1", "displayName": "Booked Player"}]},
    {"type": {"id": "70", "text": "Goal"},
     "clock": {"displayValue": "57'"}, "team": {"id": "364"},
     "scoreValue": 1, "scoringPlay": True,
     "penaltyKick": False, "ownGoal": False, "shootout": False,
     "athletesInvolved": [{
         "id": "235662", "displayName": "Alexander Isak",
         "fullName": "Alexander Isak", "shortName": "A. Isak",
         "jersey": "9", "position": {"abbreviation": "F"},
         "team": {"id": "364"}}]},
]}]}

_BIO = {
    "player_id": "235662", "display_name": "Alexander Isak", "jersey": "9",
    "position": "F", "height": "6' 3\"", "weight": "161 lbs", "age": 27,
    "birthplace": None, "headshot_url": None, "team_abbr": "LIV",
    "stat_pairs": [("START (SUB)", "5 (0)"), ("G", "4"), ("A", "0"), ("SHOT", "15")],
}


# --- 1. extraction -----------------------------------------------------------

def test_extract_goals_from_the_scoreboard_payload():
    """No summary request: the scorer rides along with data already fetched."""
    goals = extract_goals(_EVENT)
    assert len(goals) == 1, goals
    g = goals[0]
    assert g["scorer"]["name"] == "Alexander Isak"
    assert g["scorer"]["short_name"] == "A. Isak"
    assert g["scorer"]["jersey"] == "9" and g["scorer"]["position"] == "F"
    assert g["clock"] == "57'" and g["team_id"] == "364"
    assert g["badge"] is None and g["own_goal"] is False
    print("test_extract_goals_from_the_scoreboard_payload: PASS")


def test_extract_goals_skips_cards_and_nameless_entries():
    assert extract_goals({}) == []
    assert extract_goals({"competitions": [{}]}) == []
    # A goal ESPN flagged but filled in nobody for must not yield a blank card.
    nameless = {"competitions": [{"details": [
        {"scoringPlay": True, "athletesInvolved": []},
        {"scoringPlay": True, "athletesInvolved": [{"id": "9"}]},
    ]}]}
    assert extract_goals(nameless) == []
    print("test_extract_goals_skips_cards_and_nameless_entries: PASS")


def test_goal_kind_badges():
    assert _goal_kind_badge({"penaltyKick": True}) == "PEN"
    assert _goal_kind_badge({"ownGoal": True}) == "OG"
    assert _goal_kind_badge({"shootout": True}) == "SO"
    # An own goal from the spot is still, first, an own goal.
    assert _goal_kind_badge({"ownGoal": True, "penaltyKick": True}) == "OG"
    assert _goal_kind_badge({"penaltyKick": False, "ownGoal": False}) is None
    print("test_goal_kind_badges: PASS")


def test_latest_goal_scans_backwards_and_filters_by_team():
    a = {"team_id": "364", "scorer": {"name": "First"}}
    b = {"team_id": "999", "scorer": {"name": "Second"}}
    assert latest_goal([a, b])["scorer"]["name"] == "Second"
    assert latest_goal([a, b], "364")["scorer"]["name"] == "First"
    assert latest_goal([], "364") is None
    assert latest_goal(None) is None
    print("test_latest_goal_scans_backwards_and_filters_by_team: PASS")


# --- 2. stat prioritisation --------------------------------------------------

def test_prioritise_stats_leads_with_goals_and_assists():
    """ESPN leads its soccer stat set with appearances, which is the least
    interesting thing on a card about a goal and wide enough to be the only
    stat that fits on a narrow panel."""
    ordered = _prioritise_stats(_BIO["stat_pairs"])
    assert [k for k, _ in ordered] == ["G", "A", "SHOT", "START (SUB)"], ordered
    # Unrecognised labels keep their own order, behind the known ones.
    odd = _prioritise_stats([("XG", "1.2"), ("A", "3"), ("KP", "7")])
    assert [k for k, _ in odd] == ["A", "XG", "KP"], odd
    assert _prioritise_stats([]) == []
    print("test_prioritise_stats_leads_with_goals_and_assists: PASS")


# --- 3. card rows ------------------------------------------------------------

def _row(rows, key, sep="  "):
    return sep.join(rows[key])


def test_card_rows_from_the_scoreboard_alone():
    goal = dict(extract_goals(_EVENT)[0], team_abbr="LIV")
    rows = SoccerGoalCardMixin._build_goal_card_rows(goal)
    assert _row(rows, "header") == "LIV GOAL  57'", rows["header"]
    assert rows["name"] == ["Alexander Isak", "A. Isak"], rows["name"]
    # Shirt number and position come free with the goal event.
    assert _row(rows, "team", " ") == "#9 F", rows["team"]
    # No bio yet -> no stats or trivia at all, rather than empty labels.
    assert "stats" not in rows and "vitals" not in rows and "hometown" not in rows
    print("test_card_rows_from_the_scoreboard_alone: PASS")


def test_card_rows_enriched_by_the_bio():
    goal = dict(extract_goals(_EVENT)[0], team_abbr="LIV", bio=_BIO)
    rows = SoccerGoalCardMixin._build_goal_card_rows(goal)
    assert _row(rows, "stats") == "G 4  A 0  SHOT 15  START (SUB) 5 (0)", rows["stats"]
    assert _row(rows, "vitals") == "Age 27  6' 3\"  161 lbs", rows["vitals"]
    # ESPN has no birthplace for most soccer players; the row is simply absent.
    assert "hometown" not in rows
    print("test_card_rows_enriched_by_the_bio: PASS")


def test_card_rows_badge_reaches_the_banner():
    ev = {"competitions": [{"details": [dict(
        _EVENT["competitions"][0]["details"][1], penaltyKick=True)]}]}
    goal = dict(extract_goals(ev)[0], team_abbr="LIV")
    assert _row(SoccerGoalCardMixin._build_goal_card_rows(goal), "header") == \
        "LIV GOAL  57'  PEN"
    print("test_card_rows_badge_reaches_the_banner: PASS")


# --- 4. fitting + contrast ---------------------------------------------------

def test_fit_segments_drops_whole_fields():
    draw = ImageDraw.Draw(Image.new("RGB", (256, 64)))
    font = ImageFont.load_default()
    fit = SoccerGoalCardMixin._fit_segments
    segs = ["G 4", "A 0", "SHOT 15"]
    assert fit(draw, segs, font, 10_000) == "G 4  A 0  SHOT 15"
    two = draw.textbbox((0, 0), "G 4  A 0", font=font)[2]
    assert fit(draw, segs, font, two) == "G 4  A 0"
    assert fit(draw, segs, font, 1) == "G 4"
    assert fit(draw, [], font, 100) == ""
    print("test_fit_segments_drops_whole_fields: PASS")


def test_readable_on_flips_with_background_brightness():
    readable = SoccerGoalCardMixin._readable_on
    assert readable((35, 79, 135)) == (255, 255, 255)   # a navy club
    assert readable((251, 238, 35)) == (0, 0, 0)        # a yellow club
    print("test_readable_on_flips_with_background_brightness: PASS")


# --- 5. arming + window ------------------------------------------------------

from soccer_managers import SoccerLiveManager  # noqa: E402


_CELEBRATION = {
    "kind": "goal", "started_at": 1000.0, "scored_side": "home",
    "game": {"id": "g1", "home_id": "364", "home_abbr": "LIV",
             "goals": None},
}


def _make_arming_live(show=True, celebration=None, config=None,
                      favorite_teams=None):
    import logging
    live = object.__new__(SoccerLiveManager)
    live.show_goal_scorer = show
    live.active_celebration = celebration
    live._goal_card = None
    live._goal_card_baselines = {}
    live._player_bio_cache = {}
    live.live_games = []
    live.favorite_teams = favorite_teams or []
    live.config = config or {}
    live.celebration_duration = 8
    live.logger = logging.getLogger("t")
    live.cache_manager = None
    fetched = []
    live._fetch_player_bio_async = lambda pid, goal: fetched.append(pid)
    return live, fetched


def _fixture(away=0, home=0, game_id="g1", goals=None):
    return {"id": game_id, "away_score": str(away), "home_score": str(home),
            "away_id": "999", "home_id": "364",
            "away_abbr": "NEW", "home_abbr": "LIV",
            "goals": goals if goals is not None else extract_goals(_EVENT)}


def _run_update(live):
    import soccer_managers
    real = soccer_managers.SportsLive.update
    soccer_managers.SportsLive.update = lambda self: None
    try:
        SoccerLiveManager.update(live)
    finally:
        soccer_managers.SportsLive.update = real


def test_arming_requires_the_opt_in():
    live, fetched = _make_arming_live(show=False)
    live.live_games = [_fixture()]
    _run_update(live)
    live.live_games = [_fixture(home=1)]
    _run_update(live)
    assert live._goal_card is None and fetched == []
    print("test_arming_requires_the_opt_in: PASS")


def test_card_does_not_need_the_celebration():
    """The whole point of the two settings being separate: with the takeover
    off, SportsLive._check_for_goal returns early and never arms a
    celebration, so a card riding on active_celebration could never appear."""
    import time as _t
    real = _t.time
    try:
        _t.time = lambda: 1000.0
        live, fetched = _make_arming_live(celebration=None)
        live.live_games = [_fixture()]
        _run_update(live)                       # first sighting: baseline only
        assert live._goal_card is None
        live.live_games = [_fixture(home=1)]
        _run_update(live)
        card = live._goal_card
        assert card is not None, "expected a card with no celebration at all"
        assert card["scorer"]["name"] == "Alexander Isak"
        # No takeover to wait for -- the card is the only beat.
        assert card["show_from"] == 1000.0 and card["show_until"] == 1006.0
        assert fetched == ["235662"]
    finally:
        _t.time = real
    print("test_card_does_not_need_the_celebration: PASS")


def test_card_waits_when_a_celebration_is_running():
    import time as _t
    real = _t.time
    try:
        _t.time = lambda: 1000.0
        live, fetched = _make_arming_live(celebration=dict(_CELEBRATION))
        live.live_games = [_fixture()]
        _run_update(live)
        live.live_games = [_fixture(home=1)]
        _run_update(live)
        card = live._goal_card
        assert card["show_from"] == 1008.0 and card["show_until"] == 1014.0, card
        # Resolving the scorer costs no request; only the bio does.
        assert fetched == ["235662"]
    finally:
        _t.time = real
    print("test_card_waits_when_a_celebration_is_running: PASS")


def test_first_sighting_never_fires():
    live, fetched = _make_arming_live()
    live.live_games = [_fixture(away=2, home=1)]
    _run_update(live)
    assert live._goal_card is None and fetched == []
    print("test_first_sighting_never_fires: PASS")


def test_a_var_disallowed_goal_rebases_silently():
    live, fetched = _make_arming_live()
    live.live_games = [_fixture(home=1)]
    _run_update(live)
    live.live_games = [_fixture(home=0)]    # ruled out by VAR
    _run_update(live)
    assert live._goal_card is None and fetched == []
    live.live_games = [_fixture(home=1)]    # scored again for real
    _run_update(live)
    assert live._goal_card is not None
    print("test_a_var_disallowed_goal_rebases_silently: PASS")


def test_arming_fires_once_per_goal():
    live, fetched = _make_arming_live()
    live.live_games = [_fixture()]
    _run_update(live)
    live.live_games = [_fixture(home=1)]
    _run_update(live)
    _run_update(live)
    _run_update(live)
    assert len(fetched) == 1, fetched
    print("test_arming_fires_once_per_goal: PASS")


def test_favorites_only_is_the_cards_own_scope():
    cfg = {"customization": {"goal_scorer": {"favorites_only": True}}}
    live, fetched = _make_arming_live(config=cfg, favorite_teams=["LIV"])
    live.live_games = [_fixture()]
    _run_update(live)
    live.live_games = [_fixture(away=1)]    # the opponent scored
    _run_update(live)
    assert live._goal_card is None, "expected favorites_only to skip an opponent goal"
    live.live_games = [_fixture(away=1, home=1)]
    _run_update(live)
    assert live._goal_card is not None
    print("test_favorites_only_is_the_cards_own_scope: PASS")


def test_baselines_are_pruned_when_a_fixture_ends():
    live, _ = _make_arming_live()
    live.live_games = [_fixture(game_id="g1"), _fixture(game_id="g2")]
    _run_update(live)
    assert set(live._goal_card_baselines) == {"g1", "g2"}
    live.live_games = [_fixture(game_id="g1")]
    _run_update(live)
    assert set(live._goal_card_baselines) == {"g1"}
    print("test_baselines_are_pruned_when_a_fixture_ends: PASS")


def test_arming_skips_when_nobody_is_named():
    """Some leagues file a goal with no athletesInvolved. No card, rather
    than a card with a blank name."""
    live, fetched = _make_arming_live()
    live.live_games = [_fixture(goals=[])]
    _run_update(live)
    live.live_games = [_fixture(home=1, goals=[])]
    _run_update(live)
    assert live._goal_card is None and fetched == []
    print("test_arming_skips_when_nobody_is_named: PASS")


def _make_window_live(card):
    live = object.__new__(SoccerLiveManager)
    live.show_goal_scorer = True
    live._goal_card = card
    drawn = []
    live._draw_goal_card = lambda c, force_clear=False: drawn.append(c)
    return live, drawn


def test_card_waits_for_the_celebration_then_expires():
    import time as _t
    real = _t.time
    try:
        card = {"game_id": "g1", "show_from": 100.0, "show_until": 110.0}
        live, drawn = _make_window_live(card)
        _t.time = lambda: 99.0
        assert live._maybe_draw_goal_card({"id": "g1"}) is False
        _t.time = lambda: 105.0
        assert live._maybe_draw_goal_card({"id": "g1"}) is True and len(drawn) == 1
        _t.time = lambda: 111.0
        assert live._maybe_draw_goal_card({"id": "g1"}) is False
        assert live._goal_card is None
        # Never over another fixture.
        live, drawn = _make_window_live(dict(card))
        _t.time = lambda: 105.0
        assert live._maybe_draw_goal_card({"id": "g2"}) is False and drawn == []
    finally:
        _t.time = real
    print("test_card_waits_for_the_celebration_then_expires: PASS")


# --- 6. render smoke ---------------------------------------------------------

class _DisplayManager:
    def __init__(self, width, height):
        self.image = Image.new("RGB", (width, height))

    def update_display(self):
        pass


_SIZES = ((64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32),
          (128, 96), (256, 128), (256, 64), (512, 64))


def _make_render_live(width, height, config=None):
    import logging
    live = object.__new__(SoccerLiveManager)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.config = config or {}
    live.show_goal_scorer = True
    live.logger = logging.getLogger("test_soccer_goal_card")
    # Pillow >= 11's load_default() returns a scalable fallback whose textbbox
    # under-reports its own ink, which would fail the margin assertion on the
    # stub rather than on the plugin. Prefer the honest bitmap font.
    loader = getattr(ImageFont, "load_default_imagefont", ImageFont.load_default)
    font = loader()
    live._load_custom_font_from_element_config = lambda cfg, default_size=6: font
    return live


def _assert_clean(live, w, h, label):
    img = live.display_manager.image
    clipped = any(img.getpixel((x, y)) != (0, 0, 0)
                  for x in (0, w - 1) for y in range(h))
    assert not clipped, f"{label}: drew into a margin column at {w}x{h}"
    assert any(img.getpixel((x, y)) != (0, 0, 0)
               for x in range(w) for y in range(h)), f"{label}: nothing drawn at {w}x{h}"


def _full_goal():
    return dict(extract_goals(_EVENT)[0], team_abbr="LIV",
                team_color=(35, 79, 135), game_id="g1", bio=_BIO)


def test_render_all_sizes_no_overflow():
    goal = _full_goal()
    for w, h in _SIZES:
        live = _make_render_live(w, h)
        live._draw_goal_card(goal)
        _assert_clean(live, w, h, "full")
    print("test_render_all_sizes_no_overflow: PASS")


def test_render_scoreboard_only_no_crash():
    """The commonest first frame: armed from the feed, bio not back yet."""
    goal = dict(extract_goals(_EVENT)[0], team_abbr="LIV", game_id="g1")
    for w, h in _SIZES:
        live = _make_render_live(w, h)
        live._draw_goal_card(goal)
        _assert_clean(live, w, h, "feed-only")
    print("test_render_scoreboard_only_no_crash: PASS")


def test_render_toggles_off_still_draws():
    cfg = {"customization": {"goal_scorer": {
        "show_stats": False, "show_bio_details": False,
        "header_bar": False, "use_team_colors": False}}}
    goal = _full_goal()
    for w, h in _SIZES:
        live = _make_render_live(w, h, config=cfg)
        live._draw_goal_card(goal)
        _assert_clean(live, w, h, "toggles-off")
    print("test_render_toggles_off_still_draws: PASS")


if __name__ == "__main__":
    print("soccer goal-scorer card tests")
    print("=" * 60)
    tests = [
        test_extract_goals_from_the_scoreboard_payload,
        test_extract_goals_skips_cards_and_nameless_entries,
        test_goal_kind_badges,
        test_latest_goal_scans_backwards_and_filters_by_team,
        test_prioritise_stats_leads_with_goals_and_assists,
        test_card_rows_from_the_scoreboard_alone,
        test_card_rows_enriched_by_the_bio,
        test_card_rows_badge_reaches_the_banner,
        test_fit_segments_drops_whole_fields,
        test_readable_on_flips_with_background_brightness,
        test_arming_requires_the_opt_in,
        test_card_does_not_need_the_celebration,
        test_card_waits_when_a_celebration_is_running,
        test_first_sighting_never_fires,
        test_a_var_disallowed_goal_rebases_silently,
        test_arming_fires_once_per_goal,
        test_favorites_only_is_the_cards_own_scope,
        test_baselines_are_pruned_when_a_fixture_ends,
        test_arming_skips_when_nobody_is_named,
        test_card_waits_for_the_celebration_then_expires,
        test_render_all_sizes_no_overflow,
        test_render_scoreboard_only_no_crash,
        test_render_toggles_off_still_draws,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures += 1
            print(f"{t.__name__}: FAIL -- {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"{t.__name__}: ERROR -- {e}")
    print("=" * 60)
    print("ALL TESTS PASSED" if failures == 0 else f"{failures} TEST(S) FAILED")
    sys.exit(1 if failures else 0)
