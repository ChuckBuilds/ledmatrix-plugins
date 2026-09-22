"""The stat categories this plugin can show, and how to find them in ESPN's feed.

Each entry ties together three things that would otherwise drift apart: the
config key the web UI toggles, the ESPN category name(s) to match, and the
titles the renderer draws.

ESPN is not consistent about category naming across sports and seasons
(``totalTackles`` and ``tackles`` have both been served for the NFL), so a
category matches on any of several ``espn_names`` and, failing that, on a
keyword pair against the feed's own ``displayName``. Matching on the config
key alone would silently drop a category the moment ESPN renamed one, which
on a panel looks identical to "no data".

Order here is the order the ticker shows them in; the config only decides
which are on.
"""

from typing import Dict, List, NamedTuple, Optional, Tuple


class StatCategory(NamedTuple):
    """One leaderboard the ticker can draw."""

    #: Config key under ``categories`` in config_schema.json.
    key: str
    #: Title drawn on the category card when it fits.
    title: str
    #: Shorter title used when the full one will not fit the panel.
    short_title: str
    #: ESPN ``categories[].name`` values that mean this stat, best first.
    espn_names: Tuple[str, ...]
    #: All of these must appear in ESPN's ``displayName`` for the keyword
    #: fallback to accept a category.
    keywords: Tuple[str, ...]
    #: Whether this category is on in a fresh install.
    default_enabled: bool


#: The fantasy-relevant categories, in ticker order.
#:
#: Defaults are the six that decide a standard fantasy league's scoring;
#: receptions and the defensive/IDP categories ship off so a first install
#: is a readable ticker rather than a ten-minute one.
CATEGORIES: Tuple[StatCategory, ...] = (
    StatCategory(
        key="passing_yards",
        title="PASSING YARDS",
        short_title="PASS YDS",
        espn_names=("passingYards",),
        keywords=("passing", "yards"),
        default_enabled=True,
    ),
    StatCategory(
        key="passing_touchdowns",
        title="PASSING TDS",
        short_title="PASS TDS",
        espn_names=("passingTouchdowns",),
        keywords=("passing", "touchdown"),
        default_enabled=True,
    ),
    StatCategory(
        key="rushing_yards",
        title="RUSHING YARDS",
        short_title="RUSH YDS",
        espn_names=("rushingYards",),
        keywords=("rushing", "yards"),
        default_enabled=True,
    ),
    StatCategory(
        key="rushing_touchdowns",
        title="RUSHING TDS",
        short_title="RUSH TDS",
        espn_names=("rushingTouchdowns",),
        keywords=("rushing", "touchdown"),
        default_enabled=True,
    ),
    StatCategory(
        key="receiving_yards",
        title="RECEIVING YARDS",
        short_title="REC YDS",
        espn_names=("receivingYards",),
        keywords=("receiving", "yards"),
        default_enabled=True,
    ),
    StatCategory(
        key="receiving_touchdowns",
        title="RECEIVING TDS",
        short_title="REC TDS",
        espn_names=("receivingTouchdowns",),
        keywords=("receiving", "touchdown"),
        default_enabled=True,
    ),
    StatCategory(
        key="receptions",
        title="RECEPTIONS",
        short_title="REC",
        espn_names=("receptions",),
        keywords=("reception",),
        default_enabled=False,
    ),
    StatCategory(
        key="sacks",
        title="SACKS",
        short_title="SACKS",
        espn_names=("sacks", "totalSacks"),
        keywords=("sack",),
        default_enabled=False,
    ),
    StatCategory(
        key="interceptions",
        title="INTERCEPTIONS",
        short_title="INTS",
        # ``interceptions`` is the quarterback's thrown-interception count in
        # some ESPN payloads; the defensive leaderboard is the one users
        # expect from a category called INTERCEPTIONS, so it is preferred.
        espn_names=("defensiveInterceptions", "interceptions"),
        keywords=("interception",),
        default_enabled=False,
    ),
    StatCategory(
        key="total_tackles",
        title="TACKLES",
        short_title="TACKLES",
        espn_names=("totalTackles", "tackles"),
        keywords=("tackle",),
        default_enabled=False,
    ),
    StatCategory(
        key="quarterback_rating",
        title="QB RATING",
        short_title="QB RTG",
        espn_names=("quarterbackRating", "QBRating", "passerRating"),
        keywords=("rating",),
        default_enabled=False,
    ),
)

CATEGORIES_BY_KEY: Dict[str, StatCategory] = {c.key: c for c in CATEGORIES}

#: What ``categories`` looks like with nothing configured. Mirrors the
#: ``default`` in config_schema.json; the two are asserted equal by
#: test_nfl_stat_leaders.py so they cannot drift.
DEFAULT_CATEGORY_TOGGLES: Dict[str, bool] = {
    c.key: c.default_enabled for c in CATEGORIES
}


def enabled_categories(toggles: Optional[Dict[str, object]]) -> List[StatCategory]:
    """The categories to show, in ticker order.

    A key missing from ``toggles`` keeps its shipped default, so a config
    hand-edited before a category existed still behaves like a fresh install
    rather than turning everything off.
    """
    toggles = toggles if isinstance(toggles, dict) else {}
    chosen = []
    for category in CATEGORIES:
        value = toggles.get(category.key, category.default_enabled)
        if bool(value):
            chosen.append(category)
    return chosen


def match_feed_category(category: StatCategory, feed_categories: List[dict]) -> Optional[dict]:
    """Find ``category`` in an ESPN leaders payload.

    Tries the exact ESPN names in order, then falls back to requiring every
    keyword in the feed's own display name. Returns None when the feed has
    no such leaderboard.
    """
    by_name = {}
    for entry in feed_categories:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        if name and name not in by_name:
            by_name[name] = entry

    for espn_name in category.espn_names:
        entry = by_name.get(espn_name.lower())
        if entry is not None:
            return entry

    for entry in feed_categories:
        if not isinstance(entry, dict):
            continue
        haystack = " ".join(
            str(entry.get(field) or "")
            for field in ("displayName", "shortDisplayName", "name")
        ).lower()
        if haystack and all(word in haystack for word in category.keywords):
            return entry
    return None
