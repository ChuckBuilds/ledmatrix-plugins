"""
Election calendar + active-election resolver.

The plugin is dormant unless today falls inside the *active window* of an
election we can both date and build a feed URL for right now. That keeps the
"there's an election somewhere every week" firehose out: nationally elections
happen constantly, but a given state has ~two per year (primary + general), and
those are the only ones we can name a date and feed slug for in advance.

What we can predict:
- General: the date is a formula (first Tuesday after the first Monday of
  November) and the NYT slug is the standard ``results-{state}.json``.
- Primary: the date varies by state, so it comes from a small per-cycle table
  (extend it via the ``calendar_events`` config, no code change needed). Slug is
  the standard ``results-{state}-primary.json``.
- Special / runoff: only included when an explicit entry carries its date *and*
  (because NYT's slug for these is nonstandard) its ``feed_filename``. Anything
  we can't deterministically turn into a URL is skipped.

An event's active window is ``[election_day, election_day + trail_days]`` so it
covers results that trickle in over several days; the manager's per-race
24h-since-called rule drains the ticker within that window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

_DEFAULT_TRAIL_DAYS = 14

# Per-cycle primary dates by state, keyed by year. Intentionally seeded only
# with what's verified in this repo (CA 2026 primary, which the fixtures and
# default config use). Add more via the plugin's ``calendar_events`` config
# rather than guessing dates here.
_PRIMARIES: Dict[str, Dict[int, List[str]]] = {
    "CA": {2026: ["2026-06-02"]},
}


@dataclass
class ElectionEvent:
    """One scheduled election we can point a provider at."""

    state: str                         # 2-letter, upper-cased
    date: str                          # YYYY-MM-DD (election day)
    type: str                          # "primary" | "general" | "special"
    trail_days: int = _DEFAULT_TRAIL_DAYS
    feed_filename: Optional[str] = None   # nonstandard NYT slug (specials/runoffs)
    feed_url: Optional[str] = None        # full URL override; bypasses URL building

    def election_day(self) -> date:
        return datetime.strptime(self.date, "%Y-%m-%d").date()

    def election_day_ts(self) -> float:
        """Local-midnight unix timestamp of election day (cold-start call seed)."""
        d = self.election_day()
        return time.mktime(datetime(d.year, d.month, d.day).timetuple())

    def window_contains(self, today: date) -> bool:
        d = self.election_day()
        return d <= today <= d + timedelta(days=self.trail_days)

    def is_includable(self) -> bool:
        """We must be able to build a feed URL for this event right now.

        Standard primaries/generals use the provider's built-in slug; anything
        else needs an explicit ``feed_filename`` or ``feed_url``.
        """
        if self.feed_url or self.feed_filename:
            return True
        return self.type in ("primary", "general")


def general_election_date(year: int) -> date:
    """First Tuesday after the first Monday in November (US general election day)."""
    d = date(year, 11, 1)
    while d.weekday() != 0:          # 0 == Monday
        d += timedelta(days=1)
    return d + timedelta(days=1)     # the Tuesday after the first Monday


def _builtin_events(state: str, year: int) -> List[ElectionEvent]:
    """The general + table primaries for a state/year, filtered to includable."""
    state = (state or "").upper()
    events = [ElectionEvent(state=state, date=general_election_date(year).isoformat(),
                            type="general")]
    for d in _PRIMARIES.get(state, {}).get(year, []):
        events.append(ElectionEvent(state=state, date=d, type="primary"))
    return [e for e in events if e.is_includable()]


def resolve_active(state: str, today: date,
                   extra_events: Optional[List[ElectionEvent]] = None) -> Optional[ElectionEvent]:
    """Return the active election for ``state`` on ``today``, or None if dormant.

    Considers built-in events for this year and last (so a window straddling the
    new year still resolves) plus any user-supplied ``extra_events``. If several
    windows overlap, the most recent election day wins.
    """
    candidates: List[ElectionEvent] = []
    for yr in (today.year, today.year - 1):
        candidates += _builtin_events(state, yr)
    candidates += [e for e in (extra_events or []) if e.is_includable()]

    active = [e for e in candidates if e.window_contains(today)]
    if not active:
        return None
    active.sort(key=lambda e: e.election_day(), reverse=True)
    return active[0]
