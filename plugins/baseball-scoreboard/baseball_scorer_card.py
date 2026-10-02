"""The scorer card: who just drove the run in, drawn as a full-screen card.

Hockey's goal-scorer card is the model: a score going up arms it, a second
request finds out *who*, and the card follows the celebration as its second
beat (or appears straight away with the celebration off -- the two settings are
independent). The scoreboard feed never says who scored, so the card is built
from ESPN's play-by-play summary: the newest scoring play names the batter, the
roster gives the headshot and number, and the athlete endpoint (the one the
at-bat player card already uses) adds the season line.

For a home run the batter is the player who scored. For a run that came in on a
single, a walk, an error, a squeeze, the batter is the player who drove it in,
and the play text -- ESPN's own sentence, e.g. "Turner singled to center,
Harper scored" -- names the runner, so it is shown on the card rather than
guessed at.

Needs ESPN's summary, so MLB and NCAA Baseball only; MiLB's feed has no plays.
"""

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from baseball_celebration import (
    celebration_phrase, is_home_run_play, latest_scoring_play)

#: Re-reads of the summary while it catches up with the scoreboard.
SUMMARY_RETRIES = 3
SUMMARY_RETRY_SECONDS = 3.0

#: Rows given up first when the panel cannot hold them all, in order.
DROP_ORDER = ("play", "vitals", "stats")


def batter_id_of(play: Dict) -> Optional[str]:
    """The batter's athlete id on one ESPN play."""
    for participant in play.get("participants") or []:
        if participant.get("type") == "batter":
            athlete_id = str((participant.get("athlete") or {}).get("id") or "")
            if athlete_id:
                return athlete_id
    return None


def card_label(kind: str, runs: int) -> str:
    """The banner's wording: HOME RUN, 2-RUN HOMER, GRAND SLAM or RUN SCORES."""
    return celebration_phrase(kind, "", runs, pick=lambda options: options[0]).rstrip("!")


