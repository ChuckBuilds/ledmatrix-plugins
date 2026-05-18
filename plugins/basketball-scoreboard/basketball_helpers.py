"""
Basketball Helper Functions

Contains all the helper methods needed for basketball scoreboard rendering,
logo loading, text drawing, and game data extraction.

Extracted from Basketball and Sports base classes for plugin independence.
"""

import logging
from pathlib import Path
from typing import Dict, Optional
from PIL import Image, ImageDraw, ImageFont


class BasketballHelpers:
    """Helper class for basketball-specific rendering and data processing."""
    
    def __init__(self, logger: logging.Logger, display_width: int, display_height: int):
        self.logger = logger
        self.display_width = display_width
        self.display_height = display_height
        self._logo_cache = {}
    
    def load_fonts(self):
        """Load fonts used by the scoreboard."""
        fonts = {}
        try:
            fonts['score'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            fonts['time'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['team'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['status'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['detail'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['rank'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            self.logger.info("Successfully loaded fonts")
        except IOError as e:
            self.logger.warning(f"Fonts not found, using default PIL font: {e}")
            fonts['score'] = ImageFont.load_default()
            fonts['time'] = ImageFont.load_default()
            fonts['team'] = ImageFont.load_default()
            fonts['status'] = ImageFont.load_default()
            fonts['detail'] = ImageFont.load_default()
            fonts['rank'] = ImageFont.load_default()
        return fonts
    
    def draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, 
                               font: ImageFont.FreeTypeFont, fill=(255, 255, 255), 
                               outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)
    
    def load_and_resize_logo(self, team_abbrev: str, logo_path: Path) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching."""
        self.logger.debug(f"Loading logo for {team_abbrev} from {logo_path}")
        
        # Check cache first
        if team_abbrev in self._logo_cache:
            self.logger.debug(f"Using cached logo for {team_abbrev}")
            return self._logo_cache[team_abbrev]
        
        try:
            # Check if file exists
            if not logo_path.exists():
                self.logger.warning(f"Logo not found for {team_abbrev} at {logo_path}")
                return None
            
            # Load and convert to RGBA
            logo = Image.open(logo_path)
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')
            
            # Resize to fit display
            max_width = int(self.display_width * 1.5)
            max_height = int(self.display_height * 1.5)
            logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            # Cache the logo
            self._logo_cache[team_abbrev] = logo
            return logo
            
        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}", exc_info=True)
            return None
    
    def extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract game details from ESPN API event."""
        if not game_event:
            return None
        
        try:
            competition = game_event.get("competitions", [{}])[0]
            status = competition.get("status", {})
            competitors = competition.get("competitors", [])
            
            if len(competitors) < 2:
                self.logger.warning("Not enough competitors in game event")
                return None
            
            # Find home and away teams
            home_team = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_team = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            if not home_team or not away_team:
                self.logger.warning("Could not find home/away teams")
                return None
            
            # Extract team information
            home_team_info = home_team.get('team', {})
            away_team_info = away_team.get('team', {})
            
            # Build game details
            details = {
                'id': game_event.get('id'),
                'home_id': home_team_info.get('id'),
                'home_abbr': home_team_info.get('abbreviation', 'HOME'),
                'home_name': home_team_info.get('displayName', 'Home'),
                'home_score': str(home_team.get('score', 0)),
                'away_id': away_team_info.get('id'),
                'away_abbr': away_team_info.get('abbreviation', 'AWAY'),
                'away_name': away_team_info.get('displayName', 'Away'),
                'away_score': str(away_team.get('score', 0)),
            }
            
            # Extract status information
            status_type = status.get('type', {})
            status_state = status_type.get('state', 'unknown')
            details['is_live'] = status_state == 'in'
            details['is_final'] = status_state == 'post'
            details['is_upcoming'] = status_state == 'pre'
            details['is_halftime'] = status_state == 'halftime'
            
            # Format period/quarter for basketball
            period = status.get('period', 0)
            period_text = ""
            
            if status_state == 'in':
                if period == 0:
                    period_text = "Start"
                elif 1 <= period <= 4:
                    period_text = f"Q{period}"
                else:
                    period_text = f"OT{period - 4}"
            elif status_state == 'halftime':
                period_text = "HALF"
            elif status_state == 'post':
                if period > 4:
                    period_text = "Final/OT"
                else:
                    period_text = "Final"
            elif status_state == 'pre':
                # For upcoming games, show the date/time
                period_text = game_event.get('date', '')[:10] if game_event.get('date') else "TBD"
            
            details.update({
                'period': period,
                'period_text': period_text,
                'clock': status.get('displayClock', '0:00'),
            })
            
            # Set logo paths (will be set by caller based on league)
            details['home_logo_path'] = None
            details['away_logo_path'] = None
            
            return details
            
        except Exception as e:
            self.logger.error(f"Error extracting game details: {e}", exc_info=True)
            return None
