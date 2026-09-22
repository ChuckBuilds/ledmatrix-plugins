#!/usr/bin/env python3
"""
Regression tests for the card-style pitcher/batter screen in baseball.py.

The "Now Batting" / "Now Pitching" screen used to be two lines of text. It is
now a baseball card -- headshot, banner, name, team/number/position, season
stats, age and bat/throw, hometown, height/weight -- with rows given up in a
fixed order on panels too small to hold them all.

Covers:
  1. _build_at_bat_card_rows: banner wording per role, last-play suffix, and
     graceful degradation when ESPN sent a sparse athlete record.
  2. _fit_segments: whole trailing segments dropped, never a cut mid-field.
  3. _readable_on: banner glyphs flip to black over a light team color.
  4. _format_card_stats: ESPN's own season pick (stat_pairs) wins over the
     hand-rolled selection from the flat stats map.
  5. _parse_player_details: age/hometown/team/experience captured, season
     statsSummary preferred over the overview endpoint's career totals, and
     bats/throws recovered from the combined display string.
  6. _at_bat_card_style / _wants_player_bios: text style does not pay for the
     athlete lookup.
  7. _pick_at_bat_card_subject: the dwell is split batter-then-pitcher, and
     no resolved bio means no card.
  8. _maybe_draw_at_bat_info_screen: routes to the card when a bio is
     available and falls back to the text layout when it is not.
  9. Render smoke test across every harness size: no crash, no margin
     overflow, something drawn, and the headshot hidden on a tiny panel.
 10. Headshot cache bounds: the disk copy is downscaled, the directory is
     capped least-recently-used first, and the in-memory cache is bounded.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_at_bat_player_card.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from baseball import BaseballLive  # noqa: E402
from data_sources import ESPNDataSource  # noqa: E402


class _ConcreteBaseballLive(BaseballLive):
    """Minimal concrete BaseballLive so we can instantiate without the full
    manager stack (mirrors test_player_card.py)."""

    def _extract_game_details(self, game_event):
        return None

    def _fetch_data(self):
        return None


_BIO = {
    "display_name": "Aaron Judge", "player_id": "33192", "jersey": "99",
    "position": "RF", "bat": "R", "throw": "R", "headshot_url": None,
    "age": 34, "birthplace": "Linden, CA", "height": "6' 7\"",
    "weight": "282 lbs", "experience": "11th Season", "team_abbr": "NYY",
    "stat_pairs": [("AVG", ".241"), ("HR", "18"), ("RBI", "41"), ("OPS", ".871")],
}
_INFO = {"name": "A. Judge", "jersey": "99", "position": "RF", "bat": "R",
         "throw": "R", "team_id": "10", "team_abbr": "NYY"}
_GAME = {"home_id": "10", "away_id": "20", "home_abbr": "NYY", "away_abbr": "BOS",
         "inning_half": "bottom",
         "home_team_color": (38, 82, 150), "away_team_color": (189, 48, 57)}


# --- 1. _build_at_bat_card_rows ---------------------------------------------

def _row(rows, key):
    """The string a row is actually drawn as."""
    return _ConcreteBaseballLive._at_bat_card_row_text(key, rows[key])


def test_card_rows_full_bio():
    rows = _ConcreteBaseballLive._build_at_bat_card_rows("batter", _INFO, _BIO)
    assert _row(rows, "header") == "NOW BATTING", rows["header"]
    assert _row(rows, "name") == "Aaron Judge"
    assert _row(rows, "team") == "NYY #99 RF", rows["team"]
    assert _row(rows, "vitals") == "Age 34  B/T R/R", rows["vitals"]
    assert _row(rows, "hometown") == "Linden, CA"
    assert _row(rows, "extra") == "6' 7\"  282 lbs  11th Season", rows["extra"]
    print("test_card_rows_full_bio: PASS")


def test_card_rows_pitcher_banner_and_last_play():
    rows = _ConcreteBaseballLive._build_at_bat_card_rows(
        "pitcher", _INFO, _BIO, last_play_code="K"
    )
    assert _row(rows, "header") == "NOW PITCHING  K", rows["header"]
    print("test_card_rows_pitcher_banner_and_last_play: PASS")


def test_card_rows_sparse_bio_omits_rows_entirely():
    """An NCAA athlete record with nothing but a name must not produce empty
    or half-built rows ("Age " / ", " / "#"), just fewer rows."""
    rows = _ConcreteBaseballLive._build_at_bat_card_rows(
        "batter", None, {"display_name": "J. Smith"}
    )
    assert set(rows) == {"header", "name"}, rows
    assert _row(rows, "name") == "J. Smith"
    # A single known hand still reads as a sentence rather than "B/T R/".
    rows = _ConcreteBaseballLive._build_at_bat_card_rows(
        "batter", None, {"display_name": "X", "bat": "L"}
    )
    assert _row(rows, "vitals") == "Bats L", rows
    print("test_card_rows_sparse_bio_omits_rows_entirely: PASS")


def test_card_rows_name_falls_back_to_roster_then_placeholder():
    rows = _ConcreteBaseballLive._build_at_bat_card_rows("batter", _INFO, {})
    assert _row(rows, "name") == "A. Judge", rows
    rows = _ConcreteBaseballLive._build_at_bat_card_rows("batter", None, {})
    assert _row(rows, "name") == "Player", rows
    print("test_card_rows_name_falls_back_to_roster_then_placeholder: PASS")


# --- 2. _fit_segments --------------------------------------------------------

def test_fit_segments_drops_whole_segments():
    draw = ImageDraw.Draw(Image.new("RGB", (256, 64)))
    font = ImageFont.load_default()
    fit = _ConcreteBaseballLive._fit_segments
    stats = ["AVG .241", "HR 18", "RBI 41", "OPS .871"]
    full = fit(draw, stats, font, 10_000)
    assert full == "AVG .241  HR 18  RBI 41  OPS .871", full

    two_wide = draw.textbbox((0, 0), "AVG .241  HR 18", font=font)[2]
    fitted = fit(draw, stats, font, two_wide)
    assert fitted == "AVG .241  HR 18", fitted
    # Never a mid-segment cut: whatever survives is a whole prefix.
    assert full.startswith(fitted)

    # Even an impossible width keeps one whole segment for the caller to
    # truncate, rather than returning nothing at all.
    assert fit(draw, stats, font, 1) == "AVG .241"
    assert fit(draw, [], font, 100) == ""
    # The team row joins on a single space, not the usual double.
    assert fit(draw, ["NYY", "#99", "RF"], font, 10_000, " ") == "NYY #99 RF"
    print("test_fit_segments_drops_whole_segments: PASS")


# --- 3. _readable_on ---------------------------------------------------------

def test_readable_on_flips_with_background_brightness():
    readable = _ConcreteBaseballLive._readable_on
    assert readable((38, 82, 150)) == (255, 255, 255)    # Yankees navy
    assert readable((253, 184, 39)) == (0, 0, 0)         # Pirates gold
    assert readable((235, 235, 235)) == (0, 0, 0)
    assert readable((0, 0, 0)) == (255, 255, 255)
    print("test_readable_on_flips_with_background_brightness: PASS")


# --- 4. _format_card_stats ---------------------------------------------------

def test_format_card_stats_prefers_espn_season_pick():
    live = object.__new__(_ConcreteBaseballLive)
    bio = {
        "position": "RF",
        # A pitcher-shaped flat map, to prove stat_pairs is what's used and
        # not the position-guessing fallback.
        "stats": {"ERA": "9.99", "W": "1", "L": "2"},
        "stat_pairs": [("AVG", ".241"), ("HR", "18"), ("RBI", "41"), ("OPS", ".871")],
    }
    assert live._format_card_stats(bio) == [
        ("AVG", ".241"), ("HR", "18"), ("RBI", "41"), ("OPS", ".871"),
    ]
    # Capped at four so a long summary can't crowd out every other row.
    bio = {"stat_pairs": [(f"S{i}", str(i)) for i in range(9)]}
    assert len(live._format_card_stats(bio)) == 4
    # No stat_pairs -> the original hand-rolled selection still runs.
    assert live._format_card_stats(
        {"position": "SP", "stats": {"ERA": "2.90", "W": "11", "L": "4", "SO": "180"}}
    ) == [("ERA", "2.90"), ("W-L", "11-4"), ("K", "180")]
    print("test_format_card_stats_prefers_espn_season_pick: PASS")


# --- 5. _parse_player_details ------------------------------------------------

def test_parse_player_details_captures_card_bio_fields():
    bio_data = {"athlete": {
        "id": "33192", "displayName": "Aaron Judge", "jersey": "99",
        "position": {"abbreviation": "RF"},
        "age": 34, "displayBirthPlace": "Linden, CA",
        "displayHeight": "6' 7\"", "displayWeight": "282 lbs",
        "displayExperience": "11th Season", "debutYear": 2016,
        "displayDraft": "2013: Rd 1, Pk 32 (NYY)",
        "displayBatsThrows": "Right/Left",
        "college": {"shortName": "Fresno St"},
        "team": {"id": "10", "abbreviation": "NYY", "shortDisplayName": "Yankees"},
        "statsSummary": {"displayName": "2026 season stats", "statistics": [
            {"abbreviation": "AVG", "displayValue": ".241"},
            {"abbreviation": "HR", "displayValue": "18"},
        ]},
    }}
    parsed = ESPNDataSource._parse_player_details(bio_data, None)
    assert parsed["age"] == 34 and parsed["birthplace"] == "Linden, CA"
    assert parsed["experience"] == "11th Season" and parsed["debut_year"] == 2016
    assert parsed["college"] == "Fresno St"
    assert parsed["team_abbr"] == "NYY" and parsed["team_id"] == "10"
    assert parsed["team_name"] == "Yankees"
    # bats/throws are null on this endpoint for most athletes; the combined
    # display string is the field that actually carries them.
    assert parsed["bat"] == "R" and parsed["throw"] == "L"
    assert parsed["stat_pairs"] == [("AVG", ".241"), ("HR", "18")]
    assert parsed["stats_title"] == "2026 season stats"
    print("test_parse_player_details_captures_card_bio_fields: PASS")


def test_parse_player_details_prefers_season_over_career_overview():
    """The /overview endpoint's first split is career totals with no AVG in
    it, so preferring it labelled 386 career home runs as this season's."""
    bio_data = {"athlete": {
        "id": "1", "displayName": "Aaron Judge",
        "position": {"abbreviation": "RF"},
        "statsSummary": {"statistics": [{"abbreviation": "HR", "displayValue": "18"}]},
    }}
    overview = {"statistics": {
        "names": ["homeRuns", "RBIs"], "splits": [{"displayName": "Career",
                                                   "stats": ["386", "871"]}],
    }}
    parsed = ESPNDataSource._parse_player_details(bio_data, overview)
    assert parsed["stats"] == {"HR": "18"}, parsed["stats"]
    # ...but a feed with no statsSummary at all still gets the overview.
    bio_data["athlete"].pop("statsSummary")
    parsed = ESPNDataSource._parse_player_details(bio_data, overview)
    assert parsed["stats"] == {"homeRuns": "386", "RBIs": "871"}, parsed["stats"]
    assert parsed["stat_pairs"] == [] and parsed["stats_title"] is None
    print("test_parse_player_details_prefers_season_over_career_overview: PASS")


