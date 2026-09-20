#!/usr/bin/env python3
"""
Regression tests for the live goal/win celebration takeover.

Covers:
- Goal detection from per-side score increments (favorites, opponents, the
  no-favorites fallback), first-sighting suppression, and the decrement a
  waved-off goal produces.
- Win detection on the live->final transition (favorite-only, the tie the feed
  shows mid-shootout, losses, and the "board booted after the final horn"
  no-baseline case).
- display() dispatch: a celebration takes over the screen until it expires,
  then defers to the normal scorebug.
- The team-colour palette read off the scoring side's crest, and the config
  switch that turns it off.
- The 1 FPS contract: unless a league is in scroll mode the core samples this
  plugin once a second, so every frame across the window has to be a finished
  card and the scoring side has to glow on a ramp rather than toggle.
- That the plugin asks the controller for the high-FPS loop while a
  celebration is on screen, and that the config knobs reach the live manager.
- Production-font goldens at the supported sizes.

Crests come from the core's committed assets/sports/nhl_logos (33 files), not
from this plugin, which deliberately bundles none.

Run from the core LEDMatrix tree, or via the runner which sets LEDMATRIX_CORE:
    python scripts/run_plugin_tests.py --core /path/to/LEDMatrix hockey-scoreboard
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

    # The stubs above are plain ModuleTypes, so `from src.common.X import Y`
    # fails with "'src.common' is not a package" even when a real core is on
    # the path. Giving them a __path__ lets genuine submodules -- sports_shared,
    # sports_card -- resolve from the core while the stubbed ones stay stubbed.
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


def _core_root():
    """The LEDMatrix checkout, from the contract run_plugin_tests.py sets."""
    core = os.environ.get("LEDMATRIX_CORE")
    if core and os.path.isdir(os.path.join(core, "src")):
        return core
    for p in sys.path:
        if p and os.path.isdir(os.path.join(p, "src", "common")):
            return p
    return None


def _logo_dir():
    """The core's committed NHL crests, or None.

    This plugin ships no logos of its own -- it reads the core's directory at
    runtime -- so the render tests read the same 33 committed files the board
    would, rather than bundling copies just to have something to draw.
    """
    core = _core_root()
    if not core:
        return None
    d = os.path.join(core, "assets", "sports", "nhl_logos")
    return d if os.path.isdir(d) else None


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
    live.celebration_team_colors = True
    live.celebration_confetti = True
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
    # Reached once display() falls through past the celebration into the
    # inherited scorebug path.
    live.test_mode = False
    live.is_enabled = True
    return live


def _game(gid="g1", away="BOS", home="TOR", away_score="0", home_score="0",
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
    live = _make_live(favorite_teams=["BOS"])
    # First time we see this game it is already 2-0 (in progress at boot).
    live._check_for_goal(_game(away_score="2", home_score="0"))
    assert live.active_celebration is None, "first sighting must not celebrate"
    assert live._score_baselines["g1"] == {"away": 2, "home": 0}
    print("PASS: a first sighting only sets the baseline")


def test_favorite_goal_triggers_celebration():
    live = _make_live(favorite_teams=["BOS"])
    live._check_for_goal(_game(away_score="0", home_score="0"))  # baseline
    live._check_for_goal(_game(away_score="1", home_score="0"))  # BOS scores
    c = live.active_celebration
    assert c is not None, "a favorite's goal must celebrate"
    assert c["kind"] == "goal"
    assert c["scored_side"] == "away"
    assert c["motif"] == "net", "a goal gets the net"
    assert c["phrase"] in ("GOAL!", "BOS GOAL!")
    print("PASS: a favorite's goal arms a celebration")


def test_opponent_goal_suppressed_by_default():
    live = _make_live(favorite_teams=["BOS"])  # TOR is the opponent
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_goal(_game(away_score="0", home_score="1"))
    assert live.active_celebration is None, "opponent goal must not celebrate by default"
    print("PASS: an opponent's goal is suppressed by default")


def test_opponent_goal_celebrated_when_enabled():
    live = _make_live(favorite_teams=["BOS"], opponent_goals=True)
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_goal(_game(away_score="0", home_score="1"))
    assert live.active_celebration is not None, "celebrate_opponent_goals must celebrate"
    assert live.active_celebration["scored_side"] == "home"
    print("PASS: an opponent's goal celebrates when the knob is on")


def test_no_favorites_celebrates_any_goal():
    live = _make_live(favorite_teams=[])
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_goal(_game(away_score="0", home_score="1"))
    assert live.active_celebration is not None, (
        "with no favorites the user opted into this game, so any goal counts")
    print("PASS: with no favorites configured, any goal celebrates")


def test_waved_off_goal_rebases_without_celebrating():
    """Hockey reviews goals and takes them back. A decrement must re-base
    silently, and must not leave a stale baseline that fires later."""
    live = _make_live(favorite_teams=["BOS"])
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_goal(_game(away_score="1", home_score="0"))  # goal
    live.active_celebration = None
    live._check_for_goal(_game(away_score="0", home_score="0"))  # waved off
    assert live.active_celebration is None, "a disallowed goal must not celebrate"
    assert live._score_baselines["g1"] == {"away": 0, "home": 0}
    live._check_for_goal(_game(away_score="1", home_score="0"))  # scored again
    assert live.active_celebration is not None, (
        "after a waved-off goal the next real one still has to celebrate")
    print("PASS: a waved-off goal re-bases without celebrating")


def test_disabled_never_celebrates():
    live = _make_live(favorite_teams=["BOS"], enabled=False)
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_goal(_game(away_score="1", home_score="0"))
    assert live.active_celebration is None
    assert live._score_baselines == {}, "disabled must not even track baselines"
    print("PASS: celebration_enabled=False disables detection entirely")


# ---------------------------------------------------------------------------
# Win detection
# ---------------------------------------------------------------------------
def test_favorite_win_triggers_celebration():
    live = _make_live(favorite_teams=["BOS"])
    live._check_for_goal(_game(away_score="0", home_score="0"))  # seen live
    live._check_for_win(_game(away_score="4", home_score="2", is_final=True))
    c = live.active_celebration
    assert c is not None and c["kind"] == "win"
    assert c["phrase"] == "BOS WINS!"
    assert c["motif"] == "win"
    # Only once: the baseline is consumed.
    live.active_celebration = None
    live._check_for_win(_game(away_score="4", home_score="2", is_final=True))
    assert live.active_celebration is None, "a win must fire only once"
    print("PASS: a favorite's win arms one celebration")


def test_win_without_baseline_suppressed():
    live = _make_live(favorite_teams=["BOS"])
    live._check_for_win(_game(away_score="4", home_score="2", is_final=True))
    assert live.active_celebration is None, (
        "a game first seen already-final was never watched live")
    print("PASS: a game first seen final does not celebrate a win")


def test_tie_no_win_celebration():
    live = _make_live(favorite_teams=["BOS"])
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_win(_game(away_score="2", home_score="2", is_final=True))
    assert live.active_celebration is None, (
        "the feed can show a tie mid-shootout; that is not a win")
    print("PASS: a tied final does not celebrate a win")


def test_favorite_loss_no_celebration():
    live = _make_live(favorite_teams=["BOS"])
    live._check_for_goal(_game(away_score="0", home_score="0"))
    live._check_for_win(_game(away_score="1", home_score="3", is_final=True))
    assert live.active_celebration is None
    print("PASS: a favorite's loss does not celebrate")


# ---------------------------------------------------------------------------
# display() dispatch
# ---------------------------------------------------------------------------
def test_display_dispatches_celebration_then_scorebug():
    import sports

    live = _make_live(favorite_teams=["BOS"], duration=8)
    live.is_enabled = True
    live.current_game = _game()
    calls = []
    live._draw_celebration_layout = lambda c, force_clear=False: calls.append("celebration")
    live._draw_scorebug_layout = lambda g, force_clear=False: calls.append("scorebug")

    now = sports.time.time()
    live.active_celebration = {
        "kind": "goal", "motif": "net", "game": _game(), "scored_side": "away",
        "team_abbr": "BOS", "away_score": 1, "home_score": 0,
        "started_at": now, "phrase": "GOAL!",
    }
    assert live.display() is True and calls == ["celebration"], (
        "an active celebration must take over display()")

    # Force expiry by backdating the start beyond the window.
    live.active_celebration["started_at"] = now - 999
    live.last_game_switch = 0.0
    calls.clear()
    assert live.display() is True and calls == ["scorebug"], (
        "an expired celebration must clear and defer to the scorebug")
    assert live.active_celebration is None, "an expired celebration must be cleared"
    # Clearing must reset the dwell so rotation cannot immediately move off the
    # scoring game (this is the update()/display() expiry race).
    assert live.last_game_switch > 0, (
        "clearing an expired celebration must reset last_game_switch")
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
# Config reaches the live manager
# ---------------------------------------------------------------------------
def test_config_adapter_forwards_celebration_keys():
    """The plugin config lives under `nhl`/`ncaa_mens`/`ncaa_womens`, but the
    live managers read `<league>_scoreboard`. _adapt_config_for_manager must
    forward the celebration keys across that boundary, or the knobs are dead."""
    import manager

    plugin = object.__new__(manager.HockeyScoreboardPlugin)
    plugin.logger = logging.getLogger("cfg")
    plugin.cache_manager = object()  # no config_manager attr -> defaults used
    # The adapter reads these display toggles alongside the config dict.
    plugin.show_records = False
    plugin.show_ranking = False
    plugin.show_odds = False
    plugin.config = {
        "nhl": {
            "enabled": True,
            "celebration_enabled": False,
            "celebration_duration": 12,
            "celebrate_opponent_goals": True,
            "celebration_team_colors": False,
            "celebration_confetti": False,
        },
        "ncaa_mens": {"enabled": True},
    }

    nhl = plugin._adapt_config_for_manager("nhl")["nhl_scoreboard"]
    assert nhl["celebration_enabled"] is False, "celebration_enabled not forwarded"
    assert nhl["celebration_duration"] == 12, "celebration_duration not forwarded"
    assert nhl["celebrate_opponent_goals"] is True
    assert nhl["celebration_team_colors"] is False
    assert nhl["celebration_confetti"] is False

    key = [k for k in plugin._adapt_config_for_manager("ncaa_mens") if k.endswith("_scoreboard")][0]
    ncaa = plugin._adapt_config_for_manager("ncaa_mens")[key]
    assert ncaa["celebration_enabled"] is True, "default celebration_enabled wrong"
    assert ncaa["celebration_duration"] == 8, "default celebration_duration wrong"
    assert ncaa["celebrate_opponent_goals"] is False
    assert ncaa["celebration_team_colors"] is True
    assert ncaa["celebration_confetti"] is True
    print("PASS: the config adapter forwards the celebration keys to the managers")


def test_manager_asks_for_high_fps_while_celebrating():
    """Without needs_high_fps the core falls back to enable_scrolling, which is
    false on a switch-mode board -- so the confetti would be sampled once a
    second. The plugin has to ask."""
    import manager

    plugin = object.__new__(manager.HockeyScoreboardPlugin)
    plugin.logger = logging.getLogger("fps")
    plugin.enable_scrolling = False
    plugin.is_enabled = True
    plugin._league_registry = {"nhl": {"enabled": True}}

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
    celebrating[0] = False
    plugin.enable_scrolling = True
    assert plugin.needs_high_fps is True, "scrolling boards keep their behaviour"

    # The controller reads this attribute bare, so it must never raise.
    broken = object.__new__(manager.HockeyScoreboardPlugin)
    assert broken.needs_high_fps is False, "needs_high_fps raised on a bare instance"
    print("PASS: the manager asks for high FPS while a celebration is on screen")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render_celebration(scored_side, width=128, height=32, elapsed=2.5,
                        motif="net", kind="goal", phrase="GOAL!",
                        away="BOS", home="TOR", team_colors=True, confetti=True):
    """Render a celebration screen deterministically via production fonts."""
    import sports
    from sports import SportsCore

    logos = _logo_dir()

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

    def _logo_loader(team_id, abbr, path, url=None):
        im = Image.open(os.path.join(logos, f"{abbr}.png")).convert("RGBA")
        im.thumbnail((height, height), Image.Resampling.LANCZOS)
        return im

    live._load_and_resize_logo = _logo_loader

    game = _game(away=away, home=home, away_score="3", home_score="2")
    celebration = {
        "kind": kind,
        "motif": motif,
        "game": game,
        "scored_side": scored_side,
        "team_abbr": away if scored_side == "away" else home,
        "away_score": 3, "home_score": 2,
        "started_at": 0.0,
        "phrase": phrase,
    }

    saved = sports.time
    sports.time = types.SimpleNamespace(time=lambda: elapsed)
    try:
        live._draw_celebration_layout(celebration, force_clear=True)
    finally:
        sports.time = saved
    return live.display_manager.image.convert("RGB")


def _brightest(img, box=None):
    region = img.crop(box) if box else img
    return max(region.convert("RGB").getextrema()[i][1] for i in range(3))


_REAL_FONTS = (
    os.path.join("assets", "fonts", "PressStart2P-Regular.ttf"),
    os.path.join("assets", "fonts", "4x6-font.ttf"),
)


def _font_path(rel):
    """Resolve a core-shipped font the way the plugin itself does.

    run_plugin_tests.py runs each test with cwd set to the plugin directory,
    so probing these paths against the cwd makes the golden checks skip under
    the very runner that exists to run them. LEDMATRIX_CORE is the absolute
    contract that runner provides for exactly this case.
    """
    if os.path.exists(rel):
        return rel
    core = _core_root()
    if core:
        candidate = os.path.join(core, rel)
        if os.path.exists(candidate):
            return candidate
    return rel


def _renderable():
    return _logo_dir() is not None and all(
        os.path.exists(_font_path(p)) for p in _REAL_FONTS)


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
            f"golden drift for {name} ({img.width}x{img.height}): max delta={worst}")


def test_celebration_renders_score_and_side_highlight():
    if not _renderable():
        print("SKIP: celebration render (needs the core's fonts and NHL crests)")
        return
    away = _render_celebration("away")
    assert _brightest(away) > 40, "celebration screen is blank"
    home = _render_celebration("home")
    assert ImageChops.difference(away, home).getbbox() is not None, (
        "away-scored and home-scored renders are identical -- the highlight is "
        "not following the scoring side")
    print("PASS: the celebration renders a score with a side-dependent highlight")


def test_team_colors_can_be_switched_off():
    if not _renderable():
        print("SKIP: team-colour switch (needs the core's fonts and NHL crests)")
        return
    lit = _render_celebration("away", team_colors=True)
    plain = _render_celebration("away", team_colors=False)
    assert ImageChops.difference(lit, plain).getbbox() is not None, (
        "celebration_team_colors=False renders identically to True")
    print("PASS: celebration_team_colors switches the crest palette off")


def test_the_net_is_its_own_scenery():
    """A goal gets the net and a win gets the sunburst, so the two must differ."""
    if not _renderable():
        print("SKIP: motif comparison (needs the core's fonts and NHL crests)")
        return
    net = _render_celebration("away", motif="net", confetti=False)
    win = _render_celebration("away", motif="win", kind="win",
                              phrase="BOS WINS!", confetti=False)
    assert ImageChops.difference(net, win).getbbox() is not None, (
        "the net and the sunburst render identically")
    print("PASS: the net and the win sunburst are different scenery")


def test_every_celebration_frame_is_a_finished_card():
    """On a switch-mode board the core samples this plugin once a second, so
    any single frame may be the only one a viewer sees. Every frame across the
    whole window has to carry the headline and the score -- no blank frame and
    nothing clipped off the top by an entry animation."""
    if not _renderable():
        print("SKIP: frame contract (needs the core's fonts and NHL crests)")
        return
    # Every panel size the core's safety harness renders.
    for w, h in ((64, 32), (128, 32), (64, 64), (96, 48), (128, 64),
                 (256, 32), (128, 96), (256, 128)):
        for elapsed in [0.0] + [i + 0.5 for i in range(8)]:
            img = _render_celebration("away", w, h, elapsed=elapsed)
            headline = img.crop((0, 0, w, max(2, h // 4)))
            assert _brightest(img) > 40, (
                f"{w}x{h} at t={elapsed}s: the panel is effectively blank")
            assert _brightest(headline) > 60, (
                f"{w}x{h} at t={elapsed}s: no headline on the top rows -- a "
                "frame that lands here shows a card with no message on it")
    print("PASS: every celebration frame is a finished card")


def test_the_scoring_side_glows_rather_than_toggling():
    """The scoring digits breathe on a continuous ramp. A binary flash aliases
    into a colour that changes at random once a second; a ramp cannot."""
    if not _renderable():
        print("SKIP: glow ramp (needs the core's fonts and NHL crests)")
        return
    frames = [
        _render_celebration("away", elapsed=t, confetti=False)
        for t in (0.9, 1.9, 2.9, 3.9, 4.9, 5.9)
    ]
    assert len({f.tobytes() for f in frames}) > 2, (
        "sampled once a second the score only ever showed two states -- the "
        "highlight is toggling, not breathing")
    print("PASS: the scoring side glows on a ramp rather than toggling")


def test_golden_celebration_screen():
    """Lock the celebration takeover to committed production-font goldens."""
    if not _renderable():
        print("SKIP: golden celebration screen (needs the core's fonts and the "
              "core's committed NHL crests; run via run_plugin_tests.py --core)")
        return
    update = os.environ.get("UPDATE_GOLDEN") == "1"
    for w, h in ((128, 32), (128, 64), (256, 128)):
        _check_golden("celebration_goal", _render_celebration("away", w, h), update)
    _check_golden(
        "celebration_win",
        _render_celebration("away", 128, 32, motif="win", kind="win",
                            phrase="BOS WINS!"),
        update)
    print("PASS: golden celebration screen" + (" (regenerated)" if update else ""))


def main():
    tests = [
        test_first_sighting_sets_baseline_no_celebration,
        test_favorite_goal_triggers_celebration,
        test_opponent_goal_suppressed_by_default,
        test_opponent_goal_celebrated_when_enabled,
        test_no_favorites_celebrates_any_goal,
        test_waved_off_goal_rebases_without_celebrating,
        test_disabled_never_celebrates,
        test_favorite_win_triggers_celebration,
        test_win_without_baseline_suppressed,
        test_tie_no_win_celebration,
        test_favorite_loss_no_celebration,
        test_display_dispatches_celebration_then_scorebug,
        test_has_active_celebration_window,
        test_config_adapter_forwards_celebration_keys,
        test_manager_asks_for_high_fps_while_celebrating,
        test_celebration_renders_score_and_side_highlight,
        test_team_colors_can_be_switched_off,
        test_the_net_is_its_own_scenery,
        test_every_celebration_frame_is_a_finished_card,
        test_the_scoring_side_glows_rather_than_toggling,
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
