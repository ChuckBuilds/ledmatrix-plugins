"""
Rendering for the Elections plugin.

Two surfaces:
- ``render_ticker_segment`` — one compact card per race for the scrolling ticker.
- ``render_called_card`` — a full-screen "RACE CALLED" takeover card.

All drawing uses PIL so the manager can hand segment images to ScrollHelper and
push the called card straight to ``display_manager.image``.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from data_model import Race, chamber_of_office

logger = logging.getLogger(__name__)

# Party -> RGB. Kept here so the renderer is the single source of party colors.
PARTY_COLORS: Dict[str, Tuple[int, int, int]] = {
    "D": (50, 110, 255),
    "R": (235, 50, 50),
    "I": (170, 170, 170),
    "G": (40, 200, 90),
    "L": (235, 200, 40),
    "P": (180, 90, 220),
    "N": (60, 200, 200),
    "O": (220, 220, 220),
}
_DEFAULT_PARTY_COLOR = (220, 220, 220)

_WHITE = (235, 235, 235)
_DIM = (140, 140, 140)
_CALLED_GREEN = (40, 210, 90)
_HEADER_YELLOW = (240, 210, 60)

# Short office labels for the cramped ticker header.
_OFFICE_ABBREV = {
    "President": "PRES",
    "U.S. Senate": "SEN",
    "Governor": "GOV",
    "U.S. House": "HSE",
    "Ballot Measure": "BALLOT",
    "State Senate": "ST SEN",
    "State Assembly": "ST ASM",
}

# Candidate-font paths tried in order (relative to the LEDMatrix run cwd).
_FONT_CANDIDATES = [
    "assets/fonts/4x6-font.ttf",
    "assets/fonts/5by7.regular.ttf",
]


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


# Cache fonts by size so we don't reload per frame.
_FONT_CACHE: Dict[int, ImageFont.ImageFont] = {}


def font(size: int) -> ImageFont.ImageFont:
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = _load_font(size)
    return _FONT_CACHE[size]


def office_abbrev(race: Race) -> str:
    base = _OFFICE_ABBREV.get(race.office)
    if base is None:
        # Any state legislature chamber, however a given state names it.
        chamber = chamber_of_office(race.office)
        base = {"upper": "ST SEN", "lower": "ST HSE"}.get(chamber, race.office[:4].upper())
    loc = race.state or "US"
    if race.district:
        return f"{base} {loc}-{race.district}"
    return f"{base} {loc}"


def party_color(party: str) -> Tuple[int, int, int]:
    return PARTY_COLORS.get(party, _DEFAULT_PARTY_COLOR)


def _text_width(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=fnt)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 4


def _status_text(race: Race) -> Tuple[str, Tuple[int, int, int]]:
    if race.called:
        return "CALLED", _CALLED_GREEN
    # "prec" for precinct-based sources (local races) so a 100% there isn't read
    # as 100% of the vote counted; "in" for the vote-share estimate (NYT eevp).
    pct = int(round(race.pct_reporting))
    if getattr(race, "reporting_basis", "vote") == "precincts":
        return f"{pct}% prec", _DIM
    return f"{pct}% in", _DIM


# Ticker layout constants. The ticker scrolls horizontally; on taller panels we
# stack more race blocks per scrolling card to fill the height (scales to any
# height — a tall board shows many races top to bottom).
_TICKER_LINE_H = 7
_TICKER_PAD = 2
_TICKER_BLOCK_GAP = 2
_MAX_CANDS_PER_RACE = 4   # show up to this many candidates per race when present


def _ticker_max_candidates(height: int) -> int:
    """How many candidate rows fit under one header in this panel height."""
    return max(1, (height // _TICKER_LINE_H) - 1)


def ticker_block_candidate_count(race: Race, height: int) -> int:
    """Candidates shown for one race block: as many as the race has, capped by
    the per-race max and by what the panel height can physically fit."""
    return min(_MAX_CANDS_PER_RACE, len(race.candidates), _ticker_max_candidates(height))


def _block_height(race: Race, height: int) -> int:
    return _TICKER_LINE_H * (1 + ticker_block_candidate_count(race, height))


def pack_ticker_columns(races: list, height: int) -> list:
    """Greedily pack race blocks into vertical columns that fill the height.

    Scales to any panel height: 32px fits one race per column, 64px ~two, a very
    tall board many races stacked top to bottom. Each column becomes one
    horizontally-scrolling card.
    """
    columns: list = []
    cur: list = []
    cur_h = 0
    for race in races:
        bh = _block_height(race, height)
        if cur and cur_h + _TICKER_BLOCK_GAP + bh > height:
            columns.append(cur)
            cur, cur_h = [], 0
        cur.append(race)
        cur_h += (_TICKER_BLOCK_GAP if cur_h else 0) + bh
    if cur:
        columns.append(cur)
    return columns


def _block_rows(race: Race, ncands: int) -> list:
    rows = []
    for c in race.top_candidates(ncands):
        name = c.name if len(c.name) <= 12 else c.name[:11] + "."
        mark = "*" if c.is_winner else ""
        rows.append((f"{c.party} {name}{mark}", f"{int(round(c.pct))}%", party_color(c.party)))
    return rows


def render_ticker_column(races: list, height: int) -> Image.Image:
    """Render one scrolling card: a vertical stack of race blocks."""
    fnt = font(6)
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    prepared = []
    width = 40
    for race in races:
        header = office_abbrev(race)
        status, status_color = _status_text(race)
        rows = _block_rows(race, ticker_block_candidate_count(race, height))
        bw = _text_width(scratch, header, fnt) + _text_width(scratch, status, fnt) + 6
        for label, pct, _ in rows:
            bw = max(bw, _text_width(scratch, label, fnt) + _text_width(scratch, pct, fnt) + 6)
        width = max(width, bw + _TICKER_PAD * 2)
        prepared.append((header, status, status_color, rows))

    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = _TICKER_PAD
    for header, status, status_color, rows in prepared:
        draw.text((_TICKER_PAD, y), header, font=fnt, fill=_HEADER_YELLOW)
        status_x = width - _TICKER_PAD - _text_width(draw, status, fnt)
        draw.text((status_x, y), status, font=fnt, fill=status_color)
        y += _TICKER_LINE_H
        for label, pct, color in rows:
            if y + _TICKER_LINE_H > height:
                break
            draw.text((_TICKER_PAD, y), label, font=fnt, fill=color)
            pct_x = width - _TICKER_PAD - _text_width(draw, pct, fnt)
            draw.text((pct_x, y), pct, font=fnt, fill=_WHITE)
            y += _TICKER_LINE_H
        y += _TICKER_BLOCK_GAP
    return img


def render_ticker_segments(races: list, height: int) -> list:
    """Pack races into height-filling columns; render each as a scroll card."""
    return [render_ticker_column(col, height) for col in pack_ticker_columns(races, height)]


def render_ticker_segment(race: Race, height: int) -> Image.Image:
    """Single-race card (kept for callers/tests that render one race)."""
    return render_ticker_column([race], height)


def _truncate(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> str:
    """Trim text (with a trailing dot) until it fits within max_w pixels."""
    if _text_width(draw, text, fnt) <= max_w:
        return text
    while text and _text_width(draw, text + ".", fnt) > max_w:
        text = text[:-1]
    return (text + ".") if text else ""


def called_card_winners(race: Race) -> list:
    """Candidates to feature on the called card.

    A called race carries one winner (general: ``won``) or two (a top-two
    primary: ``advanced_to_runoff``). Show all flagged winners (capped at two);
    fall back to the current leader if nothing is flagged yet.
    """
    winners = [c for c in race.candidates if c.is_winner]
    if not winners and race.leader is not None:
        winners = [race.leader]
    return winners[:2]


def render_called_card(race: Race, width: int, height: int) -> Image.Image:
    """Render a full-screen takeover card for a called race.

    One winner -> "RACE CALLED" with a prominent name. Two winners (a top-two
    primary advancement) -> "ADVANCED" with both candidates stacked. Layout
    adapts to panel size so rows never overlap or run past the edge.
    """
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    small = font(6)
    use_big = height >= 48
    banner_h = 8
    reporting = f"{int(round(race.pct_reporting))}% in"
    winners = called_card_winners(race)
    multi = len(winners) >= 2

    # Banner: white text on a solid green bar reads cleanly even with glow.
    draw.rectangle([(0, 0), (width - 1, banner_h - 1)], fill=(30, 130, 60))
    if multi:
        banner = "ADVANCED" if width >= 96 else "ADV"
    else:
        banner = "RACE CALLED" if width >= 96 else "CALLED"
    bw = _text_width(draw, banner, small)
    draw.text(((width - bw) // 2, 1), banner, font=small, fill=(255, 255, 255))

    if not winners:
        return img

    if multi:
        # Two candidates: office header, then one row each (name + pct).
        name_font = font(8) if use_big else small
        row_h = 9 if use_big else 7
        if use_big:
            header_y = banner_h + 2
            row1_y = header_y + 8
            info_y = height - 7
            header = office_abbrev(race)
        else:
            header_y = banner_h + 1            # 9
            row1_y = header_y + 7              # 16
            info_y = None                      # no room; fold reporting into header
            header = f"{office_abbrev(race)}  {reporting}"
        header = _truncate(draw, header, small, width - 4)
        hw = _text_width(draw, header, small)
        draw.text(((width - hw) // 2, header_y), header, font=small, fill=_HEADER_YELLOW)

        pct_budget = 22
        for cand, y in zip(winners, (row1_y, row1_y + row_h)):
            name = _truncate(draw, cand.name, name_font, width - 4 - pct_budget)
            draw.text((2, y), name, font=name_font, fill=party_color(cand.party))
            pct = f"{int(round(cand.pct))}%"
            pct_x = width - 2 - _text_width(draw, pct, name_font)
            draw.text((pct_x, y), pct, font=name_font, fill=_WHITE)

        if info_y is not None:
            iw = _text_width(draw, reporting, small)
            draw.text(((width - iw) // 2, info_y), reporting, font=small, fill=_WHITE)
        return img

    # Single winner (general / outright win): keep the prominent layout.
    name_font = font(10) if use_big else small
    line_h = 7
    if use_big:
        header_y = banner_h + 3
        name_y = header_y + line_h + 2
        info_y = height - line_h - 1
    else:
        header_y = banner_h + 1            # 9
        name_y = header_y + line_h         # 16
        info_y = name_y + line_h           # 23  (fits within 32)

    header = _truncate(draw, office_abbrev(race), small, width - 4)
    hw = _text_width(draw, header, small)
    draw.text(((width - hw) // 2, header_y), header, font=small, fill=_HEADER_YELLOW)

    winner = winners[0]
    name = _truncate(draw, winner.name, name_font, width - 4)
    nw = _text_width(draw, name, name_font)
    draw.text(((width - nw) // 2, name_y), name, font=name_font, fill=party_color(winner.party))

    info = f"{winner.party} {int(round(winner.pct))}%  {reporting}"
    iw = _text_width(draw, info, small)
    draw.text(((width - iw) // 2, info_y), info, font=small, fill=_WHITE)
    return img
