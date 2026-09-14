# Changelog

## [1.26.1] - 2026-09-14

### Fixed
- A root `show_records` / `show_ranking` / `show_odds` you changed is no
  longer overridden by the `display_options` copy of the same toggle still at
  its default. The web UI saves defaults into both blocks, and the adapter read
  `display_options` first. A changed `display_options` value still wins. Same
  precedence as afl-scoreboard.

## [1.26.0] - 2026-09-14

### Added
- `scroll_card.switch_show_date` / `switch_show_time`: the full-screen
  upcoming scorebug's own date/time toggles (football #342). The scroll card's
  `show_date` / `show_time` no longer blank it.
- `odds_update_interval` / `live_odds_update_interval` are declared in the
  schema and forwarded to the managers (the code already read them).

### Fixed
- Newcastle/Warriors ("NEW") and Canberra/Canterbury ("CAN") no longer share a
  logo: files are `<ABBR>_<team id>.png` and caches are keyed by team id. The
  old `<ABBR>.png` is still used until the per-team file has downloaded.
- Postponed, cancelled and suspended fixtures no longer show on Recent as
  "Final 0-0": a game is final only when ESPN marks it completed.
- Full-screen odds step down a row instead of overprinting the top-row status
  text when only an O/U is present; a home spread of 0.0 is no longer treated
  as missing.
- A failed logo shows "Logo Error" instead of a black panel.
- Upcoming is trimmed to `schedule_lookahead_days`; a mode retaking the panel
  gives its current card a full dwell (football #345).
- Games rotated into the other-games slice get odds (football #343).
- Vegas rebuilds its own slate when the games change, without calling update().
- A cached "no odds" marker is a cache hit, not a refetch.
- Decoded logo caches are bounded (core #559).
- Scroll card with rankings and records on: an unranked team shows its record.
- A config `Infinity` no longer crashes manager init; a string or null
  `other_games_divisions` no longer blanks the plugin; `test_mode` reaches the
  managers.
- The core floor stays at 3.3.0. `sports.py` imports `src.common.sports_shared`,
  which first shipped in core v3.3.1, but that release still reports
  `__version__ = "3.3.0"`, so a 3.3.1 floor would refuse every current core.

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.

### Fixed
- **Favorite game turns shows up in the web UI.** Also lists the root-level favorite_rotation_boost in x-propertyOrder: the previous release declared it but left it out of the order, so the web UI's config form never rendered the field (caught by scripts/test_property_order_coverage.py).

## [1.25.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [1.24.1] - 2026-09-14

### Fixed
- **Switch mode refreshes its managers before it draws them.**
  The switch path went straight to manager.display(), so it showed whatever the
  last background plugin.update() left behind -- baseball, basketball, football,
  hockey and lacrosse have called _ensure_manager_updated() unconditionally in
  _try_manager_display() all along, and these three had no equivalent. Measured
  with no background update at all: afl's switch mode made zero draw-time
  refreshes and the panel stayed frozen for ten simulated minutes, while
  baseball's picked the score up in thirty seconds. It is invisible at the 60s
  default and an hour stale for anyone who raises update_interval -- and unlike
  baseball/football, which declare update_interval in their manifest and so
  override any config value, these three declare none, which is what makes the
  config value apply and the slow case reachable. A stale manager also reads as
  having nothing to show, so a league with a live game could be skipped from the
  rotation entirely; the refresh therefore runs before the candidate managers
  are read, not after. _ensure_manager_updated() is interval-guarded, so on
  frames where no refresh is due this costs two getattrs and a comparison.
  Pinned by a test that asserts the wiring structurally as well as behaviourally
  -- deleting the call leaves every behavioural check passing while the panel
  silently goes stale, which is how this survived in three plugins.

The refresh is dispatched to a daemon thread rather than run inline, so a due fetch never stalls the render thread: at most one refresh per manager runs at a time, dispatches for a manager are at least 5s apart, and each manager's own update interval still decides whether anything is fetched.

## [1.24.0] - 2026-09-11

### Added
- **Style each card separately.** Font, size, colour and position for the
  score, clock, team abbreviation, status, detail, odds and ranking can now
  differ between the live, upcoming and recent cards. Set them under
  "Per-Mode Overrides" in the plugin's settings; anything left blank follows
  the settings above it, so a single change applies to one card and leaves
  the others alone.

  Existing configs are unaffected: with no per-mode overrides set, every card
  renders exactly as before -- verified against the golden images at all
  eight panel sizes.

## [1.23.1] - 2026-09-11

### Fixed
- **Live score updates now actually reach the scrolling strip.**
  1.41.0 added the rebuild-on-change machinery but wired it in the wrong order,
  which left it inert: the rebuild decision is computed by fingerprinting the
  live managers' cached games, and the only call that refreshed those managers
  (_ensure_manager_updated) sat INSIDE the block that decision gates. So once
  the first strip was built nothing refreshed the data, the fingerprint could
  never change, and the block never ran again -- the same frozen-until-restart
  symptom the previous release set out to fix. Switch mode was never affected
  because _try_manager_display() refreshes unconditionally on every pass; scroll
  mode now gets the same guarantee, refreshing the live managers before it
  fingerprints them. _ensure_manager_updated() is itself interval-guarded, so on
  frames where no refresh is due this costs two getattrs and a comparison.
  Ported across all eight scoreboards in one change, per CLAUDE.md non-
  negotiable #7, and pinned by a test that asserts the ordering structurally --
  reversing the two lines leaves every behavioural test passing while the panel
  silently freezes.

## [1.23.0] - 2026-09-10

### Fixed
- **Live games now reach the scrolling strip mid-cycle.**
  The strip was rendered once per scroll cycle and _scroll_prepared was cleared
  only when the cycle completed, so a score changed while the marquee was
  running stayed frozen in the pixels until it finished -- minutes, for a long
  game list. Restarting the display forced a rebuild, which is the workaround
  users were finding. The strip is now rebuilt when anything the card draws
  changes, keeping scroll_position and total_distance_scrolled so the marquee
  does not snap back to the start and the cycle still completes on schedule. The
  game clock deliberately does not trigger a rebuild -- it ticks every second
  and re-rendering every card that often is the whole frame budget on a Pi --
  and rebuilds are floored at 5s so a large slate cannot thrash. Ported across
  all eight scoreboards in one change, per CLAUDE.md non-negotiable #7. Rebuild
  frequency is self-limiting: the floor between rebuilds scales with what the
  last one actually cost, so the marquee never spends more than about 5% of its
  time frozen re-rendering. Measured on a Pi 4, a strip rebuild takes 29ms for
  one game and 463ms for fifteen; a fixed floor would have been fine for the
  first and wrong for the second. Sports whose period label embeds the clock
  (afl, nrl, soccer build it as "<period> <clock>") exclude period_text from the
  rebuild trigger too, or they would rebuild every second; the numeric period is
  a separate field and still catches a quarter/half change. Also fixes the
  rebuild-cost bookkeeping being keyed differently from where it is read, which
  left the duty-cycle cap inert in most plugins.
## [1.16.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.
