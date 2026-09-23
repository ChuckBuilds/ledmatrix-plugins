"""
Soccer League Managers for LEDMatrix

This module provides manager classes for various soccer leagues including
Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Champions League, and Europa League.
"""

import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import pytz

from soccer_goal_card import SoccerGoalCardMixin, extract_goals, latest_goal
from sports import SportsCore, SportsLive, SportsRecent, SportsUpcoming

# ESPN API base URL for soccer
ESPN_SOCCER_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# League display names
LEAGUE_NAMES = {
    'eng.1': 'Premier League',
    'esp.1': 'La Liga',
    'ger.1': 'Bundesliga',
    'ita.1': 'Serie A',
    'fra.1': 'Ligue 1',
    'usa.1': 'MLS',
    'por.1': 'Liga Portugal',
    'uefa.champions': 'Champions League',
    'uefa.europa': 'Europa League',
    'fifa.world': 'FIFA World Cup',
}


class BaseSoccerManager(SportsCore):
    """Base class for soccer league managers with common functionality."""

    # Class variables for warning tracking
    _no_data_warning_logged = False
    _last_warning_time = 0
    _warning_cooldown = 60  # Only log warnings once per minute
    _shared_data = None
    _last_shared_update = 0

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        """
        Initialize base soccer manager.
        
        Args:
            config: Configuration dictionary
            display_manager: Display manager instance
            cache_manager: Cache manager instance
            league_key: League identifier (e.g., 'eng.1', 'esp.1')
        """
        self.logger = logging.getLogger(f"Soccer-{league_key}")
        self.league_key = league_key
        self.league_name = LEAGUE_NAMES.get(league_key, league_key)
        
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=self.logger,
            sport_key=f"soccer_{league_key}",  # Use league-specific sport_key
        )
        
        # Set sport and league for ESPN API (after parent init to avoid overwrite)
        self.sport = "soccer"
        self.league = league_key

        # National-team flags (FIFA World Cup) live in a dedicated subdirectory so
        # they never collide with club logos that share an abbreviation — e.g. ESP
        # (Spain vs Espanyol), POR (Portugal vs Portland Timbers), COL (Colombia vs
        # Colorado Rapids). The plugin bundles every World Cup nation's flag and seeds
        # them here on startup, so all teams render correctly instead of falling back
        # to a stale placeholder or a colliding club crest.
        if league_key == "fifa.world":
            self.logo_dir = self._setup_national_flags_dir(self.logo_dir)

        # Check display modes to determine what data to fetch
        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get(f"soccer_{league_key}_recent", False)
        self.upcoming_enabled = display_modes.get(f"soccer_{league_key}_upcoming", False)
        self.live_enabled = display_modes.get(f"soccer_{league_key}_live", False)

        self.logger.info(
            f"Initialized {self.league_name} manager with display dimensions: {self.display_width}x{self.display_height}"
        )
        self.logger.info(f"Logo directory: {self.logo_dir}")
        self.logger.info(
            f"Display modes - Recent: {self.recent_enabled}, Upcoming: {self.upcoming_enabled}, Live: {self.live_enabled}"
        )

    def _setup_national_flags_dir(self, club_logo_dir: Path) -> Path:
        """Return a dedicated logo directory for national-team flags, seeded from
        the plugin's bundled flags.

        World Cup flags share a flat abbreviation namespace with club logos, so
        keeping them in a 'national' subdirectory prevents a club crest (e.g.
        Espanyol's ESP.png) from shadowing a nation's flag (Spain's ESP). The
        bundled flags are copied in once so every World Cup team renders without
        depending on a per-game download.
        """
        flags_dir = Path(club_logo_dir) / "national"
        try:
            flags_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.logger.warning(
                f"Could not create national flags directory {flags_dir}: {e}; "
                "falling back to the shared soccer logo directory"
            )
            return Path(club_logo_dir)

        bundled = Path(__file__).resolve().parent / "assets" / "flags"
        if not bundled.is_dir():
            self.logger.warning(f"Bundled flags directory not found at {bundled}")
            return flags_dir

        seeded = 0
        for src in bundled.glob("*.png"):
            dest = flags_dir / src.name
            if dest.exists():
                continue
            try:
                shutil.copyfile(src, dest)
                seeded += 1
            except OSError as e:
                self.logger.warning(f"Failed to seed flag {src.name}: {e}")
        if seeded:
            self.logger.info(f"Seeded {seeded} World Cup flags into {flags_dir}")
        return flags_dir

    def _fetch_soccer_api_data(self, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetches game data for the soccer league using background threading.
        Returns cached data immediately if available, otherwise starts background fetch.
        """
        now = datetime.now(pytz.utc)
        
        # The window the user configured, not a fixed fortnight. This is the
        # authoritative fetch; leaving it hard-coded meant a widened setting
        # showed briefly from the stand-in fetch and then vanished when this
        # one completed and replaced the data.
        start_date = now - timedelta(days=self.schedule_lookback_days)
        end_date = now + timedelta(days=self.schedule_lookahead_days)
        date_str = f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
        
        cache_key = f"soccer_{self.league_key}_schedule_{date_str}"
        url = f"{ESPN_SOCCER_BASE_URL}/{self.league_key}/scoreboard"

        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data:
                # Validate cached data structure
                if isinstance(cached_data, dict) and "events" in cached_data:
                    self.logger.info(f"Using cached schedule for {self.league_name}")
                    return cached_data
                elif isinstance(cached_data, list):
                    # Handle old cache format (list of events)
                    self.logger.info(
                        f"Using cached schedule for {self.league_name} (legacy format)"
                    )
                    return {"events": cached_data}
                else:
                    self.logger.warning(
                        f"Invalid cached data format for {self.league_name}: {type(cached_data)}"
                    )
                    # Clear invalid cache
                    self.cache_manager.delete(cache_key)

        # Start background fetch if service is available
        if (
            self.background_service
            and self.background_enabled
            and self._background_fetches_espn_ranges()
        ):
            self.logger.info(
                f"Starting background fetch for {self.league_name} schedule..."
            )

            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for {self.league_name}: {len(result.data.get('events', []))} events"
                    )
                else:
                    self.logger.error(
                        f"Background fetch failed for {self.league_name}: {result.error}"
                    )

            # Get background service configuration
            background_config = self.mode_config.get("background_service", {})
            timeout = background_config.get("request_timeout", 30)
            max_retries = background_config.get("max_retries", 3)
            priority = background_config.get("priority", 2)

            # Submit background fetch request
            request_id = self.background_service.submit_fetch_request(
                sport="soccer",
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

            # Track the request
            if not hasattr(self, 'background_fetch_requests'):
                self.background_fetch_requests = {}
            self.background_fetch_requests[date_str] = request_id

            # For immediate response, try to get partial data
            partial_data = self._get_weeks_data()
            if partial_data:
                return partial_data
        else:
            # No background service, or a core that would send this range to
            # ESPN as-is (rejected with 400 since 2026-09-15): fetch it here.
            return self._fetch_season_directly(
                url, date_str, cache_key, f"{self.league_name}"
            )

    def _fetch_data(self) -> Optional[Dict]:
        """Fetch data using shared data mechanism or direct fetch for live."""
        if isinstance(self, SoccerLiveManager):
            # Live games should fetch only current games, not entire schedule
            return self._fetch_todays_games()
        else:
            # Recent and Upcoming managers should use cached schedule data
            return self._fetch_soccer_api_data(use_cache=True)

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN Soccer API response."""
        details, home_team, away_team, status, situation = self._extract_game_details_common(game_event)
        if details is None or home_team is None or away_team is None or status is None:
            return None
        
        try:
            # Format period/half for soccer
            period = status.get("period", 0)
            period_text = ""
            status_state = status["type"]["state"]
            
            status_name = status["type"]["name"]
            if status_state == "halftime" or status_name == "STATUS_HALFTIME":
                # Check halftime first: ESPN can set state="in" AND name="STATUS_HALFTIME"
                # simultaneously, so this guard must precede the generic "in" branch.
                period_text = "ETH" if period >= 3 else "HALF"
            elif status_state == "in":
                if period == 0:
                    period_text = "Start"
                elif period == 1:
                    period_text = "1H"
                elif period == 2:
                    period_text = "2H"
                elif period == 3:
                    period_text = "ET1"  # Extra Time 1st half
                elif period == 4:
                    period_text = "ET2"  # Extra Time 2nd half
                elif period >= 5:
                    period_text = "PEN"  # Penalty shootout
                else:
                    period_text = f"P{period}"
            elif status_state == "post":
                not_played = self._NOT_PLAYED_STATUS_LABELS.get(status_name)
                if not_played:
                    # ESPN files postponed/cancelled fixtures under "post" with
                    # a 0-0 score. "Final" here fed Recent's appears_finished
                    # check, so they were shown as a 0-0 result.
                    period_text = not_played
                elif status_name in ("STATUS_FINAL_PEN", "STATUS_AFTER_PENALTIES"):
                    period_text = "F/Pen"
                elif status_name in ("STATUS_FINAL_AET", "STATUS_AFTER_EXTRA_TIME") or period > 2:
                    period_text = "F/ET"
                else:
                    period_text = "Final"
            elif status_state == "pre":
                period_text = details.get("game_time", "")

            # Get clock/time for live games
            clock = status.get("displayClock", "")
            if clock and status_state == "in":
                # Format clock for soccer (e.g., "45'" or "90+3'")
                period_text = f"{period_text} {clock}" if period_text else clock

            details.update({
                "period": period,
                "period_text": period_text,
                "clock": clock,
                "league": self.league_key,  # Add league field for scroll display
                # ESPN ships the goal events inside the scoreboard payload we
                # have already downloaded, so the scorer card costs no extra
                # request to identify who scored -- only the optional bio
                # lookup does. Always extracted: it is a cheap list walk, and
                # the live manager reads it only when the card is enabled.
                "goals": extract_goals(game_event),
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


class SoccerLiveManager(SoccerGoalCardMixin, BaseSoccerManager, SportsLive):
    """Manager for live soccer games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"SoccerLive-{league_key}")
        # Opt-in: identifying the scorer is free, but the bio behind the rest
        # of the card is one ESPN request per player. Off unless asked for.
        self.show_goal_scorer = self.mode_config.get("show_goal_scorer", False)
        # The card, armed off the celebration and shown once it ends, plus a
        # per-celebration guard so one goal triggers exactly one lookup.
        self._goal_card: Optional[Dict] = None
        self._goal_card_armed_at: Optional[float] = None
        self._player_bio_cache: Dict[str, Optional[Dict]] = {}

    # ------------------------------------------------------------------
    # Goal-scorer card
    #
    # The celebration is armed from a score delta, so it knows a goal
    # happened and which side scored but never who. Soccer is the cheapest
    # sport to answer that in: the scorer is already in the scoreboard
    # payload, so only the bio is a request, and only for a player this
    # process has not seen before.
    # ------------------------------------------------------------------

    def update(self):
        super().update()
        if not self.show_goal_scorer:
            return
        celebration = getattr(self, "active_celebration", None)
        if not celebration or celebration.get("kind") != "goal":
            return
        started_at = celebration.get("started_at")
        if started_at is None or started_at == self._goal_card_armed_at:
            return  # already handled this goal
        self._goal_card_armed_at = started_at
        self._goal_card = None
        self._arm_goal_card(celebration)

    def _arm_goal_card(self, celebration: Dict) -> None:
        """Resolve the scorer from the scoreboard data already in hand, then
        enrich with the bio off-thread.

        The card is armed immediately -- the scorer alone is worth drawing --
        and the bio is merged into it when it lands. A slow or failed bio
        costs the trivia rows, never the card."""
        game = celebration.get("game") or {}
        game_id = game.get("id")
        if not game_id:
            return
        scored_side = celebration.get("scored_side")
        team_id = game.get(f"{scored_side}_id") if scored_side else None
        goal = latest_goal(game.get("goals"), team_id)
        if goal is None:
            self.logger.debug(
                f"No named scorer in the scoreboard data for game {game_id}; "
                "skipping the goal card"
            )
            return

        goal = dict(goal)
        goal["game_id"] = str(game_id)
        goal["team_abbr"] = game.get(f"{scored_side}_abbr", "")
        goal["team_color"] = game.get(f"{scored_side}_team_color")
        started_at = celebration.get("started_at", time.time())
        goal["show_from"] = started_at + float(
            getattr(self, "celebration_duration", 8) or 8
        )
        goal["show_until"] = goal["show_from"] + float(
            self._goal_card_cfg().get("dwell_seconds", 6)
        )
        self._goal_card = goal

        player_id = (goal.get("scorer") or {}).get("id")
        if player_id:
            self._fetch_player_bio_async(player_id, goal)

    def _fetch_player_bio_async(self, player_id: str, goal: Dict) -> None:
        """Fetch the scorer's bio in a daemon thread and merge it into the
        armed card. Fire-and-forget: the render path only reads what is
        there, so a miss simply leaves the extra rows off."""
        cached = self._player_bio_cache.get(player_id)
        if player_id in self._player_bio_cache:
            goal["bio"] = cached
            return

        import threading

        def resolve():
            try:
                bio = None
                cache_key = f"soccer_player_{player_id}"
                if self.cache_manager is not None:
                    try:
                        stored = self.cache_manager.get(cache_key)
                        if stored is not None:
                            bio = stored or None
                    except Exception as e:
                        self.logger.debug(f"Player bio cache read failed for {player_id}: {e}")
                if bio is None and cache_key not in ("",):
                    bio = self.data_source.fetch_player_details(
                        "soccer", self.league_key, player_id
                    )
                    if self.cache_manager is not None:
                        try:
                            self.cache_manager.set(cache_key, bio or {}, ttl=86400)
                        except Exception as e:
                            self.logger.debug(
                                f"Player bio cache write failed for {player_id}: {e}")
                self._player_bio_cache[player_id] = bio
                goal["bio"] = bio
            except Exception as e:
                self.logger.debug(f"Player bio lookup failed for {player_id}: {e}")

        threading.Thread(target=resolve, daemon=True).start()

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        if self._maybe_draw_goal_card(game, force_clear):
            return
        super()._draw_scorebug_layout(game, force_clear)
        
        # Test mode removed - always use live data
        if False:
            # Test game for soccer
            self.current_game = {
                "id": "test001",
                "home_abbr": "MCI",
                "home_id": "123",
                "away_abbr": "LIV",
                "away_id": "456",
                "home_score": "2",
                "away_score": "1",
                "period": 2,
                "period_text": "2H",
                "clock": "75'",
                "home_logo_path": Path(self.logo_dir, "MCI.png"),
                "away_logo_path": Path(self.logo_dir, "LIV.png"),
                "is_live": True,
                "is_final": False,
                "is_upcoming": False,
                "is_halftime": False,
                "status_text": "75'",
            }
            self.live_games = [self.current_game]
            self.logger.info(f"Initialized {self.league_name} LiveManager with test game: LIV vs MCI")
        else:
            self.logger.info(f"Initialized {self.league_name} LiveManager in live mode")

    def _test_mode_update(self) -> None:
        """Simulate clock running down in test mode."""
        if self.current_game and "clock" in self.current_game:
            # Simulate clock counting down
            clock_str = self.current_game["clock"]
            if "'" in clock_str:
                try:
                    minutes = int(clock_str.replace("'", ""))
                    if minutes > 0:
                        minutes -= 1
                        self.current_game["clock"] = f"{minutes}'"
                        self.current_game["status_text"] = f"{minutes}'"
                except ValueError:
                    pass


class SoccerRecentManager(BaseSoccerManager, SportsRecent):
    """Manager for recently completed soccer games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"SoccerRecent-{league_key}")
        self.logger.info(
            f"Initialized {self.league_name} RecentManager with {len(self.favorite_teams)} favorite teams"
        )


class SoccerUpcomingManager(BaseSoccerManager, SportsUpcoming):
    """Manager for upcoming soccer games."""

    def __init__(self, config: Dict[str, Any], display_manager, cache_manager, league_key: str):
        super().__init__(config, display_manager, cache_manager, league_key)
        self.logger = logging.getLogger(f"SoccerUpcoming-{league_key}")
        self.logger.info(
            f"Initialized {self.league_name} UpcomingManager with {len(self.favorite_teams)} favorite teams"
        )


# Factory functions to create league-specific managers
def create_premier_league_managers(config, display_manager, cache_manager):
    """Create Premier League (eng.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'eng.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'eng.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'eng.1'),
    )


def create_la_liga_managers(config, display_manager, cache_manager):
    """Create La Liga (esp.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'esp.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'esp.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'esp.1'),
    )


def create_bundesliga_managers(config, display_manager, cache_manager):
    """Create Bundesliga (ger.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'ger.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'ger.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'ger.1'),
    )


def create_serie_a_managers(config, display_manager, cache_manager):
    """Create Serie A (ita.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'ita.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'ita.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'ita.1'),
    )