def test_split_bats_throws():
    split = ESPNDataSource._split_bats_throws
    assert split("Right/Right") == ("R", "R")
    assert split("Switch/Left") == ("S", "L")
    assert split(None) == (None, None)
    assert split("Right") == (None, None)
    assert split("Sideways/Backwards") == (None, None)
    print("test_split_bats_throws: PASS")


# --- 6. style + bio gating ---------------------------------------------------

def _make_style_live(style=None, pitcher_batter=True, player_card=False):
    live = object.__new__(_ConcreteBaseballLive)
    live.show_pitcher_batter = pitcher_batter
    live.show_player_card = player_card
    cfg = {} if style is None else {"style": style}
    live.config = {"customization": {"at_bat_info": cfg}}
    return live


def test_card_style_is_the_default():
    assert _make_style_live()._at_bat_card_style() == "card"
    assert _make_style_live(style="TEXT")._at_bat_card_style() == "text"
    print("test_card_style_is_the_default: PASS")


def test_text_style_does_not_pay_for_the_athlete_lookup():
    assert _make_style_live()._wants_player_bios() is True
    assert _make_style_live(style="text")._wants_player_bios() is False
    # ...unless the dedicated player-card screen is on, which always needs it.
    assert _make_style_live(style="text", player_card=True)._wants_player_bios() is True
    # Nothing enabled -> nothing fetched.
    assert _make_style_live(pitcher_batter=False)._wants_player_bios() is False
    print("test_text_style_does_not_pay_for_the_athlete_lookup: PASS")


