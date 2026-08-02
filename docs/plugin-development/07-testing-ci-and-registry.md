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

It exits non-zero with a `plugin: 'src' deferred-imports 'name', also shipped
by: ...` line per violation, or prints `OK: no cross-plugin deferred-import
collisions across N plugins.`

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

Three workflows run from `.github/workflows/`:

### `test-plugins.yml` — "Plugin Safety"

Triggers on PRs touching `plugins/**`. For each **changed** plugin (files outside
`test/`), it runs three gates against the plugin, using the harness + schema from
the core repo (`ChuckBuilds/LEDMatrix@main`):

1. **Version-bump enforcement** — compares the plugin's current `manifest.json`
   `version` to the PR base; fails if code changed but the version didn't. New
   plugins (no prior version) pass.
2. **Manifest schema validation** — validates each changed manifest against the
   core's `schema/manifest_schema.json`.
3. **Safety harness** — installs the plugin's `requirements.txt`, then runs
   `check_plugin.py` across all matrix sizes/screens.

Test-only changes (`plugins/<id>/test/**`) don't trigger the gates. A
`workflow_dispatch` with `all=true` checks every plugin.

> **Note:** the version-bump gate treats *any* non-test file in a plugin folder —
> including its `README.md` — as a plugin change requiring a version bump. Keep
> that in mind when editing a single plugin's docs.

### `module-collisions.yml` — "Module Collisions"

Triggers on PRs touching `plugins/**` or the checker script. Runs
`check_module_collisions.py` across **all** plugins (a new plugin can collide with
an existing one).

### `update-registry.yml` — "Update Plugin Registry"

Triggers on push to `main` touching a `plugins/*/manifest.json` or
`update_registry.py`. Regenerates `plugins.json` and auto-commits it as
`github-actions[bot]`. This runs **post-merge**, not as a PR gate — the
pre-commit hook keeps the registry in sync within PRs.

---

## The registry: `plugins.json`

**Generated — do not hand-edit.** Top-level keys: `version` (the registry schema
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
  the entry's `last_updated`. It never downgrades.
- It also force-syncs `name`, `description`, `author`, `category`, `tags`, and
  `icon` from manifest to registry when they differ.
- Third-party entries (empty `plugin_path`) are left completely untouched.
- On any change it bumps the top-level `last_updated` and rewrites the file.

```bash
python update_registry.py            # sync plugins.json from manifests
python update_registry.py --dry-run  # preview without writing
```

---

## Quick pre-PR checklist

1. Edit code in `plugins/<plugin-id>/` (keep deferred/subpackage module names
   plugin-unique).
2. Update `config_schema.json` if config changed (mark fine-tuning keys
   `x-advanced`).
3. **Bump `version`** in `manifest.json`.
4. Run `python scripts/check_module_collisions.py`, and the safety harness from a
   core checkout.
5. Commit (the pre-commit hook syncs `plugins.json`) and open a PR — CI enforces
   the version bump, manifest schema, harness, and collisions.

[← Back to the guide index](./README.md)
