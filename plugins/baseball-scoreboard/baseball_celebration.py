"""Run and home-run celebrations for the baseball scoreboards.

Core draws the takeover (``src.common.sports_celebration``): a gradient in the
scoring team's colours, confetti, the headline and the score with the scoring
side's digits breathing. This module is what is baseball's own:

* what counts -- every run a celebratable team scores, told apart as a plain
  RUN or a HOME RUN (2-RUN, 3-RUN, GRAND SLAM by how many it drove in), and a
  WIN when a favourite's game goes final;
* the scenery -- a ball diamond for a run and a ball clearing the outfield wall
  for a home run, both painted into the backdrop core caches;
* the motion -- a runner who circles the diamond on a run, fireworks over the
  wall on a home run. Every frame is a function of elapsed time only, so a 1 FPS
  board that samples one frame a second still sees a finished picture.

A plain run and a home run are told apart from ESPN's play-by-play: the score
changing says a run came in, the summary's most recent scoring play says how.
When the feed has no plays (MiLB, or a summary that has not caught up yet) the
run is celebrated as a run rather than guessed at.
"""

import math
import queue
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from src.common.sports_celebration import (
    SportsCelebrationMixin, mix_color, scale_color)

#: How long a run's celebration waits on ESPN's play list before settling for
#: "a run". The update thread pays this once per scoring event, never per poll.
SUMMARY_TIMEOUT_SECONDS = 2.0


def is_home_run_play(play: Dict) -> bool:
    """Whether one ESPN play is a home run (inside-the-park included)."""
    play_type = str((play.get("type") or {}).get("type") or "").lower()
    if play_type == "home-run":
        return True
    text = str(play.get("text") or "").lower()
    return "homered" in text or "home run" in text


def _play_score(play: Dict) -> Optional[Tuple[int, int]]:
    """(away, home) after a play, when ESPN says so."""
    try:
        return int(play["awayScore"]), int(play["homeScore"])
    except (KeyError, TypeError, ValueError):
        return None


def latest_scoring_play(plays: Optional[List[Dict]],
                        score: Optional[Tuple[int, int]] = None) -> Optional[Dict]:
    """The newest play flagged as scoring, or None.

    With ``score`` (the game's current away, home) a play that says what the
    score was after it must agree: the scoreboard can be a poll ahead of the
    summary, and then the newest scoring play is the *previous* run -- better
    unknown than somebody else's home run.
    """
    for play in reversed(plays or []):
        if play.get("scoringPlay"):
            after = _play_score(play)
            if score is not None and after is not None and after != tuple(score):
                return None
            return play
    return None


def home_run_in_plays(plays: Optional[List[Dict]],
                      score: Optional[Tuple[int, int]] = None) -> Optional[bool]:
    """Whether the most recent scoring play was a home run, None if unknown.

    A feed that carries no scoring flag falls back to the last substantive
    play, which is the play that put the run on the board whenever the summary
    is current.
    """
    if not plays:
        return None
    if any(play.get("scoringPlay") for play in plays):
        play = latest_scoring_play(plays, score)
        return None if play is None else is_home_run_play(play)
    for play in reversed(plays):
        if (play.get("type") or {}).get("type") or play.get("text"):
            return is_home_run_play(play)
    return None


def celebration_phrase(kind: str, abbr: str, runs: int, pick=secrets.choice) -> str:
    """The headline. ``pick`` is injectable so a test can pin the choice."""
    abbr = abbr or ""
    if kind == "win":
        return f"{abbr} WINS!"
    if kind == "homerun":
        if runs >= 4:
            return "GRAND SLAM!"
        if runs >= 2:
            return f"{runs}-RUN HOMER!"
        return pick(("HOME RUN!", f"{abbr} HOMER!"))
    if runs >= 2:
        return f"{abbr} +{runs}!"
    return pick(("RUN SCORES!", f"{abbr} SCORES!"))


