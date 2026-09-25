"""Fantasy Blitz's rules, with no network and no drawing.

Everything that decides *what* the board says lives here so it can be tested
on recorded data: which scoring format a number comes from, who counts as a
bust, what a big play is and how it is described, which screens belong to
which part of the NFL week, and who wins the weekly awards.

A "player" throughout is the normalised dict built by
:func:`normalize_sleeper_rows` -- see its docstring for the shape.
"""

import re
import time
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

#: config ``scoring_format`` -> Sleeper's points key.
SCORING_KEYS = {
    "ppr": "pts_ppr",
    "half_ppr": "pts_half_ppr",
    "standard": "pts_std",
}
SCORING_LABELS = {"ppr": "PPR", "half_ppr": "HALF", "standard": "STD"}
DEFAULT_SCORING = "ppr"

#: Sleeper injury_status -> the tag drawn on the panel (None: draw nothing).
INJURY_TAGS = {
    "Questionable": "Q",
    "Doubtful": "D",
    "Out": "O",
    "IR": "IR",
    "PUP": "PUP",
    "Sus": "SUS",
    "COV": "O",
}
#: Tags in the order the injury report ranks them, most serious first.
INJURY_SEVERITY = {"O": 0, "IR": 1, "SUS": 2, "PUP": 3, "D": 4, "Q": 5}

#: The stat fields kept from a Sleeper row. Everything else is dropped so the
#: cached week stays small (Sleeper sends ~100 fields a player).
KEEP_STATS = (
    "pass_yd", "pass_td", "pass_int", "pass_cmp", "pass_att",
    "rush_att", "rush_yd", "rush_td",
    "rec", "rec_tgt", "rec_yd", "rec_td",
    "fum_lost", "fgm", "fga", "fgm_lng", "xpm",
    "sack", "int", "def_td", "st_td", "fum_rec", "safe", "pts_allow",
    "off_snp", "tm_off_snp", "gp",
)

DEFAULT_TIERS = {"legendary": 30.0, "epic": 20.0, "rare": 12.0}

PHASE_LIVE = "live"
PHASE_INTERMISSION = "intermission"
PHASE_RECAP = "recap"
PHASE_PREGAME = "pregame"
PHASE_IDLE = "idle"

#: Screen key -> the phases it draws in. Outside them display() returns False
#: and the core rotates straight past. This is the "Game day" table from the
#: user story, plus the screens it left to judgement.
SCREEN_PHASES = {
    "player_card": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
    "leaderboard": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
    # Alerts are only ever raised while a game is live; one that is still
    # queued when the last game ends is shown rather than dropped.
    "big_play": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
    "dud_alert": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP},
    "hot_pickups": {PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
    "position_kings": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP},
    "injury_report": {PHASE_PREGAME, PHASE_RECAP},
    "watchlist": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
    "weekly_awards": {PHASE_RECAP},
    "league_matchup": {PHASE_LIVE, PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
    "season_race": {PHASE_INTERMISSION, PHASE_RECAP, PHASE_PREGAME},
}


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def scoring_key(fmt: Optional[str]) -> str:
    return SCORING_KEYS.get(str(fmt or ""), SCORING_KEYS[DEFAULT_SCORING])


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def points(player: Dict[str, Any], fmt: str) -> Optional[float]:
    """This week's fantasy points in ``fmt``, or None if the player has none."""
    return safe_float((player.get("pts") or {}).get(fmt if fmt in SCORING_KEYS else DEFAULT_SCORING))


def projection(player: Dict[str, Any], fmt: str) -> Optional[float]:
    return safe_float((player.get("proj") or {}).get(fmt if fmt in SCORING_KEYS else DEFAULT_SCORING))


def stat(player: Dict[str, Any], key: str) -> float:
    value = safe_float((player.get("stats") or {}).get(key))
    return value if value is not None else 0.0


def played(player: Dict[str, Any]) -> bool:
    """True when the player took the field (a game played or a snap taken)."""
    return stat(player, "gp") > 0 or stat(player, "off_snp") > 0


