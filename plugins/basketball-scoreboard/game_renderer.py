"""
Game Renderer for Basketball Scoreboard Plugin

Extracts game rendering logic into a reusable component for scroll display mode.
Returns PIL Images instead of updating display directly.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class GameRenderer:
    """
    Renders individual game cards as PIL Images for display.
    
    This class extracts the rendering logic from the sports manager classes
    to provide a reusable component for both switch and scroll display modes.
    """
    
    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict[str, Any],
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the GameRenderer.
        
        Args:
            display_width: Width of the display/game card
            display_height: Height of the display/game card
            config: Configuration dictionary
            logo_cache: Optional shared logo cache dictionary
            custom_logger: Optional custom logger instance
        """
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logger
        
        # Shared logo cache for performance
        self._logo_cache = logo_cache if logo_cache is not None else {}
        
        # Load fonts
        self.fonts = self._load_fonts()
        
        # Get logo directories from config
        self.logo_dirs = {
            'nba': config.get('nba', {}).get('logo_dir', 'assets/sports/nba_logos'),
            'wnba': config.get('wnba', {}).get('logo_dir', 'assets/sports/wnba_logos'),
            'ncaam': config.get('ncaam', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
            'ncaaw': config.get('ncaaw', {}).get('logo_dir', 'assets/sports/ncaa_logos'),
        }
        
        # Display options - check per-league display_options in config
        # The config structure is: config[league].display_options.show_records/show_ranking
        # Enable if ANY enabled league has the option enabled
        self.show_records = False
        self.show_ranking = False
        for league_key in ('nba', 'wnba', 'ncaam', 'ncaaw'):
            league_config = config.get(league_key, {})
            if league_config.get('enabled', False):
                display_options = league_config.get('display_options', {})
                if display_options.get('show_records', False):
                    self.show_records = True
                if display_options.get('show_ranking', False):
                    self.show_ranking = True
        
        # Rankings cache (populated externally)
        self._team_rankings_cache: Dict[str, int] = {}
        
    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}
        
        # Get customization config
        customization = self.config.get('customization', {})
        
        # Load fonts from config with defaults for backward compatibility
        score_config = customization.get('score_text', {})
        period_config = customization.get('period_text', {})
        team_config = customization.get('team_name', {})
        status_config = customization.get('status_text', {})
        detail_config = customization.get('detail_text', {})
        rank_config = customization.get('rank_text', {})
        
        try:
            fonts["score"] = self._load_custom_font(score_config, default_size=10)
            fonts["time"] = self._load_custom_font(period_config, default_size=8)
            fonts["team"] = self._load_custom_font(team_config, default_size=8)
            fonts["status"] = self._load_custom_font(status_config, default_size=6)
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6, default_font='4x6-font.ttf')
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10)
            self.logger.debug("Successfully loaded fonts from config")
        except Exception as e:
            self.logger.exception("Error loading fonts, using defaults")
            # Fallback to hardcoded defaults
            try:
                fonts["score"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
                fonts["time"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["team"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["status"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["detail"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["rank"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            except IOError:
                self.logger.warning("Fonts not found, using default PIL font.")
                default_font = ImageFont.load_default()
                fonts = {k: default_font for k in ["score", "time", "team", "status", "detail", "rank"]}
        
        return fonts
    
    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf') -> ImageFont.FreeTypeFont:
        """Load a custom font from an element configuration dictionary."""
        font_name = element_config.get('font', default_font)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)
        
        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf'):
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    try:
                        return ImageFont.truetype(font_path, font_size)
                    except Exception:
                        self.logger.warning(f"Could not load BDF font {font_name}, using default")
        except Exception as e:
            self.logger.exception(f"Error loading font {font_name}")
        
        # Fallback to default font
        default_font_path = os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf')
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception:
            pass
        
        return ImageFont.load_default()
    
    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        """Set the team rankings cache for display."""
        self._team_rankings_cache = rankings
    
    def preload_logos(self, games: list, logo_dir: Path) -> None:
        """
        Pre-load team logos for all games to improve scroll performance.
        
        Args:
            games: List of game dictionaries
            logo_dir: Path to logo directory
        """
        for game in games:
            league = game.get('league', 'nba')
            for team_key in ['home_abbr', 'away_abbr']:
                abbr = game.get(team_key, '')
                if abbr:
                    # Use league+abbrev as cache key to avoid cross-league collisions
                    cache_key = f"{league}:{abbr}"
                    if cache_key not in self._logo_cache:
                        logo_path = game.get(f'{team_key.replace("abbr", "logo_path")}', '')
                        if logo_path:
                            logo = self._load_and_resize_logo(abbr, logo_path, league)
                            if logo:
                                self._logo_cache[cache_key] = logo
        
        self.logger.debug(f"Preloaded {len(self._logo_cache)} team logos")
    
    def _load_and_resize_logo(
        self, 
        team_abbrev: str, 
        logo_path: Path, 
        league: str = 'nba'
    ) -> Optional[Image.Image]:
        """
        Load and resize a team logo with caching.
        
        Args:
            team_abbrev: Team abbreviation (e.g., 'LAL', 'GSW')
            logo_path: Path to the logo file
            league: League identifier (e.g., 'nba', 'wnba', 'ncaam', 'ncaaw')
            
        Returns:
            PIL Image of the logo, or None if loading failed
        """
        # Use league+abbrev as cache key to avoid cross-league collisions
        cache_key = f"{league}:{team_abbrev}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]
        
        try:
            # Try to load from path
            if logo_path and os.path.exists(logo_path):
                with Image.open(logo_path) as img:
                    if img.mode != "RGBA":
                        img = img.convert("RGBA")

                    # Resize to fit display
                    max_width = int(self.display_width * 1.5)
                    max_height = int(self.display_height * 1.5)
                    img.thumbnail((max_width, max_height), resample=RESAMPLE_FILTER)

                    # Copy before context manager closes file handle
                    logo = img.copy()

                self._logo_cache[cache_key] = logo
                return logo
            else:
                # Try to load from league-specific logo directory
                logo_dir = Path(self.logo_dirs.get(league, 'assets/sports/nba_logos'))
                logo_file = logo_dir / f"{team_abbrev}.png"
                if logo_file.exists():
                    with Image.open(logo_file) as img:
                        if img.mode != "RGBA":
                            img = img.convert("RGBA")

                        max_width = int(self.display_width * 1.5)
                        max_height = int(self.display_height * 1.5)
                        img.thumbnail((max_width, max_height), resample=RESAMPLE_FILTER)

                        # Copy before context manager closes file handle
                        logo = img.copy()

                    self._logo_cache[cache_key] = logo
                    return logo
                else:
                    self.logger.debug(f"Logo not found at {logo_path} or {logo_file}")
                    return None

        except Exception as e:
            self.logger.exception(f"Error loading logo for {team_abbrev} (league: {league})")
            return None
    
    def _draw_text_with_outline(
        self, 
        draw: ImageDraw.Draw, 
        text: str, 
        position: Tuple[int, int], 
        font: ImageFont.FreeTypeFont, 
        fill: Tuple[int, int, int] = (255, 255, 255), 
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """Draw text with a black outline for better readability."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)
    
    def render_game_card(
        self, 
        game: Dict[str, Any], 
        game_type: str = "live"
    ) -> Image.Image:
        """
        Render a single game card as a PIL Image.
        
        Args:
            game: Game dictionary with team info, scores, status, etc.
            game_type: Type of game - 'live', 'recent', or 'upcoming'
            
        Returns:
            PIL Image of the rendered game card
        """
        # Create base image
        main_img = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (self.display_width, self.display_height), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        # Get league for logo directory
        league = game.get('league', 'nba')
        logo_dir = Path(self.logo_dirs.get(league, 'assets/sports/nba_logos'))
        
        # Get team info - support flat format from sports.py game dicts
        home_abbr = game.get('home_abbr', '')
        away_abbr = game.get('away_abbr', '')

        # Get logo paths from game data, otherwise construct from logo_dir
        home_logo_path = game.get('home_logo_path', logo_dir / f"{home_abbr}.png")
        away_logo_path = game.get('away_logo_path', logo_dir / f"{away_abbr}.png")
        
        # Load logos (using league+abbrev for cache key)
        home_logo = self._load_and_resize_logo(
            home_abbr,
            home_logo_path,
            league
        )
        away_logo = self._load_and_resize_logo(
            away_abbr,
            away_logo_path,
            league
        )
        
        if not home_logo or not away_logo:
            # Draw placeholder text if logos fail
            draw = ImageDraw.Draw(main_img)
            self._draw_text_with_outline(
                draw, 
                f"{away_abbr or '?'}@{home_abbr or '?'}", 
                (5, 5), 
                self.fonts['status']
            )
            return main_img.convert('RGB')
        
        center_y = self.display_height // 2
        
        # Draw logos
        home_x = self.display_width - home_logo.width
        home_y = center_y - (home_logo.height // 2)
        main_img.paste(home_logo, (home_x, home_y), home_logo)

        away_x = 0
        away_y = center_y - (away_logo.height // 2)
        main_img.paste(away_logo, (away_x, away_y), away_logo)
        
        # Draw scores (centered)
        home_score = str(game.get("home_score", "0"))
        away_score = str(game.get("away_score", "0"))
        score_text = f"{away_score}-{home_score}"
        score_width = draw_overlay.textlength(score_text, font=self.fonts['score'])
        score_x = (self.display_width - score_width) // 2
        score_y = (self.display_height // 2) - 3
        self._draw_text_with_outline(draw_overlay, score_text, (score_x, score_y), self.fonts['score'])
        
        # Draw period/status based on game type
        if game_type == "live":
            self._draw_live_game_status(draw_overlay, game)
        elif game_type == "recent":
            self._draw_recent_game_status(draw_overlay, game)
        elif game_type == "upcoming":
            self._draw_upcoming_game_status(draw_overlay, game)
        
        # Draw records or rankings if enabled
        if self.show_records or self.show_ranking:
            self._draw_records_or_rankings(draw_overlay, game)
        
        # Composite the overlay onto main image
        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')
    
    def _draw_live_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a live basketball game."""
        # Period and Clock (Top center) - use flat game dict format from sports.py
        period_text = game.get('period_text', '')
        clock = game.get('clock', '')

        if game.get('is_halftime'):
            period_clock_text = "Halftime"
        elif period_text and clock:
            period_clock_text = f"{period_text} {clock}".strip()
        else:
            period_clock_text = game.get('status_text', '')
        
        status_width = draw.textlength(period_clock_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_clock_text, (status_x, status_y), self.fonts['time'])
    
    def _draw_recent_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a recently completed basketball game."""
        # Final status (Top center)
        status_text = "Final"
        status_width = draw.textlength(status_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, status_text, (status_x, status_y), self.fonts['time'])
        
        # Game date (Bottom center)
        game_date = game.get("game_date", "")
        if game_date:
            date_width = draw.textlength(game_date, font=self.fonts['detail'])
            date_x = (self.display_width - date_width) // 2
            date_y = self.display_height - 7
            self._draw_text_with_outline(draw, game_date, (date_x, date_y), self.fonts['detail'])
    
    def _draw_upcoming_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for an upcoming basketball game."""
        # Next Game text (Top center)
        status_text = "Next Game"
        status_font = self.fonts['status']
        if self.display_width > 128:
            status_font = self.fonts['time']
        status_width = draw.textlength(status_text, font=status_font)
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, status_text, (status_x, status_y), status_font)

        # Game date and time - use flat format from sports.py
        game_date = game.get("game_date", "")
        game_time = game.get("game_time", "")

        if game_date:
            date_width = draw.textlength(game_date, font=self.fonts['time'])
            date_x = (self.display_width - date_width) // 2
            date_y = (self.display_height // 2) - 7
            self._draw_text_with_outline(draw, game_date, (date_x, date_y), self.fonts['time'])

        if game_time:
            time_width = draw.textlength(game_time, font=self.fonts['time'])
            time_x = (self.display_width - time_width) // 2
            time_y = (self.display_height // 2) - 7 + 9
            self._draw_text_with_outline(draw, game_time, (time_x, time_y), self.fonts['time'])
    
    def _draw_dynamic_odds(self, draw: ImageDraw.Draw, odds: Dict[str, Any]) -> None:
        """Draw odds with dynamic positioning."""
        try:
            if not odds:
                return
            
            home_team_odds = odds.get("home_team_odds", {})
            away_team_odds = odds.get("away_team_odds", {})
            home_spread = home_team_odds.get("spread_odds")
            away_spread = away_team_odds.get("spread_odds")
            
            # Get top-level spread as fallback
            top_level_spread = odds.get("spread")
            if top_level_spread is not None:
                if home_spread is None or home_spread == 0.0:
                    home_spread = top_level_spread
                if away_spread is None:
                    away_spread = -top_level_spread
            
            # Determine favored team
            home_favored = home_spread is not None and isinstance(home_spread, (int, float)) and home_spread < 0
            away_favored = away_spread is not None and isinstance(away_spread, (int, float)) and away_spread < 0
            
            favored_spread = None
            favored_side = None
            
            if home_favored:
                favored_spread = home_spread
                favored_side = "home"
            elif away_favored:
                favored_spread = away_spread
                favored_side = "away"
            
            # Show the negative spread
            if favored_spread is not None:
                spread_text = str(favored_spread)
                font = self.fonts["detail"]
                
                if favored_side == "home":
                    spread_width = draw.textlength(spread_text, font=font)
                    spread_x = self.display_width - spread_width
                    spread_y = 0
                else:
                    spread_x = 0
                    spread_y = 0
                
                self._draw_text_with_outline(draw, spread_text, (spread_x, spread_y), font, fill=(0, 255, 0))
            
            # Show over/under on opposite side
            over_under = odds.get("over_under")
            if over_under is not None and isinstance(over_under, (int, float)):
                ou_text = f"O/U: {over_under}"
                font = self.fonts["detail"]
                ou_width = draw.textlength(ou_text, font=font)
                
                if favored_side == "home":
                    ou_x = 0
                elif favored_side == "away":
                    ou_x = self.display_width - ou_width
                else:
                    ou_x = (self.display_width - ou_width) // 2
                ou_y = 0
                
                self._draw_text_with_outline(draw, ou_text, (ou_x, ou_y), font, fill=(0, 255, 0))
                
        except Exception as e:
            self.logger.exception("Error drawing odds")
    
    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw team records or rankings."""
        try:
            record_font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
        except IOError:
            record_font = ImageFont.load_default()
        
        # Get team info - support both flat format (from sports.py) and nested format
        away_abbr = game.get('away_abbr', '')
        home_abbr = game.get('home_abbr', '')
        away_record = game.get('away_record', '')
        home_record = game.get('home_record', '')
        
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - 4
        
        # Away team info
        if away_abbr:
            away_text = self._get_team_display_text(away_abbr, away_record)
            if away_text:
                away_record_x = 3
                self._draw_text_with_outline(draw, away_text, (away_record_x, record_y), record_font)
        
        # Home team info
        if home_abbr:
            home_text = self._get_team_display_text(home_abbr, home_record)
            if home_text:
                home_record_bbox = draw.textbbox((0, 0), home_text, font=record_font)
                home_record_width = home_record_bbox[2] - home_record_bbox[0]
                home_record_x = self.display_width - home_record_width - 3
                self._draw_text_with_outline(draw, home_text, (home_record_x, record_y), record_font)
    
    def _get_team_display_text(self, abbr: str, record: str) -> str:
        """Get the display text for a team (ranking or record)."""
        if self.show_ranking and self.show_records:
            # Rankings take priority when both are enabled, fall back to record
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return record
        elif self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif self.show_records:
            return record
        return ''




