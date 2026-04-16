"""
Masters Tournament Data Source

Handles all data fetching from ESPN Golf API with proper caching.
Supports mock data mode for testing when Masters isn't live.
Enriches player data with real ESPN headshot URLs and country codes.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from masters_helpers import ESPN_HEADSHOT_URL, ESPN_PLAYER_IDS, get_espn_headshot_url, get_player_country

logger = logging.getLogger(__name__)

# Cache keys
CACHE_KEY_LEADERBOARD = "masters_leaderboard"
CACHE_KEY_META = "masters_tournament_meta"
CACHE_KEY_SCHEDULE = "masters_schedule"

# Sentinel passed to cache_manager.get(max_age=...) when we want "return
# whatever exists, even if stale". The LEDMatrix core CacheManager.get()
# signature is `max_age: int = 300` — it doesn't accept None, so we use a
# very large finite value (~68 years) to effectively disable expiry at the
# read site.
_NEVER_EXPIRE = 2**31 - 1


class MastersDataSource:
    """Fetches and caches Masters Tournament data from ESPN Golf API."""

    # NOTE: ESPN's legacy `/sports/golf/pga/leaderboard` path now 404s.
    # The current working endpoint drops the `pga` segment.
    LEADERBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard"
    NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/news"
    # Athlete bio + overview live on site.web.api (common/v3), not site.api.
    ATHLETE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/golf/pga/athletes/{player_id}"
    ATHLETE_OVERVIEW_URL = "https://site.web.api.espn.com/apis/common/v3/sports/golf/pga/athletes/{player_id}/overview"

    HTTP_HEADERS = {"User-Agent": "LEDMatrix Masters Plugin/2.1"}

    def __init__(self, cache_manager, config: Dict[str, Any]):
        self.cache_manager = cache_manager
        self.config = config
        self.mock_mode = config.get("mock_data", False)
        self.logger = logging.getLogger(__name__)
        self._cache_warned = False

    def _safe_cache_get(self, key: str, max_age: int) -> Any:
        """Wrap cache_manager.get() and treat any exception as a cache miss.

        A stale or malformed cache file from an older plugin version can
        cause the core CacheManager to raise (e.g. `<=` comparisons against
        None, unpickling errors, etc.). Rather than propagate those errors
        and crash the plugin's `__init__`, we swallow them here and return
        None so the caller proceeds as if the cache were empty — the next
        successful fetch will overwrite the stale file. Log once per
        instance so we don't spam the journal every tick.
        """
        try:
            return self.cache_manager.get(key, max_age=max_age)
        except Exception as e:
            if not self._cache_warned:
                self.logger.warning(
                    f"Cache read for {key!r} failed ({e!r}); treating as miss. "
                    f"A stale cache file from an older plugin version may need "
                    f"to be removed at /var/cache/ledmatrix/{key}.json — "
                    f"it will be regenerated on the next successful fetch."
                )
                self._cache_warned = True
            return None

    # ── Leaderboard ──────────────────────────────────────────────

    def fetch_leaderboard(self) -> List[Dict]:
        """Fetch current Masters leaderboard with caching."""
        if self.mock_mode:
            return self._generate_mock_leaderboard()

        cache_key = CACHE_KEY_LEADERBOARD
        ttl = self._get_cache_ttl()

        cached = self._safe_cache_get(cache_key, max_age=ttl)
        if cached:
            self.logger.debug("Using cached leaderboard data")
            return cached

        try:
            response = requests.get(
                self.LEADERBOARD_URL,
                timeout=10,
                headers=self.HTTP_HEADERS,
            )
            response.raise_for_status()
            data = response.json()

            # Parse tournament meta from the leaderboard payload. Only cache
            # it when ESPN is actually serving the Masters — otherwise a
            # non-Masters PGA event (e.g. RBC Heritage during off-season)
            # would poison the cache and drive the countdown / phase to
            # the wrong tournament.
            meta = self._parse_tournament_meta(data)
            if meta and meta.get("is_masters"):
                self.cache_manager.set(CACHE_KEY_META, meta, ttl=ttl)

            if not meta or not meta.get("is_masters"):
                self.logger.info("Masters not currently in ESPN API, using mock data")
                mock = self._generate_mock_leaderboard()
                self.cache_manager.set(cache_key, mock, ttl=3600)
                # Clear any stale tee-time cache so we don't surface tee times
                # from a previous tournament / non-Masters event.
                self.cache_manager.set(CACHE_KEY_SCHEDULE, [], ttl=3600)
                return mock

            parsed = self._parse_leaderboard(data)
            self.cache_manager.set(cache_key, parsed, ttl=ttl)

            # Derive tee times from the same payload and cache them directly,
            # so fetch_schedule() is a pure cache read and never has to
            # re-parse stale in-memory state.
            try:
                tee_times = self._parse_tee_times_from_leaderboard(data)
                self.cache_manager.set(CACHE_KEY_SCHEDULE, tee_times, ttl=ttl)
            except Exception as e:
                self.logger.warning(f"Tee-time parsing failed: {e}")

            return parsed

        except Exception as e:
            self.logger.error(f"Failed to fetch leaderboard: {e}")
            return self._get_fallback_data(cache_key)

    # ── Tournament metadata (start/end dates, status, round) ────

    def fetch_tournament_meta(self) -> Optional[Dict]:
        """Return tournament metadata, refreshing via fetch_leaderboard() if needed.

        Meta shape:
            {
                "name": str,
                "start_date": datetime (UTC, tz-aware),
                "end_date": datetime (UTC, tz-aware),
                "status": "pre" | "in" | "post",
                "current_round": int,
                "is_masters": bool,
            }
        """
        cached = self._safe_cache_get(CACHE_KEY_META, max_age=self._get_cache_ttl())
        if cached:
            return self._rehydrate_meta(cached)

        # Meta lives alongside the leaderboard payload; a leaderboard fetch
        # will populate it as a side effect.
        try:
            self.fetch_leaderboard()
        except Exception as e:
            self.logger.warning(f"fetch_tournament_meta: leaderboard fetch failed: {e}")

        cached = self._safe_cache_get(CACHE_KEY_META, max_age=_NEVER_EXPIRE)
        if cached:
            return self._rehydrate_meta(cached)

        # Final fallback: compute the Masters as the second Thursday of April
        # so off-season countdowns still work.
        return self._computed_fallback_meta()

    @classmethod
    def _rehydrate_meta(cls, cached: Dict) -> Dict:
        """Convert cached meta date fields back to tz-aware datetimes.

        The core CacheManager serializes to JSON on disk, which turns our
        datetime objects into ISO strings. Consumers (countdown, phase
        detection, TTL computation) all expect datetime instances, so we
        rehydrate here at the single read boundary.
        """
        if not isinstance(cached, dict):
            return cached
        meta = dict(cached)
        for key in ("start_date", "end_date"):
            value = meta.get(key)
            if isinstance(value, str):
                meta[key] = cls._parse_iso_utc(value)
        return meta

    def _parse_tournament_meta(self, data: Dict) -> Optional[Dict]:
        """Extract tournament meta from an ESPN leaderboard response."""
        try:
            events = data.get("events", [])
            if not events:
                return None
            event = events[0]
            name = event.get("name", "") or ""
            is_masters = any(
                kw in name.lower() for kw in ("masters", "augusta national", "augusta")
            )

            start_date = self._parse_iso_utc(event.get("date"))
            end_date = self._parse_iso_utc(event.get("endDate"))
            if end_date is None and start_date is not None:
                # Fallback: Masters is always a 4-day (Thu–Sun) event.
                end_date = start_date + timedelta(days=3)
            if end_date is not None:
                # ESPN reports endDate as the *start* of the final day in ET
                # (e.g. 2026-04-12T04:00Z = Sun Apr 12 00:00 ET). Push to end
                # of that calendar day so phase checks treat all of Sunday's
                # play as in-tournament rather than post-tournament.
                end_date = end_date + timedelta(hours=23, minutes=59, seconds=59)

            status_obj = {}
            competitions = event.get("competitions", [])
            if competitions:
                status_obj = competitions[0].get("status", {}) or {}
            status_type = (status_obj.get("type") or {}).get("state", "pre")
            current_round = int(status_obj.get("period", 0) or 0)

            if not start_date:
                return None

            return {
                "name": name or "Masters Tournament",
                "start_date": start_date,
                "end_date": end_date,
                "status": status_type,
                "current_round": current_round,
                "is_masters": is_masters,
            }
        except Exception as e:
            self.logger.error(f"Error parsing tournament meta: {e}")
            return None

    @staticmethod
    def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp from ESPN into a tz-aware UTC datetime."""
        if not value:
            return None
        try:
            # ESPN uses trailing 'Z'; datetime.fromisoformat handles +00:00
            cleaned = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    @classmethod
    def _format_tee_time_et(cls, iso_value: Optional[str]) -> str:
        """Render an ESPN ISO tee time as compact Augusta-local display text.

        Example: '2026-04-09T14:07Z' -> '10:07 AM'. Returns 'TBD' for
        unparseable or empty values. The Masters is always played in the
        second week of April, which is after US DST starts, so EDT (UTC-4)
        is always correct — no tz database lookup needed.
        """
        dt = cls._parse_iso_utc(iso_value)
        if dt is None:
            return "TBD"
        et = dt - timedelta(hours=4)  # EDT
        hour = et.hour
        minute = et.minute
        suffix = "AM" if hour < 12 else "PM"
        display_hour = hour % 12 or 12
        return f"{display_hour}:{minute:02d} {suffix}"

    def _computed_fallback_meta(self) -> Dict:
        """Compute a best-guess Masters window using the correct Thursday rule.

        Used only when ESPN doesn't currently return the Masters (off-season).
        """
        from masters_helpers import _masters_thursday
        now = datetime.now(timezone.utc)
        year = now.year
        start = _masters_thursday(year)
        if now > start + timedelta(days=4):
            start = _masters_thursday(year + 1)
        # _masters_thursday returns noon UTC (08:00 EDT). Normalise to midnight
        # EDT (04:00 UTC) before computing the end so that +3 days +23:59:59
        # lands on Sunday 23:59:59 EDT (April 12) rather than Monday morning
        # UTC (April 13). This keeps end_e.date() == Sunday in EDT, matching
        # the ESPN-parsed endDate path and making post-tournament day counting
        # come out correctly.
        thu_midnight_edt = start.replace(hour=4, minute=0, second=0, microsecond=0)
        end = thu_midnight_edt + timedelta(days=3, hours=23, minutes=59, seconds=59)
        return {
            "name": "Masters Tournament",
            "start_date": start,
            "end_date": end,
            "status": "pre",
            "current_round": 0,
            "is_masters": False,
        }

    @staticmethod
    def _second_thursday_of_april(year: int) -> datetime:
        """Backwards-compatible alias — delegates to the correct algorithm.

        The original 'second Thursday of April' rule gave wrong dates for
        2022 (Apr 13, actual Apr 7) and 2023 (Apr 13, actual Apr 6).
        The correct rule is the Thursday between April 6-12 inclusive.
        This method is kept so any external callers are not broken.
        """
        from masters_helpers import _masters_thursday
        return _masters_thursday(year)

    # ── Schedule / tee times ─────────────────────────────────────

    def fetch_schedule(self) -> List[Dict]:
        """Return Masters tee-time pairings.

        Tee times are derived from the leaderboard payload and cached inside
        fetch_leaderboard(), so this is a pure cache read. If the cache is
        cold (e.g. first call after startup), it triggers a leaderboard
        refresh to populate it — but only when meta reports is_masters, to
        avoid parsing a non-Masters PGA event's tee times during off-season.
        """
        if self.mock_mode:
            return self._generate_mock_schedule()

        cache_key = CACHE_KEY_SCHEDULE
        ttl = self._get_cache_ttl()

        cached = self._safe_cache_get(cache_key, max_age=ttl)
        if cached is not None:
            return cached

        # Cold cache — ask the leaderboard path to refresh everything.
        # fetch_leaderboard() populates CACHE_KEY_SCHEDULE as a side effect
        # when meta.is_masters is true.
        try:
            self.fetch_leaderboard()
        except Exception as e:
            self.logger.error(f"fetch_schedule: leaderboard refresh failed: {e}")
            return self._get_fallback_data(cache_key)

        cached = self._safe_cache_get(cache_key, max_age=_NEVER_EXPIRE)
        if cached is not None:
            return cached
        return []

    # ── Player details ───────────────────────────────────────────

    def fetch_player_details(self, player_id: str) -> Optional[Dict]:
        """Fetch player bio + season stats from ESPN's athlete + overview endpoints."""
        if not player_id or str(player_id).startswith("mock_"):
            return None

        cache_key = f"masters_player_{player_id}"
        ttl = self._get_cache_ttl()

        cached = self._safe_cache_get(cache_key, max_age=ttl)
        if cached:
            self.logger.debug(f"Using cached player details for {player_id}")
            return cached

        try:
            bio_resp = requests.get(
                self.ATHLETE_URL.format(player_id=player_id),
                timeout=10,
                headers=self.HTTP_HEADERS,
            )
            if bio_resp.status_code != 200:
                self.logger.warning(
                    f"Player bio HTTP {bio_resp.status_code} for {player_id}"
                )
                return None
            bio_data = bio_resp.json()

            overview_data = None
            try:
                overview_resp = requests.get(
                    self.ATHLETE_OVERVIEW_URL.format(player_id=player_id),
                    timeout=10,
                    headers=self.HTTP_HEADERS,
                )
                if overview_resp.status_code == 200:
                    overview_data = overview_resp.json()
            except Exception as e:
                self.logger.debug(f"Player overview fetch failed for {player_id}: {e}")

            parsed = self._parse_player_details(bio_data, overview_data)
            if parsed:
                self.cache_manager.set(cache_key, parsed, ttl=ttl)
            return parsed
        except Exception as e:
            self.logger.warning(f"Failed to fetch player details for {player_id}: {e}")
            return None

    def _parse_player_details(
        self, bio_data: Dict, overview_data: Optional[Dict]
    ) -> Optional[Dict]:
        """Combine bio + overview into a single player details dict."""
        try:
            athlete = bio_data.get("athlete") or bio_data
            if not isinstance(athlete, dict):
                return None

            headshot = (athlete.get("headshot") or {}).get("href")
            flag = (athlete.get("flag") or {}).get("href")
            flag_alt = (athlete.get("flag") or {}).get("alt")

            # birthPlace is {city, state, country, countryAbbreviation}
            birth_place = athlete.get("birthPlace") or {}
            if isinstance(birth_place, dict):
                birth_parts = [
                    (birth_place.get("city") or "").strip(),
                    (birth_place.get("state") or "").strip(),
                    (birth_place.get("country") or "").strip(),
                ]
                birth_place_str = ", ".join(p for p in birth_parts if p)
            else:
                birth_place_str = str(birth_place) if birth_place else ""

            college = athlete.get("college")
            if isinstance(college, dict):
                college = college.get("name")

            stats: Dict[str, Any] = {}
            rankings: Dict[str, Any] = {}
            overview_display = None

            if overview_data:
                stat_block = overview_data.get("statistics") or {}
                overview_display = stat_block.get("displayName")
                labels = stat_block.get("names") or stat_block.get("labels") or []
                splits = stat_block.get("splits") or []
                # Prefer the PGA TOUR split over Majors when present
                chosen_split = None
                if isinstance(splits, list):
                    for sp in splits:
                        if (sp.get("displayName") or "").upper() == "PGA TOUR":
                            chosen_split = sp
                            break
                    if chosen_split is None and splits:
                        chosen_split = splits[0]
                if chosen_split:
                    values = chosen_split.get("stats") or []
                    for label, value in zip(labels, values):
                        if label:
                            stats[label] = value

                # seasonRankings.categories is a rich list of ranked stats.
                sr = overview_data.get("seasonRankings") or {}
                categories = sr.get("categories") or []
                for cat in categories:
                    key = cat.get("shortDisplayName") or cat.get("displayName") or cat.get("name")
                    if not key:
                        continue
                    rankings[key] = {
                        "value": cat.get("displayValue"),
                        "rank": cat.get("rankDisplayValue") or cat.get("rank"),
                    }

            return {
                "player_id": athlete.get("id"),
                "display_name": athlete.get("displayName"),
                "first_name": athlete.get("firstName"),
                "last_name": athlete.get("lastName"),
                "age": athlete.get("age"),
                "height": athlete.get("displayHeight") or athlete.get("height"),
                "weight": athlete.get("displayWeight") or athlete.get("weight"),
                "college": college,
                "turned_pro": athlete.get("turnedPro"),
                "birth_place": birth_place_str,
                "country": flag_alt,
                "headshot_url": headshot,
                "flag_url": flag,
                "stats_display_name": overview_display,
                "stats": stats,
                "rankings": rankings,
            }
        except Exception as e:
            self.logger.error(f"Error parsing player details: {e}")
            return None

    def _is_masters_tournament(self, data: Dict) -> bool:
        """Check if the current tournament in ESPN data is the Masters."""
        try:
            events = data.get("events", [])
            if not events:
                return False
            name = events[0].get("name", "").lower()
            return any(kw in name for kw in ["masters", "augusta national", "augusta"])
        except Exception:
            return False

    def _parse_tee_times_from_leaderboard(self, data: Dict) -> List[Dict]:
        """Extract tee-time pairings from an ESPN leaderboard payload.

        Each group is {"time": ISO UTC str, "players": [name, ...]}.
        Groups are reconstructed by clustering competitors with identical tee times.
        """
        groups: Dict[str, List[str]] = {}
        try:
            events = data.get("events", [])
            if not events:
                return []
            competitions = events[0].get("competitions", [])
            if not competitions:
                return []

            # Preferred shape: explicit teeTimes list on the competition.
            explicit = competitions[0].get("teeTimes") or []
            if explicit:
                result = []
                for tt in explicit:
                    players_list = []
                    for competitor in tt.get("competitors", []) or []:
                        athlete = competitor.get("athlete", {}) or {}
                        players_list.append(athlete.get("displayName", "Unknown"))
                    iso = tt.get("startTime") or ""
                    result.append({
                        "time": self._format_tee_time_et(iso),
                        "time_raw": iso,
                        "players": players_list,
                    })
                result.sort(key=lambda g: g.get("time_raw") or "")
                return result

            # Fallback: group competitors by their status.teeTime.
            competitors = competitions[0].get("competitors", []) or []
            for entry in competitors:
                athlete = entry.get("athlete", {}) or {}
                status = entry.get("status", {}) or {}
                tee_time = status.get("teeTime")
                if not tee_time:
                    continue
                name = athlete.get("displayName", "Unknown")
                groups.setdefault(tee_time, []).append(name)

            result = [
                {
                    "time": self._format_tee_time_et(t),
                    "time_raw": t,
                    "players": players,
                }
                for t, players in groups.items()
            ]
            result.sort(key=lambda g: g["time_raw"])
            return result
        except Exception as e:
            self.logger.error(f"Error parsing tee times: {e}")
            return []

    def _parse_leaderboard(self, data: Dict) -> List[Dict]:
        """Extract and enrich fields from ESPN leaderboard API response."""
        players = []

        try:
            events = data.get("events", [])
            if not events:
                return players

            competitions = events[0].get("competitions", [])
            if not competitions:
                return players

            competitors = competitions[0].get("competitors", [])

            for entry in competitors:
                athlete = entry.get("athlete", {}) or {}
                status = entry.get("status", {}) or {}
                score_data = entry.get("score", {}) or {}

                player_name = athlete.get("displayName", "Unknown")
                player_id = athlete.get("id", "")

                # Get headshot - prefer ESPN API data, fall back to our DB,
                # last resort construct from player_id (same URL template ESPN uses).
                headshot_url = (athlete.get("headshot") or {}).get("href")
                if not headshot_url:
                    headshot_url = get_espn_headshot_url(player_name)
                if not headshot_url and player_id:
                    headshot_url = (
                        f"https://a.espncdn.com/i/headshots/golf/players/full/{player_id}.png"
                    )

                # Country: prefer our hardcoded DB for a clean 3-letter code,
                # then fall back to extracting the ISO code from ESPN's flag URL
                # (.../countries/500/usa.png → USA).
                country = get_player_country(player_name) or ""
                if not country:
                    flag_data = athlete.get("flag") or {}
                    flag_href = flag_data.get("href", "") or ""
                    if "/countries/" in flag_href:
                        try:
                            code = flag_href.rsplit("/", 1)[-1].split(".", 1)[0]
                            country = code.upper()[:3]
                        except Exception:
                            country = ""
                    if not country:
                        alt = (flag_data.get("alt") or "").strip()
                        if 0 < len(alt) <= 3:
                            country = alt.upper()

                # Position: ESPN's current shape has position at status.position.displayName
                # (e.g. "T1", "2", "-"), with sortOrder as the numeric leaderboard rank.
                # The legacy `entry.position` field is typically null now.
                status_position = (status.get("position") or {}).get("displayName")
                position = status_position or entry.get("position") or entry.get("sortOrder") or "-"

                # thru: 0 before teeing off is shown as "-"
                thru_val = status.get("thru")
                if thru_val is None or thru_val == 0:
                    thru_display = "-"
                elif thru_val == 18:
                    thru_display = "F"
                else:
                    thru_display = thru_val

                players.append({
                    "position": position,
                    "player": player_name,
                    "player_id": player_id,
                    "country": country,
                    "score": self._calculate_score_to_par(entry),
                    "today": self._get_today_score(score_data),
                    "thru": thru_display,
                    "rounds": self._extract_round_scores(entry),
                    "headshot_url": headshot_url,
                    "current_hole": status.get("hole"),
                    "status": status.get("displayValue", ""),
                    "tee_time": status.get("teeTime"),
                })

        except Exception as e:
            self.logger.error(f"Error parsing leaderboard: {e}")

        return players

    def _calculate_score_to_par(self, entry: Dict) -> int:
        """Calculate player's score relative to par."""
        try:
            display_value = (entry.get("score") or {}).get("displayValue", "E")
            if not display_value or display_value in ("-", "E"):
                return 0
            if display_value.startswith("+"):
                return int(display_value[1:])
            if display_value.startswith("-") and len(display_value) > 1:
                return int(display_value)
            return 0
        except Exception:
            return 0

    def _get_today_score(self, score_data: Dict) -> Optional[int]:
        """Get today's round score relative to par (None when not yet playing)."""
        try:
            dv = score_data.get("displayValue")
            if dv in (None, "", "-"):
                return None
            value = score_data.get("value")
            if value is not None:
                return int(value)
        except Exception:
            pass
        return None

    def _extract_round_scores(self, entry: Dict) -> List[Optional[int]]:
        """Extract scores for each round. Placeholder values (value=0 and
        displayValue=='-') are treated as 'not yet completed' and left as None.
        """
        rounds = [None, None, None, None]
        try:
            linescores = entry.get("linescores", []) or []
            for i, linescore in enumerate(linescores[:4]):
                value = linescore.get("value")
                display = linescore.get("displayValue")
                if value is None:
                    continue
                if display in (None, "", "-"):
                    continue
                rounds[i] = int(value)
        except Exception:
            pass
        return rounds

    def _get_cache_ttl(self) -> int:
        """TTL derived from cached tournament meta, with safe hardcoded fallback.

        Avoids calling fetch_tournament_meta() (which could recurse into
        fetch_leaderboard) — only reads whatever is already in cache.
        """
        raw = self._safe_cache_get(CACHE_KEY_META, max_age=_NEVER_EXPIRE)
        if not raw:
            return 3600
        meta = self._rehydrate_meta(raw)
        status = meta.get("status")
        if status == "in":
            return 30
        start = meta.get("start_date")
        end = meta.get("end_date")
        if not isinstance(start, datetime):
            return 3600
        now = datetime.now(timezone.utc)
        if isinstance(end, datetime) and start <= now <= end:
            return 30
        if timedelta(0) <= start - now <= timedelta(days=3):
            return 300
        return 3600

    def _get_fallback_data(self, cache_key: str) -> List[Dict]:
        """Get stale cached data or mock data as fallback."""
        cached = self._safe_cache_get(cache_key, max_age=_NEVER_EXPIRE)
        if cached:
            self.logger.warning("Using stale cached data for %s", cache_key)
            return cached

        self.logger.warning("No fallback data for %s, using mock", cache_key)
        if "leaderboard" in cache_key:
            return self._generate_mock_leaderboard()
        return []

    def _generate_mock_leaderboard(self) -> List[Dict]:
        """Generate realistic mock leaderboard with real player data."""
        players = [
            {"pos": 1,    "name": "Scottie Scheffler",  "score": -12, "today": -4, "thru": 15, "rounds": [68, 67, 69, None]},
            {"pos": 2,    "name": "Rory McIlroy",       "score": -10, "today": -3, "thru": 16, "rounds": [70, 68, 68, None]},
            {"pos": 3,    "name": "Jon Rahm",           "score": -9,  "today": -2, "thru": 14, "rounds": [69, 69, 69, None]},
            {"pos": "T4", "name": "Brooks Koepka",      "score": -7,  "today": -1, "thru": 15, "rounds": [71, 68, 70, None]},
            {"pos": "T4", "name": "Viktor Hovland",     "score": -7,  "today": -2, "thru": 13, "rounds": [70, 69, 70, None]},
            {"pos": 6,    "name": "Xander Schauffele",  "score": -6,  "today": 0,  "thru": 16, "rounds": [68, 71, 69, None]},
            {"pos": 7,    "name": "Collin Morikawa",    "score": -5,  "today": -1, "thru": 14, "rounds": [72, 68, 69, None]},
            {"pos": 8,    "name": "Jordan Spieth",      "score": -4,  "today": 0,  "thru": 15, "rounds": [70, 70, 70, None]},
            {"pos": "T9", "name": "Patrick Cantlay",    "score": -3,  "today": -1, "thru": 12, "rounds": [71, 70, 70, None]},
            {"pos": "T9", "name": "Ludvig Aberg",       "score": -3,  "today": +1, "thru": 14, "rounds": [69, 71, 71, None]},
            {"pos": 11,   "name": "Tiger Woods",        "score": -2,  "today": 0,  "thru": 13, "rounds": [72, 70, 70, None]},
            {"pos": 12,   "name": "Hideki Matsuyama",   "score": -1,  "today": +1, "thru": 15, "rounds": [70, 72, 69, None]},
            {"pos": "T13","name": "Tommy Fleetwood",    "score": 0,   "today": 0,  "thru": 14, "rounds": [71, 71, 70, None]},
            {"pos": "T13","name": "Shane Lowry",        "score": 0,   "today": -1, "thru": 12, "rounds": [73, 70, 69, None]},
            {"pos": 15,   "name": "Adam Scott",         "score": +1,  "today": +2, "thru": 16, "rounds": [72, 70, 73, None]},
        ]

        result = []
        for p in players:
            name = p["name"]
            pid_info = ESPN_PLAYER_IDS.get(name, {})
            player_id = pid_info.get("id", f"mock_{name.replace(' ', '_')}")
            country = pid_info.get("country", "USA")
            headshot_url = get_espn_headshot_url(name)

            result.append({
                "position": p["pos"],
                "player": name,
                "player_id": player_id,
                "country": country,
                "score": p["score"],
                "today": p["today"],
                "thru": p["thru"],
                "rounds": p["rounds"],
                "headshot_url": headshot_url,
                "current_hole": p["thru"] + 1 if isinstance(p["thru"], int) and p["thru"] < 18 else None,
                "status": f"Thru {p['thru']}",
            })

        return result

    def _generate_mock_schedule(self) -> List[Dict]:
        """Generate mock schedule data."""
        return [
            {"time": "8:00 AM",  "players": ["Tiger Woods", "Phil Mickelson", "Adam Scott"]},
            {"time": "8:15 AM",  "players": ["Scottie Scheffler", "Rory McIlroy", "Jon Rahm"]},
            {"time": "8:30 AM",  "players": ["Brooks Koepka", "Viktor Hovland", "Xander Schauffele"]},
            {"time": "8:45 AM",  "players": ["Jordan Spieth", "Collin Morikawa", "Patrick Cantlay"]},
            {"time": "9:00 AM",  "players": ["Ludvig Aberg", "Hideki Matsuyama", "Tommy Fleetwood"]},
            {"time": "9:15 AM",  "players": ["Shane Lowry", "Tony Finau", "Max Homa"]},
        ]