# --- 7. _pick_at_bat_card_subject --------------------------------------------

def _make_pick_live(bios):
    live = object.__new__(_ConcreteBaseballLive)
    live._player_bio_cache = bios
    live._at_bat_screen_showing_until = 100.0
    return live


_PBP = {"batter_id": "b1", "pitcher_id": "p1",
        "batter_info": {"name": "Batter"}, "pitcher_info": {"name": "Pitcher"}}


def test_pick_subject_splits_the_dwell_between_both_players():
    live = _make_pick_live({"b1": {"display_name": "B"}, "p1": {"display_name": "P"}})
    dwell, cfg = 6.0, {}
    # now = showing_until - remaining, i.e. elapsed = dwell - remaining.
    first = live._pick_at_bat_card_subject(_PBP, cfg, 100.0 - 6.0, dwell)
    mid = live._pick_at_bat_card_subject(_PBP, cfg, 100.0 - 3.5, dwell)
    late = live._pick_at_bat_card_subject(_PBP, cfg, 100.0 - 0.1, dwell)
    assert first[0] == "batter", first
    assert mid[0] == "batter", mid          # 2.5s elapsed, still the first half
    assert late[0] == "pitcher", late       # 5.9s elapsed, second half
    # Past the end of the dwell we clamp rather than index off the list.
    assert live._pick_at_bat_card_subject(_PBP, cfg, 101.0, dwell)[0] == "pitcher"
    print("test_pick_subject_splits_the_dwell_between_both_players: PASS")


