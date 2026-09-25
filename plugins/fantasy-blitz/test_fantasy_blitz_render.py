"""Fantasy Blitz rendering contracts.

Every screen, at every harness size plus a few odd ones, animated and still,
at several moments of its animation: the frame is exactly the panel size and
drawing never raises. Plus the pieces a panel depends on -- 1-bit glyphs,
names that never spill out of their box, chips that never mislead.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402

import fantasy_blitz_draw as d  # noqa: E402
import fantasy_blitz_font as font  # noqa: E402
import fantasy_blitz_model as model  # noqa: E402
import fantasy_blitz_render as render  # noqa: E402
from fantasy_blitz_teams import team  # noqa: E402

with open(os.path.join(HERE, "test", "fixtures", "raw_payloads.json"), encoding="utf-8") as fh:
    RAW = json.load(fh)
WEEK = model.merge_week(model.normalize_sleeper_rows(RAW["sleeper_stats"]),
                        model.normalize_sleeper_rows(RAW["sleeper_projections"], "projections"))
JSN, ALLEN, DART, CAR = WEEK["9488"], WEEK["4984"], WEEK["12508"], WEEK["CAR"]

SIZES = [(64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32), (128, 96), (256, 128),
         (192, 64), (320, 32), (256, 64), (384, 192)]
MOMENTS = [0.0, 0.4, 1.3, 3.0, 99.0]


def ctx(animate=False):
    return render.RenderContext(fmt="ppr", week=2, phase=model.PHASE_RECAP, animate=animate, status="FINAL")


def items():
    c = ctx()
    top = model.ranked(WEEK, "ppr", limit=5)
    bust = model.busts(WEEK, "ppr", 12.0)[0]
    rows = [render.board_row(c, p, i) for i, p in enumerate(top)]
    alert = {"key": "k", "id": "9488", "name": JSN["name"], "last": JSN["last"], "pos": "WR", "team": "SEA",
             "opp": "ARI", "gain": 15.2, "total": 42.5, "desc": "82-YD TD CATCH", "td": True, "player": JSN}
    matchup = {"home": {"name": "Gridiron Ghosts", "record": "2-0", "points": 131.42},
               "away": {"name": "End Zone Dancers", "record": "1-1", "points": 118.9}, "mine": True}
    return {
        "card": (render.card, {"player": JSN, "list": top}),
        "card_def": (render.card, {"player": CAR}),
        "award": (render.card, {"player": DART, "banner": "BUST OF THE WEEK", "short": "WEEK BUST",
                                "value": 0.8, "note": "LEFT EARLY", "trophy": True}),
        "board": (render.board, {"title": "TOP SCORERS", "right": "WK 2  PPR", "rows": rows}),
        "board_empty": (render.board, {"title": "TOP SCORERS", "rows": []}),
        "pickups": (render.board, {"title": "HOT PICKUPS", "icon": "flame", "rows": [
            dict(r, value="↑484K", bar=0.5 + i / 10) for i, r in enumerate(rows)]}),
        "big_play": (render.big_play, alert),
        "big_play_fg": (render.big_play, dict(alert, td=False, desc="48-YD FIELD GOAL")),
        "big_play_plain": (render.big_play, dict(alert, td=False, desc=None)),
        "dud": (render.dud, dict(bust, pair=bust)),
        "dud_single": (render.dud, dict(bust, pair=None)),
        "kings": (render.kings, {"cells": model.kings(WEEK, "ppr")}),
        "kings_gaps": (render.kings, {"cells": [(pos, None) for pos in model.POSITIONS]}),
        "matchup": (render.matchup, {"league": "Harness League", "week": 2, "matchup": matchup, "pair": matchup}),
    }


@pytest.mark.parametrize("name", sorted(items()))
@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_every_screen_fills_every_panel_without_raising(name, size):
    fn, item = items()[name]
    for animate in (False, True):
        for t in MOMENTS if animate else (99.0,):
            frame = render.render_frame(fn, ctx(animate), item, size[0], size[1], t, "TITLE", d.GOLD)
            assert frame.size == size
            assert frame.mode == "RGB"


def test_static_frames_are_deterministic():
    fn, item = items()["card"]
    a = render.render_frame(fn, ctx(), item, 128, 64)
    b = render.render_frame(fn, ctx(), item, 128, 64)
    assert a.tobytes() == b.tobytes()


def test_glyphs_are_one_bit():
    for scale in (1, 2, 3):
        mask = font.text_mask("SMITH-NJIGBA 42.5 +15.2 ↑484K", scale)
        assert {level for _, level in mask.getcolors()} <= {0, 255}


def test_font_measures_and_normalises():
    assert font.text_width("A") == 3 and font.text_width("AA") == 7
    assert font.text_width("M") == 5 and font.text_width("A", 2) == 6
    assert font.normalize("José O’Neal") == "JOSE O'NEAL"
    assert font.normalize("中") == "?"
    assert font.text_width(font.fit("SMITH-NJIGBA", 30)) <= 30


def test_names_split_at_the_hyphen_and_never_overflow():
    assert render.name_lines("Smith-Njigba", 40, 2) == ["SMITH-", "NJIGBA"]
    for width in (10, 25, 40, 60):
        for line in render.name_lines("Smith-Njigba", width, 2):
            assert font.text_width(line) <= width


def test_long_names_scroll_only_when_animated():
    img = Image.new("RGB", (40, 8))
    still = ctx(False)
    still.label(img, "SMITH-NJIGBA", 0, 1, 30, d.WHITE, 0.0)
    assert not still.moving
    moving = ctx(True)
    moving.label(img, "SMITH-NJIGBA", 0, 1, 30, d.WHITE, 2.0)
    assert moving.moving
    short = ctx(True)
    short.label(img, "ALLEN", 0, 1, 30, d.WHITE, 2.0)
    assert not short.moving


def test_marquee_stays_inside_its_box():
    img = Image.new("RGB", (60, 10))
    c = ctx(True)
    for t in (0.0, 1.5, 2.5, 4.0):
        img.paste((0, 0, 0), (0, 0, 60, 10))
        c.label(img, "SMITH-NJIGBA", 10, 2, 30, d.WHITE, t)
        bbox = img.getbbox()
        assert bbox is None or (bbox[0] >= 10 and bbox[2] <= 40)


def test_chips_never_show_a_misleading_club_code():
    img = Image.new("RGB", (11, 7))
    d.chip(img, 0, 0, 11, 7, team("LAR"), "")
    colours = {c for _, c in img.getcolors()}
    assert colours == {d.lift(team("LAR")["primary"])}, "a three-letter club with no jersey gets a plain chip, not 'LA'"
    img2 = Image.new("RGB", (11, 7))
    d.chip(img2, 0, 0, 11, 7, team("LAR"), "17")
    assert len(img2.getcolors()) > 1


def test_dark_team_colours_are_lifted():
    navy = team("SEA")["primary"]
    assert max(d.lift(navy)) >= 150
    assert d.lift((255, 0, 0)) == (255, 0, 0)


def test_list_capacity_matches_the_rows_drawn():
    for w, h in ((64, 32), (128, 32), (128, 64), (96, 48), (128, 96), (256, 64)):
        capacity = render.list_capacity(w, h)
        assert capacity >= 3
        rows = [{"rank": i % 10, "name": f"PLAYER {i}", "value": "10.0", "team": "SEA"} for i in range(capacity + 3)]
        frame = render.board(ctx(), {"title": "T", "rows": rows}, w, h, 99.0)
        assert frame.size == (w, h)


def test_big_play_titles():
    assert render.big_play_title({"td": True}) == "TOUCHDOWN!"
    assert render.big_play_title({"desc": "48-YD FIELD GOAL"}) == "FIELD GOAL!"
    assert render.big_play_title({"desc": "SAFETY"}) == "SAFETY!"
    assert render.big_play_title({}) == "BIG PLAY!"


def test_vegas_entries_match_the_panel_height():
    for height in (32, 64):
        entry = render.vegas_entry(ctx(), JSN, height)
        assert entry.height == height and entry.width > 40
        assert render.vegas_title(height).height == height
