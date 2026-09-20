#!/usr/bin/env python3
"""
Regression tests for the live score/win celebration takeover.

Covers:
- Score detection from per-side score increments (favorites, opponents, the
  no-favorites fallback), first-sighting suppression, and correction decrements.
- The football-specific stacked-score suppression: a touchdown lands as +6 then
  a +1 extra point a few seconds later, which must NOT fire a second takeover.
- Points->phrase mapping (touchdown, field goal, safety).
- Win detection on the live->final transition (favorite-only, ties, losses,
  and the "board booted after the final whistle" no-baseline case).
- display() dispatch: a celebration takes over the screen until it expires,
  then defers to the normal scorebug.
- A celebration screen actually renders (non-blank score, side-dependent
  highlight), with production-font goldens at the supported sizes.
- The team-colour palette read off the scoring side's crest: the colours it
  picks, that lifting one keeps its hue, the no-crest fallback, and the
  config switch.
- Per-score scenery (goalposts for a kick, the goal line for a touchdown, a
  sunburst for a win) and the points-to-motif mapping.
- The 1 FPS contract: the core samples a switch-mode board once a second, so
  every frame across the window has to be a finished card, and the scoring
  side has to glow on a ramp rather than toggle (a toggle aliases).
- That the plugin asks the controller for the high-FPS loop while a
  celebration is on screen.

Run with the core venv (golden checks need assets/fonts, so run from the core
LEDMatrix tree like the safety harness):
    cd /Users/ron/code/led-matrix/LEDMatrix
    .venv/bin/python /path/to/football-scoreboard/test_score_celebration.py
"""

import os
import sys
import types
import logging
import tempfile
import threading

from PIL import Image, ImageChops

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

GOLDEN = os.path.join(PLUGIN_DIR, "test", "golden")
_LOGOS = os.path.join(PLUGIN_DIR, "assets", "sports", "nfl_logos")

# sports.py imports ``from src.logo_downloader import ...`` at module load; stub
# the names so the import succeeds. Tests build instances via __new__, so the
# stub is never actually called.
if "src.logo_downloader" not in sys.modules:
    src_pkg = types.ModuleType("src")
    # Point the stub at the real core so `from src.common import ...` still
    # resolves through to it. Without a __path__ this stub SHADOWS the core,
    # and game_renderer's top-level import of src.common.sports_card fails
    # naming `src` rather than the module actually wanted.
    _core = os.environ.get("LEDMATRIX_CORE")
    if not _core:
        for _cand in sys.path:
            if _cand and os.path.isdir(os.path.join(_cand, "src", "common")):
                _core = _cand
                break
    if not (_core and os.path.isdir(os.path.join(_core, "src"))):
        print("SKIP: no LEDMatrix core found -- set LEDMATRIX_CORE or run via "
              "scripts/run_plugin_tests.py --core <path>.")
        sys.exit(2)
    src_pkg.__path__ = [os.path.join(_core, "src")]
    logo_mod = types.ModuleType("src.logo_downloader")

    class _StubLogoDownloader:
        def get_logo_directory(self, *a, **k):
            return tempfile.gettempdir()

        def ensure_logo_directory(self, *a, **k):
            return True

    def _stub_download_missing_logo(*a, **k):
        return None

    logo_mod.LogoDownloader = _StubLogoDownloader
    logo_mod.download_missing_logo = _stub_download_missing_logo
    src_pkg.logo_downloader = logo_mod
    sys.modules["src"] = src_pkg
    sys.modules["src.logo_downloader"] = logo_mod

    # The stubs above are plain ModuleTypes, so `from src.common.X import Y`
    # fails with "'src.common' is not a package" even when a real core is on
    # the path. Giving them a __path__ lets genuine submodules -- sports_shared,
    # sports_card -- resolve from the core while the stubbed ones stay stubbed.
    # Stubbing those too would make this test pass against dummies instead of
    # the code under test.
    _core = os.environ.get("LEDMATRIX_CORE") or next(
        (p for p in sys.path
         if p and os.path.isdir(os.path.join(p, "src", "common"))), None)
    if _core:
        if "src" in sys.modules and not hasattr(sys.modules["src"], "__path__"):
            sys.modules["src"].__path__ = [os.path.join(_core, "src")]
        if ("src.common" in sys.modules
                and not hasattr(sys.modules["src.common"], "__path__")):
            sys.modules["src.common"].__path__ = [
                os.path.join(_core, "src", "common")]

