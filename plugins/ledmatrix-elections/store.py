"""
RaceStore: aggregation layer over providers.

Calls each enabled provider, merges their normalized ``Race`` lists into one
unified set, applies the state/race-type filters, sorts by importance, and
diffs against the previous snapshot to detect newly-called races (for interrupt
mode). All logic here is pure and I/O-free so it can be unit-tested directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from election_data_model import Race, Scope, chamber_of_office, office_rank, race_type_token

logger = logging.getLogger(__name__)


class RaceStore:
    def __init__(self, override_votes: bool = True, cache_manager: Any = None):
        # When True, a state-scoped provider's authoritative vote totals replace
        # the baseline's for matching races (NYT keeps calls/importance).
        self.override_votes = override_votes
        # Optional cache_manager persists the called snapshot across restarts so
        # a restart mid-count neither replays old calls nor misses a fresh one.
        self.cache_manager = cache_manager
        self._snapshot_key: Optional[str] = None
        # Snapshot of called state for the newly-called diff. None until seeded.
        self._called_snapshot: Optional[Dict[str, bool]] = None
        self._called_at: Dict[str, float] = {}

    # -- Election scoping / persistence -------------------------------------

    def set_election(self, key: Optional[str]) -> None:
        """Bind the store to an election; load its persisted snapshot or reset.

        ``key`` identifies the active election (state+date+type). Switching keys
        starts a fresh diff so a new election doesn't inherit the prior one's
        called state.
        """
        if key == self._snapshot_key:
            return
        self._snapshot_key = key
        self._called_snapshot = None
        self._called_at = {}
        if self.cache_manager and key:
            try:
                cached = self.cache_manager.get(f"elections_snapshot_{key}")
            except Exception:
                cached = None
            if cached:
                self._called_snapshot = dict(cached.get("snapshot") or {})
                self._called_at = {k: float(v) for k, v in (cached.get("called_at") or {}).items()}

    def _persist(self) -> None:
        if self.cache_manager and self._snapshot_key and self._called_snapshot is not None:
            try:
                self.cache_manager.set(
                    f"elections_snapshot_{self._snapshot_key}",
                    {"snapshot": self._called_snapshot, "called_at": self._called_at},
                )
            except Exception as e:
                logger.debug("snapshot persist failed: %s", e)

    # -- Merge --------------------------------------------------------------

    def merge(self, provider_results: Sequence[Tuple[Any, List[Race]]]) -> List[Race]:
        """Merge per-provider race lists into one keyed by ``Race.id``.

        Baseline providers (``provides_states() is None``) are folded first and
        drive race identity, calls, and importance. State-scoped providers fold
        in after and supplement/override matching races for their states.
        """
        ordered = sorted(
            provider_results,
            key=lambda pr: 0 if pr[0].provides_states() is None else 1,
        )

        merged: Dict[str, Race] = {}
        for provider, races in ordered:
            is_baseline = provider.provides_states() is None
            for race in races:
                existing = merged.get(race.id)
                if existing is None:
                    merged[race.id] = race
                elif is_baseline:
                    # Two baselines for the same id (unlikely) — keep the first.
                    continue
                else:
                    merged[race.id] = self._combine(existing, race)
        return list(merged.values())

    def _combine(self, base: Race, supp: Race) -> Race:
        """Combine a baseline race with a supplementing (state-scoped) one.

        The baseline keeps calls + importance markers; the supplement optionally
        provides authoritative/granular vote totals.
        """
        if not self.override_votes:
            return base

        # Return a new Race so provider input lists are never mutated; preserve
        # the baseline's calls/importance markers (carried as dynamic attrs).
        # Keep the baseline's pct_reporting: NYT's eevp estimates the share of the
        # *expected vote* that's counted, which is the honest "% in". A local
        # source like CA-SoS reports "% of precincts reporting" instead — that
        # hits 100% on election night while weeks of mail/provisional ballots are
        # still being counted, so letting it override would falsely read 100%.
        combined = replace(
            base,
            candidates=supp.candidates,
            title=supp.title or base.title,
            source=f"{base.source}+{supp.source}",
            last_updated=supp.last_updated,
        )
        if getattr(base, "_key_race", False):
            combined._key_race = True  # type: ignore[attr-defined]
        if getattr(base, "nyt_id", None):
            combined.nyt_id = base.nyt_id  # type: ignore[attr-defined]
        return combined

    # -- Filter -------------------------------------------------------------

    @staticmethod
    def filter_races(races: List[Race], my_state: Optional[str],
                     only_my_state: bool,
                     race_types: Optional[Sequence[str]] = None,
                     local_districts: Optional[Dict[str, str]] = None) -> List[Race]:
        """Apply the geographic + race-type filters.

        ``local_districts`` maps a legislature chamber ("upper"/"lower") to the
        user's district number. Those races are shown only for the configured
        district — the baseline carries every district, but the user only wants
        their own — and aren't subject to ``race_types``. With no district
        configured for a chamber, none of that chamber's races show.
        """
        state = my_state.upper() if my_state else None
        types = set(race_types) if race_types else None
        districts = local_districts or {}

        out: List[Race] = []
        for race in races:
            if only_my_state and state:
                if race.scope != Scope.NATIONAL and (race.state or "").upper() != state:
                    continue
            chamber = chamber_of_office(race.office)
            if chamber is not None:
                want = districts.get(chamber)
                if not want or str(race.district) != str(want):
                    continue
                out.append(race)
                continue
            if types is not None and race_type_token(race.office) not in types:
                continue
            out.append(race)
        return out

    # -- Importance sort ----------------------------------------------------

    @staticmethod
    def sort_by_importance(races: List[Race]) -> List[Race]:
        """Called races first, then key races, then by office rank, then closeness."""
        return sorted(
            races,
            key=lambda r: (
                not r.called,            # called first
                not r.is_key_race(),     # then curated key races
                office_rank(r.office),   # then by office importance
                -r.pct_reporting,        # more-reported first within a tier
                r.id,                    # stable tiebreak
            ),
        )

    # -- Newly-called diff (interrupt mode) ---------------------------------

    def diff_newly_called(self, races: List[Race], now: Optional[float] = None,
                          cold_start_ts: Optional[float] = None) -> List[Race]:
        """Return races whose ``called`` flipped False->True since last snapshot.

        On the very first call (cold start) the snapshot is seeded and an empty
        list is returned, so an already-finished election doesn't replay every
        prior call as "breaking". Records ``called_at`` (our first observation)
        on each newly-called race for interrupt dedup/age handling.

        ``cold_start_ts`` stamps races already called when we first booted. Pass
        the election day so the visibility filter ages them correctly: booting on
        election night still shows that day's calls, while booting days later
        hides them. Falls back to ``now`` when not supplied.
        """
        now = now if now is not None else time.time()
        current = {r.id: r for r in races}

        if self._called_snapshot is None:
            seed_ts = cold_start_ts if cold_start_ts is not None else now
            self._called_snapshot = {rid: r.called for rid, r in current.items()}
            for rid, r in current.items():
                if r.called:
                    self._called_at[rid] = seed_ts
                    r.called_at = seed_ts
            self._persist()
            return []

        newly: List[Race] = []
        for rid, race in current.items():
            was_called = self._called_snapshot.get(rid, False)
            if race.called and not was_called:
                self._called_at[rid] = now
                race.called_at = now
                newly.append(race)
            elif race.called and rid in self._called_at:
                race.called_at = self._called_at[rid]

        # Refresh snapshot with current called states (covers new + existing ids).
        for rid, race in current.items():
            self._called_snapshot[rid] = race.called

        self._persist()
        return newly

    # -- Visibility (ticker drain) -----------------------------------------

    @staticmethod
    def filter_visible(races: List[Race], now: Optional[float] = None,
                       hide_called_after: float = 86400.0) -> List[Race]:
        """Drop races that were called more than ``hide_called_after`` seconds ago.

        Uncalled races and freshly-called ones stay (that's the news); stale
        calls fall off even while siblings are still uncalled, so the ticker
        drains on its own and goes empty once everything has settled. A
        non-positive ``hide_called_after`` disables hiding.
        """
        now = now if now is not None else time.time()
        if hide_called_after is None or hide_called_after <= 0:
            return list(races)
        out: List[Race] = []
        for r in races:
            if not r.called:
                out.append(r)
                continue
            called_at = getattr(r, "called_at", None)
            if called_at is None or (now - called_at) <= hide_called_after:
                out.append(r)
        return out

    @staticmethod
    def all_called(races: List[Race]) -> bool:
        """True when there are races and every one is called (election settled)."""
        return bool(races) and all(r.called for r in races)