def diamond_points(width: int, height: int) -> Dict[str, Tuple[float, float]]:
    """Home, first, second and third, centred between the headline and score."""
    cx, cy = width / 2.0, height * 0.52
    reach = max(5.0, min(height * 0.36, width * 0.2))
    return {
        "home": (cx, cy + reach),
        "first": (cx + reach, cy),
        "second": (cx, cy - reach),
        "third": (cx - reach, cy),
    }


class _HeldFrame:
    """Stands in for display_manager while core draws the takeover, holding the
    finished frame instead of presenting it, so this module can lay its own
    effects on before anything reaches the panel. Everything else passes
    through."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "frame", None)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)

    def __setattr__(self, name, value):
        if name == "image":
            object.__setattr__(self, "frame", value)
        else:
            setattr(object.__getattribute__(self, "_real"), name, value)

    def update_display(self, *args, **kwargs):
        return None


def _fade(progress: float, settle: float) -> float:
    """1.0 until the celebration starts easing back, then down to 0."""
    if progress <= settle:
        return 1.0
    return max(0.0, 1.0 - (progress - settle) / (1.0 - settle))


class BaseballCelebrationMixin(SportsCelebrationMixin):
    """Arms, scores and draws baseball's run / home-run / win celebrations.

    Mixed into ``BaseballLive`` ahead of the mode classes. The host provides
    ``mode_config``, ``favorite_teams``, ``live_games``, ``logger``,
    ``data_source`` and ``espn_summary_sport_league`` like any live manager.
    """

    # ------------------------------------------------------------------
    # Settings and state
    # ------------------------------------------------------------------

    def _init_celebration(self) -> None:
        cfg = self.mode_config
        self.celebration_enabled = cfg.get("celebration_enabled", True)
        self.celebration_duration = cfg.get("celebration_duration", 8)
        self.celebrate_opponent_runs = cfg.get("celebrate_opponent_runs", False)
        self.celebration_home_runs_only = cfg.get("celebration_home_runs_only", False)
        self.celebration_team_colors = cfg.get("celebration_team_colors", True)
        self.celebration_confetti = cfg.get("celebration_confetti", True)
        # {game_id: {"away": int, "home": int}}: the last score seen live.
        self._score_baselines: Dict[str, Dict[str, int]] = {}
        # A snapshot, so a win survives its game leaving live_games.
        self.active_celebration: Optional[Dict[str, Any]] = None

    @staticmethod
    def _score_to_int(score) -> Optional[int]:
        try:
            if score is None:
                return None
            if isinstance(score, dict):
                return int(float(score.get("value", score.get("displayValue", 0))))
            text = str(score).strip()
            return int(float(text)) if text else None
        except (ValueError, TypeError):
            return None

    def _is_favorite(self, abbr: Optional[str]) -> bool:
        return bool(self.favorite_teams) and abbr in self.favorite_teams

    def _should_celebrate_for(self, abbr: Optional[str]) -> bool:
        """Whether a run by ``abbr`` earns a takeover."""
        if self._is_favorite(abbr) or not self.favorite_teams:
            # No favourites: the user chose to show this game, so celebrate it.
            return True
        return bool(self.celebrate_opponent_runs)

    def has_active_celebration(self) -> bool:
        celebration = self.active_celebration
        return bool(celebration) and (
            time.time() - celebration["started_at"] < self.celebration_duration)

    # ------------------------------------------------------------------
    # Telling a run from a home run
    # ------------------------------------------------------------------

    #: A summary fetched for one scoring event is reused for this long, so the
    #: celebration and the scorer card cost one request between them.
    _SUMMARY_REUSE_SECONDS = 15.0

    def _fetch_summary(self, game_id: str,
                       timeout: float = SUMMARY_TIMEOUT_SECONDS) -> Optional[Dict]:
        """ESPN's game summary (plays and rosters), or None. Bounded, never
        raises, and shared between callers for a few seconds. The update thread
        waits ``timeout`` seconds; a caller already off-thread can wait longer."""
        cache = self.__dict__.setdefault("_summary_cache", {})
        hit = cache.get(game_id)
        if hit and time.time() - hit[0] < self._SUMMARY_REUSE_SECONDS:
            return hit[1]
        pair = getattr(self, "espn_summary_sport_league", None)
        source = getattr(self, "data_source", None)
        if not pair or source is None:
            return None
        sport, league = pair
        results: "queue.Queue" = queue.Queue()

        def fetch():
            try:
                results.put(source.fetch_game_summary(sport, league, game_id))
            except Exception as e:  # noqa: BLE001 - a feed error is "unknown"
                results.put(e)

        threading.Thread(target=fetch, daemon=True).start()
        try:
            data = results.get(timeout=timeout)
        except queue.Empty:
            return None
        if not isinstance(data, dict):
            return None
        cache[game_id] = (time.time(), data)
        for stale in [k for k, v in cache.items() if time.time() - v[0] > 120]:
            cache.pop(stale, None)
        return data

    def _fetch_summary_plays(self, game_id: str) -> Optional[List[Dict]]:
        """ESPN's play list for one game, or None."""
        data = self._fetch_summary(game_id)
        return (data or {}).get("plays") or None

    def _scoring_was_home_run(self, game: Dict) -> bool:
        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        score = (away, home) if away is not None and home is not None else None
        verdict = home_run_in_plays(self._fetch_summary_plays(str(game.get("id"))), score)
        if verdict is None:
            # No plays to read: the last play the at-bat screens already hold.
            cached = (getattr(self, "_play_by_play_cache", {}) or {}).get(game.get("id"))
            verdict = bool(cached) and cached.get("last_play_code") == "HR"
        return bool(verdict)

    # ------------------------------------------------------------------
    # Arming
    # ------------------------------------------------------------------

    def _start_celebration(self, game: Dict, kind: str, scored_side: str,
                           team_abbr: str, away_score: int, home_score: int,
                           runs: int = 1,
                           before: Optional[Tuple[int, int]] = None) -> None:
        self.active_celebration = {
            "kind": kind,
            # "run" and "homerun" are painted by _draw_celebration_motif below;
            # a win keeps core's sunburst.
            "motif": "win" if kind == "win" else kind,
            "game": dict(game),
            "scored_side": scored_side,
            "team_abbr": team_abbr,
            "away_score": away_score,
            "home_score": home_score,
            "runs": runs,
            # The score the run was added to, so the card can tick it up.
            "before": before,
            "started_at": time.time(),
            "phrase": celebration_phrase(kind, team_abbr, runs),
        }
        # The scorebug resumes on the game that scored.
        self.current_game = dict(game)
        self.logger.info(
            f"Celebration ({kind}) armed: {self.active_celebration['phrase']} "
            f"[{game.get('away_abbr')} {away_score}-{home_score} {game.get('home_abbr')}]")

    def _check_for_score(self, game: Dict) -> None:
        """Arm a celebration when a celebratable team's run total goes up."""
        if not self.celebration_enabled:
            return
        game_id = game.get("id")
        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        if not game_id or away is None or home is None:
            return

        baseline = self._score_baselines.get(game_id)
        # Always re-base. A first sighting must never celebrate (a game in
        # progress at boot would false-fire), and a lower score -- a scoring
        # change after review -- re-bases silently.
        self._score_baselines[game_id] = {"away": away, "home": home}
        if baseline is None:
            return

        scored_side = None
        runs = 0
        for side, now_score in (("away", away), ("home", home)):
            gained = now_score - baseline[side]
            if gained > 0 and self._should_celebrate_for(game.get(f"{side}_abbr")):
                scored_side, runs = side, gained
                break
        if scored_side is None:
            return

        kind = "homerun" if self._scoring_was_home_run(game) else "run"
        if kind == "run" and self.celebration_home_runs_only:
            return
        self._start_celebration(
            game, kind, scored_side, game.get(f"{scored_side}_abbr", ""),
            away, home, runs, before=(baseline["away"], baseline["home"]))

    def _check_for_win(self, game: Dict) -> None:
        """A favourite wins a game this manager watched go live. Once per game."""
        if not self.celebration_enabled:
            return
        game_id = game.get("id")
        # A game first seen already final (the board started after the last
        # out) has no baseline and must not fire.
        if not game_id or game_id not in self._score_baselines:
            return
        self._score_baselines.pop(game_id, None)

        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        if away is None or home is None or away == home:
            return
        side = "away" if away > home else "home"
        abbr = game.get(f"{side}_abbr")
        # Wins need a favourite: every game ends, so "no favourites -> all"
        # would be noise.
        if not self._is_favorite(abbr):
            return
        self._start_celebration(game, "win", side, abbr, away, home)

    def _check_scores_of_live_games(self) -> None:
        """Run the score check over every included live game: a run is worth a
        takeover whichever game happens to be on screen."""
        for game in list(getattr(self, "live_games", None) or []):
            try:
                self._check_for_score(game)
            except Exception as e:  # noqa: BLE001 - never lose an update to this
                self.logger.debug(f"Celebration score check skipped: {e}")

    # ------------------------------------------------------------------
    # Showing it
    # ------------------------------------------------------------------

    def _celebration_display(self, force_clear: bool) -> bool:
        """Draw the takeover if one is running. True when it owns the panel."""
        celebration = self.active_celebration
        if not celebration:
            return False
        if time.time() - celebration["started_at"] < self.celebration_duration:
            try:
                self._draw_celebration_layout(celebration, force_clear)
                return True
            except Exception as e:  # noqa: BLE001
                self.logger.error(f"Error drawing celebration: {e}", exc_info=True)
                return False
        self.active_celebration = None
        # The scorebug resumes on the scoring game for a full turn.
        self.last_game_switch = time.time()
        return False

    # ------------------------------------------------------------------
    # Scenery
    # ------------------------------------------------------------------

    def _draw_celebration_motif(self, draw, motif: str, width: int, height: int,
                                palette) -> None:
        if motif == "run":
            self._paint_diamond(draw, width, height, palette)
        elif motif == "homerun":
            self._paint_outfield_wall(draw, width, height, palette)
        else:
            super()._draw_celebration_motif(draw, motif, width, height, palette)

    @staticmethod
    def _paint_diamond(draw, width: int, height: int, palette) -> None:
        """The base paths and bags. Brighter than core's scenery -- it is the
        picture, not texture -- but still behind the headline and the score."""
        path = tuple(mix_color(palette["glow"], palette["headline"], 0.45))
        pts = diamond_points(width, height)
        order = ("home", "first", "second", "third", "home")
        for a, b in zip(order, order[1:]):
            draw.line([pts[a], pts[b]], fill=path)
        bag = tuple(mix_color(palette["headline"], (255, 255, 255), 0.7))
        for name, (x, y) in pts.items():
            size = 1 if name != "home" else 2
            draw.rectangle([(int(x) - size + 1, int(y) - size + 1),
                            (int(x) + size - 1, int(y) + size - 1)], fill=bag)

    @staticmethod
    def _paint_outfield_wall(draw, width: int, height: int, palette) -> None:
        """The outfield wall: a padded rail along the bottom with its posts."""
        wall = tuple(mix_color(palette["glow"], palette["headline"], 0.55))
        wall_y = int(height * 0.90)
        draw.line([(0, wall_y), (width, wall_y)], fill=wall)
        if wall_y + 1 < height:
            draw.line([(0, wall_y + 1), (width, wall_y + 1)], fill=tuple(palette["glow"]))
        for x in range(2, width, 9):
            draw.line([(x, wall_y), (x, min(height - 1, wall_y + 2))], fill=wall)

    # ------------------------------------------------------------------
    # Impact: what makes the moment land
    #
    # Core draws the takeover and presents it in the same call, so the effects
    # are laid over the finished frame on its way to the panel (as hockey's goal
    # light is). Each is a function of elapsed time only, and a failure draws
    # the plain takeover.
    # ------------------------------------------------------------------

    #: The score ticks up this many seconds in; before it the old total shows.
    _TICK_AT = 0.9
    #: A home run shakes the panel for this long, decaying.
    _SHAKE_SECONDS = 0.8
    #: How long the "+N" floats up after the tick.
    _FLOAT_SECONDS = 1.4
    #: Seconds between sweeps of the shine across the headline.
    _SHINE_PERIOD = 1.7

    def _draw_celebration_layout(self, celebration: Dict, force_clear: bool = False) -> None:
        kind = celebration.get("kind")
        if kind not in ("run", "homerun"):
            return super()._draw_celebration_layout(celebration, force_clear)

        elapsed = max(0.0, time.time() - celebration["started_at"])
        before = celebration.get("before")
        shown = {k: celebration[k] for k in ("away_score", "home_score")}
        if before and elapsed < self._TICK_AT:
            # The old total, until the run lands.
            celebration["away_score"], celebration["home_score"] = before

        real = self.display_manager
        held = _HeldFrame(real)
        self.display_manager = held
        try:
            super()._draw_celebration_layout(celebration, force_clear)
        finally:
            self.display_manager = real
            celebration.update(shown)
        frame = held.frame
        if frame is None:
            return
        try:
            frame = self._celebration_impact(frame, celebration, elapsed)
        except Exception as e:  # noqa: BLE001 - never lose a takeover to an effect
            self.logger.debug(f"Celebration impact skipped: {e}")
        real.image = frame
        real.update_display()

    def _celebration_impact(self, frame, celebration: Dict, elapsed: float):
        """The effects that sit on top of core's frame."""
        width, height = frame.size
        kind = celebration["kind"]
        palette = self._celebration_palette(celebration)
        duration = max(float(getattr(self, "celebration_duration", 8) or 8), 0.5)
        fade = _fade(min(elapsed / duration, 1.0), self._CELEBRATION_SETTLE)
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # The bat cracks: a starburst at the plate on a home run's first beat.
        if kind == "homerun" and elapsed < 0.4:
            self._draw_crack(draw, width, height, elapsed / 0.4)

        # "+N" floating up from the score once the total has ticked.
        if celebration.get("before") and elapsed >= self._TICK_AT:
            self._draw_floating_gain(
                draw, overlay, celebration, palette, width, height,
                elapsed - self._TICK_AT, fade)

        frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")

        # A glint sweeping across the headline.
        frame = self._shine_headline(frame, palette, elapsed, fade)

        # A home run shakes the panel as it lands, settling to still.
        if kind == "homerun" and elapsed < self._SHAKE_SECONDS:
            amp = 2.0 * (1.0 - elapsed / self._SHAKE_SECONDS)
            dx = int(round(amp * math.sin(elapsed * 47.0)))
            dy = int(round(amp * math.cos(elapsed * 61.0)))
            if dx or dy:
                shaken = Image.new("RGB", frame.size, (0, 0, 0))
                shaken.paste(frame, (dx, dy))
                frame = shaken
        return frame

    @staticmethod
    def _draw_crack(draw, width: int, height: int, k: float) -> None:
        """Eight spokes bursting from the plate side, white fading to nothing."""
        cx, cy = width * 0.10, height * 0.78
        reach = 3.0 + min(width, height * 2) * 0.12 * k
        alpha = int(255 * (1.0 - k))
        for s in range(8):
            angle = math.pi * 2 * s / 8
            draw.line([(cx + math.cos(angle) * reach * 0.35,
                        cy + math.sin(angle) * reach * 0.35),
                       (cx + math.cos(angle) * reach, cy + math.sin(angle) * reach)],
                      fill=(255, 255, 255, alpha))

    def _draw_floating_gain(self, draw, overlay, celebration: Dict, palette,
                            width: int, height: int, since: float,
                            fade: float) -> None:
        """"+1" (or "+4") rising off the score and fading as it climbs."""
        if since > self._FLOAT_SECONDS:
            return
        k = since / self._FLOAT_SECONDS
        text = "+%d" % int(celebration.get("runs", 1))
        font = self.fonts.get("status") or self.fonts["time"]
        box = draw.textbbox((0, 0), text, font=font)
        score_y = height - 14
        y = score_y - 2 - (height * 0.32) * k
        x = (width - (box[2] - box[0])) // 2
        alpha = int(255 * (1.0 - k) ** 0.7 * max(fade, 0.0))
        if alpha <= 8:
            return
        colour = tuple(int(c) for c in mix_color(palette["headline"], (255, 255, 255), 0.4))
        # Drawn into a scratch layer so the outline and fill fade together.
        layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
        self._draw_text_with_outline(ImageDraw.Draw(layer), text, (int(x), int(y)),
                                     font, fill=colour)
        layer.putalpha(layer.getchannel("A").point(lambda a: a * alpha // 255))
        overlay.alpha_composite(layer)

    def _shine_headline(self, frame, palette, elapsed: float, fade: float):
        """A bright diagonal band sliding across the headline's lit pixels."""
        if elapsed < 0.3 or fade <= 0.05:
            return frame
        width, height = frame.size
        band_rows = min(height, max(9, height // 3))
        t = ((elapsed - 0.3) % self._SHINE_PERIOD) / self._SHINE_PERIOD
        if t > 0.6:
            return frame          # rests between sweeps
        centre = -6 + (width + 12) * (t / 0.6)
        pixels = frame.load()
        for y in range(band_rows):
            lean = centre + (band_rows - y) * 0.8      # a slanted band
            for x in range(max(0, int(lean) - 2), min(width, int(lean) + 3)):
                r, g, b = pixels[x, y]
                if max(r, g, b) < 150:
                    continue                           # text only, not the backdrop
                weight = 0.55 * fade * (1.0 - abs(x - lean) / 3.0)
                if weight > 0:
                    pixels[x, y] = (int(r + (255 - r) * weight),
                                    int(g + (255 - g) * weight),
                                    int(b + (255 - b) * weight))
        return frame

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------

    def _draw_celebration_confetti(self, draw, celebration: Dict, width: int,
                                   height: int, palette, elapsed: float,
                                   progress: float) -> None:
        """Core's confetti, plus this sport's moving part."""
        super()._draw_celebration_confetti(
            draw, celebration, width, height, palette, elapsed, progress)
        fade = _fade(progress, self._CELEBRATION_SETTLE)
        if fade <= 0.02:
            return
        try:
            kind = celebration.get("kind")
            if kind == "homerun":
                self._draw_fireworks(draw, width, height, palette, elapsed, fade,
                                     int(celebration.get("runs", 1)))
            elif kind == "run":
                self._draw_runner(draw, width, height, palette, elapsed, fade)
        except Exception as e:  # noqa: BLE001 - motion is never worth the takeover
            self.logger.debug(f"Celebration motion skipped: {e}")

    #: Seconds a runner takes to go round the bases.
    _RUNNER_LAP_SECONDS = 2.0
    #: Seconds between one shell's launches.
    _FIREWORK_PERIOD = 2.4
    #: Seconds the ball takes to cross the panel.
    _BALL_SECONDS = 1.8

    def _draw_runner(self, draw, width: int, height: int, palette, elapsed: float,
                     fade: float) -> None:
        """A runner circling the bases, with a fading trail behind."""
        pts = diamond_points(width, height)
        path = [pts["home"], pts["first"], pts["second"], pts["third"], pts["home"]]

        def at(lap: float) -> Tuple[float, float]:
            lap = lap % 1.0
            leg = min(int(lap * 4), 3)
            f = lap * 4 - leg
            (ax, ay), (bx, by) = path[leg], path[leg + 1]
            return ax + (bx - ax) * f, ay + (by - ay) * f

        lap = elapsed / self._RUNNER_LAP_SECONDS
        head = tuple(int(c) for c in mix_color(palette["headline"], (255, 255, 255), 0.6))
        for i in range(6, 0, -1):
            x, y = at(lap - i * 0.03)
            alpha = int(200 * fade * (1.0 - i / 7.0))
            draw.rectangle([(int(x), int(y)), (int(x) + 1, int(y) + 1)],
                           fill=tuple(int(c) for c in palette["headline"]) + (alpha,))
        x, y = at(lap)
        draw.rectangle([(int(x) - 1, int(y) - 1), (int(x) + 1, int(y) + 1)],
                       fill=head + (255,))

    def _draw_fireworks(self, draw, width: int, height: int, palette,
                        elapsed: float, fade: float, runs: int) -> None:
        """The ball leaving the park, and fireworks over the wall."""
        head = tuple(int(c) for c in mix_color(palette["headline"], (255, 255, 255), 0.7))

        # The ball: across the panel on a high arc, a trail behind it.
        def arc(t: float) -> Tuple[float, float]:
            return (width * (0.04 + 0.92 * t),
                    height * (0.84 - 0.78 * 4 * t * (1 - t) * (1 - 0.25 * t)))

        flight = (elapsed % self._BALL_SECONDS) / self._BALL_SECONDS
        for i in range(8, 0, -1):
            x, y = arc(max(0.0, flight - i * 0.018))
            alpha = int(190 * fade * (1.0 - i / 9.0))
            draw.point((int(x), int(y)), fill=head + (alpha,))
        x, y = arc(flight)
        draw.rectangle([(int(x) - 1, int(y) - 1), (int(x), int(y))], fill=head + (255,))

        # More runs, more shells (a grand slam fills the sky).
        shells = ((0.27, 0.40), (0.73, 0.36), (0.50, 0.30), (0.14, 0.30))[
            :max(2, min(4, 1 + runs))]
        colours = [palette["headline"], palette["accent"],
                   mix_color(palette["headline"], (255, 255, 255), 0.55)]
        reach = max(5.0, min(height * 0.46, width * 0.13))
        wall = height * 0.90
        for index, (fx, fy) in enumerate(shells):
            t = ((elapsed + index * 0.8) % self._FIREWORK_PERIOD) / self._FIREWORK_PERIOD
            cx, cy = fx * width, fy * height
            if t < 0.20:
                # Rising: a spark from the wall up to the burst point.
                y = wall + (cy - wall) * (t / 0.20)
                draw.rectangle([(int(cx), int(y)), (int(cx), int(y) + 1)],
                               fill=head + (int(230 * fade),))
                continue
            k = (t - 0.20) / 0.80
            radius = 1.0 + reach * (k ** 0.5)
            alpha = int(255 * fade * (1.0 - k) ** 0.7)
            if alpha <= 8:
                continue
            if k < 0.12:
                # The flash as it opens.
                draw.rectangle([(int(cx) - 1, int(cy) - 1), (int(cx) + 1, int(cy) + 1)],
                               fill=head + (alpha,))
            for s in range(12):
                angle = 2 * math.pi * s / 12 + index * 0.5
                colour = tuple(int(c) for c in colours[s % len(colours)])
                x = cx + math.cos(angle) * radius
                y = cy + math.sin(angle) * radius * 0.85
                draw.rectangle([(int(x), int(y)), (int(x) + 1, int(y) + 1)],
                               fill=colour + (alpha,))
                tx = cx + math.cos(angle) * radius * 0.7
                ty = cy + math.sin(angle) * radius * 0.7 * 0.85
                draw.point((int(tx), int(ty)), fill=colour + (alpha // 2,))
