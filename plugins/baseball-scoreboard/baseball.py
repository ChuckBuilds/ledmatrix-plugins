"""
Baseball Base Classes

This module provides baseball-specific base classes that extend the core sports functionality
with baseball-specific logic for innings, outs, bases, strikes, balls, etc.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from data_sources import ESPNDataSource
from sports import SportsCore, SportsLive, SportsRecent

# ESPN categorical play types that map unambiguously to a short code.
CLEAN_PLAY_TYPE_MAP: Dict[str, str] = {
    "single": "1B",
    "double": "2B",
    "triple": "3B",
    "home-run": "HR",
    "fly-out": "F",
    "ground-out": "GO",
    "line-out": "L",
    "pop-out": "P",
    "hit-by-pitch": "HBP",
}

# Walks/strikeouts (and a few other outcomes as a fallback) have no
# dedicated ESPN `type.type` -- they land in a generic "play-result" bucket
# and are only recoverable via keyword-matching the free-text description.
# Ordered so more specific phrases are checked before shorter substrings
# that could otherwise false-match (e.g. "walked" vs "walked back").
PLAY_RESULT_KEYWORDS: List[Tuple[str, str]] = [
    ("struck out", "K"),
    ("walked", "BB"),
    ("hit by pitch", "HBP"),
    ("homered", "HR"),
    ("tripled", "3B"),
    ("doubled", "2B"),
    ("singled", "1B"),
]


def _build_athlete_name_map(rosters: Optional[List[Dict]]) -> Dict[str, str]:
    """Join both teams' roster lists into {athlete_id: shortName}."""
    names: Dict[str, str] = {}
    for team_roster in rosters or []:
        for entry in team_roster.get("roster", []) or []:
            athlete = entry.get("athlete", {}) or {}
            athlete_id = str(athlete.get("id", "") or "")
            if not athlete_id:
                continue
            name = athlete.get("shortName") or athlete.get("fullName") or ""
            if name:
                names[athlete_id] = name
    return names


def _get_current_pitcher_batter(
    plays: Optional[List[Dict]], athlete_names: Dict[str, str]
) -> Tuple[Optional[str], Optional[str]]:
    """Scan plays backward for the most recent play naming a pitcher/batter.

    The last entry in `plays` is often a transition marker (e.g. end of
    inning) with no `participants`, so a simple `plays[-1]` lookup misses
    the actual at-bat most of the time.
    """
    for play in reversed(plays or []):
        pitcher_id = None
        batter_id = None
        for participant in play.get("participants") or []:
            role = participant.get("type")
            athlete_id = str(participant.get("athlete", {}).get("id", "") or "")
            if not athlete_id:
                continue
            if role == "pitcher":
                pitcher_id = athlete_id
            elif role == "batter":
                batter_id = athlete_id
        pitcher = athlete_names.get(pitcher_id) if pitcher_id else None
        batter = athlete_names.get(batter_id) if batter_id else None
        if pitcher or batter:
            return pitcher, batter
    return None, None


def _map_play_type(play: Dict) -> Optional[str]:
    """Map a single play to a short code, or None on no confident match."""
    play_type = (play.get("type") or {}).get("type", "")
    if play_type in CLEAN_PLAY_TYPE_MAP:
        return CLEAN_PLAY_TYPE_MAP[play_type]

    text = (play.get("text") or "").lower()
    for keyword, code in PLAY_RESULT_KEYWORDS:
        if keyword in text:
            return code
    return None


def _get_last_play_code(plays: Optional[List[Dict]]) -> Optional[str]:
    """Return the short code for the most recently completed play, or None.

    Skips trailing empty transition-marker entries (no type, no text), but
    stops at the first substantive play and returns its mapped code -- or
    None if that play's outcome can't be confidently mapped, rather than
    scanning further back and risking showing a stale result.
    """
    for play in reversed(plays or []):
        play_type = (play.get("type") or {}).get("type", "")
        text = play.get("text") or ""
        if not play_type and not text:
            continue
        return _map_play_type(play)
    return None


