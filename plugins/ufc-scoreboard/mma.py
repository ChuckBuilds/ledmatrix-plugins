"""MMA Base Classes - Adapted from original work by Alex Resnick (legoguy1000) - PR #137"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# Pillow < 9.1.0 compat: LANCZOS was added in 9.1.0
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

from data_sources import ESPNDataSource
from sports import (
    SportsCore,
    SportsLive,
    SportsRecent,
    SportsUpcoming,
    _DEFAULT_LOOKAHEAD_DAYS,
    _DEFAULT_LOOKBACK_DAYS,
    _status_is_final,
)

#: Content types accepted as a headshot download.
_HEADSHOT_CONTENT_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/gif")

#: Backoff for a headshot that could not be fetched: first retry after this
#: long, doubling per consecutive failure up to HEADSHOT_RETRY_MAX_SECONDS.
#: About 9% of fighters on a current card have no ESPN headshot at all (a 404),
#: so a failure is the normal case for them, not a transient one -- but ESPN
#: does add images later, so it is retried, just rarely.
HEADSHOT_RETRY_INITIAL_SECONDS = 15 * 60
HEADSHOT_RETRY_MAX_SECONDS = 6 * 60 * 60

#: fighter_id -> (consecutive failures, monotonic time the next try is due).
#: Module-level so the Live, Recent and Upcoming managers -- and the managers a
#: config reload rebuilds -- share one record instead of each paying for the
#: same missing image.
_headshot_failures: Dict[str, Tuple[int, float]] = {}
#: fighter ids whose download is running right now (update() can be entered
#: from the core scheduler and a draw-time refresh thread at once).
_headshot_inflight: set = set()
_headshot_lock = threading.Lock()


class MMA(SportsCore):
    """Base class for MMA sports with common functionality."""

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
        self.sport = "mma"
        self.favorite_fighters = [
            f.lower() for f in self.mode_config.get("favorite_fighters", [])
        ]
        self.favorite_weight_class = [
            wc.lower() for wc in self.mode_config.get("favorite_weight_class", [])
        ]

    def _custom_scorebug_layout(self, game: dict, draw: ImageDraw.ImageDraw):
        """No-op hook for subclasses to add custom scorebug elements."""

    def _draw_fighter_records(
        self,
        draw_overlay: ImageDraw.Draw,
        game: Dict,
        left_x: int = 0,
        right_margin: int = 0,
        bottom_offset: int = 0,
    ) -> None:
        """Draw fighter records at the bottom of the display.

        Args:
            draw_overlay: ImageDraw overlay to draw on
            game: Fight data dict with fighter1_record/fighter2_record
            left_x: X position for left-side record
            right_margin: Pixels from right edge for right-side record
            bottom_offset: Extra offset from the bottom
        """
        record_font = self.fonts.get("record") or self.fonts.get("status")
        if not record_font:
            record_font = ImageFont.load_default()

        fighter1_record = game.get("fighter1_record", "")
        fighter2_record = game.get("fighter2_record", "")

        record_bbox = draw_overlay.textbbox((0, 0), "0-0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - bottom_offset

        # Fighter 2 record (left side)
        if fighter2_record:
            self._draw_text_with_outline(
                draw_overlay, fighter2_record, (left_x, record_y), record_font
            )

        # Fighter 1 record (right side)
        if fighter1_record:
            f1_bbox = draw_overlay.textbbox((0, 0), fighter1_record, font=record_font)
            f1_width = f1_bbox[2] - f1_bbox[0]
            f1_x = self.display_width - f1_width - right_margin
            self._draw_text_with_outline(
                draw_overlay, fighter1_record, (f1_x, record_y), record_font
            )

    def _load_and_resize_headshot(
        self, fighter_id: str, fighter_name: str, image_path: Path, image_url: str = None
    ) -> Optional[Image.Image]:
        """A fighter headshot from the in-memory cache or disk, or None.

        Called from display(), so it never touches the network. It used to
        download a missing image right here, and cache only successes: a
        fighter ESPN has no headshot for (a 404, about 9% of a current card)
        was re-requested on every frame, logged an ERROR with a traceback each
        time, and the card drew "Image Error" instead of the fight. Missing
        images are now fetched by update() -- see _fetch_missing_headshots() --
        and a card with no headshot is drawn without it.

        image_url is unused here and kept for callers' signatures.
        """
        if fighter_id in self._logo_cache:
            return self._cached_logo(fighter_id)
        if not fighter_id or image_path is None:
            return None
        image_path = Path(image_path)
        try:
            if not image_path.exists():
                return None
            with Image.open(image_path) as logo:
                if logo.mode != "RGBA":
                    logo = logo.convert("RGBA")
                max_width = int(self.display_width * 1.5)
                max_height = int(self.display_height * 1.5)
                logo.thumbnail((max_width, max_height), LANCZOS)
                logo.load()  # Ensure pixel data is loaded before closing file
        except (OSError, ValueError, SyntaxError) as e:
            # A truncated or non-image file. Remove it so update() can fetch a
            # good copy -- subject to the same backoff as a failed download --
            # rather than failing to decode it on every frame.
            try:
                image_path.unlink()
            except OSError:
                pass
            self._record_headshot_failure(
                fighter_id, fighter_name, f"unreadable file {image_path.name}: {e}")
            return None
        self._cache_logo(fighter_id, logo)
        return logo

    def _headshot_candidates(self) -> Iterator[Tuple[str, str, Any, Any]]:
        """(fighter_id, name, image_path, image_url) for every fight this manager holds."""
        fights = []
        for attr in ("games_list", "live_games"):
            fights.extend(getattr(self, attr, None) or [])
        current = getattr(self, "current_game", None)
        if current:
            fights.append(current)
        seen = set()
        for fight in fights:
            if not isinstance(fight, dict):
                continue
            for n in ("1", "2"):
                fighter_id = fight.get(f"fighter{n}_id")
                if not fighter_id or fighter_id in seen:
                    continue
                seen.add(fighter_id)
                yield (fighter_id, fight.get(f"fighter{n}_name", fighter_id),
                       fight.get(f"fighter{n}_image_path"),
                       fight.get(f"fighter{n}_image_url"))

    def _fetch_missing_headshots(self, now: Optional[float] = None) -> None:
        """Download headshots the held fights need. Runs from update(), never display().

        A fighter already decoded, already on disk, being fetched by another
        thread, or inside its failure backoff is skipped, so on the calls where
        nothing is missing this is a dict lookup and a stat per fighter.
        """
        now = time.monotonic() if now is None else now
        for fighter_id, name, image_path, image_url in list(self._headshot_candidates()):
            if fighter_id in self._logo_cache or image_path is None:
                continue
            image_path = Path(image_path)
            if image_path.exists():
                continue
            with _headshot_lock:
                failures = _headshot_failures.get(fighter_id)
                if failures is not None and now < failures[1]:
                    continue
                if fighter_id in _headshot_inflight:
                    continue
                _headshot_inflight.add(fighter_id)
            try:
                if self._download_headshot(fighter_id, name, image_path, image_url, now=now):
                    with _headshot_lock:
                        _headshot_failures.pop(fighter_id, None)
            finally:
                with _headshot_lock:
                    _headshot_inflight.discard(fighter_id)

    def _download_headshot(
        self, fighter_id: str, fighter_name: str, image_path: Path,
        image_url: Optional[str], now: Optional[float] = None,
    ) -> bool:
        """Fetch one headshot to disk. True on success; a failure is recorded, not raised."""
        if not image_url:
            self._record_headshot_failure(fighter_id, fighter_name, "no image URL", now)
            return False
        tmp_path = image_path.with_name(f".{image_path.name}.{os.getpid()}.tmp")
        try:
            image_path.parent.mkdir(parents=True, exist_ok=True)
            response = self.session.get(image_url, headers=self.headers, timeout=15)
            if response.status_code == 404:
                self._record_headshot_failure(
                    fighter_id, fighter_name, "ESPN has no headshot (404)", now)
                return False
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not any(kind in content_type for kind in _HEADSHOT_CONTENT_TYPES):
                self._record_headshot_failure(
                    fighter_id, fighter_name, f"not an image ({content_type or 'no type'})", now)
                return False
            tmp_path.write_bytes(response.content)
            # Verify and normalise before it becomes visible to display(), which
            # would otherwise see a half-written file.
            with Image.open(tmp_path) as img:
                img = img.convert("RGBA") if img.mode != "RGBA" else img
                img.load()
            img.save(tmp_path, "PNG")
            os.replace(tmp_path, image_path)
        except Exception as e:  # pylint: disable=broad-except
            # Network, HTTP, disk and decode errors all end the same way: no
            # image this time, try again after the backoff.
            self._record_headshot_failure(
                fighter_id, fighter_name, f"{type(e).__name__}: {e}", now)
            try:
                tmp_path.unlink()
            except OSError:
                pass
            return False
        self.logger.info(f"Downloaded headshot for {fighter_name} -> {image_path.name}")
        return True

    def _record_headshot_failure(
        self, fighter_id: str, fighter_name: str, reason: str, now: Optional[float] = None
    ) -> None:
        """Back off before the next attempt; one WARNING per attempt, never per frame."""
        now = time.monotonic() if now is None else now
        with _headshot_lock:
            count = _headshot_failures.get(fighter_id, (0, 0.0))[0] + 1
            delay = min(HEADSHOT_RETRY_INITIAL_SECONDS * (2 ** (count - 1)),
                        HEADSHOT_RETRY_MAX_SECONDS)
            _headshot_failures[fighter_id] = (count, now + delay)
        self.logger.warning(
            f"No headshot for {fighter_name} ({reason}); drawing the fight without "
            f"it, next try in {delay // 60:.0f} min"
        )

    def _extract_game_details(self, game_event: dict) -> Optional[Dict]:
        if not game_event:
            return None
        try:
            competition = game_event["competitions"][0]
            status = competition["status"]
            competitors = competition["competitors"]
            game_date_str = game_event["date"]
            start_time_utc = None
            try:
                start_time_utc = datetime.fromisoformat(
                    game_date_str.replace("Z", "+00:00")
                )
            except ValueError:
                self.logger.warning(f"Could not parse game date: {game_date_str}")

            try:
                fight_class = competition["type"]["abbreviation"]
            except KeyError:
                fight_class = ""

            fighter1 = next((c for c in competitors if c.get("order") == 1), None)
            fighter2 = next((c for c in competitors if c.get("order") == 2), None)

            if not fighter1 or not fighter2:
                self.logger.warning(
                    f"Could not find Fighter 1 or 2 in event: {competition.get('id')}"
                )
                return None

            try:
                fighter1_name = fighter1["athlete"]["fullName"]
                fighter1_name_short = fighter1["athlete"]["shortName"]
            except KeyError:
                fighter1_name = ""
                fighter1_name_short = ""
            try:
                fighter2_name = fighter2["athlete"]["fullName"]
                fighter2_name_short = fighter2["athlete"]["shortName"]
            except KeyError:
                fighter2_name = ""
                fighter2_name_short = ""

            # Check if this is a favorite fighter/weight class match before doing expensive logging
            is_favorite_game = (
                fighter1_name.lower() in self.favorite_fighters
                or fighter2_name.lower() in self.favorite_fighters
            ) or fight_class.lower() in self.favorite_weight_class

            if is_favorite_game:
                self.logger.debug(
                    f"Processing favorite fight: {competition.get('id')}"
                )
                self.logger.debug(
                    f"Found fighters: {fighter1_name} vs {fighter2_name}, Status: {status['type']['name']}, State: {status['type']['state']}"
                )

            game_time, game_date = "", ""
            if start_time_utc:
                local_time = start_time_utc.astimezone(self._get_timezone())
                game_time = local_time.strftime("%I:%M%p").lstrip("0")

                use_short_date_format = self.config.get("display", {}).get(
                    "use_short_date_format", False
                )
                if use_short_date_format:
                    # %-m/%-d are glibc extensions: strftime raises ValueError on
                    # Windows and musl. Build the same text portably instead.
                    game_date = f"{local_time.month}/{local_time.day}"
                else:
                    game_date = self.display_manager.format_date_with_ordinal(
                        local_time
                    )

            fighter1_record = (
                fighter1.get("records", [{}])[0].get("summary", "")
                if fighter1.get("records")
                else ""
            )
            fighter2_record = (
                fighter2.get("records", [{}])[0].get("summary", "")
                if fighter2.get("records")
                else ""
            )

            # Don't show "0-0" records - set to blank instead
            if fighter1_record in {"0-0", "0-0-0"}:
                fighter1_record = ""
            if fighter2_record in {"0-0", "0-0-0"}:
                fighter2_record = ""

            # Extract scores for live fights (ESPN uses competitor "score" field)
            fighter1_score = fighter1.get("score", "0")
            fighter2_score = fighter2.get("score", "0")

            # Extract round/clock for live fights
            period = status.get("period", 0)
            clock = status.get("displayClock", "")
            period_text = f"R{period}" if period else ""

            details = {
                "event_id": game_event.get("id"),
                "comp_id": competition.get("id"),
                "id": competition.get("id"),
                "game_time": game_time,
                "game_date": game_date,
                "start_time_utc": start_time_utc,
                "status_text": status["type"]["shortDetail"],
                "is_live": status["type"]["state"] == "in",
                # Not state alone: a cancelled or postponed bout is "post" too,
                # and showed on Recent as a finished fight.
                "is_final": _status_is_final(status["type"]),
                "is_upcoming": (
                    status["type"]["state"] == "pre"
                    or status["type"]["name"].lower()
                    in ["scheduled", "pre-game", "status_scheduled"]
                ),
                # MMA has no halftime, but the shared SportsLive.update() reads
                # details["is_halftime"] by subscript for every non-live fight
                # in the feed. Without the key the first scheduled bout raised
                # KeyError and the whole live update was abandoned.
                "is_halftime": False,
                "is_period_break": status["type"]["name"] == "STATUS_END_PERIOD",
                "home_score": str(fighter1_score),
                "away_score": str(fighter2_score),
                "period": period,
                "period_text": period_text,
                "clock": clock,
                "fight_class": fight_class,
                "fighter1_name": fighter1_name,
                "fighter1_name_short": fighter1_name_short,
                "fighter1_id": fighter1.get("id", ""),
                "fighter1_image_path": self.logo_dir
                / Path(f"{fighter1.get('id')}.png"),
                "fighter1_image_url": f"https://a.espncdn.com/combiner/i?img=/i/headshots/mma/players/full/{fighter1.get('id')}.png",
                "fighter1_country_url": fighter1.get("athlete", {})
                .get("flag", {})
                .get("href", ""),
                "fighter1_record": fighter1_record,
                "fighter2_name": fighter2_name,
                "fighter2_name_short": fighter2_name_short,
                "fighter2_id": fighter2.get("id", ""),
                "fighter2_image_path": self.logo_dir
                / Path(f"{fighter2.get('id')}.png"),
                "fighter2_image_url": f"https://a.espncdn.com/combiner/i?img=/i/headshots/mma/players/full/{fighter2.get('id')}.png",
                "fighter2_country_url": fighter2.get("athlete", {})
                .get("flag", {})
                .get("href", ""),
                "fighter2_record": fighter2_record,
                "is_within_window": True,
            }
            return details
        except Exception as e:
            self.logger.error(
                f"Error extracting game details: {e} from event: {game_event.get('id')}",
                exc_info=True,
            )
            return None


class MMARecent(MMA, SportsRecent):
    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the layout for a recently completed MMA fight."""
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(overlay)

            fighter1_image = self._load_and_resize_headshot(
                game["fighter1_id"],
                game["fighter1_name"],
                game["fighter1_image_path"],
                game["fighter1_image_url"],
            )
            fighter2_image = self._load_and_resize_headshot(
                game["fighter2_id"],
                game["fighter2_name"],
                game["fighter2_image_path"],
                game["fighter2_image_url"],
            )

            center_y = self.display_height // 2

            # Fighter 1 (right side) headshot position. A fighter with no
            # headshot (ESPN has none for some) is drawn without one.
            if fighter1_image:
                home_x = (
                    self.display_width
                    - fighter1_image.width
                    + fighter1_image.width // 4
                    + 2
                    + self._get_layout_offset("fighter1_image", "x_offset")
                )
                home_y = center_y - (fighter1_image.height // 2) + self._get_layout_offset("fighter1_image", "y_offset")
                main_img.paste(fighter1_image, (home_x, home_y), fighter1_image)

            # Fighter 2 (left side) headshot position
            if fighter2_image:
                away_x = -2 - fighter2_image.width // 4 + self._get_layout_offset("fighter2_image", "x_offset")
                away_y = center_y - (fighter2_image.height // 2) + self._get_layout_offset("fighter2_image", "y_offset")
                main_img.paste(fighter2_image, (away_x, away_y), fighter2_image)

            # Result text (centered bottom)
            score_text = game.get("status_text", "Final")
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2 + self._get_layout_offset("result_text", "x_offset")
            score_y = self.display_height - 14 + self._get_layout_offset("result_text", "y_offset")
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts["score"]
            )

            # "Final" text (top center)
            status_text = game.get("period_text", "Final")
            status_width = draw_overlay.textlength(status_text, font=self.fonts["time"])
            status_x = (self.display_width - status_width) // 2 + self._get_layout_offset("status_text", "x_offset")
            status_y = 1 + self._get_layout_offset("status_text", "y_offset")
            self._draw_text_with_outline(
                draw_overlay, status_text, (status_x, status_y), self.fonts["time"]
            )

            if game.get("odds"):
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height,
                    top_span=self._top_row_span(
                        draw_overlay, status_text, self.fonts["time"],
                        self._get_layout_offset("status_text", "x_offset")),
                )

            # Draw records if enabled
            if self.show_records:
                self._draw_fighter_records(draw_overlay, game)

            self._custom_scorebug_layout(game, draw_overlay)

            # Composite and display
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(
                f"Error displaying recent fight: {e}", exc_info=True
            )

    def update(self):
        """Update recent games data."""
        if not self.is_enabled:
            return
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        self.last_update = current_time

        try:
            data = self._fetch_data()
            if not data or "events" not in data:
                self.logger.warning("No events found in shared data.")
                if not self.games_list:
                    self.current_game = None
                return

            events = data["events"]
            self.logger.info(f"Processing {len(events)} events from shared data.")

            # How far back the Recent screen looks, from the configured window
            # rather than a fixed 21 days -- see the note in sports.py.
            now = datetime.now(timezone.utc)
            # getattr, because managers are also built without __init__ (the
            # plugin tests do exactly that) and a missing attribute here would
            # raise into the surrounding except and silently skip the filter.
            lookback_days = getattr(
                self, "schedule_lookback_days", _DEFAULT_LOOKBACK_DAYS)
            recent_cutoff = now - timedelta(days=lookback_days)
            self.logger.info(
                f"Current time: {now}, Recent cutoff: {recent_cutoff} "
                f"({lookback_days} days ago)"
            )

            # Process games and filter for final fights within date range
            processed_games = []
            flattened_events = [
                {
                    **{k: v for k, v in event.items() if k != "competitions"},
                    "competitions": [comp],
                }
                for event in events
                for comp in event.get("competitions", [])
            ]
            for event in flattened_events:
                game = self._extract_game_details(event)
                if game and game["is_final"]:
                    game_time = game.get("start_time_utc")
                    if game_time and game_time >= recent_cutoff:
                        processed_games.append(game)

            # Filter for favorite fighters or weight classes
            if self.favorite_fighters or self.favorite_weight_class:
                favorite_team_games = [
                    game
                    for game in processed_games
                    if (
                        game["fighter1_name"].lower() in self.favorite_fighters
                        or game["fighter2_name"].lower() in self.favorite_fighters
                    )
                    or game["fight_class"].lower() in self.favorite_weight_class
                ]
                self.logger.info(
                    f"Found {len(favorite_team_games)} favorite fighter games out of {len(processed_games)} total final games within last 21 days"
                )

                # Sort by game time (most recent first)
                favorite_team_games.sort(
                    key=lambda g: g.get("start_time_utc")
                    or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )

                # Select one fight per favorite fighter (most recent for each)
                team_games = []
                for fighter in self.favorite_fighters:
                    team_specific_games = [
                        game
                        for game in favorite_team_games
                        if (
                            game["fighter1_name"].lower() == fighter.lower()
                            or game["fighter2_name"].lower() == fighter.lower()
                        )
                    ]

                    if team_specific_games:
                        team_specific_games.sort(
                            key=lambda g: g.get("start_time_utc")
                            or datetime.min.replace(tzinfo=timezone.utc),
                            reverse=True,
                        )
                        team_games.append(team_specific_games[0])

                for wc in self.favorite_weight_class:
                    team_specific_games = [
                        game
                        for game in favorite_team_games
                        if game["fight_class"].lower() == wc.lower()
                    ]

                    if team_specific_games:
                        team_specific_games.sort(
                            key=lambda g: g.get("start_time_utc")
                            or datetime.min.replace(tzinfo=timezone.utc),
                            reverse=True,
                        )
                        team_games.append(team_specific_games[0])

                # Deduplicate by converting to set of ids and back
                seen_ids = set()
                unique_team_games = []
                for game in team_games:
                    if game["id"] not in seen_ids:
                        seen_ids.add(game["id"])
                        unique_team_games.append(game)
                team_games = unique_team_games

                for i, game in enumerate(team_games):
                    self.logger.info(
                        f"Fight {i+1} for display: {game['fighter2_name']} vs {game['fighter1_name']} - {game.get('start_time_utc')}"
                    )
            else:
                team_games = processed_games
                self.logger.info(
                    f"Found {len(processed_games)} total final games within last 21 days (no favorite fighters configured)"
                )
                team_games.sort(
                    key=lambda g: g.get("start_time_utc")
                    or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )
                team_games = team_games[: self.recent_games_to_show]

            # Check if the list of games to display has changed
            new_game_ids = {g["id"] for g in team_games}
            current_game_ids = {g["id"] for g in self.games_list}

            if new_game_ids != current_game_ids:
                self.logger.info(
                    f"Found {len(team_games)} final fights within window for display."
                )
                self.games_list = team_games
                if (
                    not self.current_game
                    or not self.games_list
                    or self.current_game["id"] not in new_game_ids
                ):
                    self.current_game_index = 0
                    self.current_game = self.games_list[0] if self.games_list else None
                    self.last_game_switch = current_time
                else:
                    try:
                        self.current_game_index = next(
                            i
                            for i, g in enumerate(self.games_list)
                            if g["id"] == self.current_game["id"]
                        )
                        self.current_game = self.games_list[self.current_game_index]
                    except StopIteration:
                        self.current_game_index = 0
                        self.current_game = self.games_list[0]
                        self.last_game_switch = current_time

            elif self.games_list:
                self.current_game = self.games_list[self.current_game_index]

            if not self.games_list:
                self.logger.info("No relevant recent fights found to display.")
                self.current_game = None

        except Exception as e:
            self.logger.error(
                f"Error updating recent fights: {e}", exc_info=True
            )


