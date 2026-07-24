"""
Incoming Packages plugin for LEDMatrix.

Shows a rotating set of cards for packages headed your way: one per active
carrier (with a badge, the count arriving today, and the count in transit), plus
a lead summary card. Packages arriving today are prioritized and drawn in an
accent color.

It does NOT use the Shop app (Shopify exposes no consumer API). Instead it reads
a normalized snapshot from a pluggable provider — by default the Home Assistant
"Mail and Packages" integration you already run: the email scanning happens
locally inside Home Assistant, and this plugin only ever holds an HA URL + token
and reads sensor states over the LAN. AfterShip and a built-in demo provider are
also available. See package_sources.py.

The renderer is fully size-adaptive: it reads the panel dimensions every frame,
picks a crisp bitmap font tier for the panel, and marquee-scrolls or truncates
text that would overflow, so it renders correctly from 64x32 up to 256x64+.

API Version: 1.0.0
"""

import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

from package_sources import (
    AuthError,
    ProviderError,
    Snapshot,
    make_provider,
)

ERROR_TEXT_COLOR = (255, 90, 90)
IDLE_COLOR = (140, 140, 140)
MUTED_COLOR = (150, 150, 150)

CARRIER_NAMES = {
    "usps": "USPS", "ups": "UPS", "fedex": "FedEx", "dhl": "DHL",
    "amazon": "Amazon", "ontrac": "OnTrac", "lasership": "LaserShip",
    "dpd": "DPD", "gls": "GLS", "hermes": "Hermes", "royalmail": "Royal Mail",
    "canadapost": "Canada Post", "auspost": "AusPost", "other": "Package",
}

# Per-carrier badge: (background, foreground, abbreviation). Drawn (not shipped
# as trademarked bitmaps); a bundled assets/carrier_logos/<slug>.png overrides.
CARRIER_STYLE = {
    "usps": ((0, 40, 104), (255, 255, 255), "USPS"),
    "ups": ((52, 34, 20), (255, 183, 0), "UPS"),
    "fedex": ((77, 32, 127), (255, 102, 0), "FDX"),
    "dhl": ((255, 204, 0), (211, 0, 0), "DHL"),
    "amazon": ((35, 47, 62), (255, 153, 0), "amzn"),
    "ontrac": ((0, 90, 70), (255, 255, 255), "OT"),
    "lasership": ((180, 30, 40), (255, 255, 255), "LS"),
    "dpd": ((70, 20, 90), (255, 255, 255), "DPD"),
    "gls": ((0, 60, 130), (255, 210, 0), "GLS"),
    "hermes": ((20, 60, 60), (255, 255, 255), "HMS"),
    "royalmail": ((200, 0, 30), (255, 210, 0), "RM"),
    "canadapost": ((200, 0, 30), (255, 255, 255), "CP"),
    "auspost": ((220, 40, 30), (255, 255, 255), "AP"),
    "other": ((45, 45, 45), (200, 200, 200), "PKG"),
}


