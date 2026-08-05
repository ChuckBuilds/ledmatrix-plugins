#!/usr/bin/env python3
"""
Regression tests for pixel-perfect leaderboard rendering.

The leaderboard draws pixel fonts and team logos on a 1:1 LED matrix, where
there is no sub-pixel to hide a blend in: a partially-lit pixel is a visibly
dim LED, and a row of them around every glyph and logo is what made this
display read as blurry. Three properties keep it crisp, and each is asserted
here:

1. Text uses ``fontmode = "1"`` — no anti-aliased greys at any font size.
2. Default font sizes land on the font's pixel grid (multiples of 8 for
   Press Start 2P), so glyph pixels map 1:1 onto panel pixels.
3. Logos fit inside the panel and get hard alpha edges instead of a halo.

A fourth test covers the layout: the measured strip width has to match what is
actually drawn, or the ticker ends up padded with dead space or clipped short
of the last team.

Run from a LEDMatrix (core) checkout so the bundled fonts/logos resolve:
    cd /path/to/LEDMatrix && python -m pytest \\
        /path/to/ledmatrix-plugins/plugins/ledmatrix-leaderboard/test_pixel_perfect.py
"""

import logging
import os
import sys

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from image_renderer import ImageRenderer  # noqa: E402

LOGGER = logging.getLogger("test_pixel_perfect")

TEAMS = ["KC", "BUF", "PHI", "DET", "BAL", "SF", "GB", "HOU", "LAR", "MIN"]


def _teams(count=len(TEAMS)):
    return [
        {"name": abbr, "id": str(i + 1), "abbreviation": abbr, "record_summary": "10-2"}
        for i, abbr in enumerate(TEAMS[:count])
    ]


def _league_data(logo_dir="assets/sports/nfl_logos"):
    return [{
        "league": "nfl",
        "league_config": {
            "logo_dir": logo_dir,
            "league_logo": os.path.join(logo_dir, "nfl.png") if logo_dir else "",
        },
        "teams": _teams(),
    }]


def _has_pixel_font():
    return os.path.exists(ImageRenderer.PRIMARY_FONT) or os.path.exists(
        ImageRenderer.FALLBACK_FONT
    )


requires_font = pytest.mark.skipif(
    not _has_pixel_font(),
    reason="run from a core checkout so assets/fonts/ resolves",
)


@requires_font
@pytest.mark.parametrize("height", [32, 64, 96])
def test_text_has_no_antialiased_pixels(height):
    """Every lit text pixel is fully on — no dim anti-aliasing fringe.

    Logos are excluded (logo_dir="") because a real logo legitimately contains
    many colours; only the text is required to be two-valued.
    """
    renderer = ImageRenderer(height, LOGGER)
    image = renderer.create_leaderboard_image(_league_data(logo_dir=""))
    assert image is not None

    import numpy as np
    pixels = np.array(image).reshape(-1, 3)
    lit = pixels[pixels.sum(axis=1) > 0]
    assert len(lit) > 0, "nothing was drawn"

    allowed = {(255, 255, 0), (255, 255, 255)}  # rank yellow, abbreviation white
    partial = [tuple(c) for c in lit if tuple(c) not in allowed]
    assert not partial, (
        f"{len(partial)} anti-aliased text pixels at height {height}, "
        f"e.g. {sorted(set(partial))[:5]}"
    )


@requires_font
def test_pixel_perfect_text_can_be_disabled():
    """Turning the option off restores the old anti-aliased rendering."""
    renderer = ImageRenderer(32, LOGGER, {"pixel_perfect_text": False})
    image = renderer.create_leaderboard_image(_league_data(logo_dir=""))
    assert image is not None
    draw = renderer._make_draw(Image.new("RGB", (8, 8)))
    assert draw.fontmode != "1"


