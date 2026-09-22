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
  6. The arming gate: opt-in, NHL-only, once per celebration.
  7. _maybe_draw_goal_card: the window it owns, and the game it belongs to.
  8. Render smoke across every harness size, plus the headshot-cache bounds
     carried over from the baseball card.

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
    HockeyLive, _extract_goal, _goal_strength_badge, _latest_goal)


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

def _make_arming_live(show=True, sport_league=("hockey", "nhl"), celebration=None):
    live = object.__new__(_ConcreteHockeyLive)
    live.show_goal_scorer = show
    live.test_mode = False
    live.espn_summary_sport_league = sport_league
    live.active_celebration = celebration
    live._goal_card = None
    live._goal_card_armed_at = None
    live.config = {}
    resolved = []
    live._resolve_goal_scorer = lambda c: resolved.append(c)
    # Stand in for SportsLive.update(), which is where the score delta is
    # spotted and the celebration armed.
    _ConcreteHockeyLive.__mro__  # noqa: B018 -- documents the super() chain
    return live, resolved


def _run_update(live):
    # Call HockeyLive.update() with its super() stubbed out.
    import hockey
    real = hockey.SportsLive.update
    hockey.SportsLive.update = lambda self: None
    try:
        HockeyLive.update(live)
    finally:
        hockey.SportsLive.update = real


_CELEBRATION = {"kind": "goal", "started_at": 1000.0, "scored_side": "home",
                "game": {"id": "g1", "home_id": "23", "home_abbr": "WSH"}}


def test_arming_requires_the_opt_in():
    live, resolved = _make_arming_live(show=False, celebration=_CELEBRATION)
    _run_update(live)
    assert resolved == [], "expected no lookup when show_goal_scorer is off"
    print("test_arming_requires_the_opt_in: PASS")


def test_arming_skips_leagues_with_no_play_data():
    """College hockey's summary has no plays array, so there is nothing to
    read a scorer out of -- and no request worth making."""
    live, resolved = _make_arming_live(sport_league=None, celebration=_CELEBRATION)
    _run_update(live)
    assert resolved == []
    print("test_arming_skips_leagues_with_no_play_data: PASS")


def test_arming_fires_once_per_goal():
    live, resolved = _make_arming_live(celebration=_CELEBRATION)
    _run_update(live)
    _run_update(live)
    _run_update(live)
    assert len(resolved) == 1, f"expected one lookup per goal, got {len(resolved)}"
    # A second goal in the same game is a new celebration, so it arms again.
    live.active_celebration = dict(_CELEBRATION, started_at=1200.0)
    _run_update(live)
    assert len(resolved) == 2
    print("test_arming_fires_once_per_goal: PASS")


def test_arming_ignores_win_celebrations():
    live, resolved = _make_arming_live(
        celebration=dict(_CELEBRATION, kind="win"))
    _run_update(live)
    assert resolved == [], "expected only goal celebrations to arm the card"
    live.active_celebration = None
    _run_update(live)
    assert resolved == []
    print("test_arming_ignores_win_celebrations: PASS")


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
        test_arming_fires_once_per_goal,
        test_arming_ignores_win_celebrations,
        test_card_waits_for_the_celebration_then_expires,
        test_card_only_draws_over_its_own_game,
        test_no_card_armed_means_normal_scorebug,
        test_render_all_sizes_no_overflow,
        test_render_play_only_and_sparse_no_crash,
        test_render_toggles_off_still_draws,
        test_headshot_hidden_on_a_tiny_panel,
        test_headshot_cache_is_bounded,
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