class IncomingPackagesPlugin(BasePlugin):
    """Rotating incoming-package cards, provider-agnostic and size-adaptive."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.provider_name = (config.get("provider") or "homeassistant").strip().lower()
        self.update_interval = int(config.get("update_interval", 600))
        self.rotation_interval = float(config.get("rotation_interval", 6))
        self.max_cards = int(config.get("max_cards", 8))
        self.include_delivered = bool(config.get("include_delivered", False))
        self.show_carrier_logo = bool(config.get("show_carrier_logo", True))
        self.show_usps_mail = bool(config.get("show_usps_mail_image", True))
        self.highlight_today = bool(config.get("highlight_today", True))
        self.accent_color = self._parse_color(config.get("accent_color"), (0, 220, 120))

        self.scroll_enabled = bool(config.get("scroll_enabled", True))
        self.scroll_speed = max(1, int(config.get("scroll_speed", 5)))
        self.scroll_separator = config.get("scroll_separator", "   ")

        customization = config.get("customization", {})
        self.base_color = self._parse_color(
            customization.get("title_text", {}).get("text_color"), (255, 255, 255))

        self.provider = make_provider(self.provider_name, config, self.logger)

        # State
        self._snapshot: Optional[Snapshot] = None
        self._cards: List[Dict[str, Any]] = []
        self._usps_image: Optional[Image.Image] = None
        self._usps_image_key: Optional[Tuple[str, Tuple[int, int]]] = None
        self._error: Optional[str] = None
        self._last_fetch = 0.0
        self._has_fetched = False
        self.current_index = 0
        # Start the clock now so the first card shows for a full interval (and so
        # a frozen-clock harness render is deterministic on index 0).
        self.last_rotation = time.time()

        # Rendering scratch
        self._font_cache: Dict[Tuple[str, int], Any] = {}
        self._logo_cache: Dict[str, Optional[Image.Image]] = {}
        self._measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self._scroll_pos: Dict[str, int] = {"name": 0}
        self._scroll_tick: Dict[str, int] = {"name": 0}
        self._last_static_signature: Optional[str] = None

        self.logger.info("Incoming Packages initialized (provider: %s)", self.provider_name)

    # ── setup helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_color(value, default) -> Tuple[int, int, int]:
        if value is None:
            return tuple(default)
        try:
            parsed = tuple(int(c) for c in value)
            if len(parsed) == 3:
                return parsed
        except (ValueError, TypeError):
            pass
        return tuple(default)

    def _load_font(self, font_name: str, font_size: int):
        cache_key = (font_name, font_size)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]
        font = None
        rel = os.path.join("assets", "fonts", font_name)
        for candidate in (rel, os.path.join(os.getcwd(), rel),
                          str(Path(__file__).parent.parent.parent / rel)):
            if os.path.exists(candidate):
                try:
                    font = ImageFont.truetype(candidate, font_size)
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.warning("Could not load font %s: %s", candidate, exc)
        if font is None:
            font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font

    def _dims(self) -> Tuple[int, int]:
        width = getattr(self.display_manager, "width", None)
        height = getattr(self.display_manager, "height", None)
        if not width or not height:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
        return int(width), int(height)

    def _tier_fonts(self):
        """Pick (big, small) bitmap fonts sized to the panel — width-aware so
        text never overflows a narrow panel, taller on big ones."""
        w, h = self._dims()
        scale = min(h / 32.0, max(1.0, w / 128.0))
        if scale >= 1.75:
            big, small = ("10x20.bdf", 20), ("7x13.bdf", 13)
        elif scale >= 1.25:
            big, small = ("7x13.bdf", 13), ("5x8.bdf", 8)
        else:
            big, small = ("6x10.bdf", 10), ("4x6.bdf", 6)
        return self._load_font(*big), self._load_font(*small)

    def _text_width(self, text: str, font) -> int:
        try:
            return int(self._measure_draw.textlength(text, font=font))
        except Exception:
            bbox = self._measure_draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]

    def _font_height(self, font) -> int:
        try:
            bbox = self._measure_draw.textbbox((0, 0), "Ay", font=font)
            return max(1, bbox[3] - bbox[1])
        except Exception:
            return 8

    def _usps_image_box(self) -> Tuple[int, int]:
        """Image area for the USPS card: full width, leaving a row for the label."""
        w, h = self._dims()
        _, small = self._tier_fonts()
        return (max(1, w), max(1, h - self._font_height(small) - 1))

    # ── lifecycle ──────────────────────────────────────────────────────────

    def update(self) -> None:
        if not self.enabled:
            return
        now = time.time()
        if self._has_fetched and now - self._last_fetch < self.update_interval:
            return
        self._has_fetched = True
        self._last_fetch = now
        try:
            self._snapshot = self.provider.fetch()
            self._error = None
        except AuthError as exc:
            self._error = str(exc)
            self._snapshot = None
        except ProviderError as exc:
            self._error = str(exc)
            self._snapshot = None
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.exception("Package provider failed")
            self._error = "Provider error"
            self._snapshot = None
        self._maybe_fetch_usps_image(self._snapshot)
        self._cards = self._build_cards(self._snapshot) if self._snapshot else []
        if self.current_index >= len(self._cards):
            self.current_index = 0

    def _maybe_fetch_usps_image(self, snap: Optional[Snapshot]) -> None:
        """Fetch the USPS Informed Delivery image (only when there is mail).
        Done here in update(), never in display()."""
        want = bool(self.show_usps_mail and snap and snap.usps_image_url
                    and (snap.usps_mail_count or 0) > 0)
        if not want:
            self._usps_image = None
            self._usps_image_key = None
            return
        box = self._usps_image_box()
        key = (snap.usps_image_url, box)
        if key != self._usps_image_key:
            self._usps_image = self._fetch_image(snap.usps_image_url, box)
            self._usps_image_key = key

    def _image_headers(self) -> Dict[str, str]:
        if self.provider_name == "homeassistant":
            token = (self.config.get("ha_token") or "").strip()
            if token:
                return {"Authorization": f"Bearer {token}"}
        return {}

    def _fetch_image(self, url: str, box: Tuple[int, int]) -> Optional[Image.Image]:
        try:
            resp = requests.get(url, headers=self._image_headers(), timeout=8)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            img.seek(0)  # first frame of an animated GIF
            img = img.convert("RGB")
            img.thumbnail(box, Image.Resampling.LANCZOS)
            return img
        except Exception as exc:  # pragma: no cover - network/decoding
            self.logger.warning("USPS image fetch failed: %s", type(exc).__name__)
            return None

    def _build_cards(self, snap: Snapshot) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        # Lead summary when there's more than one carrier in play.
        if len(snap.carriers) > 1 and (snap.total_in_transit or snap.total_delivering_today):
            cards.append({"type": "summary",
                          "total": snap.total_in_transit + snap.total_delivering_today,
                          "today": snap.total_delivering_today})
        # USPS Informed Delivery mail image, when there is mail today.
        if self._usps_image is not None:
            cards.append({"type": "usps_image", "mail": snap.usps_mail_count or 0})
        # Carrier cards: arriving-today first, then most-in-transit.
        carriers = sorted(snap.carriers,
                          key=lambda c: (-c.delivering_today, -c.in_transit, c.carrier))
        for cs in carriers:
            cards.append({
                "type": "carrier",
                "carrier": cs.carrier,
                "today": cs.delivering_today,
                "transit": cs.in_transit,
                "mail": snap.usps_mail_count if cs.carrier == "usps" else None,
            })
        return cards[: self.max_cards]

    def display(self, force_clear: bool = False) -> None:
        if not self.enabled:
            return
        if not self._has_fetched:
            self.update()

        if self._error:
            self._render_static(self._error, ERROR_TEXT_COLOR, force_clear, hint=True)
            return
        if not self._cards:
            self._render_static("No incoming packages", IDLE_COLOR, force_clear)
            return

        self._last_static_signature = None
        now = time.time()
        if now - self.last_rotation >= self.rotation_interval:
            self.current_index = (self.current_index + 1) % len(self._cards)
            self.last_rotation = now
            self._reset_scroll()
        if self.current_index >= len(self._cards):
            self.current_index = 0

        if force_clear:
            self.display_manager.clear()
        image = self._render_card(self._cards[self.current_index])
        self.display_manager.image = image
        self.display_manager.update_display()

    def get_display_duration(self) -> float:
        n = max(1, len(self._cards))
        return max(6.0, min(60.0, n * self.rotation_interval))

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        if getattr(self.provider, "requires_token", False):
            self.logger.info("Incoming Packages: provider '%s' needs credentials; "
                             "panel shows a setup hint until they're set",
                             self.provider_name)
        return True

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        self.__init__(self.plugin_id, new_config, self.display_manager,
                      self.cache_manager, self.plugin_manager)

    # ── rendering ──────────────────────────────────────────────────────────

    def _reset_scroll(self) -> None:
        for field in self._scroll_pos:
            self._scroll_pos[field] = 0
            self._scroll_tick[field] = 0

    def _render_static(self, message: str, color, force_clear: bool,
                       hint: bool = False) -> None:
        width, height = self._dims()
        signature = f"{message}|{width}x{height}"
        if not force_clear and signature == self._last_static_signature:
            return
        self._last_static_signature = signature
        _, small = self._tier_fonts()
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        text = self._truncate(message, small, width - 2)
        draw.text(((width - self._text_width(text, small)) // 2,
                   (height - self._font_height(small)) // 2),
                  text, font=small, fill=color)
        self.display_manager.image = image
        self.display_manager.update_display()

    def _render_card(self, card: Dict[str, Any]) -> Image.Image:
        width, height = self._dims()
        big, small = self._tier_fonts()
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        tall = height >= 46

        if card["type"] == "usps_image":
            if self._usps_image is not None:
                iw, ih = self._usps_image.size
                image.paste(self._usps_image, ((width - iw) // 2, 0))
            label = f"USPS  {card['mail']} mail"
            lh = self._font_height(small)
            lt = self._truncate(label, small, width - 2)
            draw.text(((width - self._text_width(lt, small)) // 2, height - lh),
                      lt, font=small, fill=self.base_color)
            return image

        if card["type"] == "summary":
            rows = [("INCOMING", small, MUTED_COLOR, None, True),
                    (str(card["total"]), big, self.base_color, None, True)]
            if card["today"] > 0 and self.highlight_today:
                label = f"{card['today']} today" if width < 128 else f"{card['today']} arriving today"
                rows.append((self._fit(label, small, big, width - 4), small, self.accent_color, None, True))
            self._place_rows(draw, rows, 2, width - 4, height)
            return image

        # Carrier card
        slug = card["carrier"]
        tx = 2
        if self.show_carrier_logo:
            badge = min(height, max(16, int(width * 0.34)))
            img = self._carrier_badge(slug, badge)
            image.paste(img, (0, (height - badge) // 2))
            tx = badge + 3
        tw = width - tx - 1
        if tw <= 0:
            return image

        today, transit, mail = card["today"], card["transit"], card.get("mail")
        rows = [(CARRIER_NAMES.get(slug, slug.title()), small, self.base_color, "name", False)]
        if today > 0 and self.highlight_today:
            label = f"{today} today" if not tall else f"{today} arriving"
            rows.append((label, big if tall else small, self.accent_color, None, False))
        if transit > 0:
            rows.append((self._transit_label(transit, tall), small, MUTED_COLOR, None, False))
        if mail:
            rows.append((f"{mail} mail", small, MUTED_COLOR, None, False))
        if today == 0 and transit == 0 and mail:  # USPS mail only
            rows = rows[:1] + [(f"{mail} mail", big if tall else small, self.base_color, None, False)]

        if not tall:  # short panels: name + the single most important line
            rows = rows[:2]
        self._place_rows(draw, rows, tx, tw, height)
        return image

    def _transit_label(self, n: int, tall: bool) -> str:
        return f"{n} in transit" if tall else f"{n} transit"

    def _place_rows(self, draw, rows, x, tw, height) -> None:
        """Vertically center a stack of rows, marquee/clip each to width."""
        heights = [self._font_height(f) for (_, f, _, _, _) in rows]
        gap = 2 if height < 46 else 3
        total = sum(heights) + gap * (len(rows) - 1)
        y = max(1, (height - total) // 2)
        for (text, font, color, field, center), fh in zip(rows, heights, strict=True):
            shown = (self._marquee(text, font, tw, field) if field
                     else self._truncate(text, font, tw))
            tx = x + max(0, (tw - self._text_width(shown, font)) // 2) if center else x
            draw.text((tx, y), shown, font=font, fill=color)
            y += fh + gap

    def _carrier_badge(self, slug: str, size: int) -> Image.Image:
        override = self._carrier_logo_file(slug, size)
        if override is not None:
            return override
        bg, fg, abbrev = CARRIER_STYLE.get(slug, CARRIER_STYLE["other"])
        img = Image.new("RGB", (size, size), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        radius = max(2, size // 6)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=bg)
        # largest font whose abbrev fits the badge
        for name, px in (("6x10.bdf", 10), ("5x8.bdf", 8), ("4x6.bdf", 6)):
            font = self._load_font(name, px)
            tw = self._text_width(abbrev, font)
            if tw <= size - 4:
                th = self._font_height(font)
                draw.text(((size - tw) // 2, (size - th) // 2), abbrev, font=font, fill=fg)
                break
        return img

    def _carrier_logo_file(self, slug: str, size: int) -> Optional[Image.Image]:
        if slug in self._logo_cache:
            src = self._logo_cache[slug]
            return self._fit_square(src, size) if src is not None else None
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "carrier_logos", f"{slug}.png")
        src = None
        if os.path.exists(path):
            try:
                src = Image.open(path).convert("RGB")
            except Exception:  # pragma: no cover - defensive
                src = None
        self._logo_cache[slug] = src
        return self._fit_square(src, size) if src is not None else None

    @staticmethod
    def _fit_square(src: Image.Image, size: int) -> Image.Image:
        img = src.copy()
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), (0, 0, 0))
        canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
        return canvas

    # ── text fitting / marquee (adapted from jellyfin-now-playing) ──────────

    def _fit(self, text: str, small, big, max_w: int):
        """Return text unchanged (used where either font may render it)."""
        return text

    def _clip(self, text: str, font, max_width: int) -> str:
        if max_width <= 0 or not text:
            return ""
        if self._text_width(text, font) <= max_width:
            return text
        clipped = text
        while clipped and self._text_width(clipped, font) > max_width:
            clipped = clipped[:-1]
        return clipped

    def _truncate(self, text: str, font, max_width: int) -> str:
        if max_width <= 0 or not text:
            return ""
        if self._text_width(text, font) <= max_width:
            return text
        ell = "."
        clipped = self._clip(text, font, max_width - self._text_width(ell, font))
        return clipped + ell if clipped else self._clip(text, font, max_width)

    def _marquee(self, text: str, font, max_width: int, field: str) -> str:
        if max_width <= 0:
            return ""
        if not text or self._text_width(text, font) <= max_width:
            self._scroll_pos[field] = 0
            self._scroll_tick[field] = 0
            return text
        if not self.scroll_enabled:
            return self._truncate(text, font, max_width)
        full = text + self.scroll_separator
        pos = self._scroll_pos.get(field, 0) % len(full)
        rotated = full[pos:] + full[:pos]
        self._scroll_tick[field] = self._scroll_tick.get(field, 0) + 1
        if self._scroll_tick[field] >= self.scroll_speed:
            self._scroll_tick[field] = 0
            self._scroll_pos[field] = (pos + 1) % len(full)
        return self._clip(rotated, font, max_width)
