# LEDMatrix Plugins Monorepo — Agent Harness

## What this project is

This repo is the **official plugin registry + plugin source** for
[LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix). It does **not** contain
the display core. The core lives in a separate repo (`ChuckBuilds/LEDMatrix`);
this repo ships:

- `plugins/<plugin-id>/` — ~39 self-contained Python plugins the core loads
- `plugins.json` — registry the in-app Plugin Store consumes (**auto-generated;
  never hand-edit**)
- tooling/CI that keeps versions, collisions, and render safety honest

**Goal for agent work here:** ship plugins that install from the store, load
cleanly beside other plugins, fetch safely, and render correctly on real LED
panels — without breaking the version → store update pipeline.

Human deep-dive: `docs/plugin-development/`. This file is the dense, LLM-facing
harness. Prefer pointing at docs over restating them.

---

## Non-negotiables (project-specific)

These are not general Python advice — they exist because of how *this* stack works.

1. **Bump `manifest.json` `version` on every plugin change** (semver). Add the
   new entry at the **top** of the `versions` array; keep `version` in sync with
   that top entry. The store compares manifest version to `plugins.json`
   `latest_version`. Forget the bump → users never get the update; CI fails the PR.
   Even README-only edits under `plugins/<id>/` (outside `test/`) count.
2. **Never hand-edit `plugins.json`.** Commit with the pre-commit hook
   (`cp scripts/pre-commit .git/hooks/pre-commit`) or run
   `python update_registry.py`. CI also regenerates on push to `main`.
3. **Fetch in `update()`, draw in `display()`.** Never hit the network from
   `display()`. Cache network data via `self.cache_manager`, keys namespaced by
   plugin id.
4. **Deferred/subpackage modules need plugin-unique names** (e.g.
   `election_data_model.py`, not `data_model.py`). The core loads top-level
   `*.py` as bare names, then isolates; late imports can bind another plugin's
   module. Relative imports do not work (no package context). Enforce with
   `python scripts/check_module_collisions.py`.
5. **Render must survive the safety harness** — no crash, nothing drawn past
   the panel edge. Default matrix sizes are eight (see
   `docs/plugin-development/07-testing-ci-and-registry.md`); design for the
   classic four first (64×32, 128×32, 128×64, 256×32). Harness lives in the
   **core** repo: `LEDMatrix/scripts/check_plugin.py`.
6. **Guard optional core imports** (`VegasDisplayMode`, `src.adaptive_layout`,
   `src.element_style`, core `BaseOddsManager`, …) with `try/except ImportError`
   and a classic fallback — older cores stay loadable.
7. **Shared sports modules are copied, not shared.** Scoreboards ship divergent
   copies of `sports.py` / `scroll_display.py` / etc. A fix in one lineage must
   be ported to siblings in the **same PR**. See
   `docs/plugin-development/08-shared-sports-code.md` before touching those files.
8. **Secrets never in git.** Real tokens live on the Pi / LEDMatrix runtime
   (`config_secrets.json`), not in this monorepo. Keep only
   `config_secrets.template.json` in git; mark secret schema fields `x-secret`.
   OAuth artifacts (`credentials.json`, `token.pickle`) are gitignored at the
   repo root.

Starter template: `plugins/hello-world/`. Best feature references: sports
scoreboards (`hockey-scoreboard`, `football-scoreboard`, …).

---

## Layout (quick)

```text
plugins/<id>/   manifest.json, manager.py (or entry_point), config_schema.json,
                requirements.txt, README, assets/, optional test/
plugins.json    store registry (generated)
update_registry.py
scripts/        collision check, team pickers, pre-commit, …
docs/plugin-development/   human guide
```

Plugin class: subclass `BasePlugin` from the core
(`src.plugin_system.base_plugin.BasePlugin`). Constructor args:
`plugin_id, config, display_manager, cache_manager, plugin_manager`.

Required manifest fields: `id` (matches directory), `name`, `version`,
`class_name`, `display_modes`. Full field list / schema conventions →
`docs/plugin-development/06-manifest-and-config-schema.md`.

Config schemas are JSON Schema Draft-07 with UI `x-*` extensions
(`x-advanced`, `x-widget`, `x-secret`, …). Mirror schema `default`s in
`config.get(key, default)`. Details → docs topic 4 and 6.

Advanced opt-ins (cache, live priority, dynamic duration, Vegas, adaptive
`layout_mode`, high-FPS scroll) → `docs/plugin-development/03-advanced-features.md`
and topic 5. Do not reinvent the API catalog here.

---

## Version bumps

| Bump | When |
|------|------|
| **PATCH** | Bug fix, perf, docs-only in plugin tree |
| **MINOR** | New feature or backward-compatible config keys / modes |
| **MAJOR** | Breaking schema/config, removed options, rewrite |

After code change: bump manifest → commit (hook syncs registry) → PR. CI
(`.github/workflows/test-plugins.yml`) enforces bump + harness + schema;
`module-collisions.yml` runs across all plugins.

---

## Local setup (bus-factor)

Cold-start facts that are easy to rediscover the hard way:

