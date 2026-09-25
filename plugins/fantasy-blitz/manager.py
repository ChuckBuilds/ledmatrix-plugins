"""Fantasy Blitz -- an arcade-style NFL fantasy football show for LEDMatrix.

League-free by default: the week's top fantasy scorers as collectible cards,
a leaderboard, big-play alerts as they happen, the biggest busts, the free
agents everyone is adding, injury news, the top scorer at each position,
Tuesday's awards and the season race. Optionally it follows a watchlist of
players and one real Sleeper or ESPN league.

Data is Sleeper's public feed (fantasy points already calculated in PPR,
Half-PPR and Standard) with ESPN for game states, scoring-play text,
headshots and a fallback feed. No API key.

Division of labour, per the project's rules: ``update()`` does every network
call and builds the content each screen shows; ``display()`` only draws, from
memory, and returns False for a screen with nothing to show (wrong part of
the week, screen off, no data) so the core rotates straight past it.
"""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.plugin_system.base_plugin import BasePlugin

try:
    from src.plugin_system.base_plugin import VegasDisplayMode
except ImportError:  # cores before the Vegas hooks never ask for them
    VegasDisplayMode = None

try:
    import pytz
except ImportError:  # the core ships pytz; without it the week uses system time
    pytz = None

import fantasy_blitz_draw as draw
import fantasy_blitz_league as league_mod
import fantasy_blitz_model as model
import fantasy_blitz_render as render
from fantasy_blitz_data import FantasyData
from fantasy_blitz_headshots import HeadshotStore

#: display mode -> screen key (the config and SCREEN_PHASES name).
MODE_SCREENS = {
    "fantasy_player_card": "player_card",
    "fantasy_leaderboard": "leaderboard",
    "fantasy_live": "big_play",
    "fantasy_dud_alert": "dud_alert",
    "fantasy_hot_pickups": "hot_pickups",
    "fantasy_position_kings": "position_kings",
    "fantasy_injury_report": "injury_report",
    "fantasy_watchlist": "watchlist",
    "fantasy_weekly_awards": "weekly_awards",
    "fantasy_league_matchup": "league_matchup",
    "fantasy_season_race": "season_race",
}
LIVE_MODE = "fantasy_live"
#: Screens drawn as titled lists, paged to fit the panel.
LIST_SCREENS = ("leaderboard", "hot_pickups", "injury_report", "watchlist", "season_race")

#: Screen titles for the band drawn when a panel has spare rows.
SCREEN_TITLES = {
    "player_card": ("TOP SCORERS", draw.GOLD),
    "leaderboard": ("LEADERBOARD", draw.EPIC),
    "big_play": ("BIG PLAY", draw.GREEN),
    "dud_alert": ("DUD ALERT", draw.RED),
    "hot_pickups": ("WAIVER WIRE", draw.ORANGE),
    "position_kings": ("POSITION KINGS", draw.GOLD),
    "injury_report": ("INJURY REPORT", draw.YELLOW),
    "watchlist": ("MY PLAYERS", draw.RARE),
    "weekly_awards": ("WEEKLY AWARDS", draw.GOLD),
    "league_matchup": ("MY LEAGUE", draw.RARE),
    "season_race": ("SEASON RACE", draw.EPIC),
}
#: Seconds each item stays up before a screen moves to the next one.
ITEM_SECONDS_DEFAULT = 6
PAGE_SECONDS = 8
ALERT_SECONDS = 8
#: Screens whose frames keep moving after the intro (foil, sunburst, flame).
_INTRO_SECONDS = {
    "player_card": 2.6, "weekly_awards": 2.6, "leaderboard": 1.6, "dud_alert": 2.2,
    "hot_pickups": 1.6, "position_kings": 1.2, "injury_report": 1.6, "watchlist": 1.6,
    "league_matchup": 1.2, "season_race": 1.6, "big_play": 0.0,
}

SCREEN_DEFAULTS = {key: {"enabled": True, "duration": 0} for key in model.SCREEN_PHASES}
SCREEN_DEFAULTS["big_play"] = {"enabled": True, "duration": ALERT_SECONDS}