logging.basicConfig(level=logging.ERROR)


def _concrete_live():
    from sports import SportsLive

    class _ConcreteLive(SportsLive):
        def _fetch_data(self, *a, **k):
            return None

        def _extract_game_details(self, *a, **k):
            return None

    return _ConcreteLive


def _make_live(favorite_teams=None, opponent_scores=False, duration=8, enabled=True):
    """Minimal SportsLive instance carrying just the celebration state."""
    live = object.__new__(_concrete_live())
    live.celebration_enabled = enabled
    live.celebration_duration = duration
    live.celebrate_opponent_scores = opponent_scores
    live.favorite_teams = favorite_teams or []
    live._score_baselines = {}
    live.active_celebration = None
    live.current_game = None
    live.logger = logging.getLogger("t")
    # display() also checks whether the live game's dwell has elapsed, so the
    # fake needs the rotation state a real manager builds in __init__. Empty
    # live_games means "nothing to rotate to", which is what these tests want.
    live._games_lock = threading.RLock()
    live.live_games = []
    live._rotation_schedule = []
    live.last_game_switch = 0.0
    return live


def _game(gid="g1", away="DAL", home="KC", away_score="0", home_score="0",
          is_final=False):
    return {
        "id": gid, "away_abbr": away, "home_abbr": home,
        "away_id": "2", "home_id": "1",
        "away_score": away_score, "home_score": home_score,
        "away_logo_path": "y", "home_logo_path": "x",
        "is_final": is_final,
    }


# ---------------------------------------------------------------------------
# Score detection
# ---------------------------------------------------------------------------
def test_first_sighting_sets_baseline_no_celebration():
    live = _make_live(favorite_teams=["DAL"])
    # First time we see this game it's already 7-0 (game in progress at boot).
    live._check_for_score(_game(away_score="7", home_score="0"))
    assert live.active_celebration is None, "first sighting must not celebrate"
    assert live._score_baselines["g1"] == {"away": 7, "home": 0}
    print("PASS: first sighting sets baseline without celebrating")


def test_favorite_touchdown_triggers_celebration():
    live = _make_live(favorite_teams=["DAL"])
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="6", home_score="0"))  # DAL TD
    c = live.active_celebration
    assert c is not None, "favorite score should arm a celebration"
    assert c["kind"] == "score"
    assert c["scored_side"] == "away" and c["team_abbr"] == "DAL"
    assert c["away_score"] == 6 and c["home_score"] == 0
    assert c["phrase"] in ("TOUCHDOWN!", "DAL TD!")
    print("PASS: favorite touchdown triggers celebration on the scoring side")


def test_touchdown_then_extra_point_single_celebration():
    """A TD (+6) immediately followed by the extra point (+1) must produce
    exactly one takeover, not two stacked celebrations."""
    live = _make_live(favorite_teams=["DAL"])
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="6", home_score="0"))  # TD
    first = live.active_celebration
    assert first is not None and first["phrase"] in ("TOUCHDOWN!", "DAL TD!")
    # Extra point lands while the TD celebration is still on screen.
    live._check_for_score(_game(away_score="7", home_score="0"))  # XP
    assert live.active_celebration is first, "extra point must not restart the celebration"
    # Baseline still advanced, so nothing re-fires once the window closes.
    assert live._score_baselines["g1"] == {"away": 7, "home": 0}
    print("PASS: touchdown + extra point yields a single celebration")


def test_field_goal_phrase():
    live = _make_live(favorite_teams=["KC"])
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="0", home_score="3"))  # KC field goal
    c = live.active_celebration
    assert c is not None and c["scored_side"] == "home"
    assert c["phrase"] == "KC FIELD GOAL!"
    print("PASS: a +3 increment is labeled a field goal")


def test_safety_phrase():
    live = _make_live(favorite_teams=["KC"])
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="0", home_score="2"))  # KC safety
    c = live.active_celebration
    assert c is not None and c["phrase"] == "KC SAFETY!"
    print("PASS: a +2 increment is labeled a safety")


def test_score_phrase_mapping():
    from sports import SportsLive
    assert SportsLive._score_phrase(7, "DAL") in ("TOUCHDOWN!", "DAL TD!")
    assert SportsLive._score_phrase(6, "DAL") in ("TOUCHDOWN!", "DAL TD!")
    assert SportsLive._score_phrase(3, "DAL") == "DAL FIELD GOAL!"
    assert SportsLive._score_phrase(2, "DAL") == "DAL SAFETY!"
    assert SportsLive._score_phrase(1, "DAL") == "DAL SCORES!"
    print("PASS: _score_phrase maps points to the right football phrase")


