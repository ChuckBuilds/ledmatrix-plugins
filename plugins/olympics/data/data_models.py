"""
Data models for Olympics plugin.

These dataclasses represent the core data structures used throughout
the Olympics plugin for medals, events, and results.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional


def _utcnow() -> datetime:
    """Get current UTC time as naive datetime (for internal comparisons)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class MedalCount:
    """Medal count for a single country."""
    country_code: str  # ISO 3166-1 alpha-3 (e.g., "USA", "NOR", "GER")
    country_name: str
    gold: int
    silver: int
    bronze: int
    total: int
    rank: int

    def __post_init__(self):
        """Validate and compute total if not provided."""
        if self.total == 0 and (self.gold or self.silver or self.bronze):
            self.total = self.gold + self.silver + self.bronze


@dataclass
class OlympicEvent:
    """An Olympics event (scheduled, live, or completed)."""
    event_id: str
    sport: str
    event_name: str
    start_time: datetime  # UTC
    status: str  # "scheduled", "live", "completed"
    venue: str = ""
    round: str = ""  # "Final", "Semi-final", "Qualification", etc.
    end_time: Optional[datetime] = None

    @property
    def is_final(self) -> bool:
        """Check if this is a medal event (final).

        Uses word boundary matching to avoid false positives like 'Semi-final'.
        """
        if not self.round:
            return False
        # Normalize: split on non-alphanumeric and check for standalone 'final'
        tokens = re.split(r'[^a-zA-Z0-9]+', self.round.lower())
        return 'final' in tokens

    @property
    def is_live(self) -> bool:
        """Check if event is currently happening."""
        return self.status == "live"


@dataclass
class EventResult:
    """Result of a completed Olympics event."""
    event_id: str
    sport: str
    event_name: str
    completed_time: datetime
    gold_athlete: str
    gold_country: str  # ISO 3166-1 alpha-3
    silver_athlete: str = ""
    silver_country: str = ""
    bronze_athlete: str = ""
    bronze_country: str = ""
    winning_result: Optional[str] = None  # Time, score, distance, etc.


@dataclass
class OlympicsData:
    """Container for all Olympics data."""
    is_active: bool
    games_name: str  # e.g., "Milano Cortina 2026"
    games_type: str  # "winter" or "summer"
    opening_date: datetime
    closing_date: datetime
    medal_counts: List[MedalCount] = field(default_factory=list)
    upcoming_events: List[OlympicEvent] = field(default_factory=list)
    live_events: List[OlympicEvent] = field(default_factory=list)
    recent_results: List[EventResult] = field(default_factory=list)
    last_updated: Optional[datetime] = None

    @property
    def has_live_finals(self) -> bool:
        """Check if there are any live medal events."""
        return any(e.is_final for e in self.live_events)

    def get_top_countries(self, count: int = 5) -> List[MedalCount]:
        """Get top N countries by medal count."""
        sorted_medals = sorted(
            self.medal_counts,
            key=lambda m: (m.gold, m.silver, m.bronze, m.total),
            reverse=True
        )
        return sorted_medals[:count]

    def get_country_medals(self, country_code: str) -> Optional[MedalCount]:
        """Get medal count for a specific country."""
        for medal in self.medal_counts:
            if medal.country_code.upper() == country_code.upper():
                return medal
        return None

    @property
    def next_event(self) -> Optional['OlympicEvent']:
        """Get the next upcoming event."""
        if not self.upcoming_events:
            return None
        now = _utcnow()
        upcoming = [e for e in self.upcoming_events if e.start_time > now]
        if not upcoming:
            return None
        return min(upcoming, key=lambda e: e.start_time)

    @property
    def time_to_next_event(self) -> Optional[timedelta]:
        """Get time remaining until next event."""
        event = self.next_event
        if not event:
            return None
        return event.start_time - _utcnow()

    @staticmethod
    def format_countdown(td: Optional[timedelta]) -> str:
        """Format a timedelta as a human-readable countdown string."""
        if td is None:
            return ""

        total_seconds = int(td.total_seconds())
        if total_seconds < 0:
            return "NOW"

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m"
        else:
            return "<1m"

    def get_latest_results(self, count: int = 5) -> List['EventResult']:
        """Get the most recent event results."""
        sorted_results = sorted(
            self.recent_results,
            key=lambda r: r.completed_time,
            reverse=True
        )
        return sorted_results[:count]
