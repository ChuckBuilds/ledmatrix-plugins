#!/usr/bin/env python3
"""
Regression tests for the pitcher/batter/last-play parsing helpers in
baseball.py (backing the "at-bat info" rotating screen).

Covers:
  1. CLEAN_PLAY_TYPE_MAP coverage for every mapped ESPN `type.type`.
  2. Keyword fallback for walks/strikeouts (no dedicated ESPN type).
  3. Hide-on-no-match: an unrecognized play returns None rather than a guess.
  4. Backward-scan correctness for both last-play and pitcher/batter,
     skipping trailing empty transition-marker plays.
  5. Roster join across both teams for the athlete-id -> name map.
  6. Cache pruning for games no longer live.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_pitcher_batter_last_play.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from baseball import (  # noqa: E402
    BaseballLive,
    CLEAN_PLAY_TYPE_MAP,
    _build_athlete_name_map,
    _get_current_pitcher_batter,
    _get_last_play_code,
    _map_play_type,
)


def _play(play_type="", text="", participants=None):
    return {
        "type": {"type": play_type} if play_type else {},
        "text": text,
        "participants": participants or [],
    }


def _participant(role, athlete_id):
    return {"type": role, "athlete": {"id": athlete_id}}


def test_clean_type_map_coverage():
    for espn_type, expected_code in CLEAN_PLAY_TYPE_MAP.items():
        code = _map_play_type(_play(play_type=espn_type))
        assert code == expected_code, f"{espn_type} -> expected {expected_code}, got {code}"
    print("test_clean_type_map_coverage: PASS")


def test_keyword_fallback_walk_and_strikeout():
    walk = _map_play_type(_play(play_type="play-result", text="Vientos walked, Bichette to second."))
    assert walk == "BB", f"expected BB for a walk, got {walk}"

    strikeout = _map_play_type(_play(play_type="play-result", text="Judge struck out swinging."))
    assert strikeout == "K", f"expected K for a strikeout, got {strikeout}"
    print("test_keyword_fallback_walk_and_strikeout: PASS")


def test_hide_on_no_match():
    code = _map_play_type(_play(play_type="play-result", text="Mound visit by the pitching coach."))
    assert code is None, f"expected None for an unmapped play, got {code}"

    plays = [_play(play_type="play-result", text="Mound visit by the pitching coach.")]
    assert _get_last_play_code(plays) is None, "should hide rather than guess when nothing matches"
    print("test_hide_on_no_match: PASS")


def test_last_play_skips_trailing_empty_markers():
    plays = [
        _play(play_type="single", text="Judge singled to right field."),
        _play(play_type="", text=""),  # trailing transition marker, e.g. end of inning
    ]
    code = _get_last_play_code(plays)
    assert code == "1B", f"expected to skip the empty marker and find 1B, got {code}"
    print("test_last_play_skips_trailing_empty_markers: PASS")


def test_last_play_uses_most_recent_only():
    plays = [
        _play(play_type="single", text="Judge singled to right field."),
        _play(play_type="strike-out", text="Stanton struck out."),  # unmapped clean type, no keyword match on this text alone (but has real text)
    ]
    # The most recent substantive play ("strike-out"/"struck out") should win,
    # not the earlier single -- even though "strike-out" isn't in
    # CLEAN_PLAY_TYPE_MAP, its text does match the "struck out" keyword.
    code = _get_last_play_code(plays)
    assert code == "K", f"expected the most recent play (K) to win, got {code}"
    print("test_last_play_uses_most_recent_only: PASS")


def test_build_athlete_name_map_joins_both_teams():
    rosters = [
        {"roster": [{"athlete": {"id": "1", "shortName": "A. Judge"}}]},
        {"roster": [{"athlete": {"id": "2", "shortName": "S. Vientos"}}]},
    ]
    names = _build_athlete_name_map(rosters)
    assert names == {"1": "A. Judge", "2": "S. Vientos"}, f"unexpected map: {names}"
    print("test_build_athlete_name_map_joins_both_teams: PASS")


def test_get_current_pitcher_batter_backward_scan():
    names = {"10": "G. Cole", "20": "J. Soto"}
    plays = [
        _play(participants=[_participant("pitcher", "10"), _participant("batter", "20")]),
        _play(),  # trailing transition marker with no participants
    ]
    pitcher, batter = _get_current_pitcher_batter(plays, names)
    assert pitcher == "G. Cole" and batter == "J. Soto", f"got pitcher={pitcher}, batter={batter}"
    print("test_get_current_pitcher_batter_backward_scan: PASS")


def test_get_current_pitcher_batter_no_participants_returns_none():
    pitcher, batter = _get_current_pitcher_batter([_play(), _play()], {})
    assert pitcher is None and batter is None
    print("test_get_current_pitcher_batter_no_participants_returns_none: PASS")


class _ConcreteBaseballLive(BaseballLive):
    """Minimal concrete BaseballLive so we can instantiate without the full
    manager stack (mirrors test_favorite_live_boost.py's _ConcreteLive)."""

    def _extract_game_details(self, game_event):  # abstract in SportsCore
        return None

    def _fetch_data(self):  # abstract in SportsCore
        return None


def _make_live():
    live = object.__new__(_ConcreteBaseballLive)
    live._play_by_play_cache = {"g1": {"pitcher": "A"}, "g2": {"pitcher": "B"}}
    live._play_by_play_last_attempt = {"g1": 100.0, "g2": 200.0, "g3": 300.0}
    live.live_games = [{"id": "g1"}]
    return live


def test_prune_stale_play_by_play():
    live = _make_live()
    live._prune_stale_play_by_play()
    assert list(live._play_by_play_cache.keys()) == ["g1"], live._play_by_play_cache
    assert list(live._play_by_play_last_attempt.keys()) == ["g1"], live._play_by_play_last_attempt
    print("test_prune_stale_play_by_play: PASS")


class _StubDataSource:
    def __init__(self, response):
        self._response = response

    def fetch_game_summary(self, sport, league, game_id):
        return self._response


def _make_live_for_fetch(response):
    live = object.__new__(_ConcreteBaseballLive)
    live._play_by_play_cache = {"g1": {"pitcher": "G. Cole", "batter": "J. Soto", "last_play_code": "1B"}}
    live.espn_summary_sport_league = ("baseball", "mlb")
    live.data_source = _StubDataSource(response)
    import logging
    live.logger = logging.getLogger("test_fetch_play_by_play")
    return live


def test_fetch_play_by_play_keeps_prior_cache_on_empty_response():
    # A "successful" response with no plays/rosters (e.g. right before the
    # game starts) must not clobber a previously-good cache entry.
    live = _make_live_for_fetch({"plays": [], "rosters": []})
    live._fetch_play_by_play("g1")
    assert live._play_by_play_cache["g1"] == {
        "pitcher": "G. Cole", "batter": "J. Soto", "last_play_code": "1B"
    }, live._play_by_play_cache
    print("test_fetch_play_by_play_keeps_prior_cache_on_empty_response: PASS")


def test_fetch_play_by_play_updates_cache_on_real_data():
    names = {"10": "Y. Yamamoto", "20": "F. Freeman"}
    rosters = [
        {"roster": [{"athlete": {"id": "10", "shortName": names["10"]}}]},
        {"roster": [{"athlete": {"id": "20", "shortName": names["20"]}}]},
    ]
    plays = [_play(participants=[_participant("pitcher", "10"), _participant("batter", "20")])]
    live = _make_live_for_fetch({"plays": plays, "rosters": rosters})
    live._fetch_play_by_play("g1")
    assert live._play_by_play_cache["g1"]["pitcher"] == "Y. Yamamoto"
    assert live._play_by_play_cache["g1"]["batter"] == "F. Freeman"
    print("test_fetch_play_by_play_updates_cache_on_real_data: PASS")


def _make_gate_test_live(favorites_only=None, favorite_teams=None):
    live = object.__new__(_ConcreteBaseballLive)
    live.show_pitcher_batter = True
    live.show_last_play = True
    live._play_by_play_cache = {"g1": {"pitcher": "G. Cole", "batter": "J. Soto"}}
    live._at_bat_screen_last_shown = 0.0
    live._at_bat_screen_showing_until = 0.0
    live.favorite_teams = favorite_teams or []
    cfg = {}
    if favorites_only is not None:
        cfg["favorites_only"] = favorites_only
    live.config = {"customization": {"at_bat_info": cfg}}
    drawn = []
    live._draw_at_bat_info_screen = lambda game, pbp, force_clear=False: drawn.append(game)
    return live, drawn


def test_at_bat_info_favorites_only_skips_non_favorite_teams():
    live, drawn = _make_gate_test_live(favorites_only=True, favorite_teams=["NYY"])
    live._maybe_draw_at_bat_info_screen({"id": "g1", "home_abbr": "BOS", "away_abbr": "TB"})
    assert drawn == [], "expected favorites_only to skip a game with no favorite team"
    result = live._maybe_draw_at_bat_info_screen({"id": "g1", "home_abbr": "NYY", "away_abbr": "BOS"})
    assert drawn and result is True, "expected favorites_only to draw a game involving a favorite team"
    print("test_at_bat_info_favorites_only_skips_non_favorite_teams: PASS")


def test_at_bat_info_favorites_only_has_no_effect_when_favorite_teams_empty():
    live, drawn = _make_gate_test_live(favorites_only=True, favorite_teams=[])
    result = live._maybe_draw_at_bat_info_screen({"id": "g1", "home_abbr": "BOS", "away_abbr": "TB"})
    assert drawn and result is True, (
        "expected favorites_only to have no effect (draw normally) when favorite_teams is empty"
    )
    print("test_at_bat_info_favorites_only_has_no_effect_when_favorite_teams_empty: PASS")


class _DisplayManager:
    def __init__(self, width, height):
        from PIL import Image
        self.image = Image.new("RGB", (width, height))
        self._updated = False

    def update_display(self):
        self._updated = True


def _make_render_live(width, height):
    live = object.__new__(_ConcreteBaseballLive)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.config = {}
    live.show_pitcher_batter = True
    live.show_last_play = True
    # SportsCore.__init__ creates these; object.__new__ skips it, and the
    # at-bat card's font ladder reads _font_cache on its first draw. Without
    # them every render here raised AttributeError, was swallowed by the
    # plugin's except, and drew nothing -- so four checks below failed on an
    # empty canvas rather than on anything the renderer did wrong.
    live._font_cache = {}
    live._bdf_native_size_cache = {}
    import logging
    live.logger = logging.getLogger("test_at_bat_info_render")
    return live


def _find_font_asset(name="9x15.bdf"):
    """The at-bat-info screen's auto-fit sizing (and these rendering tests)
    depend on real font metrics -- _load_custom_font_from_element_config
    resolves fonts relative to cwd ('assets/fonts/...'), so this only
    succeeds when run from the LEDMatrix tree. Mirrors
    test_traditional_scoreboard.py's _find_font_asset."""
    candidates = []
    d = PLUGIN_DIR
    for _ in range(6):
        candidates.append(os.path.join(d, "assets", "fonts", name))
        d = os.path.dirname(d)
    candidates.append(os.path.join(os.getcwd(), "assets", "fonts", name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


_SAMPLE_GAME = {
    "home_abbr": "NYY", "away_abbr": "BOS", "inning_half": "top",
    "home_team_color": (38, 82, 150), "away_team_color": (189, 48, 57),
}
_SAMPLE_PBP = {"pitcher": "Y. Yamamoto", "batter": "M. Betts", "last_play_code": "BB"}


def test_at_bat_info_text_is_horizontally_centered():
    if not _find_font_asset():
        print("SKIP test_at_bat_info_text_is_horizontally_centered: "
              "could not locate assets/fonts (run from LEDMatrix tree)")
        return
    live = _make_render_live(192, 48)
    live._draw_at_bat_info_screen(_SAMPLE_GAME, _SAMPLE_PBP)
    img = live.display_manager.image
    w, _ = img.size
    non_black_xs = [x for x in range(w) for y in range(img.height) if img.getpixel((x, y)) != (0, 0, 0)]
    assert non_black_xs, "expected some text to be drawn"
    left_margin = min(non_black_xs)
    right_margin = w - 1 - max(non_black_xs)
    assert abs(left_margin - right_margin) <= 2, (
        f"expected text roughly centered horizontally, left margin={left_margin} right margin={right_margin}"
    )
    print("test_at_bat_info_text_is_horizontally_centered: PASS")


def test_at_bat_info_uses_team_colors_when_available():
    if not _find_font_asset():
        print("SKIP test_at_bat_info_uses_team_colors_when_available: "
              "could not locate assets/fonts (run from LEDMatrix tree)")
        return
    # inning_half "top" -> away (BOS) batting, home (NYY) fielding/pitching.
    live = _make_render_live(192, 48)
    live.config = {"customization": {"at_bat_info": {"use_team_colors": True}}}
    live._draw_at_bat_info_screen(_SAMPLE_GAME, _SAMPLE_PBP)
    img = live.display_manager.image
    colors = set(img.getdata())
    assert (38, 82, 150) in colors, "expected the pitcher's line in the fielding team's (NYY) color"
    assert (189, 48, 57) in colors, "expected the batter's line in the batting team's (BOS) color"
    print("test_at_bat_info_uses_team_colors_when_available: PASS")


def test_at_bat_info_falls_back_to_flat_colors_when_team_colors_disabled():
    if not _find_font_asset():
        print("SKIP test_at_bat_info_falls_back_to_flat_colors_when_team_colors_disabled: "
              "could not locate assets/fonts (run from LEDMatrix tree)")
        return
    live = _make_render_live(192, 48)
    live.config = {"customization": {"at_bat_info": {
        "use_team_colors": False,
        "pitcher_color": [10, 20, 30],
        "batter_color": [40, 50, 60],
    }}}
    live._draw_at_bat_info_screen(_SAMPLE_GAME, _SAMPLE_PBP)
    img = live.display_manager.image
    colors = set(img.getdata())
    assert (10, 20, 30) in colors, "expected the flat pitcher_color to be used"
    assert (40, 50, 60) in colors, "expected the flat batter_color to be used"
    assert (38, 82, 150) not in colors and (189, 48, 57) not in colors, (
        "did not expect team colors when use_team_colors is disabled"
    )
    print("test_at_bat_info_falls_back_to_flat_colors_when_team_colors_disabled: PASS")


def test_at_bat_info_bigger_font_on_larger_display():
    if not _find_font_asset():
        print("SKIP test_at_bat_info_bigger_font_on_larger_display: "
              "could not locate assets/fonts (run from LEDMatrix tree)")
        return
    small = _make_render_live(64, 32)
    small._draw_at_bat_info_screen(_SAMPLE_GAME, _SAMPLE_PBP)
    small_img = small.display_manager.image
    small_rows = [y for y in range(small_img.height) if any(
        small_img.getpixel((x, y)) != (0, 0, 0) for x in range(small_img.width)
    )]

    large = _make_render_live(256, 128)
    large._draw_at_bat_info_screen(_SAMPLE_GAME, _SAMPLE_PBP)
    large_img = large.display_manager.image
    large_rows = [y for y in range(large_img.height) if any(
        large_img.getpixel((x, y)) != (0, 0, 0) for x in range(large_img.width)
    )]

    assert len(large_rows) > len(small_rows), (
        f"expected a bigger auto-fit font (more lit rows) on a larger display, "
        f"small={len(small_rows)} rows, large={len(large_rows)} rows"
    )
    print("test_at_bat_info_bigger_font_on_larger_display: PASS")


def test_at_bat_info_long_name_does_not_clip():
    if not _find_font_asset():
        print("SKIP test_at_bat_info_long_name_does_not_clip: "
              "could not locate assets/fonts (run from LEDMatrix tree)")
        return
    game = dict(_SAMPLE_GAME)
    pbp = {
        "pitcher": "Yoshinobu Yamamoto-Sanchez",
        "batter": "Mookie Betts",
        "last_play_code": "HR",
    }
    for w, h in ((64, 32), (128, 32), (128, 64), (192, 48)):
        live = _make_render_live(w, h)
        live._draw_at_bat_info_screen(game, pbp)
        img = live.display_manager.image
        margin = 1
        clipped = any(
            img.getpixel((x, y)) != (0, 0, 0)
            for edge in (range(0, margin), range(w - margin, w))
            for x in edge
            for y in range(h)
        )
        assert not clipped, f"content drawn into a margin column at {w}x{h} with a long name"
    print("test_at_bat_info_long_name_does_not_clip: PASS")


if __name__ == "__main__":
    print("pitcher/batter/last-play parsing regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_clean_type_map_coverage,
        test_keyword_fallback_walk_and_strikeout,
        test_hide_on_no_match,
        test_last_play_skips_trailing_empty_markers,
        test_last_play_uses_most_recent_only,
        test_build_athlete_name_map_joins_both_teams,
        test_get_current_pitcher_batter_backward_scan,
        test_get_current_pitcher_batter_no_participants_returns_none,
        test_prune_stale_play_by_play,
        test_fetch_play_by_play_keeps_prior_cache_on_empty_response,
        test_fetch_play_by_play_updates_cache_on_real_data,
        test_at_bat_info_favorites_only_skips_non_favorite_teams,
        test_at_bat_info_favorites_only_has_no_effect_when_favorite_teams_empty,
        test_at_bat_info_text_is_horizontally_centered,
        test_at_bat_info_uses_team_colors_when_available,
        test_at_bat_info_falls_back_to_flat_colors_when_team_colors_disabled,
        test_at_bat_info_bigger_font_on_larger_display,
        test_at_bat_info_long_name_does_not_clip,
    ):
        try:
            t()
        except AssertionError as e:
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
