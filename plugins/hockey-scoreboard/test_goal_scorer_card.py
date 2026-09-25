#!/usr/bin/env python3
"""
Regression tests for the goal-scorer card in hockey.py.

Hockey's celebration is armed from a score delta on the scoreboard feed, so it
knows a goal happened and which team scored but never who. The card is a
second lookup, made while the celebration is on screen and drawn in the
seconds after it clears.

Covers:
  1. _extract_goal / _latest_goal: scorer and assisters off a real-shaped ESPN
     play, team filtering, and plays that name nobody.
  2. _goal_strength_badge: PP/SH/EN, and nothing at even strength.
  3. _build_goal_card_rows: rows from the play alone, enriched by the bio, and
     both name spellings offered to the renderer.
  4. _fit_segments / _readable_on: whole fields dropped, banner contrast.
  5. ESPNDataSource._parse_player_details: the hockey bio fields the card uses.
  6. The arming gate: opt-in, NHL-only, once per goal, its own score
     baseline (so the card works with the celebration switched off), its own
     favourites scope, and the window it claims with and without a takeover.
  7. _maybe_draw_goal_card: the window it owns, and the game it belongs to.
  8. Render smoke across every harness size, plus the headshot-cache bounds
     carried over from the baseball card.
  9. Team colour: _team_color's choice and clamping, and the colour carried
     from a real-shaped ESPN event through _extract_game_details and
     _resolve_goal_scorer onto the drawn card.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_goal_scorer_card.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from data_sources import ESPNDataSource  # noqa: E402
from hockey import (  # noqa: E402
    HockeyLive, _extract_goal, _goal_strength_badge, _latest_goal, _team_color)


class _ConcreteHockeyLive(HockeyLive):
    def _extract_game_details(self, game_event):
        return None

    def _fetch_data(self):
        return None


# Shaped exactly like a real ESPN NHL scoring play.
_PLAY = {
    "id": "401879359000090280",
    "type": {"text": "Goal", "abbreviation": "goal"},
    "text": "Jonny Brodzinski Goal (3) , assists: Martin Fehervary (1)",
    "scoringPlay": True,
    "awayScore": 2, "homeScore": 5,
    "period": {"number": 3, "displayValue": "3rd"},
    "clock": {"displayValue": "9:45"},
    "team": {"id": "23"},
    "strength": {"text": "Shorthanded", "abbreviation": "short-handed"},
    "participants": [
        {"type": "scorer", "ytdGoals": 3, "athlete": {
            "id": "3025614", "displayName": "Jonny Brodzinski",
            "shortName": "J. Brodzinski",
            "headshot": {"href": "https://a.espncdn.com/i/headshots/nhl/players/full/3025614.png"}}},
        {"type": "assister", "ytdAssists": 1, "athlete": {
            "id": "4378677", "displayName": "Martin Fehervary",
            "shortName": "M. Fehervary"}},
        {"type": "assister", "ytdAssists": 1, "athlete": {
            "id": "4697454", "displayName": "Theodor Niederbach",
            "shortName": "T. Niederbach"}},
    ],
}

_BIO = {
    "player_id": "3025614", "display_name": "Jonny Brodzinski", "jersey": "76",
    "position": "C", "height": "6' 0\"", "weight": "211 lbs", "age": 33,
    "birthplace": "Ham Lake, MN", "experience": "7th Season",
    "headshot_url": None, "team_abbr": "WSH",
    "stat_pairs": [("G", "6"), ("A", "10"), ("PTS", "16"), ("+/-", "-1")],
}


# --- 1. play extraction ------------------------------------------------------

def test_extract_goal_reads_scorer_and_assists():
    goal = _extract_goal(_PLAY)
    assert goal["scorer"]["name"] == "Jonny Brodzinski"
    assert goal["scorer"]["short_name"] == "J. Brodzinski"
    assert goal["scorer"]["season_goals"] == 3
    # The headshot URL rides along with the play -- no roster join needed.
    assert goal["scorer"]["headshot_url"].endswith("3025614.png")
    assert [a["short_name"] for a in goal["assists"]] == [
        "M. Fehervary", "T. Niederbach"]
    assert goal["period"] == "3rd" and goal["clock"] == "9:45"
    assert goal["strength"] == "SH" and goal["team_id"] == "23"
    print("test_extract_goal_reads_scorer_and_assists: PASS")


def test_extract_goal_none_when_nobody_named():
    """An own goal, or a feed that filled in the text and not the
    participants, must not produce a card with a blank name."""
    assert _extract_goal({"scoringPlay": True, "text": "Goal"}) is None
    assert _extract_goal({"participants": [{"type": "assister",
                                            "athlete": {"id": "1", "displayName": "A"}}]}) is None
    print("test_extract_goal_none_when_nobody_named: PASS")


def test_latest_goal_scans_backwards_and_filters_by_team():
    other = dict(_PLAY, id="x", team={"id": "99"},
                 participants=[{"type": "scorer", "athlete": {
                     "id": "9", "displayName": "Someone Else"}}])
    plays = [_PLAY, other, {"scoringPlay": False, "text": "Hooking"}]
    # Newest overall is the other team's goal...
    assert _latest_goal(plays)["scorer"]["name"] == "Someone Else"
    # ...but the card is armed off a score delta, so it asks by team.
    assert _latest_goal(plays, "23")["scorer"]["name"] == "Jonny Brodzinski"
    assert _latest_goal([], "23") is None
    assert _latest_goal(None) is None
    print("test_latest_goal_scans_backwards_and_filters_by_team: PASS")


# --- 2. strength badge -------------------------------------------------------

def test_goal_strength_badge():
    assert _goal_strength_badge(_PLAY) == "SH"
    assert _goal_strength_badge({"strength": {"abbreviation": "power-play"}}) == "PP"
    assert _goal_strength_badge({"strength": {"text": "Empty net"}}) == "EN"
    # Even strength is the default state; saying so would waste the slot.
    assert _goal_strength_badge({"strength": {"abbreviation": "even", "text": "Even"}}) is None
    assert _goal_strength_badge({}) is None
    print("test_goal_strength_badge: PASS")


# --- 3. card rows ------------------------------------------------------------

def _row(rows, key, sep="  "):
    return sep.join(rows[key])


def test_card_rows_from_the_play_alone():
    """Before the bio lands the card is still worth drawing: the play knows
    the banner, the name and how many the scorer has this season."""
    goal = _extract_goal(_PLAY)
    goal["team_abbr"] = "WSH"
    rows = _ConcreteHockeyLive._build_goal_card_rows(goal)
    assert _row(rows, "header") == "WSH GOAL  3rd 9:45  SH", rows["header"]
    assert rows["name"] == ["Jonny Brodzinski", "J. Brodzinski"], rows["name"]
    assert _row(rows, "stats") == "G 3", rows["stats"]
    assert _row(rows, "assists") == "A: M. Fehervary  T. Niederbach", rows["assists"]
    # No bio yet -> no number/position or trivia rows at all, rather than blanks.
    assert "team" not in rows and "vitals" not in rows and "hometown" not in rows
    print("test_card_rows_from_the_play_alone: PASS")


def test_card_rows_enriched_by_the_bio():
    goal = _extract_goal(_PLAY)
    goal["team_abbr"] = "WSH"
    goal["bio"] = _BIO
    rows = _ConcreteHockeyLive._build_goal_card_rows(goal)
    assert _row(rows, "team", " ") == "#76 C", rows["team"]
    assert _row(rows, "stats") == "G 6  A 10  PTS 16  +/- -1", rows["stats"]
    assert _row(rows, "vitals") == "Age 33  6' 0\"  211 lbs", rows["vitals"]
    assert _row(rows, "hometown") == "Ham Lake, MN"
    print("test_card_rows_enriched_by_the_bio: PASS")


def test_card_rows_offer_both_name_spellings():
    """The renderer picks the longest that fits; "J. Brodzinski" is a far
    better narrow-panel answer than "Jonny Brodzinsk"."""
    goal = _extract_goal(_PLAY)
    rows = _ConcreteHockeyLive._build_goal_card_rows(goal)
    assert rows["name"][0] == "Jonny Brodzinski"
    assert rows["name"][-1] == "J. Brodzinski"
    # A scorer whose two spellings match is offered once, not twice.
    solo = _ConcreteHockeyLive._build_goal_card_rows(
        {"scorer": {"name": "Pelle", "short_name": "Pelle"}})
    assert solo["name"] == ["Pelle"], solo["name"]
    print("test_card_rows_offer_both_name_spellings: PASS")


# --- 4. fitting + contrast ---------------------------------------------------

def test_fit_segments_drops_whole_fields():
    draw = ImageDraw.Draw(Image.new("RGB", (256, 64)))
    font = ImageFont.load_default()
    fit = _ConcreteHockeyLive._fit_segments
    segs = ["Age 33", "6' 0\"", "211 lbs"]
    assert fit(draw, segs, font, 10_000) == "Age 33  6' 0\"  211 lbs"
    two = draw.textbbox((0, 0), "Age 33  6' 0\"", font=font)[2]
    assert fit(draw, segs, font, two) == "Age 33  6' 0\""
    assert fit(draw, segs, font, 1) == "Age 33"
    assert fit(draw, [], font, 100) == ""
    assert fit(draw, ["#76", "C"], font, 10_000, " ") == "#76 C"
    print("test_fit_segments_drops_whole_fields: PASS")


def test_readable_on_flips_with_background_brightness():
    readable = _ConcreteHockeyLive._readable_on
    assert readable((0, 30, 62)) == (255, 255, 255)      # Maple Leafs blue
    assert readable((252, 181, 20)) == (0, 0, 0)         # Bruins gold
    print("test_readable_on_flips_with_background_brightness: PASS")


# --- 5. bio parsing ----------------------------------------------------------

def test_parse_player_details_hockey_fields():
    parsed = ESPNDataSource._parse_player_details({"athlete": {
        "id": "3025614", "displayName": "Jonny Brodzinski", "jersey": "76",
        "position": {"abbreviation": "C"},
        "age": 33, "displayBirthPlace": "Ham Lake, MN",
        "displayHeight": "6' 0\"", "displayWeight": "211 lbs",
        "displayExperience": "7th Season",
        "team": {"id": "23", "abbreviation": "WSH"},
        "headshot": {"href": "http://x/1.png"},
        "statsSummary": {"displayName": "2025-26 regular season stats",
                         "statistics": [
                             {"abbreviation": "G", "displayValue": "6"},
                             {"abbreviation": "A", "displayValue": "10"}]},
    }})
    assert parsed["display_name"] == "Jonny Brodzinski"
    assert parsed["jersey"] == "76" and parsed["position"] == "C"
    assert parsed["age"] == 33 and parsed["birthplace"] == "Ham Lake, MN"
    assert parsed["team_abbr"] == "WSH"
    assert parsed["stat_pairs"] == [("G", "6"), ("A", "10")]
    assert parsed["headshot_url"] == "http://x/1.png"
    # A goaltender with no statsSummary degrades rather than raising.
    bare = ESPNDataSource._parse_player_details({"athlete": {"id": "2", "displayName": "X"}})
    assert bare["stat_pairs"] == [] and bare["stats_title"] is None
    assert ESPNDataSource._parse_player_details({"athlete": "nope"}) is None
    print("test_parse_player_details_hockey_fields: PASS")


# --- 6. arming gate ----------------------------------------------------------

def _make_arming_live(show=True, sport_league=("hockey", "nhl"), celebration=None,
                      config=None, favorite_teams=None):
    live = object.__new__(_ConcreteHockeyLive)
    live.show_goal_scorer = show
    live.test_mode = False
    live.espn_summary_sport_league = sport_league
    live.active_celebration = celebration
    live._goal_card = None
    live._goal_card_baselines = {}
    live.live_games = []
    live.favorite_teams = favorite_teams or []
    live.config = config or {}
    resolved = []
    live._resolve_goal_scorer = lambda game, side: resolved.append((game, side))
    return live, resolved


def _run_update(live):
    # Call HockeyLive.update() with its super() stubbed out. SportsLive's
    # update() is what refreshes live_games and (when enabled) arms the
    # celebration; the card's own detection runs after it.
    import hockey
    real = hockey.SportsLive.update
    hockey.SportsLive.update = lambda self: None
    try:
        HockeyLive.update(live)
    finally:
        hockey.SportsLive.update = real


_CELEBRATION = {"kind": "goal", "started_at": 1000.0, "scored_side": "home",
                "game": {"id": "g1", "home_id": "23", "home_abbr": "WSH"}}


def _game(away=0, home=0, game_id="g1"):
    return {"id": game_id, "away_score": str(away), "home_score": str(home),
            "away_id": "10", "home_id": "23",
            "away_abbr": "PHI", "home_abbr": "WSH"}


def test_arming_requires_the_opt_in():
    live, resolved = _make_arming_live(show=False)
    live.live_games = [_game()]
    _run_update(live)
    live.live_games = [_game(home=1)]
    _run_update(live)
    assert resolved == [], "expected no lookup when show_goal_scorer is off"
    print("test_arming_requires_the_opt_in: PASS")


def test_arming_skips_leagues_with_no_play_data():
    """College hockey's summary has no plays array, so there is nothing to
    read a scorer out of -- and no request worth making."""
    live, resolved = _make_arming_live(sport_league=None)
    live.live_games = [_game()]
    _run_update(live)
    live.live_games = [_game(home=1)]
    _run_update(live)
    assert resolved == []
    print("test_arming_skips_leagues_with_no_play_data: PASS")


def test_card_does_not_need_the_celebration():
    """The whole point of the two settings being separate: with the takeover
    off, SportsLive._check_for_goal returns early and never arms a
    celebration, so a card that rode on active_celebration could never
    appear. The card keeps its own baseline."""
    live, resolved = _make_arming_live(celebration=None)
    live.live_games = [_game()]
    _run_update(live)                      # first sighting: baseline only
    assert resolved == []
    live.live_games = [_game(home=1)]
    _run_update(live)
    assert len(resolved) == 1 and resolved[0][1] == "home", resolved
    print("test_card_does_not_need_the_celebration: PASS")


def test_first_sighting_never_fires():
    """A game already in progress at boot would otherwise report every goal
    it had already scored."""
    live, resolved = _make_arming_live()
    live.live_games = [_game(away=3, home=2)]
    _run_update(live)
    assert resolved == [], "expected the first sighting to only set a baseline"
    print("test_first_sighting_never_fires: PASS")


def test_a_waved_off_goal_rebases_silently():
    """Hockey disallows goals after review more than most sports. A decrement
    must re-base rather than arm anything, and must not leave the card
    primed to fire on the next poll."""
    live, resolved = _make_arming_live()
    live.live_games = [_game(home=2)]
    _run_update(live)
    live.live_games = [_game(home=1)]      # goal waved off
    _run_update(live)
    assert resolved == []
    live.live_games = [_game(home=1)]      # unchanged
    _run_update(live)
    assert resolved == []
    live.live_games = [_game(home=2)]      # scored again for real
    _run_update(live)
    assert len(resolved) == 1
    print("test_a_waved_off_goal_rebases_silently: PASS")


def test_arming_fires_once_per_goal():
    live, resolved = _make_arming_live()
    live.live_games = [_game(home=1)]
    _run_update(live)
    live.live_games = [_game(home=2)]
    _run_update(live)
    _run_update(live)
    _run_update(live)
    assert len(resolved) == 1, f"expected one lookup per goal, got {len(resolved)}"
    live.live_games = [_game(home=3)]
    _run_update(live)
    assert len(resolved) == 2
    print("test_arming_fires_once_per_goal: PASS")


def test_every_live_game_is_watched_not_just_the_one_on_screen():
    live, resolved = _make_arming_live()
    live.live_games = [_game(game_id="g1"), _game(game_id="g2")]
    _run_update(live)
    live.live_games = [_game(game_id="g1"), _game(home=1, game_id="g2")]
    _run_update(live)
    assert len(resolved) == 1 and resolved[0][0]["id"] == "g2", resolved
    print("test_every_live_game_is_watched_not_just_the_one_on_screen: PASS")


def test_favorites_only_is_the_cards_own_scope():
    """Not tied to the celebration's celebrate_opponent_goals: the two
    screens can cover different goals."""
    cfg = {"customization": {"goal_scorer": {"favorites_only": True}}}
    live, resolved = _make_arming_live(config=cfg, favorite_teams=["WSH"])
    live.live_games = [_game()]
    _run_update(live)
    live.live_games = [_game(away=1)]      # the opponent scored
    _run_update(live)
    assert resolved == [], "expected favorites_only to skip an opponent's goal"
    live.live_games = [_game(away=1, home=1)]
    _run_update(live)
    assert len(resolved) == 1 and resolved[0][1] == "home"
    # Off by default: any goal in a game the board is showing gets a card.
    live, resolved = _make_arming_live(favorite_teams=["WSH"])
    live.live_games = [_game()]
    _run_update(live)
    live.live_games = [_game(away=1)]
    _run_update(live)
    assert len(resolved) == 1, "expected any goal to arm when favorites_only is off"
    print("test_favorites_only_is_the_cards_own_scope: PASS")


def test_baselines_are_pruned_when_a_game_ends():
    live, _ = _make_arming_live()
    live.live_games = [_game(game_id="g1"), _game(game_id="g2")]
    _run_update(live)
    assert set(live._goal_card_baselines) == {"g1", "g2"}
    live.live_games = [_game(game_id="g1")]
    _run_update(live)
    assert set(live._goal_card_baselines) == {"g1"}, live._goal_card_baselines
    print("test_baselines_are_pruned_when_a_game_ends: PASS")


def _make_window_live_for_timing(celebration=None, dwell=6):
    live = object.__new__(_ConcreteHockeyLive)
    live.active_celebration = celebration
    live.celebration_duration = 8
    live.config = {"customization": {"goal_scorer": {"dwell_seconds": dwell}}}
    return live


def test_window_waits_for_a_celebration_but_does_not_need_one():
    import time as _t
    real = _t.time
    try:
        _t.time = lambda: 1000.0
        # Celebration on for this game: the card is the second beat.
        live = _make_window_live_for_timing(celebration=_CELEBRATION)
        assert live._goal_card_window("g1") == (1008.0, 1014.0)
        # Celebration off: the card is the only beat, and starts now.
        live = _make_window_live_for_timing(celebration=None)
        assert live._goal_card_window("g1") == (1000.0, 1006.0)
        # A celebration for a *different* game must not delay this card.
        live = _make_window_live_for_timing(celebration=_CELEBRATION)
        assert live._goal_card_window("g2") == (1000.0, 1006.0)
        # A win celebration is not a goal takeover, so no wait either.
        live = _make_window_live_for_timing(
            celebration=dict(_CELEBRATION, kind="win"))
        assert live._goal_card_window("g1") == (1000.0, 1006.0)
    finally:
        _t.time = real
    print("test_window_waits_for_a_celebration_but_does_not_need_one: PASS")


# --- 7. display window -------------------------------------------------------

def _make_window_live(card):
    live = object.__new__(_ConcreteHockeyLive)
    live.show_goal_scorer = True
    live._goal_card = card
    drawn = []
    live._draw_goal_card = lambda c, force_clear=False: drawn.append(c)
    return live, drawn


def _card(show_from=100.0, show_until=110.0, game_id="g1"):
    return {"game_id": game_id, "show_from": show_from, "show_until": show_until,
            "scorer": {"name": "X"}}


def test_card_waits_for_the_celebration_then_expires():
    import time as _t
    real = _t.time
    try:
        live, drawn = _make_window_live(_card())
        _t.time = lambda: 99.0
        assert live._maybe_draw_goal_card({"id": "g1"}) is False, "celebration still owns the panel"
        _t.time = lambda: 105.0
        assert live._maybe_draw_goal_card({"id": "g1"}) is True and len(drawn) == 1
        _t.time = lambda: 111.0
        assert live._maybe_draw_goal_card({"id": "g1"}) is False, "expected the card to expire"
        assert live._goal_card is None, "expected the expired card cleared"
    finally:
        _t.time = real
    print("test_card_waits_for_the_celebration_then_expires: PASS")


def test_card_only_draws_over_its_own_game():
    """The rotation can move on; a Capitals goal card must not be painted
    over a Bruins game."""
    import time as _t
    real = _t.time
    try:
        live, drawn = _make_window_live(_card())
        _t.time = lambda: 105.0
        assert live._maybe_draw_goal_card({"id": "g2"}) is False
        assert drawn == []
    finally:
        _t.time = real
    print("test_card_only_draws_over_its_own_game: PASS")


def test_no_card_armed_means_normal_scorebug():
    live, drawn = _make_window_live(None)
    assert live._maybe_draw_goal_card({"id": "g1"}) is False
    live.show_goal_scorer = False
    live._goal_card = _card()
    assert live._maybe_draw_goal_card({"id": "g1"}) is False
    print("test_no_card_armed_means_normal_scorebug: PASS")


# --- 8. render smoke ---------------------------------------------------------

class _DisplayManager:
    def __init__(self, width, height):
        self.image = Image.new("RGB", (width, height))

    def update_display(self):
        pass


_SIZES = ((64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32),
          (128, 96), (256, 128), (256, 64), (512, 64))


def _make_render_live(width, height, config=None):
    import logging
    live = object.__new__(_ConcreteHockeyLive)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.sport_key = "nhl"
    live.espn_summary_sport_league = ("hockey", "nhl")
    live._headshot_mgr = None
    live.show_goal_scorer = True
    live.config = config or {}
    live.logger = logging.getLogger("test_goal_scorer_render")
    # Pillow >= 11's load_default() returns a scalable fallback whose textbbox
    # under-reports its own ink, which would fail the margin assertion on the
    # stub rather than on anything the plugin did. Prefer the honest bitmap
    # font where this Pillow has it; real BDF metrics are covered by the CI
    # render harness.
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
    goal = _extract_goal(_PLAY)
    goal.update({"team_abbr": "WSH", "team_color": (200, 16, 46),
                 "game_id": "g1", "bio": _BIO})
    return goal


def test_font_ladder_is_monotone_in_height():
    """Each rung must be no taller than the one before it, or the ladder can
    step 'down' into something that needs more room. This is also what makes
    the Matrix faces safe to insert: each sits immediately before the X11
    rung of its own height, so a panel with room renders exactly as it did."""
    import logging
    live = object.__new__(_ConcreteHockeyLive)
    live._font_cache = {}
    live._bdf_native_size_cache = {}
    live.logger = logging.getLogger("t")
    heights = []
    for name in _ConcreteHockeyLive._GOAL_CARD_FONT_LADDER:
        font = live._load_custom_font_from_element_config({"font": name}, default_size=8)
        box = font.getbbox("Ay")
        heights.append((name, box[3] - box[1]))
    for (prev_name, prev_h), (name, h) in zip(heights, heights[1:]):
        assert h <= prev_h, f"{name} ({h}px) is taller than {prev_name} ({prev_h}px)"
    # And the point of the exercise: the proportional faces really are
    # narrower than the X11 rung they precede, on this card's own text.
    widths = {}
    for name in ("MatrixChunky8.bdf", "5x8.bdf"):
        font = live._load_custom_font_from_element_config({"font": name}, default_size=8)
        widths[name] = font.getbbox("Jonny Brodzinski")[2]
    assert widths["MatrixChunky8.bdf"] < widths["5x8.bdf"] * 0.85, widths
    print("test_font_ladder_is_monotone_in_height: PASS")


def test_render_all_sizes_no_overflow():
    goal = _full_goal()
    for w, h in _SIZES:
        live = _make_render_live(w, h)
        live._draw_goal_card(goal)
        _assert_clean(live, w, h, "full")
    print("test_render_all_sizes_no_overflow: PASS")


def test_render_play_only_and_sparse_no_crash():
    """No bio yet, no assists, no strength -- the commonest first frame."""
    bare = _extract_goal(dict(_PLAY, strength=None,
                              participants=_PLAY["participants"][:1]))
    bare.update({"team_abbr": "WSH", "game_id": "g1"})
    for w, h in _SIZES:
        live = _make_render_live(w, h)
        live._draw_goal_card(bare)
        _assert_clean(live, w, h, "play-only")
    print("test_render_play_only_and_sparse_no_crash: PASS")


def test_render_toggles_off_still_draws():
    cfg = {"customization": {"goal_scorer": {
        "show_stats": False, "show_assists": False, "show_bio_details": False,
        "show_headshot": False, "header_bar": False, "use_team_colors": False,
    }}}
    goal = _full_goal()
    for w, h in _SIZES:
        live = _make_render_live(w, h, config=cfg)
        live._draw_goal_card(goal)
        _assert_clean(live, w, h, "toggles-off")
    print("test_render_toggles_off_still_draws: PASS")


def test_headshot_hidden_on_a_tiny_panel():
    asked = []
    live = _make_render_live(64, 32)
    live._get_headshot_manager = lambda: asked.append(True)
    live._draw_goal_card(_full_goal())
    assert asked == [], "expected no headshot lookup at 64x32"
    live = _make_render_live(256, 64)
    live._get_headshot_manager = lambda: asked.append(True)
    live._draw_goal_card(_full_goal())
    assert asked == [True], "expected a headshot lookup at 256x64"
    print("test_headshot_hidden_on_a_tiny_panel: PASS")


def test_headshot_cache_is_bounded():
    """The disk copy is downscaled and the directory capped -- the same
    ceiling the baseball card needed, carried over rather than re-learnt."""
    import pathlib
    import tempfile
    import logging
    from hockey_headshot_manager import HockeyHeadshotManager
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        mgr = HockeyHeadshotManager(None, logging.getLogger("t"))
        mgr._HEADSHOT_DIR = tmpdir
        mgr._download_headshot_image = lambda url: Image.new("RGBA", (600, 436), (1, 2, 3, 255))
        mgr._MAX_CACHED_HEADSHOTS = 4
        for i in range(9):
            mgr.load_headshot(f"p{i}", "https://a.espncdn.com/x.png",
                              league="nhl", max_size=32, allow_download=True)
        files = list(tmpdir.rglob("*.png"))
        assert len(files) == 4, f"expected the directory capped, got {len(files)}"
        cap = HockeyHeadshotManager._DISK_HEADSHOT_SIZE
        with Image.open(files[0]) as on_disk:
            assert on_disk.size == (cap, cap), on_disk.size
        assert mgr.get_cache_size() <= mgr._MEMORY_CACHE_MAX
    print("test_headshot_cache_is_bounded: PASS")


# --- 9. team colour ----------------------------------------------------------

def test_team_color_choice_and_clamping():
    # A vivid primary in the legible band is used as-is.
    assert _team_color({"color": "e31937", "alternateColor": "ffffff"}) == (227, 25, 55)
    # A navy primary is lifted into the band, keeping its channel ratios.
    assert _team_color({"color": "0b1f41"}) == (27, 78, 164)
    # White is brought down so it does not glare. Pure black is never picked.
    assert _team_color({"color": "ffffff", "alternateColor": "000000"}) == (235, 235, 235)
    # A black or near-black primary gives way to a coloured alternate...
    assert _team_color({"color": "000000", "alternateColor": "fcb514"}) == (252, 181, 20)
    assert _team_color({"color": "0a0a0b", "alternateColor": "fcb514"}) == (252, 181, 20)
    # ...and to a silver one, which is the team's colour when both are neutral.
    assert _team_color({"color": "000000", "alternateColor": "a2aaad"}) == (162, 170, 173)
    # Nothing usable: the card keeps its configured accent.
    for team in (None, {}, {"color": "000000"}, {"color": "zzzzzz"},
                 {"color": "fff"}, {"color": 123}):
        assert _team_color(team) is None, team
    # The '#' ESPN sometimes omits and sometimes does not.
    assert _team_color({"color": "#e31937"}) == (227, 25, 55)
    print("test_team_color_choice_and_clamping: PASS")


def _espn_live_event():
    """A live NHL scoreboard event, shaped like ESPN's, whose competitors
    carry team.color / team.alternateColor the way the feed does. The home
    side is team 23, the team _PLAY's goal belongs to."""
    return {
        "id": "401879359",
        "date": "2026-01-14T00:00Z",
        "competitions": [{
            "status": {
                "period": 3, "displayClock": "9:45",
                "type": {"name": "STATUS_IN_PROGRESS", "state": "in",
                         "completed": False, "shortDetail": "9:45 - 3rd",
                         "detail": "9:45 - 3rd"},
            },
            "competitors": [
                {"homeAway": "home", "id": "23", "score": "5",
                 "team": {"id": "23", "abbreviation": "WSH",
                          "color": "0b1f41", "alternateColor": "d71830"}},
                {"homeAway": "away", "id": "5", "score": "2",
                 "team": {"id": "5", "abbreviation": "PIT",
                          "color": "000000", "alternateColor": "fcb514"}},
            ],
        }],
    }


