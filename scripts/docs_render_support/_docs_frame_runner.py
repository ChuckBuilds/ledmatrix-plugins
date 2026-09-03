#!/usr/bin/env python3
"""Render a plugin after advancing it a number of frames.

The core's ``scripts/render_plugin.py`` calls ``display()`` once, which is the
right thing for a static screen. A scrolling plugin, though, starts its strip
fully off the right edge, so the first frame is legitimately an empty panel --
and a screenshot of one says nothing about the plugin.

This runner drives the same core testing API render_plugin.py uses
(``build_full_config`` / ``PluginLoader`` / ``VisualTestDisplayManager``), then
calls ``display()`` repeatedly before snapshotting, so a ticker can be captured
mid-travel with real content on screen.

Invoked by scripts/render_docs_assets.py for shots that set ``frames``; it is
not meant to be run by hand.
"""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("EMULATOR", "true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--plugin-dir", required=True)
    parser.add_argument("--core-repo", required=True)
    parser.add_argument("--config", default="{}")
    parser.add_argument("--mock-data", default=None)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--height", type=int, default=32)
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--frame-seconds", type=float, default=0.05,
                        help="Frozen-clock seconds to advance between frames")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    sys.path.insert(0, args.core_repo)
    from src.plugin_system.testing.loading import (  # noqa: E402
        build_full_config, find_plugin_dir, load_manifest,
    )
    from src.plugin_system.testing import (  # noqa: E402
        VisualTestDisplayManager, MockCacheManager, MockPluginManager,
    )
    from src.plugin_system.plugin_loader import PluginLoader  # noqa: E402

    plugin_dir = find_plugin_dir(args.plugin, [args.plugin_dir])
    if not plugin_dir:
        sys.stderr.write(f"Plugin {args.plugin!r} not found in {args.plugin_dir}\n")
        return 1
    plugin_dir = Path(plugin_dir)

    config = build_full_config(plugin_dir, cli_config=json.loads(args.config))
    display_manager = VisualTestDisplayManager(width=args.width, height=args.height)
    cache_manager = MockCacheManager()
    if args.mock_data:
        with open(args.mock_data, "r", encoding="utf-8") as handle:
            for key, value in json.load(handle).items():
                cache_manager.set(key, value)

    instance, _module = PluginLoader().load_plugin(
        plugin_id=args.plugin,
        manifest=load_manifest(plugin_dir),
        plugin_dir=plugin_dir,
        config=config,
        display_manager=display_manager,
        cache_manager=cache_manager,
        plugin_manager=MockPluginManager(),
        install_deps=False,
    )

    try:
        instance.update()
    except Exception as exc:  # matches render_plugin.py: update failures are not fatal
        sys.stderr.write(f"update() raised: {exc} -- continuing to display()\n")

    # Animation is driven by elapsed wall-clock time, not by how many times
    # display() was called, so the frozen clock has to move between frames or
    # every step renders the same first frame.
    advance = getattr(__builtins__, "__ledmatrix_docs_advance_clock__", None)
    if advance is None and isinstance(__builtins__, dict):
        advance = __builtins__.get("__ledmatrix_docs_advance_clock__")

    # force_clear only on the first frame, so a plugin that treats it as "start
    # over" does not restart its scroll on every step.
    for frame in range(max(1, args.frames)):
        instance.display(force_clear=(frame == 0))
        if advance is not None:
            advance(args.frame_seconds)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    display_manager.save_snapshot(str(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
