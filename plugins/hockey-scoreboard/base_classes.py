"""
Base Classes for Hockey Scoreboard Plugin

Adapted from LEDMatrix base classes to provide self-contained functionality
for the hockey scoreboard plugin.
"""

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz
import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
# Fall back to Image.LANCZOS for older versions
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class SportsCore(ABC):
    """Base class for sports functionality."""
    
    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, 
                 logger: logging.Logger, sport_key: str):
        self.logger = logger
        self.config = config
        self.cache_manager = cache_manager
        self.display_manager = display_manager
        self.display_width = self.display_manager.matrix.width
        self.display_height = self.display_manager.matrix.height
        
        self.sport_key = sport_key
        self.sport = None
        self.league = None
        
        # Configuration
        self.mode_config = config.get(f"{sport_key}_scoreboard", {})
        self.is_enabled: bool = self.mode_config.get("enabled", False)
        self.show_odds: bool = self.mode_config.get("show_odds", False)
        # Use LogoDownloader to get the correct default logo directory for this sport
        from src.logo_downloader import LogoDownloader
        default_logo_dir = Path(LogoDownloader().get_logo_directory(sport_key))
        self.logo_dir = default_logo_dir
        self.update_interval: int = self.mode_config.get("update_interval_seconds", 60)
        self.show_records: bool = self.mode_config.get('show_records', False)
        self.show_ranking: bool = self.mode_config.get('show_ranking', False)
        self.recent_games_to_show: int = self.mode_config.get("recent_games_to_show", 5)
        self.upcoming_games_to_show: int = self.mode_config.get("upcoming_games_to_show", 10)
        self.show_favorite_teams_only: bool = self.mode_config.get("show_favorite_teams_only", False)
        self.show_all_live: bool = self.mode_config.get("show_all_live", False)
        
        # Set up session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self._logo_cache = {}
        
        # Set up headers
        self.headers = {
            'User-Agent': 'LEDMatrix-HockeyPlugin/1.0',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
        
        self.last_update = 0
        self.current_game = None
        self.fonts = self._load_fonts()
        
        # Initialize team rankings cache
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        self._rankings_cache_duration = 3600  # Cache rankings for 1 hour
    
    def _load_custom_font_from_element_config(self, element_config: Dict[str, Any], default_size: int = 8) -> ImageFont.FreeTypeFont:
        """
        Load a custom font from an element configuration dictionary.
        
        Args:
            element_config: Configuration dict for a single element containing 'font' and 'font_size' keys
            default_size: Default font size if not specified in config
            
        Returns:
            PIL ImageFont object
        """
        # Get font name and size, with defaults
        font_name = element_config.get('font', 'PressStart2P-Regular.ttf')
        font_size = int(element_config.get('font_size', default_size))  # Ensure integer for PIL
        
        # Build font path
        font_path = os.path.join('assets', 'fonts', font_name)
        
        # Try to load the font
        try:
            if os.path.exists(font_path):
                # Try loading as TTF first (works for both TTF and some BDF files with PIL)
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    self.logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    # BDF fonts are not supported by ImageFont.truetype()
                    # To use BDF fonts, convert to PILfont format using pilfont.py:
                    #   python -m PIL.pilfont font.bdf
                    # This creates .pil and .pbm files that can be loaded with ImageFont.load()
                    self.logger.warning(
                        f"BDF font '{font_name}' not supported; convert to PILfont format "
                        f"using 'python -m PIL.pilfont {font_path}' then use the .pil file. "
                        f"Falling back to default font."
                    )
                    # Fall through to default
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, using default")
        
        # Fall back to default font
        default_font_path = os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf')
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                self.logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()
    
    def _load_fonts(self):
        """Load fonts used by the scoreboard from config or use defaults."""
        fonts = {}
        
        # Get customization config, with backward compatibility
        customization = self.mode_config.get('customization', {})
        
        # Load fonts from config with defaults for backward compatibility
        score_config = customization.get('score_text', {})
        period_config = customization.get('period_text', {})
        team_config = customization.get('team_name', {})
        status_config = customization.get('status_text', {})
        detail_config = customization.get('detail_text', {})
        rank_config = customization.get('rank_text', {})
        
        try:
            fonts['score'] = self._load_custom_font_from_element_config(score_config, default_size=10)
            fonts['time'] = self._load_custom_font_from_element_config(period_config, default_size=8)
            fonts['team'] = self._load_custom_font_from_element_config(team_config, default_size=8)
            fonts['status'] = self._load_custom_font_from_element_config(status_config, default_size=6)
            fonts['detail'] = self._load_custom_font_from_element_config(detail_config, default_size=6)
            fonts['rank'] = self._load_custom_font_from_element_config(rank_config, default_size=10)
            self.logger.info("Successfully loaded fonts from config")
        except Exception as e:
            self.logger.error(f"Error loading fonts: {e}, using defaults")
            # Fallback to hardcoded defaults
            try:
                fonts['score'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
                fonts['time'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts['team'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts['status'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts['detail'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts['rank'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            except IOError:
                self.logger.warning("Fonts not found, using default PIL font.")
                fonts['score'] = ImageFont.load_default()
                fonts['time'] = ImageFont.load_default()
                fonts['team'] = ImageFont.load_default()
                fonts['status'] = ImageFont.load_default()
                fonts['detail'] = ImageFont.load_default()
                fonts['rank'] = ImageFont.load_default()
        return fonts
    
    def _draw_text_with_outline(self, draw, text, position, font, 
                               fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)
    
    def _load_and_resize_logo(self, team_abbrev: str, logo_path: Path) -> Optional[Image.Image]:
        """Load and resize a team logo, with caching."""
        if team_abbrev in self._logo_cache:
            return self._logo_cache[team_abbrev]
        
        try:
            if not logo_path.exists():
                self.logger.warning(f"Logo not found for {team_abbrev} at {logo_path}")
                return None
                
            logo = Image.open(logo_path)
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')
            
            # Resize logo to fit display
            max_width = int(self.display_width * 1.5)
            max_height = int(self.display_height * 1.5)
            logo.thumbnail((max_width, max_height), RESAMPLE_FILTER)
            
            self._logo_cache[team_abbrev] = logo
            return logo
            
        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}")
            return None
    
    def _get_timezone(self):
        """Get configured timezone."""
        try:
            timezone_str = self.config.get('timezone', 'UTC')
            return pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError:
            return pytz.utc
    
    def _extract_game_details_common(self, game_event: Dict) -> tuple:
        """Extract common game details from ESPN event."""
        if not game_event: 
            return None, None, None, None, None
        try:
            competition = game_event["competitions"][0]
            status = competition["status"]
            competitors = competition["competitors"]
            game_date_str = game_event["date"]
            situation = competition.get("situation")
            start_time_utc = None
            
            try:
                start_time_utc = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
            except ValueError:
                self.logger.warning(f"Could not parse game date: {game_date_str}")

            home_team = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_team = next((c for c in competitors if c.get("homeAway") == "away"), None)

            if not home_team or not away_team:
                self.logger.warning(f"Could not find home or away team in event: {game_event.get('id')}")
                return None, None, None, None, None

            try:
                home_abbr = home_team["team"]["abbreviation"]
            except KeyError:
                home_abbr = home_team["team"]["name"][:3]
            try:
                away_abbr = away_team["team"]["abbreviation"]
            except KeyError:
                away_abbr = away_team["team"]["name"][:3]
            
            game_time, game_date = "", ""
            if start_time_utc:
                local_time = start_time_utc.astimezone(self._get_timezone())
                game_time = local_time.strftime("%I:%M%p").lstrip('0')
                
                # Check date format from config
                use_short_date_format = self.config.get('display', {}).get('use_short_date_format', False)
                if use_short_date_format:
                    game_date = local_time.strftime("%-m/%-d")
                else:
                    game_date = local_time.strftime("%B %d")

            home_record = home_team.get('records', [{}])[0].get('summary', '') if home_team.get('records') else ''
            away_record = away_team.get('records', [{}])[0].get('summary', '') if away_team.get('records') else ''
            
            # Don't show "0-0" records
            if home_record in {"0-0", "0-0-0"}:
                home_record = ''
            if away_record in {"0-0", "0-0-0"}:
                away_record = ''

            details = {
                "id": game_event.get("id"),
                "game_time": game_time,
                "game_date": game_date,
                "start_time_utc": start_time_utc,
                "status_text": status["type"]["shortDetail"],
                "is_live": status["type"]["state"] == "in",
                "is_final": status["type"]["state"] == "post",
                "is_upcoming": (status["type"]["state"] == "pre" or 
                               status["type"]["name"].lower() in ['scheduled', 'pre-game', 'status_scheduled']),
                "is_halftime": status["type"]["state"] == "halftime" or status["type"]["name"] == "STATUS_HALFTIME",
                "is_period_break": status["type"]["name"] == "STATUS_END_PERIOD",
                "home_abbr": home_abbr,
                "home_id": home_team["id"],
                "home_score": home_team.get("score", "0"),
                "home_logo_path": self.logo_dir / Path(f"{home_abbr}.png"),
                "home_logo_url": home_team["team"].get("logo"),
                "home_record": home_record,
                "away_record": away_record,
                "away_abbr": away_abbr,
                "away_id": away_team["id"],
                "away_score": away_team.get("score", "0"),
                "away_logo_path": self.logo_dir / Path(f"{away_abbr}.png"),
                "away_logo_url": away_team["team"].get("logo"),
                "is_within_window": True,
            }
            return details, home_team, away_team, status, situation
        except Exception as e:
            self.logger.error(f"Error extracting game details: {e} from event: {game_event.get('id')}", exc_info=True)
            return None, None, None, None, None
    
    @abstractmethod
    def _extract_game_details(self, game_event: dict) -> dict:
        """Extract game details - to be implemented by subclasses."""
        pass
    
    @abstractmethod
    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data - to be implemented by subclasses."""
        pass


class Hockey(SportsCore):
    """Base class for hockey sports with common functionality."""
    
    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, 
                 logger: logging.Logger, sport_key: str):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.sport = "hockey"
        self.show_shots_on_goal = self.mode_config.get("show_shots_on_goal", False)
    
    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN hockey API response."""
        details, home_team, away_team, status, situation = (
            self._extract_game_details_common(game_event)
        )
        if details is None or home_team is None or away_team is None or status is None:
            return None
        
        try:
            powerplay = False
            penalties = ""
            
            # Extract shots on goal
            home_stats = home_team.get("statistics", [])
            away_stats = away_team.get("statistics", [])
            home_shots = next(
                (int(c["displayValue"]) for c in home_stats if c.get("name") == "shots"),
                0
            )
            away_shots = next(
                (int(c["displayValue"]) for c in away_stats if c.get("name") == "shots"),
                0
            )
            

            if situation and status["type"]["state"] == "in":
                powerplay = situation.get("isPowerPlay", False)
                penalties = situation.get("penalties", "")

            # Format period
            period = status.get("period", 0)
            period_text = ""
            if status["type"]["state"] == "in":
                if period == 0:
                    period_text = "Start"
                elif period >= 1 and period <= 3:
                    period_text = f"P{period}"
                elif period > 3:
                    period_text = f"OT{period - 3}"
            elif status["type"]["state"] == "post":
                if period > 3:
                    period_text = "Final/OT"
                else:
                    period_text = "Final"
            elif status["type"]["state"] == "pre":
                period_text = details.get("game_time", "")

            details.update({
                "period": period,
                "period_text": period_text,
                "clock": status.get("displayClock", "0:00"),
                "power_play": powerplay,
                "penalties": penalties,
                "home_shots": home_shots,
                "away_shots": away_shots,
            })

            # Basic validation
            if not details["home_abbr"] or not details["away_abbr"]:
                self.logger.warning(f"Missing team abbreviation in event: {details['id']}")
                return None

            self.logger.debug(
                f"Extracted: {details['away_abbr']}@{details['home_abbr']}, Status: {status['type']['name']}, Live: {details['is_live']}, Final: {details['is_final']}, Upcoming: {details['is_upcoming']}"
            )

            return details
        except Exception as e:
            self.logger.error(f"Error extracting game details: {e} from event: {game_event.get('id')}", exc_info=True)
            return None


class HockeyLive(Hockey):
    """Live hockey game functionality."""
    
    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, 
                 logger: logging.Logger, sport_key: str):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.update_interval = self.mode_config.get("live_update_interval", 15)
        self.no_data_interval = 300
        self.last_update = 0
        self.live_games = []
        self.current_game_index = 0
        self.last_game_switch = 0
        self.game_display_duration = self.mode_config.get("live_game_duration", 20)
        self.last_display_update = 0
        self.last_log_time = 0
        self.log_interval = 300
    
    def _test_mode_update(self):
        """Update game data in test mode."""
        if self.current_game and self.current_game["is_live"]:
            # For testing, update the clock to show it's working
            minutes = int(self.current_game["clock"].split(":")[0])
            seconds = int(self.current_game["clock"].split(":")[1])
            seconds -= 1
            if seconds < 0:
                seconds = 59
                minutes -= 1
                if minutes < 0:
                    minutes = 19
                    if self.current_game["period"] < 3:
                        self.current_game["period"] += 1
                    else:
                        self.current_game["period"] = 1
            self.current_game["clock"] = f"{minutes:02d}:{seconds:02d}"
    
    def _draw_scorebug_layout(self, game: Dict) -> None:
        """Draw the detailed scorebug layout for a live hockey game."""
        try:
            main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
            overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
            draw_overlay = ImageDraw.Draw(overlay)
            
            home_logo = self._load_and_resize_logo(
                game["home_id"], game["home_abbr"], game["home_logo_path"], game.get("home_logo_url")
            )
            away_logo = self._load_and_resize_logo(
                game["away_id"], game["away_abbr"], game["away_logo_path"], game.get("away_logo_url")
            )

            if not home_logo or not away_logo:
                self.logger.error(f"Failed to load logos for live game: {game.get('id')}")
                draw_final = ImageDraw.Draw(main_img.convert("RGB"))
                self._draw_text_with_outline(draw_final, "Logo Error", (5, 5), self.fonts["status"])
                self.display_manager.image.paste(main_img.convert("RGB"), (0, 0))
                self.display_manager.update_display()
                return

            center_y = self.display_height // 2

            # Draw logos
            home_x = self.display_width - home_logo.width + 10
            home_y = center_y - (home_logo.height // 2)
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -10
            away_y = center_y - (away_logo.height // 2)
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Period/Quarter and Clock (Top center)
            period_clock_text = f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
            if game.get("is_period_break"):
                period_clock_text = game.get("status_text", "Period Break")

            status_width = draw_overlay.textlength(period_clock_text, font=self.fonts["time"])
            status_x = (self.display_width - status_width) // 2
            status_y = 1
            self._draw_text_with_outline(draw_overlay, period_clock_text, (status_x, status_y), self.fonts["time"])

            # Scores (centered, slightly above bottom)
            home_score = str(game.get("home_score", "0"))
            away_score = str(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2
            score_y = (self.display_height // 2) - 3
            self._draw_text_with_outline(draw_overlay, score_text, (score_x, score_y), self.fonts["score"])

            # Shots on Goal
            if self.show_shots_on_goal:
                shots_font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                home_shots = str(game.get("home_shots", "0"))
                away_shots = str(game.get("away_shots", "0"))
                shots_text = f"{away_shots}   SHOTS   {home_shots}"
                shots_bbox = draw_overlay.textbbox((0, 0), shots_text, font=shots_font)
                shots_height = shots_bbox[3] - shots_bbox[1]
                shots_y = self.display_height - shots_height - 1
                shots_width = draw_overlay.textlength(shots_text, font=shots_font)
                shots_x = (self.display_width - shots_width) // 2
                self._draw_text_with_outline(draw_overlay, shots_text, (shots_x, shots_y), shots_font)

            # Composite the text overlay onto the main image
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")

            # Display the final image
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying live Hockey game: {e}", exc_info=True)


class SportsRecent(SportsCore):
    """Recent games functionality."""
    
    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, 
                 logger: logging.Logger, sport_key: str):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.recent_games = []
        self.games_list = []
        self.current_game_index = 0
        self.last_update = 0
        self.update_interval = self.mode_config.get("recent_update_interval", 3600)
        self.last_game_switch = 0
        self.game_display_duration = 15


class SportsUpcoming(SportsCore):
    """Upcoming games functionality."""
    
    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, 
                 logger: logging.Logger, sport_key: str):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.upcoming_games = []
        self.games_list = []
        self.current_game_index = 0
        self.last_update = 0
        self.update_interval = self.mode_config.get("upcoming_update_interval", 3600)
        self.last_log_time = 0
        self.log_interval = 300
        self.last_warning_time = 0
        self.warning_cooldown = 300
        self.last_game_switch = 0
        self.game_display_duration = 15
