"""
Soccer Goal Scorer Card

The scorer card shown after a goal celebration clears: who scored, when, and
what kind of goal it was, plus whatever the athlete record knows about them.

Soccer is the cheapest of these cards to feed. ESPN puts the goal events
straight into the scoreboard payload the plugin already downloads
(``competitions[].details[]``, each carrying ``athletesInvolved``), so
identifying the scorer costs no request at all -- only the optional bio
lookup does.

There is no headshot. ESPN publishes none for soccer: the athlete record's
``headshot`` field is null, the CDN path 404s, and the scoreboard's athlete
entries have no such field. The card is text-only by design rather than by
degradation, which is why it centres its rows instead of reserving a column
for a face.

Deliberately NOT named goal_card.py or logo_manager.py. The core loads a
plugin's top-level modules under their bare names, so a generic name here
could bind another plugin's module (CLAUDE.md non-negotiable #4).
"""

import time
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

# ESPN flags the kind of goal on the detail entry rather than naming it. Only
# the ones worth a badge are listed; an ordinary goal gets none, because
# "ordinary" is the default state and saying so would waste the slot.
GOAL_KIND_BADGES: Tuple[Tuple[str, str], ...] = (
    ("ownGoal", "OG"),
    ("penaltyKick", "PEN"),
    ("shootout", "SO"),
)


# ESPN's season summary for a soccer player leads with appearances --
# "START (SUB) 5 (0)" -- which is the least interesting thing on a card about
# a goal, and wide enough to be the only stat that fits on a narrow panel.
# The stats are reordered so the card leads with the ones a goal is about;
# anything unrecognised keeps its place behind them rather than being
# dropped, so a league with an unusual stat set still shows something.
GOAL_CARD_STAT_PRIORITY: Tuple[str, ...] = ("G", "A", "SHOT", "PTS")


