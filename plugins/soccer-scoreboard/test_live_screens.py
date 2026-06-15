#!/usr/bin/env python3
"""
Regression tests for the soccer live screens.

Covers two bugs where live soccer games failed to render a real scorebug:

1. Scroll mode passed ``plugin_dir`` into ``GameRenderer``'s ``logo_cache``
   parameter, corrupting the cache so every logo load failed and
   ``render_game_card`` fell back to the ``away@home`` text placeholder
   ("just the two team names").

2. Switch/static mode had no live ``_draw_scorebug_layout`` on ``SportsLive``,
   so live games fell through to ``SportsCore``'s placeholder (status text only)
   and rendered effectively nothing.

Run with the core venv:
    /Users/ron/code/led-matrix/LEDMatrix/.venv/bin/python test_live_screens.py
"""

import os
import sys
import types
import logging
import tempfile

from PIL import Image, ImageFont, ImageChops

# Make the plugin's own modules importable when run from anywhere.
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

FIXTURES = os.path.join(PLUGIN_DIR, "test", "fixtures")
GOLDEN = os.path.join(PLUGIN_DIR, "test", "golden")

# sports.py imports ``from src.logo_downloader import ...`` at module load.
# We only need the names to exist for import; the test never builds a real
# manager (it uses __new__), so the stub is never invoked.
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


def _concrete_live(sports_live_cls):
    """Return a concrete SportsLive subclass (the base is abstract)."""
    class _ConcreteLive(sports_live_cls):
        def _fetch_data(self, *a, **k):
            return None

        def _extract_game_details(self, *a, **k):
            return None

    return _ConcreteLive