class Baseball(SportsCore):
    """Base class for baseball sports with common functionality."""

    # Set by league-specific base managers to opt into the ESPN per-game
    # summary endpoint (pitcher/batter/last-play). Left None for leagues
    # (e.g. MiLB) whose live game IDs aren't ESPN IDs and have no verified
    # summary endpoint shape.
    espn_summary_sport_league: Optional[Tuple[str, str]] = None

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        # Baseball-specific configuration
        self.show_innings = self.mode_config.get("show_innings", True)
        self.show_outs = self.mode_config.get("show_outs", True)
        self.show_bases = self.mode_config.get("show_bases", True)
        self.show_count = self.mode_config.get("show_count", True)
        self.show_pitcher_batter = self.mode_config.get("show_pitcher_batter", False)
        self.show_last_play = self.mode_config.get("show_last_play", False)
        self.show_series_summary = self.mode_config.get("show_series_summary", False)
        self.data_source = ESPNDataSource(logger)
        self.sport = "baseball"

    def _is_baseball_game_live(self, game: Dict) -> bool:
        """Check if a baseball game is currently live."""
        try:
            # Check if game is marked as live
            is_live = game.get("is_live", False)
            if is_live:
                return True

            # Check inning to determine if game is active
            inning = game.get("inning", "")
            if inning and inning != "Final":
                return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking if baseball game is live: {e}")
            return False

    def _get_baseball_game_status(self, game: Dict) -> str:
        """Get baseball-specific game status."""
        try:
            status = game.get("status_text", "")
            inning = game.get("inning", "")

            if self._is_baseball_game_live(game):
                if inning:
                    return f"Live - {inning}"
                else:
                    return "Live"
            elif game.get("is_final", False):
                return "Final"
            elif game.get("is_upcoming", False):
                return "Upcoming"
            else:
                return status

        except Exception as e:
            self.logger.error(f"Error getting baseball game status: {e}")
            return ""

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN Baseball API response."""
        details, home_team, away_team, status, situation = (
            self._extract_game_details_common(game_event)
        )
        if details is None or home_team is None or away_team is None or status is None:
            self.logger.debug(
                f"Skipping malformed event (missing common fields): id={game_event.get('id', '?')}"
            )
            return None
        try:
            game_status = status["type"]["name"].lower()
            status_state = status["type"]["state"].lower()
            # Get team abbreviations (some NCAA teams lack 'abbreviation')
            home_abbr = home_team["team"].get("abbreviation") or (home_team["team"].get("name") or "?")[:3]
            away_abbr = away_team["team"].get("abbreviation") or (away_team["team"].get("name") or "?")[:3]

            # Check if this is a favorite team game
            is_favorite_game = (
                home_abbr in self.favorite_teams or away_abbr in self.favorite_teams
            )

            # Log all teams found for debugging
            self.logger.debug(
                f"Found game: {away_abbr} @ {home_abbr} (Status: {game_status}, State: {status_state})"
            )

            # Only log detailed information for favorite teams
            if is_favorite_game:
                self.logger.debug(f"Full status data: {game_event['status']}")
                self.logger.debug(f"Status type: {game_status}, State: {status_state}")
                self.logger.debug(f"Status detail: {status['type'].get('detail', '')}")
                self.logger.debug(
                    f"Status shortDetail: {status['type'].get('shortDetail', '')}"
                )
            series = game_event["competitions"][0].get("series", None)
            series_summary = ""
            if series:
                series_summary = series.get("summary", "")
            # Get game state information
            if status_state == "in":
                # For live games, get detailed state
                inning = game_event["status"].get(
                    "period", 1
                )  # Get inning from status period

                # Get inning information from status
                status_detail = status["type"].get("detail", "").lower()
                status_short = status["type"].get("shortDetail", "").lower()

                if is_favorite_game:
                    self.logger.debug(
                        f"Raw status detail: {status['type'].get('detail')}"
                    )
                    self.logger.debug(
                        f"Raw status short: {status['type'].get('shortDetail')}"
                    )

                # Determine inning half from status information
                inning_half = "top"  # Default

                # Handle end of inning: next inning is top
                if "end" in status_detail or "end" in status_short:
                    inning_half = "top"
                    inning = (
                        game_event["status"].get("period", 1) + 1
                    )  # Use period and increment for next inning
                    if is_favorite_game:
                        self.logger.debug(
                            f"Detected end of inning. Setting to Top {inning}"
                        )
                # Handle middle of inning: next is bottom of current inning
                elif "mid" in status_detail or "mid" in status_short:
                    inning_half = "bottom"
                    if is_favorite_game:
                        self.logger.debug(
                            f"Detected middle of inning. Setting to Bottom {inning}"
                        )
                # Handle bottom of inning
                elif (
                    "bottom" in status_detail
                    or "bot" in status_detail
                    or "bottom" in status_short
                    or "bot" in status_short
                ):
                    inning_half = "bottom"
                    if is_favorite_game:
                        self.logger.debug(f"Detected bottom of inning: {inning}")
                # Handle top of inning
                elif "top" in status_detail or "top" in status_short:
                    inning_half = "top"
                    if is_favorite_game:
                        self.logger.debug(f"Detected top of inning: {inning}")

                if is_favorite_game:
                    self.logger.debug(f"Status detail: {status_detail}")
                    self.logger.debug(f"Status short: {status_short}")
                    self.logger.debug(f"Determined inning: {inning_half} {inning}")

                # Get count and bases from situation
                situation = game_event["competitions"][0].get("situation", {})

                # NCAA baseball API doesn't provide count/outs data (only onFirst/onSecond/onThird)
                # Use league identifier for deterministic detection instead of key-presence heuristic
                has_count_data = self.league != "college-baseball"

                if is_favorite_game:
                    self.logger.debug(f"Full situation data: {situation}")
                    self.logger.debug(f"has_count_data: {has_count_data}")

                # Get count from the correct location in the API response
                count = situation.get("count", {})
                balls = count.get("balls", 0)
                strikes = count.get("strikes", 0)
                outs = situation.get("outs", 0)

                # Add detailed logging for favorite team games
                if is_favorite_game:
                    self.logger.debug(f"Full situation data: {situation}")
                    self.logger.debug(f"Count object: {count}")
                    self.logger.debug(
                        f"Raw count values - balls: {balls}, strikes: {strikes}"
                    )
                    self.logger.debug(f"Raw outs value: {outs}")

                # Try alternative locations for count data
                if balls == 0 and strikes == 0:
                    # First try the summary field
                    if "summary" in situation:
                        try:
                            count_summary = situation["summary"]
                            balls, strikes = map(int, count_summary.split("-", 1))
                            if is_favorite_game:
                                self.logger.debug(
                                    f"Using summary count: {count_summary}"
                                )
                        except (ValueError, AttributeError):
                            if is_favorite_game:
                                self.logger.debug("Could not parse summary count")
                    else:
                        # Check if count is directly in situation
                        balls = situation.get("balls", 0)
                        strikes = situation.get("strikes", 0)
                        if is_favorite_game:
                            self.logger.debug(
                                f"Using direct situation count: balls={balls}, strikes={strikes}"
                            )
                            self.logger.debug(
                                f"Full situation keys: {list(situation.keys())}"
                            )

                if is_favorite_game:
                    self.logger.debug(f"Final count: balls={balls}, strikes={strikes}")

                # Get base runners
                bases_occupied = [
                    situation.get("onFirst", False),
                    situation.get("onSecond", False),
                    situation.get("onThird", False),
                ]

                if is_favorite_game:
                    self.logger.debug(f"Bases occupied: {bases_occupied}")
            else:
                # Default values for non-live games
                inning = 1
                inning_half = "top"
                balls = 0
                strikes = 0
                outs = 0
                bases_occupied = [False, False, False]
                has_count_data = False

            details.update(
                {
                    "status": game_status,
                    "status_state": status_state,
                    "inning": inning,
                    "inning_half": inning_half,
                    "balls": balls,
                    "strikes": strikes,
                    "outs": outs,
                    "bases_occupied": bases_occupied,
                    "has_count_data": has_count_data,
                    "start_time": game_event["date"],
                    "series_summary": series_summary,
                }
            )

            # Basic validation (can be expanded)
            if not details["home_abbr"] or not details["away_abbr"]:
                self.logger.warning(
                    f"Missing team abbreviation in event: {details['id']}"
                )
                return None

            self.logger.debug(
                f"Extracted: {details['away_abbr']}@{details['home_abbr']}, Status: {status['type']['name']}, Live: {details['is_live']}, Final: {details['is_final']}, Upcoming: {details['is_upcoming']}"
            )

            return details
        except Exception as e:
            # Log the problematic event structure if possible
            self.logger.error(
                f"Error extracting game details: {e} from event: {game_event.get('id')}",
                exc_info=True,
            )
            return None

    def display_series_summary(self, game: dict, draw_overlay: ImageDraw.ImageDraw):
        if not self.show_series_summary:
            return

        series_summary = game.get("series_summary", "")
        bbox = draw_overlay.textbbox((0, 0), series_summary, font=self.fonts['time'])
        height = bbox[3] - bbox[1]
        shots_y = (self.display_height - height) // 2
        shots_width = draw_overlay.textlength(series_summary, font=self.fonts['time'])
        shots_x = (self.display_width - shots_width) // 2
        self._draw_text_with_outline(
            draw_overlay, series_summary, (shots_x, shots_y), self.fonts['time']
        )

class BaseballRecent(Baseball, SportsRecent):
    """Base class for recent baseball games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)


    def _custom_scorebug_layout(self, game: dict, draw_overlay: ImageDraw.ImageDraw):
        self.display_series_summary(game, draw_overlay)


