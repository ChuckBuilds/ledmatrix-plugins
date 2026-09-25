"""Player headshots and club crests for the Fantasy Blitz cards.

Headshots come from ESPN: a 600x436 PNG with a transparent background, which
is what an LED panel wants (Sleeper's own headshots are JPEGs on white, a
bright box on a black panel). Sleeper's player ids do not map to ESPN's
reliably -- Sleeper leaves ``espn_id`` empty for many current players -- so
each player is looked up once through ESPN's search API by name, matched on
club and position, and the answer is cached for a month.

Storage goes through the plugin's cache (a downscaled PNG as base64), not a
directory of its own, so there is nothing to prune on the SD card and the
test harness can seed a picture for a player exactly as it seeds any other
data. Only ESPN hosts are fetched (an SSRF guard) and a download is capped
at 5 MB.

Network calls happen only in :meth:`HeadshotStore.prefetch`, which the plugin
calls from ``update()``. Everything a renderer calls reads the cache.

The crest lookup mirrors the one in NFL Stat Leaders: the core ships a PNG
per club under ``assets/sports/nfl_logos/``.
"""

import base64
import io
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

from PIL import Image

import fantasy_blitz_model as model
from fantasy_blitz_teams import from_espn, to_espn

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    RESAMPLE = Image.LANCZOS

ESPN_SEARCH_URL = "https://site.web.api.espn.com/apis/common/v3/search"
ESPN_HEADSHOT_URL = "https://a.espncdn.com/i/headshots/nfl/players/full/{espn_id}.png"
ALLOWED_HOSTS = (".espncdn.com", ".espn.com")
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
#: Stored width of a headshot. The tallest portrait any layout draws at 1x
#: is under 100px, and ESPN's frame is 600x436, so 200px wide keeps every
#: crop sharp at about 15 KB a player.
STORED_WIDTH = 200
LOOKUP_TTL = 30 * 86400
MISS_TTL = 86400
IMAGE_TTL = 30 * 86400
RETRY_AFTER = 1800

#: ESPN's position abbreviations for the fantasy positions.
_ESPN_POSITIONS = {"QB": {"QB"}, "RB": {"RB", "FB"}, "WR": {"WR"}, "TE": {"TE"},
                   "K": {"PK", "K"}}
NFL_LOGO_DIR = os.path.join("assets", "sports", "nfl_logos")