def _make_logo_file(color):
    """Write a tiny opaque PNG and return its path."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.new("RGBA", (16, 16), color).save(path)
    return path


def _is_mostly_black(img, box):
    """True if every pixel inside box is (near) black."""
    region = img.crop(box).convert("RGB")
    return max(region.getextrema()[i][1] for i in range(3)) < 10


class _FakeScrollHelper:
    """Minimal ScrollHelper stand-in for exercising prepare_scroll_content."""
    total_scroll_width = 100
    calculated_duration = 30
    cache_type = None

    def clear_cache(self):
        pass

    def create_scrolling_image(self, *a, **k):
        pass


def test_scroll_passes_real_logo_cache_to_renderer():
    """ScrollDisplay must hand GameRenderer a real (dict) logo cache.

    Reproduces the scroll bug: the call site passed ``plugin_dir`` into the
    ``logo_cache`` parameter, so every logo load failed and live cards rendered
    the ``away@home`` text placeholder ("just the two team names"). Driving the
    real prepare_scroll_content with the real GameRenderer + on-disk logos, a
    correct call populates the shared dict cache with both teams.
    """
    import scroll_display

    home_logo = _make_logo_file((255, 0, 0, 255))
    away_logo = _make_logo_file((0, 0, 255, 255))

    game = {
        "home_abbr": "MCI", "home_id": "1", "home_logo_path": home_logo,
        "away_abbr": "LIV", "away_id": "2", "away_logo_path": away_logo,
        "home_score": "2", "away_score": "1",
        "period_text": "2H 75'", "clock": "75'",
        "is_live": True, "league": "eng.1",
    }

    sd = scroll_display.ScrollDisplay.__new__(scroll_display.ScrollDisplay)
    sd.config = {}
    sd.display_height = 32
    sd.plugin_dir = tempfile.gettempdir()
    sd._logo_cache = {}
    sd.logger = logging.getLogger("t")
    sd._separator_icons = {}
    sd.scroll_helper = _FakeScrollHelper()

    ok = sd.prepare_scroll_content([game], "live", ["eng.1"])

    assert ok, "prepare_scroll_content returned False (no cards rendered)"
    # A correct call shares the dict cache, so loaded logos land in it. The bug
    # passed plugin_dir instead, leaving this dict untouched.
    assert "MCI" in sd._logo_cache and "LIV" in sd._logo_cache, (
        f"logos not loaded into shared cache: {list(sd._logo_cache)}"
    )
    print("PASS: scroll passes a real dict logo cache (logos load, no placeholder)")


def test_live_layout_is_overridden_and_draws_score():
    """SportsLive must define its own live scorebug, not inherit the placeholder."""
    from sports import SportsCore, SportsLive

    # Structural guard: the live class must override the base placeholder.
    assert SportsLive._draw_scorebug_layout is not SportsCore._draw_scorebug_layout, (
        "SportsLive still uses the SportsCore placeholder _draw_scorebug_layout"
    )

    live_cls = _concrete_live(SportsLive)

    class _FakeMatrix:
        width, height = 128, 32

    class _FakeDisplayManager:
        def __init__(self):
            self.matrix = _FakeMatrix()
            self.image = Image.new("RGB", (128, 32), (0, 0, 0))
            self.updated = False

        def clear(self):
            self.image = Image.new("RGB", (128, 32), (0, 0, 0))

        def update_display(self):
            self.updated = True

    live = object.__new__(live_cls)
    live.display_manager = _FakeDisplayManager()
    live.display_width = 128
    live.display_height = 32
    live.config = {}
    live.show_records = False
    live.show_ranking = False
    live._team_rankings_cache = {}
    live.logger = logging.getLogger("t")
    font = ImageFont.load_default()
    live.fonts = {"score": font, "time": font, "status": font, "detail": font}
    live._load_and_resize_logo = lambda *a, **k: Image.new("RGBA", (12, 12), (0, 255, 0, 255))

    game = {
        "home_abbr": "MCI", "home_id": "1", "home_logo_path": "x",
        "away_abbr": "LIV", "away_id": "2", "away_logo_path": "y",
        "home_score": "2", "away_score": "1",
        "period_text": "2H 75'", "clock": "75'", "is_live": True,
    }

    live._draw_scorebug_layout(game, force_clear=True)

    assert live.display_manager.updated, "update_display was never called"
    out = live.display_manager.image
    # The score is drawn low-center; the old placeholder left that area blank.
    assert not _is_mostly_black(out, (40, 16, 88, 32)), (
        "score region is blank — live scorebug did not render the score"
    )
    print("PASS: live switch-mode scorebug draws a score")


def test_live_scroll_card_ignores_game_date():
    """A live scroll card must not draw the bottom date line.

    On short panels (128x32) period + score + date is three stacked text rows and
    the date clips off the bottom. A live game's date is redundant, so the card
    must render identically whether or not game_date is present.
    """
    from game_renderer import GameRenderer

    base = {
        "home_abbr": "MCI", "home_id": "1",
        "home_logo_path": os.path.join(FIXTURES, "logos", "MCI.png"),
        "away_abbr": "LIV", "away_id": "2",
        "away_logo_path": os.path.join(FIXTURES, "logos", "LIV.png"),
        "home_score": "2", "away_score": "1",
        "period_text": "2H 75'", "clock": "75'", "is_live": True,
    }

    def render(g):
        gr = GameRenderer(128, 32, {}, logo_cache={}, custom_logger=logging.getLogger("t"))
        return gr.render_game_card(g, "live").convert("RGB")

    no_date = render(dict(base))
    with_date = render(dict(base, game_date="Jun 14"))
    assert ImageChops.difference(no_date, with_date).getbbox() is None, (
        "live scroll card changed when game_date was added — the date line is "
        "still drawn and overflows the bottom on short panels"
    )
    print("PASS: live scroll card ignores game_date (no bottom overflow)")


def test_live_status_text_variants():
    """_get_live_status_text prefers halftime/break, then period_text, clock, LIVE."""
    from sports import SportsLive

    live_cls = _concrete_live(SportsLive)
    live = object.__new__(live_cls)
    assert live._get_live_status_text({"is_halftime": True, "period_text": "1H"}) == "HALF"
    assert live._get_live_status_text({"is_period_break": True, "status_text": "ET"}) == "ET"
    assert live._get_live_status_text({"period_text": "2H 75'"}) == "2H 75'"
    assert live._get_live_status_text({"clock": "75'"}) == "75'"
    assert live._get_live_status_text({}) == "LIVE"
    print("PASS: live status text variants")


# ---------------------------------------------------------------------------
# Golden-image coverage of the live screens
#
# These render through the *production* font-loading path (the plugin's own
# _load_fonts, reading assets/fonts), so a font regression — a broken loader, a
# changed/removed font — shows up as golden drift. Fonts are NOT copied into a
# fixture (that would mask exactly those bugs); they resolve relative to the cwd,
# which is why these run from the core LEDMatrix tree (the same place the safety
# harness runs). Logos are the one bundled fixture: they're per-team assets
# downloaded per-install, so an in-repo copy is reproducible without hiding a
# rendering-code bug.
#
# Run / regenerate from the core tree:
#     cd /path/to/LEDMatrix
#     .venv/bin/python <plugin>/test_live_screens.py            # verify
#     UPDATE_GOLDEN=1 .venv/bin/python <plugin>/test_live_screens.py   # refresh
# ---------------------------------------------------------------------------

# Pinned live game used for every golden render.
GOLDEN_GAME = {
    "home_abbr": "MCI", "home_id": "1",
    "home_logo_path": os.path.join(FIXTURES, "logos", "MCI.png"),
    "away_abbr": "LIV", "away_id": "2",
    "away_logo_path": os.path.join(FIXTURES, "logos", "LIV.png"),
    "home_score": "2", "away_score": "1",
    "period_text": "2H 75'", "clock": "75'",
    "is_live": True, "league": "eng.1",
}

# Pinned recent / upcoming games for golden renders. These use real bundled
# World Cup flags (assets/flags) so the crests are reproducible without hiding a
# rendering-code bug, mirroring the live golden's use of the fixture logos.
_FLAGS = os.path.join(PLUGIN_DIR, "assets", "flags")
GOLDEN_RECENT = {
    "home_abbr": "USA", "home_id": "1", "home_logo_path": os.path.join(_FLAGS, "USA.png"),
    "away_abbr": "BRA", "away_id": "2", "away_logo_path": os.path.join(_FLAGS, "BRA.png"),
    "home_score": "2", "away_score": "1",
    "period_text": "Final", "game_date": "6/12", "league": "fifa.world",
}
GOLDEN_UPCOMING = {
    "home_abbr": "USA", "home_id": "1", "home_logo_path": os.path.join(_FLAGS, "USA.png"),
    "away_abbr": "MEX", "away_id": "2", "away_logo_path": os.path.join(_FLAGS, "MEX.png"),
    "game_time": "3:00PM", "game_date": "6/14", "league": "fifa.world",
}


def _flag_loader(height):
    """Logo loader that reads the real bundled flags, sized like the plugin does."""
    def _loader(team_id, abbr, path, url=None):
        im = Image.open(path).convert("RGBA")
        im.thumbnail((height, height), Image.Resampling.LANCZOS)
        return im
    return _loader


# The real fonts the production loader reads, relative to cwd. When these aren't
# resolvable the loader silently falls back to PIL's default font, which would
# make goldens meaningless — so the golden test skips instead of rendering with
# the wrong font.
_REAL_FONTS = (
    os.path.join("assets", "fonts", "PressStart2P-Regular.ttf"),
    os.path.join("assets", "fonts", "4x6-font.ttf"),
)


def _real_fonts_available():
    return all(os.path.exists(p) for p in _REAL_FONTS)


def _render_scroll_live(height):
    """Render the scroll-mode live card via the real GameRenderer (production fonts)."""
    from game_renderer import GameRenderer
    gr = GameRenderer(128, height, {}, logo_cache={}, custom_logger=logging.getLogger("g"))
    return gr.render_game_card(GOLDEN_GAME, "live").convert("RGB")


def _render_switch_live(width, height):
    """Render the switch-mode live scorebug via SportsLive (production fonts)."""
    from sports import SportsCore, SportsLive

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

    live_cls = _concrete_live(SportsLive)
    o = object.__new__(live_cls)
    o.display_manager = _FakeDisplayManager()
    o.display_width = width
    o.display_height = height
    o.config = {}
    o.show_records = False
    o.show_ranking = False
    o._team_rankings_cache = {}
    o.logger = logging.getLogger("g")
    # Production font loading — same code path the running plugin uses.
    o.fonts = SportsCore._load_fonts(o)

    def _loader(team_id, abbr, path, url=None):
        im = Image.open(path).convert("RGBA")
        im.thumbnail((height, height), Image.Resampling.LANCZOS)
        return im

    o._load_and_resize_logo = _loader
    o._draw_scorebug_layout(GOLDEN_GAME, force_clear=True)
    return o.display_manager.image.convert("RGB")


def _check_golden(name, img, update):
    """Compare img to a committed golden (or write it when update=True)."""
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


def test_golden_live_screens():
    """Render the live scroll + switch screens and lock them to committed goldens."""
    if not _real_fonts_available():
        print("SKIP: golden live screens (run from the core LEDMatrix tree so "
              "assets/fonts resolves; production fonts are required, not bundled)")
        return
    update = os.environ.get("UPDATE_GOLDEN") == "1"
    for h in (32, 64):
        _check_golden("live_scroll", _render_scroll_live(h), update)
    for w, h in ((128, 32), (128, 64)):
        _check_golden("live_switch", _render_switch_live(w, h), update)
    print("PASS: golden live screens" + (" (regenerated)" if update else ""))


def test_golden_recent_upcoming_screens():
    """Lock the recent (final + date) and upcoming (league header) switch screens."""
    if not _real_fonts_available():
        print("SKIP: golden recent/upcoming screens (run from the core LEDMatrix "
              "tree so assets/fonts resolves; production fonts are required)")
        return
    update = os.environ.get("UPDATE_GOLDEN") == "1"
    for w, h in ((128, 32), (128, 64)):
        recent = _render_switch_card(
            "SportsRecent", dict(GOLDEN_RECENT),
            width=w, height=h, logo_loader=_flag_loader(h),
        )
        _check_golden("recent_switch", recent, update)
        upcoming = _render_switch_card(
            "SportsUpcoming", dict(GOLDEN_UPCOMING), league_name="FIFA World Cup",
            width=w, height=h, logo_loader=_flag_loader(h),
        )
        _check_golden("upcoming_switch", upcoming, update)
    print("PASS: golden recent/upcoming screens" + (" (regenerated)" if update else ""))


def _render_switch_card(base_name, game, league_name=None, width=128, height=32,
                        logo_loader=None):
    """Render a switch-mode card for SportsRecent/SportsUpcoming via __new__."""
    import sports as _sports

    base = getattr(_sports, base_name)
    cls = type(
        f"_Concrete{base_name}", (base,),
        {"_fetch_data": lambda self, *a, **k: None,
         "_extract_game_details": lambda self, *a, **k: None},
    )

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

    o = object.__new__(cls)
    o.display_manager = _FakeDisplayManager()
    o.display_width = width
    o.display_height = height
    o.config = {}
    o.show_records = False
    o.show_ranking = False
    o._team_rankings_cache = {}
    o.logger = logging.getLogger("g")
    o.fonts = _sports.SportsCore._load_fonts(o)
    if league_name is not None:
        o.league_name = league_name
    o._load_and_resize_logo = logo_loader or (
        lambda *a, **k: Image.new("RGBA", (12, 12), (0, 255, 0, 255))
    )
    o._draw_scorebug_layout(game, force_clear=True)
    return o.display_manager.image.convert("RGB")


def test_recent_card_shows_game_date():
    """The recent (final) card must render the game date (parity with baseball)."""
    base = {
        "home_abbr": "USA", "home_id": "1", "home_logo_path": "x",
        "away_abbr": "BRA", "away_id": "2", "away_logo_path": "y",
        "home_score": "2", "away_score": "1", "period_text": "Final",
    }
    no_date = _render_switch_card("SportsRecent", dict(base))
    with_date = _render_switch_card("SportsRecent", dict(base, game_date="6/12"))
    assert ImageChops.difference(no_date, with_date).getbbox() is not None, (
        "recent card is identical with/without game_date — the date is not drawn"
    )
    print("PASS: recent card shows the game date")


def test_upcoming_card_shows_league_name():
    """The upcoming card header must reflect the league name when available."""
    game = {
        "home_abbr": "USA", "home_id": "1", "home_logo_path": "x",
        "away_abbr": "MEX", "away_id": "2", "away_logo_path": "y",
        "game_time": "3:00PM", "game_date": "6/14",
    }
    with_league = _render_switch_card("SportsUpcoming", dict(game), league_name="FIFA World Cup")
    fallback = _render_switch_card("SportsUpcoming", dict(game), league_name=None)
    assert ImageChops.difference(with_league, fallback).getbbox() is not None, (
        "upcoming header did not change with league_name set — league not shown"
    )
    print("PASS: upcoming card shows the league name")


def main():
    tests = [
        test_scroll_passes_real_logo_cache_to_renderer,
        test_live_layout_is_overridden_and_draws_score,
        test_live_scroll_card_ignores_game_date,
        test_live_status_text_variants,
        test_recent_card_shows_game_date,
        test_upcoming_card_shows_league_name,
        test_golden_live_screens,
        test_golden_recent_upcoming_screens,
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
    print("All soccer live-screen tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
