"""
Hockey Headshot Manager

Loads and caches player headshots for the goal-scorer card. Team logos are
loaded by SportsCore._load_and_resize_logo (sports.py) and the scroll card
renderer; nothing team-related lives here.

Deliberately NOT named logo_manager.py. The core loads a plugin's top-level
modules under their bare names, and baseball-scoreboard already ships a
`logo_manager` that it imports late, from inside a method -- a second module
of that name in another plugin is exactly the cross-plugin binding that
CLAUDE.md non-negotiable #4 exists to prevent.
"""

import logging
import os
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS

class HockeyHeadshotManager:
    """Loads, caches and downloads player headshots for hockey."""

    def __init__(self, display_manager, logger: logging.Logger, sport_key: str = None):
        """
        Initialize the logo manager.

        Args:
            display_manager: Display manager instance (for dimensions)
            logger: Logger instance
            sport_key: Sport key for logo directory resolution (optional)
        """
        self.display_manager = display_manager
        self.logger = logger
        self.sport_key = sport_key
        # Bounded LRU of decoded headshots -- see _MEMORY_CACHE_MAX. Mirrors
        # the bound SportsCore._logo_cache carries for team logos.
        self._logo_cache: "OrderedDict[str, Image.Image]" = OrderedDict()

        # Get display dimensions
        if display_manager and hasattr(display_manager, 'matrix') and display_manager.matrix is not None:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        elif display_manager:
            # Fallback to width/height properties (which also check matrix)
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)
        else:
            # Fallback dimensions
            self.display_width = 128
            self.display_height = 32

    # Player headshots are cached on disk under the plugin dir, namespaced by
    # league (MLB and NCAA athlete-id spaces differ), plus an in-memory cache
    # keyed by id+size. Mirrors the masters plugin's headshot loader.
    _HEADSHOT_DIR = Path(__file__).resolve().parent / "assets" / "headshots"
    # Headshots are stored pre-cropped and downscaled, not at ESPN's native
    # size. ESPN serves a ~600x436, ~200 KB PNG; the biggest square any card
    # draws is min(height - 4, width // 3), which is 85px on the largest
    # panel the harness covers. Keeping the square we actually use takes
    # each file to ~40 KB and costs nothing visible on any panel up to 576
    # wide; past that the render upscales slightly rather than the cache
    # carrying a megapixel per player.
    _DISK_HEADSHOT_SIZE = 192
    # ...and the directory is capped, least-recently-used first. Nothing
    # used to remove a file, and the number of athletes is not small: MLB
    # alone has ~1200 active players and ESPN's NCAA baseball coverage is
    # ten times that, so a board left running through a season would grow
    # this directory without limit on an SD card. 200 files is roughly
    # 8 MB, and far more players than any rotation revisits.
    _MAX_CACHED_HEADSHOTS = 200
    # Decoded in-memory squares, keyed by id+size. Two players are current
    # at a time, so this only needs to be big enough to ride out a pitching
    # change without re-reading the disk.
    _MEMORY_CACHE_MAX = 32
    # Headshot URLs come from ESPN's athlete API; only fetch from ESPN's own
    # domains (SSRF guard) and cap the download size (memory-exhaustion guard).
    _ALLOWED_HEADSHOT_HOSTS = (".espncdn.com", ".espn.com")
    _MAX_HEADSHOT_BYTES = 5 * 1024 * 1024  # 5 MB -- a headshot PNG is a few KB

    @classmethod
    def _is_allowed_headshot_url(cls, url: str) -> bool:
        """True only for https(+http) URLs whose host is an ESPN domain."""
        try:
            parts = urlparse(url)
        except Exception:
            return False
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(
            host == h.lstrip(".") or host.endswith(h)
            for h in cls._ALLOWED_HEADSHOT_HOSTS
        )

    @staticmethod
    def _safe_filename(value: str) -> str:
        """Reduce a value (e.g. an ESPN player id) to a safe filename stem --
        only alphanumerics, '_' and '-'. Prevents an unexpected id from
        escaping the headshot cache directory via path separators or '..'."""
        return "".join(c for c in str(value or "") if c.isalnum() or c in ("_", "-"))

    @staticmethod
    def _crop_square(img: Image.Image, size: int) -> Image.Image:
        """Crop to a square from the top-center (ESPN headshots frame the face
        at top-center) and resize to exactly fill a size x size box."""
        w, h = img.size
        if w > h:
            left = (w - h) // 2
            img = img.crop((left, 0, left + h, h))
        elif h > w:
            img = img.crop((0, 0, w, w))
        return img.resize((size, size), RESAMPLE_FILTER)

    def load_headshot(
        self, player_id: str, url: Optional[str], league: str = "nhl",
        max_size: int = 32, allow_download: bool = True,
    ) -> Optional[Image.Image]:
        """Load a player's headshot, crop-to-fill a square, with in-memory +
        on-disk caching. Returns None on any failure so callers can render a
        text-only card.

        allow_download gates the network fetch: the render path passes
        allow_download=False so it only ever does fast memory/disk reads (a
        cache miss returns None rather than blocking the display), while a
        background prefetch passes allow_download=True to warm the disk cache.
        """
        if not player_id and not url:
            return None

        cache_key = f"headshot_{league}_{player_id}_{max_size}"
        if cache_key in self._logo_cache:
            # Re-insert to mark most recently used.
            self._logo_cache.move_to_end(cache_key)
            return self._logo_cache[cache_key]

        # Sanitize the id/league before they touch the filesystem -- they
        # originate from ESPN's API, so never trust them as raw path segments.
        safe_id = self._safe_filename(player_id)
        safe_league = self._safe_filename(league) or "unknown"
        disk_path = None
        if safe_id:
            disk_path = self._HEADSHOT_DIR / safe_league / f"{safe_id}.png"
            if disk_path.exists():
                try:
                    with Image.open(disk_path) as src:
                        img = self._crop_square(src.convert("RGBA"), max_size)
                    # Stamp the file so the directory cap below evicts by
                    # genuine last use, not by when it was first downloaded
                    # -- otherwise a favourite team's regulars get dropped
                    # ahead of a one-off from a game nobody watches again.
                    # One stat-sized write per player per process start, as
                    # the in-memory cache absorbs every repeat hit.
                    try:
                        os.utime(disk_path, None)
                    except OSError:
                        pass
                    self._remember(cache_key, img)
                    return img
                except Exception as e:
                    self.logger.debug(f"Failed to load cached headshot {player_id}: {e}")

        # Network fetch only when explicitly allowed (never on the render path)
        # and only from an ESPN host, with a bounded response size.
        if allow_download and url and self._is_allowed_headshot_url(url):
            try:
                full = self._download_headshot_image(url)
                if full is None:
                    return None
                # Crop and downscale once, here, so the disk copy is the
                # square the card draws rather than ESPN's full-size PNG.
                stored = self._crop_square(full, self._DISK_HEADSHOT_SIZE)
                if disk_path is not None:
                    try:
                        disk_path.parent.mkdir(parents=True, exist_ok=True)
                        stored.save(disk_path, "PNG")
                        self._prune_headshot_cache()
                    except Exception as e:
                        self.logger.debug(f"Could not cache headshot to disk for {player_id}: {e}")
                img = self._crop_square(stored, max_size)
                self._remember(cache_key, img)
                return img
            except Exception as e:
                self.logger.debug(f"Failed to download headshot for {player_id}: {e}")
        elif url and allow_download and not self._is_allowed_headshot_url(url):
            self.logger.debug(f"Refusing non-ESPN headshot URL for {player_id}")

        return None

    def _remember(self, cache_key: str, img: Image.Image) -> None:
        """Store a decoded square, evicting the least recently used entries
        past _MEMORY_CACHE_MAX."""
        self._logo_cache[cache_key] = img
        while len(self._logo_cache) > self._MEMORY_CACHE_MAX:
            self._logo_cache.popitem(last=False)

    def _prune_headshot_cache(self) -> None:
        """Hold the on-disk cache to _MAX_CACHED_HEADSHOTS files, deleting
        the least recently used first (see the os.utime stamp on a cache
        hit). Swallows filesystem errors: a cache that cannot be trimmed is
        not a reason to fail the render that just warmed it."""
        try:
            files = sorted(
                (p for p in self._HEADSHOT_DIR.rglob("*.png") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError as e:
            self.logger.debug(f"Could not scan the headshot cache to prune it: {e}")
            return
        excess = len(files) - self._MAX_CACHED_HEADSHOTS
        for stale in files[:excess] if excess > 0 else []:
            try:
                stale.unlink()
            except OSError as e:
                self.logger.debug(f"Could not evict cached headshot {stale.name}: {e}")

    def _download_headshot_image(self, url: str) -> Optional[Image.Image]:
        """Download a headshot with a hard size cap (memory-exhaustion guard),
        returning an RGBA image or None. Assumes the URL host is already
        allowlisted by the caller."""
        resp = requests.get(
            url, timeout=5, stream=True,
            headers={"User-Agent": "LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)"},
        )
        try:
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length")
            if declared is not None and declared.isdigit() and int(declared) > self._MAX_HEADSHOT_BYTES:
                self.logger.debug(f"Headshot exceeds size cap (Content-Length={declared})")
                return None
            content = bytearray()
            for chunk in resp.iter_content(8192):
                content.extend(chunk)
                if len(content) > self._MAX_HEADSHOT_BYTES:
                    self.logger.debug("Headshot exceeded size cap while streaming")
                    return None
        finally:
            resp.close()
        return Image.open(BytesIO(bytes(content))).convert("RGBA")

    def clear_cache(self) -> None:
        """Clear the logo cache."""
        self._logo_cache.clear()
        self.logger.debug("Logo cache cleared")

    def get_cache_size(self) -> int:
        """Get the number of cached logos."""
        return len(self._logo_cache)

