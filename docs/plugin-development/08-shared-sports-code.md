# 8. Shared Sports Code — Lineages, Drift, and the Convergence Plan

The nine sports scoreboards (`afl`, `baseball`, `basketball`, `football`,
`hockey`, `lacrosse`, `nrl`, `soccer`, `ufc`) each ship their **own copy** of a
family of shared-shape modules:

| Module | Copies | Notes |
|---|---|---|
| `sports.py` | 9 | `SportsCore` / `SportsUpcoming` / `SportsRecent` / `SportsLive` |
| `scroll_display.py` | 10 | + `f1-scoreboard` (a reduced rewrite) |
| `data_sources.py` | 9 | soccer's copy is byte-equivalent to the core's |
| `base_odds_manager.py` | 9 | ufc's is a genuine MMA fork (athlete odds) |
| `game_renderer.py` | 8 | |
| `dynamic_team_resolver.py` | 8 | true forks — different constructor signatures |
| `logo_downloader.py` | 6 | five other plugins already import `src.logo_downloader` |

None of these copies are identical. **Any fix to a shared-shape file must be
applied to every lineage member in the same PR** — the cautionary example is
commit `8d33894` (the UTC start-time fix), which required touching **75 files**
because one logical change had to be replicated across ten plugins.

## The three lineages

The copies did not drift randomly; they form three families. When porting a
fix, find your plugin's lineage siblings first — their copies are close enough
to share a patch, while cross-lineage copies usually are not.

1. **soccer / afl / nrl** — the newest lineage (~3,160 lines). Uniquely has
   SWRR (smooth weighted round-robin) live rotation (`_swrr_advance`) and
   goal celebrations spelled `_check_for_goal` / `_should_celebrate_goal_for`.
   Favorite/live-duration helpers live on `SportsCore`.
2. **football** — has score celebrations spelled `_check_for_score` /
   `_should_celebrate_score_for` / `_score_phrase`, the adaptive-layout
   scorebug (`_adaptive_scorebug`, `layout_mode` config), and is the only
   `sports.py` that imports `src.element_style` and `game_renderer`.
3. **hockey / lacrosse / baseball / basketball / ufc** — the oldest lineage
   (2,400–2,900 lines). No celebration code. Live rotation via
   `_build_weighted_schedule` (baseball/basketball/football) or
   `_build_rotation_schedule` (hockey). Favorite/live-duration helpers live on
   `SportsLive`.

The common ancestor is the **core repo's** `src/base_classes/sports.py` (same
four classes, plus a core-only skin system the plugin copies lack). Only 28 of
the 66 methods appearing across the nine copies are present in all of them.

## Convergence direction

The long-term home for this code is the core repo, so a fix lands once and
every scoreboard benefits. Convergence happens module by module, gated on what
the core actually ships:

- **Already converged:** `logo_downloader` (afl, nrl, ufc, basketball, soccer
  import `src.logo_downloader`); `odds-ticker` uses `src.*` for everything and
  ships no local copies — it is the model citizen.
- **Converging now:** `base_odds_manager`. The eight non-UFC scoreboards import
  it guardedly, preferring the core's version:

  ```python
  try:
      from src.base_odds_manager import BaseOddsManager  # core-shipped
  except ImportError:
      from base_odds_manager import BaseOddsManager      # bundled fallback
  ```

  Both branches are module-level (entry-point load time), so they are safe
  under the loader's bare-name isolation rules (see doc 07 / CLAUDE.md module
  naming). The local copy stays until the sunset rule below is met.
- **Not converging (documented forks):** `dynamic_team_resolver` (plugin copies
  take `cache_manager` in the constructor; the core's does not — different
  API), ufc's `base_odds_manager` (MMA athlete-odds fork), and — until the core
  ships a unified version — `sports.py` / `scroll_display.py` / 
  `game_renderer.py` themselves.

## Device-wide settings: read them from the core, not a copy

Cross-cutting settings are the other half of this problem. `self.config` is
only the plugin's own slice, so a device-wide value like the scroll frame rate
has no copy to converge — it simply wasn't reachable.

The core now exposes the whole config on `BasePlugin`:

```python
fps = getattr(self, 'global_config', {}).get('target_fps')
```

