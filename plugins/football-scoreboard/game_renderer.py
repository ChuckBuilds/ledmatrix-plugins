"""
Game Renderer for Football Scoreboard Plugin

Extracts game rendering logic into a reusable component that can be used by both
switch mode (one game at a time) and scroll mode (all games scrolling horizontally).

This module provides:
- GameRenderer class for rendering individual game cards as PIL Images
- Pre-loading of team logos for performance
- Support for live, recent, and upcoming game layouts
- Consistent rendering across all display modes
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont
try:
    import freetype
    FREETYPE_AVAILABLE = True
except ImportError:
    FREETYPE_AVAILABLE = False

logger = logging.getLogger(__name__)


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
        
        # Display options are read dynamically per league (stored in config under league.display_options)
        # These defaults are kept for backward compatibility but should not be used
        self._default_show_odds = config.get("show_odds", False)
        self._default_show_records = config.get("show_records", False)
        self._default_show_ranking = config.get("show_ranking", False)
        
        # Rankings cache (populated externally)
        self._team_rankings_cache: Dict[str, int] = {}
        
    def _load_fonts(self) -> Dict[str, Union[ImageFont.FreeTypeFont, Any]]:
        """
        Load fonts used by the scoreboard from config or use defaults.
        
        Returns:
            Dictionary mapping font names to font objects (ImageFont.FreeTypeFont for TTF/OTF,
            freetype.Face for BDF fonts)
        """
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
            self.logger.error(f"Error loading fonts: {e}, using defaults")
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
    
    def _load_custom_font(self, element_config: Dict[str, Any], default_size: int = 8, default_font: str = 'PressStart2P-Regular.ttf') -> Union[ImageFont.FreeTypeFont, Any]:
        """
        Load a custom font from an element configuration dictionary.
        
        Supports TTF/OTF fonts via ImageFont.truetype() and BDF fonts via freetype.Face().
        
        Returns:
            ImageFont.FreeTypeFont for TTF/OTF fonts, freetype.Face for BDF fonts, or fallback font
        """
        font_name = element_config.get('font', default_font)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)
        
        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf') or font_path.lower().endswith('.otf'):
                    # TTF/OTF fonts - use ImageFont.truetype()
                    return ImageFont.truetype(font_path, font_size)
                elif font_path.lower().endswith('.bdf'):
                    # BDF fonts - ImageFont.truetype() does NOT support BDF files
                    # Option (b): Try to load pre-converted .pil/.pbm file (recommended approach)
                    # Use pilfont.py to convert: pilfont.py font.bdf (creates font.pil and font.pbm)
                    pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                    if os.path.exists(pil_font_path):
                        try:
                            font = ImageFont.load(pil_font_path)
                            self.logger.debug(f"Loaded BDF font from pre-converted PIL file: {pil_font_path}")
                            return font
                        except Exception as e:
                            # Pre-converted file exists but failed to load - will fall through to fallback
                            pass
                    
                    # If no pre-converted file or loading failed, BDF cannot be loaded directly
                    # Note: PIL.BdfFontFile doesn't exist in standard Pillow, so pre-conversion is required
                    # The warning will be logged only if fallback also fails (see below)
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, trying fallback")
            else:
                self.logger.warning(f"Font file not found: {font_path}, trying fallback")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, trying fallback")
        
        # Fallback to default font
        default_font_path = os.path.join('assets', 'fonts', default_font)
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
        except Exception as e:
            # Default font also failed - log clear warning about BDF handling failure if this was a BDF font
            if font_path.lower().endswith('.bdf'):
                pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                self.logger.warning(
                    f"BDF font loading failed for {font_name}: "
                    f"No pre-converted .pil file found at {pil_font_path}. "
                    f"Convert BDF to PIL format using: pilfont.py {font_path}. "
                    f"Default font fallback also failed: {e}. Using PIL default font."
                )
            else:
                self.logger.warning(f"Could not load default font: {e}, using PIL default font")
        
        # Final fallback - only log warning for BDF fonts if we haven't already warned above
        if font_path.lower().endswith('.bdf'):
            # Check if we already logged a warning (if default font path didn't exist, we need to warn here)
            if not os.path.exists(default_font_path):
                pil_font_path = font_path.rsplit('.', 1)[0] + '.pil'
                self.logger.warning(
                    f"BDF font {font_name} could not be loaded (no pre-converted .pil file found at {pil_font_path}). "
                    f"Using PIL default font. To fix: run 'pilfont.py {font_path}' to create {pil_font_path}"
                )
        
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
            for team_key in ['home_abbr', 'away_abbr']:
                abbr = game.get(team_key, '')
                if abbr and abbr not in self._logo_cache:
                    logo_path = game.get(f'{team_key.replace("abbr", "logo_path")}')
                    if logo_path:
                        logo = self._load_and_resize_logo(
                            game.get(team_key.replace('abbr', 'id'), ''),
                            abbr,
                            logo_path,
                            game.get(f'{team_key.replace("abbr", "logo_url")}')
                        )
                        if logo:
                            self._logo_cache[abbr] = logo
        
        self.logger.debug(f"Preloaded {len(self._logo_cache)} team logos")
    
    def _load_and_resize_logo(
        self, 
        team_id: str, 
        team_abbrev: str, 
        logo_path: Path, 
        logo_url: Optional[str] = None
    ) -> Optional[Image.Image]:
        """Load and resize a team logo with caching."""
        if team_abbrev in self._logo_cache:
            return self._logo_cache[team_abbrev]
        
        try:
            # Try to load from path
            if os.path.exists(logo_path):
                logo = Image.open(logo_path)
                if logo.mode != "RGBA":
                    logo = logo.convert("RGBA")
                
                # Resize to fit display
                max_width = int(self.display_width * 1.5)
                max_height = int(self.display_height * 1.5)
                logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                
                self._logo_cache[team_abbrev] = logo
                return logo
            else:
                self.logger.debug(f"Logo not found at {logo_path}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}")
            return None
    
    def _draw_text_with_outline(
        self, 
        draw: ImageDraw.Draw, 
        text: str, 
        position: Tuple[int, int], 
        font: Union[ImageFont.FreeTypeFont, Any], 
        fill: Tuple[int, int, int] = (255, 255, 255), 
        outline_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        """
        Draw text with a black outline for better readability.
        
        Note: BDF fonts loaded via freetype.Face() are not directly compatible with
        ImageDraw.text(). If a BDF font is passed, it will fall back to default font.
        """
        # Check if this is a freetype.Face (BDF font) - ImageDraw.text() doesn't support it
        if FREETYPE_AVAILABLE and hasattr(font, 'set_char_size'):
            # This is a freetype.Face (BDF font) - ImageDraw.text() won't work
            # Fall back to default font for rendering
            self.logger.warning(f"BDF font detected but ImageDraw.text() doesn't support freetype.Face - using default font for rendering")
            font = ImageFont.load_default()
        
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
        
        # Load logos
        home_logo = self._load_and_resize_logo(
            game.get("home_id", ""),
            game.get("home_abbr", ""),
            game.get("home_logo_path"),
            game.get("home_logo_url")
        )
        away_logo = self._load_and_resize_logo(
            game.get("away_id", ""),
            game.get("away_abbr", ""),
            game.get("away_logo_path"),
            game.get("away_logo_url")
        )
        
        if not home_logo or not away_logo:
            # Draw placeholder text if logos fail
            draw = ImageDraw.Draw(main_img)
            self._draw_text_with_outline(
                draw, 
                f"{game.get('away_abbr', '?')}@{game.get('home_abbr', '?')}", 
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
        
        # Get display options for this game's league
        game_league = game.get("league", "nfl")
        show_odds = self._get_display_option(game_league, "show_odds")
        show_records = self._get_display_option(game_league, "show_records")
        show_ranking = self._get_display_option(game_league, "show_ranking")
        
        # Draw odds if enabled
        if show_odds and 'odds' in game and game['odds']:
            self._draw_dynamic_odds(draw_overlay, game['odds'])
        
        # Draw records or rankings if enabled
        if show_records or show_ranking:
            self._draw_records_or_rankings(draw_overlay, game, show_records, show_ranking)
        
        # Composite the overlay onto main image
        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert('RGB')
    
    def _draw_live_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a live game."""
        # Period/Quarter and Clock (Top center)
        period_clock_text = f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
        if game.get("is_halftime"):
            period_clock_text = "Halftime"
        elif game.get("is_period_break"):
            period_clock_text = game.get("status_text", "Period Break")
        
        status_width = draw.textlength(period_clock_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_clock_text, (status_x, status_y), self.fonts['time'])
        
        # Down & Distance or Scoring Event (Bottom center)
        scoring_event = game.get("scoring_event", "")
        down_distance = game.get("down_distance_text", "")
        if self.display_width > 128:
            down_distance = game.get("down_distance_text_long", down_distance)
        
        if scoring_event and game.get("is_live"):
            # Display scoring event with special formatting
            event_width = draw.textlength(scoring_event, font=self.fonts['detail'])
            event_x = (self.display_width - event_width) // 2
            event_y = self.display_height - 7
            
            # Color coding for different scoring events
            if scoring_event == "TOUCHDOWN":
                event_color = (255, 215, 0)  # Gold
            elif scoring_event == "FIELD GOAL":
                event_color = (0, 255, 0)    # Green
            elif scoring_event == "PAT":
                event_color = (255, 165, 0)  # Orange
            else:
                event_color = (255, 255, 255)  # White
            
            self._draw_text_with_outline(draw, scoring_event, (event_x, event_y), self.fonts['detail'], fill=event_color)
        elif down_distance and game.get("is_live"):
            dd_width = draw.textlength(down_distance, font=self.fonts['detail'])
            dd_x = (self.display_width - dd_width) // 2
            dd_y = self.display_height - 7
            down_color = (200, 200, 0) if not game.get("is_redzone", False) else (255, 0, 0)
            self._draw_text_with_outline(draw, down_distance, (dd_x, dd_y), self.fonts['detail'], fill=down_color)
            
            # Possession indicator
            self._draw_possession_indicator(draw, game, dd_x, dd_width, dd_y)
        
        # Timeouts
        self._draw_timeouts(draw, game)
    
    def _draw_recent_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for a recently completed game."""
        # Final status (Top center)
        period_text = game.get("period_text", "Final")
        if not period_text:
            period_text = "Final"
        status_width = draw.textlength(period_text, font=self.fonts['time'])
        status_x = (self.display_width - status_width) // 2
        status_y = 1
        self._draw_text_with_outline(draw, period_text, (status_x, status_y), self.fonts['time'])
        
        # Game date (Bottom center)
        game_date = game.get("game_date", "")
        if game_date:
            date_width = draw.textlength(game_date, font=self.fonts['detail'])
            date_x = (self.display_width - date_width) // 2
            date_y = self.display_height - 7
            self._draw_text_with_outline(draw, game_date, (date_x, date_y), self.fonts['detail'])
    
    def _draw_upcoming_game_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw status elements for an upcoming game."""
        # Game time (Top center)
        game_time = game.get("game_time", "")
        if game_time:
            time_width = draw.textlength(game_time, font=self.fonts['time'])
            time_x = (self.display_width - time_width) // 2
            time_y = 1
            self._draw_text_with_outline(draw, game_time, (time_x, time_y), self.fonts['time'])
        
        # Game date (Bottom center)
        game_date = game.get("game_date", "")
        if game_date:
            date_width = draw.textlength(game_date, font=self.fonts['detail'])
            date_x = (self.display_width - date_width) // 2
            date_y = self.display_height - 7
            self._draw_text_with_outline(draw, game_date, (date_x, date_y), self.fonts['detail'])
    
    def _draw_possession_indicator(
        self, 
        draw: ImageDraw.Draw, 
        game: Dict, 
        dd_x: int, 
        dd_width: float, 
        dd_y: int
    ) -> None:
        """Draw the possession football indicator."""
        possession = game.get("possession_indicator")
        if not possession:
            return
        
        ball_radius_x = 3
        ball_radius_y = 2
        ball_color = (139, 69, 19)  # Brown
        lace_color = (255, 255, 255)  # White
        
        detail_font_height_approx = 6
        ball_y_center = dd_y + (detail_font_height_approx // 2)
        possession_ball_padding = 3
        
        if possession == "away":
            ball_x_center = dd_x - possession_ball_padding - ball_radius_x
        elif possession == "home":
            ball_x_center = dd_x + int(dd_width) + possession_ball_padding + ball_radius_x
        else:
            return
        
        if ball_x_center > 0:
            # Draw football shape (ellipse)
            draw.ellipse(
                (ball_x_center - ball_radius_x, ball_y_center - ball_radius_y,
                 ball_x_center + ball_radius_x, ball_y_center + ball_radius_y),
                fill=ball_color, outline=(0, 0, 0)
            )
            # Draw simple horizontal lace
            draw.line(
                (ball_x_center - 1, ball_y_center, ball_x_center + 1, ball_y_center),
                fill=lace_color, width=1
            )
    
    def _draw_timeouts(self, draw: ImageDraw.Draw, game: Dict) -> None:
        """Draw timeout indicators at bottom corners."""
        timeout_bar_width = 4
        timeout_bar_height = 2
        timeout_spacing = 1
        timeout_y = self.display_height - timeout_bar_height - 1
        
        # Away Timeouts (Bottom Left)
        away_timeouts_remaining = game.get("away_timeouts", 0)
        for i in range(3):
            to_x = 2 + i * (timeout_bar_width + timeout_spacing)
            color = (255, 255, 255) if i < away_timeouts_remaining else (80, 80, 80)
            draw.rectangle(
                [to_x, timeout_y, to_x + timeout_bar_width, timeout_y + timeout_bar_height],
                fill=color, outline=(0, 0, 0)
            )
        
        # Home Timeouts (Bottom Right)
        home_timeouts_remaining = game.get("home_timeouts", 0)
        for i in range(3):
            to_x = self.display_width - 2 - timeout_bar_width - (2 - i) * (timeout_bar_width + timeout_spacing)
            color = (255, 255, 255) if i < home_timeouts_remaining else (80, 80, 80)
            draw.rectangle(
                [to_x, timeout_y, to_x + timeout_bar_width, timeout_y + timeout_bar_height],
                fill=color, outline=(0, 0, 0)
            )
    
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
            self.logger.error(f"Error drawing odds: {e}")
    
    def _get_display_option(self, league: str, option: str) -> bool:
        """
        Get a display option for a specific league from the nested config structure.
        
        Args:
            league: League identifier ('nfl', 'ncaa_fb', etc.)
            option: Option name ('show_odds', 'show_records', 'show_ranking')
            
        Returns:
            Boolean value of the option, or False if not found
        """
        # Read from nested path: config[league]["display_options"][option]
        league_config = self.config.get(league, {})
        display_options = league_config.get("display_options", {})
        value = display_options.get(option, False)
        
        # Fallback to root-level config for backward compatibility
        if value is False and option in self.config:
            value = self.config.get(option, False)
        
        return bool(value)
    
    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict, show_records: bool, show_ranking: bool) -> None:
        """Draw team records or rankings."""
        try:
            record_font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
        except IOError:
            record_font = ImageFont.load_default()
        
        away_abbr = game.get('away_abbr', '')
        home_abbr = game.get('home_abbr', '')
        
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - 4
        
        # Away team info
        if away_abbr:
            away_text = self._get_team_display_text(away_abbr, game.get('away_record', ''), show_records, show_ranking)
            if away_text:
                away_record_x = 3
                self._draw_text_with_outline(draw, away_text, (away_record_x, record_y), record_font)
        
        # Home team info
        if home_abbr:
            home_text = self._get_team_display_text(home_abbr, game.get('home_record', ''), show_records, show_ranking)
            if home_text:
                home_record_bbox = draw.textbbox((0, 0), home_text, font=record_font)
                home_record_width = home_record_bbox[2] - home_record_bbox[0]
                home_record_x = self.display_width - home_record_width - 3
                self._draw_text_with_outline(draw, home_text, (home_record_x, record_y), record_font)
    
    def _get_team_display_text(self, abbr: str, record: str, show_records: bool, show_ranking: bool) -> str:
        """Get the display text for a team (ranking or record)."""
        if show_ranking and show_records:
            # Rankings replace records when both are enabled
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ''
        elif show_records:
            return record
        return ''




