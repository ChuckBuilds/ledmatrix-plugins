"""
Baseball Logo Manager

Handles logo loading, caching, and auto-download for all baseball leagues.
"""

import os
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

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
        self, player_id: str, url: Optional[str], league: str = "mlb", max_size: int = 32
    ) -> Optional[Image.Image]:
        """Load a player's headshot, crop-to-fill a square, with in-memory +
        on-disk caching and download-on-miss. Returns None on any failure so
        callers can render a text-only card."""
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

        # Only fetch over http(s); refuse file://, ftp://, etc. from an
        # unexpected URL value.
        if url and str(url).lower().startswith(("http://", "https://")):
            try:
                resp = requests.get(
                    url, timeout=5, headers={"User-Agent": "LEDMatrix Baseball Plugin/1.0"}
                )
                resp.raise_for_status()
                full = Image.open(BytesIO(resp.content)).convert("RGBA")
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

        return None

    def clear_cache(self) -> None:
        """Clear the logo cache."""
        self._logo_cache.clear()
        self.logger.debug("Logo cache cleared")

    def get_cache_size(self) -> int:
        """Get the number of cached logos."""
        return len(self._logo_cache)

