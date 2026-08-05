"""
Baseball Logo Manager

Handles logo loading, caching, and auto-download for all baseball leagues.
"""

import os
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

try:
    from src.logo_downloader import LogoDownloader, download_missing_logo
except ImportError:
    LogoDownloader = None
    download_missing_logo = None


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

    def load_logo(self, team_id: str, team_abbr: str, logo_path: Path, 
                  logo_url: Optional[str] = None, sport_key: Optional[str] = None) -> Optional[Image.Image]:
        """
        Load and resize a team logo, with caching and automatic download if missing.

        Args:
            team_id: Team identifier
            team_abbr: Team abbreviation
            logo_path: Path to logo file
            logo_url: Optional logo URL for download
            sport_key: Sport key for logo download (uses self.sport_key if not provided)

        Returns:
            PIL Image of the logo, or None if loading failed
        """
        self.logger.debug(f"Loading logo for {team_abbr} at {logo_path}")

        # Check cache first
        if team_abbr in self._logo_cache:
            self.logger.debug(f"Using cached logo for {team_abbr}")
            return self._logo_cache[team_abbr]

        try:
            # Try different filename variations first (for cases like TA&M vs TAANDM)
            actual_logo_path = None
            if LogoDownloader:
                filename_variations = LogoDownloader.get_logo_filename_variations(team_abbr)
                
                for filename in filename_variations:
                    test_path = logo_path.parent / filename
                    if test_path.exists():
                        actual_logo_path = test_path
                        self.logger.debug(f"Found logo at alternative path: {actual_logo_path}")
                        break
            else:
                # Fallback: just try the original path
                if logo_path.exists():
                    actual_logo_path = logo_path

            # If no variation found, try to download missing logo
            if not actual_logo_path and not logo_path.exists():
                self.logger.info(f"Logo not found for {team_abbr} at {logo_path}. Attempting to download.")
                
                # Try to download the logo from ESPN API (this will create placeholder if download fails)
                if download_missing_logo:
                    sport_key_to_use = sport_key or self.sport_key or "baseball"
                    download_missing_logo(sport_key_to_use, team_id, team_abbr, logo_path, logo_url)
                    actual_logo_path = logo_path
                else:
                    self.logger.warning("LogoDownloader not available - cannot download missing logos")

            # Use the original path if no alternative was found
            if not actual_logo_path:
                actual_logo_path = logo_path

            # Only try to open the logo if the file exists
            if os.path.exists(actual_logo_path):
                with Image.open(actual_logo_path) as src:
                    logo = src.convert('RGBA')
            else:
                self.logger.error(f"Logo file still doesn't exist at {actual_logo_path} after download attempt")
                return None

            # Crop transparent padding so scaling operates on actual content
            bbox = logo.getbbox()
            if bbox:
                logo = logo.crop(bbox)

            # Cap at logo slot width and 75% of display height
            logo_slot = min(self.display_height, self.display_width // 2)
            max_logo_h = int(self.display_height * 0.75)
            logo.thumbnail((logo_slot, max_logo_h), RESAMPLE_FILTER)

            # Cache the logo
            self._logo_cache[team_abbr] = logo
            return logo

        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbr}: {e}", exc_info=True)
            return None

    def load_milb_logo(self, team_abbr: str, logo_dir: Path) -> Optional[Image.Image]:
        """
        Load MiLB team logo (simpler version without download).

        Args:
            team_abbr: Team abbreviation
            logo_dir: Logo directory path

        Returns:
            PIL Image of the logo, or None if loading failed
        """
        self.logger.debug(f"Loading MiLB logo for {team_abbr} from {logo_dir}")

        # Check cache first
        if team_abbr in self._logo_cache:
            self.logger.debug(f"Using cached logo for {team_abbr}")
            return self._logo_cache[team_abbr]

        try:
            logo_path = logo_dir / f"{team_abbr}.png"
            
            if logo_path.exists():
                with Image.open(logo_path) as src:
                    logo = src.convert('RGBA')
            else:
                self.logger.warning(f"MiLB logo not found for {team_abbr} at {logo_path}")
                return None

            # Crop transparent padding so scaling operates on actual content
            bbox = logo.getbbox()
            if bbox:
                logo = logo.crop(bbox)

            # MiLB logos are landscape banner art (1.2–2.7:1 aspect ratio).
            # Cap width at 1/3 of display width and height at full display height so
            # the logo stays within its corner and never overlaps center score text.
            max_logo_w = self.display_width // 3
            max_logo_h = self.display_height
            logo.thumbnail((max_logo_w, max_logo_h), RESAMPLE_FILTER)

            # Cache the logo
            self._logo_cache[team_abbr] = logo
            return logo

        except Exception as e:
            self.logger.error(f"Error loading MiLB logo for {team_abbr}: {e}", exc_info=True)
            return None

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