class BaseballScorerCardMixin:
    """Arms, resolves and draws the scorer card for a live baseball manager.

    The host provides what ``BaseballLive`` does: ``mode_config``, ``config``,
    ``favorite_teams``, ``live_games``, ``display_manager``, ``fonts``,
    ``logger``, ``espn_summary_sport_league``, ``_fetch_summary``,
    ``_fetch_player_bio`` and the bio and headshot caches.
    """

    def _init_scorer_card(self) -> None:
        cfg = self.mode_config
        self.show_scorer_card = bool(cfg.get("show_scorer_card", False))
        self.scorer_card_dwell = float(cfg.get("scorer_card_dwell_seconds", 6) or 6)
        self.scorer_card_favorites_only = bool(cfg.get("scorer_card_favorites_only", False))
        # The card keeps its own baselines, not the celebration's: that is
        # what makes the two settings independent.
        self._scorer_baselines: Dict[str, Dict[str, int]] = {}
        self._scorer_card: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Detecting and resolving
    # ------------------------------------------------------------------

    def _check_scorer_cards(self) -> None:
        """Run over every included live game: a run is worth a card whichever
        game happens to be on screen."""
        if not self.show_scorer_card or not getattr(self, "espn_summary_sport_league", None):
            return
        for game in list(getattr(self, "live_games", None) or []):
            try:
                side, runs = self._scorer_detect(game)
                if side is None:
                    continue
                abbr = game.get(f"{side}_abbr")
                if self.scorer_card_favorites_only and self.favorite_teams \
                        and abbr not in self.favorite_teams:
                    continue
                self._scorer_card = None
                self._resolve_scorer(game, side, runs)
            except Exception as e:  # noqa: BLE001 - never lose an update to a card
                self.logger.debug(f"Scorer card check skipped: {e}")
        live_ids = {g.get("id") for g in (getattr(self, "live_games", None) or [])}
        for stale in [k for k in self._scorer_baselines if k not in live_ids]:
            self._scorer_baselines.pop(stale, None)

    def _scorer_detect(self, game: Dict) -> Tuple[Optional[str], int]:
        """('away'|'home', runs) when this game's score just went up."""
        game_id = game.get("id")
        away = self._score_to_int(game.get("away_score"))
        home = self._score_to_int(game.get("home_score"))
        if not game_id or away is None or home is None:
            return None, 0
        baseline = self._scorer_baselines.get(game_id)
        # A first sighting never fires and a lower score re-bases silently,
        # for the same reasons the celebration's check does.
        self._scorer_baselines[game_id] = {"away": away, "home": home}
        if baseline is None:
            return None, 0
        for side, now_score in (("away", away), ("home", home)):
            if now_score > baseline[side]:
                return side, now_score - baseline[side]
        return None, 0

    def _scorer_window(self, game_id: str) -> Tuple[float, float]:
        """When the card appears and goes: after the celebration, if there is
        one for this game, else straight away."""
        now = time.time()
        show_from = now
        celebration = getattr(self, "active_celebration", None)
        if (celebration and celebration.get("kind") in ("run", "homerun")
                and str((celebration.get("game") or {}).get("id") or "") == str(game_id)):
            show_from = celebration["started_at"] + float(
                getattr(self, "celebration_duration", 8) or 8)
        return show_from, show_from + self.scorer_card_dwell

    def _resolve_scorer(self, game: Dict, side: str, runs: int) -> None:
        """Find out who scored, off-thread, and arm the card when it is known.

        Fire-and-forget: the render path only ever reads the result, so a slow
        or failed lookup costs the card, never the display."""
        game = dict(game)  # snapshot: survives the game leaving live_games
        show_from, show_until = self._scorer_window(game.get("id"))
        score = (self._score_to_int(game.get("away_score")),
                 self._score_to_int(game.get("home_score")))

        def work():
            try:
                play, data = None, None
                for attempt in range(SUMMARY_RETRIES):
                    data = self._fetch_summary(str(game.get("id")))
                    play = latest_scoring_play((data or {}).get("plays"), score)
                    if play is not None:
                        break
                    if attempt + 1 < SUMMARY_RETRIES:
                        time.sleep(SUMMARY_RETRY_SECONDS)
                if play is None:
                    return
                self._arm_scorer_card(game, side, runs, play, data or {}, show_from, show_until)
            except Exception as e:  # noqa: BLE001
                self.logger.debug(f"Scorer card lookup failed: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _arm_scorer_card(self, game: Dict, side: str, runs: int, play: Dict,
                         data: Dict, show_from: float, show_until: float) -> None:
        """Build the card from the scoring play, then warm the bio and photo."""
        import baseball  # late: baseball imports this module

        batter_id = batter_id_of(play)
        info = (baseball._build_athlete_info_map(data.get("rosters")).get(batter_id)
                if batter_id else None) or {}
        kind = "homerun" if is_home_run_play(play) else "run"
        card = {
            "game_id": str(game.get("id") or ""),
            "game": game,
            "side": side,
            "team_abbr": game.get(f"{side}_abbr") or "",
            "kind": kind,
            "runs": runs,
            "play_text": str(play.get("text") or "").strip(),
            "batter_id": batter_id,
            "info": info,
            "show_from": show_from,
            "show_until": show_until,
        }
        self._scorer_card = card
        if batter_id:
            # The bio (season line) and the photo are extras: the card is
            # already worth drawing from the play and the roster alone.
            self._fetch_player_bio(batter_id)
            bio = self._player_bio_cache.get(batter_id) or {}
            url = bio.get("headshot_url") or info.get("headshot_url")
            if url:
                self._prefetch_headshot(batter_id, url)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _maybe_draw_scorer_card(self, game: Dict, force_clear: bool = False) -> bool:
        """Draw the card if one is armed, due and for this game. True when it
        drew, so the caller skips the scorebug for this frame."""
        # getattr: golden-screen tests build a live manager through __new__
        # and set only what they draw with.
        card = getattr(self, "_scorer_card", None)
        if not getattr(self, "show_scorer_card", False) or not card:
            return False
        if str(game.get("id") or "") != card["game_id"]:
            return False
        now = time.time()
        if now < card["show_from"]:
            return False            # the celebration still owns the panel
        if now >= card["show_until"]:
            self._scorer_card = None
            return False
        self._draw_scorer_card(card)
        return True

    @staticmethod
    def _fit_text(draw, text: str, font, width: int) -> str:
        """``text`` cut to ``width`` pixels, ending in ".." if it was cut."""
        if draw.textlength(text, font=font) <= width:
            return text
        while text and draw.textlength(text + "..", font=font) > width:
            text = text[:-1]
        return (text.rstrip() + "..") if text else ""

    def _scorer_rows(self, card: Dict, bio: Dict) -> Dict[str, List[str]]:
        """The card's text rows in drawing order, each as options from the
        fullest wording to the shortest. The font ladder takes the first one
        that fits, so a narrow panel gets "PHI HR" where a wide one gets
        "PHI HOME RUN  Top 5th"."""
        info = card.get("info") or {}
        game = card["game"]
        kind, runs, abbr = card["kind"], card["runs"], card["team_abbr"]
        status = str(game.get("status_text") or "").strip()
        header = f"{abbr} {card_label(kind, runs)}".strip()
        short = f"{abbr} HR" if kind == "homerun" else f"{abbr} RUN"
        rows: Dict[str, List[str]] = {"header": [
            *([f"{header}  {status}"] if status else []), header, short]}

        full = str(bio.get("display_name") or "").strip()
        shortname = str(info.get("name") or "").strip()
        names = [n for n in (full, shortname, (full or shortname).split(" ")[-1]) if n]
        if names:
            rows["name"] = list(dict.fromkeys(names))
        jersey = bio.get("jersey") or info.get("jersey")
        position = bio.get("position") or info.get("position") or ""
        vitals = " ".join(p for p in (f"#{jersey}" if jersey else "", position) if p)
        if vitals:
            rows["vitals"] = [vitals]
        stats = self._format_card_stats(bio) if bio else []
        if stats:
            rows["stats"] = ["  ".join(f"{label} {value}" for label, value in stats[:n])
                             for n in range(len(stats), 0, -1)]
        if card.get("play_text"):
            rows["play"] = [card["play_text"]]
        return rows

    def _draw_scorer_card(self, card: Dict) -> None:
        """Headshot on the left (when the panel has room), then a team-colour
        banner, the batter's name and number, their season line and ESPN's
        sentence for the play.

        Rows are priority-ordered: the font ladder is asked to fit them all
        and, when it cannot, the next row in DROP_ORDER is given up and the
        ladder asked again. A 128x32 keeps the banner, the name and a stat
        line; a 256x64 carries the lot."""
        try:
            w, h = self.display_width, self.display_height
            img = Image.new("RGB", (w, h), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            info = card.get("info") or {}
            bio = self._player_bio_cache.get(card.get("batter_id")) or {}
            accent = self._player_card_team_color(card["game"], info) or (255, 200, 0)
            accent = tuple(accent)
            colors = {"header": accent, "name": (255, 255, 255),
                      "vitals": (170, 170, 170), "stats": (0, 220, 255),
                      "play": (200, 200, 200)}

            margin = 1
            headshot = None
            if w >= 96 and h >= 32 and card.get("batter_id"):
                size = min(max(24, h - 2 * (margin + 2)), h - 2 * (margin + 1), w // 3)
                mgr = self._get_headshot_manager()
                if mgr is not None:
                    _, league = self.espn_summary_sport_league
                    # Cache-only on the render path; the resolve thread warmed it.
                    headshot = mgr.load_headshot(
                        str(card["batter_id"]),
                        bio.get("headshot_url") or info.get("headshot_url"),
                        league=league, max_size=size, allow_download=False)
            if headshot is not None:
                hx, hy = margin + 1, (h - headshot.height) // 2
                draw.rectangle([hx - 1, hy - 1, hx + headshot.width, hy + headshot.height],
                               outline=accent)
                img.paste(headshot, (hx, hy), headshot)
                text_x = hx + headshot.width + 4
            else:
                text_x = margin + 1
            avail_w = max(8, w - text_x - margin - 2)
            avail_h = h - 2 * margin

            options = self._scorer_rows(card, bio)
            ladder = [f for f in (self.fonts.get("time"), self.fonts.get("status"),
                                  self.fonts.get("record")) if f is not None]

            def pick(font):
                """First wording of each row that fits, widest face first; a row
                with none that fit keeps its shortest, to be cut with "..".
                Returns (rows, whether banner and name both fit unclipped)."""
                chosen, clean = {}, True
                for key, choices in options.items():
                    fitting = [t for t in choices if draw.textlength(t, font=font) <= avail_w]
                    chosen[key] = fitting[0] if fitting else choices[-1]
                    if not fitting and key in ("header", "name"):
                        clean = False
                return chosen, clean

            def height(font, rows):
                return sum(self._row_height(draw, text, font) for text in rows.values())

            best = None
            for font in ladder:
                rows, clean = pick(font)
                # Give up the least important rows until the rest is tall enough.
                while height(font, rows) > avail_h and any(k in rows for k in DROP_ORDER):
                    rows.pop(next(k for k in DROP_ORDER if k in rows))
                tall_enough = height(font, rows) <= avail_h
                best = (font, rows)
                if tall_enough and clean:
                    break
            chosen_font, chosen_rows = best

            y = margin
            for key, text in chosen_rows.items():
                text = self._fit_text(draw, text, chosen_font, avail_w)
                if text:
                    self._draw_text_with_outline(draw, text, (text_x, y), chosen_font,
                                                 fill=colors[key])
                y += self._row_height(draw, text or " ", chosen_font)

            self.display_manager.image.paste(img, (0, 0))
            self.display_manager.update_display()
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error drawing scorer card: {e}", exc_info=True)

    @staticmethod
    def _row_height(draw, text: str, font) -> int:
        box = draw.textbbox((0, 0), text or " ", font=font)
        return box[3] - box[1] + 2
