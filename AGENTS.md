# AGENTS.md — Cursor entry for ledmatrix-plugins

Read **`CLAUDE.md`** first for the full harness (goal, non-negotiables, local
setup, “working” definition, session-memory rules). Keep this file short.

## Goal

Maintain official LEDMatrix plugins + the Plugin Store registry. Core display
runtime is **not** in this repo (`ChuckBuilds/LEDMatrix`). Success = plugins
that version correctly for the store, load without module collisions, and pass
the render safety harness.

## Always do

- Bump `plugins/<id>/manifest.json` `version` + top `versions[]` entry on any
  non-`test/` change under that plugin.
- Never hand-edit `plugins.json` (use pre-commit / `update_registry.py`).
- Fetch in `update()`, draw in `display()`; cache with plugin-id-namespaced keys.
- Unique names for deferred/subpackage modules; run
  `python scripts/check_module_collisions.py`.
- Guard optional core imports with `ImportError` fallbacks.
- Before sports “shared” file edits →
  `docs/plugin-development/08-shared-sports-code.md` (port across lineage).

## Before calling a change done

Harness green (core `check_plugin.py`), collision check OK, version bumped,
no secrets committed. “Looked fine on one emulator size” is not enough.

## Memory

Promote repeated corrections and cold-start gotchas into `CLAUDE.md` in-session.
Decay stale/duplicated rules. Don’t leave load-bearing facts only in chat.

## Pointers

| Need | Where |
|------|--------|
| Dense harness | [CLAUDE.md](./CLAUDE.md) |
| Human guide | [docs/plugin-development/](./docs/plugin-development/) |
| Contribute / symlink setup | [CONTRIBUTING.md](./CONTRIBUTING.md) |
| Submit / verify plugin | [SUBMISSION.md](./SUBMISSION.md), [VERIFICATION.md](./VERIFICATION.md) |
