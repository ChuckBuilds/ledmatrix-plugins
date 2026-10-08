"""Shared base for the leagues fed by HockeyTech instead of ESPN (OHL, PWHL).

The ESPN leagues' managers fetch through core's ESPN helpers and background
service, all of which build ESPN URLs from ``self.sport``/``self.league``.
These leagues have no ESPN endpoint at all, so every fetch path is overridden
here to go through HockeyTechDataSource, which hands back ESPN-shaped events;
from extraction onwards the managers are the same as any other league's.

Features that need an ESPN endpoint the feed cannot stand in for are off:
odds, the poll badge, shots on goal (the scorebar has no shot totals), and
the goal-scorer card and game-activity pop-ups (``espn_summary_sport_league``
stays None, which already gates both).
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pytz

from data_sources import HockeyTechDataSource
from hockey import Hockey, HockeyLive

#: Seconds a fetched schedule window is reused. Recent and Upcoming refresh
#: hourly by default; this only lets the two of them share one request.
_SCHEDULE_CACHE_SECONDS = 300


class BaseHockeyTechManager(Hockey):
    """Hockey manager whose games come from a HockeyTech scorebar."""

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=logger,
            sport_key=sport_key,
        )
        self.league = sport_key
        self.data_source = HockeyTechDataSource(
            logger, sport_key, key_override=self.mode_config.get("hockeytech_key")
        )
        # No ESPN event ids to price, and no shot totals on the scorebar.
        self.show_odds = False
        self.show_shots_on_goal = False

        display_modes = self.mode_config.get("display_modes", {})
        self.recent_enabled = display_modes.get("hockey_recent", False)
        self.upcoming_enabled = display_modes.get("hockey_upcoming", False)
        self.live_enabled = display_modes.get("hockey_live", False)

    def _schedule_cache_key_hockeytech(self) -> str:
        _, window = self._schedule_window()
        return f"{self.sport_key}_hockeytech_schedule_{window}"

    def _fetch_hockeytech_schedule(self) -> Optional[Dict]:
        """The Recent/Upcoming window, cached for a few minutes so both
        managers share one request; a failed fetch falls back to the last
        copy whatever its age, so a feed outage does not blank the board."""
        cache_key = self._schedule_cache_key_hockeytech()
        cached = self.cache_manager.get(cache_key, max_age=_SCHEDULE_CACHE_SECONDS)
        if isinstance(cached, dict) and "events" in cached:
            return cached

        now = datetime.now(pytz.utc)
        start = now - timedelta(days=self.schedule_lookback_days)
        end = now + timedelta(days=self.schedule_lookahead_days)
        try:
            events = self.data_source.events_for(
                self.schedule_lookback_days + 1, self.schedule_lookahead_days + 1
            )
        except Exception as e:
            self.logger.error(f"HockeyTech schedule fetch failed for {self.league}: {e}")
            stale = self.cache_manager.get(cache_key, max_age=None)
            return stale if isinstance(stale, dict) and "events" in stale else None

        kept = []
        for event in events:
            try:
                when = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            except ValueError:
                continue
            # Out of season the scorebar answers with the league's latest and
            # next games whatever window was asked for; keep only this one.
            if when.tzinfo is not None and not start <= when <= end:
                continue
            kept.append(event)
        data = {"events": kept}
        self.cache_manager.set(cache_key, data, ttl=_SCHEDULE_CACHE_SECONDS)
        self.logger.info(
            f"Fetched {self.league} schedule from HockeyTech: {len(kept)} events"
        )
        return data

    def _fetch_todays_games(self) -> Optional[Dict]:
        """Today's games (and last night's, for a game running past midnight),
        always fresh: the live poll's interval decides how often this runs."""
        try:
            return {"events": self.data_source.events_for(1, 1)}
        except Exception as e:
            self.logger.error(f"HockeyTech live fetch failed for {self.league}: {e}")
            return None

    def _fetch_data(self) -> Optional[Dict]:
        if isinstance(self, HockeyLive):
            return self._fetch_todays_games()
        return self._fetch_hockeytech_schedule()