class HeadshotStore:
    """Resolves, downloads, stores and crops player headshots."""

    def __init__(self, data, logger):
        self.data = data
        self.logger = logger
        self._images: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._portraits: "OrderedDict[Tuple[Any, ...], Image.Image]" = OrderedDict()
        self._logos: "OrderedDict[Tuple[str, int, int], Optional[Image.Image]]" = OrderedDict()
        self._retry_at: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # lookup (cache only)
    # ------------------------------------------------------------------

    def _lookup_key(self, player: Dict[str, Any]) -> str:
        return self.data.key("espnid", player.get("id"))

    def lookup(self, player: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """``{"espn_id", "jersey", "href"}`` if known, from the cache only."""
        if player.get("pos") == "DEF":
            return None
        if player.get("espn_id"):
            espn_id = str(player["espn_id"])
            entry = self.data.read(self._lookup_key(player))
            jersey = ((entry or {}).get("data") or {}).get("jersey") if entry else None
            return {"espn_id": espn_id, "jersey": jersey,
                    "href": ESPN_HEADSHOT_URL.format(espn_id=espn_id)}
        entry = self.data.read(self._lookup_key(player))
        if entry is None:
            return None
        found = entry.get("data") or {}
        return found if found.get("espn_id") else None

    def jersey(self, player: Dict[str, Any]) -> str:
        found = self.lookup(player)
        return str((found or {}).get("jersey") or "")

    # ------------------------------------------------------------------
    # network (update() only)
    # ------------------------------------------------------------------

    def _resolve(self, player: Dict[str, Any], now: float) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Look a player up on ESPN; cache the answer, including "no match".

        Returns ``(found or None, whether the network was used)``.
        """
        key = self._lookup_key(player)
        entry = self.data.read(key)
        if entry is not None:
            found = entry.get("data") or {}
            age = now - float(entry.get("fetched_at") or 0)
            if found.get("espn_id") and age < LOOKUP_TTL:
                return found, False
            if not found.get("espn_id") and age < MISS_TTL:
                return None, False
        payload = self.data._get_json(ESPN_SEARCH_URL, params={
            "query": player.get("name", ""), "limit": 8, "type": "player",
            "sport": "football", "league": "nfl"})
        found = match_search_result(player, (payload or {}).get("items") or [])
        self.data.write(key, found or {}, now)
        return found, True

    def _download(self, espn_id: str, href: Optional[str], now: float) -> bool:
        url = href or ESPN_HEADSHOT_URL.format(espn_id=espn_id)
        if not is_allowed_url(url):
            self.logger.debug("Refusing a non-ESPN headshot URL: %s", url)
            return False
        resp = self.data.session.get(url, timeout=self.data.timeout, stream=True)
        try:
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                return False
            buf = bytearray()
            for chunk in resp.iter_content(16384):
                buf.extend(chunk)
                if len(buf) > MAX_DOWNLOAD_BYTES:
                    return False
        finally:
            resp.close()
        with Image.open(io.BytesIO(bytes(buf))) as src:
            img = src.convert("RGBA")
        if img.width > STORED_WIDTH:
            img = img.resize((STORED_WIDTH, max(1, round(img.height * STORED_WIDTH / img.width))), RESAMPLE)
        out = io.BytesIO()
        img.save(out, "PNG", optimize=True)
        self.data.write(self.data.key("headshot", espn_id),
                        {"png_b64": base64.b64encode(out.getvalue()).decode("ascii")}, now)
        self._images.pop(str(espn_id), None)
        return True

    def has_image(self, espn_id: str, now: float) -> bool:
        entry = self.data.read(self.data.key("headshot", espn_id))
        return entry is not None and now - float(entry.get("fetched_at") or 0) < IMAGE_TTL

    def prefetch(self, players: Iterable[Dict[str, Any]], lookup_only: Iterable[Dict[str, Any]] = (),
                 max_downloads: int = 4, max_lookups: int = 12, budget_seconds: float = 10.0) -> int:
        """Fetch photos for ``players`` and jersey numbers for ``lookup_only``.

        Bounded because update() holds the plugin's lock and the panel
        freezes while it runs: at most ``max_downloads`` photos and
        ``max_lookups`` searches (about 0.2 s each), at most
        ``budget_seconds`` in all, a failing player is not retried for half
        an hour, and the first network failure ends the pass. Returns how
        many lookups and downloads completed, so the caller knows whether
        anything it drew is now out of date.
        """
        started = time.monotonic()
        now = time.time()
        downloads = lookups = 0
        seen = set()
        queue = [(p, True) for p in players] + [(p, False) for p in lookup_only]
        for player, want_photo in queue:
            if time.monotonic() - started > budget_seconds:
                break
            pid = player.get("id")
            if not pid or pid in seen or player.get("pos") == "DEF":
                continue
            seen.add(pid)
            if self._retry_at.get(pid, 0.0) > now:
                continue
            try:
                if player.get("espn_id"):
                    found, used_network = self.lookup(player), False
                elif lookups >= max_lookups and self.lookup(player) is None:
                    continue
                else:
                    found, used_network = self._resolve(player, now)
                lookups += 1 if used_network else 0
                if not want_photo or not found or not found.get("espn_id"):
                    continue
                if downloads >= max_downloads or self.has_image(found["espn_id"], now):
                    continue
                if self._download(found["espn_id"], found.get("href"), now):
                    downloads += 1
                else:
                    self._retry_at[pid] = now + RETRY_AFTER
            except Exception as exc:  # noqa: BLE001 - one bad player never stops update()
                self._retry_at[pid] = now + RETRY_AFTER
                self.logger.debug("Headshot for %s failed: %s", player.get("name"), exc)
                break
        return downloads + lookups

    # ------------------------------------------------------------------
    # images (cache only; safe on the render path)
    # ------------------------------------------------------------------

    def _image(self, espn_id: str) -> Optional[Image.Image]:
        espn_id = str(espn_id)
        if espn_id in self._images:
            self._images.move_to_end(espn_id)
            return self._images[espn_id]
        entry = self.data.read(self.data.key("headshot", espn_id))
        if entry is None:
            return None
        try:
            raw = base64.b64decode(((entry.get("data") or {}).get("png_b64") or "").encode("ascii"))
            with Image.open(io.BytesIO(raw)) as src:
                img = src.convert("RGBA")
        except Exception as exc:  # noqa: BLE001 - a corrupt entry is just a miss
            self.logger.debug("Stored headshot %s unreadable: %s", espn_id, exc)
            return None
        self._images[espn_id] = img
        while len(self._images) > 40:
            self._images.popitem(last=False)
        return img

    def portrait(self, player: Dict[str, Any], width: int, height: int) -> Optional[Image.Image]:
        """The player's headshot cropped to fill ``width`` x ``height`` (RGBA)."""
        if width < 4 or height < 4:
            return None
        found = self.lookup(player)
        if not found:
            return None
        key = (found["espn_id"], width, height)
        if key in self._portraits:
            self._portraits.move_to_end(key)
            return self._portraits[key]
        src = self._image(found["espn_id"])
        if src is None:
            return None
        out = crop_portrait(src, width, height)
        self._portraits[key] = out
        while len(self._portraits) > 60:
            self._portraits.popitem(last=False)
        return out

    def logo(self, abbr: str, width: int, height: int) -> Optional[Image.Image]:
        """The club crest scaled to fit ``width`` x ``height``, or None."""
        key = (abbr, width, height)
        if key in self._logos:
            return self._logos[key]
        logo = None
        path = logo_path(to_espn(abbr))
        if path and width > 2 and height > 2:
            try:
                with Image.open(path) as src:
                    img = src.convert("RGBA")
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                ratio = min(width / img.width, height / img.height)
                size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                logo = img.resize(size, RESAMPLE)
            except Exception as exc:  # noqa: BLE001 - a bad crest is just absent
                self.logger.debug("Crest %s unreadable: %s", abbr, exc)
        self._logos[key] = logo
        while len(self._logos) > 48:
            self._logos.popitem(last=False)
        return logo


def is_allowed_url(url: str) -> bool:
    try:
        parts = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parts.scheme not in ("https", "http"):
        return False
    host = (parts.hostname or "").lower()
    return any(host == h.lstrip(".") or host.endswith(h) for h in ALLOWED_HOSTS)


def match_search_result(player: Dict[str, Any], items: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the ESPN athlete that is this player, or None when unsure.

    Name must match exactly (case, accents, punctuation and Jr./III ignored).
    Among those, the club decides; failing that, the position does; failing
    that, a single remaining candidate is accepted. Two Josh Allens (QB BUF
    and C ARI) resolve correctly this way.
    """
    wanted = model.normalize_name(player.get("name"))
    candidates = []
    for item in items or []:
        if not isinstance(item, dict) or item.get("type") not in (None, "player"):
            continue
        if item.get("league") not in (None, "nfl"):
            continue
        if model.normalize_name(item.get("displayName")) != wanted:
            continue
        rel = (item.get("teamRelationships") or [{}])[0] or {}
        team = from_espn(((rel.get("core") or {}).get("abbreviation")) or "")
        pos = ((item.get("position") or {}).get("abbreviation") or "").upper()
        candidates.append({
            "espn_id": str(item.get("id") or ""),
            "jersey": str(item.get("jersey") or ""),
            "href": ((item.get("headshot") or {}).get("href")),
            "team": team,
            "pos": pos,
        })
    candidates = [c for c in candidates if c["espn_id"]]
    if not candidates:
        return None
    by_team = [c for c in candidates if c["team"] and c["team"] == player.get("team")]
    if len(by_team) == 1:
        return by_team[0]
    wanted_pos = _ESPN_POSITIONS.get(str(player.get("pos")), set())
    pool = by_team or candidates
    by_pos = [c for c in pool if c["pos"] in wanted_pos]
    if len(by_pos) == 1:
        return by_pos[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def crop_portrait(src: Image.Image, width: int, height: int) -> Image.Image:
    """Crop ESPN's head-and-shoulders frame to fill a box, tuned for LEDs.

    ESPN frames the face top-centre. A tall box keeps the shoulders; a small
    one (under 32 px) crops in on the face, because at that size shoulders
    are a coloured smear and the face is what makes it a person. Colour and
    contrast get a small lift: a panel shows photos darker and flatter than
    a monitor does.
    """
    w0, h0 = src.size
    aspect = width / float(height)
    usable_h = h0 if height >= 32 else int(h0 * 0.78)
    crop_h = usable_h
    crop_w = int(round(crop_h * aspect))
    if crop_w > w0:
        crop_w = w0
        crop_h = int(round(crop_w / aspect))
    left = max(0, (w0 - crop_w) // 2)
    img = src.crop((left, 0, left + crop_w, crop_h)).resize((width, height), RESAMPLE)
    rgb = led_boost(img.convert("RGB"))
    rgb.putalpha(img.getchannel("A"))
    return rgb


def led_boost(rgb: Image.Image) -> Image.Image:
    """+25% saturation and +12% contrast, in integer arithmetic.

    ImageEnhance does the same in floating point, and ARM (the Pi) fuses
    the multiply-add that x86 rounds twice, so its portraits came out one
    level different from the goldens on a few pixels. Integers give every
    host the same bytes. Portraits are small and cached, so the loop is
    cheap.
    """
    data = bytearray(rgb.tobytes())
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        grey = (r * 299 + g * 587 + b * 114) // 1000
        out = []
        for c in (r, g, b):
            c = grey + (c - grey) * 5 // 4
            c = 128 + (c - 128) * 112 // 100
            out.append(0 if c < 0 else 255 if c > 255 else c)
        data[i], data[i + 1], data[i + 2] = out
    return Image.frombytes("RGB", rgb.size, bytes(data))


def asset_roots() -> Tuple[Path, ...]:
    """Where the core's ``assets/`` tree may be, best candidate first."""
    here = Path(__file__).resolve()
    roots = [Path("."), here.parent.parent.parent, here.parent]
    env_root = os.environ.get("LEDMATRIX_CORE")
    if env_root:
        roots.insert(0, Path(env_root))
    core_file = getattr(sys.modules.get("src"), "__file__", None)
    if core_file:
        roots.insert(0, Path(core_file).resolve().parent.parent)
    return tuple(roots)


def logo_path(espn_abbr: str) -> Optional[str]:
    if not espn_abbr:
        return None
    for root in asset_roots():
        candidate = Path(root, NFL_LOGO_DIR, f"{espn_abbr}.png")
        if candidate.exists():
            return str(candidate)
    return None
