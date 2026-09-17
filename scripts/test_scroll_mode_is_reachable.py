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

## Reachable is not enough: the frame rate has to follow

lacrosse-scoreboard passed the check above while its scroll mode was unusable.
Its renderer was reachable; the plugin just never set `enable_scrolling`, and
the core display controller only runs its 125 FPS loop for a plugin that does.
The ScrollHelper is time-based, so the strip jumped a card-width once a second
instead of scrolling. The opposite mistake is just as invisible: baseball,
basketball, hockey and ufc set the flag from "could the scroll manager be
built", which is true when every mode is 'switch', so a static scorebug was
re-rendered every 8ms (football fixed this in #487).

So every scoreboard checked here must also:

  * define `_has_any_scroll_mode()`;
  * assign `self.enable_scrolling` from exactly `self._has_any_scroll_mode()`,
    never from anything else, and never set `needs_high_fps` (which outranks
    the flag in the controller);
  * make that assignment in `__init__` after the scroll manager, the display
    mode settings and the league registry it reads are built, and again, after
    the rebuild, in any method that rebuilds one of those (a config reload).

When a LEDMatrix core checkout is available (`LEDMATRIX_CORE`), each plugin is
also constructed twice in a fresh process -- schema defaults, then every
`*_display_mode` set to scroll with every league enabled -- and the flag must be
False, then True (False for a plugin in KNOWN_MISSING_SCROLL, whose display()
cannot scroll at all).
"""
import ast
import json
import multiprocessing
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


#: What _has_any_scroll_mode() reads. The flag must be computed after the last
#: of these is (re)built, or it is computed from the previous config.
_FLAG_INPUTS = ("_scroll_manager", "_display_mode_settings")
_FLAG_INPUT_CALLS = ("_initialize_league_registry",)


def _is_self_attr(node, name):
    return (isinstance(node, ast.Attribute) and node.attr == name
            and isinstance(node.value, ast.Name) and node.value.id == "self")


def _is_has_any_call(value):
    return (isinstance(value, ast.Call) and not value.args and not value.keywords
            and _is_self_attr(value.func, "_has_any_scroll_mode"))


def high_fps_problems(plugin):
    """Static check that enable_scrolling follows _has_any_scroll_mode().

    Returns a list of human-readable problems; empty when the plugin is sound.
    """
    manager = os.path.join(PLUGINS, plugin, "manager.py")
    with open(manager, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    problems = []
    methods = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not any(m.name == "_has_any_scroll_mode" for m in methods):
        problems.append("no _has_any_scroll_mode() defined")

    init_sets_flag = False
    for method in methods:
        flag_lines, input_lines = [], []
        for node in ast.walk(method):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                for target in targets:
                    if _is_self_attr(target, "needs_high_fps"):
                        problems.append(
                            f"{method.name}() line {node.lineno}: sets needs_high_fps, "
                            f"which outranks enable_scrolling in the display controller")
                    if _is_self_attr(target, "enable_scrolling"):
                        if _is_has_any_call(value):
                            flag_lines.append(node.lineno)
                        else:
                            shown = ast.unparse(value) if value is not None else "?"
                            problems.append(
                                f"{method.name}() line {node.lineno}: enable_scrolling = "
                                f"{shown} (must be self._has_any_scroll_mode())")
                    for name in _FLAG_INPUTS:
                        # Clearing the scroll manager (cleanup) cannot turn
                        # scrolling on, so it is not a rebuild.
                        cleared = isinstance(value, ast.Constant) and value.value is None
                        if _is_self_attr(target, name) and not cleared:
                            input_lines.append(node.lineno)
            elif (isinstance(node, ast.Call)
                  and any(_is_self_attr(node.func, c) for c in _FLAG_INPUT_CALLS)):
                input_lines.append(node.lineno)
        if method.name == "__init__" and flag_lines:
            init_sets_flag = True
        if not input_lines or method.name in ("_has_any_scroll_mode",
                                              "_initialize_league_registry"):
            continue
        if not flag_lines:
            problems.append(
                f"{method.name}() rebuilds what _has_any_scroll_mode() reads "
                f"(line {max(input_lines)}) but never re-evaluates enable_scrolling")
        elif max(flag_lines) < max(input_lines):
            problems.append(
                f"{method.name}() sets enable_scrolling at line {max(flag_lines)}, "
                f"before line {max(input_lines)} rebuilds what it reads")
    if not init_sets_flag:
        problems.append("__init__ never sets enable_scrolling = self._has_any_scroll_mode()")
    return problems


def find_core():
    """A LEDMatrix core checkout for the frame-rate probe, or None."""
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""),
                      os.path.join(os.path.dirname(ROOT), "LEDMatrix")):
        if candidate and os.path.isdir(os.path.join(candidate, "src", "plugin_system")):
            return os.path.abspath(candidate)
    return None


def _schema_defaults(node):
    out = {}
    for key, prop in (node.get("properties") or {}).items():
        if prop.get("type") == "object" and "properties" in prop:
            out[key] = _schema_defaults(prop)
        elif "default" in prop:
            out[key] = prop["default"]
    return out


def _scroll_everything(node):
    for key, value in list(node.items()):
        if isinstance(value, dict):
            _scroll_everything(value)
        elif key.endswith("_display_mode"):
            node[key] = "scroll"
        elif key == "enabled" and isinstance(value, bool):
            node[key] = True


def _probe_child(conn, core, pdir, pid, mode):
    """Runs in a freshly spawned interpreter: build the plugin, report enable_scrolling."""
    import contextlib
    import importlib.util
    import logging

    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w", encoding="utf-8") as quiet, \
                contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            sys.path.insert(0, core)
            sys.path.insert(0, pdir)
            os.chdir(core)
            os.environ.setdefault("EMULATOR", "true")
            from src.plugin_system.testing import (
                MockCacheManager, MockDisplayManager, MockPluginManager)
            with open(os.path.join(pdir, "manifest.json"), encoding="utf-8") as fh:
                manifest = json.load(fh)
            with open(os.path.join(pdir, "config_schema.json"), encoding="utf-8") as fh:
                schema = json.load(fh)
            cfg = _schema_defaults(schema)
            cfg["enabled"] = True
            if mode == "scroll":
                _scroll_everything(cfg)
            entry = manifest.get("entry_point", "manager.py")
            if os.path.basename(entry) != entry or not entry.endswith(".py"):
                raise ValueError(f"entry_point {entry!r} is not a .py file in the plugin directory")
            name = entry[:-3]
            spec = importlib.util.spec_from_file_location(name, os.path.join(pdir, entry))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module      # the plugin's own imports expect it registered
            spec.loader.exec_module(module)
            plugin = getattr(module, manifest["class_name"])(
                pid, cfg, MockDisplayManager(), MockCacheManager(), MockPluginManager())
        conn.send(("ok", getattr(plugin, "enable_scrolling", None)))
    except Exception as exc:  # any construction failure is reported, not raised
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def probe_high_fps(core, plugin, mode):
    """Construct the plugin in a fresh process; return (enable_scrolling, error).

    A spawned interpreter per probe keeps one plugin's bare-name modules from
    leaking into the next, as the loader's own isolation would.
    """
    pdir = os.path.join(PLUGINS, plugin)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_probe_child, args=(child, core, pdir, plugin, mode))
    proc.start()
    child.close()
    try:
        if not parent.poll(180):
            return None, "timed out constructing the plugin"
        try:
            status, value = parent.recv()
        except EOFError:
            return None, f"construction failed: process exited with code {proc.exitcode}"
        if status == "ok":
            return value, None
        return None, f"construction failed: {value}"
    finally:
        parent.close()
        proc.join(5)
        if proc.is_alive():
            proc.terminate()
            proc.join()


def main():
    if not os.path.isdir(PLUGINS):
        print("[skip] no plugins/ directory")
        return 2

    failures, checked, fps_checked = [], 0, []
    for plugin in sorted(os.listdir(PLUGINS)):
        if not os.path.isdir(os.path.join(PLUGINS, plugin)):
            continue
        status, detail = check(plugin)
        if status == "skip":
            continue
        checked += 1
        # The frame rate applies to known-missing plugins too: a plugin whose
        # display() cannot scroll must not ask for the 125 FPS loop either.
        fps_checked.append(plugin)
        for problem in high_fps_problems(plugin):
            failures.append(f"{plugin}: high-FPS flag: {problem}")
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

    core = find_core()
    if core is None:
        print("  [note] no LEDMatrix core (set LEDMATRIX_CORE): the constructed "
              "frame-rate probe was skipped; the static check still ran")
    else:
        for plugin in fps_checked:
            want_scroll = plugin not in KNOWN_MISSING_SCROLL
            for mode, want in (("defaults", False), ("scroll", want_scroll)):
                got, error = probe_high_fps(core, plugin, mode)
                if error:
                    failures.append(f"{plugin}: frame-rate probe ({mode}): {error}")
                elif bool(got) != want:
                    loop = "1 FPS" if want else "125 FPS"
                    failures.append(
                        f"{plugin}: with {mode} display modes enable_scrolling={got!r}, "
                        f"expected {want} -- the controller would run its {loop} loop")

    if failures:
        print("[FAIL] scroll mode is unreachable, or would not run at the scroll frame rate:")
        for f in failures:
            print(f"  {f}")
        print("\nA granular mode routed to _display_league_mode() must check the "
              "league's display_mode and delegate to the scroll renderer, and "
              "enable_scrolling must be set from self._has_any_scroll_mode().")
        return 1

    probed = "" if core is None else ", constructed and probed"
    print(f"[pass] {checked} scoreboard(s): scroll renderer reachable from display(), "
          f"high-FPS flag follows _has_any_scroll_mode(){probed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