def test_pick_subject_one_player_holds_the_whole_dwell():
    live = _make_pick_live({"b1": {"display_name": "B"}})
    for now in (94.0, 97.0, 99.9):
        role, info, bio = live._pick_at_bat_card_subject(_PBP, {}, now, 6.0)
        assert role == "batter" and bio["display_name"] == "B"
    print("test_pick_subject_one_player_holds_the_whole_dwell: PASS")


def test_pick_subject_respects_show_toggles_and_missing_bios():
    live = _make_pick_live({"b1": {"display_name": "B"}, "p1": {"display_name": "P"}})
    only_pitcher = live._pick_at_bat_card_subject(
        _PBP, {"show_batter": False}, 94.0, 6.0
    )
    assert only_pitcher[0] == "pitcher", only_pitcher
    # No bio resolved yet -> None, so the caller falls back to text.
    assert _make_pick_live({})._pick_at_bat_card_subject(_PBP, {}, 94.0, 6.0) is None
    # MiLB-ish play-by-play with names but no athlete ids -> None.
    assert live._pick_at_bat_card_subject(
        {"pitcher": "G. Cole", "batter": "J. Soto"}, {}, 94.0, 6.0
    ) is None
    print("test_pick_subject_respects_show_toggles_and_missing_bios: PASS")


# --- 8. routing --------------------------------------------------------------

def _make_route_live(style=None, bios=None):
    live = object.__new__(_ConcreteBaseballLive)
    live.show_pitcher_batter = True
    live.show_last_play = True
    live.show_player_card = False
    live._play_by_play_cache = {"g1": dict(_PBP, pitcher="G. Cole", batter="J. Soto")}
    live._player_bio_cache = bios or {}
    live._at_bat_screen_last_shown = 0.0
    live._at_bat_screen_showing_until = 0.0
    live.favorite_teams = []
    cfg = {} if style is None else {"style": style}
    live.config = {"customization": {"at_bat_info": cfg}}
    drawn = []
    live._draw_at_bat_card_screen = (
        lambda game, role, info, bio, pbp, force_clear=False: drawn.append(("card", role))
    )
    live._draw_at_bat_info_screen = (
        lambda game, pbp, force_clear=False: drawn.append(("text", None))
    )
    return live, drawn


def test_routes_to_the_card_when_a_bio_is_available():
    live, drawn = _make_route_live(bios={"b1": {"display_name": "Juan Soto"}})
    assert live._maybe_draw_at_bat_info_screen({"id": "g1"}) is True
    assert drawn == [("card", "batter")], drawn
    print("test_routes_to_the_card_when_a_bio_is_available: PASS")


