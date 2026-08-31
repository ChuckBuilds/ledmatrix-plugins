# 6. Manifest & Config Schema

[← Guide index](./README.md) · [← Adaptive layout](./05-adaptive-layout.md)

Two files describe your plugin to the system: `manifest.json` (metadata the store
and loader read) and `config_schema.json` (the form the web UI generates). This
page covers both, plus the all-important version workflow.

---

## `manifest.json`

Validated on every PR against the core repo's `schema/manifest_schema.json`.

### Core required fields

| Field | Meaning |
|-------|---------|
| `id` | Plugin identifier — **must match the directory name** |
| `name` | Human-readable display name |
| `version` | Semver string, e.g. `"1.2.3"` |
| `class_name` | The Python class name in the entry point |
| `display_modes` | Array of the mode names this plugin supports |

### Fields present on essentially every plugin

`author`, `description`, `entry_point` (always `manager.py`), `tags`, `versions`
(the changelog array), `last_updated`, and `compatible_versions` (an array of
constraint strings — almost all use `[">=2.0.0"]`).

### Common optional fields

| Field | Meaning |
|-------|---------|
| `entry_point` | Python file with the class (default `manager.py`) |
| `category` | Store category |
| `config_schema` | Path to the schema file (the string `"config_schema.json"`) |
| `icon`, `homepage`, `license` | Store display / links |
| `verified`, `stars`, `downloads`, `screenshot` | Store display fields |
| `update_interval`, `default_duration` | Default timing hints |

### The `versions[]` changelog

An array of per-release records. Each has `version` and `released` (a date), and
usually a minimum-core-version key and a description:

```json
"versions": [
  { "version": "1.0.3", "released": "2026-05-15", "ledmatrix_min": "2.0.0", "notes": "..." }
]
```

> **Known inconsistency — pick one key going forward.** The minimum-core-version
> field appears under two spellings inside `versions[]`: `ledmatrix_min` and
> `ledmatrix_min_version`. Many manifests mix both. Likewise the description field
> varies (`notes`, `note`, `changes`, `changelog`). When you add a changelog
> entry, prefer **`ledmatrix_min_version`** and **`notes`** for consistency — but
> check what your plugin already uses and match it until a repo-wide normalization
> lands.

> **⚠️ A top-level floor overrides `versions[]` entirely.** The core resolves the
> floor in this order (`src/plugin_system/compatibility.py:declared_min_version`),
> stopping at the first one it finds:
>
> 1. top-level `min_ledmatrix_version`
> 2. top-level `requires.min_ledmatrix_version`
> 3. `versions[0].ledmatrix_min_version`, else `versions[0].ledmatrix_min`
>
> Note the **name is inverted** between the two locations — `min_ledmatrix_version`
> at the top level, `ledmatrix_min_version` inside `versions[]` — which is easy to
> read past. Four plugins declare the top-level form today (`ledmatrix-flights`,
> `ledmatrix-leaderboard`, `ledmatrix-music`, `ledmatrix-stocks`), and for those
> **editing `versions[0]` changes nothing the core reads.** Check for a top-level
> key before raising a floor, and raise the one that actually wins.
>
> Only `versions[0]` is ever consulted, so a floor declared on an older entry is
> dead. If a release needs a newer core, that requirement is cumulative: every
> later entry must carry it too, or the next bug-fix release silently drops it.

---

## `config_schema.json`

**JSON Schema Draft-07** (`"$schema": "http://json-schema.org/draft-07/schema#"` —
all 39 plugins use it). The web UI generates the config form from this file, so
it's the source of truth for available options.

### Conventions

- **Every option needs a `default`, a `description`, and constraints** (`minimum`,
  `maximum`, `enum`, etc.) so the form is self-documenting and validates input.
- **Mirror each `default` in code** with `config.get(key, default)` using the same
  value — the schema default and the code default aren't linked automatically;
  they're kept in sync by convention.
- **Mark fine-tuning keys `x-advanced`** and use the other `x-` extensions to
  shape the form — see [topic 4](./04-styling-and-skins.md#x--config-form-extensions).
- `enabled` is nearly always the sole `required` entry.

### Conventional keys most plugins share

| Key | Type | Typical default | `x-advanced`? |
|-----|------|-----------------|---------------|
| `enabled` | boolean | `false` (top-level toggle) | No |
| `display_duration` | number | 15–40 seconds | No |
| `update_interval` | integer | 1 (clocks) → 3600 (data) | Usually |
| `scroll_delay` | number | ~0.01 s/frame | Usually |
| `timezone` | string \| null | `null` (inherits global) | No |
| `position_x` / `position_y` | integer | 0 | Usually |

---

## The version workflow

**This is the single most important rule in the repo.** The plugin store ships
updates by comparing `manifest.json` `version` against `plugins.json`
`latest_version`. If you change plugin code without bumping the version, users
never receive the update — and CI fails the PR.

### Every plugin change:

1. Make your code changes in `plugins/<plugin-id>/`.
2. **Bump `version`** in `plugins/<plugin-id>/manifest.json` (semver).
3. Commit — the pre-commit hook runs `update_registry.py` and stages the updated
   `plugins.json` into the same commit.

### Semver guidance

| Bump | When |
|------|------|
| **Patch** (1.0.0 → 1.0.1) | Bug fixes, minor text changes |
| **Minor** (1.0.0 → 1.1.0) | New features, config-schema additions |
| **Major** (1.0.0 → 2.0.0) | Breaking config changes, major rewrites |

### The pre-commit hook

`scripts/pre-commit` is a template — install it once:

```bash
cp scripts/pre-commit .git/hooks/pre-commit
```

It only fires when a `plugins/*/manifest.json` is staged. When it does, it runs
`update_registry.py` and folds the regenerated `plugins.json` into your commit.
If it isn't installed, run `python update_registry.py` yourself before committing.

See [topic 7](./07-testing-ci-and-registry.md) for how `update_registry.py` and
the CI gates work in detail.

**Next:** [Testing, CI & the registry →](./07-testing-ci-and-registry.md)
