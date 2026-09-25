import logging
import re
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from data_sources import ESPNDataSource
from sports import SportsCore, SportsLive

#: Colour of the power-play marker (and of the clock row when there is no room
#: for the marker). game_renderer.py keeps an identical copy for scroll cards.
POWER_PLAY_COLOR = (255, 255, 0)


def power_play_slot(draw, width, clock_text, clock_xy, clock_font,
                    score_text, score_xy, score_font, pp_font):
    """Top-left for a centred "PP" in the rows between clock and score, or None.

    None means those rows cannot hold the glyphs plus their one-pixel outline
    without touching the clock or the score -- every 32-row panel.
    """
    pp_box = draw.textbbox((0, 0), "PP", font=pp_font)
    pp_w, pp_h = pp_box[2] - pp_box[0], pp_box[3] - pp_box[1]
    top = draw.textbbox(clock_xy, clock_text, font=clock_font)[3] if clock_text else clock_xy[1]
    bottom = draw.textbbox(score_xy, score_text, font=score_font)[1]
    if bottom - top < pp_h + 2:
        return None
    return ((width - pp_w) // 2 - pp_box[0],
            top + (bottom - top - pp_h) // 2 - pp_box[1])


# ESPN spells a goal's strength out in full ("Power play", "Shorthanded");
# the card has room for a badge, not a sentence. Even strength gets nothing --
# it is the default state and saying so wastes the one slot that matters.
GOAL_STRENGTH_BADGES: Dict[str, str] = {
    "power-play": "PP",
    "short-handed": "SH",
    "empty-net": "EN",
    "penalty-shot": "PS",
}


def _goal_strength_badge(play: Dict) -> Optional[str]:
    """Short badge for a goal's strength, or None at even strength."""
    strength = play.get("strength") or {}
    if not isinstance(strength, dict):
        return None
    key = (strength.get("abbreviation") or "").strip().lower()
    if key in GOAL_STRENGTH_BADGES:
        return GOAL_STRENGTH_BADGES[key]
    text = (strength.get("text") or "").strip().lower()
    for candidate, badge in GOAL_STRENGTH_BADGES.items():
        if candidate.replace("-", " ") == text:
            return badge
    return None


def _extract_goal(play: Dict) -> Optional[Dict]:
    """Pull the scorer, assisters and context out of one ESPN scoring play.

    Hockey's feed is kinder than baseball's here: the play itself carries each
    athlete's id, name and headshot URL, plus their season goal/assist totals,
    so the card has something worth drawing before any athlete lookup happens.
    Returns None for a play that names nobody -- an own goal, or a feed that
    filled in the text and not the participants."""
    scorer = None
    assists: List[Dict] = []
    for participant in play.get("participants") or []:
        athlete = participant.get("athlete") or {}
        athlete_id = str(athlete.get("id", "") or "")
        name = athlete.get("displayName") or athlete.get("shortName") or ""
        if not name:
            continue
        entry = {
            "id": athlete_id,
            "name": name,
            "short_name": athlete.get("shortName") or name,
            "headshot_url": (athlete.get("headshot") or {}).get("href"),
        }
        role = participant.get("type")
        if role == "scorer" and scorer is None:
            entry["season_goals"] = participant.get("ytdGoals")
            scorer = entry
        elif role == "assister":
            entry["season_assists"] = participant.get("ytdAssists")
            assists.append(entry)
    if scorer is None:
        return None

    period = play.get("period") or {}
    clock = play.get("clock") or {}
    return {
        "play_id": str(play.get("id", "") or ""),
        "scorer": scorer,
        "assists": assists,
        "team_id": str((play.get("team") or {}).get("id", "") or ""),
        "period": period.get("displayValue") or (
            str(period.get("number")) if period.get("number") else ""
        ),
        "clock": clock.get("displayValue") or "",
        "strength": _goal_strength_badge(play),
        "away_score": play.get("awayScore"),
        "home_score": play.get("homeScore"),
    }


def _latest_goal(plays: Optional[List[Dict]], team_id: Optional[str] = None) -> Optional[Dict]:
    """The most recent scoring play, optionally restricted to one team.

    Scanned backwards because ESPN appends, and restricted by team because the
    card is armed off a score delta: if both sides scored between two polls,
    the newest goal overall may not be the one that fired the celebration."""
    for play in reversed(plays or []):
        if not play.get("scoringPlay"):
            continue
        goal = _extract_goal(play)
        if goal is None:
            continue
        if team_id and goal["team_id"] and goal["team_id"] != str(team_id):
            continue
        return goal
    return None


# Game-activity pop-ups: the non-scoring plays worth a line on the scorebug.
# Each kind is recognised by the words of the play's ESPN type (text and
# abbreviation, split on anything but letters). Checked in order, so the
# specific shot kinds claim "Blocked Shot" and "Missed Shot" before the plain
# shot kind can.
_ACTIVITY_KIND_WORDS: Tuple[Tuple[str, str], ...] = (
    ("penalties", "penalty"),
    ("blocked_shots", "blocked"),
    ("missed_shots", "missed"),
    ("shots", "shot"),
    ("hits", "hit"),
)
DEFAULT_ACTIVITY_KINDS: Tuple[str, ...] = ("shots", "penalties")
#: What each kind says on the panel, longest first: the banner takes the
#: longest spelling that fits beside the player's name and the game clock.
_ACTIVITY_LABELS: Dict[str, Tuple[str, ...]] = {
    "shots": ("SHOT ON GOAL!", "SHOT!"),
    "penalties": ("PENALTY", "PEN"),
    "hits": ("HIT!",),
    "blocked_shots": ("BLOCKED SHOT", "BLOCKED"),
    "missed_shots": ("MISSED SHOT", "MISSED"),
}
#: Panels shorter than this have no row to spare: the scorebug's bottom row
#: is the shot line, and on a 32- or 48-row panel the score sits right on it.
_ACTIVITY_MIN_HEIGHT = 64
#: At most this many pop-ups wait their turn. A poll can bring a burst; the
#: newest are kept, since each one's clock says how old it is anyway.
_ACTIVITY_QUEUE_MAX = 3
#: Floor on the summary poll, whatever live_update_interval says.
_ACTIVITY_MIN_POLL_SECONDS = 10


def _activity_kind(play_type: Optional[Dict]) -> Optional[str]:
    """The pop-up kind for an ESPN play type, or None if it has none."""
    if not isinstance(play_type, dict):
        return None
    words = set(re.split(
        r"[^a-z]+",
        f"{play_type.get('text') or ''} {play_type.get('abbreviation') or ''}".lower(),
    ))
    for kind, word in _ACTIVITY_KIND_WORDS:
        if word in words:
            return kind
    return None


def _extract_activity(play: Dict) -> Optional[Dict]:
    """One ESPN play as a pop-up: its kind, who, which team and when.

    None for goals, which the celebration and the goal card already own, and
    for play types the pop-ups do not cover. The first named participant is
    the one the line is about -- the shooter, or the player penalised."""
    if not isinstance(play, dict) or play.get("scoringPlay"):
        return None
    kind = _activity_kind(play.get("type"))
    if kind is None:
        return None
    names: List[str] = []
    for participant in play.get("participants") or []:
        athlete = (participant or {}).get("athlete") or {}
        full = athlete.get("displayName") or ""
        short = athlete.get("shortName") or full
        if short:
            # "A. Matthews", then "Matthews" for a panel too narrow for both.
            names = [short]
            last = full.split()[-1] if full else ""
            if last and last != short:
                names.append(last)
            break
    period = play.get("period") or {}
    return {
        "play_id": str(play.get("id", "") or ""),
        "kind": kind,
        "names": names,
        "team_id": str((play.get("team") or {}).get("id", "") or ""),
        "period": period.get("displayValue") or (
            str(period.get("number")) if period.get("number") else ""
        ),
        "clock": (play.get("clock") or {}).get("displayValue") or "",
    }


# ESPN's team.color / team.alternateColor are brand hex values, chosen for
# jerseys rather than a black LED panel: a navy primary all but vanishes there
# and a white one glares. Clamped into the same legible band
# baseball-scoreboard uses (baseball.py, _parse_team_color).
_MIN_COLOR_BRIGHTNESS = 90
_MAX_COLOR_BRIGHTNESS = 235
#: Below this saturation, or with no channel above _TEAM_COLOR_MIN_CHANNEL, a
#: colour is a black, grey or white. Clamping makes one legible but not
#: recognisable, so a team that lists black first is drawn in its alternate.
_TEAM_COLOR_MIN_SATURATION = 0.25
_TEAM_COLOR_MIN_CHANNEL = 24


def _parse_hex_color(hex_str: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """'be0a14' or '#be0a14' as an (R, G, B) tuple, or None if malformed."""
    if not isinstance(hex_str, str):
        return None
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) != 6:
        return None
    try:
        return tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _has_hue(rgb: Tuple[int, int, int]) -> bool:
    high = max(rgb)
    return (
        high >= _TEAM_COLOR_MIN_CHANNEL
        and (high - min(rgb)) / high >= _TEAM_COLOR_MIN_SATURATION
    )


def _clamp_brightness(rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Scale a colour into the legible band, keeping its channel ratios."""
    brightness = sum(rgb) / 3
    if 0 < brightness < _MIN_COLOR_BRIGHTNESS:
        scale = _MIN_COLOR_BRIGHTNESS / brightness
        return tuple(min(255, int(c * scale)) for c in rgb)
    if brightness > _MAX_COLOR_BRIGHTNESS:
        scale = _MAX_COLOR_BRIGHTNESS / brightness
        return tuple(int(c * scale) for c in rgb)
    return rgb


def _team_color(team: Optional[Dict]) -> Optional[Tuple[int, int, int]]:
    """A team's colour for the goal card, read from an ESPN competitor's
    ``team`` object and brightness-clamped for a black panel.

    The primary wins unless it has no hue and the alternate does. When neither
    has one (black and silver) the brighter is used. None when ESPN sent no
    usable colour, or only pure black, so the card keeps its configured
    accent."""
    if not isinstance(team, dict):
        return None
    colors = [
        rgb
        for rgb in (_parse_hex_color(team.get("color")),
                    _parse_hex_color(team.get("alternateColor")))
        if rgb is not None and any(rgb)
    ]
    if not colors:
        return None
    vivid = [rgb for rgb in colors if _has_hue(rgb)]
    return _clamp_brightness(vivid[0] if vivid else max(colors, key=sum))


class Hockey(SportsCore):
    """Base class for hockey sports with common functionality."""

    # Set by league-specific base managers to opt into the ESPN per-game
    # summary endpoint, which is where the goal scorer lives. Left None for
    # college hockey: its summary carries no `plays` array at all, so there
    # is nothing to read a scorer out of.
    espn_summary_sport_league: Optional[Tuple[str, str]] = None

    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        self.data_source = ESPNDataSource(logger)
        self.sport = "hockey"
        self.show_shots_on_goal = self.mode_config.get("show_shots_on_goal", False)
        # True mirrors the adapter's own fallback in manager.py and the
        # schema's defaults.show_powerplay.
        self.show_powerplay = self.mode_config.get("show_powerplay", True)
        # Opt-in: the card costs one extra ESPN summary request per goal, and
        # a second for the scorer's bio. Off unless asked for.
        self.show_goal_scorer = self.mode_config.get("show_goal_scorer", False)
        # Opt-in for the same reason: one summary request per live poll of
        # the game on screen, for the pop-ups of its shots and penalties.
        self.show_game_activity = self.mode_config.get("show_game_activity", False)

    def _extract_game_details(self, game_event: Dict) -> Optional[Dict]:
        """Extract relevant game details from ESPN Hockey API response."""
        details, home_team, away_team, status, situation = (
            self._extract_game_details_common(game_event)
        )
        if details is None or home_team is None or away_team is None or status is None:
            return
        try:
            competition = game_event["competitions"][0]
            status = competition["status"]
            powerplay = False
            penalties = ""
            home_stats = home_team.get("statistics", [])
            away_stats = away_team.get("statistics", [])
            home_team_saves = next(
                (
                    int(c["displayValue"])
                    for c in home_stats
                    if c.get("name") == "saves"
                ),
                0,
            )
            home_team_saves_per = next(
                (
                    float(c["displayValue"])
                    for c in home_stats
                    if c.get("name") == "savePct"
                ),
                0.0,
            )
            away_team_saves = next(
                (
                    int(c["displayValue"])
                    for c in away_stats
                    if c.get("name") == "saves"
                ),
                0,
            )
            away_team_saves_per = next(
                (
                    float(c["displayValue"])
                    for c in away_stats
                    if c.get("name") == "savePct"
                ),
                0.0,
            )

            home_shots = 0
            away_shots = 0
            if home_team_saves_per > 0:
                away_shots = round(home_team_saves / home_team_saves_per)
            if away_team_saves_per > 0:
                home_shots = round(away_team_saves / away_team_saves_per)

            if situation and status["type"]["state"] == "in":
                # Detect scoring events from status detail
                # status_detail = status["type"].get("detail", "")
                powerplay = situation.get("isPowerPlay", False)
                penalties = situation.get("penalties", "")

            # Format period/quarter
            period = status.get("period", 0)
            period_text = ""
            if status["type"]["state"] == "in":
                if period == 0:
                    period_text = "Start"  # Before start
                elif period >= 1 and period <= 3:
                    period_text = f"P{period}"  # Periods 1-3
                elif period > 3:
                    period_text = f"OT{period - 3}"  # Overtime
            elif details.get("is_final"):
                if period > 3:
                    period_text = "Final/OT"
                else:
                    period_text = "Final"
            elif status["type"]["state"] == "post":
                # Postponed, cancelled or suspended: ESPN files these under
                # "post" too. Labelling them "Final" is what put them on the
                # Recent screen as a 0-0 result, via the "final" in
                # period_text fallback there, even with is_final False.
                period_text = status["type"].get("shortDetail") or ""
            elif status["type"]["state"] == "pre":
                period_text = details.get("game_time", "")  # Show time for upcoming

            details.update(
                {
                    "period": period,
                    "period_text": period_text,  # Formatted period/status
                    "clock": status.get("displayClock", "0:00"),
                    "power_play": powerplay,
                    "penalties": penalties,
                    "home_shots": home_shots,
                    "away_shots": away_shots,
                    # Read by the goal-scorer card for its banner and accents.
                    "home_team_color": _team_color(home_team.get("team")),
                    "away_team_color": _team_color(away_team.get("team")),
                }
            )

            # Basic validation (can be expanded)
            if not details["home_abbr"] or not details["away_abbr"]:
                self.logger.warning(
                    f"Missing team abbreviation in event: {details['id']}"
                )
                return None

            self.logger.debug(
                f"Extracted: {details['away_abbr']}@{details['home_abbr']}, Status: {status['type']['name']}, Live: {details['is_live']}, Final: {details['is_final']}, Upcoming: {details['is_upcoming']}"
            )

            return details
        except Exception as e:
            # Log the problematic event structure if possible
            self.logger.error(
                f"Error extracting game details: {e} from event: {game_event.get('id')}",
                exc_info=True,
            )
            return None


class HockeyLive(Hockey, SportsLive):
    def __init__(
        self,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        logger: logging.Logger,
        sport_key: str,
    ):
        super().__init__(config, display_manager, cache_manager, logger, sport_key)
        # The goal-scorer card. Holds the resolved goal for the game that
        # scored and the window the card owns the panel for.
        self._goal_card: Optional[Dict] = None
        # Per-game {away, home} score baselines, kept independently of the
        # celebration's so the card works with the takeover switched off.
        self._goal_card_baselines: Dict[str, Dict[str, int]] = {}
        self._player_bio_cache: Dict[str, Optional[Dict]] = {}
        self._headshot_mgr = None  # lazily created on the render path
        # Game-activity pop-ups. The poll thread appends to the queue and the
        # render thread pops from it; deque's append/popleft are atomic, so
        # neither side needs a lock. _activity_seen holds each game's newest
        # play id, so a poll only pops up what happened since the last one.
        self._activity_queue: Deque[Dict] = deque(maxlen=_ACTIVITY_QUEUE_MAX)
        self._activity_popup: Optional[Dict] = None
        self._activity_seen: Dict[str, Optional[str]] = {}
        self._activity_last_poll = 0.0
        self._activity_inflight = False
        # Last time the live scorebug was drawn where a pop-up could show.
        self._activity_drawn_at = 0.0

    # ------------------------------------------------------------------
    # Goal-scorer card
    #
    # A goal is spotted the same way the celebration spots one -- a score
    # delta on the scoreboard feed -- but with its own baseline, so the card
    # and the takeover are genuinely independent settings: either, both or
    # neither. What that feed never carries is *who* scored, so the card is a
    # second request. With the celebration on it is drawn once the takeover
    # clears; with the celebration off it is drawn straight away.
    # ------------------------------------------------------------------

    def _goal_card_cfg(self) -> Dict:
        return self.config.get("customization", {}).get("goal_scorer", {})

    def update(self):
        super().update()
        if self.test_mode or not self.espn_summary_sport_league:
            return  # college hockey: no play data to read a scorer from
        if getattr(self, "show_game_activity", False):
            self._poll_game_activity()
        if not self.show_goal_scorer:
            return

        cfg = self._goal_card_cfg()
        favorites_only = cfg.get("favorites_only", False)
        for game in list(self.live_games or []):
            scored_side = self._detect_goal_for_card(game)
            if scored_side is None:
                continue
            if favorites_only and self.favorite_teams:
                if game.get(f"{scored_side}_abbr") not in self.favorite_teams:
                    continue
            self._goal_card = None
            self._resolve_goal_scorer(game, scored_side)
        self._prune_goal_card_baselines()

    def _detect_goal_for_card(self, game: Dict) -> Optional[str]:
        """Return 'away'/'home' when this game's score just went up, else None.

        The card keeps its own baseline rather than riding on the
        celebration's. That is the whole point of the two settings being
        independent: SportsLive._check_for_goal returns early when
        celebration_enabled is off, so a card armed off active_celebration
        could never appear without the takeover. Same rules as that method,
        for the same reasons -- a first sighting never fires, because a game
        already in progress at boot would otherwise report every goal it
        already had, and a decrement re-bases silently, because a goal waved
        off after review is not a goal."""
        game_id = game.get("id")
        if not game_id:
            return None
        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        if away is None or home is None:
            return None
        baseline = self._goal_card_baselines.get(game_id)
        self._goal_card_baselines[game_id] = {"away": away, "home": home}
        if baseline is None:
            return None
        if away > baseline["away"]:
            return "away"
        if home > baseline["home"]:
            return "home"
        return None

    def _prune_goal_card_baselines(self) -> None:
        """Drop baselines for games no longer live, so a board left running
        through a season does not accumulate one dict per game it ever saw."""
        live_ids = {g.get("id") for g in (self.live_games or [])}
        for game_id in [k for k in self._goal_card_baselines if k not in live_ids]:
            self._goal_card_baselines.pop(game_id, None)

    def _goal_card_window(self, game_id: str) -> Tuple[float, float]:
        """When the card should appear and disappear.

        With the celebration on, the card is the second beat: it waits for the
        takeover to finish. With the celebration off it is the only beat, and
        appears straight away. The two settings are independent, so both
        orders have to work."""
        now = time.time()
        show_from = now
        celebration = getattr(self, "active_celebration", None)
        if (
            celebration
            and celebration.get("kind") == "goal"
            and str((celebration.get("game") or {}).get("id") or "") == str(game_id)
        ):
            show_from = celebration.get("started_at", now) + float(
                getattr(self, "celebration_duration", 8) or 8
            )
        return show_from, show_from + float(
            self._goal_card_cfg().get("dwell_seconds", 6)
        )

    def _resolve_goal_scorer(self, game: Dict, scored_side: str) -> None:
        """Look up who scored, off-thread, and arm the card when it lands.

        Fire-and-forget: the render path only ever reads the result, so a slow
        or failed lookup costs the card rather than the display. The bio is
        fetched in the same thread, after the play -- the card is already
        worth drawing from the play alone, and the bio only adds trivia."""
        game = dict(game)  # snapshot: survives the game leaving live_games
        game_id = game.get("id")
        if not game_id:
            return
        team_id = game.get(f"{scored_side}_id") if scored_side else None
        sport, league = self.espn_summary_sport_league
        show_from, show_until = self._goal_card_window(game_id)

        import threading

        def resolve():
            try:
                summary = self.data_source.fetch_game_summary(sport, league, str(game_id))
                if not summary:
                    return
                goal = _latest_goal(summary.get("plays"), team_id)
                if goal is None:
                    self.logger.debug(
                        f"No named scorer in the summary for game {game_id}; "
                        "skipping the goal card"
                    )
                    return
                scorer_id = goal["scorer"].get("id")
                if scorer_id:
                    self._fetch_player_bio(sport, league, scorer_id)
                    goal["bio"] = self._player_bio_cache.get(scorer_id)
                    url = (goal.get("bio") or {}).get("headshot_url") or \
                        goal["scorer"].get("headshot_url")
                    self._prefetch_headshot(scorer_id, url, league)
                goal["game_id"] = str(game_id)
                goal["team_abbr"] = game.get(f"{scored_side}_abbr", "")
                goal["team_color"] = game.get(f"{scored_side}_team_color")
                goal["show_from"] = show_from
                goal["show_until"] = show_until
                self._goal_card = goal
            except Exception as e:
                self.logger.debug(f"Goal-scorer lookup failed for {game_id}: {e}")

        threading.Thread(target=resolve, daemon=True).start()

    def _fetch_player_bio(self, sport: str, league: str, player_id: str) -> None:
        """Cache a scorer's bio in memory and, when the core gave us one, in
        the durable cache. Stores None on a definitive miss so a player with
        no ESPN record is not re-fetched on every goal."""
        if player_id in self._player_bio_cache:
            return
        cache_key = f"hockey_player_{player_id}"
        if self.cache_manager is not None:
            try:
                cached = self.cache_manager.get(cache_key)
                if cached is not None:
                    self._player_bio_cache[player_id] = cached or None
                    return
            except Exception as e:
                self.logger.debug(f"Player bio cache read failed for {player_id}: {e}")

        bio = self.data_source.fetch_player_details(sport, league, player_id)
        self._player_bio_cache[player_id] = bio
        if self.cache_manager is not None:
            try:
                self.cache_manager.set(cache_key, bio or {}, ttl=86400)
            except Exception as e:
                self.logger.debug(f"Player bio cache write failed for {player_id}: {e}")

    def _get_headshot_manager(self):
        """Lazily create the headshot loader, reusing the hockey logo
        manager's download/cache machinery. None means the card renders
        text-only rather than failing."""
        if self._headshot_mgr is None:
            try:
                from hockey_headshot_manager import HockeyHeadshotManager
                self._headshot_mgr = HockeyHeadshotManager(
                    self.display_manager, self.logger, self.sport_key
                )
            except Exception as e:
                self.logger.debug(f"Could not create headshot manager: {e}")
                return None
        return self._headshot_mgr

    def _prefetch_headshot(self, player_id: str, url: Optional[str], league: str) -> None:
        """Warm the on-disk headshot cache so the render path only ever does
        a synchronous cache read. Already off the render thread (called from
        the resolve thread), so no extra thread is needed here."""
        if not url:
            return
        mgr = self._get_headshot_manager()
        if mgr is None:
            return
        try:
            mgr.load_headshot(str(player_id), url, league=league, max_size=48,
                              allow_download=True)
        except Exception as e:
            self.logger.debug(f"Headshot prefetch failed for {player_id}: {e}")

    def _test_mode_update(self):
        if self.current_game and self.current_game["is_live"]:
            # For testing, we'll just update the clock to show it's working
            minutes = int(self.current_game["clock"].split(":")[0])
            seconds = int(self.current_game["clock"].split(":")[1])
            seconds -= 1
            if seconds < 0:
                seconds = 59
                minutes -= 1
                if minutes < 0:
                    minutes = 19
                    if self.current_game["period"] < 3:
                        self.current_game["period"] += 1
                    else:
                        self.current_game["period"] = 1
            self.current_game["clock"] = f"{minutes:02d}:{seconds:02d}"
            # Always update display in test mode

    # Ordered largest-to-smallest fallback ladder. BDF fonts are fixed-size
    # bitmaps -- they cannot shrink to an arbitrary computed size the way a
    # scalable .ttf can -- so when the configured font's measured row height
    # will not fit the rows the card needs, step down a rung rather than lose
    # a row off the bottom.
    #
    # The X11 rungs alone were a poor ladder for this card. 6x13, 6x12, 6x10
    # and 6x9 are all six pixels wide: four consecutive steps that get
    # shorter and never narrower, which does nothing at all when the binding
    # constraint is width -- a long name or a four-stat line on a narrow
    # panel, which is most of the time here. MatrixChunky8 is the same row
    # height as 5x8 but proportional, so it draws this card's text about a
    # third narrower, and it separates B from 8 and O from 0 better than the
    # 4x6 face (the confusion that kept 4x6 off this ladder in the first
    # place). It is placed immediately before the X11 rung of its own height
    # so every choice is either unchanged or swapped for a same-height,
    # narrower face: panels with room to spare render exactly as before,
    # while a 64x32 keeps a full name where it used to truncate one.
    # MatrixLight6 closes the ladder for the same reason at 5x7's height.
    _GOAL_CARD_FONT_LADDER: List[str] = [
        "9x15.bdf", "8x13.bdf", "7x13.bdf", "6x13.bdf",
        "6x12.bdf", "6x10.bdf", "6x9.bdf",
        "MatrixChunky8.bdf", "5x8.bdf", "5x7.bdf", "MatrixLight6.bdf",
    ]

    # Top-to-bottom order the card's rows are drawn in.
    _GOAL_CARD_ROW_ORDER: Tuple[str, ...] = (
        "header", "name", "team", "stats", "assists", "vitals", "hometown",
    )
    # The order rows are given up in when the panel cannot fit them all, least
    # useful first. Not the reverse of the draw order: the assists read above
    # the trivia but below the scorer's own season line, which is the thing
    # that makes this a player card rather than a ticker line.
    _GOAL_CARD_DROP_ORDER: Tuple[str, ...] = (
        "hometown", "vitals", "assists", "team", "stats",
    )

    @staticmethod
    def _readable_on(background: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Black or white, whichever reads against `background`. Team colours
        run from near-black navy to bright gold, so a banner knocked out in a
        fixed colour is illegible for roughly half the league."""
        r, g, b = background[:3]
        # Rec. 601 luma -- close enough for a two-way choice, and cheap.
        return (0, 0, 0) if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else (255, 255, 255)

    @staticmethod
    def _truncate_to_width(draw, text: str, font, max_width: int) -> str:
        """Hard-truncate text (no ellipsis -- pixel fonts render one poorly at
        these sizes) so it never draws past the panel edge. A long name is
        more useful clipped than bleeding off-canvas."""
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        truncated = text
        while len(truncated) > 1:
            truncated = truncated[:-1]
            if draw.textbbox((0, 0), truncated, font=font)[2] <= max_width:
                return truncated
        return truncated

    @staticmethod
    def _fit_segments(draw, segments: List[str], font, fit_width: int,
                      separator: str = "  ") -> str:
        """Join `segments` into one line that fits fit_width, dropping whole
        trailing segments rather than cutting through the middle of one.
        "Age 33  6' 0"" reads as a finished line; "Age 33  6' " does not."""
        if not segments:
            return ""
        trimmed = list(segments)
        while len(trimmed) > 1:
            if draw.textbbox((0, 0), separator.join(trimmed), font=font)[2] <= fit_width:
                break
            trimmed = trimmed[:-1]
        return separator.join(trimmed)

    def _load_multiline_fit_font(self, font_cfg: Dict, lines: List[str],
                                 available_width: int, available_height: int):
        """Largest font from the ladder that fits every line's actual text in
        the space available, falling back a rung at a time. Measures the real
        strings rather than a generic glyph, so a long name pushes the ladder
        down where a short one would not."""
        needed_rows = max(1, len(lines))
        candidates = [font_cfg.get("font", "9x15.bdf")]
        for fallback in self._GOAL_CARD_FONT_LADDER:
            if fallback not in candidates:
                candidates.append(fallback)

        result = None
        for i, font_name in enumerate(candidates):
            cfg_try = dict(font_cfg)
            cfg_try["font"] = font_name
            font = self._load_custom_font_from_element_config(
                cfg_try, default_size=font_cfg.get("font_size", 24)
            )
            try:
                row_h = (font.getbbox("Ay")[3] - font.getbbox("Ay")[1]) + 3
                max_line_w = max((font.getbbox(t)[2] for t in lines), default=0)
            except AttributeError:
                row_h, max_line_w = 10, available_width + 1  # keep trying
            result = (font, row_h)
            if (needed_rows * row_h <= available_height
                    and max_line_w <= available_width) or i == len(candidates) - 1:
                break
        return result

    @staticmethod
    def _build_goal_card_rows(goal: Dict) -> Dict[str, List[str]]:
        """Assemble the card's rows as {row_key: [segment, ...]}.

        Everything past the scorer's name is optional. The play alone yields a
        banner, a name and a season goal count; the athlete lookup adds the
        rest. A field ESPN did not send is absent rather than drawn as an
        empty label."""
        scorer = goal.get("scorer") or {}
        bio = goal.get("bio") or {}
        rows: Dict[str, List[str]] = {}

        header = [f"{goal.get('team_abbr') or ''} GOAL".strip()]
        when = " ".join(p for p in (goal.get("period"), goal.get("clock")) if p)
        if when:
            header.append(when)
        if goal.get("strength"):
            header.append(goal["strength"])
        rows["header"] = header
        # Both spellings, longest first. The renderer picks the longest that
        # fits rather than hard-cutting: ESPN hands us "J. Brodzinski"
        # alongside "Jonny Brodzinski", and the abbreviation is a far better
        # narrow-panel answer than "Jonny Brodzinsk".
        full_name = bio.get("display_name") or scorer.get("name") or "Scorer"
        short_name = scorer.get("short_name") or ""
        rows["name"] = [full_name]
        if short_name and short_name != full_name:
            rows["name"].append(short_name)

        jersey = bio.get("jersey")
        position = bio.get("position") or ""
        team_line = [p for p in (f"#{jersey}" if jersey else "", position) if p]
        if team_line:
            rows["team"] = team_line

        stats = [f"{label} {value}" for label, value in (bio.get("stat_pairs") or [])[:4]]
        if not stats and scorer.get("season_goals") is not None:
            # No bio yet: the play still knows how many the scorer has.
            stats = [f"G {scorer['season_goals']}"]
        if stats:
            rows["stats"] = stats

        assists = [a.get("short_name") or a.get("name") for a in goal.get("assists") or []]
        assists = [a for a in assists if a]
        if assists:
            # "A:" rather than "Assists:" -- the row is usually the widest
            # after the stat line and the abbreviation is universal in hockey.
            rows["assists"] = [f"A: {assists[0]}"] + assists[1:]

        vitals = []
        if bio.get("age"):
            vitals.append(f"Age {bio['age']}")
        for key in ("height", "weight"):
            if bio.get(key):
                vitals.append(str(bio[key]))
        if vitals:
            rows["vitals"] = vitals

        if bio.get("birthplace"):
            rows["hometown"] = [str(bio["birthplace"])]
        return rows

    def _maybe_draw_goal_card(self, game: Dict, force_clear: bool = False) -> bool:
        """Draw the goal-scorer card if one is armed, due, and for this game.

        Returns True when it drew, so the caller skips the scorebug for this
        frame. The card replaces the scorebug rather than overlaying it --
        there is no room on a hockey scorebug for a face and five rows of
        text."""
        if not self.show_goal_scorer:
            return False
        card = self._goal_card
        if not card:
            return False
        if str(game.get("id") or "") != card.get("game_id"):
            return False
        now = time.time()
        if now < card.get("show_from", 0):
            return False  # celebration still owns the panel
        if now >= card.get("show_until", 0):
            self._goal_card = None
            return False
        self._draw_goal_card(card, force_clear)
        return True

    def _draw_goal_card(self, goal: Dict, force_clear: bool = False) -> None:
        """Draw the goal-scorer card: headshot on the left, then a team-colour
        "<TEAM> GOAL" banner with the period, clock and strength, the scorer's
        name, number and position, their season line, the assists, and their
        age/height/weight and hometown.

        Rows are priority-ordered rather than tiered by a hardcoded panel
        table: the font ladder is asked to fit them all, and when it cannot,
        the next row in _GOAL_CARD_DROP_ORDER is given up and the ladder asked
        again. A 128x32 keeps the banner, the name and a stat or two; a 256x64
        carries the lot."""
        try:
            w, h = self.display_width, self.display_height
            img = Image.new("RGB", (w, h), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            cfg = self._goal_card_cfg()
            text_color = tuple(cfg.get("text_color", [255, 255, 255]))
            stat_color = tuple(cfg.get("stat_color", [0, 220, 255]))
            detail_color = tuple(cfg.get("detail_color", [170, 170, 170]))
            accent = tuple(cfg.get("accent_color", [255, 200, 0]))
            if cfg.get("use_team_colors", True) and goal.get("team_color"):
                accent = tuple(goal["team_color"])

            rows = self._build_goal_card_rows(goal)
            if not cfg.get("show_stats", True):
                rows.pop("stats", None)
            if not cfg.get("show_assists", True):
                rows.pop("assists", None)
            if not cfg.get("show_bio_details", True):
                for key in ("vitals", "hometown"):
                    rows.pop(key, None)

            colors = {
                "header": accent,
                # The name stays white: team colours are legible but a dark
                # navy still reads poorly at the size a name is drawn, and the
                # banner directly above already carries the team's colour.
                "name": text_color,
                "team": accent,
                "stats": stat_color,
                "assists": text_color,
                "vitals": detail_color,
                "hometown": detail_color,
            }

            margin = 1
            headshot = None
            if cfg.get("show_headshot", True) and w >= 96 and h >= 32:
                size = min(max(24, h - 2 * (margin + 2)), h - 2 * (margin + 1), w // 3)
                mgr = self._get_headshot_manager()
                if mgr is not None and self.espn_summary_sport_league:
                    _, league = self.espn_summary_sport_league
                    scorer = goal.get("scorer") or {}
                    # Cache-only on the render path: the resolve thread warmed
                    # the disk copy, so a miss draws text-only rather than
                    # blocking the panel on a download.
                    headshot = mgr.load_headshot(
                        str(scorer.get("id") or ""),
                        (goal.get("bio") or {}).get("headshot_url")
                        or scorer.get("headshot_url"),
                        league=league, max_size=size, allow_download=False,
                    )

            if headshot is not None:
                hx, hy = margin + 1, (h - headshot.height) // 2
                draw.rectangle(
                    [hx - 1, hy - 1, hx + headshot.width, hy + headshot.height],
                    outline=accent,
                )
                img.paste(headshot, (hx, hy), headshot)
                text_x = hx + headshot.width + 4
            else:
                text_x = margin + 1

            # Reserve the margin plus 1px for the outline _draw_text_with_outline
            # paints beyond the glyph on every side.
            avail_w = max(8, w - text_x - margin - 2)
            avail_h = h - 2 * margin

            font_cfg = dict(cfg)
            font_cfg.setdefault("font", "9x15.bdf")
            font_size_cap = font_cfg.get("font_size", 24)
            separators = {"team": " "}

            keys = [k for k in self._GOAL_CARD_ROW_ORDER if rows.get(k)]
            texts = {
                k: (rows[k][-1] if k == "name"
                    else separators.get(k, "  ").join(rows[k]))
                for k in keys
            }
            droppable = [k for k in self._GOAL_CARD_DROP_ORDER if k in keys]
            font, row_h = None, 0
            while keys:
                font_cfg["font_size"] = max(
                    6, min(font_size_cap, round(avail_h / len(keys) - 3))
                )
                font, row_h = self._load_multiline_fit_font(
                    font_cfg, [texts[k] for k in keys], avail_w, avail_h
                )
                if row_h * len(keys) <= avail_h or not droppable:
                    break
                keys.remove(droppable.pop(0))
            if font is None:
                return

            header_bar = (
                cfg.get("header_bar", True) and "header" in keys
                and h >= 48 and row_h >= 8
            )

            y = max(margin, (h - row_h * len(keys)) // 2)
            for key in keys:
                if y >= h:
                    break
                if key == "name":
                    # Alternatives, not segments: take the longest spelling
                    # that fits, falling back to truncating the shortest.
                    text = rows[key][-1]
                    for candidate in rows[key]:
                        if draw.textbbox((0, 0), candidate, font=font)[2] <= avail_w:
                            text = candidate
                            break
                else:
                    text = self._fit_segments(
                        draw, rows[key], font, avail_w, separators.get(key, "  ")
                    )
                text = self._truncate_to_width(draw, text, font, avail_w)
                if key == "header" and header_bar:
                    # Knocked-out banner: team colour behind, glyphs in
                    # whichever of black/white reads against it. Drawn flat --
                    # _draw_text_with_outline's black outline would smear a
                    # knocked-out glyph.
                    draw.rectangle(
                        [text_x - 1, y, text_x + avail_w, min(h - 1, y + row_h - 2)],
                        fill=accent,
                    )
                    draw.fontmode = "1"
                    draw.text((text_x + 1, y), text, font=font,
                              fill=self._readable_on(accent))
                else:
                    self._draw_text_with_outline(
                        draw, text, (text_x, y), font, fill=colors[key]
                    )
                y += row_h

            self.display_manager.image.paste(img, (0, 0))
            self.display_manager.update_display()
        except Exception as e:
            self.logger.error(f"Error drawing goal-scorer card: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Game-activity pop-ups
    #
    # A one-line banner along the bottom of the live scorebug for the plays
    # between goals -- "A. Matthews SHOT ON GOAL!  2nd 12:34" -- so a 0-0 game
    # still shows something happening. The scoreboard feed carries none of
    # this, so it is the same per-game summary the goal card reads, polled
    # for the game on screen at the live update interval. Fetched in update()
    # and off-thread; the render path only reads the queue.
    # ------------------------------------------------------------------

    def _activity_cfg(self) -> Dict:
        return self.config.get("customization", {}).get("game_activity", {})

    def _poll_game_activity(self) -> None:
        """Start a summary fetch for the game on screen, at most once per
        live update interval and never two at once.

        Only while the scorebug is actually being drawn where a pop-up can
        show. update() runs whether or not hockey is on screen, and in scroll
        mode or on a panel too short for the banner it would be spending a
        request per interval on pop-ups nobody sees. Pausing also forgets
        where each feed was up to, so coming back starts from a fresh baseline
        rather than replaying the gap as a run of stale pop-ups."""
        game = self.current_game
        if not game or not game.get("id") or self._activity_inflight:
            return
        now = time.time()
        interval = max(_ACTIVITY_MIN_POLL_SECONDS, float(self.update_interval or 0))
        if now - self._activity_drawn_at > 2 * interval:
            self._activity_seen.clear()
            self._activity_queue.clear()
            return
        if now - self._activity_last_poll < interval:
            return
        self._activity_last_poll = now
        self._activity_inflight = True
        live_ids = {str(g.get("id")) for g in (self.live_games or [])}
        for game_id in [k for k in self._activity_seen if k not in live_ids]:
            self._activity_seen.pop(game_id, None)

        import threading

        try:
            threading.Thread(
                target=self._fetch_game_activity, args=(dict(game),), daemon=True
            ).start()
        except RuntimeError as e:  # no thread, no fetch: never a stuck flag
            self._activity_inflight = False
            self.logger.debug(f"Game activity poll not started: {e}")

    def _fetch_game_activity(self, game: Dict) -> None:
        try:
            sport, league = self.espn_summary_sport_league
            summary = self.data_source.fetch_game_summary(sport, league, str(game["id"]))
            if summary:
                self._queue_game_activity(game, summary.get("plays") or [])
        except Exception as e:
            self.logger.debug(f"Game activity poll failed for {game.get('id')}: {e}")
        finally:
            self._activity_inflight = False

    def _queue_game_activity(self, game: Dict, plays: List[Dict]) -> None:
        """Queue a pop-up for each wanted play since this game's last poll.

        The first poll of a game only records where the feed is up to: a game
        joined mid-period would otherwise replay every shot it has had. So
        does a poll that cannot find the last play it saw, since ESPN has
        rewritten the feed and there is no telling which plays are new."""
        game_id = str(game.get("id"))
        ids = [str(p.get("id", "") or "") for p in plays]
        last = self._activity_seen.get(game_id)
        self._activity_seen[game_id] = ids[-1] if ids and ids[-1] else None
        if not last or last not in ids:
            return
        wanted = self._activity_cfg().get("event_types", DEFAULT_ACTIVITY_KINDS)
        wanted = {wanted} if isinstance(wanted, str) else set(wanted or ())
        sides = {str(game.get("home_id")): "home", str(game.get("away_id")): "away"}
        for play in plays[ids.index(last) + 1:]:
            activity = _extract_activity(play)
            if activity is None or activity["kind"] not in wanted:
                continue
            side = sides.get(activity["team_id"])
            activity["game_id"] = game_id
            activity["team_abbr"] = game.get(f"{side}_abbr", "") if side else ""
            activity["team_color"] = game.get(f"{side}_team_color") if side else None
            self._activity_queue.append(activity)

    def _current_activity_popup(self, game: Dict, dwell: float) -> Optional[Dict]:
        """The pop-up to draw over this game right now, if any. Pop-ups queued
        for a game the rotation has left are dropped rather than shown late
        over a different game."""
        game_id = str(game.get("id") or "")
        now = time.time()
        popup = self._activity_popup
        if popup and popup["game_id"] == game_id and now - popup["shown_at"] < dwell:
            return popup
        self._activity_popup = None
        while self._activity_queue:
            candidate = self._activity_queue.popleft()
            if candidate["game_id"] == game_id:
                self._activity_popup = dict(candidate, shown_at=now)
                return self._activity_popup
        return None

    def _layout_activity_banner(self, draw, popup: Dict, cfg: Dict,
                                width: int, max_row_h: int) -> Optional[Dict]:
        """Font and text for the banner: the fullest wording that fits the
        width, in the largest ladder font whose row fits max_row_h.

        Wording beats size -- a smaller font is tried before any word is
        given up. Then, in order: the initial ("A. Matthews" -> "Matthews"),
        the long label, the period ordinal, and last of all the clock, which
        is what says how long ago the play was. A line too wide even then is
        cut rather than drawn past the edge."""
        names = popup.get("names") or [popup.get("team_abbr") or ""]
        labels = _ACTIVITY_LABELS.get(popup["kind"], ("",))
        stamps = [s for s in (
            f"{popup.get('period', '')} {popup.get('clock', '')}".strip(),
            popup.get("clock", ""),
        ) if s]
        stamps = list(dict.fromkeys(stamps)) + [""]
        avail = width - 2
        fonts = []
        for font_name in self._GOAL_CARD_FONT_LADDER:
            font = self._load_custom_font_from_element_config(
                {"font": font_name}, default_size=8
            )
            box = font.getbbox("Ay")
            row_h = box[3] - box[1] + 2
            if row_h <= max_row_h:
                fonts.append((font, row_h))
        if not fonts:
            return None
        for stamp in stamps:
            for label in labels:
                for name in names:
                    for font, row_h in fonts:
                        text = f"{name} {label}".strip()
                        gap = draw.textlength("  ", font=font) if stamp else 0
                        total = (draw.textlength(text, font=font) + gap
                                 + draw.textlength(stamp, font=font))
                        if total <= avail:
                            return {"font": font, "row_h": row_h, "name": name,
                                    "label": label, "stamp": stamp}
        font, row_h = fonts[-1]
        return {"font": font, "row_h": row_h,
                "name": self._truncate_to_width(draw, names[-1], font, avail),
                "label": "", "stamp": ""}

    def _with_activity_popup(self, img: Image.Image, game: Dict) -> Image.Image:
        """The scorebug with the current pop-up banner over its bottom row.

        Each frame is a finished screen: the banner holds at full strength,
        then its text dims to black over fade_seconds, and the scorebug's own
        bottom row returns once it has gone. The text fades rather than the
        banner cross-fading into the scorebug, because a cross-fade shows the
        shot line through the pop-up -- two lines of text on top of each
        other. A ramp, so at the 1 FPS a switch-mode board is drawn at it
        steps down evenly instead of flickering."""
        if not getattr(self, "show_game_activity", False):
            return img
        width, height = img.size
        if height < _ACTIVITY_MIN_HEIGHT:
            return img
        self._activity_drawn_at = time.time()
        try:
            cfg = self._activity_cfg()
            dwell = max(1.0, float(cfg.get("dwell_seconds", 6)))
            fade = min(max(0.0, float(cfg.get("fade_seconds", 3))), dwell)
            popup = self._current_activity_popup(game, dwell)
            if popup is None:
                return img
            left = dwell - (time.time() - popup["shown_at"])
            strength = 1.0 if fade <= 0 or left >= fade else max(0.0, left / fade)
            if strength <= 0:
                return img

            # Drawn on a copy, so a failure part-way leaves the scorebug whole.
            out = img.copy()
            draw = ImageDraw.Draw(out)
            layout = popup.get("_layout")
            if layout is None or layout.get("size") != (width, height):
                layout = self._layout_activity_banner(
                    draw, popup, cfg, width, max(9, height // 6)
                )
                if layout is None:
                    return img
                layout["size"] = (width, height)
                popup["_layout"] = layout

            font, row_h = layout["font"], layout["row_h"]
            text_color = tuple(cfg.get("text_color", [255, 255, 255]))
            time_color = tuple(cfg.get("time_color", [170, 170, 170]))
            label_color = tuple(cfg.get("accent_color", [255, 200, 0]))
            if cfg.get("use_team_colors", True) and popup.get("team_color"):
                label_color = tuple(popup["team_color"])

            def faded(color):
                return tuple(int(round(c * strength)) for c in color[:3])

            name = layout["name"]
            label = f" {layout['label']}" if layout["label"] else ""
            stamp = f"  {layout['stamp']}" if layout["stamp"] else ""
            segments = [(name, text_color), (label, label_color), (stamp, time_color)]

            top = height - row_h
            draw.rectangle([0, top, width - 1, height - 1], fill=(0, 0, 0))
            draw.fontmode = "1"
            total = sum(draw.textlength(t, font=font) for t, _ in segments)
            x = max(1, int((width - total) // 2))
            y = top + 1 - font.getbbox("Ay")[1]
            for text, color in segments:
                if text:
                    draw.text((x, y), text, font=font, fill=faded(color))
                    x += int(round(draw.textlength(text, font=font)))
            return out
        except Exception as e:
            self.logger.debug(f"Game activity pop-up skipped: {e}")
            return img

    def _draw_scorebug_layout(self, game: Dict, force_clear: bool = False) -> None:
        """Draw the detailed scorebug layout for a live Hockey game."""
        if self._maybe_draw_goal_card(game, force_clear):
            return
        try:
            main_img = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 255)
            )
            overlay = Image.new(
                "RGBA", (self.display_width, self.display_height), (0, 0, 0, 0)
            )
            draw_overlay = ImageDraw.Draw(
                overlay
            )  # Draw text elements on overlay first
            home_logo = self._load_and_resize_logo(
                game["home_id"],
                game["home_abbr"],
                game["home_logo_path"],
                game.get("home_logo_url"),
            )
            away_logo = self._load_and_resize_logo(
                game["away_id"],
                game["away_abbr"],
                game["away_logo_path"],
                game.get("away_logo_url"),
            )

            if not home_logo or not away_logo:
                self.logger.error(
                    f"Failed to load logos for live game: {game.get('id')}"
                )
                # Draw placeholder text if logos fail, on the image that gets
                # pasted: drawing on a throwaway .convert("RGB") copy and
                # pasting main_img left a black panel.
                error_img = main_img.convert("RGB")
                draw_final = ImageDraw.Draw(error_img)
                self._draw_text_with_outline(
                    draw_final, "Logo Error", (5, 5), self.fonts["status"]
                )
                self.display_manager.image.paste(error_img, (0, 0))
                self.display_manager.update_display()
                return

            center_y = self.display_height // 2

            # Draw logos (shifted slightly more inward than NHL perhaps) with layout offsets
            home_x = (
                self.display_width - home_logo.width + 10 + self._get_layout_offset('home_logo', 'x_offset')
            )  # adjusted from 18 # Adjust position as needed
            home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
            main_img.paste(home_logo, (home_x, home_y), home_logo)

            away_x = -10 + self._get_layout_offset('away_logo', 'x_offset')  # adjusted from 18 # Adjust position as needed
            away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
            main_img.paste(away_logo, (away_x, away_y), away_logo)

            # --- Draw Text Elements on Overlay ---
            # Note: Rankings are now handled in the records/rankings section below

            # Period/Quarter and Clock (Top center)
            period_clock_text = (
                f"{game.get('period_text', '')} {game.get('clock', '')}".strip()
            )
            if game.get("is_period_break"):
                period_clock_text = game.get("status_text", "Period Break")

            status_width = draw_overlay.textlength(
                period_clock_text, font=self.fonts["time"]
            )
            status_x = (self.display_width - status_width) // 2 + self._get_layout_offset('status_text', 'x_offset')
            status_y = 1 + self._get_layout_offset('status_text', 'y_offset')  # Position at top

            # Scores (centered, slightly above bottom) with layout offsets
            home_score = str(game.get("home_score", "0"))
            away_score = str(game.get("away_score", "0"))
            score_text = f"{away_score}-{home_score}"
            score_width = draw_overlay.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2 + self._get_layout_offset('score', 'x_offset')
            score_y = (
                self.display_height // 2
            ) - 3 + self._get_layout_offset('score', 'y_offset')  # centered #from 14 # Position score higher

            # Power play (show_powerplay): "PP" between the clock and the
            # score where those rows can hold it, else the clock row itself
            # turns POWER_PLAY_COLOR (32-row panels have no free row).
            power_play = bool(self.show_powerplay and game.get("power_play"))
            pp_font = self.fonts.get("shots") or self.fonts.get("status") or ImageFont.load_default()
            pp_xy = None
            if power_play:
                pp_xy = power_play_slot(
                    draw_overlay, self.display_width,
                    period_clock_text, (status_x, status_y), self.fonts["time"],
                    score_text, (score_x, score_y), self.fonts["score"], pp_font,
                )

            self._draw_text_with_outline(
                draw_overlay,
                period_clock_text,
                (status_x, status_y),
                self.fonts["time"],
                **({"fill": POWER_PLAY_COLOR} if power_play and pp_xy is None else {}),
            )
            self._draw_text_with_outline(
                draw_overlay, score_text, (score_x, score_y), self.fonts["score"]
            )
            if pp_xy is not None:
                self._draw_text_with_outline(
                    draw_overlay, "PP", pp_xy, pp_font, fill=POWER_PLAY_COLOR
                )

            # Shots on Goal
            if self.show_shots_on_goal:
                shots_font = self.fonts.get("shots") or self.fonts.get("record") or ImageFont.load_default()
                home_shots = str(game.get("home_shots", "0"))
                away_shots = str(game.get("away_shots", "0"))
                shots_text = f"{away_shots}   SHOTS   {home_shots}"
                shots_bbox = draw_overlay.textbbox((0, 0), shots_text, font=shots_font)
                shots_height = shots_bbox[3] - shots_bbox[1]
                shots_y = self.display_height - shots_height - 1
                shots_width = draw_overlay.textlength(shots_text, font=shots_font)
                shots_x = (self.display_width - shots_width) // 2
                self._draw_text_with_outline(
                    draw_overlay, shots_text, (shots_x, shots_y), shots_font
                )

            # Draw odds if available
            if "odds" in game and game["odds"]:
                self._draw_dynamic_odds(
                    draw_overlay, game["odds"], self.display_width, self.display_height,
                    top_span=self._top_row_span(
                        draw_overlay, period_clock_text, self.fonts["time"],
                        self.display_width,
                        self._get_layout_offset('status_text', 'x_offset')),
                )

            # Draw records or rankings if enabled
            if self.show_records or self.show_ranking:
                record_font = self.fonts.get("record") or self.fonts.get("status") or ImageFont.load_default()

                # Get team abbreviations
                away_abbr = game.get("away_abbr", "")
                home_abbr = game.get("home_abbr", "")

                record_bbox = draw_overlay.textbbox((0, 0), "0-0", font=record_font)
                record_height = record_bbox[3] - record_bbox[1]
                record_y = self.display_height - record_height - 1
                self.logger.debug(
                    f"Record positioning: height={record_height}, record_y={record_y}, display_height={self.display_height}"
                )

                # Display away team info
                if away_abbr:
                    if self.show_ranking and self.show_records:
                        # When both rankings and records are enabled, rankings replace records completely
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            # Show nothing for unranked teams when rankings are prioritized
                            away_text = ""
                    elif self.show_ranking:
                        # Show ranking only if available
                        away_rank = self._team_rankings_cache.get(away_abbr, 0)
                        if away_rank > 0:
                            away_text = f"#{away_rank}"
                        else:
                            away_text = ""
                    elif self.show_records:
                        # Show record only when rankings are disabled
                        away_text = game.get("away_record", "")
                    else:
                        away_text = ""

                    if away_text:
                        away_record_x = 3
                        self.logger.debug(
                            f"Drawing away ranking '{away_text}' at ({away_record_x}, {record_y}) with font size {record_font.size if hasattr(record_font, 'size') else 'unknown'}"
                        )
                        self._draw_text_with_outline(
                            draw_overlay,
                            away_text,
                            (away_record_x, record_y),
                            record_font,
                        )

                # Display home team info
                if home_abbr:
                    if self.show_ranking and self.show_records:
                        # When both rankings and records are enabled, rankings replace records completely
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            # Show nothing for unranked teams when rankings are prioritized
                            home_text = ""
                    elif self.show_ranking:
                        # Show ranking only if available
                        home_rank = self._team_rankings_cache.get(home_abbr, 0)
                        if home_rank > 0:
                            home_text = f"#{home_rank}"
                        else:
                            home_text = ""
                    elif self.show_records:
                        # Show record only when rankings are disabled
                        home_text = game.get("home_record", "")
                    else:
                        home_text = ""

                    if home_text:
                        home_record_bbox = draw_overlay.textbbox(
                            (0, 0), home_text, font=record_font
                        )
                        home_record_width = home_record_bbox[2] - home_record_bbox[0]
                        home_record_x = self.display_width - home_record_width - 3
                        self.logger.debug(
                            f"Drawing home ranking '{home_text}' at ({home_record_x}, {record_y}) with font size {record_font.size if hasattr(record_font, 'size') else 'unknown'}"
                        )
                        self._draw_text_with_outline(
                            draw_overlay,
                            home_text,
                            (home_record_x, record_y),
                            record_font,
                        )

            # Composite the text overlay onto the main image
            main_img = Image.alpha_composite(main_img, overlay)
            main_img = main_img.convert("RGB")  # Convert for display
            main_img = self._with_activity_popup(main_img, game)

            # Display the final image
            self.display_manager.image.paste(main_img, (0, 0))
            self.display_manager.update_display()  # Update display here for live

        except Exception as e:
            self.logger.error(
                f"Error displaying live Hockey game: {e}", exc_info=True
            )

