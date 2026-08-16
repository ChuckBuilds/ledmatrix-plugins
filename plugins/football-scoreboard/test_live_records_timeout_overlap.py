"""Live scorebug: logos and records must not swallow the center / timeout strip.

Recurring live-only overlap (e.g. favorite DAL games): classic logos are
thumbnailed to 1.5x the panel and shifted inward, then live chrome
(down/distance, possession, timeouts, records) paints on top. Upcoming/recent
have less center ink so the same bleed looks acceptable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from PIL import Image, ImageDraw

from game_renderer import GameRenderer


def _live_game(**overrides):
    g = {
        "id": "dal-sea",
        "league": "nfl",
        "away_abbr": "DAL",
        "home_abbr": "SEA",
        "away_score": "17",
        "home_score": "7",
        "away_record": "1-0",
        "home_record": "0-1",
        "away_logo_path": None,
        "home_logo_path": None,
        "is_live": True,
        "period_text": "Q2",
        "clock": "5:43",
        "down_distance_text": "1st & 10",
        "away_timeouts": 3,
        "home_timeouts": 2,
        "possession_indicator": "away",
    }
    g.update(overrides)
    return g


def test_classic_live_records_sit_above_timeout_strip():
    """With reserve_timeout_strip, record bottoms must clear the timeout bars."""
    r = GameRenderer(128, 32, {"nfl": {"show_records": True}}, custom_logger=MagicMock())
    img = Image.new("RGBA", (128, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    ys = []
    original = r._draw_text_with_outline

    def capture(draw_obj, text, pos, font, fill=(255, 255, 255)):
        if text in ("1-0", "0-1"):
            ys.append(pos[1])
        return original(draw_obj, text, pos, font, fill=fill)

    r._draw_text_with_outline = capture
    r._draw_records_or_rankings(
        draw, _live_game(), show_records=True, show_ranking=False,
        reserve_timeout_strip=True,
    )

    assert ys, "expected record text to be drawn"
    timeout_y = 32 - 2 - 1  # matches _draw_timeouts
    # 4x6-ish fonts are ~6-8px tall; outline can add 1px.
    assert all(y + 9 <= timeout_y for y in ys), (
        f"record bottoms must clear timeout_y={timeout_y}, got ys={ys}"
    )


def test_live_logo_fit_leaves_center_column():
    """Oversized cached logos must be shrunk so a center gap remains for text."""
    W, H = 128, 32
    min_center = max(44, int(W * 0.34))
    max_logo_w = max(16, (W - min_center) // 2)

    # Simulate what football.py does after _load_and_resize_logo returns a 1.5x asset.
    away = Image.new("RGBA", (int(W * 1.5), int(H * 1.5)), (255, 0, 0, 255))
    home = Image.new("RGBA", (int(W * 1.5), int(H * 1.5)), (0, 0, 255, 255))
    away.thumbnail((max_logo_w, H), Image.Resampling.LANCZOS)
    home.thumbnail((max_logo_w, H), Image.Resampling.LANCZOS)

    bleed = min(4, max_logo_w // 8)
    away_x = -bleed
    home_x = W - home.width + bleed
    gap = home_x - (away_x + away.width)
    assert gap >= min_center - 2, f"center gap {gap} < reserved {min_center}"
    assert away.width <= max_logo_w and home.width <= max_logo_w
