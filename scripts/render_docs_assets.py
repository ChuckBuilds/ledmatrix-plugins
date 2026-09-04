#!/usr/bin/env python3
"""Render the README screenshots for a plugin from a declarative shot list.

Every image in a plugin README should be real plugin output rendered at the
true panel size, not a mockup. This script drives the LEDMatrix core renderer
(``scripts/render_plugin.py`` in the core checkout) once per shot, upscales the
result with nearest-neighbour so the pixels stay pixels, and optionally glues
shots together into labelled comparison grids.

Shot lists live beside the images they produce::

    docs/assets/<plugin-id>/shots.json   # the declaration
    docs/assets/<plugin-id>/*.png        # the output, committed to the repo

Usage::

    python scripts/render_docs_assets.py --plugin clock-simple
    python scripts/render_docs_assets.py --plugin clock-simple --only hero
    python scripts/render_docs_assets.py --all --check

``--check`` re-renders into a temp directory and diffs against what is
committed, so CI (or you, before a PR) can tell whether the images still match
the plugin.

Shot list format
----------------

.. code-block:: json

    {
      "plugin": "clock-simple",
      "defaults": {"width": 128, "height": 32, "scale": 6},
      "shots": [
        {
          "name": "hero",
          "height": 64,
          "config": {"show_seconds": true},
          "mock_data": {"clock_simple:tz": "..."},
          "skip_update": false
        }
      ],
      "composites": [
        {
          "name": "sizes",
          "columns": 1,
          "cells": [
            {"shot": "hero", "label": "128x64", "sublabel": "the default panel"}
          ]
        }
      ]
    }

Keys on a shot: ``name`` (required, becomes ``<name>.png``), ``width``,
``height``, ``scale``, ``config`` (merged over schema defaults), ``mock_data``
(inline object, or a path relative to the shot list), ``skip_update``,
``freeze_time`` (ISO-8601 instant; pins "now" so the image is reproducible),
``http_replay`` (a recorded-responses file, for managers that fetch without
reading the cache), ``frames`` (advance a scrolling plugin this many display
steps before snapshotting), ``attrs`` (runtime state to set on the plugin
instance, for plugins whose interesting state arrives by event rather than by
configuration), ``hostname`` (pins ``socket.gethostname``, for plugins that
print the device name) and
``env`` (extra environment variables for the render subprocess). Anything
omitted falls back to ``defaults``. Set ``"standalone": false`` on a shot that
only exists to be pasted into a composite.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
# Runs the core renderer; argv is a list built from validated local inputs.
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # Pillow is imported lazily so --help works without it
    from PIL.Image import Image as PILImage

PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
ASSETS_ROOT = REPO_ROOT / "docs" / "assets"

# Composite chrome. Tuned to read well on both GitHub themes: the dark card
# background keeps an unlit LED panel from looking like a hole in the page.
CARD_BG = (26, 26, 30)
LABEL_FG = (238, 238, 242)
SUBLABEL_FG = (150, 152, 160)
PANEL_BORDER = (64, 66, 74)
MARGIN = 20
GUTTER = 24
LABEL_SIZE = 17
SUBLABEL_SIZE = 13
LABEL_GAP = 6
CELL_GAP = 10

DEFAULT_SCALE = 6
DEFAULT_WIDTH = 128
DEFAULT_HEIGHT = 32

FONT_CANDIDATES = {
    "bold": [
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    "regular": [
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
}


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``overlay`` into ``base``, recursing into nested dicts.

    A shot that overrides one key of a per-league block must not wipe the rest
    of it. With a shallow update, a shot setting only ``mlb.display_modes``
    replaces the whole ``mlb`` block from ``defaults`` -- including
    ``mlb.enabled`` -- and the plugin renders nothing for reasons that look
    nothing like the cause.
    """
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_font(weight: str, size: int):
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES[weight]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def find_core_repo(explicit: Optional[str]) -> Path:
    """Locate the LEDMatrix core checkout that owns the renderer."""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("LEDMATRIX_CORE")
    if env:
        candidates.append(Path(env))
    candidates += [
        REPO_ROOT.parent / "LEDMatrix",
        REPO_ROOT.parent / "ledmatrix",
        Path.home() / "LEDMatrix",
    ]
    for candidate in candidates:
        if (candidate / "scripts" / "render_plugin.py").is_file():
            return candidate.resolve()
    raise SystemExit(
        "Could not find the LEDMatrix core checkout (needs scripts/render_plugin.py).\n"
        "Pass --core-repo /path/to/LEDMatrix or set LEDMATRIX_CORE.\n"
        "  git clone https://github.com/ChuckBuilds/LEDMatrix.git"
    )