class BaseballLive(Baseball, SportsLive):
    """Base class for live baseball games."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        # Pitcher/batter/last-play: keyed by game id, holds the resolved
        # {"pitcher", "batter", "last_play_code"}. Kept separate from
        # current_game/live_games since those get fully rebuilt from fresh
        # scoreboard data on every poll and would silently drop extra keys.
        self._play_by_play_cache: Dict[str, Dict] = {}
        self._play_by_play_last_attempt: Dict[str, float] = {}
        self.play_by_play_update_interval = self.mode_config.get(
            "play_by_play_update_interval", 20
        )
        # Dedicated at-bat-info rotating screen timing state.
        self._at_bat_screen_last_shown = 0.0
        self._at_bat_screen_showing_until = 0.0

    def update(self):
        super().update()
        if self.test_mode:
            return
        if not (self.show_pitcher_batter or self.show_last_play):
            return
        if not self.espn_summary_sport_league:
            return
        if not self.current_game:
            return

        game_id = self.current_game.get("id")
        if not game_id:
            return

        now = time.time()
        last_attempt = self._play_by_play_last_attempt.get(game_id, 0)
        if now - last_attempt >= self.play_by_play_update_interval:
            self._play_by_play_last_attempt[game_id] = now
            self._fetch_play_by_play(game_id)

        self._prune_stale_play_by_play()

    def _prune_stale_play_by_play(self) -> None:
        """Drop cached/attempted entries for games no longer live so this
        doesn't grow unbounded across a long-running session."""
        live_ids = {g.get("id") for g in self.live_games}
        for gid in list(self._play_by_play_cache.keys()):
            if gid not in live_ids:
                del self._play_by_play_cache[gid]
        for gid in list(self._play_by_play_last_attempt.keys()):
            if gid not in live_ids:
                del self._play_by_play_last_attempt[gid]

    def _fetch_play_by_play(self, game_id: str) -> None:
        """Fetch and parse the ESPN game summary for one game, off-thread.

        Mirrors SportsCore._fetch_odds's background-thread-with-bounded-
        timeout pattern (sports.py) so a slow/heavy per-game summary
        response can never block the render/update loop -- on timeout or
        error we simply keep whatever was cached from the previous
        successful fetch (or nothing, if there wasn't one yet).
        """
        import threading
        import queue

        sport, league = self.espn_summary_sport_league
        result_queue = queue.Queue()

        def fetch():
            try:
                data = self.data_source.fetch_game_summary(sport, league, game_id)
                result_queue.put(("success", data))
            except Exception as e:
                result_queue.put(("error", e))

        thread = threading.Thread(target=fetch)
        thread.daemon = True
        thread.start()

        try:
            result_type, result_data = result_queue.get(timeout=2.0)
        except queue.Empty:
            self.logger.debug(
                f"Play-by-play fetch timed out for game {game_id} (non-blocking)"
            )
            return

        if result_type != "success" or not result_data:
            self.logger.debug(
                f"Play-by-play fetch failed for game {game_id}: {result_data}"
            )
            return

        try:
            plays = result_data.get("plays") or []
            rosters = result_data.get("rosters") or []
            athlete_names = _build_athlete_name_map(rosters)
            pitcher, batter = _get_current_pitcher_batter(plays, athlete_names)
            last_play_code = _get_last_play_code(plays)
            self._play_by_play_cache[game_id] = {
                "pitcher": pitcher,
                "batter": batter,
                "last_play_code": last_play_code,
            }
        except Exception as e:
            self.logger.error(f"Error parsing play-by-play for game {game_id}: {e}")

    # Sample data cycled through in test_mode so the at-bat info screen's
    # real draw path (font/color/dwell/interval config) gets exercised
    # offline, with zero network calls.
    _TEST_MODE_AT_BAT_SAMPLES = [
        {"pitcher": "G. Cole", "batter": "J. Soto", "last_play_code": "1B"},
        {"pitcher": "G. Cole", "batter": "A. Judge", "last_play_code": "K"},
        {"pitcher": "Y. Yamamoto", "batter": "F. Freeman", "last_play_code": "HR"},
        {"pitcher": "Y. Yamamoto", "batter": "M. Betts", "last_play_code": "BB"},
    ]

    def _test_mode_update(self):
        if self.current_game and self.current_game["is_live"]:
            if self.current_game["inning_half"] == "top":
                self.current_game["inning_half"] = "bottom"
            else:
                self.current_game["inning_half"] = "top"
                self.current_game["inning"] += 1
            self.current_game["balls"] = (self.current_game["balls"] + 1) % 4
            self.current_game["strikes"] = (self.current_game["strikes"] + 1) % 3
            self.current_game["outs"] = (self.current_game["outs"] + 1) % 3
            self.current_game["bases_occupied"] = [
                not b for b in self.current_game["bases_occupied"]
            ]
            if self.current_game["inning"] % 2 == 0:
                self.current_game["home_score"] = str(
                    int(self.current_game["home_score"]) + 1
                )
            else:
                self.current_game["away_score"] = str(
                    int(self.current_game["away_score"]) + 1
                )

            if self.show_pitcher_batter or self.show_last_play:
                game_id = self.current_game.get("id", "test")
                sample_index = self.current_game["inning"] % len(
                    self._TEST_MODE_AT_BAT_SAMPLES
                )
                self._play_by_play_cache[game_id] = self._TEST_MODE_AT_BAT_SAMPLES[
                    sample_index
                ]

    def _maybe_draw_at_bat_info_screen(self, game: Dict, force_clear: bool = False) -> bool:
        """Rotate in the dedicated pitcher/batter/last-play screen if it's
        due. Returns True if it drew (caller should skip the normal
        scorebug draw for this frame), False otherwise.
        """
        if not (self.show_pitcher_batter or self.show_last_play):
            return False

        pbp = self._play_by_play_cache.get(game.get("id"))
        if not pbp or not (
            pbp.get("pitcher") or pbp.get("batter") or pbp.get("last_play_code")
        ):
            return False

        at_bat_cfg = self.config.get("customization", {}).get("at_bat_info", {})
        dwell = at_bat_cfg.get("dwell_seconds", 4)
        interval = at_bat_cfg.get("interval_seconds", 25)

        now = time.time()
        showing = now < self._at_bat_screen_showing_until
        if not showing and now - self._at_bat_screen_last_shown >= interval:
            self._at_bat_screen_last_shown = now
            self._at_bat_screen_showing_until = now + dwell
            showing = True

        if not showing:
            return False

        self._draw_at_bat_info_screen(game, pbp, force_clear)
        return True

    @staticmethod
    def _truncate_to_width(draw, text: str, font, max_width: int) -> str:
        """Hard-truncate text (no ellipsis -- pixel fonts render one poorly
        at small sizes) so it never draws past the panel edge. A long
        player name is more useful clipped than overlapping the next
        line's outline or bleeding off-canvas."""
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        truncated = text
        while len(truncated) > 1:
            truncated = truncated[:-1]
            if draw.textbbox((0, 0), truncated, font=font)[2] <= max_width:
                return truncated
        return truncated

    def _draw_at_bat_info_screen(
        self, game: Dict, pbp: Dict, force_clear: bool = False
    ) -> None:
        """Draw the dedicated pitcher/batter/last-play screen.

        This replaces the normal scorebug while it's showing rather than
        overlaying on top of it -- there isn't enough room on the scorebug,
        especially at small display sizes, to add this text without
        crowding or clipping the existing elements.
        """
        try:
            img = Image.new("RGB", (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            at_bat_cfg = self.config.get("customization", {}).get("at_bat_info", {})
            font = self._load_custom_font_from_element_config(at_bat_cfg, default_size=6)

            pitcher_color = tuple(at_bat_cfg.get("pitcher_color", [255, 255, 255]))
            batter_color = tuple(at_bat_cfg.get("batter_color", [255, 255, 0]))
            last_play_color = tuple(at_bat_cfg.get("last_play_color", [0, 255, 255]))

            lines = []
            if self.show_pitcher_batter and pbp.get("pitcher"):
                lines.append((f"P: {pbp['pitcher']}", pitcher_color))
            if self.show_pitcher_batter and pbp.get("batter"):
                lines.append((f"B: {pbp['batter']}", batter_color))
            if self.show_last_play and pbp.get("last_play_code"):
                lines.append((pbp["last_play_code"], last_play_color))

            if not lines:
                return

            try:
                bbox = font.getbbox("Ay")
                line_height = bbox[3] - bbox[1] + 2
            except AttributeError:
                line_height = 10

            total_height = line_height * len(lines)
            y = max(1, (self.display_height - total_height) // 2)
            max_text_width = self.display_width - 4  # 2px padding each side

            for text, color in lines:
                if y >= self.display_height:
                    break
                text = self._truncate_to_width(draw, text, font, max_text_width)
                self._draw_text_with_outline(draw, text, (2, y), font, fill=color)
                y += line_height

            self.display_manager.image.paste(img, (0, 0))
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error drawing at-bat info screen: {e}", exc_info=True)

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the detailed scorebug layout for a live baseball game."""
        if self._maybe_draw_at_bat_info_screen(game, force_clear):
            return
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(
                overlay
            )  # Draw text elements on overlay first

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
                # Draw placeholder text if logos fail
                error_img = main_img.convert("RGB")
                draw_final = ImageDraw.Draw(error_img)
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image.paste(error_img, (0, 0))
                self.display_manager.update_display()
                return

            center_y = self.display_height // 2

            # Draw logos with slight edge bleed
            home_x = (
                self.display_width - home_logo.width + 2
            )
            home_y = center_y - (home_logo.height // 2)
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -2
            away_y = center_y - (away_logo.height // 2)
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # --- Live Game Specific Elements ---

            # Define default text color

            # Draw Inning (Top Center)
            if game["is_final"]:
                inning_text = "FINAL"
            else:
                inning_half_indicator = (
                    "▲" if game["inning_half"].lower() == "top" else "▼"
                )
                inning_text = f"{inning_half_indicator}{game['inning']}"

            inning_bbox = draw_overlay.textbbox(
                (0, 0), inning_text, font=self.display_manager.font
            )
            inning_width = inning_bbox[2] - inning_bbox[0]
            inning_x = (self.display_width - inning_width) // 2
            inning_y = 1  # Position near top center
            self._draw_text_with_outline(
                draw_overlay,
                inning_text,
                (inning_x, inning_y),
                self.display_manager.font,
            )

            # --- REVISED BASES AND OUTS DRAWING ---
            bases_occupied = game["bases_occupied"]  # [1st, 2nd, 3rd]
            outs = game.get("outs", 0)
            inning_half = game["inning_half"]

            # Read configurable game display settings
            customization = self.config.get('customization', {})
            bases_cfg = customization.get('bases', {})
            outs_cfg = customization.get('outs', {})
            count_cfg = customization.get('count', {})

            # Define geometry (configurable with defaults matching original)
            base_diamond_size = bases_cfg.get('diamond_size', 7)
            out_circle_diameter = outs_cfg.get('circle_diameter', 3)
            out_vertical_spacing = outs_cfg.get('spacing', 2)
            spacing_between_bases_outs = outs_cfg.get('distance_from_bases', 3)
            base_vert_spacing = 1  # Internal vertical space in base cluster
            base_horiz_spacing = 1  # Internal horizontal space in base cluster

            # Calculate cluster dimensions
            base_cluster_height = (
                base_diamond_size + base_vert_spacing + base_diamond_size
            )
            base_cluster_width = (
                base_diamond_size + base_horiz_spacing + base_diamond_size
            )
            out_cluster_height = 3 * out_circle_diameter + 2 * out_vertical_spacing
            out_cluster_width = out_circle_diameter

            # Calculate overall start positions
            overall_start_y = (
                inning_bbox[3] + 0
            )  # Start immediately below inning text

            # Center the BASE cluster horizontally (with optional offset)
            bases_origin_x = (self.display_width - base_cluster_width) // 2 + bases_cfg.get('x_offset', 0)
            overall_start_y += bases_cfg.get('y_offset', 0)

            # Determine relative positions for outs based on inning half
            # Only compute outs column position when count data is available
            has_count_data = game.get("has_count_data", True)
            if has_count_data:
                if inning_half == "top":  # Away batting, outs on left
                    outs_column_x = (
                        bases_origin_x - spacing_between_bases_outs - out_cluster_width
                    )
                else:  # Home batting, outs on right
                    outs_column_x = (
                        bases_origin_x + base_cluster_width + spacing_between_bases_outs
                    )

                # Calculate vertical alignment offset for outs column (center align with bases cluster)
                outs_column_start_y = (
                    overall_start_y + (base_cluster_height // 2) - (out_cluster_height // 2)
                )

            # --- Draw Bases (Diamonds) ---
            base_color_occupied = tuple(bases_cfg.get('occupied_color', [255, 255, 255]))
            base_color_empty = tuple(bases_cfg.get('empty_color', [255, 255, 255]))
            h_d = base_diamond_size // 2

            # 2nd Base (Top center relative to bases_origin_x)
            c2x = bases_origin_x + base_cluster_width // 2
            c2y = overall_start_y + h_d
            poly2 = [
                (c2x, overall_start_y),
                (c2x + h_d, c2y),
                (c2x, c2y + h_d),
                (c2x - h_d, c2y),
            ]
            if bases_occupied[1]:
                draw_overlay.polygon(poly2, fill=base_color_occupied)
            else:
                draw_overlay.polygon(poly2, outline=base_color_empty)

            base_bottom_y = c2y + h_d  # Bottom Y of 2nd base diamond

            # 3rd Base (Bottom left relative to bases_origin_x)
            c3x = bases_origin_x + h_d
            c3y = base_bottom_y + base_vert_spacing + h_d
            poly3 = [
                (c3x, base_bottom_y + base_vert_spacing),
                (c3x + h_d, c3y),
                (c3x, c3y + h_d),
                (c3x - h_d, c3y),
            ]
            if bases_occupied[2]:
                draw_overlay.polygon(poly3, fill=base_color_occupied)
            else:
                draw_overlay.polygon(poly3, outline=base_color_empty)

            # 1st Base (Bottom right relative to bases_origin_x)
            c1x = bases_origin_x + base_cluster_width - h_d
            c1y = base_bottom_y + base_vert_spacing + h_d
            poly1 = [
                (c1x, base_bottom_y + base_vert_spacing),
                (c1x + h_d, c1y),
                (c1x, c1y + h_d),
                (c1x - h_d, c1y),
            ]
            if bases_occupied[0]:
                draw_overlay.polygon(poly1, fill=base_color_occupied)
            else:
                draw_overlay.polygon(poly1, outline=base_color_empty)

            # --- Draw Outs (Vertical Circles) ---
            # Only render outs and count when data is available (ESPN NCAA doesn't provide these)
            if has_count_data:
                circle_color_out = tuple(outs_cfg.get('counted_color', [255, 255, 255]))
                circle_color_empty_outline = tuple(outs_cfg.get('empty_color', [100, 100, 100]))

                for i in range(3):
                    cx = outs_column_x
                    cy = outs_column_start_y + i * (
                        out_circle_diameter + out_vertical_spacing
                    )
                    coords = [cx, cy, cx + out_circle_diameter, cy + out_circle_diameter]
                    if i < outs:
                        draw_overlay.ellipse(coords, fill=circle_color_out)
                    else:
                        draw_overlay.ellipse(coords, outline=circle_color_empty_outline)

            # --- Draw Balls-Strikes Count (BDF Font) ---
            if has_count_data:
                balls = game.get("balls", 0)
                strikes = game.get("strikes", 0)

                # Add debug logging for count with cooldown
                current_time = time.time()
                if (
                    game["home_abbr"] in self.favorite_teams
                    or game["away_abbr"] in self.favorite_teams
                ) and current_time - self.last_count_log_time >= self.count_log_interval:
                    self.logger.debug(f"Displaying count: {balls}-{strikes}")
                    self.logger.debug(
                        f"Raw count data: balls={game.get('balls')}, strikes={game.get('strikes')}"
                    )
                    self.last_count_log_time = current_time

                count_text = f"{balls}-{strikes}"
                bdf_font = self.display_manager.calendar_font
                if not hasattr(self, '_bdf_font_sized'):
                    bdf_font.set_char_size(height=7 * 64)  # Set 7px height once
                    self._bdf_font_sized = True
                count_text_width = self.display_manager.get_text_width(count_text, bdf_font)

                # Position below the base/out cluster
                cluster_bottom_y = (
                    overall_start_y + base_cluster_height
                )  # Find the bottom of the taller part (bases)
                count_y = cluster_bottom_y + count_cfg.get('y_offset', 2)

                # Center horizontally within the BASE cluster width
                count_x = bases_origin_x + (base_cluster_width - count_text_width) // 2

                # Temporarily set draw object for BDF text rendering, then restore
                original_draw = self.display_manager.draw
                self.display_manager.draw = draw_overlay
                try:
                    # Draw Balls-Strikes Count with outline using BDF font
                    outline_color_for_bdf = (0, 0, 0)

                    # Draw outline
                    for dx_offset, dy_offset in [
                        (-1, -1),
                        (-1, 0),
                        (-1, 1),
                        (0, -1),
                        (0, 1),
                        (1, -1),
                        (1, 0),
                        (1, 1),
                    ]:
                        self.display_manager._draw_bdf_text(
                            count_text,
                            count_x + dx_offset,
                            count_y + dy_offset,
                            color=outline_color_for_bdf,
                            font=bdf_font,
                        )

                    # Draw main text
                    count_text_color = tuple(count_cfg.get('text_color', [255, 255, 255]))
                    self.display_manager._draw_bdf_text(
                        count_text, count_x, count_y, color=count_text_color, font=bdf_font
                    )
                finally:
                    self.display_manager.draw = original_draw

            # Draw Team:Score at the bottom (matching main branch format)
            score_font = self.display_manager.font  # Use PressStart2P
            outline_color = (0, 0, 0)
            score_text_color = (
                255,
                255,
                255,
            )

            # Helper function for outlined text
            def draw_bottom_outlined_text(x, y, text):
                self._draw_text_with_outline(
                    draw_overlay,
                    text,
                    (x, y),
                    score_font,
                    fill=score_text_color,
                    outline_color=outline_color,
                )

            away_abbr = game["away_abbr"]
            home_abbr = game["home_abbr"]
            away_score_str = str(game["away_score"])
            home_score_str = str(game["home_score"])

            away_text = f"{away_abbr}:{away_score_str}"
            home_text = f"{home_abbr}:{home_score_str}"

            # Calculate Y position (bottom edge)
            try:
                font_height = score_font.getbbox("A")[3] - score_font.getbbox("A")[1]
            except AttributeError:
                font_height = 8  # Fallback for default font
            score_y = (
                self.display_height - font_height - 2
            )  # 2 pixels padding from bottom

            # Away Team:Score (Bottom Left)
            away_score_x = 2  # 2 pixels padding from left
            draw_bottom_outlined_text(away_score_x, score_y, away_text)

            # Home Team:Score (Bottom Right)
            home_text_bbox = draw_overlay.textbbox((0, 0), home_text, font=score_font)
            home_text_width = home_text_bbox[2] - home_text_bbox[0]
            home_score_x = (
                self.display_width - home_text_width - 2
            )  # 2 pixels padding from right
            draw_bottom_outlined_text(home_score_x, score_y, home_text)

            # Draw gambling odds if available
            if game.get("odds"):
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height
                )

            # Composite the text overlay onto the main image
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")  # Convert for display

            # Display the final image
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()  # Update display here for live

        except Exception as e:
            self.logger.error(
                f"Error displaying live Baseball game: {e}", exc_info=True
            )
