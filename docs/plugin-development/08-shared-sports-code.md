# 8. Shared Sports Code — Lineages, Drift, and the Convergence Plan

The nine sports scoreboards (`afl`, `baseball`, `basketball`, `football`,
`hockey`, `lacrosse`, `nrl`, `soccer`, `ufc`) each ship their **own copy** of a
family of shared-shape modules:

| Module | Copies | Notes |
|---|---|---|
| `sports.py` | 9 | `SportsCore` / `SportsUpcoming` / `SportsRecent` / `SportsLive`. The celebration drawing and the season-fetch / lookback / live-odds methods are core's (3.7.0, see below) |
| `scroll_display.py` | 10 | + `f1-scoreboard` (a reduced rewrite) |
| `data_sources.py` | 9 | soccer's copy is byte-equivalent to the core's |
| `base_odds_manager.py` | 1 | ufc's MMA fork (athlete odds) only; the other eight import core's `src.base_odds_manager` |
| `game_renderer.py` | 8 | the `sports_card` delegations are core's `SportsCardWrappersMixin` (3.7.0) |
| `dynamic_team_resolver.py` | 8 | true forks — different constructor signatures |
| `logo_downloader.py` | 0 | every scoreboard imports core's `src.logo_downloader` (f1-scoreboard's same-named file is an unrelated `F1LogoLoader`) |
| `<sport>_espn_dates.py` | 0 | none left. All nine scoreboards floor on core 3.5.0 and import `src.common.espn_dates` plainly (sunset: the eight team scoreboards in stage 1a, ufc in 1b). `scripts/test_espn_dates_copies.py` fails if a plugin in its `SUNSET_PLUGINS` grows its copy or a guarded import back, and on a fetch that sends ESPN `dates` without the helper. Fix it in core |
| `<sport>_favorite_check.py` | 0 | none left. afl, baseball, basketball, football, hockey, lacrosse, nrl and soccer floor on core 3.6.1 (the first release with the favourite check's finished-season fix, which also reads a soccer matchday break correctly) and import `src.common.favorite_team_check` plainly; soccer's `manager.py` dropped the older check these grew out of. `scripts/test_timezone_and_favorite_check_copies.py` fails if a copy or a guarded import comes back. Fix it in core. ufc has none: its favourites are fighter names and weight classes, and ESPN publishes no UFC team list to check them against |
| `<sport>_timezone.py` | 10 | the nine scoreboards + `f1-scoreboard`, all floored on core 3.6.1. Not a copy any more: each is a thin binding whose `resolve_timezone_name` / `resolve_timezone` call core's `src.common.sports_timezone` with the plugin's label, write-back release and module logger. The same script fails if resolver code grows back in one, and checks each binding's values against core's resolver, every log message included. Fix the resolver in core |

Apart from the sport-prefixed helpers, none of these copies are identical. **Any fix to a shared-shape file must be
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
   (2,400–2,900 lines). Only hockey celebrates (goals and wins, spelled
   `_check_for_goal` like the soccer lineage, with its own net scenery).
   Live rotation via
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

- **Already converged:** `logo_downloader` and `base_odds_manager` (every
  scoreboard imports `src.logo_downloader`, and the eight non-UFC scoreboards
  import `src.base_odds_manager`, plainly); `odds-ticker` uses `src.*` for
  everything and ships no local copies — it is the model citizen. Core has
  shipped both modules since v3.0.0, and every scoreboard floors at 3.4.0 or
  above and already imports `src.common.sports_shared` (3.3.0) unguarded, so
  the bundled fallbacks they used to carry could never run and were deleted.
  (Core's `BaseOddsManager` still lacks the `no_odds` cache-hit fix the old
  bundled copies had; that is a core change.)
- **Converged at 3.5.0 (all nine scoreboards):** `src.common.espn_dates`
  and `src.common.sports_helpers`. afl, baseball, basketball, football,
  hockey, lacrosse, nrl and soccer floor on 3.5.0, the first release that
  ships both; each deleted its `<sport>_espn_dates.py`, its private helper
  copies in `sports.py`, and its `SportsCore._get_weeks_data` override (the
  3.5.0 `SportsCoreSharedMixin` fetches that window through
  `fetch_espn_scoreboard` itself). They keep `_background_fetches_espn_ranges`
  and `_fetch_season_directly`, which serve the path with no background
  service. ufc followed in stage 1b (1.16.0): it deleted `ufc_espn_dates.py` and
  its helper copies too, and it adopted `src.common.sports_shared`'s mixins,
  which it alone had not used (see below).
- **Converged at 3.6.1 (sports consolidation stage 2):**
  `src.common.favorite_team_check` and `src.common.sports_timezone`, promoted
  from the copies above and first shipped in core 3.6.0
  (`scripts/check_min_core_version.py` dates them). The nine scoreboards and
  f1 floor on 3.6.1, whose favourite check has the fix for calling a started
  postseason a finished season (core #667). The seven favourite-check copies
  are deleted and `manager.py` imports core's plainly (soccer's too, replacing
  its own older check); each
  `<sport>_timezone.py` keeps only its binding (label, write-back release,
  logger), so its callers and tests are unchanged.
- **Converged at 3.7.0 (sports consolidation stage 3):** three modules
  holding code that was identical in every plugin carrying it. The nine
  scoreboards floor on 3.7.0 and import them plainly;
  `scripts/test_stage3_mixin_copies.py` fails if a copy, a guarded import or
  a missing base comes back.
  - `src.common.sports_fetch` — `SportsCore` (all nine) inherits
    `SportsFetchMixin`: `_fetch_season_directly`,
    `_background_fetches_espn_ranges`, `_needs_previous_day`,
    `_wants_live_odds`.
  - `src.common.sports_celebration` — `SportsLive` in afl, football, hockey,
    nrl and soccer inherits `SportsCelebrationMixin`, which draws the
    score/win takeover (`_draw_celebration_layout`, the team palette read off
    the crest, scenery, confetti); the colour helpers are its free functions.
    Only the drawing moved: each plugin still decides when to celebrate, the
    phrase and the scenery (`_start_celebration`, `_check_for_goal` /
    `_check_for_score`, `_check_for_win`, nrl matching favourites by id), and
    keeps its own `display()`. `scripts/test_celebration_renders.py` pins the
    takeover's pixels in all five.
  - `src.common.sports_card_wrappers` — `GameRenderer` (the eight with one)
    inherits `SportsCardWrappersMixin`, the `sports_card` delegations
    `SportsGameRendererMixin` expects. football keeps its own
    `_format_game_date` and `_upcoming_center_mode` (they follow the
    switch-mode settings), which override the mixin's.

  Identical but deliberately left in the plugins: `_get_timezone` (binds the
  plugin's own timezone module), the abstract `_extract_game_details` /
  `_fetch_data`, `SportsUpcoming.__init__` (no core mixin has a
  constructor), and the renderer's `_schema_font_size` / `_resolve_font_size`
  (they read the plugin's own `config_schema.json`).
- **Not converging (documented forks):** `dynamic_team_resolver` (plugin copies
  take `cache_manager` in the constructor; the core's does not — different
  API), ufc's `base_odds_manager` (MMA athlete-odds fork), and — until the core
  ships a unified version — `sports.py` / `scroll_display.py` / 
  `game_renderer.py` themselves.

### Sports helpers: core's `sports_helpers`

Core's `src/common/sports_helpers.py` (ChuckBuilds/LEDMatrix#583, released in
3.5.0) promotes the helpers every `sports.py` carried verbatim
(`_clamp_window`, `_clamp_seconds`, `_logo_needs_refresh`, the window
constants, and the `SportsCore` methods `_mode_customization`, `_setting_int`,
`_reset_dwell_on_reentry`, `_next_switch_index`, `_spread_weighted_order`,
`_odds_color`, `_upcoming_date_and_time_text`). All nine scoreboards
have adopted it: `class SportsCore(SportsCoreSharedMixin, SportsHelpersMixin,
ABC)`, with the module-level helpers imported under their old private names
(`from src.common.sports_helpers import clamp_window as _clamp_window, ...`)
so callers and tests of `sports._clamp_window` are unchanged.

`scripts/check_sports_helpers_parity.py` compares any plugin copy that
reappears with core's as a docstring-stripped AST and fails on any difference,
so a fix to one side has to land on both. None remain: an absent copy in a
plugin that imports the core module counts as adoption, and its guard test
asserts the team scoreboards do. It skips (exit 2) only against a core checkout predating
that module; CI runs it against core main, where it is present, and its guard
test fails rather than skips if it ever goes missing.

ufc-scoreboard adopted it last (1.16.0, floor 3.5.0), and was also the one
scoreboard not on `src.common.sports_shared`: its `SportsCore`, `SportsLive` and
`SportsRecent` now inherit `SportsCoreSharedMixin` + `SportsHelpersMixin`,
`SportsLiveSharedMixin` and `SportsRecentSharedMixin` in the order the team
scoreboards use, with the module-level helpers imported under their old
private names. What remains in its `sports.py` is its own: the overrides
whose behaviour differs from core's (`_draw_scorebug_layout`,
`_get_layout_offset`, `_draw_text_with_outline`) and the methods core does not
ship. Inheriting `_idle_live_interval` brought it core's #599 kickoff clamp.

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

A plugin may **delete** its local copy of a converged module only when all three
are true:

1. The plugin's manifest declares `ledmatrix_min_version` **at or above the
   first core release that ships the module** (check the core CHANGELOG; the
   core exposes its version as `src.__version__`).
2. The safety harness passes with the local copy removed.
3. The core **enforces** that floor at install/update time, and has done so long
   enough that few users run a core without the enforcement.

**Condition 3 now holds for `src.common.sports_scroll`, and B6 has run.** All
eight scoreboards have deleted their bundled `scroll_display_legacy.py`, their
imports are plain, and their floors are at 3.2.0 — the release that ships the
module. **Stage 1 of the sports consolidation did the same for
`src.common.espn_dates` and `src.common.sports_helpers`** in the same eight
plugins (stage 1a) and in ufc (stage 1b), flooring them on 3.5.0;
`scripts/test_espn_dates_copies.py` keeps its own `SUNSET_PLUGINS` set for the ESPN helper.

The history matters, because conditions 1 and 2 were written as if declaring a
floor protected anyone, and for a long time it did not:

- The loader's compatibility check is **advisory only** — it logs a warning and
  never blocks. That is still true.
- It doesn't even warn for the users most at risk. It skips entirely when the
  core's parsed version is below `2.0.0`, and the `v3.1.0` release ships
  `__version__ = "1.0.0"`.
- The store did not compare the core version at all.

That last point is what changed. The store now refuses on **all three** routes
in — `install_plugin` (core #431/#433), the git-pull branch of `update_plugin`
(#508), and `install_from_url` (#510) — so a plugin whose floor exceeds the
running core cannot be installed or updated onto it, and a refused update
leaves the user on the version they already had.

Delete a copy without the floor and the plugin still raises
`ModuleNotFoundError` at load; the core catches it, marks the plugin `ERROR`,
logs one line, and carries on. The user just loses that scoreboard with no
explanation. **The floor is what prevents that, so raise it in the same commit
that deletes the copy.**

**For a module that has NOT been through a sunset, keep the guarded
try-core/except-local import** — the fallback is still the only protection
until its own condition 3 is met. The guard must name the exact dotted path: a
missing `src/common/sports_scroll.py` raises with
`exc.name == 'src.common.sports_scroll'`, which `{"src"}` does not match.

And when you do sunset one, drop the guard along with the copy. Keeping
`try/except` with nothing behind it names the missing *fallback* rather than
the core module that is actually absent — and that name is the single line the
user gets. `scripts/check_scroll_adoption.py` enforces this for the plugins
listed in its `SUNSET_PLUGINS` set; add yours there in the same PR.

The core-side record is phase **B6** in the core repo's
`docs/SPORTS_UNIFICATION.md`. Keep these two documents in agreement — if you
change the sunset rule here, change it there in the same change. (They live in
different repositories, so "the same PR" is impossible; land them together and
cross-link the numbers.)

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
