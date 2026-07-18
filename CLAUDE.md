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

**Deep-dive human guide:** `docs/plugin-development/` holds the full developer
guide (anatomy, core API, advanced features, styling/skins, adaptive layout,
manifest/schema, testing/CI). This file is the dense LLM-facing summary of it.

## Anatomy of a Plugin

A plugin directory contains at minimum a `manifest.json` and an entry-point
Python file (default `manager.py`) with the plugin class. Typical layout:

```text
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
- `self.logger`, `self.config`, `self.display_manager`, `self.cache_manager`,
  `self.plugin_manager` (+ `.font_manager`), `self.plugin_id`, `self.enabled`,
  `self.global_config` are provided by the base class

Multi-mode plugins (the scoreboards) use a wider `display(self, display_mode=None,
force_clear=False) -> bool` signature. The core also calls a family of **optional
hooks** if implemented — dynamic duration (`supports_dynamic_duration`,
`get_cycle_duration`, `get_dynamic_duration_cap`/`_floor`, `is_cycle_complete`,
`reset_cycle_state`), live rotation (`get_live_modes`, `has_live_priority`,
`has_live_content`), Vegas (`get_vegas_content`/`_type`/`_display_mode`,
`get_supported_vegas_modes`), and lifecycle (`on_config_change`, `on_enable`,
`on_disable`). See `docs/plugin-development/`.

`hello-world` is the starter template; new plugins should begin there.

## Advanced Plugin Features

These are the optional capabilities that make plugins feature-rich. They're
opt-in: a plugin only participates by reading the relevant config key or
implementing the relevant method. The sports scoreboards (`hockey-scoreboard`,
`football-scoreboard`, `baseball-scoreboard`, …) exercise most of them and are
the best reference implementations.

### Cache management (`self.cache_manager`)
Every plugin is handed a shared `cache_manager` in its constructor. Use it for
**anything fetched over the network** so restarts and multiple plugins don't
re-hit APIs. Core API surface (seen across plugins):
- `cache_manager.get(key, max_age=<seconds>)` — return cached value or `None` if missing/stale
- `cache_manager.set(key, value, ttl=<seconds>)` — store with an optional time-to-live
- `cache_manager.get_cached_data_with_strategy(key, strategy)` / `save_cache(key, data)` —
  strategy-driven caching (e.g. `'leaderboard'`) that layers TTL/refresh policy on top of raw get/set;
  see `plugins/ledmatrix-leaderboard/data_fetcher.py`
- `cache_manager.delete(key)` / `clear_cache()` — invalidation

Namespace your keys with the plugin id (e.g. `f"{self.plugin_id}:standings:{league}"`)
so they never collide with another plugin's entries. Fetch in `update()`, never in `display()`.

### Live priority (`live_priority`)
A per-source boolean (`config[<league>]["live_priority"]`) that tells the
rotation to **prefer live games over scheduled/recent ones**. When enabled and
real live games exist, the manager surfaces only the live content; when no games
are live it falls back to the normal schedule. Wire it up by reading the flag in
`__init__` and filtering the display list in your update/selection logic (see
`plugins/hockey-scoreboard/manager.py`, `nhl_live_priority` and the live-mode
filter around the `_should_show` logic).

Related live-rotation knobs the sports plugins expose:
- **`favorite_live_boost`** — how many rotation turns a favorite team's live game
  gets per turn for other live games (and it's queued first on each refresh).
- **`non_favorite_live` / live-duration overrides** — different display durations
  for favorite vs. non-favorite live games.

### Dynamic duration (`supports_dynamic_duration()` + `dynamic_duration` config)
Lets a plugin tell the core "hold my screen for a computed time" instead of a
fixed `display_duration`. The plugin implements
`supports_dynamic_duration(self, mode_type=None) -> bool` and reads a
`dynamic_duration` config object (`enabled`, `max_duration_seconds`, per-mode
settings). Typical use: size the on-screen time to the width of scrolling content,
or extend live games. See `plugins/football-scoreboard/DYNAMIC_DURATION.md` and
the `supports_dynamic_duration` implementations in the sports managers.

### High-FPS / smooth scrolling
Scrolling plugins render far faster than the default loop for smooth motion.
Two mechanisms:
- **Global target FPS** — read `global_config['target_fps']` (fallback
  `scroll_target_fps`, default ~100) and push it into the scroll helper:
  `self.scroll_helper.set_target_fps(target_fps)`, with a clamp fallback
  (`max(30.0, min(200.0, target_fps))`) for older cores. See
  `plugins/odds-ticker/manager.py`, `plugins/news/manager.py`,
  `plugins/ledmatrix-leaderboard/manager.py`.
- **Per-frame delay** — the `scroll_delay` config key (seconds/frame; `0.01` ≈ 100 FPS)
  controls smoothness on the scoreboards.
- **Per-plugin high-performance flag** — e.g. `high_performance_transitions` in
  `plugins/christmas-countdown/config_schema.json` toggles 120 FPS transitions vs. 30 FPS.

### Vegas mode (continuous scroll integration)
"Vegas" is the core's continuous marquee that stitches multiple plugins into one
endlessly-scrolling strip. A plugin opts in by implementing:
- `get_vegas_content(self)` — return the PIL image(s) to splice into the strip (or `None`)
- `get_vegas_content_type(self)` — `'single'` or `'multi'` (multiple scrollable items, e.g. games)
- `get_vegas_display_mode(self)` — return a `VegasDisplayMode`, honoring the
  `vegas_mode` config override

Import the enum defensively, since older cores don't ship it:
```python
try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
except ImportError:
    VegasDisplayMode = None
