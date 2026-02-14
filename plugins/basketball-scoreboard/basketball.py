from typing import Dict, Any, Optional
from datetime import datetime, timezone
import logging
import re
from PIL import Image, ImageDraw, ImageFont
import time
from sports import SportsCore, SportsLive
from data_sources import ESPNDataSource

class Basketball(SportsCore):
    """Base class for basketball sports with common functionality."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, logger: logging.Logger, sport_key: str):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.data_source = ESPNDataSource(logger)
        self.sport = "basketball"

    def _fetch_team_record(self, team_id: str) -> str:
        """Fetch a team's current overall record from the ESPN team endpoint."""
        cache_key = f"{self.sport_key}_team_record_{team_id}"
        cached = self.cache_manager.get(cache_key, max_age=3600)
        if cached and isinstance(cached, str):
            return cached

        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/teams/{team_id}"
            response = self.session.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            team_data = response.json().get("team", {})
            record_items = team_data.get("record", {}).get("items", [])
            for item in record_items:
                if item.get("type") == "total":
                    record = item.get("summary", "")
                    if record:
                        self.cache_manager.set(cache_key, record, ttl=3600)
                        return record
        except Exception as e:
            self.logger.debug(f"Could not fetch record for team {team_id}: {e}")
        return ""

    def _enrich_events_with_records(self, events: list, team_id: str, team_record_summary: str) -> None:
        """Inject missing team records into competitor objects.

        The ESPN team-schedule API omits per-competitor records for upcoming
        games.  This fills them in using *team_record_summary* (from the
        schedule response metadata) for the queried team and an on-demand
        fetch for opponents.
        """
        if not team_record_summary:
            return
        for event in events:
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            for comp in competitions[0].get("competitors", []):
                if not comp.get("records") and not comp.get("record"):
                    if str(comp.get("id")) == str(team_id):
                        comp["record"] = [{"displayValue": team_record_summary, "type": "total"}]
                    else:
                        opp_id = comp.get("id")
                        if opp_id:
                            opp_record = self._fetch_team_record(opp_id)
                            if opp_record:
                                comp["record"] = [{"displayValue": opp_record, "type": "total"}]

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN Basketball API response."""
        details, home_team, away_team, status, situation = self._extract_game_details_common(game_event)
        if details is None or home_team is None or away_team is None or status is None:
            return
        try:
            # Format period/quarter for basketball
            period = status.get("period", 0)
            period_text = ""
            status_state = status["type"]["state"]
            
            if status_state == "in":
                if period == 0:
                    period_text = "Start"
                elif 1 <= period <= 4:
                    period_text = f"Q{period}"
                else:
                    period_text = f"OT{period - 4}"
            elif status_state == "halftime" or status["type"]["name"] == "STATUS_HALFTIME":
                period_text = "HALF"
            elif status_state == "post":
                if period > 4:
                    period_text = "Final/OT"
                else:
                    period_text = "Final"
            elif status_state == "pre":
                period_text = details.get("game_time", "")

            details.update({
                "period": period,
                "period_text": period_text,
                "clock": status.get("displayClock", "0:00"),
            })

            # Basic validation
            if not details['home_abbr'] or not details['away_abbr']:
                self.logger.warning(f"Missing team abbreviation in event: {details['id']}")
                return None

            self.logger.debug(f"Extracted: {details['away_abbr']}@{details['home_abbr']}, Status: {status['type']['name']}, Live: {details['is_live']}, Final: {details['is_final']}, Upcoming: {details['is_upcoming']}")

            return details
        except Exception as e:
            self.logger.error(f"Error extracting game details: {e} from event: {game_event.get('id')}", exc_info=True)
            return None

class BasketballLive(Basketball, SportsLive):
    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, logger: logging.Logger, sport_key: str):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)

    # Test mode removed
    def _test_mode_update_removed(self):
        if self.current_game and self.current_game["is_live"]:
            try:
                minutes, seconds = map(int, self.current_game["clock"].split(':'))
                seconds -= 1
                if seconds < 0:
                    seconds = 59
                    minutes -= 1
                    if minutes < 0:
                        # Simulate end of quarter
                        if self.current_game["period"] < 4:
                            self.current_game["period"] += 1
                            # Update period_text
                            if self.current_game["period"] == 1:
                                self.current_game["period_text"] = "Q1"
                            elif self.current_game["period"] == 2:
                                self.current_game["period_text"] = "Q2"
                            elif self.current_game["period"] == 3:
                                self.current_game["period_text"] = "Q3"
                            elif self.current_game["period"] == 4:
                                self.current_game["period_text"] = "Q4"
                            # Reset clock for next quarter (12:00 for basketball)
                            minutes, seconds = 12, 0
                        else:
                            # Simulate overtime
                            self.current_game["period"] += 1
                            self.current_game["period_text"] = f"OT{self.current_game['period'] - 4}"
                            minutes, seconds = 5, 0
                self.current_game["clock"] = f"{minutes:02d}:{seconds:02d}"
                self.current_game["status_text"] = f"{self.current_game['period_text']} {self.current_game['clock']}"
            except ValueError:
                self.logger.warning("Test mode: Could not parse clock")

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the detailed scorebug layout for a live Basketball game."""
        try:
            # Clear the display first to ensure full coverage
            if force_clear:
                self.display_manager.clear()
            
            # Use display_manager.matrix dimensions directly
            display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_width
            display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix else self.display_height
            
            main_img = Image.new('RGBA', (display_width, display_height), (0, 0, 0, 255))
            overlay = Image.new('RGBA', (display_width, display_height), (0, 0, 0, 0))
            draw_overlay = ImageDraw.Draw(overlay)

            home_logo = self._load_and_resize_logo(game["home_id"], game["home_abbr"], game["home_logo_path"], game.get("home_logo_url"))
            away_logo = self._load_and_resize_logo(game["away_id"], game["away_abbr"], game["away_logo_path"], game.get("away_logo_url"))

            if not home_logo or not away_logo:
                self.logger.error(f"Failed to load logos for live game: {game.get('id')}")
                draw_final = ImageDraw.Draw(main_img.convert('RGB'))
                self._draw_text_with_outline(draw_final, "Logo Error", (5, 5), self.fonts['status'])
                self.display_manager.image.paste(main_img.convert('RGB'), (0, 0))
                self.display_manager.update_display()
                return

            center_y = display_height // 2

            # Draw logos
            home_x = display_width - home_logo.width + 10
            home_y = center_y - (home_logo.height // 2)
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -10
            away_y = center_y - (away_logo.height // 2)
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Period/Quarter and Clock (Top center)
            period_clock_text = f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
            if game.get("is_halftime"):
                period_clock_text = "Halftime"
            elif game.get("is_period_break"):
                period_clock_text = game.get("status_text", "Period Break")

            status_width = draw_overlay.textlength(period_clock_text, font=self.fonts['time'])
            status_x = (display_width - status_width) // 2
            status_y = 1
            self._draw_text_with_outline(draw_overlay, period_clock_text, (status_x, status_y), self.fonts['time'])

            # Scores (centered) - convert to integers to remove decimal points
            def format_score(score):
                """Format score as integer string, removing decimals."""
                try:
                    # Handle None or empty values
                    if score is None:
                        return "0"
                    
                    # If it's already a string, try to parse it
                    if isinstance(score, str):
                        # Remove any whitespace
                        score = score.strip()
                        # If empty, return 0
                        if not score:
                            return "0"
                        
                        # Check if it's a JSON string (starts with { or [)
                        if score.startswith(('{', '[')):
                            try:
                                import json
                                # Try to parse as JSON
                                parsed = json.loads(score)
                                if isinstance(parsed, dict):
                                    score_value = parsed.get("value", parsed.get("displayValue", parsed.get("score", 0)))
                                elif isinstance(parsed, list) and len(parsed) > 0:
                                    score_value = parsed[0]
                                else:
                                    score_value = parsed
                                return str(int(float(score_value)))
                            except (json.JSONDecodeError, ValueError):
                                # If JSON parsing fails, try to extract number from string
                                numbers = re.findall(r'\d+', score)
                                if numbers:
                                    return str(int(numbers[0]))
                                self.logger.warning(f"Could not parse JSON score string: {score}")
                                return "0"
                        
                        # Try to extract number from string (handles cases where score might be a string representation of something else)
                        try:
                            return str(int(float(score)))
                        except ValueError:
                            # Try to extract first number from string
                            numbers = re.findall(r'\d+', score)
                            if numbers:
                                return str(int(numbers[0]))
                            self.logger.warning(f"Could not parse score string: {score}")
                            return "0"
                    
                    # Handle dict (shouldn't happen if extraction worked, but be safe)
                    if isinstance(score, dict):
                        score_value = score.get("value", score.get("displayValue", 0))
                        return str(int(float(score_value)))
                    
                    # Handle numeric types
                    return str(int(float(score)))
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Error formatting score: {e}, score type: {type(score)}, score value: {score}")
                    return "0"
            
            home_score = format_score(game.get("home_score", "0"))
            away_score = format_score(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts['score'])
            score_x = (display_width - score_width) // 2
            score_y = (display_height // 2) - 3
            self._draw_text_with_outline(draw_overlay, score_text, (score_x, score_y), self.fonts['score'])

            # Draw odds if available
            if 'odds' in game and game['odds']:
                self._draw_dynamic_odds(draw_overlay, game['odds'], display_width, display_height)

            # Draw records or rankings if enabled
            if self.show_records or self.show_ranking:
                try:
                    record_font = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                    self.logger.debug(f"Loaded 6px record font successfully")
                except IOError:
                    record_font = ImageFont.load_default()
                    self.logger.warning(f"Failed to load 6px font, using default font (size: {record_font.size})")
                
                # Get team abbreviations
                away_abbr = game.get('away_abbr', '')
                home_abbr = game.get('home_abbr', '')
                
                record_bbox = draw_overlay.textbbox((0, 0), "0-0", font=record_font)
                record_height = record_bbox[3] - record_bbox[1]
                record_y = display_height - record_height - 1
                self.logger.debug(f"Record positioning: height={record_height}, record_y={record_y}, display_height={display_height}")

                # Display away team info
                if away_abbr:
                    if self.show_ranking and self.show_records:
                        # Rankings take priority, fall back to record for unranked teams
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            away_text = game.get('away_record', '')
                    elif self.show_ranking:
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            away_text = ''
                    elif self.show_records:
                        away_text = game.get('away_record', '')
                    else:
                        away_text = ''

                    if away_text:
                        away_record_x = 3
                        self.logger.debug(f"Drawing away ranking '{away_text}' at ({away_record_x}, {record_y})")
                        self._draw_text_with_outline(draw_overlay, away_text, (away_record_x, record_y), record_font)

                # Display home team info
                if home_abbr:
                    if self.show_ranking and self.show_records:
                        # Rankings take priority, fall back to record for unranked teams
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            home_text = game.get('home_record', '')
                    elif self.show_ranking:
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            home_text = ''
                    elif self.show_records:
                        home_text = game.get('home_record', '')
                    else:
                        home_text = ''
                    
                    if home_text:
                        home_record_bbox = draw_overlay.textbbox((0, 0), home_text, font=record_font)
                        home_record_width = home_record_bbox[2] - home_record_bbox[0]
                        home_record_x = display_width - home_record_width - 3
                        self.logger.debug(f"Drawing home ranking '{home_text}' at ({home_record_x}, {record_y})")
                        self._draw_text_with_outline(draw_overlay, home_text, (home_record_x, record_y), record_font)

            # Composite the text overlay onto the main image
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert('RGB')

            # Display the final image
            self.display_manager.image = main_img
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying live Basketball game: {e}", exc_info=True)

