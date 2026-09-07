"""
Olympics data fetcher with lightweight lxml scraping.

Optimized for Raspberry Pi with:
- Aggressive caching to minimize requests
- Connection timeouts
- Response size limits
- Background thread support
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any


def _utcnow() -> datetime:
    """Get current UTC time as naive datetime (for internal comparisons)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
from pathlib import Path
import json

try:
    import requests
    from lxml import html
    SCRAPING_AVAILABLE = True
except ImportError:
    SCRAPING_AVAILABLE = False

from .data_models import MedalCount, OlympicEvent, EventResult, OlympicsData

logger = logging.getLogger(__name__)

# Known Games, oldest first. current_games() walks this and returns the one in
# progress, or the next one still to come.
#
# This used to be a single CURRENT_OLYMPICS dict pinned to Milano Cortina 2026.
# Once those Games closed the countdown simply went negative -- the plugin
# rendered "-210 DAYS UNTIL WINTER OLYMPICS" and would have kept counting
# downwards for ever.
#
# Add each Games here as its dates are confirmed. When the table runs out the
# plugin reports no Games rather than inventing a date, so the failure mode is a
# skipped screen and a log line, not a wrong one.
OLYMPIC_GAMES = [
    {
        'name': 'Milano Cortina 2026',
        'type': 'winter',
        'opening': datetime(2026, 2, 6),
        'closing': datetime(2026, 2, 22),
        'base_url': 'https://www.olympics.com/en/milano-cortina-2026',
    },
    {
        'name': 'Los Angeles 2028',
        'type': 'summer',
        'opening': datetime(2028, 7, 14),
        'closing': datetime(2028, 7, 30),
        'base_url': 'https://www.olympics.com/en/los-angeles-2028',
    },
]


def current_games(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The Games in progress or the next still to come; None if none are known.

    Returning None is deliberate: it lets the caller show nothing, which is
    honest, instead of counting down to a date that has passed.
    """
    if now is None:
        now = _utcnow()
    for games in OLYMPIC_GAMES:
        if now <= games['closing']:
            return games
    return None

# Cache configuration (in seconds)
CACHE_DURATION = {
    'medals': 600,      # 10 minutes
    'schedule': 1800,   # 30 minutes
    'results': 900,     # 15 minutes
}

# Request configuration
REQUEST_TIMEOUT = 15  # seconds
MAX_RESPONSE_SIZE = 4 * 1024 * 1024  # 4MB (schedule page is ~3MB)
USER_AGENT = 'LEDMatrix-Olympics/2.0 (Raspberry Pi)'

# Static schedule file (pre-generated to avoid 3MB fetch)
STATIC_SCHEDULE_FILE = Path(__file__).parent / 'static_schedule.json'
SCHEDULE_UPDATE_INTERVAL = 86400  # 24 hours


class OlympicsCache:
    """Simple in-memory cache with file backup."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.cache_dir = cache_dir or Path(__file__).parent / '.cache'
        self.cache_dir.mkdir(exist_ok=True)

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() < entry['expires']:
                    return entry['data']
                else:
                    del self._cache[key]

            # Try loading from file cache
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, 'r') as f:
                        entry = json.load(f)
                    if time.time() < entry['expires']:
                        self._cache[key] = entry
                        return entry['data']
                except (json.JSONDecodeError, KeyError):
                    pass

            return None

    def set(self, key: str, data: Any, ttl: int) -> None:
        """Cache data with TTL in seconds."""
        with self._lock:
            entry = {
                'data': data,
                'expires': time.time() + ttl,
                'cached_at': time.time()
            }
            self._cache[key] = entry

            # Also save to file for persistence across restarts
            cache_file = self.cache_dir / f"{key}.json"
            try:
                with open(cache_file, 'w') as f:
                    json.dump(entry, f)
            except Exception as e:
                logger.debug(f"Failed to write cache file: {e}")

    def get_age(self, key: str) -> Optional[float]:
        """Get age of cached entry in seconds."""
        with self._lock:
            if key in self._cache:
                return time.time() - self._cache[key].get('cached_at', 0)
        return None

    def clear(self) -> None:
        """Clear all cached data (memory and files)."""
        with self._lock:
            self._cache.clear()
            for f in self.cache_dir.glob('*.json'):
                try:
                    f.unlink()
                except Exception:
                    pass