- **This tree must be a git clone to contribute.** A zip extract under
  `Downloads/` has no `.git`, so hooks, PRs, and version-bump CI context are
  unavailable. Prefer:
  `git clone https://github.com/ChuckBuilds/ledmatrix-plugins.git`
- **You need a sibling LEDMatrix core checkout** for the harness, emulator, and
  `BasePlugin` imports:
  ```bash
  git clone https://github.com/ChuckBuilds/LEDMatrix.git
  git clone https://github.com/ChuckBuilds/ledmatrix-plugins.git
  cd LEDMatrix
  ln -s ../ledmatrix-plugins/plugins/<plugin-id> plugin-repos/<plugin-id>
  # or: scripts/dev/dev_plugin_setup.sh
  python3 scripts/dev_server.py          # http://localhost:5001
  EMULATOR=true python3 run.py
  ```
- **Harness before PR:**
  ```bash
  # from LEDMatrix core checkout
  python scripts/check_plugin.py --plugin <id> \
    --plugin-dir /path/to/ledmatrix-plugins/plugins --out-dir /tmp/preview
  ```
- **Install the pre-commit hook** in the plugins repo:
  `cp scripts/pre-commit .git/hooks/pre-commit`
- **Secrets:** core/runtime `config_secrets.json` (not this repo); plugin-local
  `plugins/**/config_secrets.json` is gitignored. Never commit real tokens.
- **Registry:** `update_registry.py` only updates `latest_version` from local
  manifests for monorepo plugins; third-party entries keep their own `repo` URL
  and empty `plugin_path`.

More: `CONTRIBUTING.md`, `SUBMISSION.md`, `VERIFICATION.md`.

---

## What “working” means

A change is **correct** only if all of the following hold for touched plugins:

| Signal | How we know it’s broken | Automatic check |
|--------|-------------------------|-----------------|
| Store can ship the update | Version not bumped / mismatches `versions[0]` / `plugins.json` stale | CI version gate + pre-commit `update_registry.py` |
| Plugin loads beside others | Deferred import binds another plugin’s module | `scripts/check_module_collisions.py` + CI |
| Manifest valid | Missing required fields / schema drift | CI vs core `schema/manifest_schema.json` |
| Renders on panels | Crash, draw past edge, or golden drift | Core `check_plugin.py` + CI harness |
| Config UI ↔ runtime | Schema default ≠ `config.get` default; README tables lie | Manual + PR checklist; prefer matching schema |
| No secret leak | Key/token committed | `.gitignore` + PR template / VERIFICATION |

Optional but strong: commit `plugins/<id>/test/harness.json` + golden PNGs so
visual drift fails CI instead of showing up on a Pi.

**Do not treat as “works”:** “looks fine on one size in the emulator once.”

---

## Session memory (compounding)

Harness knowledge dies when it only lives in a chat transcript or a one-off fix.

**Capture → promote → decay**

1. **Capture** — When Jean corrects the same fact twice, or a cold-start
   rediscovery costs real time (setup path, sports lineage, harness sizes,
   secret location), write it into **this file** under the right section in the
   same session. Do not leave it only in chat.
2. **Promote** — Standing decisions belong here as imperative rules (the
   Non-negotiables list). Long tutorials belong in `docs/plugin-development/`;
   link them. Duplicate the same rule in `.cursorrules` / `AGENTS.md` only as a
   short pointer — one source of truth.
3. **Decay** — Remove or fix instructions that contradict the docs (e.g. stale
   “four sizes only” when the harness matrix grew), leftover **core-repo** edit
   checklists that don’t apply to this plugins monorepo, and API laundry lists
   that a model already knows once pointed at a reference plugin.
4. **Do not accumulate** — No changelog of every session. Prefer fewer, sharper
   rules. If a section grows past “skim in 30 seconds,” move detail to docs and
   keep the rule + link.

**Resurface each session:** read `AGENTS.md` (entry) + this file’s
Non-negotiables before editing a plugin. For sports shared-file edits, open
topic 08 first.

---

## Standing decisions (so we don’t re-argue)

- Prefer editing an existing plugin’s patterns over inventing new architecture.
- New plugins start from `hello-world`, not by copying a full scoreboard.
- Mark fine-tuning config keys `x-advanced: true`.
- `layout_mode` (not `layout_engine`) for adaptive opt-in; default `classic`.
- When both a fix and an exploratory rewrite are possible, ship the smallest
  fix that restores harness green + correct store versioning.
- Commit only when Jean asks; don’t push unless asked.
- Don’t edit `plugins.json` by hand to “help.”

---

## Scripts cheat sheet

```bash
python update_registry.py                 # sync plugins.json from manifests
python update_registry.py --dry-run
python scripts/check_module_collisions.py
python scripts/check_team_pickers.py      # --apply regenerates ESPN enums
```

CI: `test-plugins.yml` (bump + schema + harness), `module-collisions.yml`,
`update-registry.yml` (push to `main`).

---

## Out of scope here

- Changing LEDMatrix **core** APIs, web UI templates, or `BasePlugin` — that’s
  the other repo. If a plugin needs a newer core API, bump `ledmatrix_min` /
  `compatible_versions` in the manifest and document it; don’t pretend core
  files live in this tree.