class FantasyBlitzPlugin(BasePlugin):
    """Arcade-style NFL fantasy football highlights."""

    NO_DATA_RETRY_SECONDS = 300

    def __init__(self, plugin_id: str, config: Dict[str, Any], display_manager,
                 cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self._load_config(config)

        self.data = FantasyData(cache_manager, self.logger, plugin_id, self.request_timeout)
        self.headshots = HeadshotStore(self.data, self.logger)

        # The core reads plugin.modes once, at registration, so every mode is
        # registered here and display() gates by the part of the NFL week.
        self.modes = list(MODE_SCREENS)
        self.current_mode_index = 0

        self.phase = model.PHASE_IDLE
        self.season: Optional[str] = None
        self.week: Optional[int] = None
        self.results_week: Optional[int] = None
        self.use_current_week = False
        self.players: Dict[str, Dict[str, Any]] = {}
        self.upcoming: Dict[str, Dict[str, Any]] = {}
        self.games: List[Dict[str, Any]] = []
        self.results_games: List[Dict[str, Any]] = []
        self.season_players: Dict[str, Dict[str, Any]] = {}
        self.trending_adds: List[Dict[str, Any]] = []
        self.trending_drops: List[Dict[str, Any]] = []
        self.league: Optional[Dict[str, Any]] = None
        self.watch_ids: Dict[str, str] = {}
        self.content: Dict[str, List[Dict[str, Any]]] = {}
        self.last_update = 0.0
        self.data_version = 0
        self.league_problem: Optional[str] = None

        self.alerts = model.AlertQueue(min_gap=60.0, max_age=900.0)
        self._snapshot: Optional[Dict[str, float]] = None
        self._snapshot_week: Optional[Tuple[Any, Any]] = None
        self._stats_stamp: Optional[float] = None
        self._delayed = model.DelayedView(keep_seconds=max(180.0, self.spoiler_delay + 120))
        self._final_seen: Dict[str, float] = {}
        self._restore_bigplay()

        self._current_mode: Optional[str] = None
        self._current_screen: Optional[str] = None
        self._mode_started = 0.0
        self._last_frame_at = 0.0
        self._frame_cache: Dict[Tuple[Any, ...], Any] = {}
        self._shown_key: Optional[Tuple[Any, ...]] = None
        self._last_warning = 0.0

        self.logger.info(
            "Fantasy Blitz initialised: %sx%s panel, %s scoring, %s modes",
            self.display_manager.width, self.display_manager.height,
            model.SCORING_LABELS.get(self.scoring, "PPR"), len(self.modes))

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------

    def _load_config(self, config: Dict[str, Any]) -> None:
        self.scoring = config.get("scoring_format", "ppr")
        if self.scoring not in model.SCORING_KEYS:
            self.scoring = model.DEFAULT_SCORING
        pos_cfg = config.get("positions") or {}
        self.positions = tuple(p for p in model.POSITIONS if pos_cfg.get(p.lower(), True)) or model.POSITIONS
        self.top_n = _safe_int(config.get("top_n", 5), 5, 1, 10)
        self.show_headshots = bool(config.get("show_headshots", True))
        self.live_priority = bool(config.get("live_priority", True))
        self.spoiler_delay = float(_safe_int(config.get("spoiler_delay_seconds", 0), 0, 0, 300))
        self.watchlist = [str(n) for n in (config.get("watchlist") or []) if str(n).strip()][:20]
        self.display_duration = _safe_int(config.get("display_duration", 20), 20, 5, 300)

        screens = config.get("screens") or {}
        self.screens: Dict[str, Dict[str, Any]] = {}
        for key, default in SCREEN_DEFAULTS.items():
            entry = screens.get(key) or {}
            self.screens[key] = {
                "enabled": bool(entry.get("enabled", default["enabled"])),
                "duration": _safe_int(entry.get("duration", default["duration"]), default["duration"], 0, 300),
            }
        self.show_drops = bool((screens.get("hot_pickups") or {}).get("show_drops", True))

        lg = config.get("league") or {}
        self.league_provider = str(lg.get("provider", "none") or "none")
        self.league_id = str(lg.get("league_id", "") or "")
        self.league_team = str(lg.get("team_name", "") or "")
        self.espn_s2 = str(lg.get("espn_s2", "") or "")
        self.espn_swid = str(lg.get("swid", "") or "")

        adv = config.get("advanced") or {}
        self.big_play_min = _safe_float(adv.get("big_play_min_points", 6.0), 6.0, 1.0, 50.0)
        self.watch_play_min = _safe_float(adv.get("watchlist_min_points", 3.0), 3.0, 0.5, 50.0)
        self.bust_min_projection = _safe_float(adv.get("bust_min_projection", 12.0), 12.0, 0.0, 60.0)
        tiers = adv.get("tier_thresholds") or {}
        self.tiers = {
            "legendary": _safe_float(tiers.get("legendary", 30.0), 30.0, 1.0, 100.0),
            "epic": _safe_float(tiers.get("epic", 20.0), 20.0, 1.0, 100.0),
            "rare": _safe_float(tiers.get("rare", 12.0), 12.0, 1.0, 100.0),
        }
        self.live_poll = _safe_int(adv.get("live_poll_seconds", 60), 60, 30, 600)
        self.idle_poll = _safe_int(adv.get("idle_poll_seconds", 900), 900, 300, 21600)
        self.item_seconds = _safe_int(adv.get("card_seconds", ITEM_SECONDS_DEFAULT), ITEM_SECONDS_DEFAULT, 3, 30)
        self.animations = bool(adv.get("animations", True))
        self.animation_fps = _safe_int(adv.get("animation_fps", 30), 30, 5, 60)
        self.request_timeout = _safe_int(adv.get("request_timeout", 15), 15, 5, 60)
        self.headshot_downloads = bool(adv.get("headshot_downloads", True))
        self.vegas_mode = config.get("vegas_mode")

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        self.config = new_config
        self._load_config(new_config)
        self.data.timeout = float(self.request_timeout)
        self._frame_cache.clear()
        self._shown_key = None
        self.last_update = 0.0
        self.update()

    # ------------------------------------------------------------------
    # update: the only place with network calls
    # ------------------------------------------------------------------

    def get_update_interval(self) -> Optional[float]:
        """Poll fast while games are on, slowly otherwise. Attribute reads only."""
        if not self.players and not self.upcoming:
            return float(min(self.idle_poll, self.NO_DATA_RETRY_SECONDS))
        if self.phase == model.PHASE_LIVE:
            return float(self.live_poll)
        if self.phase == model.PHASE_INTERMISSION:
            return float(max(self.live_poll, 120))
        return float(self.idle_poll)

    def update(self) -> None:
        try:
            self._refresh(time.time())
        except Exception as exc:  # noqa: BLE001 - a bad payload must not take
            # the display loop down, and the harness fails a plugin whose
            # update() raises anything but a connectivity error.
            self.logger.error("Fantasy Blitz update failed: %s", exc, exc_info=True)

    def _refresh(self, now: float) -> None:
        state = self.data.state(max_age=900 if self.phase == model.PHASE_LIVE else 1800)
        if not state:
            self._warn_occasionally("No NFL state yet (Sleeper unreachable?); nothing to show")
            return
        season = str(state.get("season") or "")
        week = _safe_int(state.get("week", 0), 0, 0, 25)
        season_type = str(state.get("season_type") or "")
        if not season or week < 1:
            self.phase = model.PHASE_IDLE
            return

        live_age = self.live_poll - 5
        quick = self.phase in (model.PHASE_LIVE, model.PHASE_INTERMISSION)
        games = self.data.games(season, week, live_age if quick else 600) or []
        phase, use_current = model.game_phase(season_type, games, self._local_now().weekday())
        if phase != self.phase and phase == model.PHASE_LIVE and not quick:
            # Just went live: the scoreboard read above may be ten minutes old.
            games = self.data.games(season, week, live_age) or games
        self.season, self.week, self.phase, self.use_current_week = season, week, phase, use_current
        self.games = games
        if phase == model.PHASE_IDLE:
            self.content = {}
            return

        results_week = week if use_current else week - 1
        self.results_week = results_week if results_week >= 1 else None
        players: Dict[str, Dict[str, Any]] = {}
        stats_stamp = None
        if self.results_week:
            if phase == model.PHASE_LIVE:
                stats_age = live_age
            elif phase == model.PHASE_INTERMISSION:
                stats_age = 300
            elif use_current:
                stats_age = 3600
            else:
                stats_age = 6 * 3600
            stats = self.data.week_stats(season, self.results_week, stats_age)
            stats_stamp = self.data.age(self.data.key("stats", season, self.results_week), now)
            proj = self.data.week_projections(season, self.results_week, 6 * 3600)
            if stats is not None:
                players = model.merge_week(stats, proj or {})
            else:
                # Sleeper failed and nothing is cached: ESPN's fantasy feed
                # carries points and projections for the chosen format.
                espn = self.data.espn_week_players(season, self.results_week, self.scoring, stats_age)
                if espn:
                    players = espn
            if self.results_week == week:
                self.results_games = games
            else:
                self.results_games = self.data.games(season, self.results_week, 6 * 3600) or []
        self.players = players

        if use_current:
            self.upcoming = players
        else:
            upcoming_proj = self.data.week_projections(season, week, 6 * 3600) or {}
            self.upcoming = model.merge_week({}, upcoming_proj)

        self.watch_ids = model.match_watchlist(self.watchlist, {**self.upcoming, **self.players})
        self._detect_big_plays(now, stats_stamp)
        if phase == model.PHASE_LIVE and self.spoiler_delay > 0:
            self._delayed.push(now, players)

        if self._on("hot_pickups") or self._on("weekly_awards"):
            self.trending_adds = self.data.trending("add") or []
            self.trending_drops = (self.data.trending("drop") or []) if self.show_drops else []
            self._remember_waiver_targets(now)
        if self._on("season_race") or self._on("injury_report"):
            self.season_players = self.data.season_totals(season) or {}
        self._update_league(season, now)

        self._build_content(now)
        if self.headshot_downloads:
            # Photos for the cards, jersey numbers for every list row. The
            # rows were built before the lookups, so rebuild when any landed.
            found = self.headshots.prefetch(
                self._players_on_screen(), self._players_in_rows(),
                max_downloads=4 if self.show_headshots else 0)
            if found:
                self._build_content(now)
        self.last_update = now
        self.data_version += 1
        self._frame_cache.clear()

    def _on(self, screen: str) -> bool:
        return self.screens.get(screen, {}).get("enabled", False)

    def _local_now(self) -> datetime:
        tz_name = None
        try:
            config_manager = getattr(self.plugin_manager, "config_manager", None)
            if config_manager is not None and hasattr(config_manager, "get_timezone"):
                tz_name = config_manager.get_timezone()
        except Exception:  # noqa: BLE001 - fall back to the system clock
            tz_name = None
        if tz_name and pytz is not None:
            try:
                return datetime.now(pytz.timezone(tz_name))
            except Exception:  # noqa: BLE001 - an unknown zone name
                if getattr(self, "_warned_timezone", None) != tz_name:
                    self._warned_timezone = tz_name
                    self.logger.warning("Unknown timezone '%s'; using the system clock", tz_name)
        return datetime.now()

    # big plays ---------------------------------------------------------

    def _bigplay_key(self) -> str:
        return self.data.key("bigplay")

    def _restore_bigplay(self) -> None:
        """Carry the last points snapshot and unshown alerts across a restart."""
        entry = self.data.read(self._bigplay_key())
        saved = (entry or {}).get("data") or {}
        if not isinstance(saved, dict):
            return
        self._snapshot = saved.get("snapshot") or None
        week = saved.get("week")
        self._snapshot_week = (saved.get("season"), week) if week else None
        self.alerts.add(saved.get("pending") or [])
        self.alerts.seen_keys = list(saved.get("seen") or [])[-200:]

    def _save_bigplay(self, now: float) -> None:
        self.data.write(self._bigplay_key(), {
            "season": self.season, "week": self.results_week,
            "snapshot": self._snapshot or {},
            "pending": self.alerts.pending,
            "seen": self.alerts.seen_keys[-200:],
        }, now)

    def _detect_big_plays(self, now: float, stats_age: Optional[float]) -> None:
        if not self.results_week or self.results_week != self.week:
            return
        week_id = (self.season, self.results_week)
        if self._snapshot_week != week_id:
            self._snapshot = None
            self._snapshot_week = week_id
        if not self.players:
            return
        stamp = None if stats_age is None else round(now - stats_age)
        if stamp is not None and stamp == self._stats_stamp:
            return  # same stats as last time; nothing can have changed
        self._stats_stamp = stamp
        states = model.teams_by_state(self.games)
        for abbr in states["post"]:
            self._final_seen.setdefault(abbr, now)
        recent_final = {abbr for abbr, seen in self._final_seen.items() if now - seen < 1800}
        active = states["in"] | (states["post"] & recent_final)
        snapshot = model.points_snapshot(self.players, self.scoring)
        alerts = model.detect_big_plays(
            self._snapshot, self.players, self.scoring, self.big_play_min, active,
            self.watch_ids, self.watch_play_min, now)
        for alert in alerts[:3]:
            self._describe(alert)
        added = self.alerts.add(alerts[:6])
        if added:
            self.logger.info("Big play: %s", ", ".join(
                f"{a['name']} +{a['gain']:.1f}" for a in alerts[:added]))
        self._snapshot = snapshot
        self._save_bigplay(now)

    def _describe(self, alert: Dict[str, Any]) -> None:
        team = alert.get("team")
        game = next((g for g in self.games if team in (g.get("home"), g.get("away"))), None)
        if not game or not game.get("id"):
            return
        plays = self.data.scoring_plays(game["id"]) or []
        player = self.players.get(alert["id"]) or alert
        found = model.describe_scoring_play(plays, player)
        if found:
            alert["desc"], alert["td"] = found

    # trending ------------------------------------------------------------

    def _remember_waiver_targets(self, now: float) -> None:
        """Before kickoff, note who is being added for this week (the waiver hero award)."""
        if self.use_current_week or not self.week or not self.trending_adds:
            return
        key = self.data.key("waivers", self.season, self.week)
        ids = [str(r.get("player_id")) for r in self.trending_adds[:5]]
        self.data.write(key, ids, now)

    def _waiver_ids(self) -> List[str]:
        if not self.results_week:
            return []
        entry = self.data.read(self.data.key("waivers", self.season, self.results_week))
        return list((entry or {}).get("data") or [])

    # league --------------------------------------------------------------

    def _update_league(self, season: str, now: float) -> None:
        self.league_problem = league_mod.describe_provider_problem(
            self.league_provider, self.league_id, self.espn_s2, self.espn_swid)
        if self.league_provider == "none" or self.league_problem or not self._on("league_matchup"):
            self.league = None
            return
        week = self.results_week if not self.use_current_week and self.phase == model.PHASE_RECAP else self.week
        age = self.live_poll if self.phase == model.PHASE_LIVE else 900
        self.league = league_mod.fetch_league(
            self.data, self.league_provider, self.league_id, season, week or 1,
            self.league_team, self.espn_s2, self.espn_swid, age)

    # ------------------------------------------------------------------
    # content: what each screen shows, built once per update
    # ------------------------------------------------------------------

    def _display_players(self, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        if self.phase == model.PHASE_LIVE and self.spoiler_delay > 0:
            held = self._delayed.view(time.time() if now is None else now, self.spoiler_delay)
            if held:
                return held
        return self.players

    def _build_content(self, now: float) -> None:
        fmt = self.scoring
        players = self._display_players(now)
        content: Dict[str, List[Dict[str, Any]]] = {}
        ctx = self._ctx()

        top = model.ranked(players, fmt, self.positions, self.top_n)
        board_top = model.ranked(players, fmt, self.positions, max(10, self.top_n))
        if top:
            content["player_card"] = [{"player": p, "list": board_top[:5], "rank": i} for i, p in enumerate(top)]
            live = self.phase == model.PHASE_LIVE
            content["leaderboard"] = [{
                "title": "LIVE LEADERS" if live else ("TOP SCORERS" if self.use_current_week else "LAST WEEK"),
                "right": ctx.week_label() if not (self.phase == model.PHASE_RECAP and self.use_current_week) else "FINAL",
                "rows": [render.board_row(ctx, p, i) for i, p in enumerate(board_top)],
                "colors": ((112, 52, 190), (24, 96, 200)),
            }]
            kings = model.kings(players, fmt, self.positions)
            if any(p for _, p in kings):
                content["position_kings"] = [{"cells": kings}]

        final_teams = None
        if self.use_current_week:
            final_teams = model.teams_by_state(self.results_games)["post"]
        busts = model.busts(players, fmt, self.bust_min_projection, final_teams, 3, self.positions)
        if busts:
            content["dud_alert"] = [dict(b, pair=busts[i + 1] if i + 1 < len(busts) else None)
                                    for i, b in enumerate(busts)]

        lookup = {**self.upcoming, **players}
        adds = model.trending_entries(self.trending_adds, lookup, 10, self.positions)
        if adds:
            items = [self._trend_item(adds, "add")]
            drops = model.trending_entries(self.trending_drops, lookup, 10, self.positions)
            if drops:
                items.append(self._trend_item(drops, "drop"))
            content["hot_pickups"] = items

        importance = {}
        for pid, p in self.season_players.items():
            games = model.stat(p, "gp")
            total = model.points(p, fmt)
            if games and total is not None:
                importance[pid] = total / games
        injured = model.injury_report(self.upcoming, fmt, 10, 6.0, self.positions, importance)
        if injured:
            content["injury_report"] = [{
                "title": "INJURY REPORT", "icon": "cross",
                "right": f"WK {self.week}" if self.week else "",
                "colors": ((150, 110, 10), (140, 20, 30)),
                "rows": [dict(render.board_row(ctx, e["player"], None),
                              code=e["tag"], tag=None,
                              value=f"VS {e['player']['opp']}" if e["player"].get("opp") else "",
                              value_color=draw.GRAY) for e in injured],
            }]

        if self.watch_ids:
            # The same week every other screen shows: live points during games,
            # last week's final points before kickoff.
            watched = [players.get(pid) or lookup.get(pid) for pid in self.watch_ids]
            watched = [p for p in watched if p]
            watched.sort(key=lambda p: (-(model.points(p, fmt) or -99.0), p.get("name", "")))
            if watched:
                content["watchlist"] = [{
                    "title": "MY PLAYERS", "colors": ((24, 96, 200), (20, 150, 140)),
                    "right": ctx.week_label(),
                    "rows": [render.board_row(ctx, p, None) for p in watched],
                }]

        if self.results_week and players:
            awards = model.weekly_awards(players, fmt, self.bust_min_projection, self._waiver_ids(), self.positions)
            if awards:
                content["weekly_awards"] = [{
                    "player": a["player"], "banner": a["title"], "short": a.get("short"),
                    "value": a["value"],
                    "note": a["note"], "trophy": True} for a in awards]

        if self.league and self.league.get("matchups"):
            matchups = self.league["matchups"]
            content["league_matchup"] = [{
                "league": self.league.get("name"), "week": self.league.get("week"),
                "matchup": m, "pair": matchups[i + 1] if i + 1 < len(matchups) else None,
            } for i, m in enumerate(matchups)]

        season_top = model.ranked(self.season_players, fmt, self.positions, 10)
        if season_top:
            content["season_race"] = [{
                "title": "SEASON LEADERS", "right": str(self.season or ""),
                "colors": ((90, 40, 150), (150, 30, 90)), "icon": "crown",
                "rows": [dict(render.board_row(ctx, p, i), tag=None) for i, p in enumerate(season_top)],
            }]
        self.content = content

    def _trend_item(self, entries: List[Dict[str, Any]], kind: str) -> Dict[str, Any]:
        ctx = self._ctx()
        top = max(1.0, max(e["count"] for e in entries))
        adds = kind == "add"
        rows = []
        for e in entries:
            row = render.board_row(ctx, e["player"], None)
            arrow = "↑" if adds else "↓"
            row.update(value=f"{arrow}{model.fmt_thousands(e['count'])}",
                       value_color=draw.GREEN if adds else draw.ICE,
                       bar=e["count"] / top,
                       bar_colors=((255, 70, 30), (255, 220, 90)) if adds else ((40, 90, 200), (140, 220, 255)))
            rows.append(row)
        return {
            "title": "HOT PICKUPS" if adds else "COLD DROPS",
            "icon": "flame" if adds else "snow",
            "right": "24H ADDS" if adds else "24H DROPS",
            "colors": ((180, 64, 10), (140, 12, 40)) if adds else ((20, 70, 150), (60, 30, 120)),
            "rows": rows,
        }

    def _players_on_screen(self) -> List[Dict[str, Any]]:
        """Who the cards will draw, most visible first (headshot prefetch order)."""
        wanted: List[Dict[str, Any]] = []
        for alert in self.alerts.pending:
            p = self.players.get(alert.get("id"))
            if p:
                wanted.append(p)
        for key in ("player_card", "weekly_awards"):
            wanted.extend(item["player"] for item in self.content.get(key, []))
        wanted.extend(item["player"] for item in self.content.get("dud_alert", []))
        for item in self.content.get("position_kings", []):
            wanted.extend(p for _, p in item.get("cells", []) if p)
        return wanted

    def _players_in_rows(self) -> List[Dict[str, Any]]:
        """Everyone on a list screen, for jersey-number lookups (no photos)."""
        lookup = {**self.upcoming, **self.players, **self.season_players}
        return [lookup[row["id"]]
                for key in LIST_SCREENS for item in self.content.get(key, [])
                for row in item.get("rows", []) if row.get("id") in lookup]

    # ------------------------------------------------------------------
    # display
    # ------------------------------------------------------------------

    def _ctx(self) -> render.RenderContext:
        status = ""
        if self.phase == model.PHASE_LIVE:
            status = "LIVE"
        elif self.phase == model.PHASE_RECAP and self.use_current_week:
            status = "FINAL"
        return render.RenderContext(
            fmt=self.scoring, tiers=self.tiers, headshots=self.headshots,
            week=self.results_week if self.results_week else self.week,
            phase=self.phase, animate=self.animations, show_headshots=self.show_headshots,
            status=status)

    @property
    def needs_high_fps(self) -> bool:
        """High FPS only for the animated screens, and only with animation on.

        The core reads this once per mode, after the mode's first display()
        call, so it reflects the screen being entered.
        """
        return bool(self.animations and self._current_screen is not None)

    def display(self, force_clear: bool = False, display_mode: Optional[str] = None) -> bool:
        mode = display_mode or self.modes[self.current_mode_index % len(self.modes)]
        screen = MODE_SCREENS.get(mode)
        if screen is None or not self.enabled:
            return False
        now = time.time()
        entering = mode != self._current_mode or force_clear
        if entering:
            if self._current_screen == "big_play" and screen != "big_play":
                self.alerts.finish()
            self._current_mode = mode
            self._mode_started = now
            self._last_frame_at = 0.0
            # Another plugin may have drawn since this mode last ran, so the
            # first frame is always pushed, even when it is cached.
            self._shown_key = None
        self._current_screen = screen

        if not self._on(screen):
            return False
        if screen == "big_play":
            return self._display_alert(now, force_clear)
        if self.phase not in model.SCREEN_PHASES.get(screen, ()):
            return False
        items = self.content.get(screen) or []
        if screen in LIST_SCREENS:
            items = self._pages(items)
        if not items:
            return False

        elapsed = now - self._mode_started
        per = PAGE_SECONDS if screen in LIST_SCREENS else self.item_seconds
        index = int(elapsed // per) % len(items)
        t = elapsed - int(elapsed // per) * per
        return self._show(screen, index, items[index], t, now, force_clear)

    def _pages(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Split list items into pages that fit the panel."""
        _, bw, bh = render.base_size(self.display_manager.width, self.display_manager.height)
        capacity = render.list_capacity(bw, bh)
        pages = []
        for item in items:
            rows = item.get("rows") or []
            limit = max(capacity, 1)
            # Two pages at most: the second page is the rest of a top ten.
            for start in range(0, min(len(rows), limit * 2), limit):
                pages.append(dict(item, rows=rows[start:start + limit]))
        return pages

    def _renderer_for(self, screen: str):
        return {
            "player_card": render.card, "weekly_awards": render.card,
            "leaderboard": render.board, "hot_pickups": render.board,
            "injury_report": render.board, "watchlist": render.board,
            "season_race": render.board, "dud_alert": render.dud,
            "position_kings": render.kings, "league_matchup": render.matchup,
            "big_play": render.big_play,
        }[screen]

    def _still(self, screen: str, item: Dict[str, Any], t: float) -> bool:
        """True when this frame will not change until the item does."""
        if not self.animations:
            return True
        if screen == "big_play" or screen == "dud_alert":
            return False
        if screen == "hot_pickups" and item.get("icon") == "flame":
            return False
        if screen in ("player_card", "weekly_awards"):
            value = item.get("value", model.points(item["player"], self.scoring))
            if model.tier_for(value, self.tiers) == "legendary":
                return False
        return t >= _INTRO_SECONDS.get(screen, 0.0)

    def _show(self, screen: str, index: int, item: Dict[str, Any], t: float, now: float,
              force_clear: bool) -> bool:
        w, h = self.display_manager.width, self.display_manager.height
        key = (screen, index, self.data_version, w, h)
        if not force_clear and key in self._frame_cache:
            # Only finished, motionless frames are cached.
            if self._shown_key == key:
                return True  # the panel already holds this exact frame
            frame = self._frame_cache[key]
        else:
            if (self.animations and not force_clear
                    and now - self._last_frame_at < 1.0 / self.animation_fps):
                return True
            title, color = SCREEN_TITLES.get(screen, ("FANTASY", draw.GOLD))
            ctx = self._ctx()
            try:
                frame = render.render_frame(self._renderer_for(screen), ctx, item, w, h,
                                            t if self.animations else 99.0, title, color)
            except Exception as exc:  # noqa: BLE001 - never lose the loop to a draw
                self.logger.error("Could not draw %s: %s", screen, exc, exc_info=True)
                return False
            if self._still(screen, item, t) and not ctx.moving:
                self._frame_cache[key] = frame
        self._last_frame_at = now
        self.display_manager.image.paste(frame, (0, 0))
        self.display_manager.update_display()
        self._shown_key = key if key in self._frame_cache else None
        return True

    def _display_alert(self, now: float, force_clear: bool) -> bool:
        if self.phase == model.PHASE_IDLE:
            return False
        # Which alerts were shown is persisted by the next update(), not here:
        # display() stays free of cache writes, and a restart inside that
        # minute costs at most one repeated alert.
        current = self.alerts.current
        if current is not None and now - current.get("shown_at", now) >= ALERT_SECONDS:
            self.alerts.finish()
            return False
        alert = self.alerts.take(now, self.spoiler_delay)
        if alert is None:
            return False
        item = dict(alert, player=self.players.get(alert.get("id")) or alert)
        t = now - alert.get("shown_at", now)
        return self._show("big_play", 0, item, t, now, force_clear)

    # ------------------------------------------------------------------
    # duration and live priority
    # ------------------------------------------------------------------

    def get_display_duration(self) -> float:
        """Seconds for the mode on screen; ``duration: 0`` means "long enough"."""
        screen = self._current_screen
        if screen is None:
            return float(self.display_duration)
        configured = self.screens.get(screen, {}).get("duration", 0)
        if configured:
            return float(configured)
        if screen == "big_play":
            return float(ALERT_SECONDS)
        items = self.content.get(screen) or []
        if screen in LIST_SCREENS:
            count, per = len(self._pages(items)), PAGE_SECONDS
        else:
            count, per = len(items), self.item_seconds
        if not count:
            return float(self.display_duration)
        return float(max(per, min(60, count * per)))

    def has_live_priority(self) -> bool:
        return bool(self.live_priority and self._on("big_play"))

    def has_live_content(self) -> bool:
        """A big play is waiting (and past the spoiler delay). Attribute reads only."""
        if not self.has_live_priority() or self.phase == model.PHASE_IDLE:
            return False
        return self.alerts.can_show(time.time(), self.spoiler_delay)

    def get_live_modes(self) -> List[str]:
        return [LIVE_MODE]

    # ------------------------------------------------------------------
    # Vegas
    # ------------------------------------------------------------------

    def get_vegas_content(self) -> Optional[List[Any]]:
        top = model.ranked(self._display_players(), self.scoring, self.positions, max(self.top_n, 5))
        if not top:
            return None
        height = self.display_manager.height
        ctx = self._ctx()
        cards = [render.vegas_title(height)]
        cards.extend(render.vegas_entry(ctx, p, height) for p in top)
        return cards

    def get_vegas_content_type(self) -> str:
        return "multi"

    def get_vegas_display_mode(self):
        if VegasDisplayMode is None:
            return "scroll"
        if self.vegas_mode:
            try:
                return VegasDisplayMode(self.vegas_mode)
            except ValueError:
                self.logger.warning("Invalid vegas_mode '%s', using scroll", self.vegas_mode)
        return VegasDisplayMode.SCROLL

    # ------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------

    def _warn_occasionally(self, message: str) -> None:
        now = time.time()
        if now - self._last_warning >= 300:
            self._last_warning = now
            self.logger.warning(message)

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "phase": self.phase,
            "season": self.season,
            "week": self.week,
            "results_week": self.results_week,
            "scoring": self.scoring,
            "players_loaded": len(self.players),
            "screens_with_content": sorted(self.content),
            "pending_big_plays": len(self.alerts.pending),
            "watchlist_matched": sorted(self.watch_ids.values()),
            "league": (self.league or {}).get("name"),
            "league_problem": self.league_problem,
            "last_update": self.last_update,
        })
        return info

    def cleanup(self) -> None:
        self._frame_cache.clear()
        try:
            self.data.session.close()
        except Exception as exc:  # noqa: BLE001 - closing is best effort
            self.logger.debug("Could not close the HTTP session: %s", exc)
        super().cleanup()


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default
