"""
Data sources for the upcoming-media plugin.

Three sources, each turning its server's calendar into ``UpcomingItem``s:

- ``SonarrSource``  -- ``GET /api/v3/calendar`` (episodes, real air times)
- ``RadarrSource``  -- ``GET /api/v3/calendar`` (movies; one item per release
  type -- in cinemas, digital, physical -- that falls in the window)
- ``JellyfinSource`` -- ``GET /Shows/Upcoming`` (episodes of series already in
  the library; Jellyfin has no notion of an unreleased movie)

The module name is plugin-unique on purpose: the core loads every plugin's
top-level modules by bare name, so a generic ``sources.py`` could bind another
plugin's module (CLAUDE.md non-negotiable 4).

Nothing here draws. The parsers are pure functions over the decoded JSON, so
tests (and the safety harness, through the cache) can feed canned payloads.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

try:  # requests is a declared dependency; the guard keeps the parsers testable
    import requests
except ImportError:  # pragma: no cover
    requests = None

from PIL import Image

REQUEST_TIMEOUT = 8
IMAGE_TIMEOUT = 6
# Largest edge an image is kept at in memory. The biggest box the renderer asks
# for is a 256x128 panel's logo strip, so anything larger is wasted RAM on a Pi.
IMAGE_KEEP_EDGE = 320

# Radarr's three release dates, in the order a movie normally reaches them.
RADARR_RELEASE_FIELDS = (
    ("inCinemas", "cinema", "In Theaters"),
    ("digitalRelease", "digital", "Digital"),
    ("physicalRelease", "physical", "Physical"),
)
RADARR_RELEASE_TYPES = tuple(key for _, key, _ in RADARR_RELEASE_FIELDS)


@dataclass
class UpcomingItem:
    """One thing that is coming out: an episode, or a movie release."""

    kind: str                       # "episode" | "movie"
    uid: str                        # unique per item (source + id [+ release])
    group_id: str                   # series/movie id; next-per-show groups on it
    title: str                      # series name or movie title
    when: datetime                  # aware UTC
    has_time: bool                  # False when the source only knows the day
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: str = ""
    overview: str = ""
    runtime_min: Optional[int] = None
    release_label: str = ""         # movies: "Digital", "In Theaters", ...
    has_file: bool = False
    year: Optional[int] = None
    # Image URLs (absolute) and the headers each needs; logo and poster.
    images: Dict[str, str] = field(default_factory=dict)
    image_headers: Dict[str, Dict[str, str]] = field(default_factory=dict)
    source: str = ""
    # Set when several episodes of a show air the same day and were merged
    # into this one card: the last episode number and how many there are.
    episode_end: Optional[int] = None
    episode_count: int = 1

    def local_date(self, tz) -> date:
        """The calendar day this airs on, in ``tz``.

        A date-only release (Radarr, Jellyfin) is stamped midnight UTC; moving
        that into a zone west of UTC would put it on the previous day, so a
        date-only item keeps its UTC date.
        """
        if not self.has_time:
            return self.when.date()
        return self.when.astimezone(tz).date() if tz else self.when.date()


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------

def parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or None.

    Accepts a trailing ``Z``, an offset, a bare date, and the 7-digit
    fractional seconds .NET servers (Jellyfin) emit, which ``fromisoformat``
    rejects before Python 3.11.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    # Trim fractional seconds to 6 digits.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_date_only(value: Any) -> bool:
    """True when a timestamp carries no real time of day (midnight UTC or bare)."""
    if not isinstance(value, str):
        return True
    if len(value.strip()) <= 10:
        return True
    parsed = parse_iso(value)
    return parsed is not None and (parsed.hour, parsed.minute, parsed.second) == (0, 0, 0)


def _int_or_none(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _origin(url: str) -> Tuple[str, str]:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower(), 0)
    return parts.scheme.lower(), f"{host}:{port}"


def _url_tag(url: str) -> str:
    """Short stable tag for a server URL, so cache keys differ per server."""
    return hashlib.sha256((url or "").strip().rstrip("/").lower().encode("utf-8")).hexdigest()[:10]


def _image_urls(images: Any, base_url: str) -> Dict[str, Dict[str, str]]:
    """Pick logo and poster out of an *arr ``images`` list.

    Returns ``{"logo": {"local": url, "remote": url}, "poster": {...}}``.
    ``local`` is the *arr's own MediaCover copy (needs the API key, works with
    no internet); ``remote`` is TheTVDB/TMDB (no key).
    """
    wanted = {"clearlogo": "logo", "poster": "poster"}
    picked: Dict[str, Dict[str, str]] = {}
    for image in images or []:
        if not isinstance(image, dict):
            continue
        slot = wanted.get(str(image.get("coverType", "")).lower())
        if not slot:
            continue
        entry: Dict[str, str] = {}
        local = image.get("url")
        if isinstance(local, str) and local:
            # urljoin keeps a URL base (/sonarr) the server already put in the
            # path, instead of doubling it.
            joined = urljoin(base_url.rstrip("/") + "/", local)
            # Only the server's own copy is "local" (and gets the API key); an
            # absolute URL to another host must never receive it.
            if _origin(joined) == _origin(base_url):
                entry["local"] = joined
        remote = image.get("remoteUrl")
        if isinstance(remote, str) and remote.startswith("http"):
            entry["remote"] = remote
        if entry:
            picked[slot] = entry
    return picked


def _pick_image_url(entry: Dict[str, str], prefer_local: bool) -> Tuple[Optional[str], bool]:
    """(url, is_local) from an _image_urls entry."""
    order = ("local", "remote") if prefer_local else ("remote", "local")
    for key in order:
        if entry.get(key):
            return entry[key], key == "local"
    return None, False


def first_sentence(text: str) -> str:
    """The overview's first sentence, or the whole thing when it has one."""
    text = " ".join((text or "").split())
    match = re.search(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def short_description(text: str, max_chars: int) -> str:
    """A short, LED-sized blurb: first sentence, then cut at a word boundary."""
    blurb = first_sentence(text)
    if max_chars <= 0 or len(blurb) <= max_chars:
        return blurb
    cut = blurb[: max_chars - 3]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "..."


# ---------------------------------------------------------------------------
# Parsers (pure: decoded JSON in, items out)
# ---------------------------------------------------------------------------

def parse_sonarr_calendar(payload: Any, base_url: str, api_key: str = "",
                          prefer_local_images: bool = True) -> List[UpcomingItem]:
    items: List[UpcomingItem] = []
    if not isinstance(payload, list):
        return items
    for ep in payload:
        if not isinstance(ep, dict):
            continue
        series = ep.get("series") or {}
        when_raw = ep.get("airDateUtc") or ep.get("airDate")
        when = parse_iso(when_raw)
        if when is None:
            continue
        season = ep.get("seasonNumber")
        number = ep.get("episodeNumber")
        item = UpcomingItem(
            kind="episode",
            uid=f"sonarr:{ep.get('id', '')}",
            group_id=f"sonarr:{ep.get('seriesId', series.get('id', ''))}",
            title=str(series.get("title") or ep.get("seriesTitle") or "Unknown series"),
            when=when,
            has_time=bool(ep.get("airDateUtc")),
            season=season if isinstance(season, int) else None,
            episode=number if isinstance(number, int) else None,
            episode_title=str(ep.get("title") or ""),
            overview=str(ep.get("overview") or ""),
            # Sonarr v4 has a per-episode runtime; v3 only the series'.
            runtime_min=_int_or_none(ep.get("runtime")) or _int_or_none(series.get("runtime")),
            has_file=bool(ep.get("hasFile")),
            year=_int_or_none(series.get("year")),
            source="sonarr",
        )
        for slot, entry in _image_urls(series.get("images"), base_url).items():
            url, local = _pick_image_url(entry, prefer_local_images)
            if url:
                item.images[slot] = url
                if local and api_key:
                    item.image_headers[slot] = {"X-Api-Key": api_key}
        # Placeholder titles Sonarr uses before the real one is known.
        if item.episode_title.upper() in ("TBA", "TBD"):
            item.episode_title = ""
        items.append(item)
    return items


def parse_radarr_calendar(payload: Any, base_url: str, api_key: str = "",
                          release_types: Iterable[str] = RADARR_RELEASE_TYPES,
                          prefer_local_images: bool = True) -> List[UpcomingItem]:
    wanted = set(release_types or RADARR_RELEASE_TYPES)
    items: List[UpcomingItem] = []
    if not isinstance(payload, list):
        return items
    for movie in payload:
        if not isinstance(movie, dict):
            continue
        images = _image_urls(movie.get("images"), base_url)
        seen_days = set()
        for field_name, key, label in RADARR_RELEASE_FIELDS:
            if key not in wanted:
                continue
            when = parse_iso(movie.get(field_name))
            if when is None or when.date() in seen_days:
                continue
            seen_days.add(when.date())
            item = UpcomingItem(
                kind="movie",
                uid=f"radarr:{movie.get('id', '')}:{key}",
                group_id=f"radarr:{movie.get('id', '')}",
                title=str(movie.get("title") or "Unknown movie"),
                when=when,
                has_time=False,
                overview=str(movie.get("overview") or ""),
                runtime_min=_int_or_none(movie.get("runtime")),
                release_label=label,
                has_file=bool(movie.get("hasFile")),
                year=_int_or_none(movie.get("year")),
                source="radarr",
            )
            for slot, entry in images.items():
                url, local = _pick_image_url(entry, prefer_local_images)
                if url:
                    item.images[slot] = url
                    if local and api_key:
                        item.image_headers[slot] = {"X-Api-Key": api_key}
            items.append(item)
    return items


def parse_jellyfin_upcoming(payload: Any, base_url: str, api_key: str = "") -> List[UpcomingItem]:
    rows = payload.get("Items") if isinstance(payload, dict) else payload
    items: List[UpcomingItem] = []
    if not isinstance(rows, list):
        return items
    base = base_url.rstrip("/")
    headers = {"Authorization": f'MediaBrowser Token="{api_key}"'} if api_key else {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        premiere = row.get("PremiereDate")
        when = parse_iso(premiere)
        if when is None:
            continue
        # Jellyfin knows only the air *date*, stamped as midnight in the
        # server's zone (05:00Z on an Eastern server), never a real time.
        # Snap it to the nearest UTC midnight so the date survives for
        # servers east or west of UTC, and treat it as date-only.
        when = datetime.combine((when + timedelta(hours=12)).date(), datetime.min.time(),
                                tzinfo=timezone.utc)
        series_id = row.get("SeriesId") or row.get("Id") or ""
        ticks = row.get("RunTimeTicks")
        runtime = None
        if isinstance(ticks, (int, float)) and ticks > 0:
            runtime = _int_or_none(round(ticks / 600_000_000))
        item = UpcomingItem(
            kind="episode",
            uid=f"jellyfin:{row.get('Id', '')}",
            group_id=f"jellyfin:{series_id}",
            title=str(row.get("SeriesName") or row.get("Name") or "Unknown series"),
            when=when,
            has_time=False,
            season=row.get("ParentIndexNumber") if isinstance(row.get("ParentIndexNumber"), int) else None,
            episode=row.get("IndexNumber") if isinstance(row.get("IndexNumber"), int) else None,
            episode_title=str(row.get("Name") or "") if row.get("SeriesName") else "",
            overview=str(row.get("Overview") or ""),
            runtime_min=runtime,
            has_file=row.get("LocationType") not in (None, "Virtual"),
            year=_int_or_none(row.get("ProductionYear")),
            source="jellyfin",
        )
        if item.episode_title.upper() in ("TBA", "TBD"):
            item.episode_title = ""
        if series_id:
            item.images["logo"] = f"{base}/Items/{series_id}/Images/Logo"
            item.images["poster"] = f"{base}/Items/{series_id}/Images/Primary"
            if headers:
                item.image_headers = {"logo": headers, "poster": headers}
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------

def select_items(items: List[UpcomingItem], now: datetime, tz, days_ahead: int,
                 window: str = "upcoming_list", include_aired_today: bool = True,
                 max_items: int = 10, include_downloaded: bool = True,
                 group_episodes: bool = True) -> List[UpcomingItem]:
    """The items to show, soonest first.

    ``now`` is aware. Items run from the start of today (or from ``now`` when
    ``include_aired_today`` is off) through the end of the day ``days_ahead``
    days out, so "7" means today plus the next seven days.
    ``window == "next_per_show"`` keeps only each series' soonest episode.
    ``group_episodes`` merges a run of consecutive episodes of one show on the
    same day into one item (see ``group_same_day``).
    """
    today = now.astimezone(tz).date() if tz else now.date()
    last_day = today + timedelta(days=max(0, int(days_ahead)))
    chosen: List[UpcomingItem] = []
    for item in items:
        day = item.local_date(tz)
        if day < today or day > last_day:
            continue
        if not include_aired_today and item.has_time and item.when < now:
            continue
        if not include_downloaded and item.has_file:
            continue
        chosen.append(item)
    chosen.sort(key=lambda i: (i.local_date(tz), i.when, i.title, i.season or 0, i.episode or 0))
    if group_episodes:
        chosen = group_same_day(chosen, tz)
    if window == "next_per_show":
        seen = set()
        unique = []
        for item in chosen:
            if item.group_id in seen:
                continue
            seen.add(item.group_id)
            unique.append(item)
        chosen = unique
    if max_items and max_items > 0:
        chosen = chosen[: int(max_items)]
    return chosen


def group_same_day(items: List[UpcomingItem], tz) -> List[UpcomingItem]:
    """Merge consecutive episodes of one season of a show that air on the
    same day (a streaming drop, a double bill) into a single item.

    ``items`` must be sorted soonest first. The merged item keeps the first
    episode's air time, runtime and overview; ``episode_end`` is the last
    episode number and the episode name becomes "N episodes". Only an unbroken
    run merges: E5 and E7 without E6 stay separate.
    """
    out: List[UpcomingItem] = []
    heads: Dict[Tuple[str, date, Optional[int]], int] = {}
    for item in items:
        if item.kind != "episode" or item.episode is None:
            out.append(item)
            continue
        key = (item.group_id, item.local_date(tz), item.season)
        at = heads.get(key)
        if at is not None:
            head = out[at]
            last = head.episode_end if head.episode_end is not None else head.episode
            if last is not None and item.episode == last + 1:
                count = head.episode_count + 1
                out[at] = replace(
                    head, uid=f"{head.uid.split('+')[0]}+{count}", episode_end=item.episode,
                    episode_count=count, episode_title=f"{count} episodes",
                    has_file=head.has_file and item.has_file,
                    runtime_min=head.runtime_min or item.runtime_min,
                    overview=head.overview or item.overview)
                continue
        heads[key] = len(out)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Network sources
# ---------------------------------------------------------------------------

class SourceError(Exception):
    """A source could not be read; ``message`` is short enough for a panel."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(detail or message)
        self.message = message


def _get_json(url: str, *, params=None, headers=None, timeout=REQUEST_TIMEOUT, name="Server"):
    if requests is None:
        raise SourceError(f"{name}: no requests")
    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise SourceError(f"{name}: offline", f"{name} unreachable: {type(e).__name__}") from e
    if response.status_code in (401, 403):
        raise SourceError(f"{name}: bad API key", f"{name} rejected the API key ({response.status_code})")
    if response.status_code >= 400:
        raise SourceError(f"{name}: HTTP {response.status_code}",
                          f"{name} returned HTTP {response.status_code} for {url}")
    try:
        return response.json()
    except ValueError as e:
        raise SourceError(f"{name}: bad reply", f"{name} returned non-JSON from {url}") from e


class _ArrSource:
    name = "Arr"
    cache_name = "arr"

    def __init__(self, url: str, api_key: str, include_unmonitored: bool = False,
                 prefer_local_images: bool = True):
        self.url = (url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.include_unmonitored = bool(include_unmonitored)
        self.prefer_local_images = prefer_local_images

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key)

    def cache_key(self, days_ahead: int) -> str:
        return (f"upcoming-media:{self.cache_name}:{_url_tag(self.url)}:"
                f"d{int(days_ahead)}:u{int(self.include_unmonitored)}")

    def fetch_raw(self, now: datetime, days_ahead: int) -> Any:
        start = (now - timedelta(days=1)).date().isoformat()
        end = (now + timedelta(days=int(days_ahead) + 2)).date().isoformat()
        params = {"start": start, "end": end,
                  "unmonitored": str(self.include_unmonitored).lower()}
        params.update(self.extra_params())
        payload = _get_json(f"{self.url}/api/v3/calendar", params=params,
                            headers={"X-Api-Key": self.api_key}, name=self.name)
        if not isinstance(payload, list):
            raise SourceError(f"{self.name}: bad reply", f"{self.name} calendar was not a list")
        return payload

    def extra_params(self) -> Dict[str, str]:
        return {}


class SonarrSource(_ArrSource):
    name = "Sonarr"
    cache_name = "sonarr"

    def extra_params(self):
        return {"includeSeries": "true"}

    def parse(self, payload: Any) -> List[UpcomingItem]:
        return parse_sonarr_calendar(payload, self.url, self.api_key, self.prefer_local_images)


class RadarrSource(_ArrSource):
    name = "Radarr"
    cache_name = "radarr"

    def __init__(self, *args, release_types: Iterable[str] = RADARR_RELEASE_TYPES, **kwargs):
        super().__init__(*args, **kwargs)
        self.release_types = tuple(release_types or RADARR_RELEASE_TYPES)

    def parse(self, payload: Any) -> List[UpcomingItem]:
        return parse_radarr_calendar(payload, self.url, self.api_key, self.release_types,
                                     self.prefer_local_images)


class JellyfinSource:
    name = "Jellyfin"
    cache_name = "jellyfin"

    def __init__(self, url: str, api_key: str, username: str = "",
                 libraries: Iterable[str] = (), limit: int = 200):
        self.url = (url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.username = (username or "").strip()
        self.libraries = [str(lib).strip() for lib in (libraries or []) if str(lib).strip()]
        self.limit = limit
        self._user_id: Optional[str] = None
        self._library_ids: Optional[List[str]] = None

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f'MediaBrowser Token="{self.api_key}"'}

    def cache_key(self, days_ahead: int) -> str:
        libs = ",".join(sorted(lib.lower() for lib in self.libraries)) or "all"
        return f"upcoming-media:jellyfin:{_url_tag(self.url)}:{self.username.lower() or '-'}:{libs}"

    def _resolve_user(self) -> Optional[str]:
        if self._user_id is not None:
            return self._user_id or None
        users = _get_json(f"{self.url}/Users", headers=self._headers(), name=self.name)
        chosen = ""
        if isinstance(users, list) and users:
            if self.username:
                for user in users:
                    if str(user.get("Name", "")).lower() == self.username.lower():
                        chosen = str(user.get("Id", ""))
                        break
                if not chosen:
                    raise SourceError("Jellyfin: no user", f"Jellyfin has no user named {self.username!r}")
            else:
                admins = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
                chosen = str((admins or users)[0].get("Id", ""))
        self._user_id = chosen
        return chosen or None

    def _resolve_libraries(self) -> List[str]:
        if not self.libraries:
            return []
        if self._library_ids is not None:
            return self._library_ids
        folders = _get_json(f"{self.url}/Library/VirtualFolders", headers=self._headers(),
                            name=self.name)
        wanted = {lib.lower() for lib in self.libraries}
        ids = [str(f.get("ItemId")) for f in folders or []
               if isinstance(f, dict) and str(f.get("Name", "")).lower() in wanted and f.get("ItemId")]
        if not ids:
            raise SourceError("Jellyfin: no library",
                              f"None of the Jellyfin libraries {self.libraries} exist")
        self._library_ids = ids
        return ids

    def fetch_raw(self, now: datetime, days_ahead: int) -> Any:
        user_id = self._resolve_user()
        params: Dict[str, Any] = {
            "limit": self.limit,
            "fields": "Overview,PremiereDate,ProductionYear",
            "enableImages": "false",
            "enableUserData": "false",
        }
        if user_id:
            params["userId"] = user_id
        library_ids = self._resolve_libraries()
        rows: List[Any] = []
        for parent in library_ids or [None]:
            query = dict(params)
            if parent:
                query["parentId"] = parent
            payload = _get_json(f"{self.url}/Shows/Upcoming", params=query,
                                headers=self._headers(), name=self.name)
            rows.extend((payload or {}).get("Items") or [] if isinstance(payload, dict) else payload or [])
        return {"Items": rows}

    def parse(self, payload: Any) -> List[UpcomingItem]:
        return parse_jellyfin_upcoming(payload, self.url, self.api_key)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

class ImageStore:
    """Downloads item images once and hands out fitted copies.

    Downloads happen only in ``prefetch`` (called from update()); ``fitted``
    never touches the network, so display() stays I/O-free. A failed URL is
    not retried for ``retry_after`` seconds.

    With a ``cache`` (the plugin's cache_manager) each downloaded image is
    also kept there as a small base64 PNG for ``cache_max_age`` seconds, so a
    restart does not re-download every logo -- and the safety harness can seed
    artwork through its mock cache.
    """

    def __init__(self, logger=None, retry_after: float = 3600.0,
                 clock: Optional[Callable[[], float]] = None,
                 cache: Any = None, cache_max_age: float = 7 * 86400):
        import time as _time
        self.logger = logger
        self.retry_after = retry_after
        self.cache = cache
        self.cache_max_age = cache_max_age
        self._clock = clock or _time.monotonic
        self._originals: Dict[str, Image.Image] = {}
        self._failed: Dict[str, float] = {}
        self._fitted: Dict[Tuple[str, int, int, bool, bool], Image.Image] = {}

    @staticmethod
    def cache_key(url: str) -> str:
        return "upcoming-media:img:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def encode(image: Image.Image) -> str:
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _from_cache(self, url: str) -> Optional[Image.Image]:
        if self.cache is None:
            return None
        try:
            data = self.cache.get(self.cache_key(url), max_age=self.cache_max_age)
            if not isinstance(data, str) or not data:
                return None
            img = Image.open(BytesIO(base64.b64decode(data)))
            img.load()
            return img.convert("RGBA")
        except Exception:  # noqa: BLE001 -- a corrupt entry is just a miss
            return None

    def has(self, url: Optional[str]) -> bool:
        return bool(url) and url in self._originals

    def prefetch(self, url: Optional[str], headers: Optional[Dict[str, str]] = None) -> bool:
        if not url or url in self._originals:
            return bool(url)
        failed_at = self._failed.get(url)
        if failed_at is not None and self._clock() - failed_at < self.retry_after:
            return False
        cached = self._from_cache(url)
        if cached is not None:
            self._originals[url] = cached
            return True
        if requests is None:
            return False
        try:
            response = requests.get(url, headers=headers or {}, timeout=IMAGE_TIMEOUT)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            img.load()
            img = img.convert("RGBA")
            img.thumbnail((IMAGE_KEEP_EDGE, IMAGE_KEEP_EDGE), Image.Resampling.LANCZOS)
            self._originals[url] = img
            self._failed.pop(url, None)
            if self.cache is not None:
                try:
                    self.cache.set(self.cache_key(url), self.encode(img), ttl=self.cache_max_age)
                except Exception as e:  # noqa: BLE001 -- caching is best-effort
                    if self.logger:
                        self.logger.debug("Image cache write failed: %s", type(e).__name__)
            return True
        except Exception as e:  # noqa: BLE001 -- any bad image just falls back
            self._failed[url] = self._clock()
            if self.logger:
                self.logger.debug("Image fetch failed for %s: %s", url, type(e).__name__)
            return False

    def put(self, url: str, image: Image.Image) -> None:
        """Seed an image directly (tests, harness fixtures)."""
        self._originals[url] = image.convert("RGBA")

    def fitted(self, url: Optional[str], box: Tuple[int, int], trim: bool = False,
               brighten: bool = False) -> Optional[Image.Image]:
        """The image scaled to fit inside ``box`` (aspect kept), RGBA, or None.

        ``trim`` crops transparent margins first: clearlogos ship with padding
        that would waste a third of a 12-pixel-tall slot. ``brighten`` lifts a
        dim logo (see ``brighten``).
        """
        if not url or url not in self._originals or box[0] < 2 or box[1] < 2:
            return None
        key = (url, int(box[0]), int(box[1]), trim, brighten)
        cached = self._fitted.get(key)
        if cached is not None:
            return cached
        img = self._originals[url]
        if trim:
            bbox = img.getchannel("A").getbbox()
            if bbox:
                img = img.crop(bbox)
        scale = min(box[0] / img.width, box[1] / img.height)
        # Round, not truncate: a 2:3 poster in a 32-px slot is 31.5 px tall
        # and should fill all 32 rows.
        size = (max(1, min(int(box[0]), round(img.width * scale))),
                max(1, min(int(box[1]), round(img.height * scale))))
        fitted = img.resize(size, Image.Resampling.LANCZOS)
        if brighten:
            fitted = self.brighten(fitted)
        if len(self._fitted) > 256:
            self._fitted.clear()
        self._fitted[key] = fitted
        return fitted

    # A logo whose bright end sits below this is lifted toward LOGO_TARGET.
    # Clearlogos are made for TV screens; on an LED panel a dark-green or
    # mid-grey wordmark all but disappears against the black background.
    LOGO_DIM = 170
    LOGO_TARGET = 210
    LOGO_MAX_GAIN = 4.0
    # Below this share of lit pixels (after brightening) a logo is unreadable:
    # black-on-transparent art, or hairline letters scaled down to nothing.
    LOGO_MIN_INK = 0.12
    INK_LEVEL = 64

    @staticmethod
    def _opaque_luma(img: Image.Image):
        """(luma image, opaque mask, luma histogram of opaque pixels)."""
        rgba = img.convert("RGBA")
        luma = rgba.convert("RGB").convert("L")
        mask = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        return luma, mask, luma.histogram(mask=mask)

    @classmethod
    def brighten(cls, img: Image.Image) -> Image.Image:
        """Scale a dim logo's colours up so its 90th-percentile brightness
        reaches LOGO_TARGET (gain capped at LOGO_MAX_GAIN). Hue is kept;
        already-bright logos come back unchanged."""
        _, _, hist = cls._opaque_luma(img)
        total = sum(hist)
        if not total:
            return img
        seen, p90 = 0, 0
        for level, count in enumerate(hist):
            seen += count
            if seen >= total * 0.9:
                p90 = level
                break
        if p90 >= cls.LOGO_DIM:
            return img
        gain = min(cls.LOGO_MAX_GAIN, cls.LOGO_TARGET / max(p90, 1))
        rgba = img.convert("RGBA")
        r, g, b, a = rgba.split()
        lut = [min(255, int(v * gain + 0.5)) for v in range(256)]
        return Image.merge("RGBA", (r.point(lut), g.point(lut), b.point(lut), a))

    @classmethod
    def ink(cls, img: Image.Image) -> float:
        """Share of the image's pixels that are opaque and visibly lit."""
        hist = cls._opaque_luma(img)[2]
        area = img.width * img.height
        return sum(hist[cls.INK_LEVEL:]) / area if area else 0.0

    @classmethod
    def readable(cls, img: Optional[Image.Image]) -> bool:
        # Under 9 px tall a wordmark's letters merge into a smear.
        return img is not None and img.height >= 9 and cls.ink(img) >= cls.LOGO_MIN_INK

    def forget_unused(self, keep: Iterable[str]) -> None:
        keep = set(keep)
        for url in list(self._originals):
            if url not in keep:
                del self._originals[url]
        self._fitted = {k: v for k, v in self._fitted.items() if k[0] in keep}