def test_falls_back_to_text_without_a_bio():
    """MiLB, a brand-new at-bat, or an athlete ESPN has no record for: the
    screen still appears, as text, rather than drawing an empty card."""
    live, drawn = _make_route_live(bios={})
    assert live._maybe_draw_at_bat_info_screen({"id": "g1"}) is True
    assert drawn == [("text", None)], drawn
    print("test_falls_back_to_text_without_a_bio: PASS")


def test_text_style_never_routes_to_the_card():
    live, drawn = _make_route_live(style="text", bios={"b1": {"display_name": "X"}})
    assert live._maybe_draw_at_bat_info_screen({"id": "g1"}) is True
    assert drawn == [("text", None)], drawn
    print("test_text_style_never_routes_to_the_card: PASS")


def test_last_play_only_keeps_the_text_screen():
    """show_last_play alone has never been a pitcher/batter screen, and a
    card for a player the user didn't ask to see would be a surprise."""
    live, drawn = _make_route_live(bios={"b1": {"display_name": "X"}})
    live.show_pitcher_batter = False
    assert live._maybe_draw_at_bat_info_screen({"id": "g1"}) is True
    assert drawn == [("text", None)], drawn
    print("test_last_play_only_keeps_the_text_screen: PASS")


# --- 9. Render smoke test ----------------------------------------------------

class _DisplayManager:
    def __init__(self, width, height):
        self.image = Image.new("RGB", (width, height))
        self._updated = False

    def update_display(self):
        self._updated = True


# The core harness's default matrix sizes, plus the two odd panels the
# author's rigs actually run (256x64 and 512x64).
_SIZES = (
    (64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32),
    (128, 96), (256, 128), (256, 64), (512, 64),
)


def _make_render_live(width, height, config=None):
    import logging
    live = object.__new__(_ConcreteBaseballLive)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.sport_key = "mlb"
    live.espn_summary_sport_league = ("baseball", "mlb")
    live._headshot_mgr = None
    live.show_last_play = True
    live.config = config or {}
    live.logger = logging.getLogger("test_at_bat_player_card_render")
    # Stub font loading so the render path runs off the LEDMatrix core tree
    # (mirrors test_player_card.py). Pillow >= 11's load_default() returns a
    # *scalable* fallback whose textbbox under-reports its own ink by a few
    # pixels; measuring against it would fail the margin assertion below on
    # the stub rather than on anything the plugin did, so prefer the honest
    # bitmap font when this Pillow has it. Real BDF metrics are exercised by
    # the safety harness in CI.
    loader = getattr(ImageFont, "load_default_imagefont", ImageFont.load_default)
    _default_font = loader()
    live._load_custom_font_from_element_config = lambda cfg, default_size=6: _default_font
    return live


def _assert_clean_render(live, w, h, label):
    img = live.display_manager.image
    margin = 1
    clipped = any(
        img.getpixel((x, y)) != (0, 0, 0)
        for x in list(range(0, margin)) + list(range(w - margin, w))
        for y in range(h)
    )
    assert not clipped, f"{label}: content drawn into a margin column at {w}x{h}"
    lit = any(img.getpixel((x, y)) != (0, 0, 0) for x in range(w) for y in range(h))
    assert lit, f"{label}: expected some content drawn at {w}x{h}"


def test_render_all_sizes_no_overflow():
    for w, h in _SIZES:
        for role in ("batter", "pitcher"):
            live = _make_render_live(w, h)
            live._draw_at_bat_card_screen(_GAME, role, _INFO, _BIO, {"last_play_code": "K"})
            _assert_clean_render(live, w, h, role)
    print("test_render_all_sizes_no_overflow: PASS")


def test_render_sparse_bio_and_long_name_no_crash():
    sparse = {"display_name": "Bartolome Villanueva-Rodriguez", "position": "",
              "headshot_url": None}
    for w, h in _SIZES:
        live = _make_render_live(w, h)
        live._draw_at_bat_card_screen(_GAME, "batter", None, sparse, {})
        _assert_clean_render(live, w, h, "sparse")
    print("test_render_sparse_bio_and_long_name_no_crash: PASS")


def test_render_toggles_off_still_draws():
    cfg = {"customization": {"at_bat_info": {
        "show_stats": False, "show_bio_details": False, "show_headshot": False,
        "header_bar": False, "use_team_colors": False,
    }}}
    for w, h in _SIZES:
        live = _make_render_live(w, h, config=cfg)
        live._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})
        _assert_clean_render(live, w, h, "toggles-off")
    print("test_render_toggles_off_still_draws: PASS")


