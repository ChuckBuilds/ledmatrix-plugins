"""
Image Renderer for Leaderboard Plugin

Handles all image creation and rendering for the scrolling leaderboard display.
Includes logo loading, text drawing with outlines, and layout calculations.

Rendering is pixel-perfect by design: an LED matrix has no sub-pixels, so any
anti-aliased grey a glyph or logo edge lands on shows up as a dim, smeared LED.
Two things keep the output crisp:

- Text is drawn with ``fontmode = "1"``, so a glyph pixel is either fully lit or
  fully off no matter what font/size is configured. Default sizes are
  additionally snapped to the font's own pixel grid (8px for Press Start 2P,
  7px for the 4x6 fallback) so glyphs land on whole pixels.
- Logos are downscaled with LANCZOS for detail, then their alpha is thresholded
  so the edges are hard instead of a ring of half-lit pixels.
"""

import math
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

# Pillow compatibility: Image.Resampling.LANCZOS arrived in Pillow 9.1.
# Fall back to the module-level constant for older versions.
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow < 9.1
    RESAMPLE_FILTER = Image.LANCZOS

# Try to import logo downloader
try:
    from src.logo_downloader import download_missing_logo
except ImportError:
    # Fallback - plugins may have their own logo downloader
    try:
        import sys
        # Look for logo downloader in parent directories
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
        from src.logo_downloader import download_missing_logo
    except ImportError:
        def download_missing_logo(*args, **kwargs):
            return False


