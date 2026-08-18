"""
NRL (National Rugby League) Managers for LEDMatrix

This module provides manager classes for the NRL, sourced from ESPN's public
rugby-league scoreboard API. NRL is a single league, so unlike the soccer
scoreboard (which this plugin was forked from) there is only one set of
Live/Recent/Upcoming managers.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import pytz

from sports import SportsCore, SportsLive, SportsRecent, SportsUpcoming

# ESPN API base URL for rugby league.
# NOTE: the ESPN "sport" slug for rugby league is "rugby-league".
ESPN_NRL_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/rugby-league"

# League display names.
#
# IMPORTANT: '3' is ESPN's INTERNAL numeric slug for the NRL under the
# rugby-league sport. It is NOT a typo and must NOT be "fixed" to "nrl" — the
# human-facing web path is /nrl/ but the API path segment is the literal string
# "3" (confirmed via
# site.web.api.espn.com/apis/v2/scoreboard/header?sport=rugby-league which lists
# NRL as id:8370, abbreviation:"NRL", slug:"3"). Changing this to "nrl" makes the
# scoreboard endpoint 404 and the plugin silently stops fetching games.
NRL_LEAGUE_SLUG = "3"
LEAGUE_NAMES = {
    NRL_LEAGUE_SLUG: "NRL",  # '3' is ESPN's NRL slug — do not change to "nrl"
}

# Config key prefix. NRL is a single league, so a plain "nrl" sport_key is used
# for the config section ("nrl_scoreboard") and the logo cache directory.
NRL_SPORT_KEY = "nrl"


class BaseNrlManager(SportsCore):
    """Base class for NRL managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged = False
    _last_warning_time = 0
    _warning_cooldown = 60  # Only log warnings once per minute
    _shared_data = None
    _last_shared_update = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        """Initialize base NRL manager."""
        self.logger = logging.getLogger("NRL")
        self.league_key = NRL_LEAGUE_SLUG
        self.league_name = LEAGUE_NAMES.get(NRL_LEAGUE_SLUG, "NRL")

        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key=NRL_SPORT_KEY,  # config lives under "nrl_scoreboard"
        )

        # Set sport and league for ESPN API (after parent init to avoid overwrite).
        # sport = "rugby-league", league = "3" (ESPN's NRL slug — NOT "nrl").
        self.sport = "rugby-league"
        self.league = NRL_LEAGUE_SLUG  # '3' — see NRL_LEAGUE_SLUG comment above

        # Check display modes to determine what data to fetch.
        # Modes are keyed nrl_live / nrl_recent / nrl_upcoming.
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("nrl_recent", False)
        self.upcoming_enabled = display_modes.get("nrl_upcoming", False)
        self.live_enabled = display_modes.get("nrl_live", False)

        self.logger.info(
            f"Initialized NRL manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )

    def _fetch_nrl_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches game data for the NRL using background threading.
        Returns cached data immediately if available, otherwise starts background fetch.
        """
        now = datetime.now(pytz.utc)

        # Fetch a date range (past 2 weeks to future 2 weeks) to cover the weekly
        # NRL round schedule for recent/upcoming views.
        # The window the user configured, not a fixed fortnight -- this is
        # the authoritative fetch, so a hard-coded range here silently
        # overrode the setting.
        start_date = now - timedelta(days=self.schedule_lookback_days)
        end_date = now + timedelta(days=self.schedule_lookahead_days)
        date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"

        cache_key = f"nrl_schedule_{date_str}"
        # NOTE: NRL_LEAGUE_SLUG is "3" (ESPN's NRL slug) — the resulting URL is
        # .../sports/rugby-league/3/scoreboard. Do NOT replace "3" with "nrl".
        url = f"{ESPN_NRL_BASE_URL}/{NRL_LEAGUE_SLUG}/scoreboard"

        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info("Using cached schedule for NRL")
                    return cached_data
                elif isinstance(cached_data, list):
                    # Handle old cache format (list of events)
                    self.logger.info("Using cached schedule for NRL (legacy format)")
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for NRL: {type(cached_data)}"
                    )
                    self.cache_manager.delete(cache_key)

        # Start background fetch if service is available
        if self.background_service and self.background_enabled:
            self.logger.info("Starting background fetch for NRL schedule...")

            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for NRL: {len(result.data.get('events', []))} events"
                    )
                else:
                    self.logger.error(
                        f"Background fetch failed for NRL: {result.error}"
                    )

            background_config = self.mode_config.get("background_service", {})
            timeout = background_config.get("request_timeout", 30)
            max_retries = background_config.get("max_retries", 3)
            priority = background_config.get("priority", 2)

            request_id = self.background_service.submit_fetch_request(
                sport="rugby-league",
                year=now.year,
                url=url,
                cache_key=cache_key,
                params={"dates": date_str, "limit": 1000},
                headers=self.headers,
                timeout=timeout,
                max_retries=max_retries,
                priority=priority,
                callback=fetch_callback,
            )

            if not hasattr(self, 'background_fetch_requests'):
                self.background_fetch_requests = {}
            self.background_fetch_requests[date_str] = request_id

            # For immediate response, try to get partial data
            partial_data = self._get_weeks_data()
            if partial_data:
                return partial_data
        else:
            # Fallback to synchronous fetch if background service not available
            self.logger.warning(
                "Background service not available, using synchronous fetch"
            )
            try:
                response = self.session.get(
                    url,
                    params={"dates": date_str, "limit": 1000},
                    headers=self.headers,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

                self.cache_manager.set(cache_key, data)
                self.logger.info("Synchronously fetched NRL schedule")
                return data

            except Exception as e:
                self.logger.error(f"Failed to fetch NRL schedule: {e}")
                return None

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data using shared data mechanism or direct fetch for live."""
        if isinstance(self, NrlLiveManager):
            # Live games should fetch only current games, not entire schedule
            return self._fetch_todays_games()
        else:
            # Recent and Upcoming managers should use cached schedule data
            return self._fetch_nrl_api_data(use_cache=True)

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN rugby-league API response.

        NRL is played over two 40-minute halves (not quarters). ESPN reports
        status.period as 1 or 2 for the two halves, with a running displayClock
        that counts UP in minutes (e.g. "40'", "80'"), exactly like soccer.
        Golden-point extra time appears as period >= 3.
        """
        details, home_team, away_team, status, situation = self._extract_game_details_common(game_event)
        if details is None or home_team is None or away_team is None or status is None:
            return None

        try:
            # Format period/half for NRL
            period = status.get("period", 0)
            period_text = ""
            status_state = status["type"]["state"]
            status_name = status["type"]["name"]

            if status_state == "halftime" or status_name == "STATUS_HALFTIME":
                # ESPN can set state="in" AND name="STATUS_HALFTIME" at the same
                # time, so this guard must precede the generic "in" branch.
                period_text = "HALF"
            elif status_state == "in":
                if period == 0:
                    period_text = "Start"
                elif period == 1:
                    period_text = "1H"  # 1st half
                elif period == 2:
                    period_text = "2H"  # 2nd half
                elif period >= 3:
                    period_text = "ET"  # golden-point extra time
                else:
                    period_text = f"P{period}"
            elif status_state == "post":
                period_text = "Final"
            elif status_state == "pre":
                period_text = details.get("game_time", "")

            # Get clock/time for live games (counts up, e.g. "40'" / "80'")
            clock = status.get("displayClock", "")
            if clock and status_state == "in":
                period_text = f"{period_text} {clock}" if period_text else clock

            details.update({
                "period": period,
                "period_text": period_text,
                "clock": clock,
                "league": self.league_key,  # '3' — used by the scroll display
            })

            # Basic validation
            if not details['home_abbr'] or not details['away_abbr']:
                self.logger.warning(f"Missing team abbreviation in event: {details['id']}")
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


class NrlLiveManager(BaseNrlManager, SportsLive):
    """Manager for live NRL games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NRLLive")
        self.logger.info("Initialized NRL LiveManager in live mode")


class NrlRecentManager(BaseNrlManager, SportsRecent):
    """Manager for recently completed NRL games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NRLRecent")
        self.logger.info(
            f"Initialized NRL RecentManager with {len(self.favorite_teams)} favorite teams"
        )


class NrlUpcomingManager(BaseNrlManager, SportsUpcoming):
    """Manager for upcoming NRL games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager):
        super().__init__(config, display_manager, cache_manager)
        self.logger = logging.getLogger("NRLUpcoming")
        self.logger.info(
            f"Initialized NRL UpcomingManager with {len(self.favorite_teams)} favorite teams"
        )


def create_nrl_managers(config, display_manager, cache_manager):
    """Create the NRL Live, Recent, and Upcoming managers.

    Returns a tuple of (NrlLiveManager, NrlRecentManager, NrlUpcomingManager).
    """
    return (
        NrlLiveManager(config, display_manager, cache_manager),
        NrlRecentManager(config, display_manager, cache_manager),
        NrlUpcomingManager(config, display_manager, cache_manager),
    )