class _SyncThread:
    """Runs a thread's target inline, so the resolve is deterministic."""

    def __init__(self, target=None, daemon=None, **_):
        self._target = target

    def start(self):
        self._target()


def test_card_gets_the_team_color_from_the_espn_feed():
    """End to end, with no hand-injected colour: the game dict is built by
    the real NHL extractor, the card is armed by _resolve_goal_scorer, and
    the drawn card carries the scoring team's colour, not the fallback."""
    import logging
    import tempfile
    import threading
    from pathlib import Path
    from nhl_managers import NHLLiveManager

    live = object.__new__(NHLLiveManager)
    live.logger = logging.getLogger("test_goal_card_team_color")
    live.favorite_teams = []
    live.config = {"timezone": "UTC"}
    live.cache_manager = None
    with tempfile.TemporaryDirectory() as tmp:
        live.logo_dir = Path(tmp)
        game = live._extract_game_details(_espn_live_event())
    assert game is not None, "expected the ESPN event to parse"
    assert game["home_team_color"] == (27, 78, 164), game["home_team_color"]
    assert game["away_team_color"] == (252, 181, 20), game["away_team_color"]

    class _DataSource:
        def fetch_game_summary(self, sport, league, game_id):
            return {"plays": [_PLAY]}

        def fetch_player_details(self, sport, league, player_id):
            return None

    live.data_source = _DataSource()
    live._goal_card = None
    live._player_bio_cache = {}
    live.active_celebration = None
    live._prefetch_headshot = lambda *a, **k: None  # no network in tests
    real_thread = threading.Thread
    threading.Thread = _SyncThread
    try:
        live._resolve_goal_scorer(game, "home")
    finally:
        threading.Thread = real_thread
    card = live._goal_card
    assert card is not None, "expected the card armed"
    assert card["team_color"] == game["home_team_color"], card.get("team_color")

    fallback = (255, 200, 0)
    for w, h in ((64, 32), (256, 64)):
        live = _make_render_live(w, h)
        live._draw_goal_card(card)
        colors = {c for _, c in live.display_manager.image.getcolors(w * h)}
        assert (27, 78, 164) in colors, f"team colour missing at {w}x{h}"
        assert fallback not in colors, f"fallback accent drawn at {w}x{h}"
    print("test_card_gets_the_team_color_from_the_espn_feed: PASS")


