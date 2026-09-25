"""The Fantasy Blitz screens.

Each screen has two designs -- *short* (32 rows) and *tall* (64 rows) -- and
each design adapts to three widths: narrow (under 96), normal (96-191) and
wide (192 and up, where most screens put a second item or a companion list
beside the first). :func:`render_frame` picks the design, adds a title band
and a status bar when the panel has spare rows, and scales the whole frame
up in whole steps on very large panels (256x128 draws the 128x64 design at
2x), so every panel size gets a finished screen.

Renderers take ``t``, the seconds since the item came on screen, for the
intro animations (count-up, bar fills, slide-ins) and the continuous ones
(foil shimmer, sunburst, confetti, hazard stripes). With animation off they
draw the final frame.
"""

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image

import fantasy_blitz_draw as d
import fantasy_blitz_font as font
import fantasy_blitz_model as model
from fantasy_blitz_teams import team as team_info

RGB = Tuple[int, int, int]


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


class RenderContext:
    """What every renderer needs besides the item: format, art, and time."""

    def __init__(self, fmt: str = "ppr", tiers: Optional[Dict[str, float]] = None,
                 headshots=None, week: Optional[int] = None, phase: str = "",
                 animate: bool = True, show_headshots: bool = True, status: str = ""):
        self.fmt = fmt if fmt in model.SCORING_KEYS else model.DEFAULT_SCORING
        self.tiers = tiers or dict(model.DEFAULT_TIERS)
        self.headshots = headshots
        self.week = week
        self.phase = phase
        self.animate = animate
        self.show_headshots = show_headshots
        self.status = status
        #: Set by a frame that scrolls a long name: that frame is not a still
        #: one, so the plugin must keep drawing it rather than cache it.
        self.moving = False

    def label(self, img: Image.Image, text: object, x: int, y: int, max_w: int, color,
              t: float, align: str = "left", outline: Optional[RGB] = None) -> int:
        """Text that always fits ``max_w``: whole, scrolling, or cut at a letter.

        A name too long for its box scrolls (a marquee that pauses at each
        end) when animation is on, and is cut at a whole character when it
        is off. ``x`` is the box's left edge, centre or right edge per
        ``align``, exactly as for plain text.
        """
        s = font.normalize(text)
        width = font.text_width(s)
        if width <= max_w or max_w <= 0:
            return d.text(img, s, x, y, color, 1, align, outline)
        left = x if align == "left" else (x - max_w // 2 if align == "center" else x - max_w)
        if not self.animate:
            return d.text(img, font.fit(s, max_w), left, y, color, 1, "left", outline)
        self.moving = True
        travel = width - max_w
        pause, speed = 1.2, 14.0
        cycle = pause * 2 + travel / speed
        phase = t % cycle
        offset = 0 if phase < pause else min(travel, int((phase - pause) * speed))
        strip = Image.new("RGB", (width + 2, font.GLYPH_HEIGHT + 2), d.BLACK)
        mask = Image.new("L", strip.size, 0)
        d.text(strip, s, 1, 1, color, 1, "left", outline)
        font.draw_text(mask, s, 1, 1, 255, 1, "left", 255 if outline is not None else None)
        box = (offset + 1, 0, offset + 1 + max_w, strip.height)
        img.paste(strip.crop(box), (left, y - 1), mask.crop(box))
        return max_w

    # data helpers ------------------------------------------------------
    def pts(self, player: Dict[str, Any]) -> Optional[float]:
        return model.points(player, self.fmt)

    def proj(self, player: Dict[str, Any]) -> Optional[float]:
        return model.projection(player, self.fmt)

    def tier(self, value: Optional[float]) -> str:
        return model.tier_for(value, self.tiers)

    def tier_color(self, value: Optional[float]) -> RGB:
        return d.TIER_COLORS[self.tier(value)]

    def week_label(self) -> str:
        parts = []
        if self.week:
            parts.append(f"WK {self.week}")
        parts.append(model.SCORING_LABELS.get(self.fmt, "PPR"))
        return "  ".join(parts)

    # art helpers -------------------------------------------------------
    def jersey(self, player: Dict[str, Any]) -> str:
        if self.headshots is None or player.get("pos") == "DEF":
            return ""
        try:
            return self.headshots.jersey(player)
        except Exception:  # noqa: BLE001 - art is never worth a crash
            return ""

    def photo(self, player: Dict[str, Any], w: int, h: int) -> Optional[Image.Image]:
        if not self.show_headshots or self.headshots is None or player.get("pos") == "DEF":
            return None
        try:
            return self.headshots.portrait(player, w, h)
        except Exception:  # noqa: BLE001
            return None

    def logo(self, abbr: str, w: int, h: int) -> Optional[Image.Image]:
        if self.headshots is None:
            return None
        try:
            return self.headshots.logo(abbr, w, h)
        except Exception:  # noqa: BLE001
            return None

    def picture(self, img: Image.Image, player: Dict[str, Any], x: int, y: int, w: int, h: int) -> None:
        """The player's portrait box: photo, crest for a defence, else silhouette."""
        team = team_info(player.get("team"))
        if player.get("pos") == "DEF":
            logo = self.logo(str(player.get("team") or ""), w - 4, h - 4)
            d.portrait(img, x, y, w, h, team, "", None, logo)
            return
        d.portrait(img, x, y, w, h, team, self.jersey(player), self.photo(player, w, h))


# ----------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------

def name_lines(name: str, max_w: int, max_lines: int = 1, scale: int = 1) -> List[str]:
    """``name`` in one line, or split at a hyphen/space onto two, never mid-letter."""
    s = font.normalize(name)
    if font.text_width(s, scale) <= max_w or max_lines < 2:
        return [s if font.text_width(s, scale) <= max_w else font.fit(s, max_w, scale)]
    for sep in ("-", " "):
        if sep in s:
            idx = s.rfind(sep) if sep == " " else s.find(sep)
            first = s[:idx + 1].rstrip() if sep == "-" else s[:idx]
            second = s[idx + 1:]
            if font.text_width(first, scale) <= max_w and font.text_width(second, scale) <= max_w:
                return [first, second]
    return [font.fit(s, max_w, scale)]


def draw_parts(img: Image.Image, parts: Sequence[Tuple[str, str]], x: int, y: int, max_w: int,
               num_color: RGB = d.WHITE, label_color: RGB = d.GRAY) -> int:
    """``9 REC 155 YD 3 TD`` -- numbers bright, labels dim, whole parts only."""
    cursor = x
    first = True
    for number, label in parts:
        piece = font.text_width(number) + 2 + font.text_width(label)
        gap = 0 if first else 4
        if cursor + gap + piece - x > max_w:
            break
        cursor += gap
        cursor += d.text(img, number, cursor, y, num_color) + 2
        cursor += d.text(img, label, cursor, y, label_color)
        first = False
    return cursor - x


def parts_width(parts: Sequence[Tuple[str, str]]) -> int:
    total = 0
    for i, (number, label) in enumerate(parts):
        total += (4 if i else 0) + font.text_width(number) + 2 + font.text_width(label)
    return total


def fmt_gain(value: float) -> str:
    return f"+{value:.1f}" if value >= 0 else f"{value:.1f}"


# ----------------------------------------------------------------------
# frame assembly
# ----------------------------------------------------------------------

ScreenFn = Callable[["RenderContext", Dict[str, Any], int, int, float], Image.Image]


def base_size(width: int, height: int) -> Tuple[int, int, int]:
    """``(scale, base_w, base_h)``: very large panels draw a smaller design at 2x, 3x..."""
    s = max(1, min(int(width) // 128, int(height) // 64))
    return s, max(64, int(width) // s), max(32, int(height) // s)


#: Screens that use every row a panel has (more list rows, taller grid
#: cells) instead of a fixed 32- or 64-row design with bands around it.
FLEX_HEIGHT = set()


def render_frame(fn: ScreenFn, ctx: RenderContext, item: Dict[str, Any], width: int, height: int,
                 t: float = 99.0, title: str = "", title_color: RGB = d.GOLD) -> Image.Image:
    """A finished ``width`` x ``height`` frame of one screen item."""
    width, height = max(1, int(width)), max(1, int(height))
    s, bw, bh = base_size(width, height)
    ctx.moving = False
    if fn in FLEX_HEIGHT:
        design_h = bh
    else:
        design_h = 64 if bh >= 64 else 32
    body = fn(ctx, item, bw, design_h, t)
    base = Image.new("RGB", (bw, bh), d.BLACK)
    extra = bh - design_h
    if extra >= 12:
        head = extra // 2
        base.paste(body, (0, head))
        _title_band(base, 0, 0, bw, head, title, title_color, ctx)
        _status_band(base, 0, head + design_h, bw, bh - head - design_h, ctx)
    else:
        base.paste(body, (0, extra // 2))
    if s > 1:
        base = base.resize((bw * s, bh * s), Image.NEAREST)
    if base.size == (width, height):
        return base
    out = Image.new("RGB", (width, height), d.BLACK)
    out.paste(base, ((width - base.width) // 2, (height - base.height) // 2))
    return out


def _title_band(img: Image.Image, x: int, y: int, w: int, h: int, title: str, color: RGB,
                ctx: RenderContext) -> None:
    if h < 6:
        return
    scale_ = 2 if h >= 16 and font.text_width(title, 2) <= w - 16 else 1
    ty = y + (h - 1 - font.text_height(scale_)) // 2
    d.hline(img, x, y + h - 2, w, d.scale(color, 0.45))
    d.bolt(img, x + 2, ty + (font.text_height(scale_) - 5) // 2, color)
    d.text(img, font.fit(title, w - 12, scale_), x + 9, ty, color, scale_)


def _status_band(img: Image.Image, x: int, y: int, w: int, h: int, ctx: RenderContext) -> None:
    if h < 6:
        return
    ty = y + (h - font.text_height()) // 2 + 1
    d.hline(img, x, y + 1, w, d.DIM)
    d.text(img, ctx.week_label(), x + 2, ty, d.GRAY)
    if ctx.status:
        color = d.RED if ctx.status == "LIVE" else d.GRAY
        right = x + w - 2
        if ctx.status == "LIVE":
            d.dot(img, right - font.text_width("LIVE") - 4, ty + 2, d.RED)
        d.text(img, ctx.status, right, ty, color, 1, "right")


def side_by_side(ctx: RenderContext, left: ScreenFn, left_item: Dict[str, Any],
                 right: ScreenFn, right_item: Dict[str, Any], w: int, h: int, t: float,
                 left_w: int = 128) -> Image.Image:
    img = Image.new("RGB", (w, h), d.BLACK)
    left_w = min(left_w, w - 64)
    img.paste(left(ctx, left_item, left_w, h, t), (0, 0))
    d.rect(img, left_w, 0, 1, h, d.DIM)
    img.paste(right(ctx, right_item, w - left_w - 1, h, t), (left_w + 1, 0))
    return img


# ----------------------------------------------------------------------
# S1 player card (also S9 awards)
# ----------------------------------------------------------------------

def card(ctx: RenderContext, item: Dict[str, Any], w: int, h: int, t: float) -> Image.Image:
    """``item``: ``{"player", "list"?, "banner"?, "value"?, "note"?, "trophy"?}``."""
    if w >= 192 and item.get("list"):
        return side_by_side(ctx, card, dict(item, list=None), board, _companion_board(ctx, item),
                            w, h, t, 128)
    if h >= 64:
        return _card_tall(ctx, item, w, t) if w >= 96 else _card_tall_narrow(ctx, item, w, t)
    return _card_short(ctx, item, w, t) if w >= 96 else _card_short_narrow(ctx, item, w, t)


def _card_values(ctx: RenderContext, item: Dict[str, Any], t: float):
    p = item["player"]
    value = item.get("value", ctx.pts(p))
    proj = ctx.proj(p)
    k = ease((t - 0.2) / 1.2) if ctx.animate else 1.0
    shown = model.fmt_points((value or 0.0) * k) if value is not None else "-"
    color = ctx.tier_color(value)
    return p, value, proj, shown, color, k


def _banner_text(item: Dict[str, Any], tier: str, max_w: int) -> str:
    """The banner title: the award (or tier) name, its short form if needed."""
    long = item.get("banner") or d.TIER_NAMES[tier]
    if font.text_width(long) <= max_w:
        return long
    short = item.get("short") or long
    return short if font.text_width(short) <= max_w else font.fit(short, max_w)


def _banner(img: Image.Image, x: int, y: int, w: int, color: RGB, item: Dict[str, Any], tier: str,
            right: str) -> None:
    d.hgrad(img, x, y, w, 7, d.mix(color, d.WHITE, 0.2), d.scale(color, 0.5))
    tx = x + 2
    if item.get("trophy"):
        d.trophy(img, x + 2, y, d.INK)
        tx += 9
    room = w - (tx - x) - 2
    rw = font.text_width(right) if right else 0
    long = item.get("banner") or d.TIER_NAMES[tier]
    if right and font.text_width(long) + rw + 6 > room:
        right = ""
    left = _banner_text(item, tier, room - (rw + 6 if right else 0))
    d.text(img, left, tx, y + 1, d.INK)
    if right:
        d.text(img, right, x + w - 2, y + 1, d.INK, 1, "right")


def _shimmer_card(ctx: RenderContext, img: Image.Image, w: int, h: int, tier: str, t: float) -> None:
    if tier == "legendary":
        pos = ((t * 55) % (w + 120)) - 40 if ctx.animate else w * 0.55
        d.shimmer(img, 0, 0, w, h, pos, 5, 0.35 if ctx.animate else 0.22)


def _card_tall(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 64), d.BLACK)
    p, value, proj, shown, color, _ = _card_values(ctx, item, t)
    tier = ctx.tier(value)
    d.frame(img, 0, 0, w, 64, d.scale(color, 0.9))
    _banner(img, 1, 1, w - 2, color, item, tier, ctx.week_label())
    pw = 41 if w >= 120 else 32
    ctx.picture(img, p, 1, 8, pw, 55)
    d.rect(img, pw + 1, 8, 1, 55, d.scale(color, 0.35))
    x0 = pw + 5
    avail = w - x0 - 3
    ctx.label(img, model.display_last(p), x0, 10, avail, d.WHITE, t)
    tag_w = d.pos_tag(img, x0, 17, p.get("pos", ""))
    matchup = f"{p.get('team', '')} VS {p.get('opp', '')}" if p.get("opp") else str(p.get("team", ""))
    if font.text_width(matchup) > avail - tag_w - 3:
        matchup = str(p.get("team", ""))
    d.text(img, matchup, x0 + tag_w + 3, 18, d.GRAY)
    code = model.injury_tag(p.get("injury"))
    if code and x0 + tag_w + 3 + font.text_width(matchup) + 4 + font.text_width(code) + 4 <= w - 2:
        d.injury_box(img, x0 + tag_w + 3 + font.text_width(matchup) + 3, 17, code)
    scale_ = 3 if font.text_width(shown, 3) + 4 + font.text_width("PTS") <= avail else 2
    num_w = d.big_number(img, shown, x0, 26 if scale_ == 3 else 29, color, scale_)
    d.text(img, "PTS", x0 + num_w + 4, 36, d.scale(color, 0.75))
    lines = model.stat_lines(p)
    if lines:
        draw_parts(img, lines[0], x0, 44, avail)
    progress = max(0.0, min(1.0, (t - 1.3) / 1.2)) if ctx.animate else 1.0
    if proj:
        d.xp_bar(img, x0, 51, avail, 4, proj, value, progress)
        note = item.get("note") or f"PROJ {model.fmt_points(proj)}"
        diff = fmt_gain((value or 0) - proj)
        d.text(img, font.fit(note, avail - font.text_width(diff) - 4), x0, 57, d.GRAY)
        d.text(img, diff, w - 3, 57, color if (value or 0) >= proj else d.RED, 1, "right")
    else:
        if len(lines) > 1:
            draw_parts(img, lines[1], x0, 51, avail)
        if item.get("note"):
            d.text(img, font.fit(item["note"], avail), x0, 57, d.GRAY)
    _shimmer_card(ctx, img, w, 64, tier, t)
    return img


def _card_tall_narrow(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 64), d.BLACK)
    p, value, proj, shown, color, _ = _card_values(ctx, item, t)
    tier = ctx.tier(value)
    d.frame(img, 0, 0, w, 64, d.scale(color, 0.9))
    d.hgrad(img, 1, 1, w - 2, 7, d.mix(color, d.WHITE, 0.2), d.scale(color, 0.5))
    d.text(img, _banner_text(item, tier, w - 6), w // 2, 2, d.INK, 1, "center")
    pw = 24
    ctx.picture(img, p, 1, 8, pw, 33)
    x0 = pw + 3
    avail = w - x0 - 2
    scale_ = 2 if font.text_width(shown, 2) <= avail else 1
    d.big_number(img, shown, x0, 11, color, scale_)
    d.text(img, "PTS", x0, 23, d.scale(color, 0.75))
    tag_w = d.pos_tag(img, x0, 31, p.get("pos", ""))
    if font.text_width(p.get("team", "")) <= avail - tag_w - 2:
        d.text(img, p.get("team", ""), x0 + tag_w + 2, 32, d.GRAY)
    ctx.label(img, model.display_last(p), w // 2, 44, w - 4, d.WHITE, t, "center")
    compact = model.stat_compact(p)
    if compact:
        d.text(img, font.fit(compact, w - 4), w // 2, 51, d.WHITE, 1, "center")
    progress = max(0.0, min(1.0, (t - 1.3) / 1.2)) if ctx.animate else 1.0
    d.xp_bar(img, 3, 58, w - 6, 3, proj, value, progress)
    _shimmer_card(ctx, img, w, 64, tier, t)
    return img


def _card_short(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 32), d.BLACK)
    p, value, proj, shown, color, _ = _card_values(ctx, item, t)
    tier = ctx.tier(value)
    award = bool(item.get("banner"))
    d.frame(img, 0, 0, w, 32, d.scale(color, 0.9))
    pw = 26
    ctx.picture(img, p, 1, 1, pw, 30)
    x0 = pw + 4
    avail = w - x0 - 2
    name = model.display_last(p)
    if award:
        # An award card leads with the award; the name takes the stat row.
        tx = x0
        if item.get("trophy"):
            d.trophy(img, x0, 1, color)
            tx += 9
        d.text(img, _banner_text(item, tier, w - 3 - tx), tx, 2, color)
    else:
        label = d.TIER_NAMES[tier]
        if font.text_width(name) + 6 + font.text_width(label) > avail:
            label = ""
        ctx.label(img, name, x0, 2, avail - (font.text_width(label) + 6 if label else 0), d.WHITE, t)
        if label:
            d.text(img, label, w - 3, 2, color, 1, "right")
    num_w = d.big_number(img, shown, x0, 8, color, 2)
    d.text(img, "PTS", x0 + num_w + 3, 13, d.scale(color, 0.75))
    tag_w = font.text_width(p.get("pos", "")) + 4 + 2 + font.text_width(p.get("team", ""))
    if x0 + num_w + 3 + font.text_width("PTS") + 6 + tag_w <= w - 3:
        tx = w - 3 - tag_w
        tw = d.pos_tag(img, tx, 9, p.get("pos", ""))
        d.text(img, p.get("team", ""), tx + tw + 2, 10, d.GRAY)
    if award:
        ctx.label(img, name, x0, 20, avail, d.WHITE, t)
    else:
        lines = model.stat_lines(p)
        if lines:
            draw_parts(img, lines[0], x0, 20, avail)
    progress = max(0.0, min(1.0, (t - 1.3) / 1.2)) if ctx.animate else 1.0
    d.xp_bar(img, x0, 27, avail, 3, proj, value, progress)
    _shimmer_card(ctx, img, w, 32, tier, t)
    return img


def _card_short_narrow(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 32), d.BLACK)
    p, value, proj, shown, color, _ = _card_values(ctx, item, t)
    tier = ctx.tier(value)
    award = bool(item.get("banner"))
    name = model.display_last(p)
    if award:
        d.text(img, _banner_text(item, tier, w - 2), w // 2, 1, color, 1, "center")
    else:
        ctx.label(img, name, w // 2, 1, w - 2, d.WHITE, t, "center")
    d.rect(img, 0, 7, w, 1, color)
    ctx.picture(img, p, 0, 8, 19, 24)
    x0 = 22
    avail = w - x0 - 1
    scale_ = 2 if font.text_width(shown, 2) + 3 + font.text_width("PTS") <= avail else 1
    num_w = d.big_number(img, shown, x0, 9, color, scale_)
    if scale_ == 2:
        d.text(img, "PTS", x0 + num_w + 3, 14, d.scale(color, 0.75))
    if award:
        ctx.label(img, name, x0, 21, avail, d.WHITE, t)
    else:
        compact = model.stat_compact(p)
        if compact:
            d.text(img, font.fit(compact, avail), x0, 21, d.WHITE)
    progress = max(0.0, min(1.0, (t - 1.3) / 1.2)) if ctx.animate else 1.0
    d.xp_bar(img, x0, 28, avail, 3, proj, value, progress)
    return img


def _companion_board(ctx: RenderContext, item: Dict[str, Any]) -> Dict[str, Any]:
    players = item.get("list") or []
    rows = [board_row(ctx, p, i) for i, p in enumerate(players)]
    focus = item["player"].get("id")
    for row in rows:
        row["highlight"] = row.get("id") == focus
    return {"title": item.get("list_title", "TOP SCORERS"), "rows": rows,
            "colors": ((112, 52, 190), (24, 96, 200)), "right": ctx.week_label()}


# ----------------------------------------------------------------------
# S2 leaderboard and every other list (S5, S7, S8, S12)
# ----------------------------------------------------------------------

def board_row(ctx: RenderContext, p: Dict[str, Any], rank: Optional[int],
              value: Optional[float] = None, show_proj: bool = False) -> Dict[str, Any]:
    """A leaderboard row for a player: rank coin, chip, name, position, points."""
    pts = ctx.pts(p) if value is None else value
    proj = ctx.proj(p)
    if pts is None and show_proj and proj is not None:
        text, color = f"P{model.fmt_points(proj)}", d.GRAY
    else:
        text, color = model.fmt_points(pts), ctx.tier_color(pts)
    return {
        "id": p.get("id"), "rank": rank, "team": p.get("team"), "jersey": ctx.jersey(p),
        "name": model.display_last(p), "pos": p.get("pos"), "value": text,
        "value_color": color, "tag": model.injury_tag(p.get("injury")),
    }


def list_capacity(w: int, h: int) -> int:
    """How many rows the list design fits at this base size."""
    header, row_h = (9, 11) if h >= 64 else (7, 8)
    per_column = (h - header - 1 - 7) // row_h + 1
    return per_column * (2 if w >= 192 else 1)


def board(ctx: RenderContext, item: Dict[str, Any], w: int, h: int, t: float) -> Image.Image:
    """A titled list. ``item``: ``{"title", "rows", "colors"?, "right"?, "icon"?}``."""
    img = Image.new("RGB", (w, h), d.BLACK)
    tall = h >= 64
    header = 9 if tall else 7
    c1, c2 = item.get("colors") or ((112, 52, 190), (24, 96, 200))
    d.hgrad(img, 0, 0, w, header, c1, c2)
    icon = item.get("icon")
    tx = 2
    if icon == "flame":
        d.flame(img, 2, 1 if tall else 0, ctx.animate and int(t * 6) % 2 == 1)
        tx = 9
    elif icon == "snow":
        d.snowflake(img, 2, 2 if tall else 1)
        tx = 9
    elif icon == "crown":
        d.crown(img, 2, 2 if tall else 1)
        tx = 11
    elif icon == "cross":
        d.rect(img, 3, 3 if tall else 2, 5, 1, d.WHITE)
        d.rect(img, 5, 1 if tall else 0, 1, 5, d.WHITE)
        tx = 10
    ty = 2 if tall else 1
    right = item.get("right") or ""
    title = item.get("title") or ""
    if right and font.text_width(title) + font.text_width(right) + 8 > w - tx:
        right = ""
    d.text(img, font.fit(title, w - tx - 2), tx, ty, d.WHITE)
    if right:
        d.text(img, right, w - 2, ty, d.mix(d.WHITE, c2, 0.15), 1, "right")
    rows = item.get("rows") or []
    if not rows:
        d.text(img, item.get("empty", "NO DATA YET"), w // 2, header + (h - header) // 2 - 2, d.GRAY, 1, "center")
        return img
    row_h = 11 if tall else 8
    per_col = (h - header - 1 - 7) // row_h + 1
    columns = 2 if w >= 192 else 1
    col_w = (w - (columns - 1) * 3) // columns
    for index, row in enumerate(rows[:per_col * columns]):
        col, line = divmod(index, per_col)
        x = col * (col_w + 3)
        y = header + 2 + line * row_h
        dx = 0
        if ctx.animate:
            dx = int(round((1 - ease((t - 0.1 - index * 0.12) / 0.45)) * (col_w + 4)))
            if dx >= col_w:
                continue
        cell = Image.new("RGB", (col_w, 7 if not tall else 10), d.BLACK)
        _board_cell(ctx, cell, row, col_w, tall, t)
        img.paste(cell.crop((0, 0, col_w - dx, cell.height)), (x + dx, y))
    return img


def _board_cell(ctx: RenderContext, img: Image.Image, row: Dict[str, Any], w: int, tall: bool,
                t: float) -> None:
    if row.get("highlight"):
        d.rect(img, 0, 0, w, 7, d.GOLD, 0.14)
    x = 1
    if row.get("rank") is not None:
        d.coin(img, x, 0, int(row["rank"]))
        x += 9
    elif row.get("code"):
        x += d.injury_box(img, x, 0, row["code"]) + 2
    wide = w >= 96
    if wide and row.get("team"):
        d.chip(img, x, 0, 11, 7, team_info(row["team"]), row.get("jersey") or "")
        x += 14
    value = str(row.get("value") or "")
    value_w = font.text_width(value)
    right = w - 2
    d.text(img, value, right, 1, row.get("value_color") or d.WHITE, 1, "right")
    right -= value_w + 3
    pos = row.get("pos") if wide else None
    if pos:
        pos_w = font.text_width(pos)
        if right - pos_w - 3 > x + 12:
            d.text(img, pos, right, 1, d.POSITION_COLORS.get(pos, d.GRAY), 1, "right")
            right -= pos_w + 3
    code = row.get("tag")
    if code and wide:
        code_w = font.text_width(code) + 4
        if right - code_w - 2 > x + 16:
            d.injury_box(img, right - code_w, 0, code)
            right -= code_w + 3
    name_color = d.GOLD if row.get("highlight") else row.get("name_color") or d.WHITE
    ctx.label(img, row.get("name", ""), x, 1, right - x, name_color, t)
    bar = row.get("bar")
    if bar is not None and tall:
        bx, bw = x, w - x - 2
        fill = int(round(bw * max(0.0, min(1.0, bar))))
        c1, c2 = row.get("bar_colors") or ((255, 70, 30), (255, 220, 90))
        d.rect(img, bx, 8, bw, 2, d.scale(c1, 0.18))
        d.hgrad(img, bx, 8, fill, 2, c1, c2)


# ----------------------------------------------------------------------
# S3 big play
# ----------------------------------------------------------------------

def big_play_title(alert: Dict[str, Any]) -> str:
    desc = str(alert.get("desc") or "")
    if alert.get("td"):
        return "TOUCHDOWN!"
    if "FIELD GOAL" in desc:
        return "FIELD GOAL!"
    if desc == "SAFETY":
        return "SAFETY!"
    return "BIG PLAY!"


def big_play(ctx: RenderContext, item: Dict[str, Any], w: int, h: int, t: float) -> Image.Image:
    """``item``: an alert from :func:`model.detect_big_plays` plus ``player``."""
    img = Image.new("RGB", (w, h), d.BLACK)
    p = item.get("player") or item
    team = team_info(item.get("team"))
    primary, accent = d.team_colors(team)
    tt = t if ctx.animate else 2.3
    tall = h >= 64
    title = big_play_title(item)
    gain = fmt_gain(float(item.get("gain") or 0))
    desc = item.get("desc") or f"{model.fmt_points(item.get('total'))} PTS TOTAL"
    name = model.display_last(p)
    pic_w = 0
    if w >= 192 or (not tall and w >= 96):
        pic_w = 48 if tall else 26
    d.rays(img, pic_w, 0, w - pic_w, h, pic_w + (w - pic_w) / 2, h * (0.34 if tall else 0.45),
           tt * 0.45 if ctx.animate else 0.3, accent, primary)
    if item.get("td"):
        confetti_h = h - 11 if tall else h
        d.confetti(img, pic_w, 0, w - pic_w, confetti_h, tt, [accent, d.WHITE, d.GOLD, (255, 90, 160)])
    if pic_w:
        ctx.picture(img, p, 1, 1, pic_w - 2, h - (12 if tall else 2))
    x0 = pic_w
    cw = w - pic_w
    cx = x0 + cw // 2
    pulse = 0.86 + 0.14 * math.sin(t * 2 * math.pi / 1.7) if ctx.animate else 1.0
    green = d.scale(d.GREEN, pulse)

    def gain_fill(row: int, height: int) -> RGB:
        return d.mix(green, d.WHITE, 0.5) if row < max(1, height // 5) else green

    if tall:
        t_scale = 2 if font.text_width(title, 2) <= cw - 4 else 1
        d.text(img, title, cx, 3, lambda r, hh: d.mix(d.GOLD_HI, d.GOLD, r / max(1, hh - 1)), t_scale, "center", d.BLACK)
        g_scale = 3 if font.text_width(gain, 3) + 3 + font.text_width("PTS") <= cw - 4 else 2
        gy = 17 if t_scale == 2 else 12
        gw = font.text_width(gain, g_scale)
        pts_w = font.text_width("PTS") + 3 if g_scale == 3 else 0
        gx = cx - (gw + pts_w) // 2
        d.text(img, gain, gx, gy, gain_fill, g_scale, "left", d.BLACK)
        if pts_w:
            d.text(img, "PTS", gx + gw + 3, gy + font.text_height(g_scale) - 5, d.scale(d.GREEN, 0.8), 1, "left", d.BLACK)
        ny = gy + font.text_height(g_scale) + 4
        ctx.label(img, name, cx, ny, cw - 4, d.WHITE, t, "center", d.BLACK)
        ctx.label(img, desc, cx, ny + 7, cw - 4, accent, t, "center", d.BLACK)
        d.rect(img, 0, 53, w, 11, (6, 8, 12))
        d.hline(img, 0, 53, w, (30, 36, 50))
        d.dot(img, 4, 58, d.RED)
        d.text(img, "LIVE", 8, 56, d.RED)
        matchup = f"{item.get('team', '')} VS {item.get('opp', '')}" if item.get("opp") else str(item.get("team", ""))
        room = w - 3 - (8 + font.text_width("LIVE") + 4)
        for right in (f"{matchup}  {ctx.week_label().split('  ')[0]}", matchup, str(item.get("team", ""))):
            if font.text_width(right) <= room:
                d.text(img, right, w - 3, 56, d.GRAY, 1, "right")
                break
        return img
    # short
    if cw >= 96:
        tx = x0 + 3
        d.text(img, title, tx, 1, d.GOLD, 1, "left", d.BLACK)
        gw = d.text(img, gain, tx, 8, gain_fill, 2, "left", d.BLACK)
        d.text(img, "PTS", tx + gw + 3, 13, d.scale(d.GREEN, 0.8), 1, "left", d.BLACK)
        total_room = 44 if cw >= 150 else 0
        ctx.label(img, name, tx, 20, cw - 6 - total_room, d.WHITE, t, "left", d.BLACK)
        ctx.label(img, desc, tx, 26, cw - 6 - total_room, accent, t, "left", d.BLACK)
        total = model.fmt_points(item.get("total"))
        if cw >= 150:
            d.big_number(img, total, w - 3, 8, ctx.tier_color(item.get("total")), 2, "right")
            d.text(img, "TOTAL", w - 3, 20, d.GRAY, 1, "right")
        return img
    d.text(img, font.fit(title, cw - 2), cx, 1, d.GOLD, 1, "center", d.BLACK)
    d.text(img, gain, cx, 8, gain_fill, 2, "center", d.BLACK)
    ctx.label(img, name, cx, 20, cw - 2, d.WHITE, t, "center", d.BLACK)
    ctx.label(img, desc, cx, 26, cw - 2, accent, t, "center", d.BLACK)
    return img


# ----------------------------------------------------------------------
# S4 dud alert
# ----------------------------------------------------------------------

def dud(ctx: RenderContext, item: Dict[str, Any], w: int, h: int, t: float) -> Image.Image:
    """``item``: a bust from :func:`model.busts`, optionally with ``pair``."""
    if w >= 192:
        second = item.get("pair")
        half = (w - 1) // 2
        img = Image.new("RGB", (w, h), d.BLACK)
        if second:
            img.paste(dud(ctx, dict(item, pair=None), half, h, t), (0, 0))
            d.rect(img, half, 0, 1, h, d.DIM)
            img.paste(dud(ctx, dict(second, pair=None), w - half - 1, h, t), (half + 1, 0))
        else:
            one = dud(ctx, dict(item, pair=None), 128, h, t)
            img.paste(one, ((w - 128) // 2, 0))
        return img
    if h >= 64:
        return _dud_tall(ctx, item, w, t) if w >= 96 else _dud_tall_narrow(ctx, item, w, t)
    return _dud_short(ctx, item, w, t) if w >= 96 else _dud_short_narrow(ctx, item, w, t)


def _dud_numbers(ctx: RenderContext, item: Dict[str, Any], t: float):
    k = ease((t - 0.5) / 1.6) if ctx.animate else 1.0
    proj, pts = float(item["proj"]), float(item["pts"])
    shown = model.fmt_points(proj - (proj - pts) * k)
    return proj, pts, shown, k


def _dud_reason(item: Dict[str, Any]) -> Tuple[str, RGB]:
    p = item["player"]
    if item.get("left_early"):
        snaps = model.stat(p, "off_snp")
        team_snaps = model.stat(p, "tm_off_snp")
        if snaps and team_snaps and p.get("pos") not in ("K", "DEF"):
            return (f"LEFT EARLY {model.fmt_count(snaps)}/{model.fmt_count(team_snaps)} SNAPS", d.ORANGE)
        return ("LEFT EARLY", d.ORANGE)
    return (f"-{model.fmt_points(item['miss'])} VS PROJ", d.scale(d.RED, 0.85))


def _dud_tall(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 64), d.BLACK)
    p = item["player"]
    proj, pts, shown, k = _dud_numbers(ctx, item, t)
    d.hazard(img, 0, 0, w, 9, int(t * 8) if ctx.animate else 0)
    label_w = font.text_width("DUD ALERT") + 10
    d.rect(img, (w - label_w) // 2, 1, label_w, 7, (8, 4, 6))
    d.text(img, "DUD ALERT", w // 2, 2, d.RED, 1, "center")
    pw = 33 if w >= 120 else 26
    ctx.picture(img, p, 1, 10, pw, 53)
    d.rect(img, 1, 10, pw, 53, (255, 0, 30), 0.08)
    code = model.injury_tag(p.get("injury"))
    if code:
        box_w = font.text_width(code) + 4
        d.injury_box(img, pw + 1 - box_w, 11, code)
    x0 = pw + 5
    avail = w - x0 - 3
    ctx.label(img, p.get("name", ""), x0, 12, avail, d.WHITE, t)
    tag_w = d.pos_tag(img, x0, 19, p.get("pos", ""))
    matchup = f"{p.get('team', '')} VS {p.get('opp', '')}" if p.get("opp") else str(p.get("team", ""))
    if font.text_width(matchup) > avail - tag_w - 3:
        matchup = str(p.get("team", ""))
    d.text(img, matchup, x0 + tag_w + 3, 20, d.GRAY)
    d.text(img, f"PROJ {model.fmt_points(proj)}", x0, 29, d.GRAY)
    d.hp_bar(img, x0, 36, avail, 5, proj, pts, k)
    num_w = d.big_number(img, shown, x0, 45, d.RED, 2)
    miss = f"-{model.fmt_points(item['miss'])}"
    if x0 + num_w + 4 + font.text_width(miss) <= w - 3:
        d.text(img, miss, w - 3, 50, d.scale(d.RED, 0.85), 1, "right")
    reason, color = _dud_reason(item)
    if item.get("left_early"):
        d.text(img, font.fit(reason, avail), x0, 57, color)
    return img


def _dud_tall_narrow(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 64), d.BLACK)
    p = item["player"]
    proj, pts, shown, k = _dud_numbers(ctx, item, t)
    d.hazard(img, 0, 0, w, 9, int(t * 8) if ctx.animate else 0)
    d.rect(img, (w - 44) // 2, 1, 44, 7, (8, 4, 6))
    d.text(img, "DUD ALERT", w // 2, 2, d.RED, 1, "center")
    ctx.picture(img, p, 1, 10, 24, 28)
    d.rect(img, 1, 10, 24, 28, (255, 0, 30), 0.08)
    x0 = 28
    avail = w - x0 - 2
    scale_ = 2 if font.text_width(shown, 2) <= avail else 1
    d.big_number(img, shown, x0, 12, d.RED, scale_)
    d.text(img, "PROJ", x0, 25, d.GRAY)
    d.text(img, model.fmt_points(proj), x0, 31, d.GRAY)
    ctx.label(img, model.display_last(p), w // 2, 41, w - 4, d.WHITE, t, "center")
    reason, color = _dud_reason(item)
    if not item.get("left_early"):
        code = model.injury_tag(p.get("injury"))
        reason = f"{p.get('pos', '')} {p.get('team', '')}" + (f" {code}" if code else "")
        color = d.GRAY
    d.text(img, font.fit(reason, w - 4), w // 2, 48, color, 1, "center")
    d.hp_bar(img, 3, 57, w - 6, 4, proj, pts, k)
    return img


def _dud_short(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 32), d.BLACK)
    p = item["player"]
    proj, pts, shown, k = _dud_numbers(ctx, item, t)
    d.hazard(img, 0, 0, 26 + 2, 32, int(t * 8) if ctx.animate else 0)
    ctx.picture(img, p, 1, 1, 26, 30)
    d.rect(img, 1, 1, 26, 30, (255, 0, 30), 0.1)
    code = model.injury_tag(p.get("injury"))
    if code:
        d.injury_box(img, 27 - font.text_width(code) - 4, 2, code)
    x0 = 31
    avail = w - x0 - 2
    d.text(img, "DUD ALERT", x0, 1, d.RED)
    miss = f"-{model.fmt_points(item['miss'])}"
    d.text(img, miss, w - 2, 1, d.scale(d.RED, 0.85), 1, "right")
    ctx.label(img, model.display_last(p), x0, 8, avail, d.WHITE, t)
    num_w = d.big_number(img, shown, x0, 15, d.RED, 2)
    side = f"OF {model.fmt_points(proj)}"
    if item.get("left_early"):
        side = "LEFT EARLY"
    if x0 + num_w + 4 + font.text_width(side) <= w - 2:
        d.text(img, side, x0 + num_w + 4, 20, d.ORANGE if item.get("left_early") else d.GRAY)
    d.hp_bar(img, x0 + 1, 28, avail - 2, 2, proj, pts, k)
    return img


def _dud_short_narrow(ctx: RenderContext, item: Dict[str, Any], w: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, 32), d.BLACK)
    p = item["player"]
    proj, pts, shown, k = _dud_numbers(ctx, item, t)
    d.hazard(img, 0, 0, w, 7, int(t * 8) if ctx.animate else 0)
    d.rect(img, (w - 42) // 2, 0, 42, 7, (8, 4, 6))
    d.text(img, "DUD ALERT", w // 2, 1, d.RED, 1, "center")
    ctx.label(img, model.display_last(p), w // 2, 9, w - 2, d.WHITE, t, "center")
    num_w = d.big_number(img, shown, 2, 16, d.RED, 2)
    side = "EARLY" if item.get("left_early") else f"/{model.fmt_points(proj)}"
    if 2 + num_w + 3 + font.text_width(side) <= w - 1:
        d.text(img, side, 2 + num_w + 3, 21, d.ORANGE if item.get("left_early") else d.GRAY)
    d.hp_bar(img, 2, 28, w - 4, 2, proj, pts, k)
    return img


# ----------------------------------------------------------------------
# S6 position kings
# ----------------------------------------------------------------------

def kings(ctx: RenderContext, item: Dict[str, Any], w: int, h: int, t: float) -> Image.Image:
    """``item``: ``{"cells": [(pos, player or None), ...]}``."""
    cells = item.get("cells") or []
    img = Image.new("RGB", (w, h), d.BLACK)
    if not cells:
        return img
    tall = h >= 64
    if w >= 192:
        cols, rows = len(cells), 1
    elif w >= 96:
        cols, rows = 3, 2
    elif tall:
        return _kings_list(ctx, cells, w, h, t)
    else:
        cols, rows = 2, 3
    gap = 1
    # Spread the leftover pixels over the first columns so the grid reaches
    # both edges (six 41 px cells left 5 px of black on a 256 px panel).
    widths = [(w - gap * (cols - 1)) // cols] * cols
    for extra in range((w - gap * (cols - 1)) - sum(widths)):
        widths[extra] += 1
    ch = (h - gap * (rows - 1)) // rows
    for i, (pos, p) in enumerate(cells[:cols * rows]):
        col, row = i % cols, i // cols
        k = max(0.0, min(1.0, (t - 0.15 * i) / 0.3)) if ctx.animate else 1.0
        if k <= 0:
            continue
        cell = _king_cell(ctx, pos, p, widths[col], ch, k, t)
        img.paste(cell, (sum(widths[:col]) + col * gap, row * (ch + gap)))
    return img


def _king_cell(ctx: RenderContext, pos: str, p: Optional[Dict[str, Any]], w: int, h: int, k: float,
               t: float = 99.0) -> Image.Image:
    img = Image.new("RGB", (w, h), d.BLACK)
    pc = d.POSITION_COLORS.get(pos, d.GRAY)
    if h < 14:
        d.text(img, pos, 1, max(0, (h - 5) // 2), d.scale(pc, k))
        if p is not None:
            value = ctx.pts(p)
            d.text(img, model.fmt_points(value), w - 1, max(0, (h - 5) // 2), d.scale(ctx.tier_color(value), k), 1, "right")
        return img
    d.rect(img, 0, 0, w, h, d.scale(pc, 0.1 * k))
    if h < 24:
        d.text(img, pos, 2, 1, d.scale(pc, k))
        if p is not None:
            value = ctx.pts(p)
            d.text(img, model.fmt_points(value), w - 2, 1, d.scale(ctx.tier_color(value), k), 1, "right")
            ctx.label(img, model.display_last(p), 2, 8, w - 3, d.scale(d.WHITE, k), t)
        return img
    d.rect(img, 0, 0, w, 7, d.scale(pc, k))
    d.text(img, pos, 2, 1, d.INK)
    if p is None:
        d.text(img, "-", w // 2, h // 2, d.GRAY, 1, "center")
        return img
    d.text(img, str(p.get("team", "")), w - 2, 1, d.INK, 1, "right")
    value = ctx.pts(p)
    color = d.scale(ctx.tier_color(value), k)
    pts_text = model.fmt_points(value)
    pts_scale = 2 if font.text_width(pts_text, 2) <= w - 2 else 1
    pts_y = h - font.text_height(pts_scale)
    name_top = 9
    if h >= 48:
        pic_h = pts_y - 9 - 8 - 2
        pic_w = min(w - 4, int(pic_h * 0.8))
        if pic_h >= 16:
            ctx.picture(img, p, (w - pic_w) // 2, 9, pic_w, pic_h)
            name_top = 9 + pic_h + 2
    two_rows = pts_y - name_top >= 12
    lines = name_lines(model.display_last(p), w - 2, 2 if two_rows else 1)
    if len(lines) == 1:
        ctx.label(img, model.display_last(p), w // 2, name_top, w - 2, d.scale(d.WHITE, k), t, "center")
    else:
        for j, line in enumerate(lines):
            d.text(img, line, w // 2, name_top + j * 6, d.scale(d.WHITE, k), 1, "center")
    d.big_number(img, pts_text, w // 2, pts_y, color, pts_scale, "center", shadow=False)
    return img


def _kings_list(ctx: RenderContext, cells, w: int, h: int, t: float) -> Image.Image:
    img = Image.new("RGB", (w, h), d.BLACK)
    d.hgrad(img, 0, 0, w, 7, (150, 110, 10), (90, 40, 120))
    d.crown(img, 2, 1)
    d.text(img, "KINGS", 11, 1, d.WHITE)
    row_h = (h - 8) // max(1, len(cells))
    for i, (pos, p) in enumerate(cells):
        y = 9 + i * row_h
        d.text(img, pos, 1, y, d.POSITION_COLORS.get(pos, d.GRAY))
        if p is None:
            continue
        value = ctx.pts(p)
        pts_text = model.fmt_points(value)
        right = w - 1 - font.text_width(pts_text)
        d.text(img, pts_text, w - 1, y, ctx.tier_color(value), 1, "right")
        ctx.label(img, model.display_last(p), 15, y, right - 16, d.WHITE, t)
    return img


# ----------------------------------------------------------------------
# S10 league matchup
# ----------------------------------------------------------------------

def matchup(ctx: RenderContext, item: Dict[str, Any], w: int, h: int, t: float) -> Image.Image:
    """``item``: ``{"league", "week", "matchup": {"home", "away", "mine"}, "pair"?}``."""
    if w >= 192:
        img = Image.new("RGB", (w, h), d.BLACK)
        half = (w - 1) // 2
        img.paste(matchup(ctx, dict(item, pair=None), half, h, t), (0, 0))
        d.rect(img, half, 0, 1, h, d.DIM)
        other = item.get("pair")
        if other:
            img.paste(matchup(ctx, dict(item, matchup=other, pair=None), w - half - 1, h, t), (half + 1, 0))
        return img
    img = Image.new("RGB", (w, h), d.BLACK)
    m = item.get("matchup") or {}
    home, away = m.get("home") or {}, m.get("away") or {}
    hp, ap = float(home.get("points") or 0.0), float(away.get("points") or 0.0)
    k = ease(t / 1.0) if ctx.animate else 1.0
    tall = h >= 64
    rows = [(home, hp), (away, ap)]
    top = 1
    if tall:
        d.hgrad(img, 0, 0, w, 9, (24, 96, 200), (112, 52, 190))
        right = f"WK {item.get('week')}" if item.get("week") else ""
        d.text(img, font.fit(item.get("league") or "LEAGUE", w - font.text_width(right) - 8), 2, 2, d.WHITE)
        if right:
            d.text(img, right, w - 2, 2, d.WHITE, 1, "right")
        top = 12
    row_h = 19 if tall else 13
    for i, (side, value) in enumerate(rows):
        y = top + i * row_h
        leading = value > (ap if i == 0 else hp)
        color = d.GOLD if leading else d.WHITE
        pts_text = model.fmt_points(value * k)
        p_scale = 2 if font.text_width(pts_text, 2) <= w // 2 - 4 else 1
        pts_w = d.big_number(img, pts_text, w - 2, y, color, p_scale, "right", shadow=False)
        x = 2
        if i == 0 and m.get("mine"):
            x += d.tag(img, x, y, "YOU", d.RARE) + 2
        name_w = w - pts_w - 6 - x
        ctx.label(img, side.get("name", ""), x, y + (1 if not tall else 0), name_w, d.GOLD if leading else d.WHITE, t)
        if tall and side.get("record"):
            d.text(img, side["record"], x, y + 7, d.GRAY)
    bar_y = top + 2 * row_h + (0 if tall else -1)
    bar_h = 5 if tall else 3
    total = hp + ap
    share = 0.5 if total <= 0 else hp / total
    bw = w - 4
    split = int(round(bw * (0.5 + (share - 0.5) * k)))
    d.rect(img, 2, bar_y, split, bar_h, d.RARE)
    d.rect(img, 2 + split, bar_y, bw - split, bar_h, d.RED)
    d.rect(img, 2 + split, bar_y - 1, 1, bar_h + 2, d.WHITE)
    if tall:
        status = ctx.status or ("FINAL" if ctx.phase == model.PHASE_RECAP else "")
        if status:
            d.text(img, status, w // 2, bar_y + bar_h + 3, d.RED if status == "LIVE" else d.GRAY, 1, "center")
    return img


# ----------------------------------------------------------------------
# S11 Vegas ticker entries
# ----------------------------------------------------------------------

def vegas_entry(ctx: RenderContext, p: Dict[str, Any], height: int) -> Image.Image:
    """One ticker item: chip, name, points in the tier colour, sized to ``height``.

    Drawn at 1x and scaled up whole on panels 48 px and taller, so the
    ticker reads at the same weight as the cards.
    """
    scale_ = 2 if height >= 48 else 1
    name = model.display_last(p)
    value = ctx.pts(p)
    pts_text = model.fmt_points(value)
    base_w = 2 + 11 + 4 + font.text_width(name) + 4 + font.text_width(pts_text) + 8
    base = Image.new("RGB", (base_w, max(8, height // scale_)), d.BLACK)
    y = (base.height - 7) // 2
    x = 2
    d.chip(base, x, y, 11, 7, team_info(p.get("team")), ctx.jersey(p))
    x += 15
    x += d.text(base, name, x, y + 1, d.WHITE) + 4
    d.text(base, pts_text, x, y + 1, ctx.tier_color(value))
    if scale_ > 1:
        base = base.resize((base.width * scale_, base.height * scale_), Image.NEAREST)
    out = Image.new("RGB", (base.width, height), d.BLACK)
    out.paste(base, (0, (height - base.height) // 2))
    return out


def vegas_title(height: int, label: str = "FANTASY") -> Image.Image:
    scale_ = 2 if height >= 48 else 1
    w = font.text_width(label, scale_) + 16
    img = Image.new("RGB", (w, height), d.BLACK)
    y = (height - font.text_height(scale_)) // 2
    d.big_number(img, label, 4, y, d.GOLD, scale_)
    return img


FLEX_HEIGHT.update({board, kings})
