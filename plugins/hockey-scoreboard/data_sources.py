"""
Pluggable Data Source Architecture

This module provides abstract data sources that can be plugged into the sports system
to support different APIs and data providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import requests
import logging
from datetime import datetime
# ESPN date-range helper: core ships it from 3.5.0, the manifest's floor.
from src.common.espn_dates import ESPN_MAX_LIMIT, fetch_espn_scoreboard

class DataSource(ABC):
    """Abstract base class for data sources."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.session = requests.Session()
        
        # Configure retry strategy
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    @abstractmethod
    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        """Fetch live games for a sport/league."""
    
    @abstractmethod
    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Fetch schedule for a sport/league within date range."""
    
    @abstractmethod
    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings for a sport/league."""
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            'User-Agent': 'LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)',
            'Accept': 'application/json'
        }


class ESPNDataSource(DataSource):
    """ESPN API data source."""
    
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports"
    
    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        """Fetch live games from ESPN API."""
        try:
            now = datetime.now()
            formatted_date = now.strftime("%Y%m%d")
            url = f"{self.base_url}/{sport}/{league}/scoreboard"
            data = fetch_espn_scoreboard(
                self.session,
                url,
                params={"dates": formatted_date, "limit": ESPN_MAX_LIMIT},
                headers=self.get_headers(),
                timeout=15,
                logger=self.logger,
            )
            events = data.get('events', [])
            
            # Filter for live games
            live_events = [event for event in events 
                          if event.get('competitions', [{}])[0].get('status', {}).get('type', {}).get('state') == 'in']
            
            self.logger.debug(f"Fetched {len(live_events)} live games for {sport}/{league}")
            return live_events
            
        except Exception as e:
            self.logger.error(f"Error fetching live games from ESPN: {e}")
            return []
    
    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Fetch schedule from ESPN API."""
        try:
            start_date, end_date = date_range
            url = f"{self.base_url}/{sport}/{league}/scoreboard"
            
            params = {
                'dates': f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}",
                "limit": ESPN_MAX_LIMIT
            }
            
            data = fetch_espn_scoreboard(
                self.session,
                url,
                headers=self.get_headers(),
                params=params,
                timeout=15,
                logger=self.logger,
            )
            events = data.get('events', [])
            
            self.logger.debug(f"Fetched {len(events)} scheduled games for {sport}/{league}")
            return events
            
        except Exception as e:
            self.logger.error(f"Error fetching schedule from ESPN: {e}")
            return []
    
    def fetch_standings(self, sport: str, league: str) -> Dict:
        """Fetch standings, or the poll for leagues that have one.

        Order matters and used to be wrong. College leagues publish a poll at
        /rankings and a records table at /standings; professional leagues have
        only /standings. The old code tried /standings first and fell back to
        /rankings only on a 404 -- but college /standings answers 200, so the
        fallback never fired and college rankings came back empty forever.
        Nothing failed; the AP rank badge simply never appeared, and anything
        else keyed off rankings quietly did nothing.

        A 200 that lacks the key is treated as a miss, so a league answering
        both endpoints still ends up with whichever one actually carries a poll.
        """
        league_name = (league or "").lower()
        wants_poll = "college" in league_name or "ncaa" in league_name
        endpoints = ["rankings", "standings"] if wants_poll else ["standings", "rankings"]

        for endpoint in endpoints:
            try:
                url = f"{self.base_url}/{sport}/{league}/{endpoint}"
                response = self.session.get(
                    url, headers=self.get_headers(), timeout=15
                )
                response.raise_for_status()
                data = response.json()
                if endpoint == "rankings" and not data.get("rankings"):
                    continue
                self.logger.debug(f"Fetched {endpoint} for {sport}/{league}")
                return data
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                # Only a 404 is routine -- it is how a league says "no poll
                # here". Everything else is worth an error, and `status is
                # None` covers the ones that matter most: ConnectionError,
                # Timeout, a body that would not parse. Silencing those left a
                # board that could not reach ESPN with one debug line, and the
                # ranked filter running on an empty table.
                if status != 404:
                    self.logger.error(
                        f"Error fetching {endpoint} from ESPN for "
                        f"{sport}/{league}: {e}"
                    )
        self.logger.debug(
            f"Standings/rankings not available for {sport}/{league} from ESPN API"
        )
        return {}

    def fetch_game_summary(self, sport: str, league: str, event_id: str) -> Optional[Dict]:
        """Fetch the per-game summary (plays, boxscore) from the ESPN API.

        Hockey's goal scorer lives here and nowhere else: the scoreboard feed
        the rest of the plugin runs on carries the score but never who put the
        puck in. Only NHL answers with a `plays` array -- college hockey's
        summary has no play data at all -- which is why the goal-scorer card
        is gated on a league opting in (see espn_summary_sport_league)."""
        try:
            url = f"{self.base_url}/{sport}/{league}/summary"
            response = self.session.get(url, params={"event": event_id}, headers=self.get_headers(), timeout=15)
            response.raise_for_status()

            data = response.json()
            self.logger.debug(f"Fetched game summary for {sport}/{league} event {event_id}")
            return data

        except Exception as e:
            self.logger.error(f"Error fetching game summary from ESPN for {sport}/{league} event {event_id}: {e}")
            return None

    # ESPN's athlete bio/stats live on a different host than the scoreboard
    # (site.web.api vs site.api), under the common/v3 tree.
    _ATHLETE_BASE = "https://site.web.api.espn.com/apis/common/v3/sports"

    def fetch_player_details(self, sport: str, league: str, player_id: str) -> Optional[Dict]:
        """Fetch a player's bio + season stats from ESPN's athlete endpoint.

        Returns a parsed dict (display_name, jersey, position, height, weight,
        age, birthplace, experience, team, headshot_url, stats) or None on any
        failure. The goal card renders from the play alone when this is
        unavailable, so a miss costs detail rather than the card."""
        if not player_id:
            return None
        try:
            url = f"{self._ATHLETE_BASE}/{sport}/{league}/athletes/{player_id}"
            response = self.session.get(url, headers=self.get_headers(), timeout=10)
            if response.status_code != 200:
                self.logger.debug(
                    f"Player bio HTTP {response.status_code} for "
                    f"{sport}/{league} {player_id}"
                )
                return None
            return self._parse_player_details(response.json())
        except Exception as e:
            self.logger.debug(f"Failed to fetch player details for {player_id}: {e}")
            return None

    @staticmethod
    def _parse_player_details(bio_data: Dict) -> Optional[Dict]:
        """Flatten ESPN's athlete record into the fields the card draws.

        Season stats come from `statsSummary`, which is ESPN's own
        position-appropriate pick -- G/A/PTS/+- for a skater, and save
        percentage and GAA for a goaltender -- already ordered for display.
        No separate stats request is needed."""
        try:
            athlete = bio_data.get("athlete") or bio_data
            if not isinstance(athlete, dict):
                return None

            position = athlete.get("position") or {}
            if isinstance(position, dict):
                position = (
                    position.get("abbreviation") or position.get("displayName") or ""
                )

            stat_pairs: List[Tuple[str, str]] = []
            summary = athlete.get("statsSummary") or {}
            for entry in summary.get("statistics") or []:
                if not isinstance(entry, dict):
                    continue
                label = (
                    entry.get("abbreviation")
                    or entry.get("shortDisplayName")
                    or entry.get("name")
                )
                value = entry.get("displayValue")
                if value is None:
                    value = entry.get("value")
                if label and value is not None:
                    stat_pairs.append((str(label), str(value)))

            team = athlete.get("team") or {}
            if not isinstance(team, dict):
                team = {}

            return {
                "player_id": athlete.get("id"),
                "display_name": athlete.get("displayName"),
                "jersey": athlete.get("jersey"),
                "position": position or "",
                "height": athlete.get("displayHeight") or athlete.get("height"),
                "weight": athlete.get("displayWeight") or athlete.get("weight"),
                "age": athlete.get("age"),
                "birthplace": athlete.get("displayBirthPlace"),
                "experience": athlete.get("displayExperience"),
                "headshot_url": (athlete.get("headshot") or {}).get("href"),
                "team_abbr": team.get("abbreviation"),
                "stat_pairs": stat_pairs,
                "stats_title": summary.get("displayName") if stat_pairs else None,
            }
        except Exception:
            return None


#: HockeyTech (LeagueStat) feeds for leagues ESPN does not carry. The keys are
#: the public ones each league's own website sends from the browser; a
#: league's config may override ``hockeytech_key`` if one is ever rotated.
HOCKEYTECH_LEAGUES: Dict[str, Dict[str, str]] = {
    "ohl": {"client_code": "ohl", "key": "f1aa699db3d81487"},
    "pwhl": {"client_code": "pwhl", "key": "446521baf8c38984"},
}

#: HockeyTech GameStatus codes. 1 and 4 are what every scheduled and final
#: game in the feed carries; 2 (in progress) and 3 (unofficial final, the
#: minutes between the horn and the league signing the sheet) are the codes
#: LeagueStat uses for the states in between.
_HT_SCHEDULED, _HT_IN_PROGRESS, _HT_UNOFFICIAL_FINAL, _HT_FINAL = "1", "2", "3", "4"

#: Words in a status string that mean the game will not be played as listed.
_HT_NOT_PLAYED = (
    ("postpon", "STATUS_POSTPONED"),
    ("cancel", "STATUS_CANCELED"),
    ("suspend", "STATUS_SUSPENDED"),
    ("delay", "STATUS_DELAYED"),
)


def _ht_int(value, default: int = 0) -> int:
    """HockeyTech sends numbers as strings for some leagues, ints for others."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _ht_text(value) -> str:
    return "" if value is None else str(value).strip()


