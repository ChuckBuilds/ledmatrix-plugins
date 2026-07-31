import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pytz
from PIL import Image, ImageDraw, ImageFont

from data_sources import ESPNDataSource
from sports import SportsCore, SportsLive


class Lacrosse(SportsCore):
    """Base class for lacrosse sports with common functionality."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.data_source = ESPNDataSource(logger)
        self.sport = "lacrosse"
        self.show_shots = self.mode_config.get("show_shots", False)

    def _fetch_season_schedule(
        self,
        *,
        sport: str,
        cache_key_prefix: str,
        scoreboard_url: str,
        season_start_mmdd: str,
        season_end_mmdd: str = "0601",
        use_cache: bool = True,
    ) -> Optional[Dict]:
        """Fetch the full ESPN lacrosse season schedule with caching.

        Shared helper used by both NCAA men's and women's managers. Handles
        season-year rollover (anything from July onward targets the next
        calendar year's season), cache hits, background fetches, and
        immediate partial-data returns.

        Args:
            sport: Sport identifier passed to the background fetch service
                (e.g. ``"ncaa_mens_lacrosse"`` or ``"ncaa_womens_lacrosse"``).
            cache_key_prefix: Cache key prefix; the season year is appended.
            scoreboard_url: Full ESPN scoreboard URL for this league.
            season_start_mmdd: First calendar date of the season window as
                ``"MMDD"`` (e.g. ``"0101"`` for men's, ``"0201"`` for women's).
            season_end_mmdd: Last calendar date of the season window; defaults
                to June 1 which covers NCAA championships for both leagues.
            use_cache: When True, consult the cache manager first and only
                kick off a background fetch on a miss.
        """
        now = datetime.now(pytz.utc)
        season_year = now.year
        # After the NCAA championship (late May / June), roll to the next
        # season year for caching purposes.
        if now.month >= 7:
            season_year = now.year + 1
        datestring = f"{season_year}{season_start_mmdd}-{season_year}{season_end_mmdd}"
        cache_key = f"{cache_key_prefix}_{season_year}"

        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info(f"Using cached schedule for {season_year}")
                    return cached_data
                elif isinstance(cached_data, list):
                    self.logger.info(
                        f"Using cached schedule for {season_year} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {season_year}: {type(cached_data)}"
                    )
                    self.cache_manager.clear_cache(cache_key)

        self.logger.info(
            f"Fetching full {season_year} season schedule from ESPN API..."
        )
        self.logger.info(
            f"Starting background fetch for {season_year} season schedule..."
        )

        def fetch_callback(result):
            """Callback when background fetch completes."""
            if result.success:
                events = (getattr(result, "data", None) or {}).get("events") or []
                self.logger.info(
                    f"Background fetch completed for {season_year}: {len(events)} events"
                )
            else:
                self.logger.error(
                    f"Background fetch failed for {season_year}: {result.error}"
                )
            if season_year in self.background_fetch_requests:
                del self.background_fetch_requests[season_year]

        background_config = self.mode_config.get("background_service", {})
        timeout = background_config.get("request_timeout", 30)
        max_retries = background_config.get("max_retries", 3)
        priority = background_config.get("priority", 2)

        request_id = self.background_service.submit_fetch_request(
            sport=sport,
            year=season_year,
            url=scoreboard_url,
            cache_key=cache_key,
            params={"dates": datestring, "limit": 1000},
            headers=self.headers,
            timeout=timeout,
            max_retries=max_retries,
            priority=priority,
            callback=fetch_callback,
        )
        self.background_fetch_requests[season_year] = request_id

        # For immediate response, return whatever partial data is available.
        partial_data = self._get_weeks_data()
        if partial_data:
            return partial_data
        return None

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN Lacrosse API response."""
        details, home_team, away_team, status, _situation = (
            self._extract_game_details_common(game_event)
        )
        if details is None or home_team is None or away_team is None or status is None:
            return None
        try:
            competition = game_event["competitions"][0]
            status = competition["status"]

            # Lacrosse shot totals (if exposed in statistics)
            home_stats = home_team.get("statistics", [])
            away_stats = away_team.get("statistics", [])
            home_shots = next(
                (
                    int(c["displayValue"])
                    for c in home_stats
                    if c.get("name") in ("shots", "totalShots")
                ),
                0,
            )
            away_shots = next(
                (
                    int(c["displayValue"])
                    for c in away_stats
                    if c.get("name") in ("shots", "totalShots")
                ),
                0,
            )

            # Format period/quarter. NCAA men's & women's lacrosse use 4 quarters.
            period = status.get("period", 0)
            period_text = ""
            if status["type"]["state"] == "in":
                if period == 0:
                    period_text = "Start"
                elif 1 <= period <= 4:
                    period_text = f"Q{period}"
                elif period > 4:
                    period_text = f"OT{period - 4}"
            elif status["type"]["state"] == "post":
                if period > 4:
                    period_text = "Final/OT"
                else:
                    period_text = "Final"
            elif status["type"]["state"] == "pre":
                period_text = details.get("game_time", "")

            details.update(
                {
                    "period": period,
                    "period_text": period_text,
                    "clock": status.get("displayClock", "0:00"),
                    "home_shots": home_shots,
                    "away_shots": away_shots,
                }
            )

            if not details["home_abbr"] or not details["away_abbr"]:
                self.logger.warning(
                    f"Missing team abbreviation in event: {details['id']}"
                )
                return None

            self.logger.debug(
                f"Extracted: {details['away_abbr']}@{details['home_abbr']}, "
                f"Status: {status['type']['name']}, Live: {details['is_live']}, "
                f"Final: {details['is_final']}, Upcoming: {details['is_upcoming']}"
            )

            return details
        except Exception as e:
            self.logger.error(
                f"Error extracting game details: {e} from event: {game_event.get('id')}",
                exc_info=True,
            )
            return None

    def _get_team_display_text(self, abbr: str, record: str) -> str:
        """Pick the short text shown under a team logo.

        When `show_ranking` is enabled, the poll rank (if any) wins and the
        record is hidden. When only `show_records` is enabled, the W-L record
        is shown. Unranked teams get an empty string under ranking-only mode.
        """
        if not abbr:
            return ""
        if self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            return ""
        if self.show_records:
            return record or ""
        return ""


class LacrosseLive(Lacrosse, SportsLive):
    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)

    def _test_mode_update(self):
        if not (self.current_game and self.current_game.get("is_live")):
            return
        # For testing, tick the clock down to show updates working.
        clock_str = self.current_game.get("clock") or ""
        try:
            minutes_str, seconds_str = clock_str.split(":", 1)
            minutes = int(minutes_str)
            seconds = int(seconds_str)
        except (ValueError, AttributeError):
            # Malformed clock — reset to the start of a 15-minute quarter.
            self.logger.debug(
                f"Test clock reset: unparseable value {clock_str!r}"
            )
            self.current_game["clock"] = "15:00"
            return
        seconds -= 1
        if seconds < 0:
            seconds = 59
            minutes -= 1
            if minutes < 0:
                minutes = 14  # 15-minute quarters (NCAA men's)
                if self.current_game.get("period", 1) < 4:
                    self.current_game["period"] = self.current_game.get("period", 1) + 1
                else:
                    self.current_game["period"] = 1
        self.current_game["clock"] = f"{minutes:02d}:{seconds:02d}"

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the detailed scorebug layout for a live Lacrosse game."""
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(overlay)
            home_logo = self._load_and_resize_logo(
                game["home_id"],
                game["home_abbr"],
                game["home_logo_path"],
                game.get("home_logo_url"),
            )
            away_logo = self._load_and_resize_logo(
                game["away_id"],
                game["away_abbr"],
                game["away_logo_path"],
                game.get("away_logo_url"),
            )

            if not home_logo or not away_logo:
                self.logger.error(
                    f"Failed to load logos for live game: {game.get('id')}"
                )
                draw_final = ImageDraw.Draw(main_img.convert("RGB"))
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image.paste(main_img.convert("RGB"), (0, 0))
                self.display_manager.update_display()
                return

            center_y = self.display_height // 2

            home_x = (
                self.display_width - home_logo.width + 10
                + self._get_layout_offset('home_logo', 'x_offset')
            )
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -10 + self._get_layout_offset('away_logo', 'x_offset')
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # Quarter and Clock (Top center)
            period_clock_text = (
                f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
            )
            if game.get("is_period_break"):
                period_clock_text = game.get("status_text", "Quarter Break")

            status_width = draw_overlay.textlength(
                period_clock_text, font=self.fonts["time"]
            )
            status_x = (self.display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
            status_y = 1 + self._get_layout_offset('status_text', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay,
                period_clock_text,
                (status_x, status_y),
                self.fonts["time"],
            )

            # Scores (centered, slightly above bottom)
            home_score = str(game.get("home_score", "0"))
            away_score = str(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2 + self._get_layout_offset('score', 'x_offset')
            score_y = (
                self.display_height // 2
            ) - 3 + self._get_layout_offset('score', 'y_offset')
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts["score"]
            )

            # Shot totals
            if self.show_shots:
                shots_font = self.fonts.get("shots") or self.fonts.get("record") or ImageFont.load_default()
                home_shots = str(game.get("home_shots", "0"))
                away_shots = str(game.get("away_shots", "0"))
                shots_text = f"{away_shots}   SHOTS   {home_shots}"
                shots_bbox = draw_overlay.textbbox((0, 0), shots_text, font=shots_font)
                shots_height = shots_bbox[3] - shots_bbox[1]
                shots_y = self.display_height - shots_height - 1
                shots_width = draw_overlay.textlength(shots_text, font=shots_font)
                shots_x = (self.display_width - shots_width) // 2
                self._draw_text_with_outline(
                    draw_overlay, shots_text, (shots_x, shots_y), shots_font
                )

            # Draw odds if available
            if game.get("odds"):
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height
                )

            # Draw records or rankings if enabled
            if self.show_records or self.show_ranking:
                record_font = self.fonts.get("record") or self.fonts.get("status") or ImageFont.load_default()

                away_abbr = game.get("away_abbr", "")
                home_abbr = game.get("home_abbr", "")

                record_bbox = draw_overlay.textbbox((0, 0), "0-0", font=record_font)
                record_height = record_bbox[3] - record_bbox[1]
                record_y = self.display_height - record_height - 1

                away_text = self._get_team_display_text(
                    away_abbr, game.get("away_record", "")
                )
                if away_text:
                    self._draw_text_with_outline(
                        draw_overlay,
                        away_text,
                        (3, record_y),
                        record_font,
                    )

                home_text = self._get_team_display_text(
                    home_abbr, game.get("home_record", "")
                )
                if home_text:
                    home_record_bbox = draw_overlay.textbbox(
                        (0, 0), home_text, font=record_font
                    )
                    home_record_width = home_record_bbox[2] - home_record_bbox[0]
                    home_record_x = self.display_width - home_record_width - 3
                    self._draw_text_with_outline(
                        draw_overlay,
                        home_text,
                        (home_record_x, record_y),
                        record_font,
                    )

            # Composite text overlay onto main image
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")

            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(
                f"Error displaying live Lacrosse game: {e}", exc_info=True
            )
