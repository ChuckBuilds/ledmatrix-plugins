"""Game-activity pop-ups for the live baseball scorebug.

A one-line banner along the bottom of the live scorebug for the plays between
runs -- "Harper SINGLE!  Top 8th", "Acuna Jr. STEALS 3RD  Bot 2nd" -- so a
scoreless half-inning still shows something happening. Hockey's scoreboard has
the same feature for shots and penalties; this is baseball's version.

The scoreboard feed carries none of it, so it is the game summary the
celebration and the scorer card already read, polled for the game on screen at
the live update interval, in a thread. The render path only reads a queue.

ESPN's baseball plays are one row per *pitch* plus one "play-result" row for
how the at-bat ended ("Harper singled to left, Turner scored."), and the text of
that row is the one sentence worth showing. Runs are left to the celebration
and the scorer card, as hockey leaves goals: a play flagged ``scoringPlay`` is
never a pop-up.
"""

import re
import threading
import time
import unicodedata
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

#: Never poll faster than this, whatever live_update_interval says.
MIN_POLL_SECONDS = 10.0
#: A summary takes longer than the 2 s the update thread will wait for one; this
#: thread has no such limit.
SUMMARY_TIMEOUT_SECONDS = 15.0
#: The banner needs a row of its own, so it is only drawn this tall or taller.
MIN_PANEL_HEIGHT = 32
#: A burst of plays keeps the newest few rather than replaying them all.
MAX_QUEUED = 3

#: What each detail level pops up for. "highlights" is the default.
DETAIL_KINDS = {
    "hits_and_steals": frozenset({"hit", "steal"}),
    "highlights": frozenset({"hit", "steal", "strikeout", "walk",
                             "pitching_change", "double_play", "error"}),
    "everything": frozenset({"hit", "steal", "strikeout", "walk",
                             "pitching_change", "double_play", "error",
                             "out", "sacrifice"}),
}
DEFAULT_DETAIL = "highlights"

_ORDINALS = {1: "st", 2: "nd", 3: "rd"}

# (kind, regex on ESPN's result sentence, long label, short label), first match
# wins, so the more specific sentences come first. The regex's "name" group is
# the player the pop-up is about.
_NAME = r"^(?P<name>[^,]+?)"
_RULES: Tuple[Tuple[str, "re.Pattern", str, str], ...] = tuple(
    (kind, re.compile(pattern, re.I), long_label, short_label)
    for kind, pattern, long_label, short_label in (
        ("double_play", _NAME + r"\s+(?:grounded|hit|lined|flied|popped)\b.*\b(?:double|triple) play",
         "DOUBLE PLAY", "DP"),
        ("pitching_change", _NAME + r"\s+relieved\b", "IN RELIEF", "RELIEF"),
        ("walk", _NAME + r"\s+intentionally walked", "INTENTIONAL WALK", "IBB"),
        ("walk", _NAME + r"\s+walked", "WALKS", "BB"),
        ("walk", _NAME + r"\s+(?:was )?hit by (?:a )?pitch", "HIT BY PITCH", "HBP"),
        ("strikeout", _NAME + r"\s+struck out", "STRIKES OUT", "K"),
        ("steal", _NAME + r"\s+stole\s+(?P<base>second|third|home)",
         "STEALS {base}", "SB"),
        ("steal", _NAME + r"\s+caught stealing", "CAUGHT STEALING", "CS"),
        ("hit", _NAME + r"\s+tripled\b", "TRIPLE!", "3B"),
        ("hit", _NAME + r"\s+doubled\b", "DOUBLE!", "2B"),
        ("hit", _NAME + r"\s+singled\b", "SINGLE!", "1B"),
        ("hit", _NAME + r"\s+reached on (?:an? )?infield single\b", "INFIELD SINGLE", "1B"),
        ("error", _NAME + r"\s+reached on (?:a )?(?:fielding |throwing )?error",
         "REACHES ON ERROR", "E"),
        ("sacrifice", _NAME + r"\s+hit (?:a )?sacrifice", "SACRIFICE", "SAC"),
        ("out", _NAME + r"\s+(?:grounded|bunted) into (?:a )?fielder's choice",
         "FIELDER'S CHOICE", "FC"),
        ("out", _NAME + r"\s+(?:grounded|flied|lined|popped|fouled)\s+out", "OUT", "OUT"),
    )
)

