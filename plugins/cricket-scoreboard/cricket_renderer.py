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
from datetime import datetime
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
                 config: Dict[str, Any]):
        self.width = display_width
        self.height = display_height
        self.config = config or {}

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
        self._fonts["score"] = self._load_one(custom.get("score_text"),
                                               "PressStart2P-Regular.ttf", 10)
        self._fonts["period"] = self._load_one(custom.get("period_text"),
                                                "PressStart2P-Regular.ttf", 8)
        self._fonts["team"] = self._load_one(custom.get("team_name"),
                                             "PressStart2P-Regular.ttf", 8)
        self._fonts["status"] = self._load_one(custom.get("status_text"),
                                               "4x6-font.ttf", 6)
        self._fonts["detail"] = self._load_one(custom.get("detail_text"),
                                               "4x6-font.ttf", 6)

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
        return img, ImageDraw.Draw(img)

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
    def _batting_innings(team: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        innings = team.get("innings") or []
        if not innings:
            return None
        for inn in innings:
            if inn.get("is_batting"):
                return inn
        return innings[-1]

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
        away_batting = bool(away_inn and away_inn.get("is_batting"))
        home_batting = bool(home_inn and home_inn.get("is_batting"))

        cx = self.width // 2
        away_score = self._score_text(away)
        home_score = self._score_text(home)
        self._draw_centered(draw, away_score, cx, 6, self._fonts["score"],
                            self.batting_color if away_batting else self.score_color)
        self._draw_centered(draw, home_score, cx, 6 + 11, self._fonts["score"],
                            self.batting_color if home_batting else self.score_color)

        # Detail line: overs + run rate for the batting side; RRR/target on chase.
        detail = self._live_detail(match, away, home, away_inn, home_inn,
                                   away_batting, home_batting)
        if detail:
            self._draw_centered(draw, detail, cx, self.height - 7,
                                self._fonts["detail"], self.detail_color)
        return img

    def _live_detail(self, match, away, home, away_inn, home_inn,
                     away_batting, home_batting) -> str:
        bat_team = away if away_batting else (home if home_batting else None)
        bat_inn = away_inn if away_batting else (home_inn if home_batting else None)
        if not bat_inn:
            return match.get("status_short", "") or ""

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
        return "  ".join(parts)

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

        lead = match.get("status_short") or match.get("status_summary") or ""
        if lead:
            self._draw_centered(draw, lead[:26], cx, self.height - 7,
                                self._fonts["detail"], self.detail_color)
        return img

    @staticmethod
    def _test_score_text(team: Dict[str, Any]) -> str:
        innings = team.get("innings") or []
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
        for key in ("status_short", "status_detail", "status_summary"):
            txt = match.get(key) or ""
            for token in ("Stumps", "Lunch", "Tea", "Close", "Drinks",
                          "Innings Break", "Day"):
                if token.lower() in txt.lower():
                    return txt[:22]
        period = match.get("period", 0)
        if period:
            return f"Day {period}"
        return "Test"

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
        away_line = f"{(away.get('abbr') or '')[:4]} {self._final_score(away)}"
        home_line = f"{(home.get('abbr') or '')[:4]} {self._final_score(home)}"
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

    @staticmethod
    def _format_datetime(dt: datetime) -> str:
        try:
            return dt.strftime("%b %d %H:%M")
        except Exception:
            return ""
