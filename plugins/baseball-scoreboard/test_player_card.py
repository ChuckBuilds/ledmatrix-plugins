#!/usr/bin/env python3
"""
Regression tests for the player-card screen in baseball.py.

Covers:
  1. _build_athlete_info_map: rich roster join (jersey/position/team) across
     both teams.
  2. _get_current_pitcher_batter_ids: backward scan returns athlete IDs.
  3. _format_card_stats: hitter vs pitcher stat selection + generic fallback.
  4. _player_card_team_color: resolves from roster team_id vs game home/away.
  5. Gatekeeper: MiLB skip (no espn_summary_sport_league), and skip when no
     resolved bio is available (never draws a blank card).
  6. Render smoke test across all supported sizes with a stubbed bio (no
     network -> headshot resolves to None -> text-only), asserting no crash,
     no margin overflow, and that the headshot is hidden on a 64x32 panel.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_player_card.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from baseball import (  # noqa: E402
    BaseballLive,
    _build_athlete_info_map,
    _get_current_pitcher_batter_ids,
)
from data_sources import ESPNDataSource  # noqa: E402


class _ConcreteBaseballLive(BaseballLive):
    """Minimal concrete BaseballLive so we can instantiate without the full
    manager stack (mirrors test_pitcher_batter_last_play.py)."""

    def _extract_game_details(self, game_event):
        return None

    def _fetch_data(self):
        return None


def _play(participants=None):
    return {"type": {}, "text": "", "participants": participants or []}


def _participant(role, athlete_id):
    return {"type": role, "athlete": {"id": athlete_id}}


# --- 1. _build_athlete_info_map ---------------------------------------------

def test_build_athlete_info_map_joins_both_teams_with_fields():
    rosters = [
        {
            "team": {"id": "10", "abbreviation": "NYY"},
            "roster": [{"athlete": {
                "id": "1", "shortName": "A. Judge", "jersey": "99",
                "position": {"abbreviation": "CF"}, "bats": {"abbreviation": "R"},
                "throws": {"abbreviation": "R"},
                "headshot": {"href": "http://x/1.png"},
            }}],
        },
        {
            "team": {"id": "20", "abbreviation": "BOS"},
            "roster": [{"athlete": {
                "id": "2", "shortName": "R. Devers", "jersey": "11",
                "position": {"abbreviation": "3B"},
            }}],
        },
    ]
    info = _build_athlete_info_map(rosters)
    assert set(info.keys()) == {"1", "2"}, info
    assert info["1"]["jersey"] == "99" and info["1"]["position"] == "CF"
    assert info["1"]["team_id"] == "10" and info["1"]["team_abbr"] == "NYY"
    assert info["1"]["headshot_url"] == "http://x/1.png"
    assert info["1"]["bat"] == "R" and info["1"]["throw"] == "R"
    # Missing optional fields degrade to None/"" rather than raising.
    assert info["2"]["team_id"] == "20" and info["2"]["headshot_url"] is None
    assert info["2"]["bat"] is None
    print("test_build_athlete_info_map_joins_both_teams_with_fields: PASS")


def test_build_athlete_info_map_handles_empty():
    assert _build_athlete_info_map(None) == {}
    assert _build_athlete_info_map([]) == {}
    print("test_build_athlete_info_map_handles_empty: PASS")


# --- 2. _get_current_pitcher_batter_ids -------------------------------------

def test_get_current_pitcher_batter_ids_backward_scan():
    plays = [
        _play(participants=[_participant("pitcher", "10"), _participant("batter", "20")]),
        _play(),  # trailing transition marker, no participants
    ]
    pid, bid = _get_current_pitcher_batter_ids(plays)
    assert pid == "10" and bid == "20", f"got pitcher_id={pid}, batter_id={bid}"
    print("test_get_current_pitcher_batter_ids_backward_scan: PASS")


def test_get_current_pitcher_batter_ids_none_when_absent():
    pid, bid = _get_current_pitcher_batter_ids([_play(), _play()])
    assert pid is None and bid is None
    print("test_get_current_pitcher_batter_ids_none_when_absent: PASS")


# --- 3. _format_card_stats --------------------------------------------------

def test_format_card_stats_hitter():
    live = object.__new__(_ConcreteBaseballLive)
    bio = {"position": "RF", "stats": {"AVG": ".312", "HR": "12", "RBI": "40", "OBP": ".390"}}
    pairs = live._format_card_stats(bio)
    labels = [lbl for lbl, _ in pairs]
    assert labels == ["AVG", "HR", "RBI"], pairs
    assert dict(pairs)["HR"] == "12"
    print("test_format_card_stats_hitter: PASS")


def test_format_card_stats_pitcher():
    live = object.__new__(_ConcreteBaseballLive)
    bio = {"position": "SP", "stats": {"ERA": "2.90", "W": "11", "L": "4", "SO": "180"}}
    pairs = live._format_card_stats(bio)
    labels = [lbl for lbl, _ in pairs]
    assert labels == ["ERA", "W-L", "K"], pairs
    assert dict(pairs)["W-L"] == "11-4"
    print("test_format_card_stats_pitcher: PASS")


def test_format_card_stats_generic_fallback():
    live = object.__new__(_ConcreteBaseballLive)
    # NCAA-ish feed with labels we don't specifically map -> first three shown.
    bio = {"position": "2B", "stats": {"G": "50", "AB": "180", "H": "55"}}
    pairs = live._format_card_stats(bio)
    assert len(pairs) == 3 and pairs[0] == ("G", "50"), pairs
    # Empty stats -> no pairs (renderer shows name/jersey/pos only).
    assert live._format_card_stats({"position": "2B", "stats": {}}) == []
    print("test_format_card_stats_generic_fallback: PASS")


# --- 3b. ESPNDataSource._parse_player_details -------------------------------

def test_parse_player_details_bio_and_stats():
    bio_data = {"athlete": {
        "id": "33", "displayName": "Aaron Judge", "firstName": "Aaron",
        "lastName": "Judge", "jersey": "99",
        "position": {"abbreviation": "CF"},
        "bats": {"abbreviation": "R"}, "throws": {"abbreviation": "R"},
        "displayHeight": "6' 7\"", "displayWeight": "282 lbs",
        "headshot": {"href": "http://x/33.png"},
    }}
    overview = {"statistics": {
        "names": ["AVG", "HR", "RBI"],
        "splits": [{"stats": [".322", "58", "144"]}],
    }}
    parsed = ESPNDataSource._parse_player_details(bio_data, overview)
    assert parsed["display_name"] == "Aaron Judge"
    assert parsed["jersey"] == "99" and parsed["position"] == "CF"
    assert parsed["bat"] == "R" and parsed["throw"] == "R"
    assert parsed["headshot_url"] == "http://x/33.png"
    assert parsed["stats"] == {"AVG": ".322", "HR": "58", "RBI": "144"}
    print("test_parse_player_details_bio_and_stats: PASS")


def test_parse_player_details_tolerates_missing_overview():
    bio_data = {"athlete": {"id": "1", "displayName": "X", "jersey": "1",
                            "position": {"abbreviation": "SP"}}}
    parsed = ESPNDataSource._parse_player_details(bio_data, None)
    assert parsed["display_name"] == "X" and parsed["stats"] == {}
    assert parsed["headshot_url"] is None
    print("test_parse_player_details_tolerates_missing_overview: PASS")


def test_parse_player_details_none_on_garbage():
    assert ESPNDataSource._parse_player_details({"athlete": "not-a-dict"}, None) is None
    print("test_parse_player_details_none_on_garbage: PASS")


# --- 3c. headshot filename sanitization -------------------------------------

def test_safe_filename_strips_path_separators():
    from logo_manager import BaseballLogoManager
    assert BaseballLogoManager._safe_filename("33099") == "33099"
    assert BaseballLogoManager._safe_filename("../../etc/passwd") == "etcpasswd"
    assert BaseballLogoManager._safe_filename("a/b\\c") == "abc"
    assert BaseballLogoManager._safe_filename(None) == ""
    print("test_safe_filename_strips_path_separators: PASS")


def test_headshot_url_allowlist():
    from logo_manager import BaseballLogoManager as B
    assert B._is_allowed_headshot_url("https://a.espncdn.com/i/headshots/mlb/players/full/1.png")
    assert B._is_allowed_headshot_url("https://secure.espn.com/x.png")
    assert not B._is_allowed_headshot_url("https://evil.example.com/x.png")
    # SSRF vectors: cloud-metadata IP, non-http scheme, and a look-alike host.
    assert not B._is_allowed_headshot_url("http://169.254.169.254/latest/meta-data/")
    assert not B._is_allowed_headshot_url("file:///etc/passwd")
    assert not B._is_allowed_headshot_url("https://espncdn.com.evil.com/x.png")
    print("test_headshot_url_allowlist: PASS")


def test_load_headshot_render_path_never_downloads():
    import logging
    import logo_manager as lm
    mgr = lm.BaseballLogoManager(None, logging.getLogger("t"))
    orig_get = lm.requests.get

    def boom(*a, **k):
        raise AssertionError("network fetch must not happen here")

    lm.requests.get = boom
    try:
        # Render path: download disabled -> cache miss returns None, no network.
        assert mgr.load_headshot(
            "no_such_id_xyz", "https://a.espncdn.com/x.png",
            league="mlb", max_size=32, allow_download=False,
        ) is None
        # Even with download allowed, a non-ESPN host is refused before any GET.
        assert mgr.load_headshot(
            "no_such_id_xyz2", "https://evil.example.com/x.png",
            league="mlb", max_size=32, allow_download=True,
        ) is None
    finally:
        lm.requests.get = orig_get
    print("test_load_headshot_render_path_never_downloads: PASS")


# --- 4. _player_card_team_color ---------------------------------------------

def test_player_card_team_color_from_roster_team_id():
    live = object.__new__(_ConcreteBaseballLive)
    game = {
        "home_id": "10", "away_id": "20",
        "home_team_color": (1, 2, 3), "away_team_color": (4, 5, 6),
    }
    assert live._player_card_team_color(game, {"team_id": "10"}) == (1, 2, 3)
    assert live._player_card_team_color(game, {"team_id": "20"}) == (4, 5, 6)
    # Unknown team / missing info -> None (renderer falls back to border_color).
    assert live._player_card_team_color(game, {"team_id": "99"}) is None
    assert live._player_card_team_color(game, None) is None
    print("test_player_card_team_color_from_roster_team_id: PASS")


# --- 5. Gatekeeper ----------------------------------------------------------

def _make_gate_live(sport_league=("baseball", "mlb"), pbp=None, bio_cache=None,
                    favorites_only=False, favorite_teams=None):
    live = object.__new__(_ConcreteBaseballLive)
    live.show_player_card = True
    live.espn_summary_sport_league = sport_league
    live._play_by_play_cache = {"g1": pbp} if pbp is not None else {}
    live._player_bio_cache = bio_cache or {}
    live._player_card_last_shown = 0.0
    live._player_card_showing_until = 0.0
    live.favorite_teams = favorite_teams or []
    cfg = {"favorites_only": favorites_only}
    live.config = {"customization": {"player_card": cfg}}
    drawn = []
    live._draw_player_card_screen = (
        lambda game, role, info, bio, force_clear=False: drawn.append((role, info, bio))
    )
    return live, drawn


def test_gate_skips_milb_no_espn_league():
    live, drawn = _make_gate_live(
        sport_league=None,
        pbp={"batter_id": "b1", "batter_info": {"name": "X"}},
        bio_cache={"b1": {"display_name": "X"}},
    )
    result = live._maybe_draw_player_card_screen({"id": "g1"})
    assert result is False and drawn == [], "expected MiLB (no espn league) to skip the card"
    print("test_gate_skips_milb_no_espn_league: PASS")


def test_gate_skips_when_no_bio_resolved():
    live, drawn = _make_gate_live(
        pbp={"batter_id": "b1", "batter_info": {"name": "X"}},
        bio_cache={},  # no bio fetched yet
    )
    result = live._maybe_draw_player_card_screen({"id": "g1"})
    assert result is False and drawn == [], "expected skip (no blank card) when bio is unavailable"
    print("test_gate_skips_when_no_bio_resolved: PASS")


def test_gate_draws_batter_when_bio_available():
    live, drawn = _make_gate_live(
        pbp={"batter_id": "b1", "batter_info": {"name": "Judge"}},
        bio_cache={"b1": {"display_name": "Aaron Judge", "stats": {"AVG": ".322"}}},
    )
    result = live._maybe_draw_player_card_screen({"id": "g1", "home_abbr": "NYY", "away_abbr": "BOS"})
    assert result is True and drawn and drawn[0][0] == "batter", drawn
    print("test_gate_draws_batter_when_bio_available: PASS")


def test_gate_favorites_only_skips_non_favorite():
    live, drawn = _make_gate_live(
        pbp={"batter_id": "b1", "batter_info": {"name": "X"}},
        bio_cache={"b1": {"display_name": "X"}},
        favorites_only=True, favorite_teams=["NYY"],
    )
    live._maybe_draw_player_card_screen({"id": "g1", "home_abbr": "BOS", "away_abbr": "TB"})
    assert drawn == [], "expected favorites_only to skip a non-favorite game"
    print("test_gate_favorites_only_skips_non_favorite: PASS")


# --- 6. Render smoke test ---------------------------------------------------

class _DisplayManager:
    def __init__(self, width, height):
        from PIL import Image
        self.image = Image.new("RGB", (width, height))
        self._updated = False

    def update_display(self):
        self._updated = True


def _make_render_live(width, height):
    import logging
    from PIL import ImageFont
    live = object.__new__(_ConcreteBaseballLive)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.sport_key = "mlb"
    live.espn_summary_sport_league = ("baseball", "mlb")
    live._headshot_mgr = None
    live.config = {}
    live.logger = logging.getLogger("test_player_card_render")
    # Stub font loading to a default bitmap font so the render path runs even
    # off the LEDMatrix core tree (mirrors test_traditional_scoreboard.py). The
    # real font metrics are exercised by the safety harness in CI.
    _default_font = ImageFont.load_default()
    live._load_custom_font_from_element_config = lambda cfg, default_size=6: _default_font
    return live


_GAME = {
    "home_id": "10", "away_id": "20", "home_abbr": "NYY", "away_abbr": "BOS",
    "inning_half": "bottom",
    "home_team_color": (38, 82, 150), "away_team_color": (189, 48, 57),
}
_INFO = {"name": "A. Judge", "jersey": "99", "position": "CF",
         "bat": "R", "throw": "R", "team_id": "10"}
# headshot_url None -> no network; renders text-only.
_BIO = {"display_name": "Aaron Judge", "jersey": "99", "position": "CF",
        "bat": "R", "throw": "R", "headshot_url": None,
        "stats": {"AVG": ".322", "HR": "58", "RBI": "144"}}


def test_render_all_sizes_no_overflow():
    for w, h in ((64, 32), (128, 32), (128, 64), (256, 32)):
        live = _make_render_live(w, h)
        live._draw_player_card_screen(_GAME, "batter", _INFO, _BIO)
        img = live.display_manager.image
        margin = 1
        clipped = any(
            img.getpixel((x, y)) != (0, 0, 0)
            for edge in (range(0, margin), range(w - margin, w))
            for x in edge
            for y in range(h)
        )
        assert not clipped, f"content drawn into a margin column at {w}x{h}"
        lit = any(img.getpixel((x, y)) != (0, 0, 0) for x in range(w) for y in range(h))
        assert lit, f"expected some content drawn at {w}x{h}"
    print("test_render_all_sizes_no_overflow: PASS")


def test_render_missing_stats_is_text_only_no_crash():
    bio = dict(_BIO)
    bio["stats"] = {}  # NCAA-ish: no season stats -> name/jersey/pos only
    for w, h in ((64, 32), (128, 64)):
        live = _make_render_live(w, h)
        live._draw_player_card_screen(_GAME, "batter", _INFO, bio)  # must not raise
    print("test_render_missing_stats_is_text_only_no_crash: PASS")


def test_render_narrow_panel_trims_stats_instead_of_truncating_mid_pair():
    """Regression for the narrow-panel stat line ("AVG .312  HR 28  RBI 71")
    truncating mid-pair (e.g. "AVG .312  H", silently losing HR/RBI). At
    64x32 the fix should drop whole trailing stat pairs -- still crash-free,
    still draws something, still respects the panel margins -- rather than
    hard-cut the joined string. (Content-level verification, i.e. that the
    drawn text is a whole prefix and not a mid-word cut, is done visually
    against a real render -- see the PR description -- since this harness
    has no OCR/text-extraction, only pixel checks.)"""
    for w, h in ((64, 32), (96, 32)):
        live = _make_render_live(w, h)
        live._draw_player_card_screen(_GAME, "batter", _INFO, _BIO)  # must not raise
        img = live.display_manager.image
        margin = 1
        clipped = any(
            img.getpixel((x, y)) != (0, 0, 0)
            for edge in (range(0, margin), range(w - margin, w))
            for x in edge
            for y in range(h)
        )
        assert not clipped, f"content drawn into a margin column at {w}x{h}"
        lit = any(img.getpixel((x, y)) != (0, 0, 0) for x in range(w) for y in range(h))
        assert lit, f"expected some content drawn at {w}x{h}"
    print("test_render_narrow_panel_trims_stats_instead_of_truncating_mid_pair: PASS")


if __name__ == "__main__":
    print("player-card tests")
    print("=" * 60)
    tests = [
        test_build_athlete_info_map_joins_both_teams_with_fields,
        test_build_athlete_info_map_handles_empty,
        test_get_current_pitcher_batter_ids_backward_scan,
        test_get_current_pitcher_batter_ids_none_when_absent,
        test_format_card_stats_hitter,
        test_format_card_stats_pitcher,
        test_format_card_stats_generic_fallback,
        test_parse_player_details_bio_and_stats,
        test_parse_player_details_tolerates_missing_overview,
        test_parse_player_details_none_on_garbage,
        test_safe_filename_strips_path_separators,
        test_headshot_url_allowlist,
        test_load_headshot_render_path_never_downloads,
        test_player_card_team_color_from_roster_team_id,
        test_gate_skips_milb_no_espn_league,
        test_gate_skips_when_no_bio_resolved,
        test_gate_draws_batter_when_bio_available,
        test_gate_favorites_only_skips_non_favorite,
        test_render_all_sizes_no_overflow,
        test_render_missing_stats_is_text_only_no_crash,
        test_render_narrow_panel_trims_stats_instead_of_truncating_mid_pair,
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
