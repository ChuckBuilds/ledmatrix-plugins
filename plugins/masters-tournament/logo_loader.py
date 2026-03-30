"""
Masters Logo & Asset Loader

Handles loading, caching, and resizing of all Masters Tournament assets:
- Masters logo (multiple sizes for different displays)
- Green jacket icon
- Azalea flower accents
- Hole maps for all 18 Augusta National holes
- Player headshots (downloaded from ESPN CDN)
- Country flags for player cards
"""

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from masters_helpers import ESPN_HEADSHOT_URL, ESPN_PLAYER_IDS, get_espn_headshot_url

logger = logging.getLogger(__name__)


class MastersLogoLoader:
    """Loads, caches, and resizes Masters Tournament assets."""

    def __init__(self, plugin_dir: str = None):
        if plugin_dir is None:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))

        self.plugin_dir = Path(plugin_dir)
        self.masters_dir = self.plugin_dir / "assets" / "masters"
        self.logos_dir = self.masters_dir / "logos"
        self.courses_dir = self.masters_dir / "courses"
        self.players_dir = self.masters_dir / "players"
        self.flags_dir = self.masters_dir / "flags"
        self.icons_dir = self.masters_dir / "icons"
        self.backgrounds_dir = self.masters_dir / "backgrounds"

        for directory in [self.logos_dir, self.courses_dir, self.players_dir,
                          self.flags_dir, self.icons_dir, self.backgrounds_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        self._cache: Dict[str, Image.Image] = {}

    def get_masters_logo(self, max_width: int = 20, max_height: int = 12) -> Optional[Image.Image]:
        """Get the Masters logo, choosing the best size variant."""
        cache_key = f"masters_logo_{max_width}x{max_height}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Try size-specific logos first
        if max_width <= 32:
            candidates = ["masters_logo_sm.png", "masters_logo.png"]
        elif max_width <= 48:
            candidates = ["masters_logo_md.png", "masters_logo_sm.png", "masters_logo.png"]
        else:
            candidates = ["masters_logo_lg.png", "masters_logo.png"]

        for filename in candidates:
            logo_path = self.logos_dir / filename
            if logo_path.exists():
                try:
                    img = Image.open(logo_path).convert("RGBA")
                    img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                    self._cache[cache_key] = img
                    return img
                except Exception as e:
                    logger.warning(f"Failed to load {filename}: {e}")

        # Text placeholder fallback
        placeholder = self._create_text_placeholder("M", max_width, max_height, (0, 104, 56))
        self._cache[cache_key] = placeholder
        return placeholder

    def get_green_jacket_icon(self, size: int = 16) -> Optional[Image.Image]:
        """Get the green jacket icon."""
        cache_key = f"green_jacket_{size}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        icon_path = self.logos_dir / "green_jacket.png"
        if icon_path.exists():
            try:
                img = Image.open(icon_path).convert("RGBA")
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning(f"Failed to load green jacket: {e}")

        # Minimal placeholder
        placeholder = Image.new("RGBA", (size, size), (0, 120, 74, 255))
        self._cache[cache_key] = placeholder
        return placeholder

    def get_azalea_icon(self, size: int = 16) -> Optional[Image.Image]:
        """Get the azalea flower accent icon."""
        cache_key = f"azalea_{size}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        icon_path = self.logos_dir / "azalea.png"
        if icon_path.exists():
            try:
                img = Image.open(icon_path).convert("RGBA")
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning(f"Failed to load azalea: {e}")

        # Pink circle fallback
        placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        r = size // 3
        c = size // 2
        draw.ellipse([c - r, c - r, c + r, c + r], fill=(255, 105, 180, 255))
        self._cache[cache_key] = placeholder
        return placeholder

    def get_hole_image(self, hole_number: int, max_width: int = 40, max_height: int = 28) -> Optional[Image.Image]:
        """Get a hole map image for Augusta National."""
        if not 1 <= hole_number <= 18:
            return None

        cache_key = f"hole_{hole_number}_{max_width}x{max_height}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        hole_path = self.courses_dir / f"hole_{hole_number:02d}.png"
        if hole_path.exists():
            try:
                img = Image.open(hole_path).convert("RGBA")
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning(f"Failed to load hole {hole_number}: {e}")

        placeholder = self._create_hole_placeholder(hole_number, max_width, max_height)
        self._cache[cache_key] = placeholder
        return placeholder

    def _crop_to_fill(self, img: Image.Image, size: int) -> Image.Image:
        """Crop and resize image to exactly fill a square, centering on the face area."""
        w, h = img.size
        # Crop to square from the top-center (faces are usually top-center in headshots)
        if w > h:
            left = (w - h) // 2
            img = img.crop((left, 0, left + h, h))
        elif h > w:
            # Keep top portion (face is at top in ESPN headshots)
            img = img.crop((0, 0, w, w))
        return img.resize((size, size), Image.Resampling.LANCZOS)

    def get_player_headshot(self, player_id: str, url: Optional[str], max_size: int = 24) -> Optional[Image.Image]:
        """Get player headshot, crop-to-fill so it fills the display box."""
        if not player_id:
            return None

        cache_key = f"player_{player_id}_{max_size}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Check disk cache
        player_path = self.players_dir / f"{player_id}.png"
        if player_path.exists():
            try:
                img = Image.open(player_path).convert("RGBA")
                img = self._crop_to_fill(img, max_size)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning(f"Failed to load cached headshot {player_id}: {e}")

        # Download from URL
        if url:
            try:
                response = requests.get(url, timeout=5, headers={
                    "User-Agent": "LEDMatrix Masters Plugin/2.0"
                })
                response.raise_for_status()

                img = Image.open(BytesIO(response.content)).convert("RGBA")
                img.save(player_path, "PNG")

                img = self._crop_to_fill(img, max_size)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.debug(f"Failed to download headshot for {player_id}: {e}")

        return None

    def get_country_flag(self, country_code: str, width: int = 16, height: int = 10) -> Optional[Image.Image]:
        """Get a country flag image."""
        if not country_code:
            return None

        cache_key = f"flag_{country_code}_{width}x{height}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        flag_path = self.flags_dir / f"{country_code}.png"
        if flag_path.exists():
            try:
                img = Image.open(flag_path).convert("RGBA")
                img = img.resize((width, height), Image.Resampling.NEAREST)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning(f"Failed to load flag {country_code}: {e}")

        return None

    def get_icon(self, icon_name: str, size: int = 16) -> Optional[Image.Image]:
        """Load an icon from the icons directory."""
        cache_key = f"icon_{icon_name}_{size}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        icon_path = self.icons_dir / icon_name
        if icon_path.exists():
            try:
                img = Image.open(icon_path).convert("RGBA")
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                self._cache[cache_key] = img
                return img
            except Exception as e:
                logger.warning(f"Failed to load icon {icon_name}: {e}")

        return None

    def _create_text_placeholder(self, text: str, width: int, height: int,
                                  color: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
        """Create a simple text-based placeholder."""
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font = self._get_small_font()

        if len(text) > width // 4:
            text = text[:width // 4]

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        x = (width - tw) // 2
        y = (height - th) // 2

        # Outline for visibility
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), text, font=font, fill=color + (255,))

        return img

    def _create_hole_placeholder(self, hole_number: int, width: int, height: int) -> Image.Image:
        """Create a placeholder hole map."""
        img = Image.new("RGBA", (width, height), (34, 120, 34, 255))
        draw = ImageDraw.Draw(img)

        # Simple fairway line
        draw.line(
            [(width // 3, height - 5), (width * 2 // 3, 5)],
            fill=(60, 170, 60, 255),
            width=max(3, width // 8),
        )

        # Green circle
        gx, gy = width * 2 // 3, 8
        draw.ellipse([gx - 6, gy - 4, gx + 6, gy + 4], fill=(80, 200, 80, 255))

        # Flag
        draw.line([(gx, gy), (gx, gy - 8)], fill=(255, 255, 255, 255), width=1)
        draw.polygon([(gx, gy - 8), (gx + 4, gy - 6), (gx, gy - 4)], fill=(255, 0, 0, 255))

        # Hole number
        font = self._get_small_font()
        text = f"#{hole_number}"
        draw.text((2, height - 8), text, font=font, fill=(255, 255, 255, 255))

        return img

    def _get_small_font(self) -> ImageFont.ImageFont:
        """Get a small font for placeholders."""
        font_paths = [
            "assets/fonts/4x6-font.ttf",
            str(Path.home() / "Github" / "LEDMatrix" / "assets" / "fonts" / "4x6-font.ttf"),
        ]
        for p in font_paths:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, 6)
                except Exception:
                    pass
        return ImageFont.load_default()

    def preload_all_holes(self, max_width: int = 40, max_height: int = 28):
        """Preload all 18 hole images into cache."""
        count = 0
        for hole_num in range(1, 19):
            if self.get_hole_image(hole_num, max_width, max_height):
                count += 1
        logger.info(f"Preloaded {count} hole images")

    def clear_cache(self):
        """Clear the in-memory image cache."""
        self._cache.clear()
