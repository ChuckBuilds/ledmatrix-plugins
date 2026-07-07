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
def _render_celebration(scored_side, width=128, height=32, elapsed=2.5):
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

    # Real bundled NFL logos as crests — committed, reproducible inputs.
    def _logo_loader(team_id, abbr, path, url=None):
        im = Image.open(path).convert("RGBA")
        im.thumbnail((height, height), Image.Resampling.LANCZOS)
        return im

    live._load_and_resize_logo = _logo_loader

    game = _game(away="DAL", home="KC", away_score="24", home_score="17")
    game["away_logo_path"] = os.path.join(_LOGOS, "DAL.png")
    game["home_logo_path"] = os.path.join(_LOGOS, "KC.png")
    celebration = {
        "kind": "score",
        "game": game,
        "scored_side": scored_side,
        "team_abbr": "DAL" if scored_side == "away" else "KC",
        "away_score": 24, "home_score": 17,
        "started_at": 0.0,
        "phrase": "TOUCHDOWN!",
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


def _real_fonts_available():
    return all(os.path.exists(p) for p in _REAL_FONTS)


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
        assert worst == 0, f"golden drift for {name} ({img.width}x{img.height}): max Δ={worst}"


def test_golden_celebration_screen():
    """Lock the celebration takeover to committed production-font goldens."""
    if not _real_fonts_available():
        print("SKIP: golden celebration screen (run from the core LEDMatrix tree "
              "so assets/fonts resolves; production fonts are required, not bundled)")
        return
    update = os.environ.get("UPDATE_GOLDEN") == "1"
    for w, h in ((128, 32), (128, 64)):
        _check_golden("celebration_switch", _render_celebration("away", w, h), update)
    print("PASS: golden celebration screen" + (" (regenerated)" if update else ""))


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