def validate_plugin_id(plugin_id: str) -> str:
    """Reject anything that is not a plain plugin id.

    The id is interpolated into the renderer's argv and into the
    ``docs/assets/<id>`` path, so a value containing a path separator or a
    leading dash would either escape the assets tree or be read as a flag.
    """
    if not PLUGIN_ID_RE.match(plugin_id or ""):
        raise SystemExit(
            f"Invalid plugin id {plugin_id!r}: expected lowercase letters, "
            "digits, dot, dash or underscore."
        )
    return plugin_id


def shot_list_path(plugin_id: str) -> Path:
    return ASSETS_ROOT / validate_plugin_id(plugin_id) / "shots.json"


def load_shot_list(plugin_id: str) -> Dict[str, Any]:
    path = shot_list_path(plugin_id)
    if not path.is_file():
        raise SystemExit(f"No shot list at {path.relative_to(REPO_ROOT)}")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_mock_data(spec: Any, shot_list_dir: Path, tmpdir: Path, name: str) -> Optional[Path]:
    """Return a path to a mock-data JSON file, materialising inline data."""
    if spec is None:
        return None
    if isinstance(spec, str):
        path = (shot_list_dir / spec).resolve()
        if not path.is_file():
            raise SystemExit(f"mock_data file not found for shot '{name}': {path}")
        return path
    path = tmpdir / f"{name}-mock.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle)
    return path


def render_shot(
    core_repo: Path,
    plugin_id: str,
    shot: Dict[str, Any],
    defaults: Dict[str, Any],
    shot_list_dir: Path,
    tmpdir: Path,
) -> Tuple[Path, int]:
    """Render one shot at true panel size. Returns (raw png path, scale)."""
    from PIL import Image

    name = shot["name"]
    width = int(shot.get("width", defaults.get("width", DEFAULT_WIDTH)))
    height = int(shot.get("height", defaults.get("height", DEFAULT_HEIGHT)))
    scale = int(shot.get("scale", defaults.get("scale", DEFAULT_SCALE)))

    config = deep_merge(defaults.get("config", {}), shot.get("config", {}))

    raw_path = tmpdir / f"{name}-raw.png"
    frames = int(shot.get("frames", defaults.get("frames", 1)))

    # A scrolling plugin starts its strip off the right edge, so one frame is an
    # empty panel. Those shots go through our own runner, which drives the same
    # core testing API and steps display() before snapshotting.
    if frames > 1:
        renderer = Path(__file__).resolve().parent / "docs_render_support" / "_docs_frame_runner.py"
        extra = ["--core-repo", str(core_repo), "--frames", str(frames)]
    else:
        renderer = core_repo / "scripts" / "render_plugin.py"
        extra = []
    if not renderer.is_file():
        raise SystemExit(f"Renderer not found at {renderer}")

    # Every element of argv is either fixed, a path this script resolved, or a
    # validated plugin id -- never a shell string.
    cmd: List[str] = [
        sys.executable,
        str(renderer),
        *extra,
        "--plugin", validate_plugin_id(plugin_id),
        "--plugin-dir", str(PLUGINS_DIR),
        "--config", json.dumps(config),
        "--width", str(width),
        "--height", str(height),
        "--output", str(raw_path),
    ]

    mock_spec = shot.get("mock_data", defaults.get("mock_data"))
    mock_path = resolve_mock_data(mock_spec, shot_list_dir, tmpdir, name)
    if mock_path:
        cmd += ["--mock-data", str(mock_path)]
    display_mode = shot.get("display_mode", defaults.get("display_mode"))
    if display_mode:
        cmd += ["--display-mode", str(display_mode)]
    if shot.get("skip_update", defaults.get("skip_update", False)):
        cmd.append("--skip-update")

    env = os.environ.copy()
    env["EMULATOR"] = "true"

    # A frozen clock is what makes a README image reproducible: without it a
    # clock, a countdown, or a "starts in 2h" line differs on every run.
    freeze_time = shot.get("freeze_time", defaults.get("freeze_time"))
    http_replay = shot.get("http_replay", defaults.get("http_replay"))
    # Runtime state that an event would normally have set; see the shim.
    attrs = shot.get("attrs", defaults.get("attrs"))
    # A plugin that prints the device hostname would otherwise bake whoever ran
    # the renderer into the committed image, and --check would fail for anyone
    # else. Pinning it keeps the screenshot generic and reproducible.
    hostname = shot.get("hostname", defaults.get("hostname"))
    if freeze_time or http_replay or attrs or hostname:
        support_dir = str(Path(__file__).resolve().parent / "docs_render_support")
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{support_dir}{os.pathsep}{existing}" if existing else support_dir
    if freeze_time:
        env["LEDMATRIX_DOCS_FREEZE_TIME"] = str(freeze_time)
    if attrs:
        env["LEDMATRIX_DOCS_ATTRS"] = json.dumps(attrs)
    if hostname:
        env["LEDMATRIX_DOCS_HOSTNAME"] = str(hostname)
    if http_replay:
        replay_path = (shot_list_dir / http_replay).resolve()
        if not replay_path.is_file():
            raise SystemExit(
                f"http_replay file not found for shot '{name}': {replay_path}")
        env["LEDMATRIX_DOCS_HTTP_REPLAY"] = str(replay_path)

    env.update({str(k): str(v) for k, v in defaults.get("env", {}).items()})
    env.update({str(k): str(v) for k, v in shot.get("env", {}).items()})

    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use
    # argv list, shell=False, validated plugin id, no untrusted input.
    result = subprocess.run(  # nosec B603
        cmd,
        cwd=str(core_repo),
        env=env,
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not raw_path.is_file():
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"Render failed for {plugin_id} shot '{name}'")

    # A plugin that draws nothing is almost always a broken fixture rather than
    # an intentional blank screenshot, so say so instead of committing a void.
    with Image.open(raw_path) as image:
        if not image.convert("RGB").getbbox():
            sys.stderr.write(
                f"warning: shot '{name}' rendered a completely blank panel — "
                "check the config and mock data\n"
            )
    return raw_path, scale


