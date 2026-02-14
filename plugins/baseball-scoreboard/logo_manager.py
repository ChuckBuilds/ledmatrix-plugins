"""
Baseball Logo Manager

Handles logo loading, caching, and auto-download for all baseball leagues.
"""

import os
import logging
from pathlib import Path
from typing import Optional

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

            # Resize to fit display (130% of display dimensions to allow extending off screen)
            max_width = int(self.display_width * 1.5)
            max_height = int(self.display_height * 1.5)
            logo.thumbnail((max_width, max_height), RESAMPLE_FILTER)

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

            # Resize to fit display (130% of display dimensions)
            max_width = int(self.display_width * 1.5)
            max_height = int(self.display_height * 1.5)
            logo.thumbnail((max_width, max_height), RESAMPLE_FILTER)

            # Cache the logo
            self._logo_cache[team_abbr] = logo
            return logo

        except Exception as e:
            self.logger.error(f"Error loading MiLB logo for {team_abbr}: {e}", exc_info=True)
            return None

    def clear_cache(self) -> None:
        """Clear the logo cache."""
        self._logo_cache.clear()
        self.logger.debug("Logo cache cleared")

    def get_cache_size(self) -> int:
        """Get the number of cached logos."""
        return len(self._logo_cache)

