"""
Baseball Logo Manager

Loads and caches player headshots for the player card. Team logos are loaded
by SportsCore._load_and_resize_logo (sports.py) and the scroll card renderer;
the team-logo loaders that used to live here had no callers.
"""

import logging
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

class BaseballLogoManager:
    """Manages logo loading, caching, and downloading for baseball teams."""

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
        self._logo_cache = {}

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
        self, player_id: str, url: Optional[str], league: str = "mlb",
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
                    self._logo_cache[cache_key] = img
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
                if disk_path is not None:
                    try:
                        disk_path.parent.mkdir(parents=True, exist_ok=True)
                        full.save(disk_path, "PNG")
                    except Exception as e:
                        self.logger.debug(f"Could not cache headshot to disk for {player_id}: {e}")
                img = self._crop_square(full, max_size)
                self._logo_cache[cache_key] = img
                return img
            except Exception as e:
                self.logger.debug(f"Failed to download headshot for {player_id}: {e}")
        elif url and allow_download and not self._is_allowed_headshot_url(url):
            self.logger.debug(f"Refusing non-ESPN headshot URL for {player_id}")

        return None

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

