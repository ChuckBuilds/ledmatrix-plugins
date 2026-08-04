# LEDMatrix Plugin Development Guide

This is the deep-dive developer guide for building plugins in the
[ledmatrix-plugins](https://github.com/ChuckBuilds/ledmatrix-plugins) monorepo.
It's the **human-readable** companion to the repo's [`CLAUDE.md`](../../CLAUDE.md)
(which is the dense, LLM-facing quick reference).

A plugin is a self-contained Python package that the LEDMatrix **core**
(`ChuckBuilds/LEDMatrix`, a separate repo) loads at runtime and renders on an
RGB LED matrix. This repo ships plugin source plus the registry (`plugins.json`)
that the in-app plugin store reads.

## Start here

New to plugins? Copy [`plugins/hello-world/`](../../plugins/hello-world/) and read
it top to bottom — it's the minimal working reference every section below points
back to. Then work through these topics in order:

| # | Topic | What it covers |
|---|-------|----------------|
| 1 | [Plugin anatomy & lifecycle](./01-plugin-anatomy.md) | Directory layout, `BasePlugin`, and the six lifecycle methods the core calls |
| 2 | [The core API surface](./02-core-api.md) | Everything the core hands you: `display_manager`, `cache_manager`, `font_manager`, `plugin_manager`, config |
| 3 | [Advanced features](./03-advanced-features.md) | Dynamic duration, live priority, high-FPS scrolling, and Vegas continuous-scroll |
| 4 | [Styling & skins](./04-styling-and-skins.md) | User-customizable fonts/colors/offsets (`customization`, `x-style-elements`) and the `x-` UI extensions |
| 5 | [Adaptive layout](./05-adaptive-layout.md) | `layout_mode` classic vs. adaptive, and rendering across matrix sizes |
| 6 | [Manifest & config schema](./06-manifest-and-config-schema.md) | Manifest fields, `config_schema.json` conventions, and the version workflow |
| 7 | [Testing, CI & the registry](./07-testing-ci-and-registry.md) | Safety harness, module-collision checks, `plugins.json`, and the CI gates |
| 8 | [Shared sports code](./08-shared-sports-code.md) | The nine `sports.py` lineages, how they drifted, and the convergence + sunset rules |
| 9 | [League coverage & data providers](./09-league-coverage-and-providers.md) | What it costs to add a league, non-ESPN provider adapters, and the registry proposal |

## The golden rules

These trip up nearly every first plugin. Each is expanded in the topic pages:

1. **Bump the version on every change.** The store ships updates by comparing
   `manifest.json` `version` to `plugins.json` `latest_version`. Forget it and
   users never get your change — and CI fails the PR. See
   [topic 6](./06-manifest-and-config-schema.md#the-version-workflow).
2. **Fetch in `update()`, draw in `display()`.** Never hit the network from
   `display()`. See [topic 1](./01-plugin-anatomy.md).
3. **Cache anything you fetch** through `self.cache_manager`, namespaced by
   plugin id. See [topic 2](./02-core-api.md#cache-manager).
4. **Import optional core features defensively.** Newer capabilities
   (`VegasDisplayMode`, `src.adaptive_layout`, `src.element_style`) don't exist on
   older cores — guard every import with `try/except ImportError` and fall back.
   See [topics 3](./03-advanced-features.md) and [5](./05-adaptive-layout.md).
5. **Give deferred/subpackage modules plugin-unique names.** Two plugins sharing
   a bare module name (`data_model.py`) can bind each other's module and fail to
   load. See [topic 7](./07-testing-ci-and-registry.md#module-collisions).
6. **Render correctly at every matrix size** (64×32, 128×32, 128×64, 256×32).
   The safety harness enforces it. See [topic 5](./05-adaptive-layout.md) and
   [topic 7](./07-testing-ci-and-registry.md#the-safety-harness).

## Where things live

- **This repo** (`ledmatrix-plugins`) — plugin source, manifests, config schemas,
  the registry, and the collision/registry tooling in `scripts/`.
- **The core repo** (`ChuckBuilds/LEDMatrix`) — `BasePlugin`, the display/cache/font
  managers, the optional subsystems (`src.adaptive_layout`, `src.element_style`),
  the manifest JSON Schema, and the safety harness (`scripts/check_plugin.py`).
  You import from it but you don't edit it here.

> Every code reference in this guide points at a real plugin in this repo so you
> can see the pattern in context. When in doubt, grep the sports scoreboards —
> they exercise almost every feature.