def fmt_points(value: Optional[float]) -> str:
    """Points as the panel shows them: one decimal, or a dash for none."""
    if value is None:
        return "-"
    return f"{value:.1f}"


def fmt_count(value: float) -> str:
    """A counting stat without a trailing ``.0``."""
    if value is None:
        return "0"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}"


def fmt_thousands(value: float) -> str:
    """483993 -> ``484K``; 1250000 -> ``1.3M``."""
    value = float(value or 0)
    if value >= 999_500:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{round(value / 1000):.0f}K"
    return str(int(value))


def tier_for(value: Optional[float], thresholds: Optional[Dict[str, float]] = None) -> str:
    """``legendary`` / ``epic`` / ``rare`` / ``common`` for a points total."""
    t = dict(DEFAULT_TIERS)
    if thresholds:
        for key in t:
            v = safe_float(thresholds.get(key))
            if v is not None:
                t[key] = v
    if value is None:
        return "common"
    if value >= t["legendary"]:
        return "legendary"
    if value >= t["epic"]:
        return "epic"
    if value >= t["rare"]:
        return "rare"
    return "common"


def injury_tag(status: Optional[str]) -> Optional[str]:
    if not status:
        return None
    return INJURY_TAGS.get(str(status))


def normalize_name(name: Any) -> str:
    """Lower-case letters and spaces only, suffixes dropped, for matching."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z\s-]", "", s).replace("-", " ")
    words = [w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v")]
    return " ".join(words)


# ----------------------------------------------------------------------
# Normalising Sleeper rows
# ----------------------------------------------------------------------

def _position(player_obj: Dict[str, Any]) -> Optional[str]:
    pos = player_obj.get("position")
    if pos in POSITIONS:
        return pos
    for alt in player_obj.get("fantasy_positions") or []:
        if alt in POSITIONS:
            return alt
    return None


def normalize_sleeper_rows(rows: Iterable[Dict[str, Any]], kind: str = "stats") -> Dict[str, Dict[str, Any]]:
    """Sleeper stats or projection rows -> ``{player_id: player}``.

    A player is::

        {"id": "9488", "first": "Jaxon", "last": "Smith-Njigba",
         "name": "Jaxon Smith-Njigba", "pos": "WR", "team": "SEA",
         "opp": "ARI", "game_id": "202610201",
         "pts": {"ppr": 42.5, "half_ppr": 38.0, "standard": 33.5},
         "stats": {"rec": 9.0, "rec_yd": 155.0, ...},
         "injury": "Questionable" | None}

    For ``kind="projections"`` the points land under ``"proj"`` instead of
    ``"pts"`` and the stat line is dropped. Rows for positions the plugin
    does not show (IDP, OL) and rows with no player are skipped.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        pid = row.get("player_id")
        player_obj = row.get("player") or {}
        if not pid or not isinstance(player_obj, dict):
            continue
        pos = _position(player_obj)
        if pos is None:
            continue
        raw_stats = row.get("stats") or {}
        first = str(player_obj.get("first_name") or "").strip()
        last = str(player_obj.get("last_name") or "").strip()
        team = str(row.get("team") or player_obj.get("team") or "").upper()
        pts = {
            fmt: safe_float(raw_stats.get(key))
            for fmt, key in SCORING_KEYS.items()
        }
        record: Dict[str, Any] = {
            "id": str(pid),
            "first": first,
            "last": last,
            "name": f"{first} {last}".strip(),
            "pos": pos,
            "team": team,
            "opp": str(row.get("opponent") or "").upper(),
            "game_id": str(row.get("game_id") or ""),
            "injury": player_obj.get("injury_status"),
        }
        if kind == "projections":
            record["proj"] = pts
        else:
            record["pts"] = pts
            record["stats"] = {
                k: raw_stats[k] for k in KEEP_STATS
                if k in raw_stats and safe_float(raw_stats[k]) is not None
            }
        out[record["id"]] = record
    return out


