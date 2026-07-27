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
from PIL import Image, ImageDraw, ImageFont, ImageSequence

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
DELIVERED_COLOR = (120, 185, 120)

CARRIER_NAMES = {
    "usps": "USPS", "ups": "UPS", "fedex": "FedEx", "dhl": "DHL",
    "amazon": "Amazon", "walmart": "Walmart", "deutschepost": "Deutsche Post",
    "ontrac": "OnTrac", "lasership": "LaserShip", "dpd": "DPD", "gls": "GLS",
    "hermes": "Hermes", "royalmail": "Royal Mail", "canadapost": "Canada Post",
    "auspost": "AusPost", "other": "Package",
}

# Per-carrier badge: (background, foreground, abbreviation). Drawn (not shipped
# as trademarked bitmaps); a bundled assets/carrier_logos/<slug>.png overrides.
CARRIER_STYLE = {
    "usps": ((0, 40, 104), (255, 255, 255), "USPS"),
    "ups": ((52, 34, 20), (255, 183, 0), "UPS"),
    "fedex": ((77, 32, 127), (255, 102, 0), "FDX"),
    "dhl": ((255, 204, 0), (211, 0, 0), "DHL"),
    "amazon": ((35, 47, 62), (255, 153, 0), "amzn"),
    "walmart": ((0, 113, 206), (255, 194, 32), "WMT"),
    "deutschepost": ((255, 204, 0), (211, 0, 0), "DP"),
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
        self.show_delivery_images = bool(config.get("show_delivery_images", True))
        self.show_delivered = bool(config.get("show_delivered", True))
        self.show_dashboard = bool(config.get("show_dashboard", True))
        self.stale_after = max(60, int(config.get("stale_after_minutes", 60)) * 60)
        self.image_frame_seconds = max(0.2, float(config.get("image_frame_seconds", 1.5)))
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
        # Fetched image frames keyed by slot: 'usps_mail' for the Informed
        # Delivery image (multi-frame GIF), and a carrier slug for a delivery
        # image. Value is a list of fitted frames (one for static images).
        self._images: Dict[str, List[Image.Image]] = {}
        self._image_sig: Dict[str, Tuple[str, Tuple[int, int]]] = {}
        self._error: Optional[str] = None
        self._last_fetch = 0.0
        self._last_success = 0.0     # wall-clock of the last good fetch
        self._stale = False          # last fetch failed; showing cached data
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

    def _image_box(self) -> Tuple[int, int]:
        """Image area for an image card: full width, leaving a row for the label."""
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
            snap = self.provider.fetch()
            self._snapshot = snap
            self._last_success = now
            self._error = None
            self._stale = False
            self._fetch_images(snap)
            self._cards = self._build_cards(snap)
        except (AuthError, ProviderError) as exc:
            self._handle_fetch_error(str(exc), now)
        except Exception:  # pragma: no cover - defensive
            self.logger.exception("Package provider failed")
            self._handle_fetch_error("Provider error", now)
        if self.current_index >= len(self._cards):
            self.current_index = 0

    def _handle_fetch_error(self, message: str, now: float) -> None:
        """Ride out a transient failure on the last-good snapshot (flagged
        stale) rather than blanking; only surface the error card once the
        cached data is gone or too old to trust."""
        grace = max(self.stale_after, 2 * self.update_interval)
        if self._cards and self._snapshot is not None and (now - self._last_success) < grace:
            self._stale = True
            self._error = None
            self.logger.warning("Provider error (%s); showing cached data", message)
        else:
            self._error = message
            self._snapshot = None
            self._cards = []
            self._images.clear()
            self._image_sig.clear()

    def _data_age_seconds(self) -> float:
        """Seconds since the data we're showing was last confirmed fresh:
        HA's own last-scan time when available, else our last successful fetch."""
        if self._snapshot and self._snapshot.updated:
            return max(0.0, time.time() - self._snapshot.updated.timestamp())
        if self._last_success:
            return max(0.0, time.time() - self._last_success)
        return 0.0

    @staticmethod
    def _age_label(seconds: float) -> str:
        mins = int(seconds // 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"

    def _wanted_images(self, snap: Snapshot) -> Dict[str, str]:
        """Which images to show this refresh: the USPS Informed Delivery image
        when there is mail, and a carrier's scanned delivery image when that
        carrier is out for delivery today (otherwise the camera is a 'NO
        DELIVERIES' placeholder)."""
        wanted: Dict[str, str] = {}
        if self.show_usps_mail and (snap.usps_mail_count or 0) > 0 and snap.usps_image_url:
            wanted["usps_mail"] = snap.usps_image_url
        if self.show_delivery_images:
            for cs in snap.carriers:
                if cs.delivering_today > 0 and cs.carrier in snap.carrier_images:
                    wanted[cs.carrier] = snap.carrier_images[cs.carrier]
        return wanted

    def _fetch_images(self, snap: Optional[Snapshot]) -> None:
        """Fetch the needed images in update() (never in display())."""
        wanted = self._wanted_images(snap) if snap else {}
        box = self._image_box()
        for slot in list(self._images):            # drop images no longer wanted
            if slot not in wanted:
                self._images.pop(slot, None)
                self._image_sig.pop(slot, None)
        for slot, url in wanted.items():
            sig = (url, box)
            if self._image_sig.get(slot) != sig or slot not in self._images:
                frames = self._fetch_frames(url, box)
                if frames:
                    self._images[slot] = frames
                    self._image_sig[slot] = sig
                else:
                    self._images.pop(slot, None)

    def _image_headers(self) -> Dict[str, str]:
        if self.provider_name == "homeassistant":
            token = (self.config.get("ha_token") or "").strip()
            if token:
                return {"Authorization": f"Bearer {token}"}
        return {}

    def _fetch_frames(self, url: str, box: Tuple[int, int]) -> List[Image.Image]:
        """Fetch an image and return every frame fitted to `box`. The USPS
        Informed Delivery image is an animated GIF cycling through each scanned
        mail piece; a static image yields a single frame. Capped to keep memory
        and the animation length sane."""
        try:
            resp = requests.get(url, headers=self._image_headers(), timeout=8)
            resp.raise_for_status()
            src = Image.open(BytesIO(resp.content))
            frames: List[Image.Image] = []
            for frame in ImageSequence.Iterator(src):
                rgb = frame.convert("RGB")
                rgb.thumbnail(box, Image.Resampling.LANCZOS)
                frames.append(rgb)
                if len(frames) >= 24:
                    break
            return frames
        except Exception as exc:  # pragma: no cover - network/decoding
            self.logger.warning("Image fetch failed: %s", type(exc).__name__)
            return []

    def _build_cards(self, snap: Snapshot) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        delivered = snap.total_delivered_today if self.show_delivered else 0
        carriers = sorted(snap.carriers,
                          key=lambda c: (-c.delivering_today, -c.in_transit, c.carrier))
        # Lead overview when there's more than one carrier in play: an
        # all-carriers dashboard, or the compact text summary.
        if len(carriers) > 1 and (snap.total_in_transit or snap.total_delivering_today):
            lead = {
                "total": snap.total_in_transit + snap.total_delivering_today,
                "today": snap.total_delivering_today,
                "delivered": delivered,
                "grid": [(c.carrier, c.delivering_today, c.in_transit) for c in carriers],
            }
            lead["type"] = "dashboard" if self.show_dashboard else "summary"
            cards.append(lead)
        # USPS Informed Delivery mail image, when there is mail today.
        if "usps_mail" in self._images:
            cards.append({"type": "usps_image", "mail": snap.usps_mail_count or 0})
        # Carrier cards: arriving-today first, then most-in-transit. When a
        # carrier is out for delivery today and we have its scanned image, show
        # the image card instead of the plain count card.
        for cs in carriers:
            common = {
                "carrier": cs.carrier,
                "today": cs.delivering_today,
                "transit": cs.in_transit,
                "delivered": cs.delivered_today if self.show_delivered else 0,
                "mail": snap.usps_mail_count if cs.carrier == "usps" else None,
            }
            if cs.delivering_today > 0 and cs.carrier in self._images:
                cards.append({"type": "carrier_image", **common})
            else:
                cards.append({"type": "carrier", **common})
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
            summary = (self._snapshot.summary_text if self._snapshot else "") or \
                "No incoming packages"
            self._render_static(summary, IDLE_COLOR, force_clear)
            return

        self._last_static_signature = None
        now = time.time()
        if self.current_index >= len(self._cards):
            self.current_index = 0
        if now - self.last_rotation >= self._card_dwell(self._cards[self.current_index]):
            self.current_index = (self.current_index + 1) % len(self._cards)
            self.last_rotation = now
            self._reset_scroll()

        if force_clear:
            self.display_manager.clear()
        image = self._render_card(self._cards[self.current_index])
        self.display_manager.image = image
        self.display_manager.update_display()

    def _image_slot(self, card: Dict[str, Any]) -> Optional[str]:
        if card.get("type") == "usps_image":
            return "usps_mail"
        if card.get("type") == "carrier_image":
            return card["carrier"]
        return None

    def _card_dwell(self, card: Dict[str, Any]) -> float:
        """Seconds to hold a card. Animated image cards stay long enough to
        play through all their frames once."""
        slot = self._image_slot(card)
        frames = len(self._images.get(slot, [])) if slot else 1
        if frames > 1:
            return max(self.rotation_interval, frames * self.image_frame_seconds)
        return self.rotation_interval

    def get_display_duration(self) -> float:
        total = sum(self._card_dwell(c) for c in self._cards) if self._cards else self.rotation_interval
        return max(6.0, min(90.0, total))

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
        lines = self._wrap_two(message, small, width - 2)
        lh = self._font_height(small)
        total = lh * len(lines) + (len(lines) - 1)
        y = max(0, (height - total) // 2)
        for line in lines:
            draw.text(((width - self._text_width(line, small)) // 2, y),
                      line, font=small, fill=color)
            y += lh + 1
        self.display_manager.image = image
        self.display_manager.update_display()

    def _wrap_two(self, text: str, font, max_w: int) -> List[str]:
        """Greedy word-wrap into at most two lines (second is ellipsized if the
        text still doesn't fit)."""
        if self._text_width(text, font) <= max_w:
            return [text]
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if not cur or self._text_width(trial, font) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= 1:
            return lines or [""]
        return [lines[0], self._truncate(" ".join(lines[1:]), font, max_w)]

    def _render_card(self, card: Dict[str, Any]) -> Image.Image:
        width, height = self._dims()
        big, small = self._tier_fonts()
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        tall = height >= 46

        if card["type"] in ("usps_image", "carrier_image"):
            frames = self._images.get(self._image_slot(card), [])
            if frames:
                # Animate multi-frame images (the USPS GIF cycles through each
                # scanned mail piece); pick this instant's frame by wall clock.
                idx = int(time.time() / self.image_frame_seconds) % len(frames)
                frame = frames[idx]
                image.paste(frame, ((width - frame.width) // 2, 0))
            if card["type"] == "usps_image":
                label, color = f"USPS  {card['mail']} mail", self.base_color
            else:
                name = CARRIER_NAMES.get(card["carrier"], card["carrier"].title())
                label = f"{name}  {card['today']} today"
                color = self.accent_color if self.highlight_today else self.base_color
            lh = self._font_height(small)
            lt = self._truncate(label, small, width - 2)
            draw.text(((width - self._text_width(lt, small)) // 2, height - lh),
                      lt, font=small, fill=color)
            self._draw_stale(draw, width)
            return image

        if card["type"] == "dashboard":
            self._render_dashboard(image, draw, card, width, height)
            return image

        if card["type"] == "summary":
            rows = [("INCOMING", small, MUTED_COLOR, None, True),
                    (str(card["total"]), big, self.base_color, None, True)]
            today, delivered = card["today"], card.get("delivered", 0)
            # One status row (keeps the card to 3 rows so the big count fits).
            if today > 0 and self.highlight_today:
                lbl = f"{today} today" if width < 160 else f"{today} arriving today"
                if delivered > 0 and width >= 160:
                    lbl += f"  {delivered} done"
                rows.append((lbl, small, self.accent_color, None, True))
            elif delivered > 0:
                rows.append((f"{delivered} delivered", small, DELIVERED_COLOR, None, True))
            self._place_rows(draw, rows, 2, width - 4, height)
            self._draw_freshness(draw, width, height)
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
        if tall and card.get("delivered", 0) > 0:
            rows.append((f"{card['delivered']} delivered", small, DELIVERED_COLOR, None, False))
        if today == 0 and transit == 0 and mail:  # USPS mail only
            rows = rows[:1] + [(f"{mail} mail", big if tall else small, self.base_color, None, False)]

        # Cap rows so the (possibly large) arriving-today line always fits:
        # 2 on short panels, 3 on tall.
        rows = rows[:2] if not tall else rows[:3]
        self._place_rows(draw, rows, tx, tw, height)
        self._draw_stale(draw, width)
        return image

    # ── dashboard + freshness ───────────────────────────────────────────────

    def _render_dashboard(self, image, draw, card, width, height) -> None:
        """All active carriers at a glance: a header line plus a grid of badge
        + count cells. On narrow panels (<128px) it falls back to the compact
        text summary so nothing is cramped."""
        if width < 128:
            rows = [(f"{card['total']} INCOMING", self._tier_fonts()[1], MUTED_COLOR, None, True)]
            if card["today"] > 0:
                rows.append((f"{card['today']} today", self._tier_fonts()[1],
                             self.accent_color, None, True))
            self._place_rows(draw, rows, 2, width - 4, height)
            self._draw_freshness(draw, width, height)
            return

        _, small = self._tier_fonts()
        fh = self._font_height(small)
        header = f"{card['total']} incoming"
        if card["today"] > 0:
            header += f"  ·  {card['today']} today"
        draw.text((2, 1), self._truncate(header, small, width - 4), font=small,
                  fill=self.base_color)

        grid = card.get("grid", [])
        top = fh + 3
        cell_h = height - top - 1
        badge = max(12, min(cell_h, 26))
        gap = 4
        x = 2
        for slug, today, transit in grid:
            count = today + transit
            cnt = str(count)
            cw = self._text_width(cnt, small)
            cell_w = badge + 2 + cw
            if x + cell_w > width:            # no more room on this single row
                break
            by = top + (cell_h - badge) // 2
            image.paste(self._carrier_badge(slug, badge), (x, by))
            color = self.accent_color if today > 0 else MUTED_COLOR
            draw.text((x + badge + 2, top + (cell_h - fh) // 2), cnt, font=small, fill=color)
            x += cell_w + gap
        self._draw_freshness(draw, width, height)

    def _draw_freshness(self, draw, width, height) -> None:
        """Small bottom-right 'Xm ago' when the data isn't fresh, in a warning
        tint if it is stale (last fetch failed / older than stale_after)."""
        age = self._data_age_seconds()
        if not self._stale and age <= 300:
            return
        _, small = self._tier_fonts()
        label = self._age_label(age)
        color = (230, 150, 60) if (self._stale or age > self.stale_after) else MUTED_COLOR
        tw = self._text_width(label, small)
        draw.text((width - tw - 1, height - self._font_height(small)),
                  label, font=small, fill=color)

    def _draw_stale(self, draw, width) -> None:
        """A small amber dot in the top-right corner while showing cached data."""
        if self._stale:
            draw.ellipse([width - 4, 1, width - 1, 4], fill=(230, 150, 60))

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
