#!/usr/bin/env python3
"""
Regression tests for the opt-in adaptive layout mode (layout_mode: "adaptive").

Guards the two promises the migration made:
1. CLASSIC IS UNTOUCHED — with the default config (layout_mode absent or
   "classic") the renderer takes the classic path and renders byte-identically
   to a renderer that has never heard of adaptive layout.
2. ADAPTIVE SCALES + RESPECTS CUSTOMIZATION — adaptive renders fill more of a
   big panel than classic, user-configured fonts win over the ladder, and
   customization.layout x/y offsets translate elements.

Golden images live in test/golden-adaptive/<WxH>/<name>.png. Regenerate after
an intentional visual change with UPDATE_GOLDEN=1.

Run from the core LEDMatrix tree (needs src.* and assets/fonts), e.g.:
    cd /path/to/LEDMatrix
    python -m pytest /path/to/football-scoreboard/test_adaptive_layout_mode.py -q
"""

import os
import sys

import pytest
from PIL import Image, ImageChops

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

GOLDEN_ADAPTIVE = os.path.join(PLUGIN_DIR, "test", "golden-adaptive")
LOGOS = os.path.join(PLUGIN_DIR, "assets", "sports", "nfl_logos")

# test_score_celebration.py's standalone-run shim replaces sys.modules["src"]
# with a fake package, which clobbers src.adaptive_layout when both files
# share a pytest session. Evict the stub (the real core package is importable
# here — this file runs from the core tree), then import the real module so
# the shim won't reinstall itself.
_src = sys.modules.get("src")
if _src is not None and not hasattr(_src, "__path__"):
    for _k in [k for k in list(sys.modules) if k == "src" or k.startswith("src.")]:
        del sys.modules[_k]
import src.logo_downloader  # noqa: E402,F401

from game_renderer import ADAPTIVE_AVAILABLE, GameRenderer  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ADAPTIVE_AVAILABLE,
    reason="core without src.adaptive_layout — adaptive mode falls back to classic",
)

SIZES = [(128, 32), (128, 64), (256, 128)]


def _game(**overrides):
    game = {
        "home_id": "1", "home_abbr": "KC",
        "home_logo_path": os.path.join(LOGOS, "KC.png"),
        "away_id": "2", "away_abbr": "GB",
        "away_logo_path": os.path.join(LOGOS, "GB.png"),
        "home_score": "21", "away_score": "17",
        "period_text": "Q3", "clock": "8:42",
        "is_live": True,
        "down_distance_text": "3rd & 7",
        "down_distance_text_long": "3rd & 7 at KC 35",
        "possession_indicator": "home",
        "home_timeouts": 2, "away_timeouts": 3,
        "league": "nfl",
    }
    game.update(overrides)
    return game


def _renderer(width, height, config=None):
    return GameRenderer(width, height, config or {})


def _ink_ratio(img):
    lit = img.convert("L").point(lambda p: 255 if p > 16 else 0)
    return sum(1 for p in lit.getdata() if p) / (img.width * img.height)


class TestClassicUntouched:
    @pytest.mark.parametrize("config", [{}, {"layout_mode": "classic"}])
    def test_default_takes_classic_path(self, config):
        r = _renderer(128, 32, config)
        assert not r._adaptive

    def test_classic_render_byte_identical(self):
        """A default renderer must produce the same pixels as one explicitly
        set to classic — proving the adaptive changes are inert by default."""
        game = _game()
        for w, h in SIZES:
            baseline = _renderer(w, h, {}).render_game_card(game, "live")
            classic = _renderer(w, h, {"layout_mode": "classic"}).render_game_card(game, "live")
            assert ImageChops.difference(baseline, classic).getbbox() is None