if __name__ == "__main__":
    print("goal-scorer card tests")
    print("=" * 60)
    tests = [
        test_extract_goal_reads_scorer_and_assists,
        test_extract_goal_none_when_nobody_named,
        test_latest_goal_scans_backwards_and_filters_by_team,
        test_goal_strength_badge,
        test_card_rows_from_the_play_alone,
        test_card_rows_enriched_by_the_bio,
        test_card_rows_offer_both_name_spellings,
        test_fit_segments_drops_whole_fields,
        test_readable_on_flips_with_background_brightness,
        test_parse_player_details_hockey_fields,
        test_arming_requires_the_opt_in,
        test_arming_skips_leagues_with_no_play_data,
        test_card_does_not_need_the_celebration,
        test_first_sighting_never_fires,
        test_a_waved_off_goal_rebases_silently,
        test_arming_fires_once_per_goal,
        test_every_live_game_is_watched_not_just_the_one_on_screen,
        test_favorites_only_is_the_cards_own_scope,
        test_baselines_are_pruned_when_a_game_ends,
        test_window_waits_for_a_celebration_but_does_not_need_one,
        test_card_waits_for_the_celebration_then_expires,
        test_card_only_draws_over_its_own_game,
        test_no_card_armed_means_normal_scorebug,
        test_font_ladder_is_monotone_in_height,
        test_render_all_sizes_no_overflow,
        test_render_play_only_and_sparse_no_crash,
        test_render_toggles_off_still_draws,
        test_headshot_hidden_on_a_tiny_panel,
        test_headshot_cache_is_bounded,
        test_team_color_choice_and_clamping,
        test_card_gets_the_team_color_from_the_espn_feed,
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
