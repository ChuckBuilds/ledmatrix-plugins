# 7. Testing, CI & the Registry

[← Guide index](./README.md) · [← Manifest & schema](./06-manifest-and-config-schema.md)

How your plugin is validated, how the registry stays in sync, and the rule that
keeps plugins from clobbering each other at load time.

---

## Module collisions

The core loads every plugin's top-level `*.py` files as **bare-name** modules on
`sys.path` (e.g. `import data_model`), then namespace-isolates them *after* the
entry point finishes loading. Two plugins **may** ship identically-named
top-level modules (the sports plugins all share `sports.py`, `scroll_display.py`,
…) — but only if every intra-plugin import runs **while the entry point is
loading**.

It breaks for **deferred imports** — a `from data_model import X` that runs
*after* isolation:

- inside a **subpackage** `__init__`/module imported lazily during instantiation
  (e.g. `providers/__init__.py`), or
- inside a **function/method body** that runs at update/display time.

By then the bare name has been popped from `sys.modules`, so the import
re-resolves via `sys.path` and can bind a **different plugin's** identically-named
module — and the plugin fails to load. (Real case: `ledmatrix-elections` and
`ledmatrix-flights` both shipped `data_model.py`; elections' `providers/`
subpackage bound flights' `data_model` and failed.)

**Rule:** if a module is imported from a subpackage or a deferred
(function-scoped) position, give it a **plugin-unique name** — prefix it with the
plugin domain, e.g. `election_data_model.py`, not `data_model.py`.

Relative imports are **not** an option: the loader loads the entry point via
`spec_from_file_location` with no package context, so `from .data_model import X`
raises "no known parent package."

### The checker

`scripts/check_module_collisions.py` enforces this across **all** plugins on every
PR. It builds a map of which plugins ship each top-level module name, scans each
plugin's subpackage files (treated as entirely deferred) and function-scoped
imports in top-level files, and flags any deferred import of a bare name that
(a) the plugin actually ships as a top-level module and (b) another plugin also
ships. Run it locally:

```bash
python scripts/check_module_collisions.py
```

A top-level subdirectory holding `.py` files (other than `test/`, `tests/` and
`scripts/`) counts as a module name too: a deferred `import data.teams` binds
whichever plugin's `data` package comes first. A plugin file that cannot be
parsed fails the check rather than being treated as import-free.

It exits non-zero with a `plugin: 'src' deferred-imports 'name', also shipped
by: ...` line per violation (or a `FAIL` line per unparseable file), or prints
`OK: no cross-plugin deferred-import collisions across N plugins (M files
parsed).`

---

## The safety harness

Each plugin can expose multiple screens and must render on every supported matrix
size. The harness's default test matrix covers eight sizes — 64×32, 128×32,
64×64, 96×48, 128×64, 256×32, 128×96, and 256×128 (see `DEFAULT_TEST_SIZES` in
the core's `src/plugin_system/testing/sizes.py`; a plugin's
`test/harness.json` can override the list). The harness lives in the **core** repo
(`LEDMatrix/scripts/check_plugin.py`) and renders every screen at every size,
failing on crashes, content drawn past the panel edge, or visual drift vs.
committed golden images.

**Before opening a PR that changes a plugin**, run it from a core checkout with
this repo's plugins on the path:

```bash
python scripts/check_plugin.py --plugin <id> \
  --plugin-dir /path/to/ledmatrix-plugins/plugins --out-dir /tmp/preview
```

Eyeball the PNGs in `/tmp/preview`, then fix any FAIL (overflow/crash) before
pushing.

### Golden images (optional, per plugin)

Commit reference PNGs so visual drift is caught automatically:

```text
plugins/<id>/test/harness.json           # deterministic config / mock data / frozen time
plugins/<id>/test/golden/<WxH>/<mode>.png
```

Regenerate with `check_plugin.py --update-golden` and review the diff. See
[`plugins/clock-simple/test/`](../../plugins/clock-simple/test/) for a worked
example and the core's `docs/plugin-safety-harness.md` for the full reference.

---

## CI workflows

Four workflows run from `.github/workflows/`:

### `test-plugins.yml` — "Plugin Safety"

Triggers on PRs touching `plugins/**`, `scripts/**`, `update_registry.py`,
`plugins.json` or the workflow itself. It checks out the core repo
(`ChuckBuilds/LEDMatrix@main`, full history with tags) for the harness, the
manifest schema and the imports several guards need.

"Changed plugins" means plugins with a changed file **outside** `test/` and
outside root-level `test_*.py` (most plugins keep their tests at the root, so
both are excluded). Any change at all, tests included, still counts for the
plugin unit-test step. A `workflow_dispatch` with `all=true` checks every plugin.

Steps, in order:

1. **Version-bump enforcement** (changed plugins) —
   `scripts/check_version_bump.py --base <PR base>`. Fails unless `version` is
   strictly greater than the base (semver, so a downgrade fails), `version ==
   versions[0].version`, and `versions[0]` is a new entry rather than the old
   top entry edited in place. New plugins only need `version` and
   `versions[0]` to agree. `python scripts/check_version_bump.py --all` audits
   the sync rule across the whole repo.
2. **Manifest version fields** (changed plugins) —
   `scripts/check_manifest_version_fields.py`: `versions[0]` uses
   `ledmatrix_min_version` (not the deprecated `ledmatrix_min`) and a floor is
   declared somewhere; `compatible_versions` is present. Runs its regression
   suite too.
3. **Registry sync** (always) — `python update_registry.py --check`; see
   [the registry](#the-registry-pluginsjson) below.
4. **Manifest schema validation** (changed plugins) — against the core's
   `schema/manifest_schema.json`.
5. **Safety harness** (changed plugins) — installs the plugin's
   `requirements.txt`, then runs `check_plugin.py` across all matrix
   sizes/screens.
6. **Repo-level guard tests** (always) — every `scripts/test_*.py`, discovered
   by glob, with `LEDMATRIX_CORE` and `PYTHONPATH` pointing at the core
   checkout. A new guard runs the day it lands; there is no list to update.
7. **Plugin unit tests** (always, for plugins with any change) —
   `scripts/run_plugin_tests.py <ids> --core <core>` runs the plugins' own
   `test_*.py`.

> **Note:** the version-bump gate treats *any* non-test file in a plugin folder —
> including its `README.md` — as a plugin change requiring a version bump. Keep
> that in mind when editing a single plugin's docs.

### `module-collisions.yml` — "Plugin Structure"

Triggers on PRs touching `plugins/**`, the scripts it runs, `README.md`,
`docs/assets/**` or `config_secrets.template.json`. Every check scans **all**
plugins, because each problem can arrive with a newly added plugin. None needs
the core.

- `check_module_collisions.py` and its regression suite
- `check_scroll_adoption.py` and its suite: `scroll_display.py` must import the
  legacy fallback, not inline it
- `check_sports_display_contract.py` and its suite: sports `display()` returns a
  bool on every path
- `test_scroll_mode_is_reachable.py`: a scroll display mode reaches its renderer
- `test_pixel_perfect_text.py`: text draws are 1-bit (no anti-aliasing)
- `update_readme_previews.py --check`: the root README's Preview column matches
  the `hero.png` files on disk
- `check_secrets_template.py`: every `x-secret` schema field has a placeholder
  in the root `config_secrets.template.json`, under the plugin id

### `sports-drift.yml` — "Sports Lineage Drift"

Triggers on PRs touching `plugins/*-scoreboard/**` or the drift scripts.
`check_sports_drift.py` fails when a function whose copies agree across a
sports lineage starts to disagree, or when display-path logging loses its
throttle. It is baselined (`scripts/sports_drift_baseline.json`), so only new
drift fails. See [shared sports code](./08-shared-sports-code.md).

### `update-registry.yml` — "Update Plugin Registry"

Triggers on push to `main` touching a `plugins/*/manifest.json` or
`update_registry.py`. Regenerates `plugins.json` and auto-commits it as
`github-actions[bot]`. This runs **post-merge**, not as a PR gate — the
pre-commit hook keeps the registry in sync within PRs.

### Writing a repo-level guard

Put it in `scripts/`, standalone, and follow the existing ones:

- Exit **0** pass, **1** fail, **2** skipped with a printed reason (for
  example, no core checkout). The guard-test step reports 2 as a skip; any other
  nonzero status fails the PR.
- Print clear `PASS`/`FAIL` lines.
- Include a plausibility self-check proving the gate is really looking (it
  found N plugins or files, or it still detects a known-bad sample). A gate
  that reports by absence otherwise can't tell "clean" from "looked at nothing".
- Add a `scripts/test_*.py` regression suite. It is picked up automatically.
- Read the core location from `LEDMATRIX_CORE` first.

---

## The registry: `plugins.json`

**Generated — do not hand-edit versions or metadata.** The one exception is
adding an entry: `update_registry.py` only updates entries that already exist,
so a **new monorepo plugin needs its entry added by hand** (copy a neighbour's
shape, with `plugin_path: "plugins/<dir>"`). CI's `update_registry.py --check`
fails a PR that adds a plugin directory without one.

Top-level keys: `version` (the registry schema
version), `last_updated`, and a `plugins` array. Each entry carries a fixed set of
fields (`id`, `name`, `description`, `author`, `category`, `tags`, `repo`,
`branch`, `plugin_path`, `stars`, `downloads`, `last_updated`, `verified`,
`screenshot`, `latest_version`).

- **Monorepo plugins** use `repo` = this repo's URL, `branch` = `main`,
  `plugin_path` = `plugins/<id>`.
- **Third-party plugins** keep their own external `repo`, an empty `plugin_path`,
  and are typically `verified: false`.

### `update_registry.py`

Treats each plugin's `manifest.json` as the source of truth and syncs the
registry:

- For monorepo entries (non-empty `plugin_path`), if the manifest `version` is
  **greater** than the registry `latest_version`, it updates `latest_version` and
  the entry's `last_updated`. It never downgrades: a registry version *ahead* of
  its manifest is warned about and left alone.
- It also force-syncs `name`, `description`, `author`, `category`, `tags`,
  `icon` and `last_updated` from manifest to registry when they differ.
- Third-party entries (empty `plugin_path`) are left completely untouched.
- On any change it bumps the top-level `last_updated` and rewrites the file.
- It checks coverage, matching by `plugin_path` (registry ids and manifest ids
  differ for weather, stocks, music and leaderboard): a `plugins/<dir>` with a
  manifest but no entry, a `plugin_path` with no manifest, or two entries
  claiming one path. A normal run warns; `--check` fails.
- `--check` also fails when anything a normal run would write is missing from
  the committed `plugins.json`: a `latest_version` behind its manifest, one
  ahead of it, or a synced metadata field that differs. The pre-commit hook
  keeps this green; without it, run `python update_registry.py` and commit
  the result.

```bash
python update_registry.py            # sync plugins.json from manifests
python update_registry.py --dry-run  # preview without writing
python update_registry.py --check    # dry run; exit 1 on drift or a coverage problem (CI)
```

---

## Manual tools

Not run by CI; use them by hand.

- `scripts/check_espn_api.py` — probes every ESPN endpoint shape the
  scoreboards use under several User-Agents, and says whether ESPN moved an
  endpoint or is filtering on the header. Run it from a host that can reach
  ESPN when "the scoreboards went blank".
- `scripts/check_team_pickers.py` — compares the team-picker enums with ESPN;
  `--apply` regenerates them.
- `scripts/render_docs_assets.py` — renders a plugin README's screenshots from
  `docs/assets/<id>/shots.json` through the core renderer; `--check` diffs
  against what is committed. `--all --check` is not in CI: it re-renders all
  42 shot lists through the core renderer (each plugin's dependencies needed),
  and a local run was still rendering, with no output yet, after more than
  five minutes. Run it for the plugins you
  touched, e.g. `--plugin <id> --check`.
- `scripts/update_readme_previews.py` — rewrites the root README's Preview
  column (CI runs its `--check`).
- `scripts/archive_old_repos.sh` — the monorepo migration's archiver for the
  old per-plugin repos: adds a redirect notice, then archives. Dry run by
  default, `--apply` to act. Not every listed repo was archived (for example,
  `ledmatrix-hello-world` was still live on 2026-09-15), so it is kept.

---

## Quick pre-PR checklist

1. Edit code in `plugins/<plugin-id>/` (keep deferred/subpackage module names
   plugin-unique).
2. Update `config_schema.json` if config changed (mark fine-tuning keys
   `x-advanced`).
3. **Bump `version`** in `manifest.json` and add a matching entry at the top of
   `versions[]`. New plugin? Add its `plugins.json` entry too.
4. Run `python scripts/check_module_collisions.py`, and the safety harness from a
   core checkout.
5. Commit (the pre-commit hook syncs `plugins.json`) and open a PR — CI enforces
   the version bump, registry coverage, manifest schema, harness, collisions and
   every repo-level guard.

[← Back to the guide index](./README.md)
