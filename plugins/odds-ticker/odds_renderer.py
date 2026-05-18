"""
Odds Renderer for Odds Ticker Plugin

Handles rendering of odds data into scrolling ticker display.
Manages scrolling animation, text rendering, and display formatting.

Features:
- Scrolling ticker animation
- Multi-font text rendering
- Broadcast channel logos
- Dynamic duration calculation
- Performance optimization
"""

import time
import logging
import os
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

logger = logging.getLogger(__name__)


class OddsRenderer:
    """Handles rendering of odds data into scrolling ticker display."""
    
    # Broadcast logo mapping for channel logos
    BROADCAST_LOGO_MAP = {
        "ACC Network": "accn",
        "ACCN": "accn",
        "ABC": "abc",
        "BTN": "btn",
        "CBS": "cbs",
        "CBSSN": "cbssn",
        "CBS Sports Network": "cbssn",
        "ESPN": "espn",
        "ESPN2": "espn2",
        "ESPN3": "espn3",
        "ESPNU": "espnu",
        "ESPNEWS": "espn",
        "ESPN+": "espn",
        "ESPN Plus": "espn",
        "FOX": "fox",
        "FS1": "fs1",
        "FS2": "fs2",
        "MLBN": "mlbn",
        "MLB Network": "mlbn",
        "MLB.TV": "mlbn",
        "NBC": "nbc",
        "NFLN": "nfln",
        "NFL Network": "nfln",
        "PAC12": "pac12n",
        "Pac-12 Network": "pac12n",
        "SECN": "espn-sec-us",
        "TBS": "tbs",
        "TNT": "tnt",
        "truTV": "tru",
        "Peacock": "nbc",
        "Paramount+": "cbs",
        "Hulu": "espn",
        "Disney+": "espn",
        "Apple TV+": "nbc",
        # Regional sports networks
        "MASN": "cbs",
        "MASN2": "cbs",
        "MAS+": "cbs",
        "SportsNet": "nbc",
        "FanDuel SN": "fox",
        "FanDuel SN DET": "fox",
        "FanDuel SN FL": "fox",
        "SportsNet PIT": "nbc",
        "Padres.TV": "espn",
        "CLEGuardians.TV": "espn"
    }
    
    def __init__(self, display_manager, config: Dict[str, Any]):
        """Initialize the odds renderer."""
        self.display_manager = display_manager
        self.config = config
        
        # Resolve project root path (plugin_dir -> plugins -> project_root)
        self.project_root = Path(__file__).resolve().parent.parent.parent
        
        # Display settings
        self.scroll_speed = config.get('scroll_speed', 2)
        self.scroll_delay = config.get('scroll_delay', 0.05)
        self.scroll_pixels_per_second = config.get('scroll_pixels_per_second', 18.0)
        self.loop = config.get('loop', True)
        self.show_channel_logos = config.get('show_channel_logos', True)
        self.broadcast_logo_height_ratio = config.get('broadcast_logo_height_ratio', 0.8)
        self.broadcast_logo_max_width_ratio = config.get('broadcast_logo_max_width_ratio', 0.8)

        # Dynamic duration settings
        self.dynamic_duration_enabled = config.get('dynamic_duration', True)
        self.min_duration = config.get('min_duration', 30)
        self.max_duration = config.get('max_duration', 300)
        self.duration_buffer = config.get('duration_buffer', 0.1)
        
        # State variables
        self.scroll_position = 0
        self.last_scroll_time = 0
        self.ticker_image = None
        self.total_scroll_width = 0
        self.dynamic_duration = 60
        self._end_reached_logged = False
        self._insufficient_time_warning_logged = False
        self._display_start_time = None
        
        # Font setup
        self.fonts = self._load_fonts()
        
        logger.info("OddsRenderer initialized")
    
    def _load_custom_font_from_element_config(self, element_config: Dict[str, Any], default_size: int = 8, default_font_name: str = 'PressStart2P-Regular.ttf'):
        """
        Load a custom font from an element configuration dictionary.
        
        Args:
            element_config: Configuration dict for a single element containing 'font' and 'font_size' keys
            default_size: Default font size if not specified in config
            default_font_name: Default font file name if not specified in config
            
        Returns:
            PIL ImageFont object
        """
        font_name = element_config.get('font', default_font_name)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)
        
        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        logger.debug(f"Loaded BDF font: {font_name} at size {font_size}")
                        return font
                    except Exception:
                        logger.warning(f"Could not load BDF font {font_name} with PIL, using default")
                else:
                    logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            logger.error(f"Error loading font {font_name}: {e}, using default")
        
        # Fall back to default font
        default_font_path = os.path.join('assets', 'fonts', default_font_name)
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts for the ticker display from config or use defaults."""
        customization = self.config.get('customization', {})
        
        # Load custom fonts for specific text elements
        team_config = customization.get('team_text', {})
        odds_config = customization.get('odds_text', {})
        datetime_config = customization.get('datetime_text', {})
        
        # Load fonts as instance variables
        self.team_font = self._load_custom_font_from_element_config(team_config, default_size=8)
        self.odds_font = self._load_custom_font_from_element_config(odds_config, default_size=8)
        self.datetime_font = self._load_custom_font_from_element_config(datetime_config, default_size=8)
        
        # Keep 'large' font in dict for error messages
        try:
            # Resolve font path relative to project root
            font_path = self.project_root / "assets" / "fonts" / "PressStart2P-Regular.ttf"
            large_font = ImageFont.truetype(str(font_path), 10)
        except Exception as e:
            logger.error(f"Error loading large font: {e}")
            large_font = ImageFont.load_default()
        
        return {
            'large': large_font
        }
    
    def create_ticker_image(self, games_data: List[Dict]) -> Image.Image:
        """Create the composite ticker image from games data - matching original layout exactly."""
        if not games_data:
            return self._create_no_data_image()
        
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            # Create game images using the original method
            game_images = [self._create_game_display(game) for game in games_data]
            
            if not game_images:
                return self._create_no_data_image()
            
            # Use original spacing and layout
            gap_width = 24  # Reduced gap between games (matches original)
            display_width = matrix_width  # Add display width of black space at start and end
            content_width = sum(img.width for img in game_images) + gap_width * (len(game_images))
            total_width = display_width + content_width + display_width  # Add display width at both start and end
            
            logger.debug("Image creation details:")
            logger.debug(f"  Display width: {display_width}px")
            logger.debug(f"  Content width: {content_width}px")
            logger.debug(f"  Total image width: {total_width}px")
            logger.debug(f"  Number of games: {len(game_images)}")
            logger.debug(f"  Gap width: {gap_width}px")
            
            # Create the composite image
            composite_img = Image.new('RGB', (total_width, matrix_height), color=(0, 0, 0))
            
            # Paste game images with original spacing
            current_x = display_width  # Start after the black space
            for idx, img in enumerate(game_images):
                composite_img.paste(img, (current_x, 0))
                current_x += img.width
                # Draw a 1px white vertical bar between games, except after the last one
                if idx < len(game_images) - 1:
                    bar_x = current_x + gap_width // 2
                    for y in range(matrix_height):
                        composite_img.putpixel((bar_x, y), (255, 255, 255))
                current_x += gap_width
            
            # Calculate total scroll width for dynamic duration (only the content width, not including display width)
            self.total_scroll_width = content_width
            
            # Calculate dynamic duration if enabled
            if self.dynamic_duration_enabled:
                self._calculate_dynamic_duration()
            
            logger.debug(f"Created ticker image: {total_width}x{matrix_height}, total scroll width: {content_width}")
            self.ticker_image = composite_img
            return composite_img
            
        except Exception as e:
            logger.error(f"Error creating ticker image: {e}")
            return self._create_error_image("Render Error")
    
    def _create_game_display(self, game: Dict) -> Image.Image:
        """Create a display image for a game matching the original odds_ticker_manager layout exactly."""
        width = self.display_manager.matrix.width
        height = self.display_manager.matrix.height
        
        # Make logos use most of the display height, with a small margin
        logo_size = int(height * 1.2)
        h_padding = 4  # Use a consistent horizontal padding

        # Fonts - use custom fonts from config
        team_font = self.team_font
        odds_font = self.odds_font
        vs_font = self.team_font  # Use same font as team names for "vs."
        datetime_font = self.datetime_font

        # Get team logos
        home_logo = self._get_team_logo(game.get("league", ''), game.get('home_id', ''), game.get('home_team', ''), game.get('logo_dir', ''))
        away_logo = self._get_team_logo(game.get("league", ''), game.get('away_id', ''), game.get('away_team', ''), game.get('logo_dir', ''))
        broadcast_logo = None
        
        # Handle broadcast logo
        if self.show_channel_logos:
            broadcast_name = game.get('broadcast', '')
            if broadcast_name:
                logo_name = self.BROADCAST_LOGO_MAP.get(broadcast_name, '')
                if logo_name:
                    try:
                        broadcast_logo = Image.open(f"assets/broadcast_logos/{logo_name}.png")
                    except Exception:
                        broadcast_logo = None

        if home_logo:
            home_logo = home_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        if away_logo:
            away_logo = away_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        
        # Handle broadcast logo sizing
        broadcast_logo_col_width = 0
        if broadcast_logo:
            b_logo_h = int(height * self.broadcast_logo_height_ratio)
            ratio = b_logo_h / broadcast_logo.height
            b_logo_w = int(broadcast_logo.width * ratio)

            max_width = int(width * self.broadcast_logo_max_width_ratio)
            if b_logo_w > max_width:
                ratio = max_width / broadcast_logo.width
                b_logo_w = max_width
                b_logo_h = int(broadcast_logo.height * ratio)
            
            broadcast_logo = broadcast_logo.resize((b_logo_w, b_logo_h), Image.Resampling.LANCZOS)
            broadcast_logo_col_width = b_logo_w

        # Format date and time into 3 parts (like original)
        game_time = game.get('start_time', '')
        if isinstance(game_time, str):
            try:
                from datetime import datetime
                import pytz
                game_time = datetime.fromisoformat(game_time.replace('Z', '+00:00'))
            except Exception:
                game_time = None
        
        if game_time:
            try:
                import pytz
                timezone_str = self.config.get('timezone', 'UTC')
                tz = pytz.timezone(timezone_str)
                if game_time.tzinfo is None:
                    game_time = game_time.replace(tzinfo=pytz.UTC)
                local_time = game_time.astimezone(tz)
                day_text = local_time.strftime("%a")  # Day of week
                date_text = local_time.strftime("%-m/%d")  # Month/Day
                time_text = local_time.strftime("%I:%M%p").lstrip('0')  # Time
            except Exception:
                day_text = "TBD"
                date_text = "TBD"
                time_text = "TBD"
        else:
            day_text = "TBD"
            date_text = "TBD"
            time_text = "TBD"

        # Calculate column widths (like original)
        temp_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        day_width = int(temp_draw.textlength(day_text, font=datetime_font))
        date_width = int(temp_draw.textlength(date_text, font=datetime_font))
        time_width = int(temp_draw.textlength(time_text, font=datetime_font))
        datetime_col_width = max(day_width, date_width, time_width)

        # "vs." text
        vs_text = "vs."
        vs_width = int(temp_draw.textlength(vs_text, font=vs_font))

        # Team and record text
        away_team_name = game.get('away_team', 'N/A')
        home_team_name = game.get('home_team', 'N/A')
        away_team_text = f"{away_team_name}"
        home_team_text = f"{home_team_name}"
        
        away_team_width = int(temp_draw.textlength(away_team_text, font=team_font))
        home_team_width = int(temp_draw.textlength(home_team_text, font=team_font))
        team_info_width = max(away_team_width, home_team_width)
        
        # Odds text
        odds = game.get('odds', {})
        home_team_odds = odds.get('home_team_odds', {})
        away_team_odds = odds.get('away_team_odds', {})
        
        # Format odds like original
        away_odds_text = ""
        home_odds_text = ""
        
        if home_team_odds.get('money_line') is not None:
            away_odds_text = f"{away_team_odds.get('money_line', '')}"
            home_odds_text = f"{home_team_odds.get('money_line', '')}"
        else:
            # Show spread if available
            spread = odds.get('spread')
            if spread is not None:
                away_odds_text = f"{spread:+.1f}"
                home_odds_text = f"{spread:+.1f}"
            else:
                # Show over/under
                over_under = odds.get('over_under')
                if over_under:
                    away_odds_text = f"O/U {over_under}"
                    home_odds_text = f"O/U {over_under}"
        
        away_odds_width = int(temp_draw.textlength(away_odds_text, font=odds_font))
        home_odds_width = int(temp_draw.textlength(home_odds_text, font=odds_font))
        odds_width = max(away_odds_width, home_odds_width)
        
        # Calculate total width
        total_width = (logo_size * 2) + vs_width + team_info_width + odds_width + datetime_col_width + broadcast_logo_col_width + (h_padding * 8)
        
        # Create the image
        image = Image.new('RGB', (int(total_width), height), color=(0, 0, 0))
        draw = ImageDraw.Draw(image)

        # --- Draw elements (exactly like original) ---
        current_x = 0

        # Away Logo
        if away_logo:
            y_pos = (height - logo_size) // 2  # Center the logo vertically
            image.paste(away_logo, (current_x, y_pos), away_logo if away_logo.mode == 'RGBA' else None)
        current_x += logo_size + h_padding

        # "vs." text
        draw.text((current_x, height // 2 - 4), vs_text, font=vs_font, fill=(255, 255, 255))
        current_x += vs_width + h_padding

        # Home Logo
        if home_logo:
            y_pos = (height - logo_size) // 2  # Center the logo vertically
            image.paste(home_logo, (current_x, y_pos), home_logo if home_logo.mode == 'RGBA' else None)
        current_x += logo_size + h_padding

        # Team names (stacked)
        away_y = 2
        home_y = height - 10
        draw.text((current_x, away_y), away_team_text, font=team_font, fill=(255, 255, 255))
        draw.text((current_x, home_y), home_team_text, font=team_font, fill=(255, 255, 255))
        current_x += team_info_width + h_padding

        # Odds (stacked)
        odds_y_away = 2
        odds_y_home = height - 10
        draw.text((current_x, odds_y_away), away_odds_text, font=odds_font, fill=(255, 255, 255))
        draw.text((current_x, odds_y_home), home_odds_text, font=odds_font, fill=(255, 255, 255))
        current_x += odds_width + h_padding

        # Date/Time (stacked in 3 lines)
        datetime_font_height = datetime_font.size if hasattr(datetime_font, 'size') else 8
        dt_start_y = (height - (datetime_font_height * 3 + 4)) // 2
        
        day_y = dt_start_y
        date_y = day_y + datetime_font_height + 2
        time_y = date_y + datetime_font_height + 2

        # Center justify each line of text within the datetime column
        day_text_width = int(temp_draw.textlength(day_text, font=datetime_font))
        date_text_width = int(temp_draw.textlength(date_text, font=datetime_font))
        time_text_width = int(temp_draw.textlength(time_text, font=datetime_font))

        day_x = current_x + (datetime_col_width - day_text_width) // 2
        date_x = current_x + (datetime_col_width - date_text_width) // 2
        time_x = current_x + (datetime_col_width - time_text_width) // 2

        draw.text((day_x, day_y), day_text, font=datetime_font, fill=(255, 255, 255))
        draw.text((date_x, date_y), date_text, font=datetime_font, fill=(255, 255, 255))
        draw.text((time_x, time_y), time_text, font=datetime_font, fill=(255, 255, 255))
        current_x += datetime_col_width + h_padding

        # Broadcast logo
        if broadcast_logo:
            logo_y = (height - broadcast_logo.height) // 2
            image.paste(broadcast_logo, (current_x, logo_y))

        return image
    
    def _get_team_logo(self, league: str, team_id: str, team_abbr: str, logo_dir: str) -> Optional[Image.Image]:
        """Get team logo from assets directory."""
        try:
            # Suppress unused parameter warnings
            _ = team_id
            _ = logo_dir
            
            # Map league names to logo directories
            league_logo_map = {
                'nfl': 'nfl_logos',
                'mlb': 'mlb_logos', 
                'nba': 'nba_logos',
                'nhl': 'nhl_logos',
                'ncaa_fb': 'ncaa_logos',
                'milb': 'milb_logos'
            }
            
            logo_dir_name = league_logo_map.get(league, '')
            if not logo_dir_name or not team_abbr:
                return None
                
            # Resolve path relative to project root
            logo_path = self.project_root / "assets" / "sports" / logo_dir_name / f"{team_abbr}.png"
            if logo_path.exists():
                return Image.open(logo_path)
            else:
                logger.debug("Team logo not found: %s", logo_path)
                return None
                
        except Exception as e:
            logger.debug("Error loading team logo for %s in %s: %s", team_abbr, league, e)
            return None
    
    def _load_broadcast_logo(self, logo_name: str) -> Optional[Image.Image]:
        """Load broadcast logo from assets."""
        try:
            # Resolve path relative to project root
            logo_path = self.project_root / "assets" / "broadcast_logos" / f"{logo_name}.png"
            if logo_path.exists():
                return Image.open(logo_path)
        except Exception as e:
            logger.debug(f"Could not load broadcast logo {logo_name}: {e}")
        return None
    
    def _format_odds_display(self, odds: Dict) -> str:
        """Format odds for display - matching original format."""
        try:
            if not odds:
                return ""
            
            parts = []
            
            # Money line
            home_ml = odds.get('home_team_odds', {}).get('money_line')
            away_ml = odds.get('away_team_odds', {}).get('money_line')
            if home_ml and away_ml:
                parts.append(f"ML: {away_ml}/{home_ml}")
            
            # Spread
            spread = odds.get('spread')
            if spread is not None:
                parts.append(f"SP: {spread}")
            
            # Total/Over-Under
            over_under = odds.get('over_under')
            if over_under is not None:
                parts.append(f"O/U: {over_under}")
            
            return " | ".join(parts) if parts else ""
            
        except Exception as e:
            logger.error(f"Error formatting odds display: {e}")
            return ""
    
    
    def _create_no_data_image(self) -> Image.Image:
        """Create image when no data is available."""
        matrix_width = self.display_manager.matrix.width
        matrix_height = self.display_manager.matrix.height
        
        img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((10, 12), "No Odds Available", 
                 font=self.team_font, fill=(150, 150, 150))
        
        return img
    
    def _display_fallback_message(self):
        """Display a fallback message when no games data is available."""
        try:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            
            logger.info(f"Displaying fallback message on {width}x{height} display")
            
            # Create a simple fallback image with a brighter background
            image = Image.new('RGB', (width, height), color=(50, 50, 50))  # Dark gray instead of black
            draw = ImageDraw.Draw(image)
            
            # Draw a simple message with larger font
            message = "No odds data"
            font = self.fonts['large']  # Use large font for better visibility
            text_width = draw.textlength(message, font=font)
            text_x = (width - text_width) // 2
            text_y = (height - font.size) // 2
            
            logger.info(f"Drawing fallback message: '{message}' at position ({text_x}, {text_y})")
            
            # Draw with bright white text and black outline
            self._draw_text_with_outline(draw, message, (text_x, text_y), font, fill=(255, 255, 255), outline_color=(0, 0, 0))
            
            # Display the fallback image
            self.display_manager.image = image
            if hasattr(self.display_manager, 'draw'):
                self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
            self.display_manager.update_display()
            
        except Exception as e:
            logger.error(f"Error displaying fallback message: {e}")
    
    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, font, fill=(255, 255, 255), outline_color=(0, 0, 0), outline_width=1):
        """Draw text with an outline for better visibility."""
        try:
            x, y = position
            
            # Draw outline by drawing the text in outline color at multiple positions
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx != 0 or dy != 0:  # Skip the center position
                        draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
            
            # Draw the main text
            draw.text((x, y), text, font=font, fill=fill)
            
        except Exception as e:
            logger.error(f"Error drawing text with outline: {e}")
            # Fallback to simple text without outline
            draw.text(position, text, font=font, fill=fill)
    
    def _create_error_image(self, message: str) -> Image.Image:
        """Create error image."""
        matrix_width = self.display_manager.matrix.width
        matrix_height = self.display_manager.matrix.height
        
        img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((10, 12), message, 
                 font=self.team_font, fill=(255, 0, 0))
        
        return img
    
    def _calculate_dynamic_duration(self):
        """Calculate dynamic duration based on content width."""
        try:
            if not self.dynamic_duration_enabled or self.total_scroll_width <= 0:
                return
            
            # Calculate duration based on scroll speed and content width
            scroll_time = self.total_scroll_width / self.scroll_pixels_per_second
            
            # Add buffer time
            buffer_time = scroll_time * self.duration_buffer
            
            # Calculate total duration
            total_time = scroll_time + buffer_time
            
            # Apply min/max constraints
            self.dynamic_duration = max(self.min_duration, 
                                      min(self.max_duration, total_time))
            
            logger.debug(f"Dynamic duration calculated: {self.dynamic_duration}s "
                        f"(scroll: {scroll_time}s, buffer: {buffer_time}s)")
            
        except Exception as e:
            logger.error(f"Error calculating dynamic duration: {e}")
            self.dynamic_duration = self.min_duration
    
    def render_scrolling_ticker(self, ticker_image: Image.Image) -> bool:
        """Render the scrolling ticker animation with full original functionality."""
        if not ticker_image:
            return False
        
        try:
            current_time = time.time()
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            # Check if we should be scrolling
            should_scroll = current_time - self.last_scroll_time >= self.scroll_delay
            
            # Signal scrolling state to display manager (if available)
            if hasattr(self.display_manager, 'set_scrolling_state'):
                if should_scroll:
                    self.display_manager.set_scrolling_state(True)
                else:
                    # If we're not scrolling, check if we should process deferred updates
                    if hasattr(self.display_manager, 'process_deferred_updates'):
                        self.display_manager.process_deferred_updates()
            
            # Scroll the image
            if should_scroll:
                self.scroll_position += self.scroll_speed
                self.last_scroll_time = current_time
            
            # Handle looping based on configuration
            if self.loop:
                # Reset position when we've scrolled past the end for a continuous loop
                if self.scroll_position >= ticker_image.width:
                    logger.debug(f"Odds ticker loop reset: scroll_position {self.scroll_position} >= image width {ticker_image.width}")
                    self.scroll_position = 0
            else:
                # Stop scrolling when we reach the end
                if self.scroll_position >= ticker_image.width - matrix_width:
                    if not self._end_reached_logged:
                        logger.info(f"Odds ticker reached end: scroll_position {self.scroll_position} >= {ticker_image.width - matrix_width}")
                        logger.info("Odds ticker scrolling stopped - reached end of content")
                        self._end_reached_logged = True
                    self.scroll_position = ticker_image.width - matrix_width
                    # Signal that scrolling has stopped
                    if hasattr(self.display_manager, 'set_scrolling_state'):
                        self.display_manager.set_scrolling_state(False)
            
            # Check if we're at a natural break point for mode switching
            # If we're near the end of the display duration and not at a clean break point,
            # adjust the scroll position to complete the current game display
            if hasattr(self, '_display_start_time'):
                elapsed_time = current_time - self._display_start_time
                remaining_time = self.dynamic_duration - elapsed_time
                
                # Log scroll progress every 50 pixels to help debug (less verbose)
                if self.scroll_position % 50 == 0 and self.scroll_position > 0:
                    logger.info(f"Odds ticker progress: elapsed={elapsed_time:.1f}s, remaining={remaining_time:.1f}s, scroll_pos={self.scroll_position}/{ticker_image.width}px")
                
                # If we have less than 2 seconds remaining, check if we can complete the content display
                if remaining_time < 2.0 and self.scroll_position > 0:
                    # Calculate how much time we need to complete the current scroll position
                    # Use actual observed scroll speed (54.2 px/s) instead of theoretical calculation
                    actual_scroll_speed = 54.2  # pixels per second (calculated from logs)
                    
                    if self.loop:
                        # For looping, we need to complete one full cycle
                        distance_to_complete = ticker_image.width - self.scroll_position
                    else:
                        # For single pass, we need to reach the end (content width minus display width)
                        end_position = max(0, ticker_image.width - matrix_width)
                        distance_to_complete = end_position - self.scroll_position
                    
                    time_to_complete = distance_to_complete / actual_scroll_speed
                    
                    if time_to_complete <= remaining_time:
                        # We have enough time to complete the scroll, continue normally
                        logger.debug(f"Sufficient time remaining ({remaining_time:.1f}s) to complete scroll ({time_to_complete:.1f}s)")
                    else:
                        # Not enough time, reset to beginning for clean transition
                        # Only log this warning once per display session to avoid spam
                        if not self._insufficient_time_warning_logged:
                            logger.warning(f"Not enough time to complete content display - remaining: {remaining_time:.1f}s, needed: {time_to_complete:.1f}s")
                            logger.debug("Resetting scroll position for clean transition")
                            self._insufficient_time_warning_logged = True
                        else:
                            logger.debug("Resetting scroll position for clean transition (insufficient time warning already logged)")
                        self.scroll_position = 0
            
            # Create the visible part of the image by pasting from the ticker_image
            visible_image = Image.new('RGB', (matrix_width, matrix_height))
            
            # Main part
            visible_image.paste(ticker_image, (-self.scroll_position, 0))

            # Handle wrap-around for continuous scroll
            if self.scroll_position + matrix_width > ticker_image.width:
                wrap_around_width = (self.scroll_position + matrix_width) - ticker_image.width
                wrap_around_image = ticker_image.crop((0, 0, wrap_around_width, matrix_height))
                visible_image.paste(wrap_around_image, (ticker_image.width - self.scroll_position, 0))
            
            # Display the cropped image
            self.display_manager.image = visible_image
            if hasattr(self.display_manager, 'draw'):
                self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
            
            # Add timeout protection for display update to prevent hanging
            try:
                import threading
                import queue
                
                display_queue = queue.Queue()
                
                def update_display():
                    try:
                        self.display_manager.update_display()
                        display_queue.put(('success', None))
                    except Exception as e:
                        display_queue.put(('error', e))
                
                # Start display update in a separate thread with 1-second timeout
                display_thread = threading.Thread(target=update_display)
                display_thread.daemon = True
                display_thread.start()
                
                try:
                    result_type, result_data = display_queue.get(timeout=1)
                    if result_type == 'error':
                        logger.error(f"Display update failed: {result_data}")
                except queue.Empty:
                    logger.warning("Display update timed out after 1 second")
                
            except Exception as e:
                logger.error(f"Error during display update: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error rendering scrolling ticker: {e}", exc_info=True)
            return False
    
    def get_display_duration(self) -> float:
        """Get the display duration for this ticker."""
        if self.dynamic_duration_enabled:
            return self.dynamic_duration
        else:
            return self.config.get('display_duration', 30)
    
    def reset_scroll(self):
        """Reset scroll position to beginning."""
        self.scroll_position = 0
        self.last_scroll_time = 0
        self._end_reached_logged = False
        self._insufficient_time_warning_logged = False
    
    def start_display_session(self, force_clear: bool = False):
        """Start a new display session with proper timing."""
        current_time = time.time()
        
        # Reset display start time when force_clear is True or when starting fresh
        if force_clear or self._display_start_time is None:
            self._display_start_time = current_time
            logger.debug("Reset/initialized display start time: %s", self._display_start_time)
            # Also reset scroll position for clean start
            self.scroll_position = 0
            # Reset the end reached logging flag
            self._end_reached_logged = False
            # Reset the insufficient time warning logging flag
            self._insufficient_time_warning_logged = False
        else:
            # Check if the display start time is too old (more than 2x the dynamic duration)
            elapsed_time = current_time - self._display_start_time
            if elapsed_time > (self.dynamic_duration * 2):
                logger.debug("Display start time is too old (%.1fs), resetting", elapsed_time)
                self._display_start_time = current_time
                self.scroll_position = 0
                # Reset the end reached logging flag
                self._end_reached_logged = False
                # Reset the insufficient time warning logging flag
                self._insufficient_time_warning_logged = False
