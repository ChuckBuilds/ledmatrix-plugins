"""Draws the NFL stat-leader ticker as one wide image.

The whole ticker is a single RGB strip that the core's ScrollHelper then
slides past the panel, so everything here happens once per data refresh
rather than once per frame.

Rendering is pixel-perfect by design -- an LED panel has no sub-pixels, so
an anti-aliased grey lands on the panel as a dim, smeared LED:

- text is drawn with ``fontmode = "1"`` (1-bit glyphs, fully lit or off) at
  sizes snapped to each font's own pixel grid, because Press Start 2P drops
  glyph columns off-grid;
- logos are downscaled with LANCZOS for detail, then their alpha is
  thresholded so edges are a hard on/off boundary.

Colour comes from the clubs themselves. Each crest is already on disk, so
its dominant colour is sampled from the pixels rather than kept in a table
that would need maintaining -- and lifted to a luminance that actually
reads on a panel, since several official primaries are near-black.

Module name is plugin-unique so the core's flat module loading cannot bind
another plugin's ``image_renderer`` (monorepo CLAUDE.md non-negotiable #4).
"""

import colorsys
import logging
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

#: LANCZOS keeps a crest's detail as it shrinks; BOX averages evenly, which
#: is what a colour sample wants. Both are unconditional: requirements.txt
#: floors Pillow at 12.2.0, where Image.Resampling has long existed.
RESAMPLE_FILTER = Image.Resampling.LANCZOS
RESAMPLE_BOX = Image.Resampling.BOX

RGB = Tuple[int, int, int]

#: Fonts whose glyphs only rasterise cleanly at whole multiples of a grid.
PIXEL_FONT_GRIDS = {
    "PressStart2P-Regular.ttf": 8,
    "4x6-font.ttf": 7,
}

PRIMARY_FONT_NAME = "PressStart2P-Regular.ttf"
SMALL_FONT_NAME = "4x6-font.ttf"

NFL_LOGO_DIR = os.path.join("assets", "sports", "nfl_logos")
NFL_CREST_NAME = "NFL.png"

#: Panel height at or above which an entry gets three text rows instead of
#: two. Below it there is no room for the position line on its own.
THREE_BAND_HEIGHT = 56

#: Largest automatic font size, in pixels, and the largest multiplier the
#: layout gaps are scaled by. Both exist so a very tall panel gets a
#: comfortable ticker rather than a magnified one.
MAX_FONT_SIZE = 24
MAX_GAP_SCALE = 3

# ----------------------------------------------------------------------
# Layout constants, in pixels.
# ----------------------------------------------------------------------

#: Width of the coloured bar that opens a card.
ACCENT_BAR_W = 2
ACCENT_GAP = 4
#: Between the rank badge and the crest.
BADGE_GAP = 3
#: Between a crest and the text column beside it.
LOGO_GAP = 4
#: Between a value and the position/team that follows it on one row.
META_GAP = 4
#: Trailing space after one player's row.
ENTRY_GAP = 12
#: Trailing space after a card, before its first player.
CARD_GAP = 10
#: Blank space between one category and the next.
BOARD_GAP = 28


WHITE: RGB = (255, 255, 255)
DIM: RGB = (150, 150, 155)
BLACK: RGB = (0, 0, 0)

#: Rank badge colours for the top three. Deliberately not the club's own
#: colour: a podium reads at a glance on a strip that is moving.
MEDAL_COLORS: Tuple[RGB, RGB, RGB] = (
    (255, 196, 0),
    (198, 203, 214),
    (205, 127, 50),
)


