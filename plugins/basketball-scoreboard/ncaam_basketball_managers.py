import copy
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

from basketball import Basketball, BasketballLive
from sports import SportsRecent, SportsUpcoming

# Constants
ESPN_NCAAMB_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
)


class BaseNCAAMBasketballManager(Basketball):
    """Base class for NCAA Men's Basketball managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged = False
    _last_warning_time = 0
    _warning_cooldown = 60
    _shared_data = None
    _last_shared_update = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        self.logger = logging.getLogger("NCAAM")
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key="ncaam",
        )

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("ncaam_recent", False)
        self.upcoming_enabled = display_modes.get("ncaam_upcoming", False)
        self.live_enabled = display_modes.get("ncaam_live", False)

        self.logger.info(
            f"Initialized NCAA Men's manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )
        self.league = "mens-college-basketball"
        
        # Cache for team ID lookups
        self._team_id_cache = {}
        self._team_id_cache_timestamp = 0
        self._team_id_cache_duration = 86400  # Cache team IDs for 24 hours

    def _get_team_id(self, team_abbr: str) -> Optional[str]:
        """Get team ID from abbreviation using ESPN teams endpoint."""
        # Check cache first
        current_time = time.time()
        if (
            team_abbr in self._team_id_cache
            and current_time - self._team_id_cache_timestamp < self._team_id_cache_duration
        ):
            return self._team_id_cache[team_abbr]
        
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/teams"
            response = self.session.get(url, params={"limit": 500}, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
            for team_obj in teams:
                team = team_obj.get("team", {})
                if team.get("abbreviation", "").upper() == team_abbr.upper():
                    team_id = team.get("id")
                    if team_id:
                        self._team_id_cache[team_abbr] = str(team_id)
                        self._team_id_cache_timestamp = current_time
                        return str(team_id)
            
            self.logger.warning(f"Team ID not found for abbreviation: {team_abbr}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching team ID for {team_abbr}: {e}")
            return None

    def _fetch_team_schedule(self, team_id: str, season_year: int, use_cache: bool = True) -> Optional[Dict]:
        """Fetch a team's full season schedule.

        Raw events are cached without record enrichment so that records
        stay fresh (they are injected on every read via the base-class
        ``_enrich_events_with_records`` helper).
        """
        cache_key = f"{self.sport_key}_team_{team_id}_schedule_{season_year}"
        record_summary_key = f"{self.sport_key}_team_{team_id}_record_summary"

        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.debug(f"Using cached team schedule for team {team_id}")
                    events = cached_data["events"]
                elif isinstance(cached_data, list):
                    self.logger.debug(f"Using cached team schedule (legacy format) for team {team_id}")
                    events = cached_data
                else:
                    events = None

                if events is not None:
                    # Deep-copy so enrichment doesn't mutate the cached object
                    events = copy.deepcopy(events)
                    summary = self.cache_manager.get(record_summary_key, max_age=3600)
                    if isinstance(summary, str):
                        self._enrich_events_with_records(events, team_id, summary)
                    return {"events": events}

        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{self.sport}/{self.league}/teams/{team_id}/schedule"
            response = self.session.get(url, params={"season": str(season_year)}, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Extract events from response
            events = data.get("events", [])

            # Cache raw events (without enriched records)
            self.cache_manager.set(cache_key, {"events": events})

            # Cache the team's record summary separately
            team_record_summary = data.get("team", {}).get("recordSummary", "")
            if team_record_summary:
                self.cache_manager.set(record_summary_key, team_record_summary, ttl=3600)

            # Deep-copy before enriching so the cached object stays raw
            enriched_events = copy.deepcopy(events)
            self._enrich_events_with_records(enriched_events, team_id, team_record_summary)

            self.logger.info(f"Fetched {len(events)} events for team {team_id} season {season_year}")
            return {"events": enriched_events}
        except Exception as e:
            self.logger.error(f"Error fetching team schedule for team {team_id}: {e}")
            return None

    def _fetch_ncaam_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches the full season schedule for NCAA Men's Basketball.
        Uses team schedules for favorite teams (Recent/Upcoming modes).
        Falls back to current date scoreboard if no favorite teams configured.
        """
        now = datetime.now(pytz.utc)
        # NCAA season typically runs from November to April
        # ESPN's season parameter uses the year the season ENDS, not starts
        # If we're in Nov-Dec, we're in a season that ends next year
        if now.month >= 11:
            season_year = now.year + 1  # Season ends next year
        else:
            season_year = now.year  # Season ends this year
        
        # If favorite teams are configured, use team schedules
        if self.favorite_teams:
            combined_cache_key = f"{self.sport_key}_favorite_teams_schedule_{season_year}"
            
            # Check combined cache first
            if use_cache:
                cached_data = self.cache_manager.get(combined_cache_key)
                if cached_data:
                    if isinstance(cached_data, dict) and "events" in cached_data:
                        self.logger.info(f"Using cached favorite teams schedule for {season_year}")
                        return cached_data
                    elif isinstance(cached_data, list):
                        self.logger.info(f"Using cached favorite teams schedule (legacy format) for {season_year}")
                        return {"events": cached_data}
            
            # Fetch each favorite team's schedule
            all_events = {}
            team_ids_found = {}
            
            for team_abbr in self.favorite_teams:
                team_id = self._get_team_id(team_abbr)
                if team_id:
                    team_ids_found[team_abbr] = team_id
                    team_data = self._fetch_team_schedule(team_id, season_year, use_cache=use_cache)
                    if team_data and "events" in team_data:
                        # Deduplicate by event ID
                        for event in team_data["events"]:
                            event_id = event.get("id")
                            if event_id:
                                all_events[event_id] = event
            
            if all_events:
                combined_data = {"events": list(all_events.values())}
                # Cache combined result
                self.cache_manager.set(combined_cache_key, combined_data)
                self.logger.info(
                    f"Fetched {len(combined_data['events'])} unique events from {len(team_ids_found)} favorite teams"
                )
                return combined_data
            else:
                self.logger.warning("No events found from favorite teams' schedules")
                # Fall through to fallback
        
        # Fallback: Use current date scoreboard (no dates parameter)
        # This works when no favorite teams are configured or team schedules fail
        cache_key = f"{self.sport_key}_scoreboard_current"
        
        if use_cache:
            cached_data = self.cache_manager.get(cache_key, max_age=300)  # 5 minute cache for live data
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.debug("Using cached current scoreboard")
                    return cached_data
        
        try:
            # Use no dates parameter to get current/today's games
            response = self.session.get(
                ESPN_NCAAMB_SCOREBOARD_URL,
                params={"limit": 1000},  # No dates parameter
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            
            # Cache with short TTL (live data changes frequently)
            self.cache_manager.set(cache_key, data)
            self.logger.info(f"Fetched {len(data.get('events', []))} events from current scoreboard")
            return data
        except Exception as e:
            self.logger.error(f"Failed to fetch current scoreboard: {e}")
            return None

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data using shared data mechanism or direct fetch for live."""
        if isinstance(self, NCAAMBasketballLiveManager):
            # Live mode: Use current date scoreboard (no dates parameter) to show ALL live games
            return self._fetch_todays_games()
        else:
            # Recent/Upcoming modes: Use team schedules for favorite teams
            return self._fetch_ncaam_api_data(use_cache=True)


class NCAAMBasketballLiveManager(BaseNCAAMBasketballManager, BasketballLive):
    """Manager for live NCAA Men's Basketball games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NCAAMBasketballLiveManager")

        # Test mode removed - always use live data
        if False:
            self.current_game = {
                "id": "test001",
                "home_abbr": "DUKE",
                "home_id": "123",
                "away_abbr": "UNC",
                "away_id": "456",
                "home_score": "78",
                "away_score": "75",
                "period": 2,
                "period_text": "Q2",
                "clock": "05:30",
                "home_logo_path": Path(self.logo_dir, "DUKE.png"),
                "away_logo_path": Path(self.logo_dir, "UNC.png"),
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
                "is_halftime": False,
                "status_text": "Q2 05:30",
            }
            self.live_games = [self.current_game]
            self.logger.info("Initialized NCAAMBasketballLiveManager with test game: UNC vs DUKE")
        else:
            self.logger.info("Initialized NCAAMBasketballLiveManager in live mode")


class NCAAMBasketballRecentManager(BaseNCAAMBasketballManager, SportsRecent):
    """Manager for recently completed NCAA Men's Basketball games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NCAAMBasketballRecentManager")
        self.logger.info(
            f"Initialized NCAAMBasketballRecentManager with {len(self.favorite_teams)} favorite teams"
        )


class NCAAMBasketballUpcomingManager(BaseNCAAMBasketballManager, SportsUpcoming):
    """Manager for upcoming NCAA Men's Basketball games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NCAAMBasketballUpcomingManager")
        self.logger.info(
            f"Initialized NCAAMBasketballUpcomingManager with {len(self.favorite_teams)} favorite teams"
        )