class HockeyTechDataSource(DataSource):
    """HockeyTech / LeagueStat scorebar feed, reshaped into ESPN events.

    OHL and PWHL are not on ESPN (its scoreboard answers 400 for both), but
    their own sites run on HockeyTech's ``modulekit`` scorebar, which lists
    every game in a window of days with score, clock, period and records.
    Everything downstream of the fetch -- extraction, selection, rendering --
    reads ESPN's event shape, so this adapts the feed to it once, here, and
    nothing else in the plugin has to know the league came from elsewhere.
    """

    BASE_URL = "https://lscluster.hockeytech.com/feed/index.php"
    #: The scorebar's window is counted in days either side of today.
    _MAX_DAYS = 60

    def __init__(self, logger: logging.Logger, league: str,
                 key_override: Optional[str] = None):
        super().__init__(logger)
        info = HOCKEYTECH_LEAGUES.get(league)
        if info is None:
            raise ValueError(f"No HockeyTech feed known for league {league!r}")
        self.league = league
        self.client_code = info["client_code"]
        self.key = (key_override or "").strip() or info["key"]

    def fetch_scorebar(self, days_back: int, days_ahead: int,
                       timeout: int = 15) -> List[Dict]:
        """The raw scorebar games for ``days_back``..``days_ahead``. Raises on
        a transport or parse failure so callers can tell "no games" apart from
        "could not ask"."""
        params = {
            "feed": "modulekit",
            "view": "scorebar",
            "fmt": "json",
            "lang": "en",
            "client_code": self.client_code,
            "key": self.key,
            "numberofdaysback": max(0, min(self._MAX_DAYS, int(days_back))),
            "numberofdaysahead": max(0, min(self._MAX_DAYS, int(days_ahead))),
        }
        response = self.session.get(
            self.BASE_URL, params=params, headers=self.get_headers(), timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        games = ((data or {}).get("SiteKit") or {}).get("Scorebar") or []
        return [g for g in games if isinstance(g, dict)]

    @staticmethod
    def _status(game: Dict) -> Dict:
        """An ESPN ``status`` block for one scorebar game."""
        code = _ht_text(game.get("GameStatus"))
        long_text = _ht_text(game.get("GameStatusStringLong")) or _ht_text(
            game.get("GameStatusString"))
        lowered = long_text.lower()
        period_short = _ht_text(game.get("PeriodNameShort")).upper()
        period = _ht_int(game.get("Period"))
        # ESPN's numbering, which the scorebug reads: 4 is the first overtime
        # and 5 the shootout (or a second overtime, which HockeyTech already
        # numbers 5).
        if period_short == "SO":
            period = max(period, 5)
        elif period_short.startswith("OT"):
            period = max(period, 4)

        not_played = next(
            (name for word, name in _HT_NOT_PLAYED if word in lowered), None)
        if not_played:
            state, name, completed = "post", not_played, False
        elif code in (_HT_FINAL, _HT_UNOFFICIAL_FINAL) or lowered.startswith("final"):
            state, name, completed = "post", "STATUS_FINAL", True
        elif code == _HT_IN_PROGRESS:
            state, completed = "in", False
            name = ("STATUS_END_PERIOD" if _ht_int(game.get("Intermission"))
                    else "STATUS_IN_PROGRESS")
        else:
            state, name, completed = "pre", "STATUS_SCHEDULED", False

        clock = _ht_text(game.get("GameClock")) or "0:00"
        if state == "in":
            label = "INT" if name == "STATUS_END_PERIOD" else (period_short or str(period))
            short_detail = f"{clock} - {label}"
        else:
            short_detail = long_text
        return {
            "clock": 0,
            "displayClock": clock,
            "period": period,
            "type": {
                "name": name,
                "state": state,
                "completed": completed,
                "description": long_text,
                "detail": long_text,
                "shortDetail": short_detail,
            },
        }

    @staticmethod
    def _competitor(game: Dict, side: str, home_away: str) -> Dict:
        """``side`` is HockeyTech's field prefix: "Home" or "Visitor"."""
        wins = _ht_int(game.get(f"{side}Wins"))
        losses = _ht_int(game.get(f"{side}RegulationLosses"))
        ot_losses = (_ht_int(game.get(f"{side}OTLosses"))
                     + _ht_int(game.get(f"{side}ShootoutLosses")))
        code = _ht_text(game.get(f"{side}Code"))
        nickname = _ht_text(game.get(f"{side}Nickname"))
        return {
            "id": _ht_text(game.get(f"{side}ID")),
            "homeAway": home_away,
            "score": str(_ht_int(game.get(f"{side}Goals"))),
            "team": {
                "id": _ht_text(game.get(f"{side}ID")),
                "abbreviation": code or nickname[:3].upper(),
                "displayName": _ht_text(game.get(f"{side}LongName")),
                "shortDisplayName": nickname,
                "name": nickname,
                "location": _ht_text(game.get(f"{side}City")),
                "logo": _ht_text(game.get(f"{side}Logo")) or None,
            },
            "records": [{
                "name": "overall",
                "type": "total",
                "summary": f"{wins}-{losses}-{ot_losses}",
            }],
            "statistics": [],
        }

    @classmethod
    def to_espn_event(cls, game: Dict) -> Optional[Dict]:
        """One scorebar game as an ESPN scoreboard event, or None if it lacks
        what every event needs (an id, a start time and both teams)."""
        game_id = _ht_text(game.get("ID"))
        date = _ht_text(game.get("GameDateISO8601"))
        if not game_id or not date:
            return None
        home = cls._competitor(game, "Home", "home")
        away = cls._competitor(game, "Visitor", "away")
        if not home["team"]["abbreviation"] or not away["team"]["abbreviation"]:
            return None
        status = cls._status(game)
        return {
            "id": game_id,
            "date": date,
            "name": f"{away['team']['displayName']} at {home['team']['displayName']}",
            "shortName": f"{away['team']['abbreviation']} @ {home['team']['abbreviation']}",
            "status": status,
            "competitions": [{
                "id": game_id,
                "date": date,
                "status": status,
                "competitors": [home, away],
                "venue": {"fullName": _ht_text(game.get("venue_name"))},
            }],
        }

    def events_for(self, days_back: int, days_ahead: int) -> List[Dict]:
        """ESPN-shaped events for the window, oldest first. Raises like
        fetch_scorebar."""
        events = []
        for game in self.fetch_scorebar(days_back, days_ahead):
            event = self.to_espn_event(game)
            if event is not None:
                events.append(event)
        return events

    def fetch_live_games(self, sport: str, league: str) -> List[Dict]:
        try:
            return [e for e in self.events_for(1, 1)
                    if e["status"]["type"]["state"] == "in"]
        except Exception as e:
            self.logger.error(f"Error fetching live games from HockeyTech ({self.league}): {e}")
            return []

    def fetch_schedule(self, sport: str, league: str, date_range: tuple) -> List[Dict]:
        """Events whose start falls in ``date_range`` (two aware datetimes).

        The scorebar is asked for whole days either side of today, and out of
        season it answers with the league's most recent and next games
        whatever the window -- so the result is filtered to the range, or a
        May playoff final would sit on the Recent screen all summer.
        """
        try:
            start, end = date_range
            now = datetime.now(start.tzinfo)
            back = max(0, (now - start).days + 1)
            ahead = max(0, (end - now).days + 1)
            events = self.events_for(back, ahead)
        except Exception as e:
            self.logger.error(f"Error fetching schedule from HockeyTech ({self.league}): {e}")
            return []
        kept = []
        for event in events:
            try:
                when = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None or start <= when <= end:
                kept.append(event)
        return kept

    def fetch_standings(self, sport: str, league: str) -> Dict:
        """No poll and no standings feed is used: records ride on the scorebar."""
        return {}


# Factory function removed - sport classes now instantiate data sources directly