#: ESPN rows that are pitches, markers or bookkeeping rather than a result.
_NOT_RESULT_TYPES = frozenset({
    "ball", "foul-ball", "start-batterpitcher", "end-batterpitcher",
    "start-inning", "end-inning", "start-half-inning", "end-half-inning",
    "bunted-foul",
})


def _ascii(text: str) -> str:
    """Accents folded away: the 4x6 face the banner falls back to has no
    "n with tilde", and a missing glyph draws as a box in the middle of a name."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{_ORDINALS.get(n % 10, 'th')}" if n % 10 in _ORDINALS else f"{n}th"


def inning_stamps(play: Dict) -> List[str]:
    """"Top 8th", then "T8" -- the long wording first."""
    period = play.get("period") or {}
    half = str(period.get("type") or "").strip()
    try:
        number = int(period.get("number"))
    except (TypeError, ValueError):
        return []
    if half.lower().startswith("top"):
        return [f"Top {_ordinal(number)}", f"T{number}"]
    if half.lower().startswith(("bot", "bottom")):
        return [f"Bot {_ordinal(number)}", f"B{number}"]
    return [f"{_ordinal(number)} inn", str(number)]


def extract_activity(play: Dict) -> Optional[Dict]:
    """One ESPN play as a pop-up, or None.

    None for pitches, inning markers, anything unrecognised and every scoring
    play (the celebration and the scorer card own runs). Otherwise a dict with
    ``kind``, the player's ``names`` (fullest first), the ``labels`` (long,
    short), the ``stamps`` (long, short), the acting ``team_id`` and the play's
    ``text``.
    """
    if not isinstance(play, dict) or play.get("scoringPlay"):
        return None
    text = str(play.get("text") or "").strip()
    ptype = str((play.get("type") or {}).get("type") or "")
    # A pitch row's text is "Pitch 2 : Ball In Play"; its result is the next row.
    if not text or text.startswith("Pitch ") or ptype in _NOT_RESULT_TYPES:
        return None
    for kind, pattern, long_label, short_label in _RULES:
        match = pattern.search(text)
        if match is None:
            continue
        # "Baldwin struck out looking, Acuna Jr. stole second." is a strikeout
        # about Baldwin: the name is whoever the sentence starts with, and stops
        # at the first comma. Not stripped of a full stop -- "Acuna Jr." has one.
        name = _ascii(match.group("name").strip(" ,"))
        if not name or len(name) > 24:
            return None
        groups = match.groupdict()
        long_label = long_label.format(base=(groups.get("base") or "").upper().replace(
            "SECOND", "2ND").replace("THIRD", "3RD").replace("HOME", "HOME"))
        parts = name.split()
        # The surname alone is the fallback for a tight panel, unless it is
        # only a suffix ("Acuna Jr." must not shrink to "Jr.").
        suffixes = {"jr.", "sr.", "ii", "iii", "iv", "v"}
        names = [name]
        if len(parts) > 1 and parts[-1].lower() not in suffixes:
            names.append(parts[-1])
        return {
            "kind": kind,
            "names": list(dict.fromkeys(names)),
            "labels": [long_label, short_label],
            "stamps": inning_stamps(play),
            "team_id": str((play.get("team") or {}).get("id") or ""),
            "text": text,
            "play_id": str(play.get("id") or ""),
        }
    return None


def wanted_kinds(detail: Any) -> frozenset:
    """The kinds a detail level pops up for; unknown values mean the default."""
    return DETAIL_KINDS.get(str(detail or DEFAULT_DETAIL), DETAIL_KINDS[DEFAULT_DETAIL])


class BaseballActivityMixin:
    """Polls, queues and draws the pop-up banner for a live baseball manager.

    The host provides what ``BaseballLive`` does: ``mode_config``,
    ``current_game``, ``live_games``, ``update_interval``, ``fonts``,
    ``logger``, ``espn_summary_sport_league`` and ``_fetch_summary``.
    """

    def _init_game_activity(self) -> None:
        cfg = self.mode_config
        self.show_game_activity = bool(cfg.get("show_game_activity", False))
        self.game_activity_kinds = wanted_kinds(cfg.get("game_activity_detail"))
        self.game_activity_dwell = max(1.0, float(cfg.get("game_activity_dwell_seconds", 6) or 6))
        self.game_activity_fade = min(
            max(0.0, float(cfg.get("game_activity_fade_seconds", 3) or 0)),
            self.game_activity_dwell)
        self._activity_queue: Deque[Dict] = deque(maxlen=MAX_QUEUED)
        self._activity_popup: Optional[Dict] = None
        self._activity_seen: Dict[str, Optional[str]] = {}
        self._activity_inflight = False
        self._activity_last_poll = 0.0
        self._activity_drawn_at = 0.0

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll_game_activity(self) -> None:
        """Start a summary fetch for the game on screen, at most once per live
        update interval and never two at once.

        Only while the scorebug is actually being drawn where a pop-up can
        show: update() runs whether or not baseball is on screen, and in scroll
        mode or on a panel too short for the banner it would be spending a
        request per interval on pop-ups nobody sees. Pausing also forgets where
        each feed was up to, so coming back starts from a fresh baseline rather
        than replaying the gap as a run of stale pop-ups."""
        game = getattr(self, "current_game", None)
        if not game or not game.get("id") or self._activity_inflight:
            return
        now = time.time()
        interval = max(MIN_POLL_SECONDS, float(getattr(self, "update_interval", 0) or 0))
        if now - self._activity_drawn_at > 2 * interval:
            self._activity_seen.clear()
            self._activity_queue.clear()
            return
        if now - self._activity_last_poll < interval:
            return
        self._activity_last_poll = now
        self._activity_inflight = True
        live_ids = {str(g.get("id")) for g in (getattr(self, "live_games", None) or [])}
        for game_id in [k for k in self._activity_seen if k not in live_ids]:
            self._activity_seen.pop(game_id, None)
        try:
            threading.Thread(target=self._fetch_game_activity, args=(dict(game),),
                             daemon=True).start()
        except RuntimeError as e:  # no thread, no fetch: never a stuck flag
            self._activity_inflight = False
            self.logger.debug(f"Game activity poll not started: {e}")

    def _fetch_game_activity(self, game: Dict) -> None:
        try:
            summary = self._fetch_summary(str(game["id"]), timeout=SUMMARY_TIMEOUT_SECONDS)
            if summary:
                self._queue_game_activity(game, summary.get("plays") or [])
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Game activity poll failed for {game.get('id')}: {e}")
        finally:
            self._activity_inflight = False

    def _queue_game_activity(self, game: Dict, plays: List[Dict]) -> None:
        """Queue a pop-up for each wanted play since this game's last poll.

        The first poll of a game only records where the feed is up to: a game
        joined mid-inning would otherwise replay every hit it has had. So does a
        poll that cannot find the last play it saw, since ESPN has rewritten the
        feed and there is no telling which plays are new."""
        game_id = str(game.get("id"))
        ids = [str(p.get("id", "") or "") for p in plays]
        last = self._activity_seen.get(game_id)
        self._activity_seen[game_id] = ids[-1] if ids and ids[-1] else None
        if not last or last not in ids:
            return
        sides = {str(game.get("home_id")): "home", str(game.get("away_id")): "away"}
        seen_text = set()
        for play in plays[ids.index(last) + 1:]:
            activity = extract_activity(play)
            if activity is None or activity["kind"] not in self.game_activity_kinds:
                continue
            # ESPN can carry the same sentence on two rows (a steal is one).
            key = (activity["text"], tuple(activity["stamps"]))
            if key in seen_text:
                continue
            seen_text.add(key)
            side = sides.get(activity["team_id"])
            activity["game_id"] = game_id
            activity["team_abbr"] = game.get(f"{side}_abbr", "") if side else ""
            activity["team_color"] = game.get(f"{side}_team_color") if side else None
            self._activity_queue.append(activity)

    # ------------------------------------------------------------------
    # Showing it
    # ------------------------------------------------------------------

    def _current_activity_popup(self, game: Dict, dwell: float) -> Optional[Dict]:
        """The pop-up to draw over this game right now, if any. Pop-ups queued
        for a game the rotation has left are dropped rather than shown late over
        a different game."""
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

    @staticmethod
    def _cut(draw, text: str, font, width: int) -> str:
        """``text`` cut to ``width`` pixels, ending in ".." if it was cut."""
        if draw.textlength(text, font=font) <= width:
            return text
        while text and draw.textlength(text + "..", font=font) > width:
            text = text[:-1]
        return (text.rstrip() + "..") if text else ""

    def _layout_activity_banner(self, draw, popup: Dict, width: int,
                                max_row_h: int) -> Optional[Dict]:
        """Font and wording for the banner: the fullest wording that fits the
        width, in the largest font whose row fits ``max_row_h``.

        Wording beats size -- a smaller font is tried before any word is given
        up. Then, in order: the player's surname alone, the short label, the
        long inning, and last of all the inning itself, which is what says when
        the play happened. A line too wide even then is cut rather than drawn
        past the edge."""
        fonts = []
        for font in (self.fonts.get("time"), self.fonts.get("status"), self.fonts.get("record")):
            if font is None:
                continue
            box = font.getbbox("Ay")
            row_h = box[3] - box[1] + 2
            if row_h <= max_row_h:
                fonts.append((font, row_h))
        if not fonts:
            return None
        names = popup.get("names") or [popup.get("team_abbr") or ""]
        stamps = list(dict.fromkeys(popup.get("stamps") or [])) + [""]
        avail = width - 2
        for stamp in stamps:
            for label in popup["labels"]:
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
                "name": self._cut(draw, names[-1], font, avail), "label": "", "stamp": ""}

    def _with_activity_popup(self, img: Image.Image, game: Dict) -> Image.Image:
        """The scorebug with the current pop-up banner over its bottom row.

        Each frame is a finished screen: the banner holds at full strength,
        then its text dims to black over the fade, and the scorebug's own bottom
        row returns once it has gone. The text fades rather than the banner
        cross-fading into the scorebug, because a cross-fade shows the scorebug
        line through the pop-up -- two lines of text on top of each other. A
        ramp, so at the 1 FPS a switch-mode board is drawn at it steps down
        evenly instead of flickering."""
        if not getattr(self, "show_game_activity", False):
            return img
        width, height = img.size
        if height < MIN_PANEL_HEIGHT:
            return img
        self._activity_drawn_at = time.time()
        try:
            dwell, fade = self.game_activity_dwell, self.game_activity_fade
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
                layout = self._layout_activity_banner(draw, popup, width, max(9, height // 6))
                if layout is None:
                    return img
                layout["size"] = (width, height)
                popup["_layout"] = layout

            font, row_h = layout["font"], layout["row_h"]
            text_color, time_color = (255, 255, 255), (170, 170, 170)
            label_color = tuple(popup["team_color"]) if popup.get("team_color") else (255, 200, 0)

            def faded(color):
                return tuple(int(round(c * strength)) for c in color[:3])

            label = f" {layout['label']}" if layout["label"] else ""
            stamp = f"  {layout['stamp']}" if layout["stamp"] else ""
            segments = [(layout["name"], text_color), (label, label_color), (stamp, time_color)]

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
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Game activity pop-up skipped: {e}")
            return img