class ImageRenderer:
    """Handles image creation and rendering for leaderboard display."""

    MARCH_MADNESS_LOGO_PATH = 'assets/sports/ncaa_logos/MARCH_MADNESS.png'

    #: Fonts whose glyphs are drawn on a fixed pixel grid. Rendering them at a
    #: size that is not a whole multiple of the grid forces the rasteriser to
    #: split single design pixels across screen pixels, which is what makes the
    #: text look blurry on the panel.
    PIXEL_FONT_GRIDS = {
        'PressStart2P-Regular.ttf': 8,
        '4x6-font.ttf': 7,
    }

    PRIMARY_FONT = 'assets/fonts/PressStart2P-Regular.ttf'
    FALLBACK_FONT = 'assets/fonts/4x6-font.ttf'

    #: Horizontal gaps, in pixels, used by the team layout.
    RANK_LOGO_GAP = 4
    LOGO_TEXT_GAP = 4
    TEAM_GAP = 12
    #: Width of the league logo column, and the gap after it.
    LEAGUE_LOGO_WIDTH = 64
    LEAGUE_LOGO_GAP = 10
    #: Blank space between one league's last team and the next league's logo.
    LEAGUE_SPACING = 40

    def __init__(self, display_height: int, logger: Optional[logging.Logger] = None,
                 appearance: Optional[Dict[str, Any]] = None):
        """
        Initialize image renderer.

        Args:
            display_height: Height of the display in pixels
            logger: Optional logger instance
            appearance: Optional appearance overrides (see config_schema.json
                ``global.appearance``)
        """
        self.display_height = display_height
        self.logger = logger or logging.getLogger(__name__)

        appearance = appearance or {}
        self.pixel_perfect_text = bool(appearance.get('pixel_perfect_text', True))
        self.crisp_logos = bool(appearance.get('crisp_logos', True))
        self.text_outline = bool(appearance.get('text_outline', True))
        self.logo_scale = self._clamp_float(appearance.get('logo_scale', 1.0), 0.5, 1.5, 1.0)
        self.font_size_override = self._clamp_int(appearance.get('font_size', 0), 0, 32, 0)

        self.font_path = self._resolve_font_path()
        self.font_grid = self.PIXEL_FONT_GRIDS.get(
            os.path.basename(self.font_path or ''), 0
        )
        self.fonts = self._load_fonts()

    @staticmethod
    def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
        try:
            return max(low, min(high, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return default

    def _resolve_font_path(self) -> Optional[str]:
        """Pick the best available font file, preferring Press Start 2P."""
        for candidate in (self.PRIMARY_FONT, self.FALLBACK_FONT):
            if os.path.exists(candidate):
                return candidate
        return None

    def _snap_font_size(self, requested: int) -> int:
        """
        Round a font size to the font's pixel grid.

        Press Start 2P only rasterises without anti-aliasing at multiples of 8
        (8, 16, 24...); the 4x6 fallback at multiples of 7. Off-grid sizes are
        what produced the blurry text this renderer used to show.
        """
        if self.font_grid <= 0:
            return max(1, requested)
        snapped = int(round(requested / self.font_grid)) * self.font_grid
        return max(self.font_grid, snapped)

    def _auto_font_size(self) -> int:
        """Choose an on-grid font size that suits the panel height."""
        if self.font_size_override:
            return self._snap_font_size(self.font_size_override)

        grid = self.font_grid or 8
        # Aim for text about a quarter of the panel height, then snap to the
        # grid. 32px panels land on one grid step, 64px panels on two.
        target = max(grid, int(self.display_height / 4))
        return self._snap_font_size(target)

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """
        Load fonts for the leaderboard display.

        All sizes are snapped to the font's pixel grid so glyph edges land on
        whole panel pixels.
        """
        fonts = {}
        base = self._auto_font_size()
        grid = self.font_grid or 8
        sizes = {
            'small': max(grid, base - grid) if base > grid else base,
            'medium': base,
            'large': base,
            'xlarge': base,
        }

        if self.font_path:
            try:
                for key, size in sizes.items():
                    fonts[key] = ImageFont.truetype(self.font_path, size)
                self.logger.info(
                    "Loaded %s at pixel-aligned sizes %s (grid=%spx)",
                    os.path.basename(self.font_path), sizes, self.font_grid or 'n/a'
                )
                return fonts
            except (IOError, OSError) as e:
                self.logger.warning("Could not load %s: %s", self.font_path, e)
            except Exception as e:  # pragma: no cover - defensive
                self.logger.error("Error loading fonts: %s", e)

        self.logger.warning("No pixel font available, using default PIL font")
        default_font = ImageFont.load_default()
        return {key: default_font for key in ('small', 'medium', 'large', 'xlarge')}

    def _text_advance(self, text: str, font: ImageFont.FreeTypeFont) -> int:
        """Width a string occupies for layout purposes, in whole pixels."""
        try:
            return int(math.ceil(font.getlength(text)))
        except AttributeError:  # pragma: no cover - very old Pillow
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0])

    def _text_ink_box(self, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
        """Return (ink_top, ink_height) for a string relative to the draw origin."""
        try:
            bbox = font.getbbox(text)
        except AttributeError:  # pragma: no cover - very old Pillow
            return 0, getattr(font, 'size', self.display_height // 4)
        return int(bbox[1]), int(bbox[3] - bbox[1])

    def _text_baseline_y(self, text: str, font: ImageFont.FreeTypeFont, height: int) -> int:
        """
        Y to pass to ``draw.text`` so the string's ink is vertically centred.

        ``draw.text`` positions by the ascender line, not by the ink box, so the
        ink offset has to be subtracted or the text sits low and can clip off
        the bottom of the panel.
        """
        ink_top, ink_height = self._text_ink_box(text, font)
        return (height - ink_height) // 2 - ink_top

    def _make_draw(self, image: Image.Image) -> ImageDraw.ImageDraw:
        """
        Get a draw context that rasterises text without anti-aliasing.

        ``fontmode = "1"`` switches Pillow to 1-bit glyph rendering, so every
        text pixel is either fully lit or off. Left on the default the panel
        shows partially-lit LEDs around every glyph, which is what made this
        display read as blurry.
        """
        draw = ImageDraw.Draw(image)
        if self.pixel_perfect_text:
            draw.fontmode = "1"
        return draw

    def _draw_text(self, draw: ImageDraw.ImageDraw, text: str, position: tuple,
                   font: ImageFont.FreeTypeFont, fill: tuple = (255, 255, 255),
                   outline_color: tuple = (0, 0, 0)):
        """Draw text, optionally with a black outline for contrast over logos."""
        if not text:
            return

        x, y = position
        if self.text_outline:
            for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                           (0, 1), (1, -1), (1, 0), (1, 1)]:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def _prepare_logo(self, logo: Image.Image, max_width: int,
                      max_height: int) -> Optional[Image.Image]:
        """
        Scale a logo to fit ``max_width`` x ``max_height`` with hard edges.

        Aspect ratio is preserved (squashing a non-square logo into a square box
        is its own kind of blur), and the alpha channel is thresholded so the
        edge is a clean on/off boundary rather than a ring of half-lit pixels.
        """
        if logo is None or max_width <= 0 or max_height <= 0:
            return None
        try:
            logo = logo.convert('RGBA')
            scale = min(max_width / logo.width, max_height / logo.height)
            target_w = max(1, int(logo.width * scale))
            target_h = max(1, int(logo.height * scale))
            logo = logo.resize((target_w, target_h), RESAMPLE_FILTER)

            if self.crisp_logos:
                r, g, b, a = logo.split()
                a = a.point(lambda p: 255 if p >= 128 else 0)
                logo = Image.merge('RGBA', (r, g, b, a))
            return logo
        except Exception as e:
            self.logger.error("Error preparing logo: %s", e)
            return None

    def _get_team_logo(self, league: str, team_id: str, team_abbr: str, logo_dir: str) -> Optional[Image.Image]:
        """Get team logo from the configured directory, downloading if missing."""
        if not team_abbr or not logo_dir:
            self.logger.debug("Cannot get team logo with missing team_abbr or logo_dir")
            return None
        try:
            logo_path = Path(logo_dir, f"{team_abbr}.png")
            if os.path.exists(logo_path):
                logo = Image.open(logo_path)
                self.logger.debug(f"Successfully loaded logo for {team_abbr}")
                return logo
            else:
                self.logger.warning(f"Logo not found at path: {logo_path}")

                # Try to download the missing logo
                if league:
                    self.logger.info(f"Attempting to download missing logo for {team_abbr} in league {league}")
                    success = download_missing_logo(league, team_id, team_abbr, logo_path, None)
                    if success and os.path.exists(logo_path):
                        logo = Image.open(logo_path)
                        self.logger.info(f"Successfully downloaded and loaded logo for {team_abbr}")
                        return logo

                return None
        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbr}: {e}")
            return None

    def _get_league_logo(self, league_logo_path: str) -> Optional[Image.Image]:
        """Get league logo from the configured path."""
        if not league_logo_path:
            return None
        try:
            if os.path.exists(league_logo_path):
                logo = Image.open(league_logo_path)
                self.logger.debug(f"Successfully loaded league logo from {league_logo_path}")
                return logo
            else:
                self.logger.warning(f"League logo not found at path: {league_logo_path}")
                return None
        except Exception as e:
            self.logger.error(f"Error loading league logo: {e}")
            return None

    def _build_layout(self, leaderboard_data: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Resolve every league/team into a measured, draw-ready layout.

        Measuring and drawing used to be two separate passes over the same data,
        which let them disagree — the width pass always budgeted for a team logo
        while the draw pass skipped it when the file was missing, so the strip
        ended up either padded with dead space or clipped short of the last
        team. Resolving logos once here means the measured width is exactly the
        drawn width.

        Returns:
            (layout, total_width) where total_width is the exact content width.
        """
        height = self.display_height
        logo_box = max(1, int(height * self.logo_scale))
        layout = []
        total_width = 0

        for league_data in leaderboard_data:
            league_key = league_data['league']
            league_config = league_data['league_config']

            league_logo_path = league_config.get('league_logo')
            if league_data.get('is_tournament') and league_key in ('ncaam_basketball', 'ncaaw_basketball'):
                if os.path.exists(self.MARCH_MADNESS_LOGO_PATH):
                    league_logo_path = self.MARCH_MADNESS_LOGO_PATH
            league_logo = self._prepare_logo(
                self._get_league_logo(league_logo_path), self.LEAGUE_LOGO_WIDTH, height
            )

            teams = []
            teams_width = 0
            for i, team in enumerate(league_data['teams']):
                number_text = self._get_number_text(league_key, league_config, team, i)
                number_width = self._text_advance(number_text, self.fonts['xlarge'])

                team_text = team.get('abbreviation', '')
                text_width = self._text_advance(team_text, self.fonts['large'])

                team_logo = self._prepare_logo(
                    self._get_team_logo(league_key, team.get('id'), team_text,
                                        league_config.get('logo_dir')),
                    logo_box, logo_box
                )

                width = number_width + text_width + self.TEAM_GAP + self.LOGO_TEXT_GAP
                if team_logo:
                    width += self.RANK_LOGO_GAP + team_logo.width

                teams.append({
                    'number_text': number_text,
                    'number_width': number_width,
                    'text': team_text,
                    'text_width': text_width,
                    'logo': team_logo,
                    'width': width,
                })
                teams_width += width

            league_width = self.LEAGUE_LOGO_WIDTH + self.LEAGUE_LOGO_GAP + teams_width
            layout.append({
                'key': league_key,
                'logo': league_logo,
                'teams': teams,
                'width': league_width,
            })
            total_width += league_width + self.LEAGUE_SPACING

        return layout, total_width

    def create_leaderboard_image(self, leaderboard_data: List[Dict[str, Any]]) -> Optional[Image.Image]:
        """
        Create the scrolling leaderboard image.

        Args:
            leaderboard_data: List of league data dictionaries with teams

        Returns:
            PIL Image containing the full scrolling leaderboard, or None on error
        """
        if not leaderboard_data:
            self.logger.warning("No leaderboard data available")
            return None

        try:
            height = self.display_height
            layout, total_width = self._build_layout(leaderboard_data)
            if total_width <= 0:
                self.logger.warning("Leaderboard layout measured zero width")
                return None

            leaderboard_image = Image.new('RGB', (total_width, height), (0, 0, 0))
            draw = self._make_draw(leaderboard_image)

            current_x = 0
            for league_idx, league in enumerate(layout):
                self.logger.info(
                    "Drawing League %d (%s) at x=%dpx, %d teams, %dpx wide",
                    league_idx + 1, league['key'], current_x, len(league['teams']), league['width']
                )

                league_logo = league['logo']
                if league_logo:
                    logo_x = current_x + (self.LEAGUE_LOGO_WIDTH - league_logo.width) // 2
                    logo_y = (height - league_logo.height) // 2
                    leaderboard_image.paste(league_logo, (logo_x, logo_y), league_logo)

                team_x = current_x + self.LEAGUE_LOGO_WIDTH + self.LEAGUE_LOGO_GAP

                for team in league['teams']:
                    number_text = team['number_text']
                    number_y = self._text_baseline_y(number_text, self.fonts['xlarge'], height)
                    self._draw_text(draw, number_text, (team_x, number_y),
                                    self.fonts['xlarge'], fill=(255, 255, 0))

                    text_x = team_x + team['number_width']
                    team_logo = team['logo']
                    if team_logo:
                        logo_x = text_x + self.RANK_LOGO_GAP
                        logo_y_pos = (height - team_logo.height) // 2
                        leaderboard_image.paste(team_logo, (logo_x, logo_y_pos), team_logo)
                        text_x = logo_x + team_logo.width

                    text_x += self.LOGO_TEXT_GAP
                    text_y = self._text_baseline_y(team['text'], self.fonts['large'], height)
                    self._draw_text(draw, team['text'], (text_x, text_y),
                                    self.fonts['large'], fill=(255, 255, 255))

                    team_x += team['width']

                current_x = team_x + self.LEAGUE_SPACING

            self.logger.info(
                "Created leaderboard image: %dpx wide, %d league(s), %d team(s)",
                total_width, len(layout), sum(len(l['teams']) for l in layout)
            )
            return leaderboard_image

        except Exception as e:
            self.logger.error(f"Error creating leaderboard image: {e}")
            return None

    def _get_number_text(self, league_key: str, league_config: Dict[str, Any],
                         team: Dict[str, Any], index: int) -> str:
        """Get the number/ranking text to display for a team."""
        if league_key == 'ncaa_fb':
            if league_config.get('show_ranking', True):
                if 'rank' in team and team['rank'] > 0:
                    return f"#{team['rank']}"
                else:
                    return f"{index+1}."
            else:
                if 'record_summary' in team:
                    return team['record_summary']
                else:
                    return f"{index+1}."
        elif league_key in ('ncaam_basketball', 'ncaaw_basketball'):
            if league_config.get('show_ranking', True) and team.get('rank', 0) > 0:
                return f"#{team['rank']}"
            return f"{index+1}."
        else:
            return f"{index+1}."