class OlympicsDataFetcher:
    """
    Fetches Olympics data via lightweight web scraping.

    Optimized for Raspberry Pi with aggressive caching and
    minimal resource usage.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.cache = OlympicsCache()
        self._session: Optional[requests.Session] = None
        # Per-resource locks to avoid serializing all fetches
        self._medals_lock = threading.Lock()
        self._schedule_lock = threading.Lock()
        self._results_lock = threading.Lock()
        self._live_lock = threading.Lock()
        self._last_fetch_error: Optional[str] = None
        self._static_schedule: Optional[List[Dict]] = None
        self._static_schedule_loaded = False
        self._last_schedule_update: float = 0

        # Load static schedule on init
        self._load_static_schedule()

        if not SCRAPING_AVAILABLE:
            logger.warning("requests/lxml not available - scraping disabled")

    def _load_static_schedule(self) -> bool:
        """Load pre-generated schedule from static JSON file."""
        if not STATIC_SCHEDULE_FILE.exists():
            logger.info("No static schedule file found, will fetch from web")
            return False

        try:
            with open(STATIC_SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._static_schedule = data.get('events', [])
            meta = data.get('meta', {})

            logger.info(
                f"Loaded static schedule: {len(self._static_schedule)} events "
                f"(generated {meta.get('generated_at', 'unknown')})"
            )
            self._static_schedule_loaded = True
            return True

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load static schedule: {e}")
            return False

    @property
    def session(self) -> 'requests.Session':
        """Lazy-loaded requests session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                'User-Agent': USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'en-US,en;q=0.9',
            })
        return self._session

    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch a page with timeout and size limits."""
        if not SCRAPING_AVAILABLE:
            return None

        try:
            response = self.session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                stream=True
            )
            response.raise_for_status()

            # Check content length
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                logger.warning(f"Response too large: {content_length} bytes")
                response.close()
                return None

            # Read with size limit (use list to avoid O(n²) concatenation)
            chunks = []
            total_size = 0
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    chunks.append(chunk)
                    total_size += len(chunk)
                    if total_size > MAX_RESPONSE_SIZE:
                        logger.warning("Response exceeded size limit")
                        return None
            finally:
                response.close()

            return b''.join(chunks).decode('utf-8', errors='replace')

        except requests.Timeout:
            logger.warning(f"Timeout fetching {url}")
            self._last_fetch_error = "timeout"
        except requests.RequestException as e:
            logger.warning(f"Error fetching {url}: {e}")
            self._last_fetch_error = str(e)
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            self._last_fetch_error = str(e)

        return None

    def fetch_medal_counts(self) -> List[MedalCount]:
        """
        Fetch current medal standings.

        Returns cached data if available, otherwise scrapes fresh data.
        """
        cache_key = 'medals'

        # Check cache first
        cached = self.cache.get(cache_key)
        if cached is not None:
            return [MedalCount(**m) for m in cached]

        with self._medals_lock:
            # Double-check cache after acquiring lock
            cached = self.cache.get(cache_key)
            if cached is not None:
                return [MedalCount(**m) for m in cached]

            medals = self._scrape_medals()
            if medals:
                # Cache as dicts for JSON serialization
                medal_dicts = [
                    {
                        'country_code': m.country_code,
                        'country_name': m.country_name,
                        'gold': m.gold,
                        'silver': m.silver,
                        'bronze': m.bronze,
                        'total': m.total,
                        'rank': m.rank,
                    }
                    for m in medals
                ]
                self.cache.set(cache_key, medal_dicts, CACHE_DURATION['medals'])

            return medals

    def _scrape_medals(self) -> List[MedalCount]:
        """
        Scrape medal counts from Olympics.com.

        Olympics.com embeds medal data as JSON in a script tag with
        the key 'result_medals_data'. This is much more reliable than
        trying to parse the client-side rendered HTML.
        """
        games = current_games()
        if games is None:
            logger.info("No upcoming Olympics in OLYMPIC_GAMES; nothing to fetch")
            return []
        url = f"{games['base_url']}/medals"
        page_content = self._fetch_page(url)

        if not page_content:
            logger.warning("Failed to fetch medals page")
            return []

        try:
            tree = html.fromstring(page_content)
            medals = []

            # Find script tags containing JSON data
            scripts = tree.xpath('//script/text()')

            for script in scripts:
                if 'result_medals_data' not in script:
                    continue
                if len(script) < 1000:
                    continue

                try:
                    data = json.loads(script)
                    if 'result_medals_data' not in data:
                        continue

                    medals_data = data['result_medals_data']
                    initial_medals = medals_data.get('initialMedals', {})
                    standings = initial_medals.get('medalStandings', {})
                    medals_table = standings.get('medalsTable', [])

                    for country in medals_table:
                        try:
                            medal = self._parse_embedded_medal(country)
                            if medal:
                                medals.append(medal)
                        except Exception as e:
                            logger.debug(f"Error parsing medal entry: {e}")
                            continue

                    logger.info(f"Parsed {len(medals)} countries from embedded JSON")
                    return medals

                except json.JSONDecodeError:
                    continue

            # Fallback: try traditional table parsing
            logger.warning("No embedded JSON found, trying table parsing")
            return self._scrape_medals_fallback(tree)

        except Exception as e:
            logger.error(f"Error parsing medals page: {e}")
            return []

    def _parse_embedded_medal(self, country_data: Dict[str, Any]) -> Optional[MedalCount]:
        """Parse a single country's medal data from embedded JSON."""
        org = country_data.get('organisation', '')
        if not org:
            return None

        country_name = country_data.get('longDescription', org)
        rank = country_data.get('rank', 0)

        # Sum medals across all disciplines
        total_gold = 0
        total_silver = 0
        total_bronze = 0

        for disc in country_data.get('disciplines', []):
            total_gold += disc.get('gold', 0)
            total_silver += disc.get('silver', 0)
            total_bronze += disc.get('bronze', 0)

        total = total_gold + total_silver + total_bronze

        if total == 0:
            return None

        return MedalCount(
            country_code=org,
            country_name=country_name,
            gold=total_gold,
            silver=total_silver,
            bronze=total_bronze,
            total=total,
            rank=rank
        )

    def _scrape_medals_fallback(self, tree) -> List[MedalCount]:
        """Fallback table-based scraping if embedded JSON not found."""
        medals = []

        selectors = [
            '//table[contains(@class, "medal")]//tr',
            '//div[contains(@class, "medal-table")]//tr',
            '//*[contains(@class, "country-row")]',
            '//table//tbody//tr',
        ]

        rows = []
        for selector in selectors:
            rows = tree.xpath(selector)
            if rows:
                break

        for i, row in enumerate(rows[:50]):
            try:
                medal = self._parse_medal_row(row, i + 1)
                if medal:
                    medals.append(medal)
            except Exception as e:
                logger.debug(f"Error parsing medal row {i}: {e}")
                continue

        logger.info(f"Scraped {len(medals)} countries from medal table (fallback)")
        return medals

    def _parse_medal_row(self, row, default_rank: int) -> Optional[MedalCount]:
        """Parse a single medal table row."""
        # Try to extract text content from cells
        cells = row.xpath('.//td | .//div[contains(@class, "cell")]')

        if len(cells) < 4:
            return None

        # Extract text content
        texts = []
        for cell in cells:
            text = cell.text_content().strip()
            texts.append(text)

        # Try to identify country code and medal counts
        # Format varies but usually: rank, country, gold, silver, bronze, total
        country_code = ""
        country_name = ""
        gold = silver = bronze = total = 0
        rank = default_rank
        rank_found = False

        for i, text in enumerate(texts):
            # Look for 3-letter country code
            if len(text) == 3 and text.isupper():
                country_code = text
            # Look for numbers (first is rank, then medal counts)
            elif text.isdigit():
                num = int(text)
                if not rank_found:
                    # First numeric is the rank
                    rank = num
                    rank_found = True
                elif gold == 0:
                    gold = num
                elif silver == 0:
                    silver = num
                elif bronze == 0:
                    bronze = num
                elif total == 0:
                    total = num
            # Country name is usually the longest text
            elif len(text) > 3 and not text.isdigit():
                if len(text) > len(country_name):
                    country_name = text

        if not country_code:
            # Try to derive from country name
            country_code = country_name[:3].upper() if country_name else f"UNK{default_rank}"

        if total == 0:
            total = gold + silver + bronze

        if country_code and (gold or silver or bronze or total):
            return MedalCount(
                country_code=country_code,
                country_name=country_name or country_code,
                gold=gold,
                silver=silver,
                bronze=bronze,
                total=total,
                rank=rank
            )

        return None

    def _event_from_cache(self, data: Dict[str, Any]) -> OlympicEvent:
        """Deserialize an OlympicEvent from cached dict, parsing datetime strings."""
        # Parse start_time from ISO string
        start_time = data.get('start_time')
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        elif start_time is None:
            start_time = _utcnow()

        return OlympicEvent(
            event_id=data.get('event_id', ''),
            sport=data.get('sport', ''),
            event_name=data.get('event_name', ''),
            start_time=start_time,
            status=data.get('status', 'scheduled'),
            venue=data.get('venue', ''),
            round=data.get('round', '')
        )

    def fetch_schedule(self, days_ahead: int = 2) -> List[OlympicEvent]:
        """
        Fetch upcoming events.

        Uses static schedule file for event times (lightweight, pre-generated).
        Only fetches from web if static file not available.

        Args:
            days_ahead: Number of days to look ahead

        Returns:
            List of upcoming OlympicEvent objects
        """
        # Use static schedule if available (much faster, no network)
        if self._static_schedule_loaded and self._static_schedule:
            return self._get_events_from_static(days_ahead)

        # Fallback to cache/web scraping
        cache_key = 'schedule'

        cached = self.cache.get(cache_key)
        if cached is not None:
            events = [self._event_from_cache(e) for e in cached]
            now = _utcnow()
            return [e for e in events if e.start_time > now]

        with self._schedule_lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                events = [self._event_from_cache(e) for e in cached]
                now = _utcnow()
                return [e for e in events if e.start_time > now]

            events = self._scrape_schedule()
            if events:
                event_dicts = [
                    {
                        'event_id': e.event_id,
                        'sport': e.sport,
                        'event_name': e.event_name,
                        'start_time': e.start_time.isoformat(),
                        'status': e.status,
                        'venue': e.venue,
                        'round': e.round,
                    }
                    for e in events
                ]
                self.cache.set(cache_key, event_dicts, CACHE_DURATION['schedule'])

            return events

    def _get_events_from_static(self, days_ahead: int = 2) -> List[OlympicEvent]:
        """Get upcoming events from static schedule file."""
        now = _utcnow()
        cutoff = now + timedelta(days=days_ahead)
        events = []

        for event_data in self._static_schedule:
            try:
                # Parse start time
                start_str = event_data.get('start', '')
                if not start_str:
                    continue

                # Handle timezone in ISO format
                if '+' in start_str or 'Z' in start_str:
                    start_time = datetime.fromisoformat(
                        start_str.replace('Z', '+00:00')
                    )
                    # Convert to UTC (naive datetime)
                    if start_time.utcoffset():
                        start_time = start_time - start_time.utcoffset()
                    start_time = start_time.replace(tzinfo=None)
                else:
                    start_time = datetime.fromisoformat(start_str)

                # Filter to upcoming events within range
                if start_time < now or start_time > cutoff:
                    continue

                event = OlympicEvent(
                    event_id=event_data.get('id', ''),
                    sport=event_data.get('sport', 'Unknown'),
                    event_name=event_data.get('name', 'Event'),
                    start_time=start_time,
                    status='scheduled',  # Static file doesn't have live status
                    venue=event_data.get('venue', ''),
                    round=event_data.get('round', '')
                )
                events.append(event)

            except (ValueError, KeyError) as e:
                logger.debug(f"Error parsing static event: {e}")
                continue

        # Sort by start time
        events.sort(key=lambda e: e.start_time)
        return events

    def _scrape_schedule(self) -> List[OlympicEvent]:
        """
        Scrape event schedule from Olympics.com.

        Olympics.com embeds schedule data as JSON in a script tag with
        the key 'result_schedule_data'. Each day has its own key like
        'initialSchedule_2026-02-08'.
        """
        games = current_games()
        if games is None:
            logger.info("No upcoming Olympics in OLYMPIC_GAMES; nothing to fetch")
            return []
        url = f"{games['base_url']}/schedule"
        page_content = self._fetch_page(url)

        if not page_content:
            logger.warning("Failed to fetch schedule page")
            return []

        try:
            tree = html.fromstring(page_content)
            events = []

            # Find script tags containing schedule JSON
            scripts = tree.xpath('//script/text()')

            for script in scripts:
                if 'result_schedule_data' not in script:
                    continue
                if len(script) < 10000:
                    continue

                try:
                    data = json.loads(script)
                    if 'result_schedule_data' not in data:
                        continue

                    schedule_data = data['result_schedule_data']

                    # Get events for today and next few days
                    now = _utcnow()
                    for day_offset in range(3):  # Today + 2 days
                        day = now + timedelta(days=day_offset)
                        day_key = f"initialSchedule_{day.strftime('%Y-%m-%d')}"

                        day_schedule = schedule_data.get(day_key, {})
                        units = day_schedule.get('units', [])

                        for unit in units:
                            event = self._parse_schedule_unit(unit)
                            if event:
                                events.append(event)

                    # Sort by start time
                    events.sort(key=lambda e: e.start_time)

                    # Filter to upcoming only (not finished)
                    events = [e for e in events if e.status != 'completed']

                    logger.info(f"Parsed {len(events)} events from embedded JSON")
                    return events

                except json.JSONDecodeError:
                    continue

            # Fallback to selector-based parsing
            logger.warning("No embedded schedule JSON found, trying fallback")
            return self._scrape_schedule_fallback(tree)

        except Exception as e:
            logger.error(f"Error parsing schedule page: {e}")
            return []

    def _parse_schedule_unit(self, unit: Dict[str, Any]) -> Optional[OlympicEvent]:
        """Parse a single schedule unit from embedded JSON."""
        try:
            event_id = unit.get('id', '')
            sport = unit.get('disciplineName', '')
            event_name = unit.get('eventUnitName', '') or unit.get('eventName', '')

            # Parse start time (ISO 8601 with timezone)
            start_str = unit.get('startDate', '')
            if start_str:
                # Handle timezone in ISO format
                if '+' in start_str or 'Z' in start_str:
                    start_time = datetime.fromisoformat(
                        start_str.replace('Z', '+00:00')
                    )
                    # Convert to UTC: get offset first, then subtract, then remove tzinfo
                    offset = start_time.utcoffset()
                    if offset is not None:
                        start_time = start_time - timedelta(seconds=offset.total_seconds())
                    start_time = start_time.replace(tzinfo=None)
                else:
                    start_time = datetime.fromisoformat(start_str)
            else:
                start_time = _utcnow()

            # Map status
            status_raw = unit.get('status', '').upper()
            if status_raw == 'FINISHED':
                status = 'completed'
            elif status_raw == 'RUNNING' or unit.get('liveFlag', False):
                status = 'live'
            else:
                status = 'scheduled'

            venue = unit.get('venueDescription', '') or unit.get('venueLongDescription', '')
            round_name = unit.get('phaseName', '')

            # Ensure "Final" is in round name if this is a medal event
            # The is_final property checks if "final" is in round name
            if unit.get('medalFlag', 0) == 1 and 'final' not in round_name.lower():
                round_name = round_name + " Final" if round_name else "Final"

            if not sport and not event_name:
                return None

            return OlympicEvent(
                event_id=event_id,
                sport=sport or 'Unknown',
                event_name=event_name or sport or 'Event',
                start_time=start_time,
                status=status,
                venue=venue,
                round=round_name
            )

        except Exception as e:
            logger.debug(f"Error parsing schedule unit: {e}")
            return None

    def _scrape_schedule_fallback(self, tree) -> List[OlympicEvent]:
        """Fallback HTML-based schedule parsing."""
        events = []

        selectors = [
            '//*[contains(@class, "event-item")]',
            '//*[contains(@class, "schedule-item")]',
            '//div[contains(@class, "event")]',
        ]

        items = []
        for selector in selectors:
            items = tree.xpath(selector)
            if items:
                break

        for i, item in enumerate(items[:100]):  # Limit to 100 events
            try:
                event = self._parse_event_item(item, i)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug(f"Error parsing event item {i}: {e}")
                continue

        logger.info(f"Scraped {len(events)} events from schedule (fallback)")
        return events

    def _parse_event_item(self, item, index: int) -> Optional[OlympicEvent]:
        """Parse a single event item."""
        # Extract sport name (usually in a heading or class)
        sport = ""
        sport_elem = item.xpath('.//*[contains(@class, "sport")]')
        if sport_elem:
            sport = sport_elem[0].text_content().strip()

        # Extract event name
        event_name = ""
        name_elem = item.xpath('.//*[contains(@class, "name") or contains(@class, "title")]')
        if name_elem:
            event_name = name_elem[0].text_content().strip()

        # Extract time
        time_elem = item.xpath('.//*[contains(@class, "time")]')
        start_time = _utcnow()  # Default
        if time_elem:
            time_text = time_elem[0].text_content().strip()
            # Try to parse time (format varies)
            try:
                # Common formats: "10:30", "10:30 AM", "2026-02-10T10:30:00"
                if 'T' in time_text:
                    start_time = datetime.fromisoformat(time_text.replace('Z', '+00:00'))
                else:
                    # Assume today's date
                    today = _utcnow().date()
                    # Normalize AM/PM - strip and uppercase for checking
                    time_upper = time_text.upper()
                    time_clean = time_text.upper().replace('AM', '').replace('PM', '').strip()
                    time_parts = time_clean.split(':')
                    if len(time_parts) >= 2:
                        hour = int(time_parts[0].strip())
                        minute = int(time_parts[1].strip())
                        # Handle 12-hour to 24-hour conversion
                        if 'AM' in time_upper:
                            if hour == 12:
                                hour = 0  # 12:xx AM is 00:xx
                        elif 'PM' in time_upper:
                            if hour < 12:
                                hour += 12  # 1-11 PM becomes 13-23
                        start_time = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
            except (ValueError, IndexError):
                pass

        # Extract round info
        round_text = ""
        round_elem = item.xpath('.//*[contains(@class, "round") or contains(@class, "phase")]')
        if round_elem:
            round_text = round_elem[0].text_content().strip()

        if sport or event_name:
            return OlympicEvent(
                event_id=f"evt_{index}",
                sport=sport or "Unknown",
                event_name=event_name or sport or "Event",
                start_time=start_time,
                status="scheduled",
                venue="",
                round=round_text
            )

        return None

    def _result_from_cache(self, data: Dict[str, Any]) -> EventResult:
        """Deserialize an EventResult from cached dict, converting datetime strings."""
        completed_time = data.get('completed_time')
        if isinstance(completed_time, str):
            completed_time = datetime.fromisoformat(completed_time)
        elif completed_time is None:
            completed_time = _utcnow()

        return EventResult(
            event_id=data.get('event_id', ''),
            sport=data.get('sport', ''),
            event_name=data.get('event_name', ''),
            completed_time=completed_time,
            gold_athlete=data.get('gold_athlete', ''),
            gold_country=data.get('gold_country', ''),
            silver_athlete=data.get('silver_athlete', ''),
            silver_country=data.get('silver_country', ''),
            bronze_athlete=data.get('bronze_athlete', ''),
            bronze_country=data.get('bronze_country', ''),
            winning_result=data.get('winning_result', ''),
        )

    def fetch_results(self, count: int = 10) -> List[EventResult]:
        """
        Fetch recent event results.

        Args:
            count: Maximum number of results to return

        Returns:
            List of recent EventResult objects
        """
        cache_key = 'results'

        cached = self.cache.get(cache_key)
        if cached is not None:
            return [self._result_from_cache(r) for r in cached][:count]

        with self._results_lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return [self._result_from_cache(r) for r in cached][:count]

            results = self._scrape_results()
            if results:
                result_dicts = [
                    {
                        'event_id': r.event_id,
                        'sport': r.sport,
                        'event_name': r.event_name,
                        'completed_time': r.completed_time.isoformat(),
                        'gold_athlete': r.gold_athlete,
                        'gold_country': r.gold_country,
                        'silver_athlete': r.silver_athlete,
                        'silver_country': r.silver_country,
                        'bronze_athlete': r.bronze_athlete,
                        'bronze_country': r.bronze_country,
                        'winning_result': r.winning_result,
                    }
                    for r in results
                ]
                self.cache.set(cache_key, result_dicts, CACHE_DURATION['results'])

            return results[:count]

    def _scrape_results(self) -> List[EventResult]:
        """
        Extract recent results from the medals page.

        The medals page contains individual medal winners which we can
        group by event to create result entries.
        """
        games = current_games()
        if games is None:
            logger.info("No upcoming Olympics in OLYMPIC_GAMES; nothing to fetch")
            return []
        url = f"{games['base_url']}/medals"
        page_content = self._fetch_page(url)

        if not page_content:
            logger.warning("Failed to fetch medals page for results")
            return []

        try:
            tree = html.fromstring(page_content)
            results = []

            # Find embedded JSON with medal data
            scripts = tree.xpath('//script/text()')

            for script in scripts:
                if 'result_medals_data' not in script:
                    continue
                if len(script) < 1000:
                    continue

                try:
                    data = json.loads(script)
                    if 'result_medals_data' not in data:
                        continue

                    medals_data = data['result_medals_data']
                    initial = medals_data.get('initialMedals', {})
                    standings = initial.get('medalStandings', {})
                    table = standings.get('medalsTable', [])

                    # Collect all medal winners across all countries
                    all_winners = []
                    for country in table:
                        for disc in country.get('disciplines', []):
                            for winner in disc.get('medalWinners', []):
                                winner['disciplineName'] = disc.get('name', '')
                                all_winners.append(winner)

                    # Group by event
                    events = {}
                    for w in all_winners:
                        event_code = w.get('eventCode', '')
                        if not event_code:
                            continue

                        if event_code not in events:
                            events[event_code] = {
                                'event_id': event_code,
                                'sport': w.get('disciplineName', 'Unknown'),
                                'event_name': w.get('eventDescription', ''),
                                'date': w.get('date', ''),
                                'gold': None,
                                'silver': None,
                                'bronze': None,
                            }

                        medal_type = w.get('medalType', '')
                        athlete = w.get('competitorDisplayName', 'Unknown')
                        country = w.get('organisation', '')

                        if 'GOLD' in medal_type:
                            events[event_code]['gold'] = (athlete, country)
                        elif 'SILVER' in medal_type:
                            events[event_code]['silver'] = (athlete, country)
                        elif 'BRONZE' in medal_type:
                            events[event_code]['bronze'] = (athlete, country)

                    # Convert to EventResult objects
                    for event_data in events.values():
                        # Only include events with at least gold
                        if not event_data['gold']:
                            continue

                        # Parse date
                        date_str = event_data.get('date', '')
                        try:
                            completed_time = datetime.fromisoformat(date_str) if date_str else _utcnow()
                        except ValueError:
                            completed_time = _utcnow()

                        gold = event_data.get('gold') or ('Unknown', 'UNK')
                        silver = event_data.get('silver') or ('', '')
                        bronze = event_data.get('bronze') or ('', '')

                        result = EventResult(
                            event_id=event_data['event_id'],
                            sport=event_data['sport'],
                            event_name=event_data['event_name'],
                            completed_time=completed_time,
                            gold_athlete=gold[0],
                            gold_country=gold[1],
                            silver_athlete=silver[0],
                            silver_country=silver[1],
                            bronze_athlete=bronze[0],
                            bronze_country=bronze[1],
                        )
                        results.append(result)

                    # Sort by date (most recent first)
                    results.sort(key=lambda r: r.completed_time, reverse=True)

                    logger.info(f"Parsed {len(results)} event results from medal data")
                    return results

                except json.JSONDecodeError:
                    continue

            return []

        except Exception as e:
            logger.error(f"Error parsing results: {e}")
            return []

    def get_olympics_data(self) -> OlympicsData:
        """
        Get complete Olympics data package.

        Returns:
            OlympicsData with all available information
        """
        now = _utcnow()
        games = current_games(now)
        if games is None:
            # Past every Games we know about. Report an empty, inactive package
            # so the plugin renders nothing rather than a negative countdown.
            logger.warning(
                "No Olympics on or after %s in OLYMPIC_GAMES -- add the next "
                "Games to data/olympics_api.py", now.date())
            return OlympicsData(
                is_active=False, games_name="", games_type="",
                opening_date=None, closing_date=None, medal_counts=[],
                upcoming_events=[], live_events=[], recent_results=[],
                last_updated=now,
            )
        opening = games['opening']
        closing = games['closing']

        is_active = opening <= now <= closing

        # Fetch all data
        medals = self.fetch_medal_counts()
        schedule = self.fetch_schedule() if is_active else []
        results = self.fetch_results() if is_active else []

        # Separate live events
        live_events = [e for e in schedule if e.status == 'live']
        upcoming = [e for e in schedule if e.status == 'scheduled']

        return OlympicsData(
            is_active=is_active,
            games_name=games['name'],
            games_type=games['type'],
            opening_date=opening,
            closing_date=closing,
            medal_counts=medals,
            upcoming_events=upcoming,
            live_events=live_events,
            recent_results=results,
            last_updated=_utcnow()
        )

    def get_last_error(self) -> Optional[str]:
        """Get the last fetch error, if any."""
        return self._last_fetch_error

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.cache.clear()

    def get_next_event(self) -> Optional[OlympicEvent]:
        """
        Get the next upcoming event.

        Returns:
            The next scheduled event, or None if no events upcoming.
        """
        events = self.fetch_schedule(days_ahead=1)
        if not events:
            return None

        now = _utcnow()
        upcoming = [e for e in events if e.start_time > now]

        if not upcoming:
            return None

        # Return the soonest event
        return min(upcoming, key=lambda e: e.start_time)

    def get_time_to_next_event(self) -> Optional[timedelta]:
        """
        Get time remaining until the next event.

        Returns:
            Timedelta to next event, or None if no events upcoming.
        """
        next_event = self.get_next_event()
        if not next_event:
            return None

        now = _utcnow()
        return next_event.start_time - now

    def fetch_live_status(self) -> List[OlympicEvent]:
        """
        Fetch current live events with lightweight status check.

        This is a lighter-weight call than full schedule fetch,
        optimized for frequent polling during live events.
        """
        # Use the schedule scraping which includes live status
        # but filter to only live events
        cache_key = 'live_events'

        cached = self.cache.get(cache_key)
        if cached is not None:
            return [self._event_from_cache(e) for e in cached]

        with self._live_lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return [self._event_from_cache(e) for e in cached]

            # Fetch from schedule page
            events = self._scrape_schedule()
            live_events = [e for e in events if e.status == 'live']

            if live_events:
                event_dicts = [
                    {
                        'event_id': e.event_id,
                        'sport': e.sport,
                        'event_name': e.event_name,
                        'start_time': e.start_time.isoformat(),
                        'status': e.status,
                        'venue': e.venue,
                        'round': e.round,
                    }
                    for e in live_events
                ]
                # Short cache for live events (2 minutes)
                self.cache.set(cache_key, event_dicts, 120)

            return live_events

    def get_medal_event_alerts(self) -> List[OlympicEvent]:
        """
        Get live medal events (finals) for priority display.

        Returns:
            List of live events that are finals (medal-deciding).
        """
        live = self.fetch_live_status()
        return [e for e in live if e.is_final]