```
The `vegas_mode` config key (mark it `x-advanced`) is an enum:
- `scroll` — items scroll individually through the stream (default)
- `fixed` — the whole display scrolls by as one block
- `static` — the marquee pauses while the plugin shows for its duration

See `plugins/hockey-scoreboard/manager.py` (Vegas section) and
`plugins/nfl-draft/config_schema.json` / `plugins/olympics/config_schema.json`
for the config declaration.

### Adaptive layout (`layout_mode`)
Every plugin must render on all four sizes (64×32, 128×32, 128×64, 256×32). Most
adapt with plain width/height-tier branching off `self.display_manager.width/height`
(e.g. `ledmatrix-flights/renderer.py`, `masters-tournament`). Two plugins
(`football-scoreboard`, `ledmatrix-music`) additionally opt into the core's
**adaptive engine** via a `layout_mode` config enum (`["classic","adaptive"]`,
default `classic`, `x-advanced`) — note the key is `layout_mode`, not
`layout_engine`. `adaptive` (beta) scales fonts/logos/regions to the panel using
`src.adaptive_layout` (guarded import; falls back to classic on older cores) while
still honoring user font overrides and `customization.layout` x/y offsets. See
`plugins/football-scoreboard/game_renderer.py` and
`docs/plugin-development/05-adaptive-layout.md`.

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
Config schemas are **JSON Schema Draft-07** (all 39 plugins) and drive the
auto-generated web-UI config form. Beyond standard JSON Schema, the UI honors
custom `x-` extensions (validators ignore unknown `x-` keys):
- **`x-advanced: true`** — hide a property behind the **Advanced Settings**
  disclosure; use for fine-tuning knobs. By far the most used.
- **`x-propertyOrder`** (array) — explicit property render order.
- **`x-widget`** (string) — custom editor: `color-picker`, `checkbox-group`,
  `file-upload`, `array-table`, `radio`, `time-picker`, `plugin-file-manager`, …
  (companions: `x-widget-config`, `x-upload-config`, `x-columns`, `x-options`).
- **`x-collapsed`** — section collapsed by default. **`x-secret`/`x-sensitive`** —
  mask value. **`x-placeholder`**, **`x-display`** (`"hidden"`).

**Styling / "skins" — two mechanisms.** (1) The manual `customization` block:
per-element objects with `font`/`font_size`/`text_color` (~17 plugins; e.g.
`plugins/clock-simple/config_schema.json`), self-contained and core-agnostic.
(2) `x-style-elements`: a compact shorthand on `customization` that a newer core
expands into a full font/size/color/offset UI via `src.element_style`
(guarded import + classic fallback). Only `plugins/of-the-day` uses it — the
reference. See `docs/plugin-development/04-styling-and-skins.md`.

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
