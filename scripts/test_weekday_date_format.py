#!/usr/bin/env python3
"""Every scoreboard that offers date_format "weekday" must actually render it.

`scroll_card.date_format` is an enum in each scoreboard's config_schema.json,
and "weekday" is one of the documented choices ('weekday "Fri Sep 19"'). Seven
of the eight game_renderer.py copies reached for `datetime`, `timezone` and
`ZoneInfo` without importing any of them, so selecting that option raised
NameError -- and neither helper's except clause catches NameError:

    _weekday_for   except (ValueError, TypeError)
    _card_tzinfo   except (KeyError, ValueError, TypeError, OSError)

so it propagated out of the render instead of falling back. Only
hockey-scoreboard had the imports, which is why the bug survived: the harness
and the goldens all render the default "abbrev" format and never touch the
weekday branch.

A linter would catch the missing name, but the thing worth guarding is the
behaviour: the option is offered, so it has to work. Every copy is called
`game_renderer`, so each is loaded under its own module name rather than by
import, which would have them shadowing one another.

Run: <core-venv>/bin/python scripts/test_weekday_date_format.py
"""

import importlib.util
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# 01:00 UTC on the Tuesday is still 21:00 on the Monday in New York, so a
# result of "Tue" means _card_tzinfo() was skipped or silently fell back to
# UTC. That distinction is the only thing separating a working timezone
# conversion from one that merely does not crash.
GAME = {"game_date": "10/12", "start_time_utc": "2026-10-13T01:00:00Z"}

# Windows has no system tz database; without the tzdata package ZoneInfo
# raises and the renderer correctly falls back to UTC. That is an environment
# limitation, not a defect, so skip just that assertion when it applies.
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ZoneInfo("America/New_York")
    TZ_AVAILABLE = True
except Exception:
    TZ_AVAILABLE = False


def load_renderer_module(plugin_dir):
    """Load one plugin's game_renderer under a name of its own.

    All eight copies are called `game_renderer`, so a plain import would bind
    whichever landed in sys.modules first and silently test it eight times.
    The plugin directory goes on sys.path for the duration because one copy
    (baseball) imports a plugin-local helper.
    """
    name = "gr_%s" % plugin_dir.name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, plugin_dir / "game_renderer.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(plugin_dir))
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(plugin_dir))
        sys.modules.pop(name, None)
    return module


results = []
skipped_tz = []


def check(case, passed):
    results.append((case, passed))
    if not passed:
        print("  [FAIL] %s" % case)


def offers_weekday(plugin_dir):
    schema = plugin_dir / "config_schema.json"
    if not schema.is_file():
        return False
    try:
        return '"weekday"' in schema.read_text(encoding="utf-8")
    except OSError:
        return False


def main():
    os.chdir(str(CORE))
    sys.path.insert(0, str(CORE))
    sys.path.insert(0, str(CORE / "src"))

    targets = sorted(p.parent for p in REPO.glob("plugins/*/game_renderer.py")
                     if offers_weekday(p.parent))
    if not targets:
        print("SKIP: no plugin offers date_format weekday")
        sys.exit(2)

    for plugin in targets:
        name = plugin.name
        try:
            gr = load_renderer_module(plugin)
        except Exception as exc:
            check("%s -- game_renderer imports (%s: %s)"
                  % (name, type(exc).__name__, exc), False)
            continue

        def render(config):
            return gr.GameRenderer(128, 64, config)._format_game_date(
                GAME["game_date"], GAME)

        try:
            value = render({"scroll_card": {"date_format": "weekday"},
                            "timezone": "America/New_York"})
            check("%s -- date_format 'weekday' does not raise" % name, True)
            check("%s -- 'weekday' renders a weekday, got %r" % (name, value),
                  bool(re.match(r"^(%s)\s" % "|".join(WEEKDAYS), value)))
            if TZ_AVAILABLE:
                # UTC would say Tue; New York says Mon
                check("%s -- the configured timezone is applied, got %r" % (name, value),
                      value.startswith("Mon"))
            else:
                skipped_tz.append(name)
        except Exception as exc:
            check("%s -- date_format 'weekday' does not raise (%s: %s)"
                  % (name, type(exc).__name__, exc), False)

        try:
            render({"scroll_card": {"date_format": "weekday"}, "timezone": "Not/AZone"})
            check("%s -- an unusable timezone falls back instead of raising" % name, True)
        except Exception as exc:
            check("%s -- an unusable timezone falls back instead of raising (%s: %s)"
                  % (name, type(exc).__name__, exc), False)

        try:
            render({})
            check("%s -- the default date format still works" % name, True)
        except Exception as exc:
            check("%s -- the default date format still works (%s: %s)"
                  % (name, type(exc).__name__, exc), False)

    if skipped_tz:
        print("  note: no tz database here (pip install tzdata) -- timezone-conversion "
              "check skipped for %d plugin(s)" % len(skipped_tz))

    failed = [c for c, ok in results if not ok]
    print("%d checks across %d plugins, %s"
          % (len(results), len(targets),
             "%d FAILED" % len(failed) if failed else "all passed"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