def merge_week(stats: Dict[str, Dict[str, Any]],
               projections: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """One dict per player carrying both this week's points and projection."""
    merged: Dict[str, Dict[str, Any]] = {}
    for pid, proj in (projections or {}).items():
        merged[pid] = dict(proj)
    for pid, rec in (stats or {}).items():
        base = merged.get(pid, {})
        combined = dict(base)
        combined.update(rec)
        combined["proj"] = base.get("proj") or rec.get("proj") or {}
        # Injury news is fresher on the projection feed mid-week, but the
        # stats row is the one that follows the game; take whichever says so.
        combined["injury"] = rec.get("injury") or base.get("injury")
        merged[pid] = combined
    return merged


def has_results(players: Dict[str, Dict[str, Any]], fmt: str = DEFAULT_SCORING) -> bool:
    """True once any player has scored (or lost) a point this week."""
    return any(points(p, fmt) not in (None, 0.0) for p in (players or {}).values())


# ----------------------------------------------------------------------
# Rankings
# ----------------------------------------------------------------------

def ranked(players: Dict[str, Dict[str, Any]], fmt: str,
           positions: Sequence[str] = POSITIONS, limit: int = 5) -> List[Dict[str, Any]]:
    """The top ``limit`` scorers at ``positions``, highest first.

    Ties break on name so the order (and so every golden image) is stable.
    """
    pool = [
        p for p in (players or {}).values()
        if p.get("pos") in positions and points(p, fmt) is not None
    ]
    pool.sort(key=lambda p: (-(points(p, fmt) or 0.0), p.get("name", "")))
    return pool[:max(0, int(limit))]


def kings(players: Dict[str, Dict[str, Any]], fmt: str,
          positions: Sequence[str] = POSITIONS) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
    """``[(position, top scorer or None), ...]`` in position order."""
    result = []
    for pos in positions:
        top = ranked(players, fmt, (pos,), 1)
        result.append((pos, top[0] if top else None))
    return result


def left_early(player: Dict[str, Any]) -> bool:
    """Under a quarter of the team's offensive snaps, or now injured.

    Kickers and defences are exempt from the snap test: their snap counts
    are not offensive snaps.
    """
    if injury_tag(player.get("injury")) in ("O", "IR", "D", "SUS"):
        return True
    if player.get("pos") in ("K", "DEF"):
        return False
    team_snaps = stat(player, "tm_off_snp")
    if team_snaps <= 0:
        return False
    return stat(player, "off_snp") / team_snaps < 0.25


def busts(players: Dict[str, Dict[str, Any]], fmt: str, min_projection: float = 12.0,
          final_teams: Optional[Iterable[str]] = None, limit: int = 3,
          positions: Sequence[str] = POSITIONS) -> List[Dict[str, Any]]:
    """The players who fell furthest below a projection of ``min_projection``+.

    Only players who took the field count (a healthy scratch is not a bust),
    and when ``final_teams`` is given only players whose game is over -- the
    board never calls a bust at halftime. Each entry is
    ``{"player", "proj", "pts", "miss", "left_early"}``.
    """
    final = set(final_teams) if final_teams is not None else None
    out = []
    for p in (players or {}).values():
        if p.get("pos") not in positions:
            continue
        proj = projection(p, fmt)
        pts = points(p, fmt)
        if proj is None or pts is None or proj < min_projection:
            continue
        if not played(p):
            continue
        if final is not None and p.get("team") not in final:
            continue
        miss = proj - pts
        if miss <= 0:
            continue
        out.append({"player": p, "proj": proj, "pts": pts, "miss": miss,
                    "left_early": left_early(p)})
    out.sort(key=lambda b: (-b["miss"], b["player"].get("name", "")))
    return out[:max(0, int(limit))]


def booms(players: Dict[str, Dict[str, Any]], fmt: str, limit: int = 3,
          positions: Sequence[str] = POSITIONS) -> List[Dict[str, Any]]:
    """The players who beat their projection by the most."""
    out = []
    for p in (players or {}).values():
        if p.get("pos") not in positions:
            continue
        proj, pts = projection(p, fmt), points(p, fmt)
        if proj is None or pts is None or pts <= proj:
            continue
        out.append({"player": p, "proj": proj, "pts": pts, "gain": pts - proj})
    out.sort(key=lambda b: (-b["gain"], b["player"].get("name", "")))
    return out[:max(0, int(limit))]


def injury_report(players: Dict[str, Dict[str, Any]], fmt: str, limit: int = 5,
                  min_projection: float = 6.0,
                  positions: Sequence[str] = POSITIONS,
                  importance: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """Tagged players who matter this week, most important first.

    "Matter" means worth ``min_projection`` points or more. Sleeper projects
    a player who is already ruled Out for next to nothing, which would hide
    exactly the news people want, so ``importance`` (per-game season
    average, say) stands in when it is higher than the projection.
    """
    out = []
    for p in (players or {}).values():
        if p.get("pos") not in positions or p.get("pos") == "DEF":
            continue
        tag = injury_tag(p.get("injury"))
        if not tag:
            continue
        proj = projection(p, fmt) or 0.0
        weight = max(proj, safe_float((importance or {}).get(p.get("id"))) or 0.0)
        if weight < min_projection:
            continue
        out.append({"player": p, "tag": tag, "proj": weight})
    out.sort(key=lambda e: (-e["proj"], INJURY_SEVERITY.get(e["tag"], 9), e["player"].get("name", "")))
    return out[:max(0, int(limit))]


# ----------------------------------------------------------------------
# Stat lines
# ----------------------------------------------------------------------

def stat_lines(player: Dict[str, Any]) -> List[List[Tuple[str, str]]]:
    """The stat lines behind a score, most important line first.

    Each line is a list of ``(number, label)`` parts, e.g.
    ``[[("9", "REC"), ("155", "YD"), ("3", "TD")]]``. Renderers show as many
    lines, and as many parts of each, as the panel has room for.
    """
    pos = player.get("pos")
    s = lambda key: stat(player, key)  # noqa: E731 - local shorthand
    lines: List[List[Tuple[str, str]]] = []

    def receiving() -> List[Tuple[str, str]]:
        line = [(fmt_count(s("rec")), "REC"), (fmt_count(s("rec_yd")), "YD")]
        if s("rec_td"):
            line.append((fmt_count(s("rec_td")), "TD"))
        return line

    def rushing() -> List[Tuple[str, str]]:
        line = [(fmt_count(s("rush_yd")), "RUSH YD")]
        if s("rush_td"):
            line.append((fmt_count(s("rush_td")), "TD"))
        return line

    if pos == "QB":
        line = [(fmt_count(s("pass_yd")), "PASS YD"), (fmt_count(s("pass_td")), "TD")]
        if s("pass_int"):
            line.append((fmt_count(s("pass_int")), "INT"))
        lines.append(line)
        if s("rush_yd") >= 10 or s("rush_td"):
            lines.append(rushing())
    elif pos == "RB":
        if s("rush_att") or s("rush_yd") or s("rush_td"):
            lines.append(rushing())
        if s("rec") or s("rec_yd"):
            lines.append(receiving())
    elif pos in ("WR", "TE"):
        lines.append(receiving())
        if s("rush_yd") >= 10 or s("rush_td"):
            lines.append(rushing())
    elif pos == "K":
        line = [(fmt_count(s("fgm")), "FG"), (fmt_count(s("xpm")), "XP")]
        lines.append(line)
        if s("fgm_lng"):
            lines.append([(fmt_count(s("fgm_lng")), "YD LONG")])
    elif pos == "DEF":
        line = []
        if s("int"):
            line.append((fmt_count(s("int")), "INT"))
        if s("sack"):
            line.append((fmt_count(s("sack")), "SACK"))
        if s("fum_rec"):
            line.append((fmt_count(s("fum_rec")), "FUM"))
        if line:
            lines.append(line)
        second = []
        tds = s("def_td") + s("st_td")
        if tds:
            second.append((fmt_count(tds), "TD"))
        second.append((fmt_count(s("pts_allow")), "PTS ALLOWED"))
        lines.append(second)
    if s("fum_lost") and pos not in ("K", "DEF"):
        lines.append([(fmt_count(s("fum_lost")), "FUM LOST")])
    return [line for line in lines if line]


def stat_compact(player: Dict[str, Any]) -> str:
    """One short line for a 64-wide panel, in fantasy shorthand.

    Catches-yards-touchdowns as ``9-155-3`` for pass catchers, and a plain
    ``248 YD 3 TD`` for passers and runners.
    """
    pos = player.get("pos")
    s = lambda key: stat(player, key)  # noqa: E731
    if pos in ("WR", "TE") or (pos == "RB" and s("rec_yd") > s("rush_yd")):
        return f"{fmt_count(s('rec'))}-{fmt_count(s('rec_yd'))}-{fmt_count(s('rec_td'))}"
    if pos == "QB":
        return f"{fmt_count(s('pass_yd'))} YD {fmt_count(s('pass_td') + s('rush_td'))} TD"
    if pos == "RB":
        return f"{fmt_count(s('rush_yd'))} YD {fmt_count(s('rush_td') + s('rec_td'))} TD"
    if pos == "K":
        return f"{fmt_count(s('fgm'))} FG {fmt_count(s('xpm'))} XP"
    if pos == "DEF":
        return f"{fmt_count(s('int') + s('fum_rec'))} TO {fmt_count(s('sack'))} SK"
    return ""


def display_last(player: Dict[str, Any]) -> str:
    """The name a panel shows: last name, or the nickname for a defence."""
    if player.get("pos") == "DEF":
        return str(player.get("last") or player.get("team") or "")
    return str(player.get("last") or player.get("name") or "")


def display_initial_last(player: Dict[str, Any]) -> str:
    """``J. SMITH-NJIGBA`` -- for rows where two players could share a name."""
    if player.get("pos") == "DEF":
        return display_last(player)
    first = str(player.get("first") or "")
    last = display_last(player)
    return f"{first[:1]}. {last}" if first else last


# ----------------------------------------------------------------------
# Game phases
# ----------------------------------------------------------------------

def game_states(games: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"pre": 0, "in": 0, "post": 0}
    for g in games or []:
        state = g.get("state")
        if state in counts:
            counts[state] += 1
    return counts


def game_phase(season_type: Optional[str], games: Sequence[Dict[str, Any]],
               weekday: int) -> Tuple[str, bool]:
    """Where the NFL week is, and whether results come from the current week.

    ``games`` are the current week's games (``{"state": "pre"|"in"|"post"}``)
    and ``weekday`` is ``datetime.weekday()`` in the board's timezone
    (Monday 0). Returns ``(phase, use_current_week)``: the second value is
    False when nothing has kicked off yet, so results come from last week.
    """
    if season_type not in ("regular",):
        return PHASE_IDLE, False
    counts = game_states(games)
    if counts["in"]:
        return PHASE_LIVE, True
    if counts["post"]:
        if counts["pre"]:
            return PHASE_INTERMISSION, True
        return PHASE_RECAP, True
    # Nothing has kicked off this week: Tuesday and Wednesday belong to last
    # week's results, Thursday through Monday to the build-up to kickoff.
    if weekday in (1, 2):
        return PHASE_RECAP, False
    return PHASE_PREGAME, False


def teams_by_state(games: Sequence[Dict[str, Any]]) -> Dict[str, set]:
    """``{"pre": {...}, "in": {...}, "post": {...}}`` of Sleeper abbreviations."""
    out: Dict[str, set] = {"pre": set(), "in": set(), "post": set()}
    for g in games or []:
        state = g.get("state")
        if state in out:
            out[state].update(t for t in (g.get("home"), g.get("away")) if t)
    return out


# ----------------------------------------------------------------------
# Big plays
# ----------------------------------------------------------------------

def points_snapshot(players: Dict[str, Dict[str, Any]], fmt: str) -> Dict[str, float]:
    return {pid: v for pid, v in ((pid, points(p, fmt)) for pid, p in (players or {}).items())
            if v is not None}


def detect_big_plays(previous: Optional[Dict[str, float]], players: Dict[str, Dict[str, Any]],
                     fmt: str, threshold: float, active_teams: Optional[Iterable[str]] = None,
                     watch_ids: Iterable[str] = (), watch_threshold: Optional[float] = None,
                     now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Players whose points jumped by ``threshold`` or more since ``previous``.

    ``previous`` of None means "first look this session": nothing is an
    alert, because the whole week's score would look like one jump.
    ``active_teams`` limits alerts to clubs whose game is live or just ended
    (a late stat correction on Tuesday is not a big play). Watchlist
    players use ``watch_threshold`` when it is lower.
    """
    if previous is None:
        return []
    active = set(active_teams) if active_teams is not None else None
    watch = set(watch_ids or ())
    stamp = time.time() if now is None else now
    alerts = []
    for pid, p in (players or {}).items():
        cur = points(p, fmt)
        if cur is None:
            continue
        before = previous.get(pid, 0.0)
        gain = cur - before
        limit = threshold
        if pid in watch and watch_threshold is not None:
            limit = min(threshold, watch_threshold)
        if gain < limit - 1e-9:
            continue
        if active is not None and p.get("team") not in active:
            continue
        alerts.append({
            "key": f"{pid}:{round(cur, 2)}",
            "id": pid,
            "name": p.get("name", ""),
            "first": p.get("first", ""),
            "last": p.get("last", ""),
            "pos": p.get("pos", ""),
            "team": p.get("team", ""),
            "opp": p.get("opp", ""),
            "gain": round(gain, 2),
            "total": round(cur, 2),
            "detected_at": stamp,
            "desc": None,
            "td": False,
            "watch": pid in watch,
        })
    alerts.sort(key=lambda a: -a["gain"])
    return alerts


_PLAY_RE = re.compile(
    r"^(?P<who>.+?)\s+(?P<yds>\d+)\s+Yd\s+(?P<kind>pass from|Rush|Run|Field Goal|"
    r"Interception Return|Fumble Return|Fumble Recovery|Punt Return|Kickoff Return|"
    r"Blocked Punt Return|Blocked Field Goal Return|Return)",
    re.IGNORECASE,
)

_RETURN_LABELS = {
    "interception return": "PICK SIX",
    "fumble return": "FUMBLE RETURN TD",
    "fumble recovery": "FUMBLE TD",
    "punt return": "PUNT RETURN TD",
    "kickoff return": "KICK RETURN TD",
    "blocked punt return": "BLOCKED PUNT TD",
    "blocked field goal return": "BLOCKED FG TD",
    "return": "RETURN TD",
}


def describe_scoring_play(plays: Sequence[Dict[str, Any]], player: Dict[str, Any]) -> Optional[Tuple[str, bool]]:
    """Describe the newest scoring play this player was part of.

    ``plays`` are ESPN ``scoringPlays`` (oldest first); ESPN writes them as
    ``"Jaxon Smith-Njigba 82 Yd pass from Drew Lock (Jason Myers Kick)"``.
    Returns ``("82-YD TD CATCH", True)``, ``("48-YD FIELD GOAL", False)`` and
    so on, or None when no scoring play names the player. Team defences are
    matched on the scoring team and a return or safety.
    """
    pos = player.get("pos")
    team = player.get("team")
    name = normalize_name(player.get("name"))
    for play in reversed(list(plays or [])):
        text = str(play.get("text") or "")
        play_team = play.get("team")
        if pos == "DEF":
            if play_team != team:
                continue
            kind_text = str((play.get("type") or {}).get("text") or "").lower()
            if "safety" in kind_text:
                return "SAFETY", False
            m = _PLAY_RE.match(text)
            if m and m.group("kind").lower() in _RETURN_LABELS:
                return f"{m.group('yds')}-YD {_RETURN_LABELS[m.group('kind').lower()]}", True
            continue
        m = _PLAY_RE.match(text)
        if not m or not name:
            continue
        who = normalize_name(m.group("who"))
        kind = m.group("kind").lower()
        yds = m.group("yds")
        if kind == "pass from":
            passer = normalize_name(text[m.end():].split("(")[0])
            if who == name:
                return f"{yds}-YD TD CATCH", True
            if passer == name:
                return f"{yds}-YD TD PASS", True
            continue
        if who != name:
            continue
        if kind in ("rush", "run"):
            return f"{yds}-YD TD RUN", True
        if kind == "field goal":
            return f"{yds}-YD FIELD GOAL", False
        if kind in _RETURN_LABELS:
            return f"{yds}-YD {_RETURN_LABELS[kind]}", True
    return None


class AlertQueue:
    """Big-play alerts waiting for the panel.

    An alert is held back for the spoiler delay, shown at most once, spaced
    at least ``min_gap`` seconds apart, and dropped if it is still unshown
    after ``max_age`` seconds -- a touchdown from twenty minutes ago is not
    news.
    """

    def __init__(self, min_gap: float = 60.0, max_age: float = 900.0, max_len: int = 12):
        self.min_gap = float(min_gap)
        self.max_age = float(max_age)
        self.max_len = int(max_len)
        self.pending: List[Dict[str, Any]] = []
        self.seen_keys: List[str] = []
        self.last_shown_at = 0.0
        self.current: Optional[Dict[str, Any]] = None

    def add(self, alerts: Iterable[Dict[str, Any]]) -> int:
        added = 0
        for alert in alerts or []:
            key = alert.get("key")
            if not key or key in self.seen_keys or any(a.get("key") == key for a in self.pending):
                continue
            self.pending.append(alert)
            added += 1
        self.pending.sort(key=lambda a: (-(1 if a.get("watch") else 0), a.get("detected_at", 0), -a.get("gain", 0)))
        del self.pending[self.max_len:]
        return added

    def expire(self, now: float) -> None:
        self.pending = [a for a in self.pending if now - a.get("detected_at", now) <= self.max_age]

    def ready(self, now: float, delay: float = 0.0) -> List[Dict[str, Any]]:
        """Alerts past the spoiler delay, oldest first."""
        self.expire(now)
        return [a for a in self.pending if now - a.get("detected_at", now) >= delay]

    def can_show(self, now: float, delay: float = 0.0) -> bool:
        if self.current is not None:
            return True
        return bool(self.ready(now, delay)) and now - self.last_shown_at >= self.min_gap

    def take(self, now: float, delay: float = 0.0) -> Optional[Dict[str, Any]]:
        """The alert to show now (the one already on screen, else the next)."""
        if self.current is not None:
            return self.current
        if not self.can_show(now, delay):
            return None
        alert = self.ready(now, delay)[0]
        self.pending.remove(alert)
        self.seen_keys.append(alert["key"])
        del self.seen_keys[:-200]
        self.current = dict(alert, shown_at=now)
        self.last_shown_at = now
        return self.current

    def finish(self) -> None:
        self.current = None

    def clear(self) -> None:
        self.pending = []
        self.current = None


class DelayedView:
    """Holds back live snapshots for viewers watching a delayed stream.

    ``push`` every fresh snapshot with its time; ``view(now, delay)`` returns
    the newest one at least ``delay`` seconds old, or the oldest held when
    none is that old yet, so the board never shows the future.
    """

    def __init__(self, keep_seconds: float = 180.0):
        self.keep_seconds = float(keep_seconds)
        self.items: List[Tuple[float, Any]] = []

    def push(self, stamp: float, value: Any) -> None:
        self.items.append((stamp, value))
        cutoff = stamp - self.keep_seconds
        while len(self.items) > 1 and self.items[1][0] <= cutoff:
            self.items.pop(0)

    def view(self, now: float, delay: float) -> Any:
        if not self.items:
            return None
        if delay <= 0:
            return self.items[-1][1]
        eligible = [v for ts, v in self.items if now - ts >= delay]
        return eligible[-1] if eligible else self.items[0][1]


# ----------------------------------------------------------------------
# Watchlist, awards, trending
# ----------------------------------------------------------------------

def match_watchlist(names: Iterable[str], players: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """``{player_id: typed name}`` for the watchlist entries that resolve.

    A full name wins; a bare last name counts only when it is unique, so
    "Allen" does not quietly pick one of the league's four Allens. A team
    abbreviation after the name ("Josh Allen BUF") narrows it.
    """
    by_full: Dict[str, List[str]] = {}
    by_last: Dict[str, List[str]] = {}
    for pid, p in (players or {}).items():
        by_full.setdefault(normalize_name(p.get("name")), []).append(pid)
        by_last.setdefault(normalize_name(p.get("last")), []).append(pid)
    found: Dict[str, str] = {}
    for raw in names or []:
        typed = str(raw or "").strip()
        if not typed:
            continue
        parts = typed.split()
        team = None
        if len(parts) > 1 and parts[-1].upper() in {p.get("team") for p in players.values()}:
            team = parts[-1].upper()
            typed_name = " ".join(parts[:-1])
        else:
            typed_name = typed
        key = normalize_name(typed_name)
        candidates = by_full.get(key) or []
        if not candidates:
            last_only = by_last.get(key) or []
            candidates = last_only
        if team:
            candidates = [pid for pid in candidates if players[pid].get("team") == team]
        if len(candidates) == 1:
            found[candidates[0]] = typed
        elif len(candidates) > 1:
            # Several matches on a full name: prefer the one who plays.
            scored = [pid for pid in candidates if players[pid].get("proj") or players[pid].get("pts")]
            if len(scored) == 1:
                found[scored[0]] = typed
    return found


def weekly_awards(players: Dict[str, Dict[str, Any]], fmt: str, min_projection: float = 12.0,
                  waiver_ids: Iterable[str] = (),
                  positions: Sequence[str] = POSITIONS) -> List[Dict[str, Any]]:
    """Tuesday's trophy screens: MVP, bust, waiver hero, best at each position.

    Each award is ``{"key", "title", "short", "player", "value", "note"}``
    where ``short`` is the title for narrow panels, ``value`` the points and
    ``note`` a short second line.
    """
    awards: List[Dict[str, Any]] = []
    top = ranked(players, fmt, positions, 1)
    if top:
        p = top[0]
        awards.append({"key": "mvp", "title": "MVP OF THE WEEK", "short": "WEEK MVP", "player": p,
                       "value": points(p, fmt), "note": f"{p.get('pos')} {p.get('team')}"})
    worst = busts(players, fmt, min_projection, None, 1, positions)
    if worst:
        b = worst[0]
        note = "LEFT EARLY" if b["left_early"] else f"PROJ {fmt_points(b['proj'])}"
        awards.append({"key": "bust", "title": "BUST OF THE WEEK", "short": "WEEK BUST", "player": b["player"],
                       "value": b["pts"], "note": note})
    boom = booms(players, fmt, 1, positions)
    if boom:
        b = boom[0]
        awards.append({"key": "boom", "title": "BIGGEST BOOM", "short": "BIG BOOM", "player": b["player"],
                       "value": b["pts"], "note": f"+{fmt_points(b['gain'])} VS PROJ"})
    waiver = [players[pid] for pid in waiver_ids if pid in players and points(players[pid], fmt) is not None]
    if waiver:
        waiver.sort(key=lambda p: -(points(p, fmt) or 0.0))
        p = waiver[0]
        awards.append({"key": "waiver", "title": "WAIVER HERO", "short": "WAIVER HERO", "player": p,
                       "value": points(p, fmt), "note": "LAST WEEK'S TOP ADD"})
    return awards


def trending_entries(trending: Sequence[Dict[str, Any]], lookup: Dict[str, Dict[str, Any]],
                     limit: int = 3, positions: Sequence[str] = POSITIONS) -> List[Dict[str, Any]]:
    """Sleeper trending rows -> ``[{"player", "count"}]`` for players we know.

    Team defences come back from Sleeper keyed by abbreviation ("TB").
    """
    out = []
    for row in trending or []:
        pid = str((row or {}).get("player_id") or "")
        player = lookup.get(pid)
        if not player or player.get("pos") not in positions:
            continue
        out.append({"player": player, "count": safe_float(row.get("count")) or 0.0})
        if len(out) >= limit:
            break
    return out
