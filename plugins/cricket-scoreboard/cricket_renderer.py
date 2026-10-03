"""
Cricket scoreboard renderer.

One render method per match state, mirroring the separate-renderer-per-view
pattern used by the olympics plugin's renderers:

  render_live_limited_overs  -> live T20 / ODI (overs clock, run rate, target/RRR)
  render_live_test           -> live Test / first-class (day + session, no clock)
  render_recent              -> completed match (final scores + result summary)
  render_upcoming            -> scheduled match (date/time, teams, venue, format)

Each method returns a PIL Image sized (width, height) that the manager pastes
onto the display_manager and pushes with update_display().
"""

import logging
import os
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from cricket_data_fetcher import (
    CricketDataFetcher,
    current_run_rate,
    required_run_rate,
)

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent

# Font search paths: bundled first, then the core LEDMatrix asset dirs.
_FONT_DIRS = [
    _PLUGIN_DIR / "assets" / "fonts",
    Path("assets") / "fonts",
    _PLUGIN_DIR.parent.parent / "assets" / "fonts",
    Path.home() / "Github" / "LEDMatrix" / "assets" / "fonts",
]

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREY = (170, 170, 170)
YELLOW = (255, 210, 0)
GREEN = (0, 255, 102)


def _hex_to_rgb(value: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    if not value:
        return default
    v = value.lstrip("#")
    if len(v) != 6:
        return default
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except ValueError:
        return default


class CricketRenderer:
    """Renders cricket match cards for the LED matrix."""

    def __init__(self, display_width: int, display_height: int,
                 config: Dict[str, Any], tz: Optional[tzinfo] = None):
        self.width = display_width
        self.height = display_height
        self.config = config or {}
        # Start times arrive in UTC; they are drawn in this zone (the Pi's
        # local zone when None).
        self.tz = tz

        custom = self.config.get("customization", {}) or {}
        colors = custom.get("colors", {}) or {}
        self.score_color = _hex_to_rgb(colors.get("score_color"), WHITE)
        self.batting_color = _hex_to_rgb(colors.get("batting_color"), GREEN)
        self.detail_color = _hex_to_rgb(colors.get("detail_color"), YELLOW)
        self.status_color = _hex_to_rgb(colors.get("status_color"), GREY)

        self._fonts: Dict[str, ImageFont.ImageFont] = {}
        self._load_fonts(custom)

        self._img_cache: Dict[str, Optional[Image.Image]] = {}

    # ---- fonts ------------------------------------------------------------ #

    @staticmethod
    def _find_font(filename: str) -> Optional[str]:
        for d in _FONT_DIRS:
            p = Path(d) / filename
            if p.exists():
                return str(p)
        return None

    def _load_one(self, element_cfg: Dict[str, Any], default_font: str,
                  default_size: int) -> ImageFont.ImageFont:
        name = (element_cfg or {}).get("font", default_font)
        size = int((element_cfg or {}).get("font_size", default_size))
        path = self._find_font(name) or self._find_font(default_font)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception as e:
                logger.warning("Font load failed %s@%s: %s", path, size, e)
        return ImageFont.load_default()

    def _load_fonts(self, custom: Dict[str, Any]) -> None:
        # Defaults mirror config_schema.json (score 8, status/detail 7).
        self._fonts["score"] = self._load_one(custom.get("score_text"),
                                               "PressStart2P-Regular.ttf", 8)
        self._fonts["period"] = self._load_one(custom.get("period_text"),
                                                "PressStart2P-Regular.ttf", 8)
        self._fonts["team"] = self._load_one(custom.get("team_name"),
                                             "PressStart2P-Regular.ttf", 8)
        self._fonts["status"] = self._load_one(custom.get("status_text"),
                                               "4x6-font.ttf", 7)
        self._fonts["detail"] = self._load_one(custom.get("detail_text"),
                                               "4x6-font.ttf", 7)

    # ---- draw helpers ----------------------------------------------------- #

    def _text_size(self, draw: ImageDraw.ImageDraw, text: str,
                   font: ImageFont.ImageFont) -> Tuple[int, int]:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            return len(text) * 6, 8

    def _draw_centered(self, draw: ImageDraw.ImageDraw, text: str,
                       cx: int, y: int, font: ImageFont.ImageFont,
                       fill: Tuple[int, int, int]) -> None:
        w, _ = self._text_size(draw, text, font)
        draw.text((cx - w // 2, y), text, font=font, fill=fill)

    def _blank(self) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (self.width, self.height), BLACK)
        draw = ImageDraw.Draw(img)
        # Disable anti-aliasing: pixel/bitmap fonts (e.g. PressStart2P) get
        # anti-aliased into dim partial-lit pixels on a 1:1 LED matrix, muddying
        # glyphs. 1-bit mode keeps strokes crisp.
        draw.fontmode = "1"
        return img, draw

    # ---- team crest (flag / logo / placeholder) --------------------------- #

    def _load_crest(self, team: Dict[str, Any], size: int) -> Optional[Image.Image]:
        """Load a national-team flag or franchise logo, cached by key+size."""
        abbr = (team.get("abbr") or "").upper()
        name = (team.get("name") or "").lower().replace(" ", "_")
        cache_key = f"{abbr}:{name}:{size}"
        if cache_key in self._img_cache:
            return self._img_cache[cache_key]

        candidates: List[Path] = []
        flags_dir = _PLUGIN_DIR / "assets" / "flags"
        logos_dir = _PLUGIN_DIR / "assets" / "logos"
        if abbr:
            candidates += [flags_dir / f"{abbr}.png", logos_dir / f"{abbr}.png"]
        if name:
            candidates += [flags_dir / f"{name}.png", logos_dir / f"{name}.png"]

        img = None
        for path in candidates:
            if path.exists():
                try:
                    with Image.open(path) as raw:
                        crest = raw.convert("RGBA").resize((size, size), Image.NEAREST)
                        crest.load()
                    img = crest
                    break
                except Exception as e:
                    logger.debug("Crest load failed %s: %s", path, e)

        self._img_cache[cache_key] = img
        return img

    def _draw_team_crest(self, img: Image.Image, draw: ImageDraw.ImageDraw,
                         team: Dict[str, Any], x: int, y: int, size: int) -> None:
        crest = self._load_crest(team, size)
        if crest is not None:
            img.paste(crest, (x, y), crest)
            return
        # Text placeholder box.
        draw.rectangle([x, y, x + size - 1, y + size - 1], outline=GREY)
        abbr = (team.get("abbr") or team.get("short_name") or "?")[:3]
        w, h = self._text_size(draw, abbr, self._fonts["team"])
        draw.text((x + (size - w) // 2, y + (size - h) // 2), abbr,
                  font=self._fonts["team"], fill=WHITE)

    # ---- innings helpers -------------------------------------------------- #

    @staticmethod
    def _batted_innings(team: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The innings this side actually batted, in order.

        ESPN gives each side a linescore for every period of the match,
        including the ones it spent bowling: those carry 0 runs, 0 wickets and
        the opponent's overs, with isBatting false. isBatting marks the periods
        a side batted in (not just the one in progress), so it stays true on a
        finished first innings. Counting the bowling rows drew a Test score as
        "0 & 278 & 0/0" and a side yet to bat as "0/0".
        """
        return [inn for inn in (team.get("innings") or [])
                if inn.get("is_batting") or inn.get("runs") or inn.get("wickets")]

    @staticmethod
    def _batting_innings(team: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """This side's latest batted innings, or None when it has not batted."""
        batted = CricketRenderer._batted_innings(team)
        return batted[-1] if batted else None

    @staticmethod
    def _at_crease(inn: Optional[Dict[str, Any]],
                   other: Optional[Dict[str, Any]]) -> bool:
        """Whether `inn` is the innings in progress, given the other side's.

        Both sides keep isBatting true on every innings they batted, so the
        flag alone highlighted the side that batted first for the whole chase.
        The later innings (higher period) is the one in progress.
        """
        if not inn:
            return False
        if other and inn.get("period", 0) != other.get("period", 0):
            return inn.get("period", 0) > other.get("period", 0)
        return bool(inn.get("is_batting"))

    @staticmethod
    def _score_text(team: Dict[str, Any]) -> str:
        inn = CricketRenderer._batting_innings(team)
        if not inn:
            return "-"
        return f"{inn['runs']}/{inn['wickets']}"

    # ---- public render methods ------------------------------------------- #

    def render_live_limited_overs(self, match: Dict[str, Any]) -> Image.Image:
        """Live T20/ODI card: crests, runs/wickets (overs/max ov), run rates."""
        img, draw = self._blank()
        teams = match.get("teams", [])
        if len(teams) < 2:
            return self._render_message(match.get("name", "Cricket"), "No data")

        home, away = teams[0], teams[1]
        crest = min(self.height - 12, 16)
        self._draw_team_crest(img, draw, away, 1, 1, crest)
        self._draw_team_crest(img, draw, home, self.width - crest - 1, 1, crest)

        # Format badge / series top-center.
        self._draw_centered(draw, match.get("format", "T20"),
                             self.width // 2, 0, self._fonts["status"],
                             self.status_color)

        # Abbreviations under crests.
        away_abbr = (away.get("abbr") or away.get("short_name") or "")[:4]
        home_abbr = (home.get("abbr") or home.get("short_name") or "")[:4]
        self._draw_centered(draw, away_abbr, 1 + crest // 2, crest + 1,
                            self._fonts["status"], WHITE)
        self._draw_centered(draw, home_abbr, self.width - crest // 2 - 1, crest + 1,
                            self._fonts["status"], WHITE)

        # Scores center.
        away_inn = self._batting_innings(away)
        home_inn = self._batting_innings(home)
        away_batting = self._at_crease(away_inn, home_inn)
        home_batting = self._at_crease(home_inn, away_inn)

        cx = self.width // 2
        away_score = self._score_text(away)
        home_score = self._score_text(home)
        self._draw_centered(draw, away_score, cx, 6, self._fonts["score"],
                            self.batting_color if away_batting else self.score_color)
        self._draw_centered(draw, home_score, cx, 6 + 11, self._fonts["score"],
                            self.batting_color if home_batting else self.score_color)

        # Detail line: overs + run rate for the batting side; RRR/target on chase.
        parts = self._live_detail_parts(match, away, home, away_inn, home_inn,
                                        away_batting, home_batting)
        detail = self._fit_parts(draw, parts, self._fonts["detail"])
        if detail:
            self._draw_centered(draw, detail, cx, self.height - 7,
                                self._fonts["detail"], self.detail_color)
        return img

    def _fit_parts(self, draw: ImageDraw.ImageDraw, parts: List[str],
                   font: ImageFont.ImageFont) -> str:
        """The detail parts joined, dropping the least useful until they fit.

        A chase reads "13/20 ov  RR 9.4  need 34 RRR 4.9", about 130px in the
        detail font -- wider than a 128px panel, so both ends were cut off.
        Run rate goes first, then the overs; the chase equation is kept.
        """
        if not parts:
            return ""
        candidates = [parts]
        no_rr = [p for p in parts if not p.startswith("RR ")]
        if no_rr != parts:
            candidates.append(no_rr)
        if len(no_rr) > 1:
            candidates.append(no_rr[1:])   # the overs are always first
        for cand in candidates:
            text = "  ".join(cand)
            if self._text_size(draw, text, font)[0] <= self.width:
                return text
        return "  ".join(candidates[-1])

    def _live_detail_parts(self, match, away, home, away_inn, home_inn,
                           away_batting, home_batting) -> List[str]:
        bat_team = away if away_batting else (home if home_batting else None)
        bat_inn = away_inn if away_batting else (home_inn if home_batting else None)
        if not bat_inn:
            status = match.get("status_short", "") or ""
            return [status] if status else []

        max_overs = CricketDataFetcher.parse_max_overs(
            bat_team.get("score_str", ""), match.get("format", ""))
        overs_disp = self._format_overs(bat_inn.get("overs_raw", 0.0))
        if max_overs:
            overs_txt = f"{overs_disp}/{max_overs} ov"
        else:
            overs_txt = f"{overs_disp} ov"

        crr = current_run_rate(bat_inn.get("runs", 0), bat_inn.get("overs_raw", 0.0))
        parts = [overs_txt]
        if crr is not None:
            parts.append(f"RR {crr:.1f}")

        target = match.get("target")
        if target and max_overs:
            runs_needed = target - bat_inn.get("runs", 0)
            balls_bowled = bat_inn.get("balls", 0)
            balls_remaining = max_overs * 6 - balls_bowled
            rrr = required_run_rate(runs_needed, balls_remaining)
            if runs_needed > 0 and rrr is not None:
                parts.append(f"need {runs_needed} RRR {rrr:.1f}")
        return parts

    def render_live_test(self, match: Dict[str, Any]) -> Image.Image:
        """Live Test card: no clock -- day + session, both innings scores."""
        img, draw = self._blank()
        teams = match.get("teams", [])
        if len(teams) < 2:
            return self._render_message(match.get("name", "Cricket"), "No data")
        home, away = teams[0], teams[1]

        crest = min(self.height - 12, 16)
        self._draw_team_crest(img, draw, away, 1, 1, crest)
        self._draw_team_crest(img, draw, home, self.width - crest - 1, 1, crest)

        # Session/day from status text (e.g. "Stumps", "Lunch", "Day 3").
        session = self._test_session(match)
        self._draw_centered(draw, session or "Test", self.width // 2, 0,
                            self._fonts["status"], self.status_color)

        cx = self.width // 2
        away_score = self._test_score_text(away)
        home_score = self._test_score_text(home)
        self._draw_centered(draw, (away.get("abbr") or "")[:4] + " " + away_score,
                            cx, 8, self._fonts["detail"], self.score_color)
        self._draw_centered(draw, (home.get("abbr") or "")[:4] + " " + home_score,
                            cx, 8 + 8, self._fonts["detail"], self.score_color)

        # The summary ("India lead by 84 runs") first: ESPN's short detail
        # is just "Live" while a Test is in progress.
        lead = match.get("status_summary") or match.get("status_short") or ""
        if lead:
            self._draw_centered(draw, lead[:26], cx, self.height - 7,
                                self._fonts["detail"], self.detail_color)
        return img

    @staticmethod
    def _test_score_text(team: Dict[str, Any]) -> str:
        innings = CricketRenderer._batted_innings(team)
        if not innings:
            return "-"
        pieces = []
        for inn in innings:
            wk = inn.get("wickets", 0)
            runs = inn.get("runs", 0)
            if wk >= 10 or inn.get("description", "").lower() in ("declared", "all out"):
                pieces.append(f"{runs}")
            else:
                pieces.append(f"{runs}/{wk}")
        return " & ".join(pieces)

    def _test_session(self, match: Dict[str, Any]) -> str:
        # ESPN puts the break ("Stumps", "Lunch") in status.type.description
        # and the day ("Day 2") in status.session. status.period counts
        # innings, not days, so it is not used here: it drew "Day 3" on the
        # second day's third innings.
        day = match.get("status_session") or ""
        for key in ("status_description", "status_short", "status_detail",
                    "status_summary"):
            txt = match.get(key) or ""
            for token in ("Stumps", "Lunch", "Tea", "Close", "Drinks",
                          "Innings Break", "Day"):
                if token.lower() in txt.lower():
                    if day and "day" not in txt.lower():
                        txt = f"{txt} {day}"
                    return txt[:22]
        return day[:22] or "Test"

    def render_recent(self, match: Dict[str, Any]) -> Image.Image:
        """Completed match: final scores + result summary."""
        img, draw = self._blank()
        teams = match.get("teams", [])
        if len(teams) < 2:
            return self._render_message(match.get("name", "Cricket"), "Final")
        home, away = teams[0], teams[1]

        crest = min(self.height - 14, 14)
        self._draw_team_crest(img, draw, away, 1, 1, crest)
        self._draw_team_crest(img, draw, home, self.width - crest - 1, 1, crest)

        self._draw_centered(draw, "FINAL", self.width // 2, 0,
                            self._fonts["status"], self.status_color)

        cx = self.width // 2
        # A Test result needs both innings; the last one alone read as the
        # side's whole match.
        score = self._test_score_text if match.get("is_test") else self._final_score
        away_line = f"{(away.get('abbr') or '')[:4]} {score(away)}"
        home_line = f"{(home.get('abbr') or '')[:4]} {score(home)}"
        away_col = GREEN if away.get("winner") else self.score_color
        home_col = GREEN if home.get("winner") else self.score_color
        self._draw_centered(draw, away_line, cx, 7, self._fonts["detail"], away_col)
        self._draw_centered(draw, home_line, cx, 7 + 8, self._fonts["detail"], home_col)

        summary = match.get("status_summary", "")
        if summary:
            self._draw_centered(draw, summary[:30], cx, self.height - 7,
                                self._fonts["status"], self.detail_color)
        return img

    @staticmethod
    def _final_score(team: Dict[str, Any]) -> str:
        innings = team.get("innings") or []
        if not innings:
            return team.get("score_str", "").split(" ")[0] or "-"
        # Prefer the innings that actually has runs (its last batted innings).
        inn = innings[-1]
        for i in reversed(innings):
            if i.get("runs", 0) or i.get("wickets", 0):
                inn = i
                break
        return f"{inn['runs']}/{inn['wickets']}"

    def render_upcoming(self, match: Dict[str, Any]) -> Image.Image:
        """Scheduled match: date/time, teams, venue, format badge."""
        img, draw = self._blank()
        teams = match.get("teams", [])
        cx = self.width // 2

        self._draw_centered(draw, match.get("format", "Cricket"), cx, 0,
                            self._fonts["status"], self.detail_color)

        if len(teams) >= 2:
            home, away = teams[0], teams[1]
            crest = min(self.height - 14, 14)
            self._draw_team_crest(img, draw, away, 1, 8, crest)
            self._draw_team_crest(img, draw, home, self.width - crest - 1, 8, crest)
            matchup = f"{(away.get('abbr') or away.get('short_name') or '')[:4]} v {(home.get('abbr') or home.get('short_name') or '')[:4]}"
            self._draw_centered(draw, matchup, cx, 8, self._fonts["team"], WHITE)

        dt = match.get("start_time_utc")
        when = self._format_datetime(dt) if dt else ""
        if when:
            self._draw_centered(draw, when, cx, self.height - 14,
                                self._fonts["status"], self.score_color)

        if self.config.get("show_venue", True):
            venue = match.get("venue", "")
            if venue:
                self._draw_centered(draw, venue[:30], cx, self.height - 7,
                                    self._fonts["status"], self.status_color)
        return img

    # ---- misc ------------------------------------------------------------- #

    def _render_message(self, title: str, msg: str) -> Image.Image:
        img, draw = self._blank()
        cx = self.width // 2
        self._draw_centered(draw, title[:20], cx, self.height // 2 - 8,
                            self._fonts["team"], WHITE)
        self._draw_centered(draw, msg[:24], cx, self.height // 2 + 2,
                            self._fonts["status"], GREY)
        return img

    @staticmethod
    def _format_overs(overs_raw: float) -> str:
        try:
            overs_raw = float(overs_raw)
        except (TypeError, ValueError):
            return "0"
        whole = int(overs_raw)
        balls = int(round((overs_raw - whole) * 10))
        if balls <= 0:
            return f"{whole}"
        return f"{whole}.{balls}"

    def _format_datetime(self, dt: datetime) -> str:
        """A start time in the display's timezone. It used to be drawn in UTC,
        so an evening match in New York read as the next morning."""
        try:
            return dt.astimezone(self.tz).strftime("%b %d %H:%M")
        except Exception:
            return ""
