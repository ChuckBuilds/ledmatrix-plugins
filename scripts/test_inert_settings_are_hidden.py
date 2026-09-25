#!/usr/bin/env python3
"""A scoreboard must not draw a control that cannot affect anything.

Three settings are copied into every scoreboard schema regardless of whether
the plugin's leagues can use them, because the sports lineages are copies of
each other (CLAUDE.md non-negotiable #7) and a schema is easier to copy than to
re-derive. Counted before this check existed: **76 controls across nine
plugins** that no value could change.

  * ``other_games_divisions`` -- the FBS / FCS / Other checkboxes. ESPN
    publishes those group rosters for **college football and nothing else**
    (``sports.py _DIVISION_GROUPS_BY_LEAGUE``, identical in all nine copies),
    so everywhere else ``_game_divisions`` resolves nothing, the filter fails
    open, and the boxes are decoration. Soccer offered them on the Champions
    League and the World Cup.
  * ``other_games_min_quality`` -- "ranked" needs a poll. On a league without
    one the rank table stays empty and ``_passes_other_filters`` fails open, so
    the setting has exactly one meaningful value.
  * ``display_options.show_ranking`` -- worse than inert on a pollless league.
    The rank badge *replaces* the record, so ticking it erased the records
    ``show_records`` was drawing. (basketball-scoreboard is the exception: its
    ``_get_team_annotation`` falls back to the record. The other lineages do
    not -- see the note at the bottom of this file.)

Plus two that are dead everywhere:

  * ``scroll_settings.scroll_delay`` -- every copy's own description has read
    "Kept so saved configs still load; ignored" for releases, and the core
    paces scrolling off ``scroll_speed`` and the panel refresh. ufc reads it
    into a local and discards it, with a comment saying so.
  * ``customization.layout.ranking`` -- no reader. The rank badge shares the
    records row and is positioned by ``layout.record``.

Hidden means ``"x-display": "hidden"``: the property stays declared, so a
config already carrying it keeps validating and nothing is lost on upgrade,
but the form draws no control (core ``plugin_config.html`` ``prop_is_hidden``
and ``api_v3._is_hidden_prop``).

WHICH LEAGUES HAVE A POLL is measured, not assumed. The code's heuristic is
``"college" in league or "ncaa" in league``; probing ESPN's /rankings endpoint
on 2026-09-24 found it wrong in one direction that matters here:

    college-football            200, 125 teams      mlb/nba/wnba/nfl/nhl   404
    mens/womens-college-bball   200, 50 each        minor-league-baseball  400
    mens/womens-college-hockey  200, 4 / 5          afl, rugby-league 3    404
    mens/womens-college-lax     200, 28 / 33        soccer eng.1           404
    college-baseball            404  <-- exception

college-baseball's slug is right (/scoreboard and /standings answer 200 on it)
and out of season is not the explanation -- men's college lacrosse and hockey
are equally out of season and both answer 200 with real poll blocks. So
baseball-scoreboard narrows the heuristic with ``_NO_POLL_COLLEGE_LEAGUES``.

Run: <core-venv>/bin/python scripts/test_inert_settings_are_hidden.py
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_DIR = os.path.join(REPO, "plugins")

#: Schema league blocks whose league publishes a poll. Anything not listed for
#: a plugin is treated as pollless, which is the safe direction: a block wrongly
#: listed here would let an inert control stay visible, never the reverse.
POLL_LIVE = {
    "football-scoreboard": {"ncaa_fb"},
    "basketball-scoreboard": {"ncaam", "ncaaw"},
    "hockey-scoreboard": {"ncaa_mens", "ncaa_womens"},
    "lacrosse-scoreboard": {"ncaa_mens", "ncaa_womens"},
}

#: Schema league blocks whose league has FBS/FCS division rosters.
DIV_LIVE = {"football-scoreboard": {"ncaa_fb"}}

results = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    results.append((label, ok))


def leaves(node, path=""):
    out = {}
    for key, value in (node.get("properties") or {}).items():
        if not isinstance(value, dict):
            continue
        where = "%s.%s" % (path, key) if path else key
        out[where] = value
        out.update(leaves(value, where))
    return out


def classify(plugin, path):
    """Why this property must be hidden, or None if it may stay visible."""
    block = path.split(".")[0]
    if path.endswith("other_games_divisions"):
        if block in DIV_LIVE.get(plugin, set()):
            return None
        return "FBS/FCS rosters exist for college football only"
    if path.endswith("other_games_min_quality"):
        if block in POLL_LIVE.get(plugin, set()):
            return None
        return "no poll to rank against"
    if path.endswith("display_options.show_ranking"):
        if block in POLL_LIVE.get(plugin, set()):
            return None
        return "no poll; the badge replaces the record"
    if path.endswith("scroll_settings.scroll_delay"):
        return "ignored; scroll_speed is the only pacing control"
    if path.endswith("customization.layout.ranking"):
        return "no reader; layout.record positions the badge"
    return None


def main():
    schemas = sorted(
        (name, os.path.join(PLUGINS_DIR, name, "config_schema.json"))
        for name in os.listdir(PLUGINS_DIR)
        if os.path.isfile(os.path.join(PLUGINS_DIR, name, "sports.py"))
        and os.path.isfile(os.path.join(PLUGINS_DIR, name, "config_schema.json"))
    )
    if not schemas:
        print("SKIP: no scoreboard schemas found; the layout changed")
        return 2

    print("no scoreboard draws a control that cannot affect anything")
    exposed = []
    for plugin, path in schemas:
        with open(path, encoding="utf-8") as handle:
            found = leaves(json.load(handle))
        bad = []
        for prop_path, node in sorted(found.items()):
            reason = classify(plugin, prop_path)
            if reason and node.get("x-display") != "hidden":
                bad.append((prop_path, reason))
        check("%s: %d inert control(s) drawn" % (plugin, len(bad)), not bad)
        exposed += [(plugin,) + b for b in bad]
    for plugin, prop_path, reason in exposed:
        print("        %s: %s -- %s" % (plugin, prop_path, reason))

    print("\nhiding is reversible: every hidden property is still declared")
    for plugin, path in schemas:
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
        found = leaves(schema)
        hidden = [p for p, n in found.items() if n.get("x-display") == "hidden"]
        # A declared property is exactly what `leaves` walked, so presence here
        # IS the declaration. What matters is that it was not deleted instead.
        undocumented = [p for p in hidden
                        if "HIDDEN" not in (found[p].get("description") or "")]
        check("%s: %d hidden, all explaining why" % (plugin, len(hidden)),
              not undocumented, undocumented)

    print("\nthe settings that DO work are still reachable")
    for plugin, blocks in sorted(POLL_LIVE.items()):
        with open(os.path.join(PLUGINS_DIR, plugin, "config_schema.json"),
                  encoding="utf-8") as handle:
            found = leaves(json.load(handle))
        for block in sorted(blocks):
            live = [p for p, n in found.items()
                    if p.split(".")[0] == block
                    and (p.endswith("other_games_min_quality")
                         or p.endswith("display_options.show_ranking"))
                    and n.get("x-display") != "hidden"]
            check("%s/%s: poll-backed controls still offered (%d)"
                  % (plugin, block, len(live)), len(live) >= 2, live)

    print("\nand the fetch is gated, so a pollless league never asks")
    for plugin, _ in schemas:
        source_path = os.path.join(PLUGINS_DIR, plugin, "sports.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        marker = "def _fetch_team_rankings"
        start = source.find(marker)
        body = source[start:start + 2000] if start >= 0 else ""
        check("%s: _fetch_team_rankings consults _league_has_rankings" % plugin,
              "_league_has_rankings()" in body)

    print()
    failed = [name for name, passed in results if not passed]
    print("%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


# NOTE, deliberately not asserted here: on a pollless league an empty rank
# table makes `show_ranking` ERASE the record rather than fall back to it, in
# every lineage except basketball-scoreboard, whose `_get_team_annotation`
# returns the record when no rank is found. Hiding the control and gating the
# fetch stops that for anyone configuring fresh, but a config saved with
# `show_ranking: true` still hits it. Porting basketball's fallback to the
# other lineages would close it -- and would also change what a poll-backed
# college board draws for an unranked team (blank today, the record after), so
# it is a display decision, not a cleanup, and is left for its own change.


if __name__ == "__main__":
    sys.exit(main())