def test_opponent_score_suppressed_by_default():
    live = _make_live(favorite_teams=["DAL"])  # KC is the opponent
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="0", home_score="7"))  # KC scores
    assert live.active_celebration is None, "opponent score must not celebrate by default"
    print("PASS: opponent score suppressed when celebrate_opponent_scores is off")


def test_opponent_score_celebrated_when_enabled():
    live = _make_live(favorite_teams=["DAL"], opponent_scores=True)
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="0", home_score="7"))  # KC scores
    c = live.active_celebration
    assert c is not None and c["scored_side"] == "home" and c["team_abbr"] == "KC"
    print("PASS: opponent score celebrated when celebrate_opponent_scores is on")


def test_no_favorites_celebrates_any_score():
    live = _make_live(favorite_teams=[])  # showing all live games
    live._check_for_score(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_score(_game(away_score="0", home_score="3"))  # anyone scores
    assert live.active_celebration is not None, "no favorites -> celebrate any score"
    print("PASS: with no favorites configured, any score celebrates")


def test_correction_decrement_no_celebration():
    live = _make_live(favorite_teams=["DAL"])
    live._check_for_score(_game(away_score="14", home_score="7"))  # baseline 14-7
    live._check_for_score(_game(away_score="8", home_score="7"))  # score corrected down
    assert live.active_celebration is None, "a score decrement must not celebrate"
    assert live._score_baselines["g1"] == {"away": 8, "home": 7}, "baseline must re-base"
    print("PASS: a downward score correction does not celebrate and re-bases")


def test_disabled_never_celebrates():
    live = _make_live(favorite_teams=["DAL"], enabled=False)
    live._check_for_score(_game(away_score="0", home_score="0"))
    live._check_for_score(_game(away_score="7", home_score="0"))
    assert live.active_celebration is None and not live._score_baselines
    print("PASS: celebration disabled -> no detection at all")


# ---------------------------------------------------------------------------
# Win detection
# ---------------------------------------------------------------------------
def test_favorite_win_triggers_celebration():
    live = _make_live(favorite_teams=["DAL"])
    live._check_for_score(_game(away_score="24", home_score="17"))  # tracked live
    live._check_for_win(_game(away_score="24", home_score="17", is_final=True))
    c = live.active_celebration
    assert c is not None and c["kind"] == "win"
    assert c["scored_side"] == "away" and c["team_abbr"] == "DAL"
    assert c["phrase"] == "DAL WINS!"
    assert "g1" not in live._score_baselines, "win must consume the baseline"
    print("PASS: favorite win triggers a win celebration once")


def test_win_without_baseline_suppressed():
    live = _make_live(favorite_teams=["DAL"])
    # Board started after the final whistle: game seen final with no prior baseline.
    live._check_for_win(_game(away_score="24", home_score="17", is_final=True))
    assert live.active_celebration is None, "no baseline -> no win celebration"
    print("PASS: a game first seen already-final does not celebrate a win")


def test_tie_no_win_celebration():
    live = _make_live(favorite_teams=["DAL"])
    live._check_for_score(_game(away_score="17", home_score="17"))  # tracked live
    live._check_for_win(_game(away_score="17", home_score="17", is_final=True))
    assert live.active_celebration is None, "a tie is not a win"
    print("PASS: a tied final does not celebrate a win")


def test_favorite_loss_no_celebration():
    live = _make_live(favorite_teams=["DAL"])
    live._check_for_score(_game(away_score="10", home_score="27"))  # tracked live
    live._check_for_win(_game(away_score="10", home_score="27", is_final=True))
    assert live.active_celebration is None, "favorite lost -> no win celebration"
    print("PASS: a favorite's loss does not celebrate")


# ---------------------------------------------------------------------------
# display() dispatch
# ---------------------------------------------------------------------------
def test_display_dispatches_celebration_then_scorebug():
    live = _make_live(favorite_teams=["DAL"], duration=8)
    live.is_enabled = True
    live.current_game = _game()
    calls = []
    live._draw_celebration_layout = lambda c, force_clear=False: calls.append("celebration")
    live._draw_scorebug_layout = lambda g, force_clear=False: calls.append("scorebug")

    import sports
    real_time = sports.time.time
    live.active_celebration = {
        "kind": "score", "game": _game(), "scored_side": "away",
        "team_abbr": "DAL", "away_score": 6, "home_score": 0,
        "started_at": real_time(), "phrase": "TOUCHDOWN!",
    }
    assert live.display() is True and calls == ["celebration"], (
        "an active celebration must take over display()"
    )

    # Force expiry by backdating the start beyond the window.
    live.active_celebration["started_at"] = real_time() - 999
    live.last_game_switch = 0.0
    calls.clear()
    assert live.display() is True and calls == ["scorebug"], (
        "an expired celebration must clear and defer to the scorebug"
    )
    assert live.active_celebration is None, "expired celebration must be cleared"
    # Clearing must reset the dwell timer so rotation can't immediately move off
    # the scoring game (closes the update()/display() expiry race).
    assert live.last_game_switch > 0, "clearing an expired celebration must reset last_game_switch"
    print("PASS: display() shows the celebration then falls back to the scorebug")


def test_has_active_celebration_window():
    import sports

    live = _make_live(duration=8)
    assert live.has_active_celebration() is False
    live.active_celebration = {"started_at": sports.time.time()}
    assert live.has_active_celebration() is True
    live.active_celebration = {"started_at": sports.time.time() - 999}
    assert live.has_active_celebration() is False
    print("PASS: has_active_celebration tracks the duration window")


# ---------------------------------------------------------------------------
# Config wiring (plugin -> manager)
# ---------------------------------------------------------------------------
def test_config_adapter_forwards_celebration_keys():
    """The plugin config lives under `nfl`/`ncaa_fb`, but the live managers read
    `<league>_scoreboard`. _adapt_config_for_manager must forward the celebration
    keys across that boundary, or the config knobs are silently dead."""
    import manager

    plugin = object.__new__(manager.FootballScoreboardPlugin)
    plugin.logger = logging.getLogger("cfg")
    plugin.cache_manager = object()  # no config_manager attr -> defaults used
    plugin.config = {
        "nfl": {
            "enabled": True,
            "celebration_enabled": False,
            "celebration_duration": 12,
            "celebrate_opponent_scores": True,
        },
        "ncaa_fb": {"enabled": True},  # nothing set -> defaults
    }

    nfl = plugin._adapt_config_for_manager("nfl")["nfl_scoreboard"]
    assert nfl["celebration_enabled"] is False, "celebration_enabled not forwarded"
    assert nfl["celebration_duration"] == 12, "celebration_duration not forwarded"
    assert nfl["celebrate_opponent_scores"] is True, "celebrate_opponent_scores not forwarded"

    ncaa = plugin._adapt_config_for_manager("ncaa_fb")["ncaa_fb_scoreboard"]
    assert ncaa["celebration_enabled"] is True, "default celebration_enabled wrong"
    assert ncaa["celebration_duration"] == 8, "default celebration_duration wrong"
    assert ncaa["celebrate_opponent_scores"] is False, "default celebrate_opponent_scores wrong"
    print("PASS: config adapter forwards celebration keys from nfl/ncaa_fb to the manager")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render_celebration(scored_side, width=128, height=32, elapsed=2.5,
                        motif="touchdown", kind="score", phrase="TOUCHDOWN!",
                        home="KC", away="DAL", team_colors=True, confetti=True):
    """Render a celebration screen deterministically via production fonts."""
    import sports
    from sports import SportsCore

    class _FakeMatrix:
        pass

    class _FakeDisplayManager:
        def __init__(self):
            self.matrix = _FakeMatrix()
            self.matrix.width = width
            self.matrix.height = height
            self.image = Image.new("RGB", (width, height), (0, 0, 0))

        def clear(self):
            self.image = Image.new("RGB", (width, height), (0, 0, 0))

        def update_display(self):
            pass

    live = object.__new__(_concrete_live())
    live.display_manager = _FakeDisplayManager()
    live.display_width = width
    live.display_height = height
    live.config = {}
    live.logger = logging.getLogger("g")
    live.fonts = SportsCore._load_fonts(live)
    live.celebration_duration = 8
    live.celebration_team_colors = team_colors
    live.celebration_confetti = confetti

    # Real bundled NFL logos as crests — committed, reproducible inputs.
    def _logo_loader(team_id, abbr, path, url=None):
        im = Image.open(os.path.join(_LOGOS, f"{abbr}.png")).convert("RGBA")
        im.thumbnail((height, height), Image.Resampling.LANCZOS)
        return im

    live._load_and_resize_logo = _logo_loader

    game = _game(away=away, home=home, away_score="24", home_score="17")
    game["away_logo_path"] = os.path.join(_LOGOS, f"{away}.png")
    game["home_logo_path"] = os.path.join(_LOGOS, f"{home}.png")
    celebration = {
        "kind": kind,
        "motif": motif,
        "game": game,
        "scored_side": scored_side,
        "team_abbr": away if scored_side == "away" else home,
        "away_score": 24, "home_score": 17,
        "started_at": 0.0,
        "phrase": phrase,
    }

    # Freeze elapsed time so the flash/pulse animation is deterministic.
    saved = sports.time
    sports.time = types.SimpleNamespace(time=lambda: elapsed)
    try:
        live._draw_celebration_layout(celebration, force_clear=True)
    finally:
        sports.time = saved
    return live.display_manager.image.convert("RGB")


def _is_mostly_black(img, box):
    region = img.crop(box).convert("RGB")
    return max(region.getextrema()[i][1] for i in range(3)) < 10


def test_celebration_renders_score_and_side_highlight():
    away = _render_celebration("away")
    assert not _is_mostly_black(away, (40, 16, 88, 32)), "celebration score region is blank"
    home = _render_celebration("home")
    assert ImageChops.difference(away, home).getbbox() is not None, (
        "away-scored and home-scored renders are identical — the highlight is "
        "not following the scoring side"
    )
    print("PASS: celebration renders a score with a side-dependent highlight")


_REAL_FONTS = (
    os.path.join("assets", "fonts", "PressStart2P-Regular.ttf"),
    os.path.join("assets", "fonts", "4x6-font.ttf"),
)


def _font_path(rel):
    """Resolve a core-shipped font the way the plugin itself does.

    The probe below tested these paths against the process cwd, and
    scripts/run_plugin_tests.py -- the runner CI uses -- runs each test with
    cwd set to the plugin directory. So the golden screens skipped under the
    very runner that exists to check them, and reported a pass while doing it.
    LEDMATRIX_CORE is the absolute contract that runner already provides for
    exactly this case.
    """
    if os.path.exists(rel):
        return rel
    core = os.environ.get("LEDMATRIX_CORE")
    if core:
        candidate = os.path.join(core, rel)
        if os.path.exists(candidate):
            return candidate
    return rel


def _real_fonts_available():
    return all(os.path.exists(_font_path(p)) for p in _REAL_FONTS)


def _check_golden(name, img, update):
    path = os.path.join(GOLDEN, f"{img.width}x{img.height}", f"{name}.png")
    if update:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        return
    assert os.path.exists(path), f"missing golden {path} (run with UPDATE_GOLDEN=1)"
    golden = Image.open(path).convert("RGB")
    assert golden.size == img.size, f"{name}: size {img.size} != golden {golden.size}"
    diff = ImageChops.difference(img, golden)
    bbox = diff.getbbox()
    if bbox is not None:
        worst = max(max(px) for px in diff.crop(bbox).getdata())
        assert worst == 0, (
            f"golden drift for {name} ({img.width}x{img.height}): "
            f"max delta={worst}")


def test_golden_celebration_screen():
    """Lock the celebration takeover to committed production-font goldens."""
    if not _real_fonts_available():
        print("SKIP: golden celebration screen (run from the core LEDMatrix tree "
              "so assets/fonts resolves; production fonts are required, not bundled)")
        return
    update = os.environ.get("UPDATE_GOLDEN") == "1"
    for w, h in ((128, 32), (128, 64), (192, 48)):
        _check_golden("celebration_switch", _render_celebration("away", w, h), update)
    # One golden per kind of scenery, at the most common panel. These lock the
    # team palette, the goalposts, the goal line and the sunburst down, so a
    # change to any of them has to be looked at rather than merged.
    for name, kwargs in (
        ("celebration_touchdown", dict(motif="touchdown", phrase="TOUCHDOWN!",
                                       scored_side="home")),
        ("celebration_field_goal", dict(motif="kick", phrase="KC FIELD GOAL!",
                                        scored_side="home")),
        ("celebration_win", dict(motif="win", kind="win", phrase="PIT WINS!",
                                 scored_side="away", away="PIT")),
    ):
        side = kwargs.pop("scored_side")
        _check_golden(name, _render_celebration(side, 128, 32, **kwargs), update)
    print("PASS: golden celebration screen" + (" (regenerated)" if update else ""))


def test_celebration_score_fits_on_tall_panels():
    """#338 scales the score font with panel height (16px at 48 and 64 tall),
    but the celebration still placed it at display_height - 14, sized for the
    old 8px face -- so the bottom of the digits ran off the panel. Nothing may
    be drawn on the bottom row between the logos."""
    # 192x48 is the panel this was reported on. At 128x64 the two 64px logos
    # fill the width, so the between-the-logos probe has nothing to look at;
    # the 128x64 golden covers that size.
    for w, h in ((192, 48),):
        # Confetti off: this probe asks whether the SCORE is inside the panel,
        # and a flake is allowed to land on the bottom row.
        img = _render_celebration("away", w, h, confetti=False)
        # Between the two edge-pasted logos (each at most h wide).
        left, right = h, w - h
        bottom = img.crop((left, h - 1, right, h)).convert("RGB")
        lit = max(bottom.getextrema()[i][1] for i in range(3))
        assert lit < 10, f"celebration score clipped at the bottom edge of {w}x{h}"
        assert not _is_mostly_black(img, (left, h // 2, right, h - 1)), (
            f"no celebration score drawn at {w}x{h}")
    print("PASS: celebration score stays inside tall panels")


# ---------------------------------------------------------------------------
# Team-colour palette
# ---------------------------------------------------------------------------
def _brightest(img, box=None):
    region = img.crop(box) if box else img
    return max(region.convert("RGB").getextrema()[i][1] for i in range(3))


def test_palette_reads_the_scoring_team_off_its_crest():
    """The takeover's colours come from the crest, so a Chiefs score renders
    red where a Steelers score renders gold. Checked on the crests this plugin
    ships, which are the same files the board draws from."""
    import sports

    for abbr, want_hue in (("KC", "red"), ("PIT", "gold"), ("GB", "gold")):
        logo = Image.open(os.path.join(_LOGOS, f"{abbr}.png")).convert("RGBA")
        logo.thumbnail((32, 32), Image.Resampling.LANCZOS)
        palette = sports._logo_palette(logo)
        assert palette, f"{abbr}: no palette derived from the crest"
        r, g, b = palette["headline"]
        if want_hue == "red":
            assert r > 150 and r > g * 2 and r > b * 2, f"{abbr} headline {palette['headline']} is not red"
        else:
            assert r > 150 and g > 110 and b < 110, f"{abbr} headline {palette['headline']} is not gold"
        # Every headline has to survive being shrunk to 6px of text.
        assert sports._rgb_luminance(palette["headline"]) >= 100, (
            f"{abbr} headline {palette['headline']} is too dark to read on a panel")
        # And the backdrop has to stay out of its way.
        assert sports._rgb_luminance(palette["deep"]) <= 36, (
            f"{abbr} backdrop {palette['deep']} is too bright to put text on")
    print("PASS: the palette reads the scoring team's colours off its crest")


def test_palette_prefers_a_legible_crest_colour_over_lifting_a_dark_one():
    """Green Bay's dark green only reaches legibility as a teal, and the gold
    right next to it on the same crest is just as much theirs. The ranking has
    to reach for the colour that already reads."""
    import sports

    logo = Image.open(os.path.join(_LOGOS, "GB.png")).convert("RGBA")
    logo.thumbnail((32, 32), Image.Resampling.LANCZOS)
    palette = sports._logo_palette(logo)
    r, g, b = palette["headline"]
    assert not (b > r and g > r), (
        f"GB headline {palette['headline']} came back teal -- a dark colour was "
        "lifted instead of a legible one being preferred")
    # The backdrop still carries the green the crest is mostly made of.
    assert palette["deep"][1] >= palette["deep"][0], (
        f"GB backdrop {palette['deep']} lost the green")
    print("PASS: the palette prefers a legible crest colour over lifting a dark one")


def test_lifting_a_colour_keeps_its_hue():
    """Scaling the channels to brighten a dark saturated colour turns
    Baltimore's navy-purple into magenta. Lifting has to work in HSV."""
    import sports

    navy_purple = (39, 15, 98)
    lifted = sports._lift_color(navy_purple)
    assert sports._rgb_luminance(lifted) >= 100, f"{lifted} is still too dark"
    assert lifted[2] > lifted[0] > lifted[1], (
        f"{lifted} is no longer a blue-purple -- the hue moved")
    # Capping is exact on the way down, so a cap must not move the hue at all.
    capped = sports._cap_luminance((248, 61, 1), 34)
    assert capped[0] > capped[1] > capped[2], f"{capped} lost the orange"
    assert sports._rgb_luminance(capped) <= 35, f"{capped} was not capped"
    print("PASS: lifting and capping a colour both keep its hue")


def test_palette_falls_back_when_there_is_no_crest():
    """A team whose badge has not downloaded yet still gets a celebration."""
    from sports import SportsLive

    live = _make_live()
    live.celebration_team_colors = True
    live._load_and_resize_logo = lambda *a, **k: None
    celebration = {"game": _game(), "scored_side": "home"}
    palette = SportsLive._celebration_palette(live, celebration)
    assert palette == SportsLive._DEFAULT_CELEBRATION_PALETTE, (
        "a missing crest must fall back to the default palette")

    # And a crest that raises must not take the takeover down with it.
    def _boom(*a, **k):
        raise OSError("unreadable png")

    live._load_and_resize_logo = _boom
    palette = SportsLive._celebration_palette(live, {"game": _game(), "scored_side": "away"})
    assert palette == SportsLive._DEFAULT_CELEBRATION_PALETTE, (
        "an unreadable crest must fall back, not raise")
    print("PASS: the palette falls back when there is no usable crest")


def test_team_colors_can_be_switched_off():
    lit = _render_celebration("home", team_colors=True)
    plain = _render_celebration("home", team_colors=False)
    assert ImageChops.difference(lit, plain).getbbox() is not None, (
        "celebration_team_colors=False renders identically to True")
    print("PASS: celebration_team_colors switches the crest palette off")


# ---------------------------------------------------------------------------
# Motifs
# ---------------------------------------------------------------------------
def test_score_motif_mapping():
    from sports import SportsLive

    assert SportsLive._score_motif(6) == "touchdown"
    assert SportsLive._score_motif(7) == "touchdown"
    assert SportsLive._score_motif(3) == "kick", "a field goal is a kick"
    assert SportsLive._score_motif(1) == "kick", "an extra point is a kick too"
    assert SportsLive._score_motif(2) == "score"
    print("PASS: _score_motif maps points to the right scenery")


def test_celebration_records_the_motif_it_was_armed_with():
    live = _make_live(favorite_teams=["KC"])
    live._check_for_score(_game(away_score="0", home_score="0"))
    live._check_for_score(_game(away_score="0", home_score="3"))  # KC field goal
    assert live.active_celebration["motif"] == "kick", (
        "a field goal must arm the goalposts")

    live = _make_live(favorite_teams=["KC"])
    live._check_for_score(_game(away_score="0", home_score="0"))
    live._check_for_score(_game(away_score="0", home_score="7"))  # KC touchdown
    assert live.active_celebration["motif"] == "touchdown"

    live = _make_live(favorite_teams=["KC"])
    live._check_for_score(_game(away_score="0", home_score="0"))
    live._check_for_win(_game(away_score="3", home_score="24", is_final=True))
    assert live.active_celebration["motif"] == "win"
    print("PASS: the celebration records the motif it was armed with")


def test_motifs_render_differently():
    """Each kind of score gets its own scenery, so the screens must differ."""
    shots = {
        m: _render_celebration("home", motif=m, confetti=False)
        for m in ("touchdown", "kick", "win", "score")
    }
    names = sorted(shots)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert ImageChops.difference(shots[a], shots[b]).getbbox() is not None, (
                f"the {a} and {b} scenery render identically")
    print("PASS: each motif renders its own scenery")


# ---------------------------------------------------------------------------
# The 1 FPS contract
# ---------------------------------------------------------------------------
def test_every_celebration_frame_is_a_finished_card():
    """On a switch-mode board the core samples this plugin once a second, so
    any single frame may be the only one a viewer sees. Every frame across the
    whole window has to carry the headline and the score -- no blank frame, no
    frame caught mid-wipe, and nothing clipped off the top by an entry
    animation (the headline used to slide in from y=-3).
    """
    # Every panel size the core's safety harness renders, plus 192x48.
    for w, h in ((64, 32), (128, 32), (64, 64), (96, 48), (128, 64),
                 (256, 32), (128, 96), (256, 128), (192, 48)):
        for elapsed in [0.0] + [i + 0.5 for i in range(8)]:
            img = _render_celebration("home", w, h, elapsed=elapsed)
            headline = img.crop((0, 0, w, max(2, h // 4)))
            assert _brightest(img, (0, 0, w, h)) > 40, (
                f"{w}x{h} at t={elapsed}s: the panel is effectively blank")
            assert _brightest(headline) > 60, (
                f"{w}x{h} at t={elapsed}s: no headline on the top rows -- a "
                "frame that lands here shows a card with no message on it")
    print("PASS: every celebration frame is a finished card")


def test_the_scoring_side_glows_rather_than_toggling():
    """The scoring digits breathe on a continuous ramp. A binary flash aliases
    into a colour that changes at random once a second; a ramp cannot. Sampled
    one second apart, consecutive frames must never be identical (it is still
    animating) and must never swap between exactly two states (it is not a
    toggle)."""
    frames = [
        _render_celebration("home", elapsed=t, confetti=False)
        for t in (0.9, 1.9, 2.9, 3.9, 4.9, 5.9)
    ]
    signatures = {f.tobytes() for f in frames}
    assert len(signatures) > 2, (
        "sampled once a second the score only ever showed two states -- the "
        "highlight is toggling, not breathing")
    print("PASS: the scoring side glows on a ramp rather than toggling")


# ---------------------------------------------------------------------------
# High-FPS declaration
# ---------------------------------------------------------------------------
def test_manager_asks_for_high_fps_while_celebrating():
    """Without needs_high_fps the core falls back to enable_scrolling, which is
    false on a switch-mode board -- so the confetti was being sampled once a
    second. The plugin has to ask."""
    import manager

    plugin = object.__new__(manager.FootballScoreboardPlugin)
    plugin.logger = logging.getLogger("fps")
    plugin.enable_scrolling = False
    plugin.is_enabled = True
    plugin._league_registry = {"nfl": {"enabled": True}}

    celebrating = [False]

    class _Live:
        def has_active_celebration(self):
            return celebrating[0]

    plugin._get_league_manager_for_mode = lambda league, mode: _Live()

    assert plugin.needs_high_fps is False, (
        "a quiet switch-mode board must not be driven at 125 FPS")
    celebrating[0] = True
    assert plugin.needs_high_fps is True, (
        "a celebration must ask for the high-FPS loop")

    # Scrolling boards keep the behaviour they had before this existed.
    celebrating[0] = False
    plugin.enable_scrolling = True
    assert plugin.needs_high_fps is True

    # And the controller reads this attribute bare, so it must never raise.
    broken = object.__new__(manager.FootballScoreboardPlugin)
    assert broken.needs_high_fps is False, "needs_high_fps raised on a bare instance"
    print("PASS: the manager asks for high FPS while a celebration is on screen")


def main():
    tests = [
        test_first_sighting_sets_baseline_no_celebration,
        test_favorite_touchdown_triggers_celebration,
        test_touchdown_then_extra_point_single_celebration,
        test_field_goal_phrase,
        test_safety_phrase,
        test_score_phrase_mapping,
        test_opponent_score_suppressed_by_default,
        test_opponent_score_celebrated_when_enabled,
        test_no_favorites_celebrates_any_score,
        test_correction_decrement_no_celebration,
        test_disabled_never_celebrates,
        test_favorite_win_triggers_celebration,
        test_win_without_baseline_suppressed,
        test_tie_no_win_celebration,
        test_favorite_loss_no_celebration,
        test_display_dispatches_celebration_then_scorebug,
        test_has_active_celebration_window,
        test_config_adapter_forwards_celebration_keys,
        test_celebration_renders_score_and_side_highlight,
        test_golden_celebration_screen,
        test_celebration_score_fits_on_tall_panels,
        test_palette_reads_the_scoring_team_off_its_crest,
        test_palette_prefers_a_legible_crest_colour_over_lifting_a_dark_one,
        test_lifting_a_colour_keeps_its_hue,
        test_palette_falls_back_when_there_is_no_crest,
        test_team_colors_can_be_switched_off,
        test_score_motif_mapping,
        test_celebration_records_the_motif_it_was_armed_with,
        test_motifs_render_differently,
        test_every_celebration_frame_is_a_finished_card,
        test_the_scoring_side_glows_rather_than_toggling,
        test_manager_asks_for_high_fps_while_celebrating,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")
    print("=" * 50)
    if failed:
        print(f"{failed} test(s) failed")
        sys.exit(1)
    print("All score-celebration tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
