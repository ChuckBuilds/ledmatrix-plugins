"""
Card renderer for the upcoming-media plugin.

Every upcoming item is drawn as one *card* at panel height:

- an image slot (poster on the left, or the show's clearlogo -- on the left on
  short panels, across the top on tall ones), and
- text lines in priority order, packed into whatever height the fonts allow:
  title (skipped when the logo already says it), episode number + name (or a
  movie's release type), date + runtime, then the short description.

A switch-mode card is exactly the panel size. A strip card (scroll / Vegas)
is as wide as its content, capped, so short items do not drag a panel-width
of black through the marquee.

Nothing here does I/O: images come from an ``ImageStore`` that update() filled.
The module name is plugin-unique (CLAUDE.md non-negotiable 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from upcoming_media_sources import ImageStore, UpcomingItem, short_description

ELLIPSIS = "..."

# Font per element per size tier: (file under assets/fonts, pixel size).
# Bitmap (.bdf) faces exist at one size only; the ttf sizes sit on each face's
# crisp grid (src.common.font_layout.FONT_PIXEL_GRID).
TIER_FONTS: Dict[str, Dict[str, Tuple[str, int]]] = {
    "small": {
        # 6-px-wide faces: 5-px ones (4x6, 5x7) leave 3 px for m/w and they
        # smear on a real panel. Three lines fit in 32 px; the description
        # is the line that drops.
        "title": ("6x10.bdf", 10),
        "episode": ("6x9.bdf", 9),
        "date": ("6x9.bdf", 9),
        "description": ("6x9.bdf", 9),
    },
    "medium": {
        "title": ("6x13B.bdf", 13),
        "episode": ("6x10.bdf", 10),
        "date": ("5x8.bdf", 8),
        "description": ("5x8.bdf", 8),
    },
    "large": {
        "title": ("9x15B.bdf", 15),
        "episode": ("7x13.bdf", 13),
        "date": ("6x10.bdf", 10),
        "description": ("6x10.bdf", 10),
    },
}
ELEMENTS = ("title", "episode", "date", "description")


def size_tier(width: int, height: int) -> str:
    """Pick a font tier from the panel. A 256x32 strip is still 'small':
    height is what limits the line count; width only caps it for narrow
    square panels (64x64 behaves like 64x32 per line of text)."""
    scale = min(height, width // 2)
    if scale >= 96:
        return "large"
    if scale >= 56:
        return "medium"
    return "small"


@dataclass
class RenderSettings:
    show_episode_title: bool = True
    show_description: bool = True
    show_runtime: bool = True
    show_date: bool = True
    episode_format: str = "compact"          # compact | padded | long
    image_type: str = "auto"                 # auto | logo | poster | none
    date_format: str = "relative"            # relative | short | numeric
    time_format: str = "12h"                 # 12h | 24h
    description_max_chars: int = 60
    colors: Dict[str, Tuple[int, int, int]] = field(default_factory=lambda: {
        "title": (255, 255, 255),
        "episode": (120, 200, 255),
        "date": (255, 190, 60),
        "description": (170, 170, 170),
    })
    accent_color: Tuple[int, int, int] = (124, 77, 255)
    background_color: Tuple[int, int, int] = (0, 0, 0)
    highlight_today: bool = True
    today_color: Tuple[int, int, int] = (90, 255, 120)
    strip_max_text_width: int = 192


@dataclass
class _Line:
    text: str
    element: str
    right: str = ""          # right-aligned companion (runtime)
    color: Optional[Tuple[int, int, int]] = None
    keep: int = 0            # leading chars never cut ("S1E8" before the name)


# ---------------------------------------------------------------------------
# Text formatting (pure)
# ---------------------------------------------------------------------------

def format_episode_number(item: UpcomingItem, fmt: str) -> str:
    if item.season is None and item.episode is None:
        return ""
    season = item.season if item.season is not None else 0
    episode = item.episode if item.episode is not None else 0
    end = item.episode_end if item.episode_end is not None and item.episode_end > episode else None
    if fmt == "long":
        eps = f"Episodes {episode}-{end}" if end is not None else f"Episode {episode}"
        if item.season is None:
            return eps
        return f"Season {season} {eps}"
    if fmt == "padded":
        return f"S{season:02d}E{episode:02d}" + (f"-{end:02d}" if end is not None else "")
    return f"S{season}E{episode}" + (f"-{end}" if end is not None else "")


def format_runtime(minutes: Optional[int], compact: bool = False) -> str:
    if not minutes or minutes <= 0:
        return ""
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if compact:
        return f"{hours}h{mins:02d}" if mins else f"{hours}h"
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def format_time(dt: datetime, time_format: str, compact: bool = False) -> str:
    if time_format == "24h":
        return dt.strftime("%H:%M")
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    if dt.minute == 0 or compact:
        return f"{hour}{suffix}" if not compact else f"{hour}{suffix[0]}"
    return f"{hour}:{dt.minute:02d}{suffix}"


def format_when(item: UpcomingItem, now: datetime, tz, date_format: str = "relative",
                time_format: str = "12h", level: int = 0) -> str:
    """The item's date (and time, when known) for the panel.

    ``level`` asks for progressively shorter text: 0 full, 1 abbreviated,
    2 without the time.
    """
    day = item.local_date(tz)
    today = now.astimezone(tz).date() if tz else now.date()
    if date_format == "numeric":
        day_text = f"{day.month}/{day.day}"
    elif date_format == "short":
        day_text = f"{day.strftime('%b')} {day.day}"
    else:
        delta = (day - today).days
        if delta == 0:
            day_text = "Today"
        elif delta == 1:
            day_text = "Tmrw" if level >= 1 else "Tomorrow"
        elif delta == -1:
            day_text = "Yesterday" if level == 0 else "Yday"
        elif 1 < delta < 7:
            day_text = day.strftime("%a")
        else:
            day_text = f"{day.strftime('%b')} {day.day}"
    if item.has_time and level < 2:
        local = item.when.astimezone(tz) if tz else item.when
        return f"{day_text} {format_time(local, time_format, compact=level >= 1)}"
    return day_text


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class UpcomingRenderer:
    """Draws cards and messages. ``font_loader(name, size)`` returns a PIL font."""

    LINE_GAP = 1
    MARQUEE_GAP = 16
    MARQUEE_PAUSE = 1.5      # seconds a line holds before it starts to move
    MARQUEE_SPEED = 18       # pixels per second

    def __init__(self, settings: RenderSettings, images: ImageStore,
                 font_loader: Callable[[str, int], Any],
                 font_overrides: Optional[Dict[str, Tuple[Optional[str], int]]] = None):
        self.settings = settings
        self.images = images
        self._font_loader = font_loader
        self._overrides = font_overrides or {}
        self._fonts: Dict[Tuple[str, str], Any] = {}
        self._metrics: Dict[int, Tuple[int, int]] = {}
        self._measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        # Seconds the slowest scrolling line of the last card needs for one
        # full pass (pause + one loop); 0 when nothing on it scrolls.
        self.last_marquee_seconds = 0.0

    # -- fonts / measuring ------------------------------------------------

    def font(self, element: str, tier: str):
        key = (element, tier)
        if key not in self._fonts:
            name, size = TIER_FONTS[tier][element]
            o_name, o_size = self._overrides.get(element, (None, 0))
            if o_name:
                name = o_name
                # A chosen face with "auto" size: keep the tier's size for the
                # same face, else let the loader pick (bdf native, ttf grid).
                size = o_size or (size if o_name == TIER_FONTS[tier][element][0] else 0)
            elif o_size:
                size = o_size
            self._fonts[key] = self._font_loader(name, size)
        return self._fonts[key]

    def text_width(self, text: str, font) -> int:
        if not text:
            return 0
        try:
            return int(round(float(self._measure.textlength(text, font=font))))
        except Exception:  # noqa: BLE001 -- bitmap default font
            box = self._measure.textbbox((0, 0), text, font=font)
            return box[2] - box[0]

    def metrics(self, font) -> Tuple[int, int]:
        """(top offset, line height) for a font, measured on 'Ay'."""
        key = id(font)
        if key not in self._metrics:
            try:
                box = self._measure.textbbox((0, 0), "Ay", font=font)
                self._metrics[key] = (box[1], max(1, box[3] - box[1]))
            except Exception:  # noqa: BLE001
                self._metrics[key] = (0, 8)
        return self._metrics[key]

    def fit_text(self, text: str, font, max_width: int) -> str:
        """``text`` truncated with an ellipsis to fit ``max_width``."""
        if self.text_width(text, font) <= max_width:
            return text
        if self.text_width(ELLIPSIS, font) > max_width:
            return ""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.text_width(text[:mid].rstrip() + ELLIPSIS, font) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + ELLIPSIS

    def _fit_keeping(self, line: "_Line", font, max_width: int) -> str:
        """Truncate ``line`` but never into its first ``keep`` characters:
        "S1E8 Low Tide" becomes "S1E8 Lo..." or just "S1E8", not "S1E...".
        """
        if not line.keep or self.text_width(line.text, font) <= max_width:
            return self.fit_text(line.text, font, max_width)
        head, rest = line.text[:line.keep], line.text[line.keep:]
        if self.text_width(head, font) > max_width:
            # Even the number alone is too wide: cut it rather than clip it.
            return self.fit_text(line.text, font, max_width)
        room = max_width - self.text_width(head, font)
        tail = self.fit_text(rest, font, room) if room > 0 else ""
        # A lone "..." after the number says nothing; drop it.
        return head + tail if tail.strip() not in ("", ELLIPSIS.strip()) else head

    def wrap(self, text: str, font, max_width: int, max_lines: int) -> List[str]:
        """Greedy word wrap into at most ``max_lines``; the last line gets an
        ellipsis when text is left over."""
        if max_lines <= 0 or not text:
            return []
        words = text.split()
        lines: List[str] = []
        current = ""
        i = 0
        while i < len(words):
            word = words[i]
            candidate = f"{current} {word}" if current else word
            if self.text_width(candidate, font) <= max_width:
                current = candidate
                i += 1
                continue
            if not current:  # a single word wider than the line
                current = self.fit_text(word, font, max_width)
                i += 1
            lines.append(current)
            current = ""
            if len(lines) == max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
            current = ""
        if i < len(words) or current:
            rest = " ".join(([lines[-1]] if lines else []) + words[i:])
            lines[-1] = self.fit_text(rest, font, max_width)
        return [line for line in lines if line]

    # -- layout -----------------------------------------------------------

    @staticmethod
    def poster_box_width(height: int) -> int:
        """Width allowed for a side poster. Posters are 2:3 (TVDB) to 0.68
        (TMDB); a box a little wider than 2:3 lets either fill the full panel
        height instead of being width-limited a row or two short."""
        return int(round(height * 0.7)) + 1

    @staticmethod
    def poster_fits(width: int, height: int) -> bool:
        """Whether a side poster (2:3 at panel height) still leaves a usable
        text column. On a square 64x64 panel it would leave ~20 px."""
        text_w = width - int(round(height * 2 / 3)) - 3
        # ~9 characters of a 6-px font; 64x32 would leave 40 px (6 chars).
        return text_w >= max(54, int(width * 0.45))

    def _image_plan(self, item: UpcomingItem, width: int, height: int):
        """(placement, url, trim): placement is 'top', 'side' or None."""
        pref = self.settings.image_type
        logo = item.images.get("logo") if self.images.has(item.images.get("logo")) else None
        poster = item.images.get("poster") if self.images.has(item.images.get("poster")) else None
        if not self.poster_fits(width, height):
            poster = None
        tall = height >= 56
        if pref == "none":
            return None, None, False
        if pref == "poster":
            if poster:
                return "side", poster, False
            if logo:
                return ("top" if tall else "side"), logo, True
            return None, None, False
        if pref == "logo":
            if logo:
                return ("top" if tall else "side"), logo, True
            if poster:
                return "side", poster, False
            return None, None, False
        # auto: a logo reads best across the top of a tall panel; on a short
        # one a poster is taller and more recognisable than a squashed logo.
        if tall and logo:
            return "top", logo, True
        if poster:
            return "side", poster, False
        if logo:
            return "side", logo, True
        return None, None, False

    def _num_line(self, item: UpcomingItem, font, width: int, separate_name: bool) -> str:
        if item.kind == "movie":
            label = item.release_label
            if item.year and not label:
                label = str(item.year)
            return label
        number = format_episode_number(item, self.settings.episode_format)
        if self.settings.episode_format == "padded" and number and self.text_width(number, font) > width:
            number = format_episode_number(item, "compact")
        name = item.episode_title if self.settings.show_episode_title else ""
        if self.settings.episode_format == "long" and number:
            joined = f"{number} {name}".strip() if not separate_name else number
            if self.text_width(joined, font) > width:
                number = format_episode_number(item, "compact")
        if separate_name or not name:
            return number
        return f"{number} {name}".strip()

    def _date_line(self, item: UpcomingItem, now: datetime, tz, font, width: int) -> _Line:
        s = self.settings
        runtime = format_runtime(item.runtime_min) if s.show_runtime else ""
        color = None
        today = now.astimezone(tz).date() if tz else now.date()
        if s.highlight_today and item.local_date(tz) == today:
            color = s.today_color
        for level in range(3):
            when = format_when(item, now, tz, s.date_format, s.time_format, level) if s.show_date else ""
            for rt in ((runtime, format_runtime(item.runtime_min, compact=True), "") if runtime else ("",)):
                gap = self._gap(font) if when and rt else 0
                total = self.text_width(when, font) + gap + self.text_width(rt, font)
                if total <= width:
                    return _Line(when, "date", right=rt, color=color)
        when = format_when(item, now, tz, s.date_format, s.time_format, 2) if s.show_date else ""
        return _Line(self.fit_text(when, font, width), "date", color=color)

    def _build_lines(self, item: UpcomingItem, tier: str, width: int, height: int,
                     now: datetime, tz, show_title: bool, measure_width: Optional[int] = None):
        """Lines that fit ``height``, highest priority first, and whether any
        single line overflowed ``width`` (marquee candidate).

        ``measure_width`` (strip cards) is the cap used for wrapping; lines
        are not truncated against it until the final width is known.
        """
        s = self.settings
        f_title, f_ep, f_date, f_desc = (self.font(e, tier) for e in ELEMENTS)
        h_title, h_ep, h_date, h_desc = (self.metrics(f)[1] for f in (f_title, f_ep, f_date, f_desc))
        gap = self.LINE_GAP

        def total(heights):
            return sum(heights) + gap * max(0, len(heights) - 1)

        name = item.episode_title if (item.kind == "episode" and s.show_episode_title) else ""
        title_line = _Line(item.title, "title") if show_title else None
        date_line = self._date_line(item, now, tz, f_date, width) if (s.show_date or s.show_runtime) else None
        if date_line and not date_line.text and not date_line.right:
            date_line = None

        variants = []
        if name:
            variants.append(True)   # episode name on its own line
        variants.append(False)
        chosen: List[_Line] = []
        for separate in variants:
            lines: List[_Line] = []
            heights: List[int] = []
            if title_line:
                lines.append(title_line)
                heights.append(h_title)
            num = self._num_line(item, f_ep, width, separate)
            if num:
                number = format_episode_number(item, "compact") if item.kind == "episode" else ""
                keep = len(number) if number and num.startswith(number) else 0
                if not keep and item.kind == "episode":
                    full = format_episode_number(item, self.settings.episode_format)
                    keep = len(full) if full and num.startswith(full) else 0
                lines.append(_Line(num, "episode", keep=keep))
                heights.append(h_ep)
            if separate:
                lines.append(_Line(name, "episode"))
                heights.append(h_ep)
            if date_line:
                lines.append(date_line)
                heights.append(h_date)
            if separate and total(heights) > height:
                continue
            # Drop lowest-priority lines until the essentials fit.
            while lines and total(heights) > height:
                # keep title and episode number; drop date, then the rest
                drop = len(lines) - 1
                lines.pop(drop)
                heights.pop(drop)
            chosen = lines
            used = total(heights)
            break
        else:
            used = 0

        # A description in a column under ~12 characters wraps a word per
        # line ("A / cartogr... / discove..."); leave it out there.
        desc_fits = width >= self.text_width("M" * 12, f_desc)
        if s.show_description and item.overview and desc_fits:
            blurb = short_description(item.overview, s.description_max_chars)
            room = height - used - (gap if chosen else 0)
            max_lines = max(0, (room + gap) // (h_desc + gap))
            wrap_width = measure_width or width
            for text in self.wrap(blurb, f_desc, wrap_width, max_lines):
                chosen.append(_Line(text, "description"))
        return chosen

    def _line_font(self, line: _Line, tier: str):
        return self.font(line.element, tier)

    def _gap(self, font) -> int:
        """Space between the date and the runtime: at least a character wide,
        since a space is only 1-2 px in the small bitmap fonts."""
        return max(self.text_width("  ", font), self.text_width("0", font) + 2)

    def _line_natural_width(self, line: _Line, tier: str) -> int:
        font = self._line_font(line, tier)
        width = self.text_width(line.text, font)
        if line.right:
            width += self._gap(font) + self.text_width(line.right, font)
        return width

    # -- drawing ----------------------------------------------------------

    def _draw_lines(self, canvas: Image.Image, lines: List[_Line], tier: str,
                    box: Tuple[int, int, int, int], marquee_t: Optional[float],
                    center_x: bool = False) -> bool:
        """Draw ``lines`` vertically centred in ``box``; returns True when a
        line overflowed and is being marqueed (so the caller keeps redrawing)."""
        x0, y0, bw, bh = box
        if bw <= 0 or bh <= 0 or not lines:
            return False
        heights = [self.metrics(self._line_font(l, tier))[1] for l in lines]
        block = sum(heights) + self.LINE_GAP * (len(lines) - 1)
        y = y0 + max(0, (bh - block) // 2)
        block_w = bw  # only used when date + runtime overflow the box
        moving = False
        for line, lh in zip(lines, heights):
            if y + lh > y0 + bh:
                break
            font = self._line_font(line, tier)
            top, _ = self.metrics(font)
            color = line.color or self.settings.colors.get(line.element, (255, 255, 255))
            strip = Image.new("RGB", (bw, lh), self.settings.background_color)
            draw = ImageDraw.Draw(strip)
            draw.fontmode = "1"
            right_w = 0
            if line.right:
                # "Today 10PM  52m" as one unit (centred under a logo), so the
                # runtime sits in the same place on every card.
                left_w = self.text_width(line.text, font)
                both = left_w + self._gap(font) + self.text_width(line.right, font)
                if both <= bw:
                    lx = (bw - both) // 2 if center_x else 0
                    draw.text((lx, -top), line.text, font=font, fill=color)
                    draw.text((lx + both - self.text_width(line.right, font), -top), line.right,
                              font=font, fill=self.settings.colors.get("date", color))
                    canvas.paste(strip, (x0, y))
                    y += lh + self.LINE_GAP
                    continue
            if line.right:
                right_w = self.text_width(line.right, font)
                draw.text((block_w - right_w, -top), line.right, font=font,
                          fill=self.settings.colors.get("date", color))
                right_w += self._gap(font)
            avail = (block_w if line.right else bw) - right_w
            text_w = self.text_width(line.text, font)
            if text_w <= avail:
                tx = (avail - text_w) // 2 if center_x and not line.right else 0
                draw.text((tx, -top), line.text, font=font, fill=color)
            elif marquee_t is not None and line.element in ("title", "episode"):
                period = text_w + self.MARQUEE_GAP
                offset = int(max(0.0, marquee_t - self.MARQUEE_PAUSE) * self.MARQUEE_SPEED) % period
                self.last_marquee_seconds = max(self.last_marquee_seconds,
                                                self.MARQUEE_PAUSE + period / self.MARQUEE_SPEED)
                draw.text((-offset, -top), line.text, font=font, fill=color)
                draw.text((period - offset, -top), line.text, font=font, fill=color)
                moving = True
            else:
                draw.text((0, -top), self._fit_keeping(line, font, avail), font=font, fill=color)
            canvas.paste(strip, (x0, y))
            y += lh + self.LINE_GAP
        return moving

    def _paste_image(self, canvas: Image.Image, img: Image.Image, x: int, y: int) -> None:
        bg = Image.new("RGBA", img.size, self.settings.background_color + (255,))
        bg.alpha_composite(img)
        canvas.paste(bg.convert("RGB"), (x, y))

    def render_card(self, item: UpcomingItem, width: int, height: int, now: datetime, tz,
                    strip: bool = False, marquee_t: Optional[float] = None,
                    tier: Optional[str] = None) -> Tuple[Image.Image, bool]:
        """Draw one item. Returns (image, moving).

        ``strip`` sizes the card to its content (scroll / Vegas); otherwise the
        card is exactly ``width`` x ``height``. ``tier`` defaults to the one the
        panel size implies; strip cards pass the panel's own.
        """
        tier = tier or size_tier(width, height)
        self.last_marquee_seconds = 0.0
        # A strip card grows to fit its text, so a poster always has room there.
        plan_w = max(width, self.settings.strip_max_text_width) if strip else width
        placement, url, trim = self._image_plan(item, plan_w, height)
        margin = 1
        img = None
        img_w = img_h = 0
        text_x, text_y = margin, 0
        text_h = height
        if trim:
            # A logo: brighten a dim one, and use the poster (or the text
            # title) instead when it is still unreadable at this size.
            if placement == "top":
                logo_h = max(10, min(height // 2, int(round(height * 0.32))))
                box = (width - 2 * margin, logo_h)
            else:
                box = (max(2, min(int(width * 0.4), height * 3)), height)
            img = self.images.fitted(url, box, trim=True, brighten=True)
            if not self.images.readable(img):
                poster = item.images.get("poster")
                img, trim = None, False
                usable = self.images.has(poster) and self.poster_fits(plan_w, height)
                placement, url = ("side", poster) if usable else (None, None)
        if placement == "side":
            if not trim:
                img = self.images.fitted(url, (max(2, self.poster_box_width(height)), height))
            if img is not None:
                img_w, img_h = img.size
                text_x = img_w + 2
        elif placement == "top":
            if img is not None:
                img_w, img_h = img.size
                text_y = img_h + 2
                text_h = height - text_y
        if img is None:
            placement = None
        show_title = placement is None or not trim

        if strip:
            # A strip card may be wider than a small panel -- it scrolls --
            # so a 64-wide panel still gets readable titles.
            cap = min(self.settings.strip_max_text_width, max(width, 120))
            lines = self._build_lines(item, tier, cap, text_h, now, tz, show_title,
                                      measure_width=cap)
            natural = max([self._line_natural_width(l, tier) for l in lines] or [0])
            text_w = min(cap, natural)
            if placement == "top":
                card_w = max(img_w, text_w) + 2 * margin
                text_x = margin
            else:
                card_w = text_x + text_w + margin
            card_w = max(card_w, 8)
        else:
            card_w = width
            text_w = width - text_x - margin
            lines = self._build_lines(item, tier, text_w, text_h, now, tz, show_title)

        canvas = Image.new("RGB", (card_w, height), self.settings.background_color)
        if placement == "top" and img is not None:
            # Centre logo + text as one group, not the text alone under a
            # logo pinned to the top edge (a gap opens on tall panels).
            block = sum(self.metrics(self._line_font(l, tier))[1] for l in lines) \
                + self.LINE_GAP * max(0, len(lines) - 1)
            group = img_h + (2 + block if lines else 0)
            top_y = max(0, (height - group) // 2)
            self._paste_image(canvas, img, (card_w - img_w) // 2, top_y)
            text_y = top_y + img_h + 2
            text_h = min(block, height - text_y)
        elif img is not None:
            self._paste_image(canvas, img, 0, (height - img_h) // 2)
        if placement == "top":
            # Centre the text block under a centred logo when there is spare room.
            moving = self._draw_lines(canvas, lines, tier, (text_x, text_y, card_w - text_x - margin, text_h),
                                      marquee_t, center_x=True)
        else:
            moving = self._draw_lines(canvas, lines, tier, (text_x, text_y, card_w - text_x - margin, text_h),
                                      marquee_t)
        return canvas, moving

    def marquee_seconds(self, item: UpcomingItem, width: int, height: int, now: datetime, tz) -> float:
        """How long a switch-mode card needs for its scrolling lines to make
        one full pass; 0 when everything fits."""
        self.render_card(item, width, height, now, tz, marquee_t=0.0)
        return self.last_marquee_seconds

    def render_separator(self, height: int, gap: int = 6) -> Image.Image:
        """A thin accent bar between strip cards."""
        width = gap * 2 + 1
        img = Image.new("RGB", (width, height), self.settings.background_color)
        draw = ImageDraw.Draw(img)
        inset = max(2, height // 6)
        draw.line([(gap, inset), (gap, height - 1 - inset)], fill=self.settings.accent_color)
        return img

    def render_strip(self, items: List[UpcomingItem], width: int, height: int,
                     now: datetime, tz, header: Optional[str] = None) -> Image.Image:
        """All items side by side, separated, for ScrollHelper."""
        tier = size_tier(width, height)
        pieces: List[Image.Image] = []
        if header:
            pieces.append(self.render_header(header, height, tier))
        for item in items:
            if pieces:
                pieces.append(self.render_separator(height))
            card, _ = self.render_card(item, width, height, now, tz, strip=True, tier=tier)
            pieces.append(card)
        total = sum(p.width for p in pieces) or 1
        strip = Image.new("RGB", (total, height), self.settings.background_color)
        x = 0
        for piece in pieces:
            strip.paste(piece, (x, 0))
            x += piece.width
        return strip

    def render_header(self, text: str, height: int, tier: str) -> Image.Image:
        font = self.font("title", tier)
        top, lh = self.metrics(font)
        w = self.text_width(text, font) + 4
        img = Image.new("RGB", (max(8, w), height), self.settings.background_color)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"
        draw.text((2, (height - lh) // 2 - top), text, font=font, fill=self.settings.accent_color)
        return img

    def render_message(self, width: int, height: int, lines: List[str],
                       color: Tuple[int, int, int]) -> Image.Image:
        """A centred one-to-three line status message."""
        tier = size_tier(width, height)
        canvas = Image.new("RGB", (width, height), self.settings.background_color)
        draw = ImageDraw.Draw(canvas)
        draw.fontmode = "1"
        font = self.font("episode", tier)
        top, lh = self.metrics(font)
        fitted: List[str] = []
        for text in lines:
            fitted.extend(self.wrap(text, font, width - 2, 2))
        max_lines = max(1, (height + self.LINE_GAP) // (lh + self.LINE_GAP))
        fitted = fitted[:max_lines]
        block = len(fitted) * lh + self.LINE_GAP * (len(fitted) - 1)
        y = max(0, (height - block) // 2)
        for text in fitted:
            w = self.text_width(text, font)
            draw.text((max(0, (width - w) // 2), y - top), text, font=font, fill=color)
            y += lh + self.LINE_GAP
        return canvas