Resolution is `plugin_manager.config_manager` then `cache_manager.config_manager`,
returning `{}` when neither exists. Always go through
`getattr(self, 'global_config', {})` as above so a plugin still loads on a core
that predates the property. Treat the result as **read-only** — it is the live
config dict, and mutating it has bitten this repo before (a plugin writing
`self.config["timezone"]` back persisted a stale `"UTC"` for every consumer).

Assignment still works and overrides the resolved value, which is what
`news`, `stock-news`, `ledmatrix-stocks`, `ledmatrix-elections`,
`ledmatrix-leaderboard` and `nfl-draft` rely on when they set
`self.global_config = config.get('global', {})`.

## The sunset rule

A plugin may **delete** its local copy of a converged module only when both are
true:

1. The plugin's manifest declares `ledmatrix_min_version` **at or above the
   first core release that ships the module** (check the core CHANGELOG; the
   core exposes its version as `src.__version__`).
2. The safety harness passes with the local copy removed.

Until then, keep the guarded try-core/except-local import: the loader's
compatibility check is **advisory only** (it logs a warning and never blocks),
so the `except ImportError` fallback is the real protection for users running
an older core.

### Worked example: the scroll display

Core 3.2.0 ships `src/common/sports_scroll.py`, which holds the *orchestration*
half of `scroll_display.py` — scroll-helper configuration, frame pumping,
completion, settings resolution, and native `global_config['target_fps']`
support. The *content* half stays per-plugin, permanently: a survey of the eight
copies that share a shape found `prepare_scroll_content` has eight distinct
bodies (145 lines, 53% similar at worst) because each draws its own game card.
Same method name, different job.

Once a plugin floors at 3.2.0, the adoption is mechanical:

```python
from src.common.sports_scroll import SportsScrollDisplay, SportsScrollDisplayManager

class ScrollDisplay(SportsScrollDisplay):
    # The ladder the local _get_scroll_settings used to hardcode, same order.
    SCROLL_LEAGUE_KEYS = ("nhl", "ncaa_mens", "ncaam_hockey")

    def scroll_settings_defaults(self):
        # Only where this plugin's defaults differ from core's.
        return {**super().scroll_settings_defaults(), "game_card_width": 128}

    def _load_separator_icons(self): ...      # per-sport
    def prepare_scroll_content(self, games, game_type, leagues, rankings=None): ...

class ScrollDisplayManager(SportsScrollDisplayManager):
    display_class = ScrollDisplay
```

Delete the local `__init__`, `_configure_scroll_helper`, `_get_scroll_settings`,
`display_scroll_frame`, `_log_scroll_progress`, `is_scroll_complete`,
`reset_scroll`, `get_scroll_info`, `clear`, and the whole manager body except
methods that genuinely differ. Keep `_determine_game_type` if your plugin
supports `'mixed'` scrolls.

**Measured on hockey-scoreboard** against a core carrying 3.2.0: 691 → 289
lines, and all 16 harness renders (8 sizes × 2 screens) byte-for-byte identical
to the pre-adoption run. That byte-comparison is the acceptance gate — run the
harness before and after and `diff -r` the two output directories.

Two things to watch when you do this:

- **Check the imports you inherited.** `_load_separator_icons` uses `os.path`
  even though nothing else in the trimmed file does; dropping `import os` with
  the rest is an easy way to break the plugin at load time.
- **The base always constructs a `ScrollHelper`**, so `if not self.scroll_helper`
  guards inherited from the old copy are dead. Harmless, but delete them rather
  than leaving a check that can never fire.

## Rules for future changes

- **Fix all lineage members in one PR.** Grep every copy of the file you're
  changing; the CI harness runs on every changed plugin, so a complete sweep
  gets full coverage automatically.
- **Keep the copies structurally aligned within a lineage** — gratuitous
  refactors in one copy make the next cross-copy patch harder.
- **New shared functionality goes to the core first** when possible, with a
  guarded import and a classic fallback in the plugins (the
  `src.element_style` / `src.adaptive_layout` adoption pattern).
- **Never introduce a deferred (function-scoped or subpackage) bare-name import
  of a shared-shape module** — that is exactly the collision case
  `scripts/check_module_collisions.py` exists to catch.