class TickerRenderer:
    """Builds the scrolling strip for a set of stat leaderboards."""

    #: Prepared crests, keyed by file identity and target box. Preparing one
    #: is a PNG decode plus a LANCZOS resize, and a rebuild would otherwise
    #: redo it for every entry of every category.
    _LOGO_CACHE_MAX = 256

    def __init__(self, display_height: int, logger: Optional[logging.Logger] = None,
                 appearance: Optional[Dict[str, Any]] = None):
        self.display_height = max(1, int(display_height))
        self.logger = logger or logging.getLogger(__name__)

        appearance = appearance or {}
        self.pixel_perfect_text = bool(appearance.get("pixel_perfect_text", True))
        self.crisp_logos = bool(appearance.get("crisp_logos", True))
        self.text_outline = bool(appearance.get("text_outline", True))
        self.team_color_accents = bool(appearance.get("team_color_accents", True))
        self.highlight_top_three = bool(appearance.get("highlight_top_three", True))
        self.show_league_logo = bool(appearance.get("show_league_logo", True))
        self.accent_color = _parse_color(appearance.get("accent_color"), (255, 182, 18))
        self.font_size_override = _clamp_int(appearance.get("font_size", 0), 0, 32, 0)
        self.logo_scale = _clamp_float(appearance.get("logo_scale", 1.0), 0.4, 1.4, 1.0)

        self.primary_font_path = _resolve_font_path(PRIMARY_FONT_NAME)
        self.small_font_path = _resolve_font_path(SMALL_FONT_NAME)
        self.font_primary, self.font_small = self._load_fonts()

        self._logo_cache: Dict[Any, Optional[Image.Image]] = {}
        self._accent_cache: Dict[str, RGB] = {}

        self.three_band = self.display_height >= THREE_BAND_HEIGHT
        self.pad_y = max(2, self.display_height // 10)
        # Gaps are quoted for a 32px panel and scaled with the panel, so the
        # rhythm between a crest, a name and the next player stays the same
        # on a 128px-high board instead of collapsing into one dense block.
        self._scale = max(1, min(MAX_GAP_SCALE, self.display_height // 32))

    def _gap(self, base: int) -> int:
        """A layout constant, scaled to this panel."""
        return base * self._scale

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------

    def _base_font_size(self) -> int:
        """An on-grid size that suits the panel height.

        Capped rather than scaled all the way up: a quarter of a 128px panel
        is 32px of Press Start 2P, at which one player's name is wider than
        a 256px board and the ticker reads one word at a time. The cap keeps
        glyphs large and legible while still fitting a name on screen.
        """
        grid = PIXEL_FONT_GRIDS[PRIMARY_FONT_NAME]
        requested = self.font_size_override or max(grid, self.display_height // 4)
        snapped = int(round(requested / grid)) * grid
        if self.font_size_override:
            return max(grid, snapped)
        return max(grid, min(MAX_FONT_SIZE, snapped))

    def _small_font_size(self, base: int) -> int:
        """The meta face, at the grid step closest to two thirds of ``base``."""
        grid = PIXEL_FONT_GRIDS[SMALL_FONT_NAME]
        steps = max(1, int(round((base * 0.66) / grid)))
        return grid * steps

    def _load_fonts(self) -> Tuple[ImageFont.ImageFont, ImageFont.ImageFont]:
        """The name/value face and the smaller meta face.

        Two faces rather than two sizes of one: at a panel's scale a second
        size of Press Start 2P is either the same height or twice it, so the
        4x6 face is the only way to get a genuinely subordinate line.
        """
        size = self._base_font_size()
        primary = self._truetype(self.primary_font_path, size)

        small = self._truetype(self.small_font_path, self._small_font_size(size))

        if primary is None and small is None:
            self.logger.warning("No pixel font found; falling back to PIL's default")
            default = ImageFont.load_default()
            return default, default
        return primary or small, small or primary

    def _truetype(self, path: Optional[str], size: int) -> Optional[ImageFont.ImageFont]:
        if not path:
            return None
        try:
            font = ImageFont.truetype(path, size)
            self.logger.debug("Loaded %s at %spx", os.path.basename(path), size)
            return font
        except (IOError, OSError) as exc:
            self.logger.warning("Could not load %s: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def _make_draw(self, image: Image.Image) -> ImageDraw.ImageDraw:
        """A draw context that rasterises glyphs 1-bit.

        Measuring canvases go through this too, so measured widths match
        what is actually drawn.
        """
        draw = ImageDraw.Draw(image)
        if self.pixel_perfect_text:
            draw.fontmode = "1"
        return draw

    @staticmethod
    def _advance(text: str, font) -> int:
        """Width a string occupies, in whole pixels."""
        if not text:
            return 0
        try:
            return int(math.ceil(font.getlength(text)))
        except AttributeError:  # pragma: no cover - very old Pillow
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0])

    @staticmethod
    def _ink_box(text: str, font) -> Tuple[int, int]:
        try:
            bbox = font.getbbox(text or "X")
        except AttributeError:  # pragma: no cover - very old Pillow
            return 0, int(getattr(font, "size", 8))
        return int(bbox[1]), int(bbox[3] - bbox[1])

    def _baseline_y(self, text: str, font, band_top: int, band_height: int) -> int:
        """Y for ``draw.text`` that centres a string's ink in a band.

        ``draw.text`` positions by the ascender, not the ink box, so without
        this the line sits low and can clip off the panel.
        """
        ink_top, ink_height = self._ink_box(text, font)
        return band_top + (band_height - ink_height) // 2 - ink_top

    def _draw_text(self, draw: ImageDraw.ImageDraw, text: str, x: int, y: int,
                   font, fill: RGB) -> None:
        if not text:
            return
        if self.text_outline:
            for dx, dy in ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                           (0, 1), (1, -1), (1, 0), (1, 1)):
                draw.text((x + dx, y + dy), text, font=font, fill=BLACK)
        draw.text((x, y), text, font=font, fill=fill)

    def _band_height(self, font) -> int:
        _, ink_height = self._ink_box("Ag", font)
        return max(1, ink_height)

    # ------------------------------------------------------------------
    # Logos and colour
    # ------------------------------------------------------------------

    def _logo_path(self, abbr: str) -> Optional[str]:
        """Where a crest lives, resolved without depending on the cwd."""
        if not abbr:
            return None
        for root in _asset_roots():
            candidate = Path(root, NFL_LOGO_DIR, f"{abbr}.png")
            if candidate.exists():
                return str(candidate)
        return None

    def _prepare_logo(self, path: str, box_w: int, box_h: int) -> Optional[Image.Image]:
        """Scale a crest into a box, preserving aspect and hardening edges."""
        if box_w <= 0 or box_h <= 0:
            return None
        try:
            logo = Image.open(path).convert("RGBA")
            scale = min(box_w / logo.width, box_h / logo.height)
            target = (max(1, int(logo.width * scale)), max(1, int(logo.height * scale)))
            logo = logo.resize(target, RESAMPLE_FILTER)
            if self.crisp_logos:
                r, g, b, a = logo.split()
                a = a.point(lambda p: 255 if p >= 128 else 0)
                logo = Image.merge("RGBA", (r, g, b, a))
            return logo
        except Exception as exc:  # noqa: BLE001 - a bad PNG must not stop the ticker
            self.logger.warning("Could not prepare logo %s: %s", path, exc)
            return None

    def _logo(self, abbr: str, box_w: int, box_h: int) -> Optional[Image.Image]:
        """A prepared crest, decoded and resized at most once per file version.

        Keyed on mtime as well as path so a crest replaced on disk is picked
        up rather than served stale forever. A miss is not cached: a file
        that appears later would otherwise stay invisible until restart.
        """
        path = self._logo_path(abbr)
        if not path:
            return None
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = None

        key = (path, stamp, box_w, box_h, self.crisp_logos)
        if stamp is not None and key in self._logo_cache:
            return self._logo_cache[key]

        prepared = self._prepare_logo(path, box_w, box_h)
        if stamp is not None:
            if len(self._logo_cache) >= self._LOGO_CACHE_MAX:
                self._logo_cache.clear()
            self._logo_cache[key] = prepared
        return prepared

    def team_accent(self, abbr: str) -> RGB:
        """The club's colour, sampled from its crest and lifted to read.

        ESPN does serve team colours, but only on endpoints this plugin has
        no reason to call, and several official primaries are black or
        near-black navy -- which on an LED panel is indistinguishable from
        off. Sampling the crest costs no request and yields the colour the
        club is actually recognised by.
        """
        if not self.team_color_accents or not abbr:
            return self.accent_color
        cached = self._accent_cache.get(abbr)
        if cached is not None:
            return cached

        colour = self.accent_color
        path = self._logo_path(abbr)
        if path:
            try:
                with Image.open(path) as source:
                    sampled = _dominant_color(source)
                if sampled:
                    colour = _lift(sampled)
            except Exception as exc:  # noqa: BLE001 - fall back to the accent
                self.logger.debug("Could not sample %s crest: %s", abbr, exc)

        self._accent_cache[abbr] = colour
        return colour

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _bands(self, fonts: Sequence[Any]) -> List[Tuple[int, int]]:
        """Stacked text bands, one per font, centred vertically on the panel.

        Sized from the fonts themselves so a small-font row does not reserve
        a full-size band and pull the block off centre.
        """
        heights = [self._band_height(font) for font in fonts]
        gap = 1 * self._scale
        total = sum(heights) + gap * (len(heights) - 1)
        top = max(0, (self.display_height - total) // 2)

        bands = []
        y = top
        for height in heights:
            bands.append((y, height))
            y += height + gap
        return bands

    def _logo_box(self) -> int:
        """Side of the square a crest is fitted into.

        Tied to the text as well as to the panel: on a tall board the text
        stops growing at MAX_FONT_SIZE, and a crest that kept growing with
        the panel would tower over the name beside it.
        """
        usable = self.display_height - 2 * self.pad_y
        text_relative = int(self._band_height(self.font_primary) * 2.6)
        box = min(int(self.display_height * 0.62), max(text_relative, 16))
        return max(8, min(usable, int(box * self.logo_scale)))

    def _entry_plan(self, leader: Dict[str, Any]) -> Dict[str, Any]:
        """Measure one leaderboard row. Measuring and drawing share this plan
        so the strip is never wider or narrower than what gets drawn."""
        rank_text = str(leader.get("rank", ""))
        name = str(leader.get("name", ""))
        value = str(leader.get("value", ""))
        team = str(leader.get("team", ""))
        position = str(leader.get("position", ""))
        meta = " ".join(part for part in (position, team) if part)

        band_fonts = ((self.font_primary, self.font_primary, self.font_small)
                      if self.three_band
                      else (self.font_primary, self.font_primary))
        bands = self._bands(band_fonts)
        badge_h = max(7, self._band_height(self.font_primary) + 4)
        badge_w = max(badge_h, self._advance(rank_text, self.font_small)
                      + 2 * self._scale + 3)
        logo_box = self._logo_box()

        if self.three_band:
            rows = [
                (name, self.font_primary),
                (value, self.font_primary),
                (meta, self.font_small),
            ]
            text_w = max(self._advance(text, font) for text, font in rows)
        else:
            value_w = self._advance(value, self.font_primary)
            meta_w = self._advance(meta, self.font_small)
            second_w = value_w + (self._gap(META_GAP) + meta_w if meta else 0)
            text_w = max(self._advance(name, self.font_primary), second_w)

        width = (badge_w + self._gap(BADGE_GAP) + logo_box
                 + self._gap(LOGO_GAP) + text_w + self._gap(ENTRY_GAP))
        return {
            "width": width,
            "rank_text": rank_text,
            "name": name,
            "value": value,
            "meta": meta,
            "team": team,
            "badge": (badge_w, badge_h),
            "logo_box": logo_box,
            "bands": bands,
        }

    def _card_plan(self, title: str, short_title: str,
                   subtitle: str) -> Dict[str, Any]:
        """Measure a category (or intro) card."""
        lines = self._fit_title(title, short_title)
        crest_box = self._logo_box() if self.show_league_logo else 0

        line_w = max(self._advance(text, self.font_primary) for text in lines)
        subtitle_w = self._advance(subtitle, self.font_small) if subtitle else 0
        text_w = max(line_w, subtitle_w)

        width = self._gap(ACCENT_BAR_W) + self._gap(ACCENT_GAP)
        if crest_box:
            width += crest_box + self._gap(LOGO_GAP)
        width += text_w + self._gap(CARD_GAP)
        return {
            "width": width,
            "lines": lines,
            "subtitle": subtitle,
            "crest_box": crest_box,
        }

    def _fit_title(self, title: str, short_title: str) -> List[str]:
        """Title lines for the card: one row on a three-band panel, up to two
        on a shorter one, shortened before it is ever allowed to wrap badly."""
        if self.three_band:
            # A ticker is as wide as it needs to be, so a tall panel spends
            # its one title row on the full name rather than an abbreviation.
            return [title]

        words = title.split()
        if len(words) <= 1:
            return [title]
        if len(words) == 2:
            return words
        # Three words or more only happens for titles the short form covers.
        return (short_title or title).split()[:2] or [title]

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def build_strip(self, boards: Sequence[Dict[str, Any]],
                    season_label: str) -> Optional[Image.Image]:
        """The whole ticker as one image, or None if there is nothing to show."""
        boards = [b for b in boards if b.get("leaders")]
        if not boards:
            return None

        intro = self._card_plan("STAT LEADERS", "LEADERS", season_label)
        segments: List[Dict[str, Any]] = [{"kind": "card", "plan": intro,
                                           "accent": self.accent_color}]

        for board in boards:
            card = self._card_plan(
                str(board.get("title", "")),
                str(board.get("short_title", "")),
                "",
            )
            segments.append({"kind": "card", "plan": card,
                             "accent": self.accent_color, "rule": True})
            for leader in board["leaders"]:
                segments.append({"kind": "entry", "plan": self._entry_plan(leader),
                                 "rule": True})
            segments.append({"kind": "spacer", "width": self._gap(BOARD_GAP)})

        total_width = sum(_segment_width(segment) for segment in segments)
        if total_width <= 0:
            return None

        strip = Image.new("RGB", (total_width, self.display_height), BLACK)
        draw = self._make_draw(strip)

        x = 0
        for segment in segments:
            if segment["kind"] == "spacer":
                x += segment["width"]
                continue
            plan = segment["plan"]
            if segment["kind"] == "card":
                self._draw_card(strip, draw, x, plan, segment["accent"])
            else:
                self._draw_entry(strip, draw, x, plan)
            if segment.get("rule"):
                self._draw_rule(draw, x, plan["width"])
            x += plan["width"]

        self.logger.info("Built stat-leader strip: %sx%s across %s boards",
                         strip.width, strip.height, len(boards))
        return strip

    def draw_placeholder(self, image: Image.Image) -> None:
        """A quiet holding screen for the panel while there is nothing to scroll.

        Drawn rather than left black so a user can tell the plugin is alive
        and waiting on data, not broken.
        """
        draw = self._make_draw(image)
        draw.fontmode = "1"
        draw.rectangle([0, 0, image.width - 1, image.height - 1], fill=BLACK)
        font = self.font_small
        lines = ("NFL STAT", "LEADERS")
        line_h = self._band_height(font) + 2
        top = max(0, (image.height - line_h * len(lines)) // 2)
        for index, text in enumerate(lines):
            width = self._advance(text, font)
            draw.text((max(0, (image.width - width) // 2), top + index * line_h),
                      text, font=font, fill=DIM)

    def _draw_rule(self, draw: ImageDraw.ImageDraw, x: int, width: int) -> None:
        """A dim accent line along the bottom, tying a category's segments
        together while they scroll past."""
        y = self.display_height - 1
        draw.line([(x, y), (x + width - 1, y)], fill=_scale(self.accent_color, 0.35))

    def _draw_card(self, strip: Image.Image, draw: ImageDraw.ImageDraw, x: int,
                   plan: Dict[str, Any], accent: RGB) -> None:
        bar_top = self.pad_y
        bar_bottom = self.display_height - self.pad_y - 1
        bar_w = self._gap(ACCENT_BAR_W)
        draw.rectangle([x, bar_top, x + bar_w - 1, bar_bottom], fill=accent)
        cursor = x + bar_w + self._gap(ACCENT_GAP)

        crest_box = plan["crest_box"]
        if crest_box:
            crest = self._crest(crest_box)
            if crest is not None:
                strip.paste(crest, (cursor + (crest_box - crest.width) // 2,
                                    (self.display_height - crest.height) // 2), crest)
            cursor += crest_box + self._gap(LOGO_GAP)

        lines = plan["lines"]
        subtitle = plan["subtitle"]
        rows: List[Tuple[str, Any, RGB]] = [(line, self.font_primary, accent)
                                            for line in lines]
        if subtitle:
            rows.append((subtitle, self.font_small, DIM))

        bands = self._bands([font for _, font, _ in rows])
        for (text, font, colour), (band_top, band_h) in zip(rows, bands):
            self._draw_text(draw, text, cursor,
                            self._baseline_y(text, font, band_top, band_h),
                            font, colour)

    def _crest(self, box: int) -> Optional[Image.Image]:
        for root in _asset_roots():
            candidate = Path(root, NFL_LOGO_DIR, NFL_CREST_NAME)
            if candidate.exists():
                key = ("__crest__", str(candidate), box)
                if key in self._logo_cache:
                    return self._logo_cache[key]
                prepared = self._prepare_logo(str(candidate), box, box)
                if len(self._logo_cache) >= self._LOGO_CACHE_MAX:
                    self._logo_cache.clear()
                self._logo_cache[key] = prepared
                return prepared
        return None

    def _draw_entry(self, strip: Image.Image, draw: ImageDraw.ImageDraw, x: int,
                    plan: Dict[str, Any]) -> None:
        badge_w, badge_h = plan["badge"]
        rank_text = plan["rank_text"]
        accent = self.team_accent(plan["team"])

        badge_color = accent
        if self.highlight_top_three:
            try:
                rank = int(rank_text)
            except (TypeError, ValueError):
                rank = 0
            if 1 <= rank <= len(MEDAL_COLORS):
                badge_color = MEDAL_COLORS[rank - 1]

        badge_top = (self.display_height - badge_h) // 2
        draw.rectangle(
            [x, badge_top, x + badge_w - 1, badge_top + badge_h - 1],
            fill=badge_color,
        )
        # The digit is drawn without an outline: at badge size an outline
        # eats the fill and the number stops reading.
        rank_x = x + (badge_w - self._advance(rank_text, self.font_small)) // 2
        draw.text(
            (rank_x, self._baseline_y(rank_text, self.font_small, badge_top, badge_h)),
            rank_text, font=self.font_small, fill=_readable_on(badge_color),
        )

        cursor = x + badge_w + self._gap(BADGE_GAP)
        logo_box = plan["logo_box"]
        logo = self._logo(plan["team"], logo_box, logo_box)
        if logo is not None:
            strip.paste(logo, (cursor + (logo_box - logo.width) // 2,
                               (self.display_height - logo.height) // 2), logo)
        cursor += logo_box + self._gap(LOGO_GAP)

        bands = plan["bands"]
        if self.three_band:
            rows = (
                (plan["name"], self.font_primary, WHITE),
                (plan["value"], self.font_primary, accent),
                (plan["meta"], self.font_small, DIM),
            )
            for (text, font, colour), (band_top, band_h) in zip(rows, bands):
                self._draw_text(draw, text, cursor,
                                self._baseline_y(text, font, band_top, band_h),
                                font, colour)
            return

        name_top, name_h = bands[0]
        self._draw_text(draw, plan["name"], cursor,
                        self._baseline_y(plan["name"], self.font_primary,
                                         name_top, name_h),
                        self.font_primary, WHITE)

        value_top, value_h = bands[1]
        self._draw_text(draw, plan["value"], cursor,
                        self._baseline_y(plan["value"], self.font_primary,
                                         value_top, value_h),
                        self.font_primary, accent)
        if plan["meta"]:
            meta_x = (cursor + self._advance(plan["value"], self.font_primary)
                      + self._gap(META_GAP))
            self._draw_text(draw, plan["meta"], meta_x,
                            self._baseline_y(plan["meta"], self.font_small,
                                             value_top, value_h),
                            self.font_small, DIM)


# ----------------------------------------------------------------------
# Asset and colour helpers
# ----------------------------------------------------------------------

@lru_cache(maxsize=1)
def _asset_roots() -> Tuple[str, ...]:
    """Where the core's ``assets/`` tree may be, best candidate first.

    The display service runs with the core checkout as its working
    directory and installs plugins beneath it, which is what makes the
    path-relative entries work on a Pi. The core package's own location is
    the one that matters everywhere else: it names the checkout even when
    the plugin is being rendered from the monorepo by the test harness.
    """
    here = Path(__file__).resolve()
    roots = [
        Path("."),
        # plugin dir -> plugin-repos/ -> the core checkout
        here.parent.parent.parent,
        here.parent,
    ]

    env_root = os.environ.get("LEDMATRIX_CORE")
    if env_root:
        roots.insert(0, Path(env_root))

    # The core package, read from sys.modules rather than imported: a plugin
    # only ever runs with the core already loaded, and asking for it this way
    # cannot fail, import anything, or need an except clause around it.
    core_file = getattr(sys.modules.get("src"), "__file__", None)
    if core_file:
        roots.insert(0, Path(core_file).resolve().parent.parent)

    seen = []
    for root in roots:
        text = str(root)
        if text not in seen:
            seen.append(text)
    return tuple(seen)


def _resolve_font_path(name: str) -> Optional[str]:
    for root in _asset_roots():
        candidate = Path(root, "assets", "fonts", name)
        if candidate.exists():
            return str(candidate)
    return None


def _segment_width(segment: Dict[str, Any]) -> int:
    """How much of the strip a segment occupies."""
    if segment["kind"] == "spacer":
        return int(segment["width"])
    return int(segment["plan"]["width"])


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _parse_color(value: Any, default: RGB) -> RGB:
    """Accept ``[r, g, b]`` or ``"#rrggbb"``; fall back rather than raise."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(max(0, min(255, int(c))) for c in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return default
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 6:
            try:
                return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
            except ValueError:
                return default
    return default


def _luminance255(color: RGB) -> float:
    """Rec. 709 relative luminance, 0-255."""
    r, g, b = color
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _luminance(color: RGB) -> float:
    """Rec. 709 relative luminance, 0-1."""
    return _luminance255(color) / 255.0


def _saturation(color: RGB) -> float:
    high, low = max(color), min(color)
    return 0.0 if high == 0 else (high - low) / high


def _scale(color: RGB, factor: float) -> RGB:
    return tuple(max(0, min(255, int(c * factor))) for c in color)  # type: ignore[return-value]


def _readable_on(background: RGB) -> RGB:
    """Black or white, whichever the badge digit will actually read in."""
    return BLACK if _luminance(background) > 0.45 else WHITE


# ----------------------------------------------------------------------
# Crest colour
#
# The same two-stage approach the football scoreboard uses for its scoring
# celebration (plugins/football-scoreboard/sports.py, _logo_palette): bucket
# the crest's opaque pixels, then rank them by how well each would survive
# being shrunk to a few pixels of text rather than by area. Area alone picks
# the largest block, which on many crests is a navy fill -- right as a
# backdrop, invisible as a number. That ranking was checked against ESPN's
# own colours for all 32 clubs; only the headline half of it is needed here.
# ----------------------------------------------------------------------

#: Sampling grid. Small enough to be free, large enough that a crest's
#: secondary colour is still represented.
_SAMPLE_PX = 40
#: Saturation at which a pixel counts as paint rather than outline or field.
_VIVID_SATURATION = 0.22
#: Below this on every channel a pixel is shadow, not colour.
_MIN_CHANNEL = 24
#: Luminance (0-255) a colour is lifted to before it is drawn as text.
_HEADLINE_LUMINANCE = 112.0
#: A candidate must clear these to win on legibility rather than on score.
_LEGIBLE_LUMINANCE = 90.0
_LEGIBLE_SATURATION = 0.65
_LEGIBLE_AREA = 0.02
#: Lifting a deep blue runs out of value long before it is legible, so
#: saturation is bled out instead -- floored here so it never reaches white.
_MIN_SATURATION = 0.42


def _palette_buckets(image: Image.Image):
    """Bucket a crest's opaque pixels into coarse bins.

    Returns ``(vivid, neutral)``, each mapping a 3-bit-per-channel key to
    ``[r_sum, g_sum, b_sum, count]``. Neutral holds the greys and silvers
    that carry no identity alone but are all a monochrome crest -- the
    Raiders' silver on black -- has to offer.
    """
    sample = image.convert("RGBA")
    sample.thumbnail((_SAMPLE_PX, _SAMPLE_PX), RESAMPLE_BOX)
    vivid: Dict[Tuple[int, int, int], List[int]] = {}
    neutral: Dict[Tuple[int, int, int], List[int]] = {}
    # tobytes() rather than getdata(): same pixels, no per-pixel Python
    # object, and getdata() is deprecated from Pillow 14.
    raw = sample.tobytes()
    for i in range(0, len(raw) - 3, 4):
        red, green, blue, alpha = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        if alpha < 160:
            continue
        high, low = max(red, green, blue), min(red, green, blue)
        if high < _MIN_CHANNEL:
            continue
        target = vivid if (high - low) / high >= _VIVID_SATURATION else neutral
        acc = target.setdefault((red >> 5, green >> 5, blue >> 5), [0, 0, 0, 0])
        acc[0] += red
        acc[1] += green
        acc[2] += blue
        acc[3] += 1
    return vivid, neutral


def _bucket_mean(acc: List[int]) -> RGB:
    count = acc[3]
    return (acc[0] // count, acc[1] // count, acc[2] // count)


def _headline_score(acc: List[int]) -> float:
    """How well a bin would serve as a few pixels of text on a panel."""
    colour = _bucket_mean(acc)
    return (
        acc[3]
        * (0.30 + 0.70 * _saturation(colour))
        * (0.20 + 0.80 * min(1.0, _luminance255(colour) / 120.0))
    )


def _dominant_color(image: Image.Image) -> Optional[RGB]:
    """The colour a crest reads as when drawn small, or None."""
    try:
        vivid, neutral = _palette_buckets(image)
    except Exception:  # noqa: BLE001 - an unreadable crest just has no colour
        return None

    pool = list(vivid.values())
    if not pool and neutral:
        # A monochrome crest: its brightest neutral is the only identity it
        # has, and for silver-on-black that is exactly right.
        pool = [max(
            neutral.values(),
            key=lambda acc: acc[3] * (
                0.2 + 0.8 * min(1.0, _luminance255(_bucket_mean(acc)) / 160.0)),
        )]
    if not pool:
        return None

    ranked = sorted(pool, key=_headline_score, reverse=True)
    chosen = _bucket_mean(ranked[0])
    vivid_pixels = sum(acc[3] for acc in pool)
    for acc in ranked:
        candidate = _bucket_mean(acc)
        if (_luminance255(candidate) >= _LEGIBLE_LUMINANCE
                and _saturation(candidate) >= _LEGIBLE_SATURATION
                and acc[3] >= max(3, vivid_pixels * _LEGIBLE_AREA)):
            chosen = candidate
            break
    return chosen


def _lift(colour: RGB, min_luminance: float = _HEADLINE_LUMINANCE) -> RGB:
    """Raise a colour's brightness until it reads on a panel, keeping its hue.

    Scaling the channels is the obvious version and it shifts hue badly on
    exactly the colours that need lifting -- it turns Baltimore's
    navy-purple into magenta. Working in HSV and raising only the value
    leaves the hue where the club put it.
    """
    if _luminance255(colour) >= min_luminance:
        return tuple(int(c) for c in colour)  # type: ignore[return-value]

    hue, sat, value = colorsys.rgb_to_hsv(*[c / 255.0 for c in colour])
    if sat < 0.12:
        lifted = colorsys.hsv_to_rgb(hue, sat, max(value, 0.85))
        return tuple(int(round(c * 255)) for c in lifted)  # type: ignore[return-value]
    sat = min(sat, 0.92)

    def _rgb(s: float, v: float) -> RGB:
        return tuple(int(round(c * 255))  # type: ignore[return-value]
                     for c in colorsys.hsv_to_rgb(hue, s, v))

    out = _rgb(sat, value)
    while value < 1.0 and _luminance255(out) < min_luminance:
        value = min(1.0, value + 0.05)
        out = _rgb(sat, value)
    # Blue carries almost no luminance -- pure blue sits at 18 of 255 -- so a
    # navy runs out of value long before it is legible. Bleeding saturation
    # is the only way up, and it keeps the hue.
    while sat > _MIN_SATURATION and _luminance255(out) < min_luminance:
        sat = max(_MIN_SATURATION, sat - 0.05)
        out = _rgb(sat, value)
    return out