def create_ligue_1_managers(config, display_manager, cache_manager):
    """Create Ligue 1 (fra.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'fra.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'fra.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'fra.1'),
    )


def create_mls_managers(config, display_manager, cache_manager):
    """Create MLS (usa.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'usa.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'usa.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'usa.1'),
    )


def create_liga_portugal_managers(config, display_manager, cache_manager):
    """Create Liga Portugal (por.1) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'por.1'),
        SoccerRecentManager(config, display_manager, cache_manager, 'por.1'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'por.1'),
    )


def create_champions_league_managers(config, display_manager, cache_manager):
    """Create Champions League (uefa.champions) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'uefa.champions'),
        SoccerRecentManager(config, display_manager, cache_manager, 'uefa.champions'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'uefa.champions'),
    )


def create_europa_league_managers(config, display_manager, cache_manager):
    """Create Europa League (uefa.europa) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'uefa.europa'),
        SoccerRecentManager(config, display_manager, cache_manager, 'uefa.europa'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'uefa.europa'),
    )


def create_world_cup_managers(config, display_manager, cache_manager):
    """Create FIFA World Cup (fifa.world) managers."""
    return (
        SoccerLiveManager(config, display_manager, cache_manager, 'fifa.world'),
        SoccerRecentManager(config, display_manager, cache_manager, 'fifa.world'),
        SoccerUpcomingManager(config, display_manager, cache_manager, 'fifa.world'),
    )


def create_custom_league_managers(
    league_code: str,
    league_name: str,
    config: Dict[str, Any],
    display_manager,
    cache_manager
):
    """
    Create managers for a custom soccer league.

    This factory function creates Live, Recent, and Upcoming managers for any
    ESPN-supported soccer league. Custom leagues use the same manager classes
    as predefined leagues but with a custom league code.

    Args:
        league_code: ESPN league code (e.g., 'por.1', 'mex.1', 'arg.1')
        league_name: Display name for the league (e.g., 'Liga Portugal')
        config: Configuration dictionary for the managers
        display_manager: Display manager instance
        cache_manager: Cache manager instance

    Returns:
        Tuple of (SoccerLiveManager, SoccerRecentManager, SoccerUpcomingManager)

    Example usage:
        live, recent, upcoming = create_custom_league_managers(
            'por.1', 'Liga Portugal', config, display_manager, cache_manager
        )
    """
    # Register the custom league name in the module's LEAGUE_NAMES dict
    # This allows the managers to get the proper display name
    LEAGUE_NAMES[league_code] = league_name

    logger = logging.getLogger(f"Soccer-{league_code}")
    logger.info(f"Creating managers for custom league: {league_name} ({league_code})")

    # Create manager instances with the custom league code
    live = SoccerLiveManager(config, display_manager, cache_manager, league_code)
    recent = SoccerRecentManager(config, display_manager, cache_manager, league_code)
    upcoming = SoccerUpcomingManager(config, display_manager, cache_manager, league_code)

    # Store the league_code on managers for identification
    live.league_code = league_code
    live.league_name = league_name
    recent.league_code = league_code
    recent.league_name = league_name
    upcoming.league_code = league_code
    upcoming.league_name = league_name

    return (live, recent, upcoming)