def test_headshot_is_hidden_on_a_tiny_panel():
    """A 64x32 has no room for a face beside readable text, so the loader is
    never even asked -- which also means no disk read on the render path."""
    asked = []
    live = _make_render_live(64, 32)
    live._get_headshot_manager = lambda: asked.append(True)
    live._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})
    assert asked == [], "expected no headshot lookup at 64x32"

    live = _make_render_live(256, 64)
    live._get_headshot_manager = lambda: asked.append(True)
    live._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})
    assert asked == [True], "expected a headshot lookup at 256x64"
    print("test_headshot_is_hidden_on_a_tiny_panel: PASS")


def test_short_panel_drops_trivia_before_the_name():
    """The drop order is the point of the layout: a 128x32 keeps the banner,
    the name and the stats; the trivia rows only appear when there's height."""
    short = _make_render_live(128, 32)
    short._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})
    tall = _make_render_live(128, 64)
    tall._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})

    def lit_rows(live, h):
        img = live.display_manager.image
        return sum(
            1 for y in range(h)
            if any(img.getpixel((x, y)) != (0, 0, 0) for x in range(live.display_width))
        )

    assert lit_rows(short, 32) < lit_rows(tall, 64), "expected the tall panel to say more"
    print("test_short_panel_drops_trivia_before_the_name: PASS")


def test_header_bar_paints_the_team_color_behind_the_banner():
    accent = _GAME["home_team_color"]
    live = _make_render_live(256, 64)
    live._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})
    img = live.display_manager.image
    assert any(
        img.getpixel((x, y)) == accent
        for x in range(256) for y in range(64)
    ), "expected the banner bar filled with the team color"

    off = _make_render_live(256, 64, config={
        "customization": {"at_bat_info": {"header_bar": False}}})
    off._draw_at_bat_card_screen(_GAME, "batter", _INFO, _BIO, {})
    off_img = off.display_manager.image
    bar_pixels = sum(
        1 for x in range(256) for y in range(64) if off_img.getpixel((x, y)) == accent
    )
    on_pixels = sum(
        1 for x in range(256) for y in range(64) if img.getpixel((x, y)) == accent
    )
    assert bar_pixels < on_pixels, "expected header_bar=false to drop the filled bar"
    print("test_header_bar_paints_the_team_color_behind_the_banner: PASS")


# --- 10. Headshot cache bounds ----------------------------------------------

def _mock_manager(tmpdir, monkey_download=None):
    import logging
    import logo_manager as lm
    mgr = lm.BaseballLogoManager(None, logging.getLogger("t"))
    mgr._HEADSHOT_DIR = tmpdir
    if monkey_download is not None:
        mgr._download_headshot_image = monkey_download
    return mgr


def _fake_espn_headshot():
    """ESPN serves a wide, full-size PNG; the card wants a small square."""
    return Image.new("RGBA", (600, 436), (200, 30, 30, 255))


def test_disk_copy_is_downscaled_not_espn_full_size():
    """~200 KB of megapixel PNG per player was being kept to draw an 85px
    square. The disk copy is now the square the card actually uses."""
    import tempfile
    import logo_manager as lm
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = __import__("pathlib").Path(tmp)
        mgr = _mock_manager(tmpdir, monkey_download=lambda url: _fake_espn_headshot())
        img = mgr.load_headshot(
            "33192", "https://a.espncdn.com/x.png", league="mlb",
            max_size=48, allow_download=True,
        )
        assert img is not None and img.size == (48, 48), img
        stored = tmpdir / "mlb" / "33192.png"
        assert stored.exists(), "expected the headshot cached to disk"
        with Image.open(stored) as on_disk:
            size = on_disk.size
        cap = lm.BaseballLogoManager._DISK_HEADSHOT_SIZE
        assert size == (cap, cap), f"expected a {cap}px square on disk, got {size}"
    print("test_disk_copy_is_downscaled_not_espn_full_size: PASS")


