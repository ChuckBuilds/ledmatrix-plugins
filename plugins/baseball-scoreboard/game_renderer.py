"""
Game Card Renderer for Baseball Scoreboard Plugin

Renders individual baseball game cards as PIL Images for use in scroll mode.
Returns images instead of updating display directly.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import pytz
from PIL import Image, ImageDraw, ImageFont

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class GameRenderer:
    """Renders individual baseball game cards as PIL Images."""

    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict,
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the game renderer.

        Args:
            display_width: Display width in pixels
            display_height: Display height in pixels
            config: Plugin configuration dictionary
            logo_cache: Optional shared logo cache
            custom_logger: Optional custom logger
        """
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logging.getLogger(__name__)

        # Use provided logo cache or create new one
        self._logo_cache = logo_cache if logo_cache is not None else {}

        # Rankings cache (populated externally via set_rankings_cache)
        self._team_rankings_cache: Dict[str, int] = {}

        # Load fonts
        self.fonts = self._load_fonts()

    def _load_fonts(self):
        """Load fonts used by the renderer."""
        fonts = {}
        try:
            fonts['score'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            fonts['time'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['team'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['status'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['detail'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['rank'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            self.logger.debug("Successfully loaded fonts")
        except IOError:
            self.logger.warning("Fonts not found, using default PIL font.")
            fonts['score'] = ImageFont.load_default()
            fonts['time'] = ImageFont.load_default()
            fonts['team'] = ImageFont.load_default()
            fonts['status'] = ImageFont.load_default()
            fonts['detail'] = ImageFont.load_default()
            fonts['rank'] = ImageFont.load_default()
        return fonts

    def _get_logo_path(self, league: str, team_abbrev: str) -> Path:
        """Get the logo path for a team based on league."""
        if league == 'mlb':
            return Path("assets/sports/mlb_logos") / f"{team_abbrev}.png"
        elif league == 'milb':
            return Path("assets/sports/milb_logos") / f"{team_abbrev}.png"
        elif league == 'ncaa_baseball':
            return Path("assets/sports/ncaa_logos") / f"{team_abbrev}.png"
        else:
            return Path("assets/sports/mlb_logos") / f"{team_abbrev}.png"

    def _load_and_resize_logo(self, league: str, team_abbrev: str) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching."""
        cache_key = f"{league}_{team_abbrev}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        logo_path = self._get_logo_path(league, team_abbrev)

        if not logo_path.exists():
            self.logger.warning(f"Logo not found for {team_abbrev} at {logo_path}")
            return None

        try:
            with Image.open(logo_path) as logo:
                if logo.mode != 'RGBA':
                    logo = logo.convert('RGBA')

                # Resize logo to fit display
                max_width = int(self.display_width * 1.5)
                max_height = int(self.display_height * 1.5)
                logo.thumbnail((max_width, max_height), RESAMPLE_FILTER)

                # Copy before exiting context manager
                cached_logo = logo.copy()

            self._logo_cache[cache_key] = cached_logo
            return cached_logo

        except OSError:
            self.logger.exception(f"Error loading logo for {team_abbrev}")
            return None

    def _draw_text_with_outline(self, draw, text, position, font,
                               fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        """Set the team rankings cache for display."""
        self._team_rankings_cache = rankings

    def render_game_card(self, game: Dict, game_type: str) -> Image.Image:
        """
        Render a game card as a PIL Image.

        Args:
            game: Game dictionary
            game_type: Type of game ('live', 'recent', 'upcoming')

        Returns:
            PIL Image of the rendered game card
        """
        if game_type == 'live':
            return self._render_live_game(game)
        elif game_type == 'recent':
            return self._render_recent_game(game)
        elif game_type == 'upcoming':
            return self._render_upcoming_game(game)
        else:
            self.logger.error(f"Unknown game type: {game_type}")
            return self._render_error_card("Unknown type")

    def _render_live_game(self, game: Dict) -> Image.Image:
        """Render a live baseball game card with full scorebug elements."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos
            main_img.paste(home_logo, (self.display_width - home_logo.width, center_y - home_logo.height // 2), home_logo)
            main_img.paste(away_logo, (0, center_y - away_logo.height // 2), away_logo)

            # Inning indicator (top center)
            inning_half = game.get('inning_half', 'top')
            inning_num = game.get('inning', 1)
            if game.get('is_final'):
                inning_text = "FINAL"
            elif inning_half == 'end':
                inning_text = f"E{inning_num}"
            elif inning_half == 'mid':
                inning_text = f"M{inning_num}"
            else:
                symbol = "▲" if inning_half == 'top' else "▼"
                inning_text = f"{symbol}{inning_num}"

            inning_font = self.fonts['time']
            inning_bbox = draw.textbbox((0, 0), inning_text, font=inning_font)
            inning_width = inning_bbox[2] - inning_bbox[0]
            inning_x = (self.display_width - inning_width) // 2
            inning_y = 1
            self._draw_text_with_outline(draw, inning_text, (inning_x, inning_y), inning_font)

            # Bases diamond + Outs circles
            bases_occupied = game.get('bases_occupied', [False, False, False])
            outs = game.get('outs', 0)

            base_diamond_size = 7
            out_circle_diameter = 3
            out_vertical_spacing = 2
            spacing_between_bases_outs = 3
            base_vert_spacing = 1
            base_horiz_spacing = 1

            base_cluster_height = base_diamond_size + base_vert_spacing + base_diamond_size
            base_cluster_width = base_diamond_size + base_horiz_spacing + base_diamond_size

            overall_start_y = inning_bbox[3] + 1
            bases_origin_x = (self.display_width - base_cluster_width) // 2

            # Outs column position (only needed when count data is available)
            has_count_data = game.get('has_count_data', True)
            out_cluster_height = 3 * out_circle_diameter + 2 * out_vertical_spacing
            if has_count_data:
                if inning_half == 'top':
                    outs_column_x = bases_origin_x - spacing_between_bases_outs - out_circle_diameter
                else:
                    outs_column_x = bases_origin_x + base_cluster_width + spacing_between_bases_outs
                outs_column_start_y = overall_start_y + (base_cluster_height // 2) - (out_cluster_height // 2)

            # Draw bases as diamond polygons
            h_d = base_diamond_size // 2
            base_fill = (255, 255, 255)
            base_outline = (255, 255, 255)

            # 2nd base (top center)
            c2x = bases_origin_x + base_cluster_width // 2
            c2y = overall_start_y + h_d
            poly2 = [(c2x, overall_start_y), (c2x + h_d, c2y), (c2x, c2y + h_d), (c2x - h_d, c2y)]
            draw.polygon(poly2, fill=base_fill if bases_occupied[1] else None, outline=base_outline)

            base_bottom_y = c2y + h_d

            # 3rd base (bottom left)
            c3x = bases_origin_x + h_d
            c3y = base_bottom_y + base_vert_spacing + h_d
            poly3 = [(c3x, base_bottom_y + base_vert_spacing), (c3x + h_d, c3y), (c3x, c3y + h_d), (c3x - h_d, c3y)]
            draw.polygon(poly3, fill=base_fill if bases_occupied[2] else None, outline=base_outline)

            # 1st base (bottom right)
            c1x = bases_origin_x + base_cluster_width - h_d
            c1y = base_bottom_y + base_vert_spacing + h_d
            poly1 = [(c1x, base_bottom_y + base_vert_spacing), (c1x + h_d, c1y), (c1x, c1y + h_d), (c1x - h_d, c1y)]
            draw.polygon(poly1, fill=base_fill if bases_occupied[0] else None, outline=base_outline)

            # Outs circles (only when count data is available)
            if has_count_data:
                for i in range(3):
                    cx = outs_column_x
                    cy = outs_column_start_y + i * (out_circle_diameter + out_vertical_spacing)
                    coords = [cx, cy, cx + out_circle_diameter, cy + out_circle_diameter]
                    if i < outs:
                        draw.ellipse(coords, fill=(255, 255, 255))
                    else:
                        draw.ellipse(coords, outline=(100, 100, 100))

            # Balls-strikes count (below bases, only when count data is available)
            if has_count_data:
                balls = game.get('balls', 0)
                strikes = game.get('strikes', 0)
                count_text = f"{balls}-{strikes}"
                count_font = self.fonts['detail']
                count_width = draw.textlength(count_text, font=count_font)
                count_y = overall_start_y + base_cluster_height + 2
                count_x = bases_origin_x + (base_cluster_width - count_width) // 2
                self._draw_text_with_outline(draw, count_text, (int(count_x), count_y), count_font)

            # Team:Score at bottom corners
            score_font = self.fonts['score']
            away_text = f"{game.get('away_abbr', '')}:{game.get('away_score', '0')}"
            home_text = f"{game.get('home_abbr', '')}:{game.get('home_score', '0')}"
            try:
                font_height = score_font.getbbox("A")[3] - score_font.getbbox("A")[1]
            except AttributeError:
                font_height = 8
            score_y = self.display_height - font_height - 2
            self._draw_text_with_outline(draw, away_text, (2, score_y), score_font)
            try:
                home_w = draw.textbbox((0, 0), home_text, font=score_font)[2]
            except AttributeError:
                home_w = len(home_text) * 8
            self._draw_text_with_outline(draw, home_text, (self.display_width - home_w - 2, score_y), score_font)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(draw, game['odds'])

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering live game")
            return self._render_error_card("Display error")

    def _render_recent_game(self, game: Dict) -> Image.Image:
        """Render a recent baseball game card."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos (tighter fit for recent)
            main_img.paste(home_logo, (self.display_width - home_logo.width, center_y - home_logo.height // 2), home_logo)
            main_img.paste(away_logo, (0, center_y - away_logo.height // 2), away_logo)

            # "Final" (top center)
            status_text = "Final"
            status_width = draw.textlength(status_text, font=self.fonts['time'])
            self._draw_text_with_outline(draw, status_text, ((self.display_width - status_width) // 2, 1), self.fonts['time'])

            # Score (centered)
            score_text = f"{game.get('away_score', '0')}-{game.get('home_score', '0')}"
            score_width = draw.textlength(score_text, font=self.fonts['score'])
            score_x = (self.display_width - score_width) // 2
            score_y = self.display_height - 14
            self._draw_text_with_outline(draw, score_text, (score_x, score_y), self.fonts['score'], fill=(255, 200, 0))

            # Records at bottom corners
            self._draw_records(draw, game)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(draw, game['odds'])

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering recent game")
            return self._render_error_card("Display error")

    def _render_upcoming_game(self, game: Dict) -> Image.Image:
        """Render an upcoming baseball game card."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            league = game.get('league', 'mlb')
            home_logo = self._load_and_resize_logo(league, game.get('home_abbr', ''))
            away_logo = self._load_and_resize_logo(league, game.get('away_abbr', ''))

            if not home_logo or not away_logo:
                return self._render_error_card("Logo Error")

            center_y = self.display_height // 2

            # Logos (tighter fit)
            main_img.paste(home_logo, (self.display_width - home_logo.width, center_y - home_logo.height // 2), home_logo)
            main_img.paste(away_logo, (0, center_y - away_logo.height // 2), away_logo)

            # "Next Game" (top center)
            status_font = self.fonts['status'] if self.display_width <= 128 else self.fonts['time']
            status_text = "Next Game"
            status_width = draw.textlength(status_text, font=status_font)
            self._draw_text_with_outline(draw, status_text, ((self.display_width - status_width) // 2, 1), status_font)

            # Game time/date from start_time
            start_time = game.get('start_time', '')
            game_date = ''
            game_time = ''
            if start_time:
                try:
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    local_tz = pytz.timezone(self.config.get('timezone', 'US/Eastern'))
                    dt_local = dt.astimezone(local_tz)
                    game_date = dt_local.strftime('%b %d')
                    game_time = dt_local.strftime('%-I:%M %p')
                except (ValueError, AttributeError):
                    game_time = start_time[:10] if len(start_time) > 10 else start_time

            time_font = self.fonts['time']
            if game_date:
                date_width = draw.textlength(game_date, font=time_font)
                draw_y = center_y - 7
                self._draw_text_with_outline(draw, game_date, ((self.display_width - date_width) // 2, draw_y), time_font)
            if game_time:
                time_width = draw.textlength(game_time, font=time_font)
                draw_y = center_y + 2
                self._draw_text_with_outline(draw, game_time, ((self.display_width - time_width) // 2, draw_y), time_font)

            # Records at bottom corners
            self._draw_records(draw, game)

            # Odds
            if game.get('odds'):
                self._draw_dynamic_odds(draw, game['odds'])

            main_img = Image.alpha_composite(main_img, overlay)
            return main_img.convert("RGB")

        except Exception:
            self.logger.exception("Error rendering upcoming game")
            return self._render_error_card("Display error")

    def _get_team_display_text(self, abbr: str, record: str, show_records: bool, show_ranking: bool) -> str:
        """Get display text for a team (ranking or record)."""
        if show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            if not show_records:
                return ''
        if show_records:
            return record
        return ''

    def _draw_records(self, draw, game: Dict):
        """Draw team records or rankings at bottom corners if enabled by config."""
        league = game.get('league', 'mlb')
        league_config = self.config.get(league, {})
        display_options = league_config.get('display_options', {})
        show_records = display_options.get('show_records', self.config.get('show_records', False))
        show_ranking = display_options.get('show_ranking', self.config.get('show_ranking', False))

        if not show_records and not show_ranking:
            return

        record_font = self.fonts['detail']
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height

        # Away team (bottom left)
        away_text = self._get_team_display_text(
            game.get('away_abbr', ''), game.get('away_record', ''),
            show_records, show_ranking
        )
        if away_text:
            self._draw_text_with_outline(draw, away_text, (0, record_y), record_font)

        # Home team (bottom right)
        home_text = self._get_team_display_text(
            game.get('home_abbr', ''), game.get('home_record', ''),
            show_records, show_ranking
        )
        if home_text:
            home_bbox = draw.textbbox((0, 0), home_text, font=record_font)
            home_w = home_bbox[2] - home_bbox[0]
            self._draw_text_with_outline(draw, home_text, (self.display_width - home_w, record_y), record_font)

    def _draw_dynamic_odds(self, draw, odds: Dict) -> None:
        """Draw odds with dynamic positioning based on favored team."""
        try:
            if not odds:
                return

            home_team_odds = odds.get('home_team_odds', {})
            away_team_odds = odds.get('away_team_odds', {})
            home_spread = home_team_odds.get('spread_odds')
            away_spread = away_team_odds.get('spread_odds')

            # Get top-level spread as fallback (only when individual spread is truly missing)
            top_level_spread = odds.get('spread')
            if top_level_spread is not None:
                if home_spread is None:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = -top_level_spread

            # Determine favored team
            home_favored = isinstance(home_spread, (int, float)) and home_spread < 0
            away_favored = isinstance(away_spread, (int, float)) and away_spread < 0

            favored_spread = None
            favored_side = None

            if home_favored:
                favored_spread = home_spread
                favored_side = 'home'
            elif away_favored:
                favored_spread = away_spread
                favored_side = 'away'

            # Odds row below the status/inning text row
            status_bbox = draw.textbbox((0, 0), "A", font=self.fonts['time'])
            odds_y = status_bbox[3] + 2  # just below the status row

            # Show the negative spread on the appropriate side
            font = self.fonts['detail']
            if favored_spread is not None:
                spread_text = str(favored_spread)
                spread_width = draw.textlength(spread_text, font=font)
                if favored_side == 'home':
                    spread_x = self.display_width - spread_width
                else:
                    spread_x = 0
                self._draw_text_with_outline(draw, spread_text, (spread_x, odds_y), font, fill=(0, 255, 0))

            # Show over/under on opposite side
            over_under = odds.get('over_under')
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                ou_width = draw.textlength(ou_text, font=font)
                if favored_side == 'home':
                    ou_x = 0
                elif favored_side == 'away':
                    ou_x = self.display_width - ou_width
                else:
                    ou_x = (self.display_width - ou_width) // 2
                self._draw_text_with_outline(draw, ou_text, (ou_x, odds_y), font, fill=(0, 255, 0))

        except Exception:
            self.logger.exception("Error drawing odds")

    def _render_error_card(self, message: str) -> Image.Image:
        """Render an error message card."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_text_with_outline(draw, message, (5, 5), self.fonts['status'])
        return img