def upscale(raw_path: Path, scale: int) -> "PILImage":
    from PIL import Image

    with Image.open(raw_path) as image:
        rgb = image.convert("RGB")
        return rgb.resize((rgb.width * scale, rgb.height * scale), Image.NEAREST)


def build_composite(spec: Dict[str, Any], panels: Dict[str, "PILImage"]) -> "PILImage":
    """Lay labelled panels out in a grid on a dark card."""
    from PIL import Image, ImageDraw

    cells = spec["cells"]
    columns = max(1, int(spec.get("columns", 1)))
    label_font = _load_font("bold", int(spec.get("label_size", LABEL_SIZE)))
    sublabel_font = _load_font("regular", int(spec.get("sublabel_size", SUBLABEL_SIZE)))

    prepared = []
    for cell in cells:
        shot_name = cell["shot"]
        if shot_name not in panels:
            raise SystemExit(f"Composite '{spec['name']}' references unknown shot '{shot_name}'")
        prepared.append((cell, panels[shot_name]))

    label_h = LABEL_SIZE + LABEL_GAP
    sub_h = SUBLABEL_SIZE + LABEL_GAP
    def cell_height(cell, panel):
        height = panel.height + 2  # 1px border each side
        if cell.get("label"):
            height += label_h
        if cell.get("sublabel"):
            height += sub_h
        return height

    rows: List[List[Tuple[Dict[str, Any], "PILImage"]]] = [
        prepared[i:i + columns] for i in range(0, len(prepared), columns)
    ]
    col_widths = [0] * columns
    for row in rows:
        for index, (_cell, panel) in enumerate(row):
            col_widths[index] = max(col_widths[index], panel.width + 2)
    row_heights = [max(cell_height(c, p) for c, p in row) for row in rows]

    total_w = MARGIN * 2 + sum(col_widths) + GUTTER * (columns - 1)
    total_h = MARGIN * 2 + sum(row_heights) + CELL_GAP * (len(rows) - 1)

    canvas = Image.new("RGB", (total_w, total_h), CARD_BG)
    draw = ImageDraw.Draw(canvas)

    y = MARGIN
    for row_index, row in enumerate(rows):
        x = MARGIN
        for col_index, (cell, panel) in enumerate(row):
            cursor = y
            if cell.get("label"):
                draw.text((x, cursor), cell["label"], font=label_font, fill=LABEL_FG)
                cursor += label_h
            if cell.get("sublabel"):
                draw.text((x, cursor), cell["sublabel"], font=sublabel_font, fill=SUBLABEL_FG)
                cursor += sub_h
            draw.rectangle(
                [x, cursor, x + panel.width + 1, cursor + panel.height + 1],
                outline=PANEL_BORDER,
            )
            canvas.paste(panel, (x + 1, cursor + 1))
            x += col_widths[col_index] + GUTTER
        y += row_heights[row_index] + CELL_GAP

    return canvas


