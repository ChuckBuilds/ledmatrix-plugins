"""
F1 Data Source Module

Handles all API interactions for the F1 Scoreboard plugin.
Uses three data sources:
- ESPN F1 API: Schedule, calendar, circuit info, session types
- Jolpi API (Ergast replacement): Standings, race results, qualifying, sprints
- OpenF1 API: Free practice results, driver info, team colors
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from team_colors import normalize_constructor_id

logger = logging.getLogger(__name__)

# API Base URLs
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/racing/f1"
JOLPI_BASE = "https://api.jolpi.ca/ergast/f1"
OPENF1_BASE = "https://api.openf1.org/v1"

class F1DataSource:
    """Fetches and processes F1 data from ESPN, Jolpi, and OpenF1 APIs."""

    def __init__(self, cache_manager=None, config: Dict[str, Any] = None):
        """
        Initialize the data source.

        Args:
            cache_manager: LEDMatrix cache manager for persistent caching
            config: Plugin configuration dictionary
        """
        self.cache_manager = cache_manager
        self.config = config or {}

        # HTTP session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "LEDMatrix-F1/1.0",
            "Accept": "application/json",
        })

        # Cache durations in seconds
        self._cache_durations = {
            "schedule": 6 * 3600,       # 6 hours
            "standings": 3600,          # 1 hour
            "race_results": 24 * 3600,  # 24 hours
            "qualifying": 24 * 3600,    # 24 hours
            "sprint": 24 * 3600,        # 24 hours
            "practice": 2 * 3600,       # 2 hours
            "drivers": 24 * 3600,       # 24 hours
        }

        # In-memory cache for when no cache_manager
        self._mem_cache: Dict[str, Tuple[float, Any]] = {}

        # Memoize latest round to avoid redundant HTTP requests
        self._latest_round_cache: Dict[int, Tuple[float, int]] = {}

        # Live session detection state
        self._live_session_type: str = ""
        self._is_race_weekend: bool = False

    # ─── Cache Helpers ─────────────────────────────────────────────────

    def _get_cached(self, key: str, category: str = "schedule") -> Optional[Any]:
        """Get cached data if still valid."""
        max_age = self._cache_durations.get(category, 3600)

        if self.cache_manager:
            return self.cache_manager.get(key, max_age=max_age)

        # Fallback to in-memory cache
        if key in self._mem_cache:
            cached_time, data = self._mem_cache[key]
            if time.time() - cached_time < max_age:
                return data
        return None

    def _set_cached(self, key: str, data: Any):
        """Store data in cache."""
        if self.cache_manager:
            self.cache_manager.set(key, data)
        else:
            self._mem_cache[key] = (time.time(), data)

    def _fetch_json(self, url: str, params: Dict = None,
                    timeout: int = 30) -> Optional[Dict]:
        """Fetch JSON from a URL with error handling."""
        try:
            response = self.session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error("API request failed for %s: %s", url, e)
            return None

    def _fallback_previous_season(self, method_name: str, season: int,
                                   default_return=None, **kwargs):
        """Fall back to previous season when current has no data (pre-season).

        Performs a single bounded fallback to (current_year - 1) to avoid
        recursive HTTP requests through multiple empty seasons.
        """
        current_year = datetime.now(timezone.utc).year
        if season >= current_year and season > 2000:
            method = getattr(self, method_name, None)
            if method is None or not callable(method):
                logger.error("Invalid fallback method: %s", method_name)
                return default_return
            target = current_year - 1
            logger.info("No %s data for %d, falling back to %d",
                       method_name, season, target)
            return method(season=target, **kwargs)
        return default_return

    # ─── ESPN: Schedule & Calendar ─────────────────────────────────────

    def fetch_schedule(self, season: int = None) -> Optional[List[Dict]]:
        """
        Fetch the full F1 season schedule from ESPN.

        Returns list of events with sessions, circuits, and status info.
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        cache_key = f"f1_schedule_{season}"
        cached = self._get_cached(cache_key, "schedule")
        if cached is not None:
            return cached

        data = self._fetch_json(f"{ESPN_BASE}/scoreboard",
                                params={"dates": str(season), "limit": "200"})
        if not data:
            return None

        events = []
        for event in data.get("events", []):
            parsed = self._parse_espn_event(event)
            if parsed:
                events.append(parsed)

        self._set_cached(cache_key, events)
        return events

    def _parse_espn_event(self, event: Dict) -> Optional[Dict]:
        """Parse an ESPN event into a clean data structure."""
        try:
            circuit = event.get("circuit", {})
            address = circuit.get("address", {})

            sessions = []
            for comp in event.get("competitions", []):
                comp_type = comp.get("type", {})
                status = comp.get("status", {})
                status_type = status.get("type", {})

                session = {
                    "id": comp.get("id"),
                    "type_id": comp_type.get("id", ""),
                    "type_abbr": comp_type.get("abbreviation", ""),
                    "date": comp.get("date", ""),
                    "status_state": status_type.get("state", "pre"),
                    "status_completed": status_type.get("completed", False),
                    "status_detail": status_type.get("detail", ""),
                    "status_short": status_type.get("shortDetail", ""),
                    "broadcast": comp.get("broadcast", ""),
                }

                # Parse competitors for completed sessions
                competitors = []
                for c in comp.get("competitors", []):
                    athlete = c.get("athlete", {})
                    competitors.append({
                        "id": c.get("id"),
                        "order": c.get("order", 0),
                        "winner": c.get("winner", False),
                        "name": athlete.get("displayName", ""),
                        "short_name": athlete.get("shortName", ""),
                        "flag_url": athlete.get("flag", {}).get("href", ""),
                    })

                if competitors:
                    session["competitors"] = sorted(competitors,
                                                     key=lambda x: x["order"])

                sessions.append(session)

            return {
                "id": event.get("id"),
                "name": event.get("name", ""),
                "short_name": event.get("shortName", ""),
                "date": event.get("date", ""),
                "end_date": event.get("endDate", ""),
                "circuit_name": circuit.get("fullName", ""),
                "city": address.get("city", ""),
                "country": address.get("country", ""),
                "sessions": sessions,
            }
        except Exception as e:
            logger.error("Error parsing ESPN event: %s", e)
            return None

    def get_upcoming_race(self) -> Optional[Dict]:
        """Get the next upcoming race event."""
        events = self.fetch_schedule()
        if not events:
            return None

        now = datetime.now(timezone.utc)

        for event in events:
            # Find the Race session
            race_session = None
            for s in event.get("sessions", []):
                if s.get("type_abbr") == "Race":
                    race_session = s
                    break

            if not race_session:
                continue

            # Check if race hasn't happened yet
            if race_session.get("status_state") == "pre":
                # Calculate countdown to next session
                next_session = self._get_next_session(event, now)
                countdown_seconds = None
                next_session_type = None

                if next_session and next_session.get("date"):
                    try:
                        session_dt = datetime.fromisoformat(
                            next_session["date"].replace("Z", "+00:00"))
                        countdown_seconds = max(
                            0, (session_dt - now).total_seconds())
                        next_session_type = next_session.get("type_abbr", "")
                    except (ValueError, TypeError):
                        pass

                return {
                    **event,
                    "countdown_seconds": countdown_seconds,
                    "next_session_type": next_session_type,
                }

        return None

    def _get_next_session(self, event: Dict,
                          now: datetime) -> Optional[Dict]:
        """Find the next upcoming session within an event."""
        for session in event.get("sessions", []):
            if session.get("status_state") == "pre" and session.get("date"):
                try:
                    session_dt = datetime.fromisoformat(
                        session["date"].replace("Z", "+00:00"))
                    if session_dt > now:
                        return session
                except (ValueError, TypeError):
                    continue
        return None

    def detect_live_session(self) -> Tuple[bool, str]:
        """
        Detect if a race session is currently live.

        Checks scheduled session times from ESPN schedule. A session is
        considered "live" if we're within its expected duration window:
          - Practice: 90 min
          - Qualifying: 90 min
          - Sprint Qualifying: 45 min
          - Sprint Race: 30 min
          - Grand Prix: 120 min

        Returns:
            (is_live, session_type_abbr) tuple
        """
        SESSION_DURATIONS = {
            "FP1": 90, "FP2": 90, "FP3": 90,
            "Qual": 90,
            "SS": 45,    # Sprint Shootout / Sprint Qualifying
            "SR": 45,    # Sprint Race
            "Race": 120,
        }

        events = self.fetch_schedule()
        if not events:
            self._live_session_type = ""
            self._is_race_weekend = False
            return False, ""

        now = datetime.now(timezone.utc)
        is_race_weekend = False

        for event in events:
            # Check if we're within this event's time window (FP1 start to Race end+2h)
            sessions = event.get("sessions", [])
            if not sessions:
                continue

            # Find event time bounds
            event_start = None
            event_end = None
            for s in sessions:
                if s.get("date"):
                    try:
                        dt = datetime.fromisoformat(
                            s["date"].replace("Z", "+00:00"))
                        if event_start is None or dt < event_start:
                            event_start = dt
                        if event_end is None or dt > event_end:
                            event_end = dt
                    except (ValueError, TypeError):
                        continue

            if event_start is None or event_end is None:
                continue

            # Add buffer: event ends 4h after last session start (timedelta handles day rollover)
            event_end_buffered = event_end + timedelta(hours=4)

            if event_start <= now <= event_end_buffered:
                is_race_weekend = True

                # Check each session for live status
                for session in sessions:
                    abbr = session.get("type_abbr", "")
                    state = session.get("status_state", "pre")
                    date_str = session.get("date", "")

                    if not date_str:
                        continue

                    try:
                        session_start = datetime.fromisoformat(
                            date_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue

                    duration_min = SESSION_DURATIONS.get(abbr, 90)
                    session_end = session_start + timedelta(minutes=duration_min)

                    if session_start <= now <= session_end:
                        self._live_session_type = abbr
                        self._is_race_weekend = True
                        return True, abbr

                    # ESPN may mark it "in" if it's live
                    if state == "in":
                        self._live_session_type = abbr
                        self._is_race_weekend = True
                        return True, abbr

        self._live_session_type = ""
        self._is_race_weekend = is_race_weekend
        return False, ""

    def get_is_race_weekend(self) -> bool:
        """Return whether we're currently in a race weekend window."""
        return self._is_race_weekend

    def get_live_session_type(self) -> str:
        """Return the currently live session abbreviation, or empty string."""
        return self._live_session_type

    def get_championship_gaps(self, standings: List[Dict],
                               points_key: str = "points") -> List[Dict]:
        """
        Annotate standings entries with gap-to-leader and gap-to-next.

        Args:
            standings: List of standing entry dicts (must be sorted by position)
            points_key: Key containing the points value

        Returns:
            Same list with 'gap_to_leader' and 'gap_to_next' added to each entry
        """
        if not standings:
            return standings

        annotated = [dict(e) for e in standings]
        leader_pts = annotated[0].get(points_key, 0)

        for i, entry in enumerate(annotated):
            pts = entry.get(points_key, 0)
            entry["gap_to_leader"] = round(leader_pts - pts, 1)
            if i > 0:
                prev_pts = annotated[i - 1].get(points_key, 0)
                entry["gap_to_next"] = round(prev_pts - pts, 1)
            else:
                entry["gap_to_next"] = 0.0
            entry["leader_points"] = leader_pts

        return annotated

    def get_calendar(self, show_practice: bool = False,
                     show_qualifying: bool = True,
                     show_sprint: bool = True,
                     max_events: int = 5) -> List[Dict]:
        """
        Get upcoming race calendar with filtered sessions.

        Returns list of session entries for future events.
        """
        events = self.fetch_schedule()
        if not events:
            return []

        now = datetime.now(timezone.utc)
        calendar_entries = []
        events_added = 0

        for event in events:
            if events_added >= max_events:
                break

            has_future_sessions = False

            for session in event.get("sessions", []):
                # Filter by session type
                abbr = session.get("type_abbr", "")
                if abbr in ("FP1", "FP2", "FP3") and not show_practice:
                    continue
                if abbr == "Qual" and not show_qualifying:
                    continue
                if abbr in ("SS", "SR") and not show_sprint:
                    continue

                # Only future sessions
                if session.get("status_state") != "pre":
                    continue

                try:
                    session_dt = datetime.fromisoformat(
                        session["date"].replace("Z", "+00:00"))
                    if session_dt <= now:
                        continue
                except (ValueError, TypeError):
                    continue

                has_future_sessions = True
                calendar_entries.append({
                    "event_name": event.get("short_name", event.get("name", "")),
                    "circuit": event.get("circuit_name", ""),
                    "city": event.get("city", ""),
                    "country": event.get("country", ""),
                    "session_type": abbr,
                    "date": session.get("date", ""),
                    "status_detail": session.get("status_short", ""),
                    "broadcast": session.get("broadcast", ""),
                })

            if has_future_sessions:
                events_added += 1

        return calendar_entries

    # ─── Jolpi: Driver Standings ───────────────────────────────────────

    def fetch_driver_standings(self, season: int = None) -> List[Dict]:
        """
        Fetch current driver championship standings.

        Returns list of driver standing entries with position, points, wins.
        Falls back to previous season if current season has no data yet.
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        cache_key = f"f1_driver_standings_{season}"
        cached = self._get_cached(cache_key, "standings")
        if cached is not None:
            return cached

        data = self._fetch_json(
            f"{JOLPI_BASE}/{season}/driverStandings.json")
        if not data:
            # Try current season keyword
            data = self._fetch_json(
                f"{JOLPI_BASE}/current/driverStandings.json")
        if not data:
            return self._fallback_previous_season(
                "fetch_driver_standings", season, default_return=[])

        standings = []
        try:
            standings_lists = (data.get("MRData", {})
                              .get("StandingsTable", {})
                              .get("StandingsLists", []))
            if not standings_lists:
                return self._fallback_previous_season(
                    "fetch_driver_standings", season, default_return=[])

            # Populate round cache so _get_latest_round skips HTTP request
            try:
                round_num = int(standings_lists[0].get("round", 0))
                if round_num > 0:
                    self._latest_round_cache[season] = (
                        time.time(), round_num)
            except (ValueError, TypeError):
                pass

            for entry in standings_lists[0].get("DriverStandings", []):
                driver = entry.get("Driver", {})
                constructors = entry.get("Constructors", [])
                constructor = constructors[0] if constructors else {}

                standings.append({
                    "position": int(entry.get("position", 0)),
                    "points": float(entry.get("points", 0)),
                    "wins": int(entry.get("wins", 0)),
                    "driver_id": driver.get("driverId", ""),
                    "code": driver.get("code", ""),
                    "first_name": driver.get("givenName", ""),
                    "last_name": driver.get("familyName", ""),
                    "number": driver.get("permanentNumber", ""),
                    "nationality": driver.get("nationality", ""),
                    "constructor_id": normalize_constructor_id(
                        constructor.get("constructorId", "")),
                    "constructor": constructor.get("name", ""),
                })
        except (KeyError, IndexError, ValueError) as e:
            logger.error("Error parsing driver standings: %s", e)
            return []

        self._set_cached(cache_key, standings)
        return standings

    # ─── Jolpi: Constructor Standings ──────────────────────────────────

    def fetch_constructor_standings(self, season: int = None) -> List[Dict]:
        """
        Fetch current constructor championship standings.

        Returns list of constructor standing entries.
        Falls back to previous season if current season has no data yet.
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        cache_key = f"f1_constructor_standings_{season}"
        cached = self._get_cached(cache_key, "standings")
        if cached is not None:
            return cached

        data = self._fetch_json(
            f"{JOLPI_BASE}/{season}/constructorStandings.json")
        if not data:
            data = self._fetch_json(
                f"{JOLPI_BASE}/current/constructorStandings.json")
        if not data:
            return self._fallback_previous_season(
                "fetch_constructor_standings", season, default_return=[])

        standings = []
        try:
            standings_lists = (data.get("MRData", {})
                              .get("StandingsTable", {})
                              .get("StandingsLists", []))
            if not standings_lists:
                return self._fallback_previous_season(
                    "fetch_constructor_standings", season, default_return=[])

            for entry in standings_lists[0].get("ConstructorStandings", []):
                constructor = entry.get("Constructor", {})

                standings.append({
                    "position": int(entry.get("position", 0)),
                    "points": float(entry.get("points", 0)),
                    "wins": int(entry.get("wins", 0)),
                    "constructor_id": normalize_constructor_id(
                        constructor.get("constructorId", "")),
                    "constructor": constructor.get("name", ""),
                    "nationality": constructor.get("nationality", ""),
                })
        except (KeyError, IndexError, ValueError) as e:
            logger.error("Error parsing constructor standings: %s", e)
            return []

        self._set_cached(cache_key, standings)
        return standings

    # ─── Jolpi: Race Results ───────────────────────────────────────────

    def fetch_race_results(self, season: int, round_num: int) -> Optional[Dict]:
        """
        Fetch results for a specific race.

        Returns race info with full results including timing data.
        """
        cache_key = f"f1_race_results_{season}_{round_num}"
        cached = self._get_cached(cache_key, "race_results")
        if cached is not None:
            return cached

        data = self._fetch_json(
            f"{JOLPI_BASE}/{season}/{round_num}/results.json")
        if not data:
            return None

        try:
            races = (data.get("MRData", {})
                    .get("RaceTable", {})
                    .get("Races", []))
            if not races:
                return None

            race = races[0]
            circuit = race.get("Circuit", {})
            location = circuit.get("Location", {})

            results = []
            for r in race.get("Results", []):
                driver = r.get("Driver", {})
                constructor = r.get("Constructor", {})
                time_data = r.get("Time", {})
                fastest = r.get("FastestLap", {})
                fastest_time = fastest.get("Time", {})

                results.append({
                    "position": int(r.get("position", 0)),
                    "points": float(r.get("points", 0)),
                    "code": driver.get("code", ""),
                    "first_name": driver.get("givenName", ""),
                    "last_name": driver.get("familyName", ""),
                    "driver_id": driver.get("driverId", ""),
                    "number": r.get("number", ""),
                    "constructor_id": normalize_constructor_id(
                        constructor.get("constructorId", "")),
                    "constructor": constructor.get("name", ""),
                    "grid": int(r.get("grid", 0)),
                    "laps": int(r.get("laps", 0)),
                    "status": r.get("status", ""),
                    "time": time_data.get("time", ""),
                    "time_millis": time_data.get("millis", ""),
                    "fastest_lap": fastest.get("rank", "") == "1",
                    "fastest_lap_rank": fastest.get("rank", ""),
                    "fastest_lap_time": fastest_time.get("time", ""),
                    "fastest_lap_number": fastest.get("lap", ""),
                })

            parsed = {
                "season": race.get("season", str(season)),
                "round": race.get("round", str(round_num)),
                "race_name": race.get("raceName", ""),
                "circuit_name": circuit.get("circuitName", ""),
                "city": location.get("locality", ""),
                "country": location.get("country", ""),
                "date": race.get("date", ""),
                "time": race.get("time", ""),
                "results": results,
            }

            self._set_cached(cache_key, parsed)
            return parsed

        except (KeyError, IndexError, ValueError) as e:
            logger.error("Error parsing race results for %s R%d: %s",
                        season, round_num, e)
            return None

    def fetch_recent_races(self, season: int = None,
                           count: int = 3) -> List[Dict]:
        """
        Fetch the last N completed race results.

        Returns list of race result dicts, most recent first.
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        cache_key = f"f1_recent_races_{season}_{count}"
        cached = self._get_cached(cache_key, "race_results")
        if cached is not None:
            return cached

        current_round = self._get_latest_round(season)

        if current_round == 0:
            return self._fallback_previous_season(
                "fetch_recent_races", season, default_return=[], count=count)

        races = []
        for round_num in range(current_round, max(0, current_round - count), -1):
            result = self.fetch_race_results(season, round_num)
            if result:
                races.append(result)

        self._set_cached(cache_key, races)
        return races

    # ─── Jolpi: Qualifying Results ─────────────────────────────────────

    def fetch_qualifying(self, season: int = None,
                         round_num: int = None) -> Optional[Dict]:
        """
        Fetch qualifying results with Q1/Q2/Q3 times.

        If round_num is None, fetches the most recent qualifying.
        Returns parsed qualifying data with gap calculations.
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        # Determine latest round if not specified
        if round_num is None:
            round_num = self._get_latest_round(season)
            if round_num == 0:
                return self._fallback_previous_season(
                    "fetch_qualifying", season)

        cache_key = f"f1_qualifying_{season}_{round_num}"
        cached = self._get_cached(cache_key, "qualifying")
        if cached is not None:
            return cached

        data = self._fetch_json(
            f"{JOLPI_BASE}/{season}/{round_num}/qualifying.json")
        if not data:
            return None

        try:
            races = (data.get("MRData", {})
                    .get("RaceTable", {})
                    .get("Races", []))
            if not races:
                return None

            race = races[0]
            results = []

            for q in race.get("QualifyingResults", []):
                driver = q.get("Driver", {})
                constructor = q.get("Constructor", {})

                entry = {
                    "position": int(q.get("position", 0)),
                    "code": driver.get("code", ""),
                    "first_name": driver.get("givenName", ""),
                    "last_name": driver.get("familyName", ""),
                    "driver_id": driver.get("driverId", ""),
                    "number": q.get("number", ""),
                    "constructor_id": normalize_constructor_id(
                        constructor.get("constructorId", "")),
                    "constructor": constructor.get("name", ""),
                    "q1": q.get("Q1", ""),
                    "q2": q.get("Q2", ""),
                    "q3": q.get("Q3", ""),
                }

                results.append(entry)

            # Calculate gaps for each qualifying session
            for session_key in ("q1", "q2", "q3"):
                leader_time = None
                for entry in results:
                    time_str = entry.get(session_key, "")
                    if time_str:
                        seconds = self._parse_lap_time(time_str)
                        if seconds is not None:
                            if leader_time is None:
                                leader_time = seconds
                            gap = seconds - leader_time
                            entry[f"{session_key}_gap"] = (
                                f"+{gap:.3f}" if gap > 0 else "")
                        else:
                            entry[f"{session_key}_gap"] = ""
                    else:
                        entry[f"{session_key}_gap"] = ""

            # Determine elimination status based on actual entry count
            total = len(results)
            q1_cutoff = total - 5   # Bottom 5 eliminated in Q1
            q2_cutoff = q1_cutoff - 5  # Next 5 eliminated in Q2
            for entry in results:
                pos = entry["position"]
                if pos > q1_cutoff:
                    entry["eliminated_in"] = "Q1"
                elif pos > q2_cutoff:
                    entry["eliminated_in"] = "Q2"
                else:
                    entry["eliminated_in"] = ""

            circuit = race.get("Circuit", {})
            location = circuit.get("Location", {})

            parsed = {
                "season": race.get("season", str(season)),
                "round": race.get("round", str(round_num)),
                "race_name": race.get("raceName", ""),
                "circuit_name": circuit.get("circuitName", ""),
                "city": location.get("locality", ""),
                "country": location.get("country", ""),
                "date": race.get("date", ""),
                "results": results,
            }

            self._set_cached(cache_key, parsed)
            return parsed

        except (KeyError, IndexError, ValueError) as e:
            logger.error("Error parsing qualifying for %s R%d: %s",
                        season, round_num, e)
            return None

    # ─── Jolpi: Sprint Results ─────────────────────────────────────────

    def fetch_sprint_results(self, season: int = None,
                              round_num: int = None) -> Optional[Dict]:
        """
        Fetch sprint race results.

        Not all rounds have sprints; returns None if no sprint data.
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        if round_num is None:
            round_num = self._get_latest_round(season)
            if round_num == 0:
                return self._fallback_previous_season(
                    "fetch_sprint_results", season)

        cache_key = f"f1_sprint_{season}_{round_num}"
        cached = self._get_cached(cache_key, "sprint")
        if cached is not None:
            return cached

        # Try current round and work backwards to find most recent sprint
        for r in range(round_num, max(0, round_num - 5), -1):
            data = self._fetch_json(
                f"{JOLPI_BASE}/{season}/{r}/sprint.json")
            if not data:
                continue

            try:
                races = (data.get("MRData", {})
                        .get("RaceTable", {})
                        .get("Races", []))
                if not races:
                    continue

                race = races[0]
                sprint_results = race.get("SprintResults", [])
                if not sprint_results:
                    continue

                results = []
                for sr in sprint_results:
                    driver = sr.get("Driver", {})
                    constructor = sr.get("Constructor", {})
                    time_data = sr.get("Time", {})

                    fastest = sr.get("FastestLap", {})
                    results.append({
                        "position": int(sr.get("position", 0)),
                        "points": float(sr.get("points", 0)),
                        "code": driver.get("code", ""),
                        "first_name": driver.get("givenName", ""),
                        "last_name": driver.get("familyName", ""),
                        "driver_id": driver.get("driverId", ""),
                        "number": sr.get("number", ""),
                        "constructor_id": normalize_constructor_id(
                            constructor.get("constructorId", "")),
                        "constructor": constructor.get("name", ""),
                        "grid": int(sr.get("grid", 0)),
                        "laps": int(sr.get("laps", 0)),
                        "status": sr.get("status", ""),
                        "time": time_data.get("time", ""),
                        "fastest_lap": fastest.get("rank", "") == "1",
                    })

                circuit = race.get("Circuit", {})
                location = circuit.get("Location", {})

                parsed = {
                    "season": race.get("season", str(season)),
                    "round": str(r),
                    "race_name": race.get("raceName", ""),
                    "circuit_name": circuit.get("circuitName", ""),
                    "city": location.get("locality", ""),
                    "country": location.get("country", ""),
                    "date": race.get("date", ""),
                    "results": results,
                }

                self._set_cached(cache_key, parsed)
                return parsed

            except (KeyError, IndexError, ValueError) as e:
                logger.error("Error parsing sprint for %s R%d: %s",
                            season, r, e)
                continue

        return None

    # ─── Jolpi: Pole Positions ─────────────────────────────────────────

    def calculate_pole_positions(self, season: int = None) -> Dict[str, int]:
        """
        Count pole positions per driver for the season.

        Iterates qualifying results and counts position=1 for each driver.

        Returns:
            Dict mapping driver code to pole count
        """
        if season is None:
            season = datetime.now(timezone.utc).year

        cache_key = f"f1_poles_{season}"
        cached = self._get_cached(cache_key, "qualifying")
        if cached is not None:
            return cached

        current_round = self._get_latest_round(season)
        poles: Dict[str, int] = {}

        for r in range(1, current_round + 1):
            quali = self.fetch_qualifying(season, r)
            if quali and quali.get("results"):
                for entry in quali["results"]:
                    if entry.get("position") == 1:
                        code = entry.get("code", "")
                        if code:
                            poles[code] = poles.get(code, 0) + 1
                        break

        self._set_cached(cache_key, poles)
        return poles

    # ─── OpenF1: Free Practice Results ─────────────────────────────────

    def fetch_practice_results(self, session_name: str = "Practice 3",
                                year: int = None) -> Optional[Dict]:
        """
        Fetch free practice session results from OpenF1.

        Gets best lap time per driver and final positions.

        Args:
            session_name: "Practice 1", "Practice 2", or "Practice 3"
            year: Season year

        Returns:
            Dict with session info and driver results sorted by best lap
        """
        if year is None:
            year = datetime.now(timezone.utc).year

        cache_key = f"f1_practice_{session_name}_{year}"
        cached = self._get_cached(cache_key, "practice")
        if cached is not None:
            return cached

        # Find the most recent session of this type
        sessions_data = self._fetch_json(
            f"{OPENF1_BASE}/sessions",
            params={
                "year": year,
                "session_name": session_name,
            })

        if not sessions_data or not isinstance(sessions_data, list):
            return None

        # Get most recent completed session
        latest_session = None
        for s in reversed(sessions_data):
            if s.get("date_end"):
                latest_session = s
                break

        if not latest_session:
            return None

        session_key = latest_session.get("session_key")
        if not session_key:
            return None

        # Fetch all laps for this session
        laps_data = self._fetch_json(
            f"{OPENF1_BASE}/laps",
            params={"session_key": session_key})

        if not laps_data or not isinstance(laps_data, list):
            return None

        # Find best lap per driver
        best_laps: Dict[int, Dict] = {}
        for lap in laps_data:
            driver_num = lap.get("driver_number")
            duration = lap.get("lap_duration")
            if driver_num is None or duration is None:
                continue

            try:
                duration = float(duration)
            except (ValueError, TypeError):
                continue

            if duration <= 0:
                continue

            if (driver_num not in best_laps or
                    duration < best_laps[driver_num]["duration"]):
                best_laps[driver_num] = {
                    "driver_number": driver_num,
                    "duration": duration,
                    "lap_number": lap.get("lap_number", 0),
                }

        if not best_laps:
            return None

        # Fetch driver info to map numbers to names/teams
        drivers_data = self._fetch_json(
            f"{OPENF1_BASE}/drivers",
            params={"session_key": session_key})

        driver_info = {}
        if drivers_data and isinstance(drivers_data, list):
            for d in drivers_data:
                num = d.get("driver_number")
                if num is not None:
                    driver_info[num] = {
                        "name": d.get("full_name", ""),
                        "code": d.get("name_acronym", ""),
                        "team": d.get("team_name", ""),
                        "team_color": d.get("team_colour", ""),
                        "number": num,
                    }

        # Sort by best lap time
        sorted_laps = sorted(best_laps.values(), key=lambda x: x["duration"])

        # Build results
        results = []
        leader_time = sorted_laps[0]["duration"] if sorted_laps else 0

        for i, lap in enumerate(sorted_laps):
            driver_num = lap["driver_number"]
            info = driver_info.get(driver_num, {})
            gap = lap["duration"] - leader_time

            # Format duration as lap time string
            minutes = int(lap["duration"]) // 60
            seconds = lap["duration"] - (minutes * 60)
            time_str = f"{minutes}:{seconds:06.3f}"

            # Map team name to constructor ID
            team_name = info.get("team", "")
            constructor_id = normalize_constructor_id(team_name)

            results.append({
                "position": i + 1,
                "code": info.get("code", f"#{driver_num}"),
                "name": info.get("name", f"Driver #{driver_num}"),
                "number": str(driver_num),
                "constructor_id": constructor_id,
                "constructor": team_name,
                "best_lap": time_str,
                "best_lap_seconds": lap["duration"],
                "gap": f"+{gap:.3f}" if gap > 0 else "",
                "gap_seconds": gap,
            })

        # Map session_name to short FP label
        fp_map = {
            "Practice 1": "FP1",
            "Practice 2": "FP2",
            "Practice 3": "FP3",
        }

        parsed = {
            "session_name": fp_map.get(session_name, session_name),
            "circuit": latest_session.get("circuit_short_name", ""),
            "country": latest_session.get("country_name", ""),
            "date": latest_session.get("date_start", ""),
            "results": results,
        }

        self._set_cached(cache_key, parsed)
        return parsed

    # ─── Helpers ───────────────────────────────────────────────────────

    def get_latest_round(self, season: int) -> int:
        """Public accessor for the latest completed round number."""
        return self._get_latest_round(season)

    def _get_latest_round(self, season: int) -> int:
        """Get the latest completed round number for a season (memoized)."""
        # Return memoized value if fresh (within standings cache duration)
        max_age = self._cache_durations.get("standings", 3600)
        if season in self._latest_round_cache:
            cached_time, round_num = self._latest_round_cache[season]
            if time.time() - cached_time < max_age:
                return round_num

        # Persistent cache so the value survives restarts and the plugin still
        # resolves the latest round when the ergast API is unreachable (offline).
        round_key = f"f1_latest_round_{season}"
        cached_round = self._get_cached(round_key, "standings")
        if cached_round is not None:
            self._latest_round_cache[season] = (time.time(), cached_round)
            return cached_round

        data = self._fetch_json(
            f"{JOLPI_BASE}/{season}/driverStandings.json")
        if not data:
            data = self._fetch_json(
                f"{JOLPI_BASE}/current/driverStandings.json")
        if not data:
            return 0

        try:
            standings_lists = (data.get("MRData", {})
                              .get("StandingsTable", {})
                              .get("StandingsLists", []))
            if standings_lists:
                round_num = int(standings_lists[0].get("round", 0))
                self._latest_round_cache[season] = (time.time(), round_num)
                self._set_cached(round_key, round_num)
                return round_num
        except (KeyError, IndexError, ValueError):
            pass
        return 0

    @staticmethod
    def _parse_lap_time(time_str: str) -> Optional[float]:
        """
        Parse a lap time string like '1:15.096' into total seconds.

        Returns None if parsing fails.
        """
        if not time_str:
            return None
        try:
            if ":" in time_str:
                parts = time_str.split(":")
                minutes = int(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            return float(time_str)
        except (ValueError, IndexError):
            return None

    # ─── Favorite Filtering ────────────────────────────────────────────

    def apply_favorite_filter(self, entries: List[Dict], top_n: int,
                               favorite_driver: str = "",
                               favorite_team: str = "",
                               always_show_favorite: bool = True,
                               driver_key: str = "code",
                               team_key: str = "constructor_id"
                               ) -> List[Dict]:
        """
        Apply favorite driver/team filtering to a list of entries.

        Shows top N entries, then appends favorite if not already shown.

        Args:
            entries: List of standings/results entries
            top_n: Number of top entries to show
            favorite_driver: Favorite driver code (e.g., "NOR")
            favorite_team: Favorite constructor ID (e.g., "mclaren")
            always_show_favorite: Whether to append favorite if outside top N
            driver_key: Key name for driver code in entry dict
            team_key: Key name for constructor ID in entry dict

        Returns:
            Filtered list of entries
        """
        if not entries:
            return []

        # Take top N
        shown = entries[:top_n]
        shown_codes = {e.get(driver_key, "").upper() for e in shown}
        shown_teams = {e.get(team_key, "").lower() for e in shown}

        if not always_show_favorite:
            return shown

        # Add favorite driver if not already shown
        if favorite_driver:
            fav_upper = favorite_driver.upper()
            if fav_upper not in shown_codes:
                for entry in entries[top_n:]:
                    if entry.get(driver_key, "").upper() == fav_upper:
                        fav_entry = dict(entry)
                        fav_entry["is_favorite"] = True
                        shown.append(fav_entry)
                        shown_codes.add(fav_upper)
                        break

        # Add favorite team drivers if not already shown
        if favorite_team:
            fav_team = normalize_constructor_id(favorite_team)
            if fav_team not in shown_teams:
                for entry in entries[top_n:]:
                    if entry.get(team_key, "") == fav_team:
                        code = entry.get(driver_key, "").upper()
                        if code not in shown_codes:
                            fav_entry = dict(entry)
                            fav_entry["is_favorite"] = True
                            shown.append(fav_entry)
                            shown_codes.add(code)

        return shown