class MMAUpcoming(MMA, SportsUpcoming):
    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the layout for an upcoming MMA fight."""
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(overlay)

            fighter1_image = self._load_and_resize_headshot(
                game["fighter1_id"],
                game["fighter1_name"],
                game["fighter1_image_path"],
                game["fighter1_image_url"],
            )
            fighter2_image = self._load_and_resize_headshot(
                game["fighter2_id"],
                game["fighter2_name"],
                game["fighter2_image_path"],
                game["fighter2_image_url"],
            )

            center_y = self.display_height // 2

            # Fighter 1 (right side) headshot position. A fighter with no
            # headshot (ESPN has none for some) is drawn without one.
            if fighter1_image:
                home_x = (
                    self.display_width
                    - fighter1_image.width
                    + fighter1_image.width // 4
                    + 2
                    + self._get_layout_offset("fighter1_image", "x_offset")
                )
                home_y = center_y - (fighter1_image.height // 2) + self._get_layout_offset("fighter1_image", "y_offset")
                main_img.paste(fighter1_image, (home_x, home_y), fighter1_image)

            # Fighter 2 short name (second row left, below fight class)
            fighter2_name_text = game.get("fighter2_name_short", "")
            f2_name_x = 1 + self._get_layout_offset("fighter_names", "x_offset")
            f2_name_y = 9 + self._get_layout_offset("fighter_names", "y_offset")
            self._draw_text_with_outline(
                draw_overlay, fighter2_name_text, (f2_name_x, f2_name_y), self.fonts["detail"]
            )

            # Fighter 2 (left side) headshot position
            if fighter2_image:
                away_x = -2 - fighter2_image.width // 4 + self._get_layout_offset("fighter2_image", "x_offset")
                away_y = center_y - (fighter2_image.height // 2) + self._get_layout_offset("fighter2_image", "y_offset")
                main_img.paste(fighter2_image, (away_x, away_y), fighter2_image)

            # Fighter 1 short name (second row right, below fight class)
            fighter1_name_text = game.get("fighter1_name_short", "")
            fighter1_name_width = draw_overlay.textlength(
                fighter1_name_text, font=self.fonts["detail"]
            )
            fighter1_name_x = self.display_width - fighter1_name_width - 1
            fighter1_name_y = 9 + self._get_layout_offset("fighter_names", "y_offset")
            self._draw_text_with_outline(
                draw_overlay, fighter1_name_text, (fighter1_name_x, fighter1_name_y), self.fonts["detail"]
            )

            # Date and time display (centered bottom)
            game_date = game.get("game_date", "")
            game_time = game.get("game_time", "")
            if game_date and game_time:
                score_text = f"{game_date} {game_time}"
            elif game_time:
                score_text = game_time
            elif game_date:
                score_text = game_date
            else:
                score_text = game.get("status_text", "TBD")

            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2 + self._get_layout_offset("result_text", "x_offset")
            score_y = self.display_height - 14 + self._get_layout_offset("result_text", "y_offset")
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts["score"]
            )

            # Fight class / status text (top center)
            status_text = game.get("fight_class", game.get("status_text", ""))
            if status_text:
                status_width = draw_overlay.textlength(status_text, font=self.fonts["time"])
                status_center_x = (self.display_width - status_width) // 2
                status_center_y = 1
                self._draw_text_with_outline(
                    draw_overlay, status_text, (status_center_x, status_center_y), self.fonts["time"]
                )

            if game.get("odds"):
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height,
                    top_span=self._top_row_span(
                        draw_overlay, status_text, self.fonts["time"]),
                )

            # Draw records if enabled
            if self.show_records:
                self._draw_fighter_records(draw_overlay, game)

            self._custom_scorebug_layout(game, draw_overlay)

            # Composite and display
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(
                f"Error displaying upcoming fight: {e}", exc_info=True
            )

    def update(self):
        """Update upcoming games data."""
        if not self.is_enabled:
            return
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        self.last_update = current_time

        try:
            data = self._fetch_data()
            if not data or "events" not in data:
                self.logger.warning("No events found in shared data.")
                if not self.games_list:
                    self.current_game = None
                return

            events = data["events"]
            self.logger.info(f"Processing {len(events)} events from shared data.")

            processed_games = []
            all_upcoming_games = 0
            favorite_games_found = 0
            flattened_events = [
                {
                    **{k: v for k, v in event.items() if k != "competitions"},
                    "competitions": [comp],
                }
                for event in events
                for comp in event.get("competitions", [])
            ]
            # How far ahead this screen looks (#345). The fetch is season-wide
            # (Jan-Dec), so without a cutoff every fight ESPN had published was
            # eligible and Upcoming filled with cards months out, ignoring
            # schedule_lookahead_days. Mirrors the lookback cutoff on Recent.
            upcoming_cutoff = datetime.now(timezone.utc) + timedelta(
                days=getattr(self, "schedule_lookahead_days", _DEFAULT_LOOKAHEAD_DAYS))
            for event in flattened_events:
                game = self._extract_game_details(event)
                if game and game["is_upcoming"]:
                    all_upcoming_games += 1
                    start_time = game.get("start_time_utc")
                    if start_time and start_time > upcoming_cutoff:
                        continue
                    if self.show_favorite_teams_only and (
                        self.favorite_fighters or self.favorite_weight_class
                    ):
                        is_favorite = (
                            game["fighter1_name"].lower() in self.favorite_fighters
                            or game["fighter2_name"].lower() in self.favorite_fighters
                            or game["fight_class"].lower() in self.favorite_weight_class
                        )
                        if not is_favorite:
                            continue
                        favorite_games_found += 1
                    if self.show_odds:
                        self._fetch_odds(game)
                    processed_games.append(game)

            self.logger.info(f"Found {all_upcoming_games} total upcoming fights in data")
            self.logger.info(
                f"Found {len(processed_games)} upcoming fights after filtering"
            )

            if processed_games:
                for game in processed_games[:3]:
                    self.logger.info(
                        f"  {game['fighter1_name']} vs {game['fighter2_name']} - {game['start_time_utc']}"
                    )

            team_games = processed_games
            team_games.sort(
                key=lambda g: g.get("start_time_utc")
                or datetime.max.replace(tzinfo=timezone.utc)
            )
            team_games = team_games[: self.upcoming_games_to_show]

            should_log = (
                current_time - self.last_log_time >= self.log_interval
                or len(team_games) != len(self.games_list)
                or any(
                    g1["id"] != g2.get("id")
                    for g1, g2 in zip(self.games_list, team_games)
                )
                or (not self.games_list and team_games)
            )

            new_game_ids = {g["id"] for g in team_games}
            current_game_ids = {g["id"] for g in self.games_list}

            if new_game_ids != current_game_ids:
                self.logger.info(
                    f"Found {len(team_games)} upcoming fights within window for display."
                )
                self.games_list = team_games
                if (
                    not self.current_game
                    or not self.games_list
                    or self.current_game["id"] not in new_game_ids
                ):
                    self.current_game_index = 0
                    self.current_game = self.games_list[0] if self.games_list else None
                    self.last_game_switch = current_time
                else:
                    try:
                        self.current_game_index = next(
                            i
                            for i, g in enumerate(self.games_list)
                            if g["id"] == self.current_game["id"]
                        )
                        self.current_game = self.games_list[self.current_game_index]
                    except StopIteration:
                        self.current_game_index = 0
                        self.current_game = self.games_list[0]
                        self.last_game_switch = current_time

            elif self.games_list:
                self.current_game = self.games_list[self.current_game_index]

            if not self.games_list:
                self.logger.info("No relevant upcoming fights found to display.")
                self.current_game = None

            if should_log and not self.games_list:
                self.logger.debug(
                    f"Favorite fighters: {self.favorite_fighters}"
                )
                self.logger.debug(
                    f"Total upcoming fights before filtering: {all_upcoming_games}"
                )
                self.last_log_time = current_time
            elif should_log:
                self.last_log_time = current_time

        except Exception as e:
            self.logger.error(
                f"Error updating upcoming fights: {e}", exc_info=True
            )


class MMALive(MMA, SportsLive):
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
        if self.current_game and self.current_game.get("is_live"):
            clock = self.current_game.get("clock", "05:00")
            period = self.current_game.get("period", 1)
            parts = clock.split(":")
            if len(parts) == 2:
                minutes = int(parts[0])
                seconds = int(parts[1])
            else:
                minutes, seconds = 5, 0
            seconds -= 1
            if seconds < 0:
                seconds = 59
                minutes -= 1
                if minutes < 0:
                    minutes = 4  # MMA rounds are 5 minutes
                    if period < 3:
                        period += 1
                    else:
                        period = 1
            self.current_game["clock"] = f"{minutes:02d}:{seconds:02d}"
            self.current_game["period"] = period

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the detailed scorebug layout for a live MMA fight."""
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(overlay)

            fighter1_image = self._load_and_resize_headshot(
                game["fighter1_id"],
                game["fighter1_name"],
                game["fighter1_image_path"],
                game.get("fighter1_image_url"),
            )
            fighter2_image = self._load_and_resize_headshot(
                game["fighter2_id"],
                game["fighter2_name"],
                game["fighter2_image_path"],
                game.get("fighter2_image_url"),
            )

            center_y = self.display_height // 2

            # Fighter 1 (right side) headshot with layout offsets. A fighter
            # with no headshot (ESPN has none for some) is drawn without one.
            if fighter1_image:
                home_x = (
                    self.display_width - fighter1_image.width + 10
                    + self._get_layout_offset("fighter1_image", "x_offset")
                )
                home_y = center_y - (fighter1_image.height // 2) + self._get_layout_offset("fighter1_image", "y_offset")
                main_img.paste(fighter1_image, (home_x, home_y), fighter1_image)

            # Fighter 2 (left side) headshot with layout offsets
            if fighter2_image:
                away_x = -10 + self._get_layout_offset("fighter2_image", "x_offset")
                away_y = center_y - (fighter2_image.height // 2) + self._get_layout_offset("fighter2_image", "y_offset")
                main_img.paste(fighter2_image, (away_x, away_y), fighter2_image)

            # Round and Clock (top center)
            period_clock_text = (
                f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
            )
            if game.get("is_period_break"):
                period_clock_text = game.get("status_text", "Round Break")

            status_width = draw_overlay.textlength(
                period_clock_text, font=self.fonts["time"]
            )
            status_x = (self.display_width - status_width) // 2 + self._get_layout_offset("status_text", "x_offset")
            status_y = 1 + self._get_layout_offset("status_text", "y_offset")
            self._draw_text_with_outline(
                draw_overlay,
                period_clock_text,
                (status_x, status_y),
                self.fonts["time"],
            )

            # Scores (centered)
            home_score = str(game.get("home_score", "0"))
            away_score = str(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2 + self._get_layout_offset("result_text", "x_offset")
            score_y = (self.display_height // 2) - 3 + self._get_layout_offset("result_text", "y_offset")
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts["score"]
            )

            # Draw odds if available
            if game.get("odds"):
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height,
                    top_span=self._top_row_span(
                        draw_overlay, period_clock_text, self.fonts["time"],
                        self._get_layout_offset("status_text", "x_offset")),
                )

            # Draw records if enabled
            if self.show_records:
                self._draw_fighter_records(
                    draw_overlay, game, left_x=3, right_margin=3, bottom_offset=1
                )

            # Composite the text overlay onto the main image
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")

            # Display the final image
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(
                f"Error displaying live MMA fight: {e}", exc_info=True
            )
