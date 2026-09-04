#!/usr/bin/env python3
"""A scoreboard configured for scroll must actually reach its scroll renderer.

football-scoreboard shipped with `*_display_mode: "scroll"` doing nothing. The
scroll dispatch lived in `_display_external_mode()`, which nothing calls:
manifest.json registers granular modes only (nfl_recent, ncaa_fb_live, ...) and
`display()` routes every one of those to `_display_league_mode()`, which had no
scroll check. `_display_scroll_mode()` was defined, tested, and unreachable.

Every existing test missed it, in the same way:

  * test_scroll_mode.py calls `_should_use_scroll_mode("recent")` directly
  * scripts/test_scroll_card_renders.py renders `render_game_card` directly

Both prove the card renderer works. Neither proves the display path ever asks
for it. On hardware the panel switched cards while the config said scroll, and
the journal showed no scroll image from the plugin at all.

So this checks reachability rather than rendering: from `display()`, following
calls through the manager, is any scroll-rendering method reachable? It is a
static call-graph walk -- no data, no panel, no live games -- because the modes
that expose the bug need live fixtures the harness does not have.
"""
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "plugins")

#: Known-broken, recorded rather than hidden.
#:
#: ufc-scoreboard has the same defect football had -- config_schema.json offers
#: live/recent/upcoming_display_mode, and is_cycle_complete() consults
#: _should_use_scroll_mode(), but display() never mentions scrolling, so setting
#: "scroll" changes nothing on the panel. It is excluded here because unlike
#: football it has no scroll renderer to wire up: football's _display_scroll_mode
#: existed and was merely unreachable, whereas ufc would need the prepare/display
#: path written from scratch. That is a feature, not a repair, so it is not
#: bundled with this fix.
#:
#: Removing an entry from this list must make the gate pass, never fail.
KNOWN_MISSING_SCROLL = {"ufc-scoreboard"}


def scroll_render_methods(fns):
    """Methods that render a scroll frame (not merely decide about scrolling)."""
    return {n for n in fns if "scroll" in n.lower() and "display" in n.lower()}


def reachable_from(fns, entry):
    seen, stack = set(), [entry]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in fns:
            continue
        seen.add(cur)
        for node in ast.walk(fns[cur]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                stack.append(node.func.attr)
    return seen


def check(plugin):
    """Return (status, detail). status: 'pass' | 'fail' | 'skip'."""
    manager = os.path.join(PLUGINS, plugin, "manager.py")
    if not os.path.isfile(manager):
        return "skip", "no manager.py"

    with open(manager, encoding="utf-8") as fh:
        src = fh.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return "fail", f"cannot parse manager.py: {exc}"

    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "display" not in fns:
        return "skip", "no display() entry point"

    renderers = scroll_render_methods(fns)
    if not renderers:
        return "skip", "plugin has no scroll renderer"

    # Only meaningful if the plugin actually offers a scroll setting.
    schema = os.path.join(PLUGINS, plugin, "config_schema.json")
    if os.path.isfile(schema):
        with open(schema, encoding="utf-8") as fh:
            if "_display_mode" not in fh.read():
                return "skip", "no *_display_mode setting"

    reached = renderers & reachable_from(fns, "display")
    if reached:
        return "pass", ", ".join(sorted(reached))
    return "fail", (f"defined but unreachable from display(): "
                    f"{', '.join(sorted(renderers))}")


def main():
    if not os.path.isdir(PLUGINS):
        print("[skip] no plugins/ directory")
        return 2

    failures, checked = [], 0
    for plugin in sorted(os.listdir(PLUGINS)):
        if not os.path.isdir(os.path.join(PLUGINS, plugin)):
            continue
        status, detail = check(plugin)
        if status == "skip":
            continue
        checked += 1
        if status == "fail":
            if plugin in KNOWN_MISSING_SCROLL:
                print(f"  [known] {plugin}: {detail}")
                continue
            failures.append(f"{plugin}: {detail}")
        elif plugin in KNOWN_MISSING_SCROLL:
            failures.append(
                f"{plugin}: now reaches its scroll renderer -- "
                f"remove it from KNOWN_MISSING_SCROLL")

    if not checked:
        print("[skip] no scoreboard with a scroll renderer found")
        return 2

    if failures:
        print("[FAIL] scroll mode is configurable but unreachable:")
        for f in failures:
            print(f"  {f}")
        print("\nA granular mode routed to _display_league_mode() must check the "
              "league's display_mode and delegate to the scroll renderer.")
        return 1

    print(f"[pass] {checked} scoreboard(s): scroll renderer reachable from display()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