class TestAdaptiveMode:
    def test_adaptive_flag(self):
        assert _renderer(128, 32, {"layout_mode": "adaptive"})._adaptive

    def test_adaptive_text_scales_up_on_big_panels(self):
        """Classic renders a fixed 10px score on every panel; adaptive scales
        it proportionally to the panel HEIGHT (target = 10px * height/32,
        nearest crisp rung at or below that) rather than maximizing to
        whatever the region merely allows — maximizing let the score
        balloon large enough to visually overlap/obscure the team logos
        next to it. Height (not LayoutContext's conservative min-of-both-
        axes scale) is the reference because the card's own logo_slot
        already tracks height alone, and text should match that. 256x128
        is 4x the design height, so target=40 -> capped at the largest
        crisp rung, 32 (which also happens to match the region max here —
        confirming it's a deliberate height-proportional pick, not an
        accidental one, matters more on a panel like 128x64 where they
        diverge — see the golden images)."""
        from src.adaptive_layout import Region, scoreboard_regions
        from game_renderer import ADAPTIVE_LADDER_HEADLINE

        r = _renderer(256, 128, {"layout_mode": "adaptive"})
        regs = scoreboard_regions(Region(0, 0, 256, 128), ctx=r._ctx)
        fit = r._fit_element('score', "17-21", regs.score_area,
                             ADAPTIVE_LADDER_HEADLINE)
        assert fit.size_px == 32
        assert fit.family == "press_start"  # still a crisp rung

        game = _game()
        classic = _renderer(256, 128, {}).render_game_card(game, "live")
        adaptive = r.render_game_card(game, "live")
        assert _ink_ratio(adaptive) > _ink_ratio(classic)

    def test_score_scales_with_height_not_width(self):
        """128x64 (height doubled, width unchanged from the 128x32 design)
        must still grow the score — logo_slot = min(height, width // 2)
        already doubles the logos here, so text sized by the conservative
        min(width_ratio, height_ratio) (which stays 1.0 since width didn't
        grow) would look under-scaled next to them."""
        from src.adaptive_layout import Region, scoreboard_regions
        from game_renderer import ADAPTIVE_LADDER_HEADLINE

        r = _renderer(128, 64, {"layout_mode": "adaptive"})
        assert r._ctx.scale == 1.0  # the conservative default would pick 8px
        regs = scoreboard_regions(Region(0, 0, 128, 64), ctx=r._ctx)
        fit = r._fit_element('score', "17-21", regs.score_area,
                             ADAPTIVE_LADDER_HEADLINE)
        assert fit.size_px == 16  # height/32 = 2 -> target 20 -> nearest rung 16

    def test_user_font_wins_over_ladder(self):
        """An explicitly configured score font must be used verbatim."""
        cfg = {"layout_mode": "adaptive",
               "customization": {"score_text": {"font_size": 10}}}
        r = _renderer(256, 128, cfg)
        from src.adaptive_layout import Region
        fit = r._fit_element("score", "17-21", Region(0, 0, 100, 100),
                             ladder=None)
        assert fit.family == "user"
        # ladder on this panel would have picked something far larger than 10px
        assert fit.height <= 12

    def test_user_offsets_translate_elements(self):
        """customization.layout offsets must shift the rendered element."""
        game = _game(is_live=False, period_text="Final")
        base_cfg = {"layout_mode": "adaptive"}
        moved_cfg = {"layout_mode": "adaptive",
                     "customization": {"layout": {"score": {"x_offset": 6}}}}
        base = _renderer(128, 32, base_cfg).render_game_card(game, "recent")
        moved = _renderer(128, 32, moved_cfg).render_game_card(game, "recent")
        assert ImageChops.difference(base, moved).getbbox() is not None

    def test_semantic_colors_preserved(self):
        """Scoring-event gold must survive the adaptive path."""
        game = _game(scoring_event="TOUCHDOWN")
        img = _renderer(128, 64, {"layout_mode": "adaptive"}).render_game_card(game, "live")
        colors = {img.getpixel((x, y)) for x in range(img.width)
                  for y in range(img.height)}
        assert (255, 215, 0) in colors


class TestAdaptiveGoldens:
    """Visual-drift net for the adaptive path (classic is covered by the
    celebration goldens in test/golden/)."""

    @pytest.mark.parametrize("w,h", SIZES)
    @pytest.mark.parametrize("game_type,game_kwargs", [
        ("live", {}),
        ("recent", {"is_live": False, "period_text": "Final",
                    "game_date": "10/12"}),
        ("upcoming", {"is_live": False, "period_text": "",
                      "game_time": "7:30PM", "game_date": "10/12",
                      "home_score": "0", "away_score": "0"}),
    ])
    def test_golden(self, w, h, game_type, game_kwargs):
        img = _renderer(w, h, {"layout_mode": "adaptive"}).render_game_card(
            _game(**game_kwargs), game_type)
        path = os.path.join(GOLDEN_ADAPTIVE, f"{w}x{h}", f"{game_type}.png")
        if os.environ.get("UPDATE_GOLDEN") == "1":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            img.save(path, format="PNG")
            return
        assert os.path.exists(path), f"missing golden {path} (run with UPDATE_GOLDEN=1)"
        with Image.open(path) as golden:
            assert ImageChops.difference(
                img.convert("RGB"), golden.convert("RGB")).getbbox() is None, \
                f"adaptive render drifted from {path}"


class TestLadderCrispness:
    """Every rung in the adaptive ladders must render with zero antialiasing.

    PIL antialiases TTF outlines by default; PressStart2P only rasterizes
    crisply at exact multiples of its 8px design grid, and not every
    'pixel-style' font is crisp at any size at all. An earlier version of
    these ladders included press_start@12/10 (not multiples of 8, added to
    match classic's fixed 10px score) and '5by7.regular'@8 (never crisp at
    any tested size) — both shipped visibly blurry text on small panels.
    """

    def test_headline_ladder_is_crisp(self):
        from game_renderer import ADAPTIVE_LADDER_HEADLINE
        from src.adaptive_layout import measure_font_crispness
        from src.font_manager import FontManager

        fm = FontManager({})
        offenders = []
        for step in ADAPTIVE_LADDER_HEADLINE:
            font = fm.get_font(step.family, step.size_px)
            c = measure_font_crispness(font, "17-21")
            if c > 0.02:
                offenders.append(f"{step.family}@{step.size_px}px: {c:.1%} antialiased")
        assert not offenders, "Blurry rung(s):\n  " + "\n  ".join(offenders)

    def test_text_ladder_is_crisp(self):
        from game_renderer import ADAPTIVE_LADDER_TEXT
        from src.adaptive_layout import measure_font_crispness
        from src.font_manager import FontManager

        fm = FontManager({})
        offenders = []
        for step in ADAPTIVE_LADDER_TEXT:
            font = fm.get_font(step.family, step.size_px)
            c = measure_font_crispness(font, "3rd & 7")
            if c > 0.02:
                offenders.append(f"{step.family}@{step.size_px}px: {c:.1%} antialiased")
        assert not offenders, "Blurry rung(s):\n  " + "\n  ".join(offenders)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