def render_plugin_assets(
    plugin_id: str, core_repo: Path, out_dir: Path, only: Optional[Sequence[str]] = None
) -> List[Path]:
    """Render every shot and composite for one plugin into ``out_dir``."""
    shot_list = load_shot_list(plugin_id)
    shot_list_dir = shot_list_path(plugin_id).parent
    defaults = shot_list.get("defaults", {})
    written: List[Path] = []

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        panels: Dict[str, "PILImage"] = {}

        for shot in shot_list.get("shots", []):
            name = shot["name"]
            raw_path, scale = render_shot(
                core_repo, plugin_id, shot, defaults, shot_list_dir, tmpdir
            )
            panel = upscale(raw_path, scale)
            panels[name] = panel
            if shot.get("standalone", True) and (only is None or name in only):
                target = out_dir / f"{name}.png"
                panel.save(target, optimize=True)
                written.append(target)
                print(f"  {target.name}  ({panel.width}x{panel.height})")

        for composite in shot_list.get("composites", []):
            name = composite["name"]
            if only is not None and name not in only:
                continue
            image = build_composite(composite, panels)
            target = out_dir / f"{name}.png"
            image.save(target, optimize=True)
            written.append(target)
            print(f"  {target.name}  ({image.width}x{image.height})")

    return written


def check_plugin_assets(plugin_id: str, core_repo: Path) -> bool:
    """Re-render into a temp dir and compare against the committed images."""
    committed_dir = ASSETS_ROOT / plugin_id
    with tempfile.TemporaryDirectory() as tmp:
        fresh_dir = Path(tmp) / plugin_id
        render_plugin_assets(plugin_id, core_repo, fresh_dir)
        drifted = []
        for fresh in sorted(fresh_dir.glob("*.png")):
            committed = committed_dir / fresh.name
            if not committed.is_file():
                drifted.append(f"{fresh.name}: not committed")
            elif committed.read_bytes() != fresh.read_bytes():
                drifted.append(f"{fresh.name}: differs from committed image")
        for entry in drifted:
            print(f"  DRIFT {entry}")
        return not drifted


def plugins_with_shot_lists() -> List[str]:
    if not ASSETS_ROOT.is_dir():
        return []
    return sorted(p.parent.name for p in ASSETS_ROOT.glob("*/shots.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--plugin", "-p", help="Plugin id to render assets for")
    target.add_argument("--all", action="store_true", help="Every plugin that has a shot list")
    parser.add_argument("--only", nargs="+", help="Render only these shot/composite names")
    parser.add_argument("--core-repo", help="Path to the LEDMatrix core checkout")
    parser.add_argument("--out-dir", help="Write elsewhere instead of docs/assets/<plugin>")
    parser.add_argument("--check", action="store_true", help="Verify committed images still match")
    args = parser.parse_args()

    if importlib.util.find_spec("PIL") is None:
        raise SystemExit("Pillow is required: pip install Pillow")

    core_repo = find_core_repo(args.core_repo)
    plugin_ids = plugins_with_shot_lists() if args.all else [args.plugin]
    if not plugin_ids:
        print("No shot lists found under docs/assets/*/shots.json")
        return 0

    failures = []
    for plugin_id in plugin_ids:
        print(f"{plugin_id}:")
        if args.check:
            if not check_plugin_assets(plugin_id, core_repo):
                failures.append(plugin_id)
            else:
                print("  up to date")
        else:
            out_dir = Path(args.out_dir) if args.out_dir else ASSETS_ROOT / plugin_id
            render_plugin_assets(plugin_id, core_repo, out_dir, args.only)

    if failures:
        print(f"\nStale README images for: {', '.join(failures)}")
        print("Re-run: python scripts/render_docs_assets.py --plugin <id>")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
