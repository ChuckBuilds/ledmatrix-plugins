#!/usr/bin/env python3
"""Every scoreboard must find its own config_schema.json the way the DISPLAY
loads it, not the way a test does.

WHY THIS EXISTS
---------------
src/common/sports_shared.py resolves a plugin's directory to read its
config_schema.json. That lookup feeds _schema_font_size, which decides whether
a configured font size equals the schema default. If it does, the size is a
default and gets snapped to the font's pixel grid; if it does not, it is the
user's choice and is left alone.

When the lookup fails it returns None, so *every* configured size stops looking
like a default and skips the snap. 4x6-font.ttf then renders at 6 instead of 7
-- 3px-wide glyphs instead of 4px. On a 256x64 panel that made the odds, the
team records and the date row hard to read.

That shipped. It was found by a user counting pixels on a photo of the panel,
not by any gate, because:

    PluginLoader._namespace_plugin_modules renames every bare module a plugin
    brought in (sports, game_renderer, ...) to "_plg_<plugin_id>_<module>" and
    REMOVES the bare sys.modules entry.

A class defined in sports.py still reports __module__ == "sports", but
sys.modules["sports"] is gone. Tests that import the plugin directly leave the
bare entry in place and never see it. This guard reproduces the rename, which
is the whole point.

    python scripts/test_plugin_dir_under_loader.py

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = ["afl", "baseball", "basketball", "football",
           "hockey", "lacrosse", "nrl", "soccer"]


def core_root():
    env = os.environ.get("LEDMATRIX_CORE")
    if env and (Path(env) / "src").is_dir():
        return Path(env)
    for cand in (REPO.parent / "LEDMatrix", Path.home() / "LEDMatrix"):
        if (cand / "src").is_dir():
            return cand
    return None


def load_like_the_loader(plugin_id: str, plugin_dir: Path):
    """Import sports.py under its BARE name, then rename it away.

    Both halves matter. The bare import is what makes the class report
    ``__module__ == "sports"``; the rename is what removes that key from
    sys.modules. Import it under a namespaced name instead and __module__
    points at a module that still exists, the MRO walk succeeds, and the guard
    passes while production fails -- which is exactly what the first draft of
    this file did.
    """
    safe = plugin_id.replace("-", "_")
    for stale in ("sports", f"_plg_{safe}_sports"):
        sys.modules.pop(stale, None)

    sys.path.insert(0, str(plugin_dir))
    try:
        spec = importlib.util.spec_from_file_location("sports", plugin_dir / "sports.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sports"] = mod          # bare, as the plugin's own import does
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(plugin_dir))

    # PluginLoader._namespace_plugin_modules: move it aside, drop the bare key.
    sys.modules[f"_plg_{safe}_sports"] = mod
    del sys.modules["sports"]
    return mod


def main() -> int:
    core = core_root()
    if core is None:
        print("  [skip] no LEDMatrix core checkout (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    try:
        import src.common.sports_shared  # noqa: F401
    except Exception as exc:                       # noqa: BLE001
        print(f"  [skip] core has no sports_shared yet: {exc}")
        return 2

    failures = []
    for short in PLUGINS:
        plugin_id = f"{short}-scoreboard"
        pdir = REPO / "plugins" / plugin_id
        if not (pdir / "sports.py").is_file():
            continue
        try:
            mod = load_like_the_loader(plugin_id, pdir)
        except Exception as exc:                   # noqa: BLE001
            failures.append(f"{plugin_id}: import failed -- {type(exc).__name__}: {exc}")
            continue

        base = getattr(mod, "SportsCore", None)
        if base is None:
            failures.append(f"{plugin_id}: no SportsCore")
            continue
        probe = type("Probe", (base,), {
            "_extract_game_details": lambda s, *a, **k: None,
            "_fetch_data": lambda s, *a, **k: None})
        inst = probe.__new__(probe)
        inst.logger = logging.getLogger("plugin_dir_probe")

        found = inst._plugin_dir()
        if not found:
            failures.append(
                f"{plugin_id}: _plugin_dir() is None under the loader's module "
                f"renaming -- every font size will skip its grid snap")
            continue
        if Path(found).resolve() != pdir.resolve():
            failures.append(f"{plugin_id}: _plugin_dir() -> {found}, expected {pdir}")
            continue
        size = inst._schema_font_size("detail_text")
        if size is None:
            failures.append(f"{plugin_id}: schema found but detail_text size is None")
            continue
        print(f"  [pass] {plugin_id:<22} dir ok, detail_text default = {size}")

    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
        return 1
    print(f"  {len(PLUGINS)} scoreboards resolve their schema under the real loader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