def _prioritise_stats(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Sort (label, value) stats so goals and assists lead. Stable, so the
    feed's own order survives within each tier."""
    def rank(pair):
        label = str(pair[0]).upper()
        try:
            return GOAL_CARD_STAT_PRIORITY.index(label)
        except ValueError:
            return len(GOAL_CARD_STAT_PRIORITY)
    return sorted(pairs, key=rank)


def _goal_kind_badge(detail: Dict) -> Optional[str]:
    """Short badge for a goal's kind, or None for an ordinary goal."""
    for key, badge in GOAL_KIND_BADGES:
        if detail.get(key):
            return badge
    return None


def extract_goals(game_event: Dict) -> List[Dict]:
    """Pull every goal out of a scoreboard event, oldest first.

    Reads ``competitions[].details[]``, which ESPN includes in the scoreboard
    payload the plugin already fetches -- so the scorer costs nothing extra.
    Entries that name nobody are skipped rather than yielding a blank card.
    """
    goals: List[Dict] = []
    competitions = game_event.get("competitions") or []
    details = (competitions[0].get("details") or []) if competitions else []
    for detail in details:
        if not detail.get("scoringPlay"):
            continue
        athletes = detail.get("athletesInvolved") or []
        if not athletes:
            continue
        scorer = athletes[0] or {}
        name = scorer.get("fullName") or scorer.get("displayName")
        if not name:
            continue
        position = scorer.get("position") or {}
        if isinstance(position, dict):
            position = position.get("abbreviation") or position.get("displayName") or ""
        goals.append({
            "scorer": {
                "id": str(scorer.get("id", "") or ""),
                "name": name,
                "short_name": scorer.get("shortName") or name,
                "jersey": scorer.get("jersey"),
                "position": position or "",
            },
            "team_id": str((detail.get("team") or {}).get("id", "") or ""),
            "clock": (detail.get("clock") or {}).get("displayValue") or "",
            "badge": _goal_kind_badge(detail),
            # An own goal is credited to a player on the *other* side, so the
            # scoring team cannot be read off the scorer's own team id.
            "own_goal": bool(detail.get("ownGoal")),
        })
    return goals


def latest_goal(goals: Optional[List[Dict]], team_id: Optional[str] = None) -> Optional[Dict]:
    """The most recent goal, optionally for one team.

    Scanned backwards because ESPN appends. The team filter matters because
    the card is armed from a score delta: if both sides scored between two
    polls, the newest goal overall may not be the one that fired the
    celebration. An own goal is matched against the team it was *credited
    to* rather than the scorer's own club.
    """
    for goal in reversed(goals or []):
        if team_id and goal.get("team_id") and goal["team_id"] != str(team_id):
            continue
        return goal
    return None


class SoccerGoalCardMixin:
    """Renders the goal-scorer card. Mixed into the live manager, which owns
    the celebration state and the display path."""

    _GOAL_CARD_FONT_LADDER: List[str] = [
        "9x15.bdf", "8x13.bdf", "7x13.bdf", "6x13.bdf",
        "6x12.bdf", "6x10.bdf", "6x9.bdf", "5x8.bdf", "5x7.bdf",
    ]
    _GOAL_CARD_ROW_ORDER: Tuple[str, ...] = (
        "header", "name", "team", "stats", "vitals", "hometown",
    )
    # Given up least-useful-first when the panel cannot hold them all.
    _GOAL_CARD_DROP_ORDER: Tuple[str, ...] = (
        "hometown", "vitals", "team", "stats",
    )

    def _goal_card_cfg(self) -> Dict:
        return self.config.get("customization", {}).get("goal_scorer", {})

    @staticmethod
    def _readable_on(background: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Black or white, whichever reads against `background`. Club colours
        run from near-black navy to bright yellow, so a banner knocked out in
        a fixed colour is illegible for roughly half a league."""
        r, g, b = background[:3]
        return (0, 0, 0) if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else (255, 255, 255)

    @staticmethod
    def _truncate_to_width(draw, text: str, font, max_width: int) -> str:
        """Hard-truncate so text never draws past the panel edge. Last resort:
        the name row offers a short spelling first."""
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
        """Join segments into a line that fits, dropping whole trailing
        segments rather than cutting through the middle of one."""
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
        """Largest font from the ladder that fits every line's real text."""
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
                row_h, max_line_w = 10, available_width + 1
            result = (font, row_h)
            if (needed_rows * row_h <= available_height
                    and max_line_w <= available_width) or i == len(candidates) - 1:
                break
        return result

    @staticmethod
    def _build_goal_card_rows(goal: Dict) -> Dict[str, List[str]]:
        """Assemble the card's rows as {row_key: [segment, ...]}.

        The scoreboard feed alone yields the banner, the name and the shirt
        number; the optional bio adds the position, season line, age, height
        and hometown. A field ESPN did not send is absent rather than drawn
        as an empty label."""
        scorer = goal.get("scorer") or {}
        bio = goal.get("bio") or {}
        rows: Dict[str, List[str]] = {}

        header = [f"{goal.get('team_abbr') or ''} GOAL".strip()]
        if goal.get("clock"):
            header.append(str(goal["clock"]))
        if goal.get("badge"):
            header.append(goal["badge"])
        rows["header"] = header

        # Both spellings, longest first -- the renderer takes the longest that
        # fits rather than hard-cutting a name mid-word.
        full_name = bio.get("display_name") or scorer.get("name") or "Scorer"
        short_name = scorer.get("short_name") or ""
        rows["name"] = [full_name]
        if short_name and short_name != full_name:
            rows["name"].append(short_name)

        jersey = bio.get("jersey") or scorer.get("jersey")
        position = bio.get("position") or scorer.get("position") or ""
        team_line = [p for p in (f"#{jersey}" if jersey else "", position) if p]
        if team_line:
            rows["team"] = team_line

        ordered = _prioritise_stats(bio.get("stat_pairs") or [])
        stats = [f"{label} {value}" for label, value in ordered[:4]]
        if stats:
            rows["stats"] = stats

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
        """Draw the card if one is armed, due, and for this game. Returns True
        when it drew, so the caller skips the scorebug for this frame."""
        if not getattr(self, "show_goal_scorer", False):
            return False
        card = getattr(self, "_goal_card", None)
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
        """Draw the card: a club-coloured "<TEAM> GOAL" banner with the clock
        and any PEN/OG/SO badge, the scorer's name, shirt number and position,
        their season line, and their age, height and hometown.

        Rows are priority-ordered rather than tiered by a hardcoded panel
        table: the font ladder is asked to fit them all, and when it cannot
        the next row in _GOAL_CARD_DROP_ORDER is given up and the ladder asked
        again. Text is centred -- with no headshot to sit beside, a centred
        block reads as deliberate rather than as a card missing its picture.
        """
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
            if not cfg.get("show_bio_details", True):
                for key in ("vitals", "hometown"):
                    rows.pop(key, None)

            colors = {
                "header": accent,
                # The name stays white: club colours are legible but a dark
                # navy still reads poorly at the size a name is drawn, and the
                # banner above already carries the club's colour.
                "name": text_color,
                "team": accent,
                "stats": stat_color,
                "vitals": detail_color,
                "hometown": detail_color,
            }

            margin = 1
            # Reserve the margin plus 1px for the outline the text helper
            # paints beyond each glyph.
            avail_w = max(8, w - 2 * margin - 2)
            avail_h = h - 2 * margin
            font_cfg = dict(cfg)
            font_cfg.setdefault("font", "9x15.bdf")
            font_size_cap = font_cfg.get("font_size", 24)
            separators = {"team": " "}

            keys = [k for k in self._GOAL_CARD_ROW_ORDER if rows.get(k)]
            texts = {k: (rows[k][-1] if k == "name"
                         else separators.get(k, "  ").join(rows[k])) for k in keys}
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
                    # Alternatives, not segments: longest spelling that fits.
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
                text_w = draw.textbbox((0, 0), text, font=font)[2]
                tx = max(margin + 1, (w - text_w) // 2)
                if key == "header" and header_bar:
                    # Knocked-out banner: club colour behind, glyphs in
                    # whichever of black/white reads against it. Drawn flat --
                    # the outline helper's black edge would smear a
                    # knocked-out glyph.
                    draw.rectangle(
                        [margin, y, w - margin - 1, min(h - 1, y + row_h - 2)],
                        fill=accent,
                    )
                    draw.fontmode = "1"
                    draw.text((tx, y), text, font=font, fill=self._readable_on(accent))
                else:
                    self._draw_text_with_outline(
                        draw, text, (tx, y), font, fill=colors[key]
                    )
                y += row_h

            self.display_manager.image.paste(img, (0, 0))
            self.display_manager.update_display()
        except Exception as e:
            self.logger.error(f"Error drawing goal-scorer card: {e}", exc_info=True)
