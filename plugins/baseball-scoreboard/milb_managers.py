import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

import pytz

from baseball import Baseball, BaseballLive, BaseballRecent
from sports import SportsUpcoming

# MiLB uses the MLB Stats API (ESPN does not support MiLB scoreboard)
MLB_STATS_BASE_URL = "https://statsapi.mlb.com/api/v1"
# Default MiLB sport IDs: AAA=11, AA=12, High-A=13, Single-A=14
DEFAULT_MILB_SPORT_IDS = [11, 12, 13, 14]


class BaseMiLBManager(Baseball):
    """Base class for MiLB managers with common functionality.

    Unlike other sports that use ESPN's scoreboard API, MiLB uses the MLB Stats API
    (statsapi.mlb.com) since ESPN does not provide a MiLB scoreboard endpoint.
    Data is fetched from the Stats API and converted to ESPN-compatible format
    so it works seamlessly with the SportsCore extraction pipeline.
    """

    # Class variables shared across all MiLB manager instances (Live/Recent/Upcoming)
    # so they can share API data and coordinate warning throttling
    _no_data_warning_logged: ClassVar[bool] = False
    _last_warning_time: ClassVar[float] = 0
    _warning_cooldown: ClassVar[int] = 60  # Only log warnings once per minute
    _shared_data: ClassVar[Optional[Dict]] = None
    _last_shared_update: ClassVar[float] = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        self.logger = logging.getLogger("MiLB")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="milb",
        )

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.live_enabled = display_modes.get("milb_live", False)
        self.recent_enabled = display_modes.get("milb_recent", False)
        self.upcoming_enabled = display_modes.get("milb_upcoming", False)

        # MiLB sport IDs to fetch (configurable)
        self.milb_sport_ids = self.mode_config.get(
            "sport_ids", DEFAULT_MILB_SPORT_IDS
        )

        self.logger.info(
            f"Initialized MiLB manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Live: {self.live_enabled}, Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}"
        )
        self.league = "minor-league-baseball"

    @staticmethod
    def _convert_stats_game_to_espn_event(game: Dict) -> Dict:
        """Convert a single MLB Stats API game to ESPN event format.

        This allows the SportsCore extraction pipeline (_extract_game_details_common
        and _extract_game_details) to process MiLB data identically to ESPN data.
        """
        home = game.get("teams", {}).get("home", {})
        away = game.get("teams", {}).get("away", {})
        home_team = home.get("team", {})
        away_team = away.get("team", {})
        status_obj = game.get("status", {})
        linescore = game.get("linescore", {})

        # Map status
        abstract_state = status_obj.get("abstractGameState", "Preview")
        detailed_state = status_obj.get("detailedState", "")

        if abstract_state == "Live":
            state = "in"
            status_name = "STATUS_IN_PROGRESS"
        elif abstract_state == "Final":
            state = "post"
            status_name = "STATUS_FINAL"
        else:
            state = "pre"
            status_name = "STATUS_SCHEDULED"

        # Build inning detail text
        current_inning = linescore.get("currentInning") or None
        inning_state = linescore.get("inningState", "")
        inning_ordinal = linescore.get("currentInningOrdinal", f"{current_inning}" if current_inning else "")

        if abstract_state == "Final":
            detail_text = "Final"
            short_detail = "Final"
            if current_inning is not None and current_inning != 9:
                detail_text = f"Final/{current_inning}"
                short_detail = f"Final/{current_inning}"
        elif abstract_state == "Live":
            half = "Top" if inning_state.lower().startswith("top") else "Bot"
            if "mid" in inning_state.lower():
                half = "Mid"
            elif "end" in inning_state.lower():
                half = "End"
            detail_text = f"{inning_state} {inning_ordinal}"
            short_detail = f"{half} {inning_ordinal}"
        else:
            detail_text = detailed_state or "Scheduled"
            short_detail = detail_text

        # Build records
        home_record = home.get("leagueRecord", {})
        away_record = away.get("leagueRecord", {})
        home_record_summary = ""
        away_record_summary = ""
        if home_record.get("wins") is not None:
            home_record_summary = f"{home_record.get('wins', 0)}-{home_record.get('losses', 0)}"
        if away_record.get("wins") is not None:
            away_record_summary = f"{away_record.get('wins', 0)}-{away_record.get('losses', 0)}"

        # Build situation (for live games)
        situation = {}
        if abstract_state == "Live" and linescore:
            offense = linescore.get("offense", {})
            situation = {
                "outs": linescore.get("outs", 0),
                "onFirst": bool(offense.get("first")),
                "onSecond": bool(offense.get("second")),
                "onThird": bool(offense.get("third")),
                "count": {
                    "balls": linescore.get("balls", 0),
                    "strikes": linescore.get("strikes", 0),
                },
            }

        # Build ESPN-compatible event structure
        event = {
            "id": str(game.get("gamePk", "")),
            "date": game.get("gameDate", ""),
            "name": f"{away_team.get('name', '')} at {home_team.get('name', '')}",
            "competitions": [
                {
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {
                                "id": str(home_team.get("id", "")),
                                "abbreviation": home_team.get(
                                    "abbreviation",
                                    home_team.get("name", "???")[:3].upper(),
                                ),
                                "name": home_team.get("name", ""),
                                "displayName": home_team.get("name", ""),
                                "shortDisplayName": home_team.get("shortName", home_team.get("name", "")),
                                "logo": "",
                            },
                            "score": str(home.get("score", 0)),
                            "records": [{"summary": home_record_summary}]
                            if home_record_summary
                            else [],
                            "id": str(home_team.get("id", "")),
                        },
                        {
                            "homeAway": "away",
                            "team": {
                                "id": str(away_team.get("id", "")),
                                "abbreviation": away_team.get(
                                    "abbreviation",
                                    away_team.get("name", "???")[:3].upper(),
                                ),
                                "name": away_team.get("name", ""),
                                "displayName": away_team.get("name", ""),
                                "shortDisplayName": away_team.get("shortName", away_team.get("name", "")),
                                "logo": "",
                            },
                            "score": str(away.get("score", 0)),
                            "records": [{"summary": away_record_summary}]
                            if away_record_summary
                            else [],
                            "id": str(away_team.get("id", "")),
                        },
                    ],
                    "status": {
                        "type": {
                            "name": status_name,
                            "state": state,
                            "detail": detail_text,
                            "shortDetail": short_detail,
                            "completed": abstract_state == "Final",
                        },
                        "period": current_inning or 0,
                        "displayClock": "0:00",
                    },
                    "situation": situation or {},
                    "odds": [],
                    "series": {},
                }
            ],
        }

        return event

    def _fetch_from_mlb_stats_api(
        self, start_date: str, end_date: str, sport_ids: Optional[List[int]] = None
    ) -> Optional[Dict]:
        """Fetch MiLB games from the MLB Stats API and convert to ESPN format.

        Uses the startDate/endDate parameters to fetch the entire range in a
        single request instead of one request per date.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            sport_ids: MiLB sport IDs to fetch (default: self.milb_sport_ids)

        Returns:
            ESPN-compatible dict with {"events": [...]} or None on failure
        """
        if sport_ids is None:
            sport_ids = self.milb_sport_ids

        all_events = []
        sport_id_str = ",".join(str(s) for s in sport_ids)

        url = (
            f"{MLB_STATS_BASE_URL}/schedule"
            f"?sportId={sport_id_str}"
            f"&startDate={start_date}&endDate={end_date}"
            f"&hydrate=linescore,team"
        )
        try:
            response = self.session.get(
                url, headers=self.headers, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            for date_entry in data.get("dates", []):
                for game in date_entry.get("games", []):
                    event = self._convert_stats_game_to_espn_event(game)
                    all_events.append(event)

        except Exception as e:
            self.logger.error(
                f"Failed to fetch MiLB data for {start_date} to {end_date}: {e}"
            )
            return None

        if all_events:
            self.logger.info(
                f"Fetched {len(all_events)} MiLB games from MLB Stats API"
            )
        else:
            self.logger.debug("No MiLB games found from MLB Stats API")

        return {"events": all_events}

    def _fetch_todays_games(self) -> Optional[Dict]:
        """Override SportsCore's ESPN-based fetch with MLB Stats API fetch."""
        now = datetime.now(pytz.utc)
        today = now.strftime("%Y-%m-%d")
        self.logger.debug(f"Fetching today's MiLB games for {today}")
        return self._fetch_from_mlb_stats_api(today, today)

    def _fetch_milb_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """Fetch MiLB season schedule data using MLB Stats API.

        Returns cached data if available, otherwise fetches from MLB Stats API.
        """
        now = datetime.now(pytz.utc)
        season_year = now.year
        # MiLB season runs April-September; before April, use previous year
        if now.month < 4:
            season_year = now.year - 1
        cache_key = f"{self.sport_key}_schedule_{season_year}"

        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.debug(f"Using cached MiLB schedule for {season_year}")
                    return cached_data
                elif isinstance(cached_data, list):
                    self.logger.debug(
                        f"Using cached MiLB schedule for {season_year} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {season_year}: {type(cached_data)}"
                    )
                    self.cache_manager.clear_cache(cache_key)

        # MiLB season: April - September
        current_month = now.month
        in_season = 4 <= current_month <= 9

        if not in_season:
            self.logger.debug(
                "MiLB is currently in offseason (October-March). No games expected."
            )
            return {"events": []}

        # Fetch recent + upcoming games (7 days back, 7 days ahead)
        start_date = (now + timedelta(days=-7)).strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")

        data = self._fetch_from_mlb_stats_api(start_date, end_date)

        # Cache the result with 4-hour TTL so it refreshes periodically
        if data and data.get("events"):
            self.cache_manager.set(cache_key, data, ttl=14400)
            self.logger.info(
                f"Cached {len(data['events'])} MiLB events for {season_year}"
            )

        return data

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch cached schedule data. Subclasses may override."""
        return self._fetch_milb_api_data(use_cache=True)


class MiLBLiveManager(BaseMiLBManager, BaseballLive):
    """Manager for live MiLB games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("MiLBLiveManager")

        if self.test_mode:
            # More detailed test game for MiLB
            self.current_game = {
                "id": "testMiLB001",
                "home_abbr": "DUR",
                "home_id": "dur001",
                "away_abbr": "NOR",
                "away_id": "nor001",
                "home_score": "5",
                "away_score": "3",
                "inning": 6,
                "inning_half": "bottom",
                "balls": 2,
                "strikes": 1,
                "outs": 1,
                "bases_occupied": [True, False, True],
                "home_logo_path": Path(self.logo_dir, "DUR.png"),
                "away_logo_path": Path(self.logo_dir, "NOR.png"),
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
                "is_halftime": False,
                "home_logo_url": "",
                "away_logo_url": "",
                "series_summary": "",
                "status_text": "Bot 6",
            }
            self.live_games = [self.current_game]
            self.logger.info("Initialized MiLBLiveManager with test game: NOR vs DUR")
        else:
            self.logger.info("Initialized MiLBLiveManager in live mode")

    def _fetch_data(self) -> Optional[Dict]:
        """Live games fetch only today's games, not entire season."""
        return self._fetch_todays_games()


class MiLBRecentManager(BaseMiLBManager, BaseballRecent):
    """Manager for recently completed MiLB games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("MiLBRecentManager")
        self.logger.info(
            f"Initialized MiLBRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class MiLBUpcomingManager(BaseMiLBManager, SportsUpcoming):
    """Manager for upcoming MiLB games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("MiLBUpcomingManager")
        self.logger.info(
            f"Initialized MiLBUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )
