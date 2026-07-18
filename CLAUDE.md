# LEDMatrix Plugins Monorepo

This repo is the **official plugin registry** for [LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix).
Each plugin is a self-contained Python package that the LEDMatrix core loads at
runtime and renders on an RGB LED matrix. The core lives in a separate repo
(`ChuckBuilds/LEDMatrix`); this repo only ships plugin source + the registry the
plugin store reads.

## Structure
- `plugins/<plugin-id>/` — Each plugin's source code, manifest, config schema, README, tests
- `plugins.json` — Central registry consumed by the LEDMatrix plugin store (auto-generated; do not hand-edit)
- `update_registry.py` — Syncs `plugins.json` `latest_version` from local plugin manifests
- `scripts/` — `check_module_collisions.py`, `pre-commit` hook, `archive_old_repos.sh`
- `.github/workflows/` — CI: module-collisions, plugin safety harness, registry auto-update
- `schema/` reference and `docs/` — supporting material; canonical `manifest_schema.json` lives in the **core** repo

There are ~39 plugins in `plugins/`; `plugins.json` also lists third-party plugins hosted in their own repos.

## Anatomy of a Plugin

A plugin directory contains at minimum a `manifest.json` and an entry-point
Python file (default `manager.py`) with the plugin class. Typical layout:

```
plugins/<plugin-id>/
  manifest.json         # metadata (required) — see fields below
  manager.py            # entry point; default class location
  config_schema.json    # JSON Schema Draft-07 for the web-UI config form
  requirements.txt      # plugin runtime deps (installed by CI before the harness)
  README.md             # user docs
  assets/               # fonts, logos, images
  test/                 # optional safety-harness fixtures (harness.json, golden/)
  test_*.py             # optional unit tests
```

The plugin class **inherits from `BasePlugin`** (`src.plugin_system.base_plugin.BasePlugin`
in the core repo) and is constructed as
`__init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager)`.
Key methods (see `plugins/hello-world/manager.py` for a minimal reference):
- `update(self)` — fetch/refresh data (called on `update_interval`); never draw here
- `display(self, force_clear=False)` — render via `self.display_manager` then call `update_display()`
- `validate_config(self)` — call `super().validate_config()` then check plugin-specific keys
- `get_info(self)` / `cleanup(self)` — web-UI info and unload teardown
- `self.logger`, `self.config`, `self.plugin_manager.font_manager` are provided by the base class

`hello-world` is the starter template; new plugins should begin there.

## Module Naming — Avoid Cross-Plugin Collisions

The core loads every plugin's top-level `*.py` files as **bare-name** modules on
`sys.path` (e.g. `import data_model`), then namespace-isolates them *after* the
entry point finishes loading. Two plugins **may** ship identically-named
top-level modules (the sports plugins all share `sports.py`, `scroll_display.py`,
…) — but only if every intra-plugin import runs **while the entry point is
loading**.

It breaks for **deferred imports** — a `from data_model import X` that runs
*after* isolation:
- inside a **subpackage** `__init__`/module that's imported lazily during
  instantiation (e.g. `providers/__init__.py`), or
- inside a **function/method body** that runs at update/display time.

By then the bare name has been popped from `sys.modules`, so the import
re-resolves via `sys.path` and can bind a **different plugin's** identically-named
module — the plugin fails to load. (Real case: `ledmatrix-elections` and
`ledmatrix-flights` both shipped `data_model.py`; elections' `providers/`
subpackage bound flights' `data_model` and failed.)

**Rule:** if a module is imported from a subpackage or a deferred (function-scoped)
position, give it a **plugin-unique name** — prefix with the plugin domain, e.g.
`election_data_model.py`, not `data_model.py`. Relative imports are **not** an
option: the loader loads the entry point via `spec_from_file_location` with no
package context, so `from .data_model import X` raises "no known parent package."

**Enforcement:** `scripts/check_module_collisions.py` fails CI when a plugin's
deferred import targets a sibling top-level module whose name is also shipped by
another plugin. It runs on every PR via `.github/workflows/module-collisions.yml`.
Run it locally with `python scripts/check_module_collisions.py`.

## Plugin Version Workflow

**IMPORTANT:** When modifying any plugin, you MUST bump its version. This is how users receive updates — the LEDMatrix plugin store compares `manifest.json` version against `plugins.json` latest_version.

### Steps for every plugin change:
1. Make your code changes in `plugins/<plugin-id>/`
2. Bump `version` in `plugins/<plugin-id>/manifest.json` (semver: major.minor.patch)
3. Commit — the pre-commit hook automatically runs `update_registry.py` and stages `plugins.json`

> **Note:** The pre-commit hook only triggers when a `plugins/*/manifest.json` is staged. If it's not installed, run `cp scripts/pre-commit .git/hooks/pre-commit` to set it up.

### Version bump guidelines:
- **Patch** (1.0.0 → 1.0.1): Bug fixes, minor text changes
- **Minor** (1.0.0 → 1.1.0): New features, config schema additions
- **Major** (1.0.0 → 2.0.0): Breaking config changes, major rewrites

### If you forget to bump the version:
Users will NOT receive the update. The store uses version comparison, not git commits. CI (`test-plugins.yml`) **fails a PR** whose plugin code changed without a version bump.

## Plugin Manifest Fields
Every `plugins/<id>/manifest.json` is validated against the core repo's
`schema/manifest_schema.json`. Core required fields:
- `id` — Plugin identifier (must match directory name)
- `name` — Human-readable display name
- `version` — Semver string (e.g., "1.2.3")
- `class_name` — Python class name in the entry point
- `display_modes` — Array of supported display mode names

Commonly present optional fields:
- `entry_point` — Python file with the plugin class (default `manager.py`)
- `author`, `description`, `category`, `tags` — store metadata
- `config_schema` — path to the config schema file (usually `config_schema.json`)
- `versions` — changelog array of `{version, released, ledmatrix_min}` entries
- `compatible_versions` / `ledmatrix_min` — core-version compatibility constraints
- `verified`, `stars`, `downloads`, `screenshot`, `last_updated` — store display fields

## Config Schema Conventions (`config_schema.json`)
Config schemas are **JSON Schema Draft-07** and drive the auto-generated web-UI
config form. Beyond standard JSON Schema, the LEDMatrix UI honors custom `x-`
extensions:
- **`x-advanced: true`** on a property hides it behind the form's **Advanced
  Settings** disclosure — use it for fine-tuning knobs (intervals, pixel offsets,
  layout tweaks) that most users shouldn't need. Widely used (~60 files).
- **`x-style-elements`** declares per-text-element user-customizable font / size /
  color / offset controls (see `plugins/of-the-day/config_schema.json`). Each
  element defines `font`, `size` (with `min`/`max`), `color` (RGB), and offsets
  with `default`s; the plugin reads the resolved values at render time.

Mirror the property `default`s in the plugin code's `config.get(key, default)`
calls so behavior matches the schema even when a key is absent.

## Registry Format
`plugins.json` is generated by `update_registry.py` — **do not hand-edit it**; it
has top-level `version`, `last_updated`, and a `plugins` array. Entries for
monorepo plugins use:
- `repo`: `https://github.com/ChuckBuilds/ledmatrix-plugins`
- `plugin_path`: `plugins/<plugin-id>`
- `branch`: `main`
- `latest_version`: Synced from manifest by `update_registry.py`

Third-party plugins keep their own `repo` URL and empty `plugin_path`.

## Scripts
- `python update_registry.py` — Update plugins.json from manifests
- `python update_registry.py --dry-run` — Preview without writing
- `python scripts/check_module_collisions.py` — Cross-plugin module-collision check
- `scripts/archive_old_repos.sh` — Archive old individual repos (one-time, use `--apply`)

## Git Hooks
- `scripts/pre-commit` — Auto-syncs `plugins.json` when manifest versions change
- Install: `cp scripts/pre-commit .git/hooks/pre-commit`

## CI Workflows (`.github/workflows/`)
- **`test-plugins.yml`** (Plugin Safety) — on PRs touching `plugins/**`: for each
  *changed* plugin (non-test code only) it enforces the version bump, validates the
  manifest against the schema, installs the plugin's `requirements.txt`, and runs
  the core safety harness. Test-only changes (`plugins/<id>/test/**`) don't trigger the gate.
- **`module-collisions.yml`** (Module Collisions) — on PRs touching `plugins/**`:
  runs `check_module_collisions.py` across **all** plugins.
- **`update-registry.yml`** (Update Plugin Registry) — on push to `main` touching a
  manifest or `update_registry.py`: regenerates `plugins.json` and auto-commits it.

## Plugin Safety Harness (cross-size / cross-screen)

Each plugin can expose multiple screens and must render on every supported matrix
size (64×32, 128×32, 128×64, 256×32). The harness lives in the **core** repo
(`LEDMatrix/scripts/check_plugin.py`) and renders every screen at every size,
failing on crashes, content drawn past the panel edge, or visual drift vs
committed golden images.

**Before opening a PR that changes a plugin:**
```bash
# from a LEDMatrix (core) checkout, with the monorepo plugins on the path:
python scripts/check_plugin.py --plugin <id> \
  --plugin-dir /path/to/ledmatrix-plugins/plugins --out-dir /tmp/preview
```
Eyeball the PNGs in `/tmp/preview`, then fix any FAIL (overflow/crash) before pushing.

**Golden images (optional, per plugin):** commit reference PNGs so visual drift is
caught automatically:
```text
plugins/<id>/test/harness.json           # deterministic config / mock data / frozen time
plugins/<id>/test/golden/<WxH>/<mode>.png
```
Regenerate with `check_plugin.py --update-golden` and review the diff. See
`clock-simple/test/` for a worked example and `LEDMatrix/docs/plugin-safety-harness.md`
for the full reference.

**CI:** `.github/workflows/test-plugins.yml` runs the harness against every
*changed* plugin on each PR (installs that plugin's `requirements.txt` first),
validates its manifest against `schema/manifest_schema.json`, and enforces the
version bump.

## Quick Reference — Making a Plugin Change
1. Edit code in `plugins/<plugin-id>/` (keep deferred/subpackage module names plugin-unique).
2. Update `config_schema.json` if config changed (mark fine-tuning keys `x-advanced`).
3. **Bump `version`** in `manifest.json`.
4. Run `python scripts/check_module_collisions.py` and, from a core checkout, the safety harness.
5. Commit (pre-commit hook syncs `plugins.json`) and open a PR — CI enforces the version bump, manifest schema, harness, and collisions.