@requires_font
@pytest.mark.parametrize("height,expected", [(32, 8), (64, 16), (96, 24)])
def test_default_font_sizes_land_on_the_pixel_grid(height, expected):
    renderer = ImageRenderer(height, LOGGER)
    if not renderer.font_grid:
        pytest.skip("no grid-based pixel font available")
    for key, font in renderer.fonts.items():
        assert font.size % renderer.font_grid == 0, (
            f"font '{key}' size {font.size} is off the {renderer.font_grid}px grid"
        )
    if os.path.basename(renderer.font_path) == "PressStart2P-Regular.ttf":
        assert renderer.fonts["large"].size == expected


@requires_font
def test_font_size_override_is_snapped_to_the_grid():
    renderer = ImageRenderer(32, LOGGER, {"font_size": 14})
    if not renderer.font_grid:
        pytest.skip("no grid-based pixel font available")
    assert renderer.fonts["large"].size % renderer.font_grid == 0


@requires_font
@pytest.mark.parametrize("height", [32, 64])
def test_nothing_is_drawn_past_the_panel_edge(height):
    """Logos used to be scaled to 120% of the panel and cropped top and bottom."""
    renderer = ImageRenderer(height, LOGGER)
    image = renderer.create_leaderboard_image(_league_data())
    assert image is not None
    box = image.getbbox()
    assert box is not None, "nothing was drawn"
    assert box[1] >= 0 and box[3] <= height, (
        f"content spans y={box[1]}..{box[3]} on a {height}px panel"
    )


def test_logo_alpha_is_thresholded():
    """Crisp mode leaves no semi-transparent halo around a logo."""
    renderer = ImageRenderer(32, LOGGER)
    source = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for y in range(256):  # a soft vertical alpha ramp
        for x in range(256):
            source.putpixel((x, y), (255, 0, 0, x))

    crisp = renderer._prepare_logo(source, 32, 32)
    assert crisp is not None
    assert set(crisp.split()[3].tobytes()) <= {0, 255}

    renderer.crisp_logos = False
    soft = renderer._prepare_logo(source, 32, 32)
    assert len(set(soft.split()[3].tobytes())) > 2


def test_logo_preserves_aspect_ratio():
    renderer = ImageRenderer(32, LOGGER)
    wide = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
    fitted = renderer._prepare_logo(wide, 32, 32)
    assert fitted.size == (32, 16)


@requires_font
@pytest.mark.parametrize("logo_dir", ["assets/sports/nfl_logos", ""])
def test_measured_width_matches_drawn_content(logo_dir):
    """The strip is exactly as wide as what gets drawn into it.

    Measuring and drawing were previously two separate passes that budgeted for
    a team logo differently when the file was missing, so the strip came out
    either padded with dead space or clipped short of the last team.
    """
    renderer = ImageRenderer(32, LOGGER)
    data = _league_data(logo_dir=logo_dir)
    if logo_dir and not os.path.isdir(logo_dir):
        pytest.skip("core logo assets not reachable")

    image = renderer.create_leaderboard_image(data)
    assert image is not None
    box = image.getbbox()

    # The only blank after the last abbreviation is that team's own trailing
    # gap plus the inter-league gap (+1 for the glyph's right side bearing). A
    # mismatch between the two passes shows up as a much larger gap, or as ink
    # running right up to the edge.
    trailing_blank = image.width - box[2]
    budget = ImageRenderer.TEAM_GAP + ImageRenderer.LEAGUE_SPACING + 2
    assert 0 < trailing_blank <= budget, (
        f"{trailing_blank}px of blank after the last team "
        f"(strip={image.width}px, ink ends at {box[2]}px)"
    )


@requires_font
def test_all_teams_are_drawn():
    """Every team handed to the renderer appears in the strip."""
    renderer = ImageRenderer(32, LOGGER)
    layout, total_width = renderer._build_layout(_league_data(logo_dir=""))
    assert len(layout) == 1
    assert len(layout[0]["teams"]) == len(TEAMS)
    assert [t["text"] for t in layout[0]["teams"]] == TEAMS
    assert total_width > 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