def test_disk_cache_is_capped_evicting_least_recently_used():
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        mgr = _mock_manager(tmpdir, monkey_download=lambda url: _fake_espn_headshot())
        cap = mgr._MAX_CACHED_HEADSHOTS
        mgr._MAX_CACHED_HEADSHOTS = 5

        for i in range(5):
            mgr.load_headshot(f"p{i}", "https://a.espncdn.com/x.png", league="mlb",
                              max_size=32, allow_download=True)
        assert len(list(tmpdir.rglob("*.png"))) == 5

        # Touch p0 so it is the most recently *used*, not the oldest written.
        import os
        import time
        now = time.time()
        for i in range(5):
            os.utime(tmpdir / "mlb" / f"p{i}.png", (now - (5 - i), now - (5 - i)))
        os.utime(tmpdir / "mlb" / "p0.png", (now, now))

        mgr.load_headshot("p5", "https://a.espncdn.com/x.png", league="mlb",
                          max_size=32, allow_download=True)
        names = {p.stem for p in tmpdir.rglob("*.png")}
        assert len(names) == 5, names
        assert "p5" in names, "expected the new headshot kept"
        assert "p0" in names, "expected the recently used headshot kept"
        assert "p1" not in names, "expected the least recently used one evicted"
        mgr._MAX_CACHED_HEADSHOTS = cap
    print("test_disk_cache_is_capped_evicting_least_recently_used: PASS")


def test_memory_cache_is_bounded():
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = _mock_manager(pathlib.Path(tmp),
                            monkey_download=lambda url: _fake_espn_headshot())
        for i in range(mgr._MEMORY_CACHE_MAX + 20):
            mgr.load_headshot(f"p{i}", "https://a.espncdn.com/x.png", league="mlb",
                              max_size=32, allow_download=True)
        assert mgr.get_cache_size() <= mgr._MEMORY_CACHE_MAX, mgr.get_cache_size()
    print("test_memory_cache_is_bounded: PASS")


def test_a_cache_hit_still_never_downloads():
    """The prune/stamp work must not have opened a network path on the
    render side: allow_download=False stays a pure memory/disk read."""
    import pathlib
    import tempfile
    import logo_manager as lm
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        mgr = _mock_manager(tmpdir, monkey_download=lambda url: _fake_espn_headshot())
        mgr.load_headshot("p1", "https://a.espncdn.com/x.png", league="mlb",
                          max_size=32, allow_download=True)
        mgr._logo_cache.clear()  # force the disk path

        orig_get = lm.requests.get

        def boom(*a, **k):
            raise AssertionError("network fetch must not happen on the render path")

        lm.requests.get = boom
        try:
            img = mgr.load_headshot("p1", "https://a.espncdn.com/x.png", league="mlb",
                                    max_size=32, allow_download=False)
            assert img is not None and img.size == (32, 32), img
        finally:
            lm.requests.get = orig_get
    print("test_a_cache_hit_still_never_downloads: PASS")


if __name__ == "__main__":
    print("at-bat player-card tests")
    print("=" * 60)
    tests = [
        test_card_rows_full_bio,
        test_card_rows_pitcher_banner_and_last_play,
        test_card_rows_sparse_bio_omits_rows_entirely,
        test_card_rows_name_falls_back_to_roster_then_placeholder,
        test_fit_segments_drops_whole_segments,
        test_readable_on_flips_with_background_brightness,
        test_format_card_stats_prefers_espn_season_pick,
        test_parse_player_details_captures_card_bio_fields,
        test_parse_player_details_prefers_season_over_career_overview,
        test_split_bats_throws,
        test_card_style_is_the_default,
        test_text_style_does_not_pay_for_the_athlete_lookup,
        test_pick_subject_splits_the_dwell_between_both_players,
        test_pick_subject_one_player_holds_the_whole_dwell,
        test_pick_subject_respects_show_toggles_and_missing_bios,
        test_routes_to_the_card_when_a_bio_is_available,
        test_falls_back_to_text_without_a_bio,
        test_text_style_never_routes_to_the_card,
        test_last_play_only_keeps_the_text_screen,
        test_render_all_sizes_no_overflow,
        test_render_sparse_bio_and_long_name_no_crash,
        test_render_toggles_off_still_draws,
        test_headshot_is_hidden_on_a_tiny_panel,
        test_short_panel_drops_trivia_before_the_name,
        test_header_bar_paints_the_team_color_behind_the_banner,
        test_disk_copy_is_downscaled_not_espn_full_size,
        test_disk_cache_is_capped_evicting_least_recently_used,
        test_memory_cache_is_bounded,
        test_a_cache_hit_still_never_downloads,
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
