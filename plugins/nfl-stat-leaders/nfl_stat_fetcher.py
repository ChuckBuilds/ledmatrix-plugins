"""Fetch NFL statistical leaders from ESPN's public API.

ESPN serves season leaders without an API key, so this plugin needs no
credentials of any kind -- nothing is read from ``config_secrets.json`` and
nothing is ever logged that could leak one.

Two shapes of the same feed are tried in order. The ``common/v3`` endpoint
embeds the athlete object inside each leader, which is what makes a player's
name and position available without a second request; the older ``site/v2``
endpoint is the fallback for the day ESPN moves something. Both are parsed
by the same normaliser, because the leader objects inside them agree even
where the envelopes do not.

The one thing neither endpoint reliably embeds is the club: it is usually a
``$ref``. Resolving those would be one request per leader, so the franchise
id in the ref is mapped locally instead (``nfl_stat_teams``).

Module name is plugin-unique so the core's flat module loading cannot bind
another plugin's ``data_fetcher`` (monorepo CLAUDE.md non-negotiable #4).
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from nfl_stat_categories import StatCategory, match_feed_category
from nfl_stat_teams import abbr_from_ref, abbr_from_team_id, normalize_abbr

#: Identifies the project to ESPN. A bare or browser-style agent started
#: getting 403s in August 2026 (see nfl-draft 1.4.1); this one is accepted.
USER_AGENT = "LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)"

#: Embeds the athlete object in each leader -- preferred.
LEADERS_URL_V3 = (
    "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/leaders"
)
#: Older envelope, same leader objects. Tried only if the first yields nothing.
LEADERS_URL_V2 = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/leaders"
)

#: ESPN season types.
SEASON_TYPE_REGULAR = 2
SEASON_TYPE_POSTSEASON = 3

SEASON_TYPE_LABELS = {
    SEASON_TYPE_REGULAR: "REGULAR",
    SEASON_TYPE_POSTSEASON: "POSTSEASON",
}

#: Most leaders ESPN will be asked for in one category. The renderer shows at
#: most ``players_per_category``; asking for a few more costs nothing and
#: leaves room to drop a malformed entry without shortening the board.
MAX_LEADERS_REQUESTED = 20


def current_season_year(now: Optional[datetime] = None) -> int:
    """The season ESPN would label "current".

    A season is named for the calendar year it kicks off in, so January and
    February belong to the previous year's season. March is the cutover: by
    then the previous season is complete and the next has not started, and
    showing the season that just finished is what a viewer expects.
    """
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 3 else now.year - 1


class LeaderEntry(dict):
    """One player on one leaderboard.

    A plain dict subclass so the whole board survives ``save_cache``'s JSON
    round-trip unchanged; the class exists only to name the shape in one
    place. Keys: ``rank``, ``name``, ``position``, ``team``, ``value``.
    """


class StatFetcher:
    """Fetches and normalises ESPN's NFL leaders feed."""

    def __init__(self, cache_manager, logger: Optional[logging.Logger] = None,
                 request_timeout: int = 30):
        self.cache_manager = cache_manager
        self.logger = logger or logging.getLogger(__name__)
        self.request_timeout = request_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_boards(self, categories: List[StatCategory], season: int,
                     season_type: int, players_per_category: int,
                     max_age: int) -> List[Dict[str, Any]]:
        """Return one board per requested category, in the order given.

        ``max_age`` is how old a cached payload may be before ESPN is asked
        again; it comes from the plugin's ``update_interval`` so a user who
        refreshes hourly is not served a week-old board. Categories ESPN has
        no data for are dropped rather than drawn empty.
        """
        if not categories:
            return []

        payload = self._get_payload(season, season_type, max_age)
        if payload is None:
            return []

        feed_categories = _feed_categories(payload)
        if not feed_categories:
            self.logger.warning(
                "ESPN returned no leader categories for season %s type %s",
                season, season_type,
            )
            return []

        boards = []
        for category in categories:
            entry = match_feed_category(category, feed_categories)
            if entry is None:
                self.logger.info(
                    "ESPN has no '%s' leaderboard for season %s type %s",
                    category.key, season, season_type,
                )
                continue
            leaders = self._normalize_leaders(entry, players_per_category)
            if not leaders:
                self.logger.info(
                    "'%s' leaderboard came back empty for season %s type %s",
                    category.key, season, season_type,
                )
                continue
            boards.append({
                "key": category.key,
                "title": category.title,
                "short_title": category.short_title,
                "leaders": leaders,
            })
        return boards

    def resolve_season(self, configured_season: int, season_type: int,
                       max_age: int) -> int:
        """Pick the season to show.

        A configured non-zero season is used as given. ``0`` means auto: the
        current season, falling back to the one before it when the current
        one has no leaders yet. Without that fallback the panel is blank all
        summer, and again every March, which reads as a broken plugin rather
        than an empty season.
        """
        if configured_season:
            return int(configured_season)

        season = current_season_year()
        payload = self._get_payload(season, season_type, max_age)
        if payload is not None and _feed_categories(payload):
            return season

        previous = season - 1
        self.logger.info(
            "Season %s has no leaders yet; showing %s instead", season, previous
        )
        return previous

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _cache_key(self, season: int, season_type: int) -> str:
        # Namespaced by plugin id, as BasePlugin's caching guidance requires.
        return f"nfl-stat-leaders_{season}_{season_type}"

    def _get_payload(self, season: int, season_type: int,
                     max_age: int) -> Optional[Dict[str, Any]]:
        """The raw leaders payload, from cache when it is fresh enough."""
        cache_key = self._cache_key(season, season_type)
        cached = self._read_cache(cache_key, max_age)
        if cached is not None:
            self.logger.debug("Using cached leaders for %s", cache_key)
            return cached

        payload = self._request_payload(season, season_type)
        if payload is None:
            # Nothing fresh and nothing new. A stale payload still beats a
            # blank panel during an ESPN outage, so fall back to whatever is
            # on disk regardless of age.
            stale = self._read_cache(cache_key, max_age=_STALE_MAX_AGE)
            if stale is not None:
                self.logger.warning(
                    "ESPN unavailable; showing leaders cached earlier")
            return stale

        try:
            # get()/set() rather than save_cache(): the pair round-trips a
            # plain dict identically through the real CacheManager and the
            # test harness's mock, and set() is the only write whose max_age
            # the read side can then control.
            self.cache_manager.set(cache_key, {
                "fetched_at": time.time(),
                "payload": payload,
            })
        except Exception as exc:  # noqa: BLE001 - a cache write must not
            # cost us the fetch we just made.
            self.logger.warning("Could not cache leaders: %s", exc)
        return payload

    def _read_cache(self, cache_key: str, max_age: int) -> Optional[Dict[str, Any]]:
        try:
            record = self.cache_manager.get(cache_key, max_age=max_age)
        except Exception as exc:  # noqa: BLE001 - a broken cache is not fatal
            self.logger.warning("Could not read cached leaders: %s", exc)
            return None
        if not isinstance(record, dict):
            return None
        payload = record.get("payload")
        return payload if isinstance(payload, dict) else None

    def _request_payload(self, season: int,
                         season_type: int) -> Optional[Dict[str, Any]]:
        """Ask ESPN, preferring the endpoint that embeds athletes."""
        params = {
            "season": season,
            "seasontype": season_type,
            "limit": MAX_LEADERS_REQUESTED,
        }
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

        for url in (LEADERS_URL_V3, LEADERS_URL_V2):
            try:
                response = requests.get(
                    url, params=params, headers=headers,
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                self.logger.warning("Leaders request to %s failed: %s", url, exc)
                continue
            except ValueError as exc:
                self.logger.warning("Leaders response from %s was not JSON: %s",
                                    url, exc)
                continue

            if isinstance(payload, dict) and _feed_categories(payload):
                self.logger.info(
                    "Fetched NFL leaders for season %s type %s from %s",
                    season, season_type, url,
                )
                return payload
            self.logger.debug("No categories in the response from %s", url)
        return None

    # ------------------------------------------------------------------
    # Normalising
    # ------------------------------------------------------------------

    def _normalize_leaders(self, feed_category: Dict[str, Any],
                           limit: int) -> List[LeaderEntry]:
        """Turn ESPN's leader objects into the flat rows the renderer draws."""
        raw = feed_category.get("leaders")
        if not isinstance(raw, list):
            return []

        rows: List[LeaderEntry] = []
        for item in raw:
            if len(rows) >= limit:
                break
            row = _leader_row(item, len(rows) + 1)
            if row is not None:
                rows.append(row)
        return rows


#: A cached payload older than this is treated as absent even during an
#: outage. Two weeks is long enough to cover a holiday-season API wobble and
#: short enough that a Pi left running over the summer does not show last
#: season's board as if it were live.
_STALE_MAX_AGE = 14 * 24 * 3600


def _feed_categories(payload: Any) -> List[dict]:
    """The category list, whichever envelope ESPN used.

    ``common/v3`` puts it at the root; ``site/v2`` nests it under
    ``leaders``, and has also served ``leaders`` as the list itself.
    """
    if not isinstance(payload, dict):
        return []

    root = payload.get("categories")
    if isinstance(root, list) and root:
        return root

    nested = payload.get("leaders")
    if isinstance(nested, dict):
        inner = nested.get("categories")
        if isinstance(inner, list):
            return inner
    if isinstance(nested, list):
        return nested
    return []


def _leader_row(item: Any, rank: int) -> Optional[LeaderEntry]:
    """One normalised row, or None if the entry is unusable.

    A leader with no name is dropped: an anonymous row on a leaderboard is
    worse than a shorter leaderboard.
    """
    if not isinstance(item, dict):
        return None

    athlete = item.get("athlete")
    athlete = athlete if isinstance(athlete, dict) else {}

    name = _athlete_name(athlete)
    if not name:
        return None

    value = _leader_value(item)
    if not value:
        return None

    return LeaderEntry(
        rank=rank,
        name=name,
        position=_athlete_position(athlete),
        team=_leader_team(item, athlete) or "",
        value=value,
    )


def _athlete_name(athlete: Dict[str, Any]) -> str:
    """The shortest name that still identifies the player.

    ESPN's ``shortName`` is already "J. Allen", which is what fits a panel;
    the longer forms are only used when it is missing.
    """
    for field in ("shortName", "displayName", "fullName", "name"):
        value = athlete.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _athlete_position(athlete: Dict[str, Any]) -> str:
    position = athlete.get("position")
    if isinstance(position, dict):
        for field in ("abbreviation", "displayName", "name"):
            value = position.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
    if isinstance(position, str) and position.strip():
        return position.strip().upper()
    return ""


def _leader_team(item: Dict[str, Any], athlete: Dict[str, Any]) -> Optional[str]:
    """The club abbreviation, from whichever of ESPN's shapes is present."""
    for source in (item.get("team"), athlete.get("team")):
        if isinstance(source, dict):
            abbr = normalize_abbr(source.get("abbreviation"))
            if abbr:
                return abbr
            abbr = abbr_from_team_id(source.get("id"))
            if abbr:
                return abbr
            abbr = abbr_from_ref(source.get("$ref"))
            if abbr:
                return abbr
        elif isinstance(source, str):
            # Sometimes the whole team field is just the ref URL.
            abbr = abbr_from_ref(source) or normalize_abbr(source)
            if abbr:
                return abbr

    for field in ("teamId", "teamID"):
        abbr = abbr_from_team_id(item.get(field) or athlete.get(field))
        if abbr:
            return abbr
    return None


def _leader_value(item: Dict[str, Any]) -> str:
    """The number to draw, preferring ESPN's own formatting.

    ``displayValue`` already carries thousands separators and the right
    number of decimals for the stat ("4,183", "17", "98.4"), which is more
    correct than re-deriving them per category.
    """
    display = item.get("displayValue")
    if isinstance(display, str) and display.strip():
        return display.strip()

    value = item.get("value")
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.1f}"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""
