"""
Logo loader for F1 Scoreboard Plugin

Handles loading, caching, and resizing of F1 team logos, the F1 brand logo,
and circuit layout images. All assets are bundled as static PNGs.
Falls back to generating text-based placeholder logos for any missing teams.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from team_colors import get_team_color, normalize_constructor_id

logger = logging.getLogger(__name__)



# Map ESPN circuit names/cities to our bundled circuit image filenames
# Keys are lowercased substrings matched against circuit_name or city
CIRCUIT_FILENAME_MAP = {
    "melbourne": "melbourne",
    "albert park": "melbourne",
    "shanghai": "shanghai",
    "suzuka": "suzuka",
    "bahrain": "bahrain",
    "sakhir": "bahrain",
    "jeddah": "jeddah",
    "miami": "miami",
    "hard rock": "miami",
    "gilles villeneuve": "montreal",
    "montreal": "montreal",
    "monaco": "monaco",
    "monte carlo": "monaco",
    "catalunya": "barcelona",
    "barcelona": "barcelona",
    "red bull ring": "spielberg",
    "spielberg": "spielberg",
    "silverstone": "silverstone",
    "spa": "spa",
    "francorchamps": "spa",
    "stavelot": "spa",
    "hungaroring": "budapest",
    "budapest": "budapest",
    "zandvoort": "zandvoort",
    "monza": "monza",
    "madrid": "madrid",
    "baku": "baku",
    "marina bay": "singapore",
    "singapore": "singapore",
    "americas": "austin",
    "austin": "austin",
    "hermanos rodriguez": "mexico_city",
    "mexico": "mexico_city",
    "interlagos": "interlagos",
    "carlos pace": "interlagos",
    "sao paulo": "interlagos",
    "las vegas": "las_vegas",
    "losail": "losail",
    "lusail": "losail",
    "qatar": "losail",
    "yas marina": "yas_marina",
    "abu dhabi": "yas_marina",
}


class F1LogoLoader:
    """Loads, caches, and resizes F1 team logos and circuit images."""

    def __init__(self, plugin_dir: str = None):
        """
        Initialize the logo loader.

        Args:
            plugin_dir: Path to the plugin directory (contains assets/f1/)
        """
        if plugin_dir is None:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))

        self.plugin_dir = Path(plugin_dir)
        self.teams_dir = self.plugin_dir / "assets" / "f1" / "teams"
        self.circuits_dir = self.plugin_dir / "assets" / "f1" / "circuits"
        self.f1_logo_path = self.plugin_dir / "assets" / "f1" / "f1_logo.png"

        # In-memory cache: key -> PIL Image (already resized)
        self._cache: Dict[str, Image.Image] = {}

    def get_team_logo(self, constructor_id: str, max_height: int = 28,
                      max_width: int = 28) -> Image.Image:
        """
        Get a team logo, resized to fit within max dimensions.

        Always returns an image — generates a text placeholder if no
        logo file exists for the given constructor.

        Args:
            constructor_id: Constructor identifier (any format)
            max_height: Maximum height in pixels
            max_width: Maximum width in pixels

        Returns:
            PIL Image in RGBA mode
        """
        normalized = normalize_constructor_id(constructor_id)
        cache_key = f"team_{normalized}_{max_width}x{max_height}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        logo = self._load_logo(normalized, max_width, max_height)
        self._cache[cache_key] = logo
        return logo

    def get_f1_logo(self, max_height: int = 12,
                    max_width: int = 20) -> Optional[Image.Image]:
        """
        Get the F1 brand logo.

        Args:
            max_height: Maximum height in pixels
            max_width: Maximum width in pixels

        Returns:
            PIL Image in RGBA mode, or None if unavailable
        """
        cache_key = f"f1_logo_{max_width}x{max_height}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        if self.f1_logo_path.exists():
            try:
                img = Image.open(self.f1_logo_path).convert("RGBA")
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning("Failed to load F1 logo: %s", e)

        # Create F1 text placeholder
        placeholder = self._create_text_placeholder("F1", max_width, max_height,
                                                     color=(229, 0, 0))
        self._cache[cache_key] = placeholder
        return placeholder

    def _load_logo(self, constructor_id: str, max_width: int,
                   max_height: int) -> Image.Image:
        """Load a team logo from disk, with placeholder fallback.

        Always returns an image — generates a text placeholder if no
        logo file exists on disk.
        """
        logo_path = self.teams_dir / f"{constructor_id}.png"

        if logo_path.exists():
            try:
                img = Image.open(logo_path).convert("RGBA")
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                return img
            except Exception as e:
                logger.warning("Failed to load logo for %s: %s",
                             constructor_id, e)

        # Try common filename variations
        for variation in [constructor_id.replace("_", ""),
                         constructor_id.replace("_", "-")]:
            alt_path = self.teams_dir / f"{variation}.png"
            if alt_path.exists():
                try:
                    img = Image.open(alt_path).convert("RGBA")
                    img.thumbnail((max_width, max_height),
                                Image.Resampling.LANCZOS)
                    return img
                except Exception as e:
                    logger.debug("Failed to load logo variant %s: %s",
                                 alt_path, e)

        # Create placeholder with team color
        color = get_team_color(constructor_id)
        abbr = constructor_id[:3].upper() if constructor_id else "???"
        return self._create_text_placeholder(abbr, max_width, max_height,
                                              color=color)

    def _create_text_placeholder(self, text: str, width: int, height: int,
                                  color: Tuple[int, int, int] = (200, 200, 200)
                                  ) -> Image.Image:
        """Create a simple text-based placeholder logo."""
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 7)
        except Exception:
            try:
                font = ImageFont.truetype(
                    str(Path(__file__).parent.parent.parent /
                        "assets" / "fonts" / "4x6-font.ttf"), 7)
            except Exception:
                font = ImageFont.load_default()

        text = text[:3]
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = (width - text_w) // 2
        y = (height - text_h) // 2

        # Draw outline
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=color)

        return img

    def get_circuit_image(self, circuit_name: str = "", city: str = "",
                          max_height: int = 28,
                          max_width: int = 40) -> Optional[Image.Image]:
        """
        Get a circuit layout image by matching circuit name or city.

        Args:
            circuit_name: Circuit name (e.g., "Silverstone Circuit")
            city: City name (e.g., "Melbourne")
            max_height: Maximum height in pixels
            max_width: Maximum width in pixels

        Returns:
            PIL Image in RGBA mode (white outline on transparent), or None
        """
        filename = self._resolve_circuit_filename(circuit_name, city)
        if not filename:
            return None

        cache_key = f"circuit_{filename}_{max_width}x{max_height}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        circuit_path = self.circuits_dir / f"{filename}.png"
        if not circuit_path.exists():
            return None

        try:
            img = Image.open(circuit_path).convert("RGBA")
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            self._cache[cache_key] = img
            return img
        except Exception as e:
            logger.warning("Failed to load circuit image %s: %s", filename, e)
            return None

    @staticmethod
    def _resolve_circuit_filename(circuit_name: str, city: str) -> str:
        """Resolve a circuit name/city to a filename key.

        Matches longest keys first to prevent short-key false positives
        (e.g. 'spa' matching inside a longer unrelated string).
        """
        combined = f"{circuit_name} {city}".lower()
        # Sort by key length descending so longer, more specific keys match first
        for key, filename in sorted(CIRCUIT_FILENAME_MAP.items(),
                                     key=lambda kv: len(kv[0]),
                                     reverse=True):
            if key in combined:
                return filename
        return ""

    def clear_cache(self):
        """Clear the in-memory logo cache."""
        self._cache.clear()

    def preload_all_teams(self, max_height: int = 28, max_width: int = 28):
        """
        Preload all team logos into cache.

        Args:
            max_height: Maximum height for cached logos
            max_width: Maximum width for cached logos
        """
        if not self.teams_dir.exists():
            logger.warning("Teams logo directory not found: %s", self.teams_dir)
            return

        count = 0
        for logo_file in self.teams_dir.glob("*.png"):
            constructor_id = logo_file.stem
            self.get_team_logo(constructor_id, max_height, max_width)
            count += 1

        logger.info("Preloaded %d team logos", count)
