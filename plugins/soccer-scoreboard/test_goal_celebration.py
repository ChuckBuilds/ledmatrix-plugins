#!/usr/bin/env python3
"""
Regression tests for the live goal/win celebration takeover.

Covers:
- Goal detection from per-side score increments (favorites, opponents, the
  no-favorites fallback), first-sighting suppression, and VAR decrements.
- Win detection on the live->final transition (favorite-only, draws, losses,
  and the "Pi booted after full time" no-baseline case).
- display() dispatch: a celebration takes over the screen until it expires,
  then defers to the normal scorebug.
- A celebration screen actually renders (non-blank score, side-dependent
  highlight), with production-font goldens at the supported sizes.

Run with the core venv (golden checks need assets/fonts, so run from the core
LEDMatrix tree like the safety harness):
    /Users/ron/code/led-matrix/LEDMatrix/.venv/bin/python test_goal_celebration.py
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
_FLAGS = os.path.join(PLUGIN_DIR, "assets", "flags")

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


def _make_live(favorite_teams=None, opponent_goals=False, duration=8, enabled=True):
    """Minimal SportsLive instance carrying just the celebration state."""
    live = object.__new__(_concrete_live())
    live.celebration_enabled = enabled
    live.celebration_duration = duration
    live.celebrate_opponent_goals = opponent_goals
    live.favorite_teams = favorite_teams or []
    live._score_baselines = {}
    live.active_celebration = None
    live.current_game = None
    live.logger = logging.getLogger("t")
    return live


def _game(gid="g1", away="LIV", home="MCI", away_score="1", home_score="0",
          is_final=False):
    return {
        "id": gid, "away_abbr": away, "home_abbr": home,
        "away_id": "2", "home_id": "1",
        "away_score": away_score, "home_score": home_score,
        "away_logo_path": "y", "home_logo_path": "x",
        "is_final": is_final,
    }


# ---------------------------------------------------------------------------
# Goal detection
# ---------------------------------------------------------------------------
def test_first_sighting_sets_baseline_no_celebration():
    live = _make_live(favorite_teams=["LIV"])
    # First time we see this game it's already 1-0 (match in progress at boot).
    live._check_for_goal(_game(away_score="1", home_score="0"))
    assert live.active_celebration is None, "first sighting must not celebrate"
    assert live._score_baselines["g1"] == {"away": 1, "home": 0}
    print("PASS: first sighting sets baseline without celebrating")


def test_favorite_goal_triggers_celebration():
    live = _make_live(favorite_teams=["LIV"])
    live._check_for_goal(_game(away_score="1", home_score="0"))  # baseline
    live._check_for_goal(_game(away_score="2", home_score="0"))  # LIV scores
    c = live.active_celebration
    assert c is not None, "favorite goal should arm a celebration"
    assert c["kind"] == "goal"
    assert c["scored_side"] == "away" and c["team_abbr"] == "LIV"
    assert c["away_score"] == 2 and c["home_score"] == 0
    assert c["phrase"] in ("GOOOOAAALLL!", "LIV SCORES!")
    print("PASS: favorite goal triggers celebration on the scoring side")


def test_opponent_goal_suppressed_by_default():
    live = _make_live(favorite_teams=["LIV"])  # MCI is the opponent
    live._check_for_goal(_game(away_score="1", home_score="0"))  # baseline
    live._check_for_goal(_game(away_score="1", home_score="1"))  # MCI scores
    assert live.active_celebration is None, "opponent goal must not celebrate by default"
    print("PASS: opponent goal suppressed when celebrate_opponent_goals is off")


def test_opponent_goal_celebrated_when_enabled():
    live = _make_live(favorite_teams=["LIV"], opponent_goals=True)
    live._check_for_goal(_game(away_score="1", home_score="0"))  # baseline
    live._check_for_goal(_game(away_score="1", home_score="1"))  # MCI scores
    c = live.active_celebration
    assert c is not None and c["scored_side"] == "home" and c["team_abbr"] == "MCI"
    print("PASS: opponent goal celebrated when celebrate_opponent_goals is on")


def test_no_favorites_celebrates_any_goal():
    live = _make_live(favorite_teams=[])  # showing all live games
    live._check_for_goal(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_goal(_game(away_score="0", home_score="1"))  # anyone scores
    assert live.active_celebration is not None, "no favorites -> celebrate any goal"
    print("PASS: with no favorites configured, any goal celebrates")


def test_var_decrement_no_celebration():
    live = _make_live(favorite_teams=["LIV"])
    live._check_for_goal(_game(away_score="2", home_score="1"))  # baseline 2-1
    live._check_for_goal(_game(away_score="1", home_score="1"))  # goal disallowed
    assert live.active_celebration is None, "a score decrement must not celebrate"
    assert live._score_baselines["g1"] == {"away": 1, "home": 1}, "baseline must re-base"
    print("PASS: VAR/disallowed-goal decrement does not celebrate and re-bases")


def test_disabled_never_celebrates():
    live = _make_live(favorite_teams=["LIV"], enabled=False)
    live._check_for_goal(_game(away_score="1", home_score="0"))
    live._check_for_goal(_game(away_score="2", home_score="0"))
    assert live.active_celebration is None and not live._score_baselines
    print("PASS: celebration disabled -> no detection at all")


# ---------------------------------------------------------------------------
# Win detection
# ---------------------------------------------------------------------------
def test_favorite_win_triggers_celebration():
    live = _make_live(favorite_teams=["LIV"])
    live._check_for_goal(_game(away_score="2", home_score="1"))  # tracked live
    live._check_for_win(_game(away_score="2", home_score="1", is_final=True))
    c = live.active_celebration
    assert c is not None and c["kind"] == "win"
    assert c["scored_side"] == "away" and c["team_abbr"] == "LIV"
    assert c["phrase"] == "LIV WINS!"
    assert "g1" not in live._score_baselines, "win must consume the baseline"
    print("PASS: favorite win triggers a win celebration once")


def test_win_without_baseline_suppressed():
    live = _make_live(favorite_teams=["LIV"])
    # Pi started after full time: the game is seen final with no prior baseline.
    live._check_for_win(_game(away_score="2", home_score="1", is_final=True))
    assert live.active_celebration is None, "no baseline -> no win celebration"
    print("PASS: a game first seen already-final does not celebrate a win")


def test_draw_no_win_celebration():
    live = _make_live(favorite_teams=["LIV"])
    live._check_for_goal(_game(away_score="1", home_score="1"))  # tracked live
    live._check_for_win(_game(away_score="1", home_score="1", is_final=True))
    assert live.active_celebration is None, "a draw is not a win"
    print("PASS: a drawn final does not celebrate a win")


def test_favorite_loss_no_celebration():
    live = _make_live(favorite_teams=["LIV"])
    live._check_for_goal(_game(away_score="0", home_score="2"))  # tracked live
    live._check_for_win(_game(away_score="0", home_score="2", is_final=True))
    assert live.active_celebration is None, "favorite lost -> no win celebration"
    print("PASS: a favorite's loss does not celebrate")


# ---------------------------------------------------------------------------
# display() dispatch
# ---------------------------------------------------------------------------
def test_display_dispatches_celebration_then_scorebug():
    import sports

    live = _make_live(favorite_teams=["LIV"], duration=8)
    live.is_enabled = True
    live.current_game = _game()
    calls = []
    live._draw_celebration_layout = lambda c, force_clear=False: calls.append("celebration")
    live._draw_scorebug_layout = lambda g, force_clear=False: calls.append("scorebug")

    # Arm a celebration "now".
    real_time = sports.time.time
    live.active_celebration = {
        "kind": "goal", "game": _game(), "scored_side": "away",
        "team_abbr": "LIV", "away_score": 2, "home_score": 0,
        "started_at": real_time(), "phrase": "LIV SCORES!",
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

    # Real bundled flags (assets/flags) as crests — committed, reproducible
    # inputs, sized like the live golden's loader.
    def _flag_loader(team_id, abbr, path, url=None):
        im = Image.open(path).convert("RGBA")
        im.thumbnail((height, height), Image.Resampling.LANCZOS)
        return im

    live._load_and_resize_logo = _flag_loader

    game = _game(away="USA", home="BRA", away_score="2", home_score="1")
    game["away_logo_path"] = os.path.join(_FLAGS, "USA.png")
    game["home_logo_path"] = os.path.join(_FLAGS, "BRA.png")
    celebration = {
        "kind": "goal",
        "game": game,
        "scored_side": scored_side,
        "team_abbr": "USA" if scored_side == "away" else "BRA",
        "away_score": 2, "home_score": 1,
        "started_at": 0.0,
        "phrase": "GOOOOAAALLL!",
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
        test_favorite_goal_triggers_celebration,
        test_opponent_goal_suppressed_by_default,
        test_opponent_goal_celebrated_when_enabled,
        test_no_favorites_celebrates_any_goal,
        test_var_decrement_no_celebration,
        test_disabled_never_celebrates,
        test_favorite_win_triggers_celebration,
        test_win_without_baseline_suppressed,
        test_draw_no_win_celebration,
        test_favorite_loss_no_celebration,
        test_display_dispatches_celebration_then_scorebug,
        test_has_active_celebration_window,
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
    print("All goal-celebration tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
