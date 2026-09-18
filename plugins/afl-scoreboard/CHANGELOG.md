# Changelog

## [1.28.1] - 2026-09-17

### Changed
- **The bundled ESPN date helper fetches its chunks concurrently.** Since ESPN
  began rejecting `dates=YYYYMMDD-YYYYMMDD`, a season is fetched as one request
  per month, and a month over the 500-event cap becomes one per day -- about
  130 requests for a cold college-baseball season, previously issued one at a
  time. That outran the startup update budget core shares across all plugins,
  so scoreboards logged `update() timed out` on first run and were deferred
  with nothing on the panel. Measured on a Pi 4 against live ESPN with run order
  alternated: one college-baseball month 5.3s before, 1.5-1.8s after; two
  capped months (63 requests, 3101 events) 6.4-7.5s before, 1.1-2.1s after.
  Same requests, same events, and merged events keep their existing order.
  A truncated month is dropped as soon as it is seen, so peak memory during a
  cold season fetch rises about 16 MB rather than 43 MB.
  Synced from LEDMatrix core ChuckBuilds/LEDMatrix#596.

## [1.28.0] - 2026-09-16

### Added
- **Live games poll at the live interval.** The plugin implements
  `get_update_interval()`: while a game is in progress the core calls `update()`
  every `live_update_interval` seconds instead of at the static interval (the
  manifest's 60s, or `update_interval_seconds` where the manifest declares
  none). With nothing live it returns no opinion, so the idle cadence is
  unchanged. The Vegas cards and modes not on screen no longer lag behind the
  score.

### Changed
- **Requires LEDMatrix core 3.4.0**, the first release that consults
  `get_update_interval()` (ChuckBuilds/LEDMatrix#555).
- **`scroll_settings.scroll_delay` is documented as ignored.** It never affected
  scrolling (frames are paced to the panel refresh and `scroll_speed` sets the
  speed) but was described as a smoothness knob. The key stays declared so saved
  configs keep loading.

### Fixed
- **Scroll mode no longer freezes while a fetch runs.** The per-frame live
  refresh ran `manager.update()` on the render thread, so when a fetch was due
  the marquee stalled for the whole ESPN request. It is handed to a worker
  thread (one per manager at a time, at least 5s apart; the manager's own
  interval still decides whether anything is fetched).

## [1.27.2] - 2026-09-16

### Fixed
- **Scores and schedules load again after ESPN stopped accepting date
  ranges.** Since 2026-09-15 ESPN answers `dates=YYYYMMDD-YYYYMMDD` scoreboard
  queries with `400 Bad Request` for every sport. Today's games, the
  lookback/lookahead window and the season schedule are all ranges, so the
  AFL boards logged `400 Client Error` and showed nothing. A rejected
  range is now fetched by `fetch_espn_scoreboard` (`afl_espn_dates.py`, a
  copy of LEDMatrix core's `src/common/espn_dates.py`) as whole months plus the
  days at either end, which cover the window exactly: a season is 8 to 12
  requests. A month that comes back at ESPN's 500-event cap is re-fetched day by
  day, and after one rejection ranges go straight to chunks for 6 hours.
- **`limit=1000` silently truncated results.** Above 500 ESPN returns a short
  list with no error (college football: 25 of 68 games for one Saturday).
  Scoreboard requests now send at most 500.
- **Older cores.** A core whose background service cannot fetch ranges (before
  ChuckBuilds/LEDMatrix#591 added `handles_espn_date_ranges`) would send the
  season range to ESPN as-is, so the plugin fetches the season itself during
  `update()` instead. `SportsCore._get_weeks_data` is carried here for the same
  reason.

## [1.27.1] - 2026-09-14

### Fixed
- **Hardening: the live "looks finished" check no longer raises on a None or
  non-string period text.** `game.get("period_text", "").lower()` only
  defaults a missing key, so a `None` value raised, and `SportsLive.update()`
  does not catch it. The AFL parser only produces that for a postponed-style
  fixture where ESPN sends both a null `shortDetail` and a null status name.
  Such values are now treated as empty / period 0; the end-of-game rule is
  unchanged.

## [1.27.0] - 2026-09-14

### Fixed
- **Postponed / cancelled games no longer show as "Final 0-0" on Recent.**
  ESPN files them under state `post` with zero scores; `is_final` now also
  requires `status.type.completed` and a played status, and the period label
  uses ESPN's own ("Postponed", "Canceled").
- **Full-screen odds no longer overprint the top-centre text.** A total with no
  favourite anchors left instead of centring through the period / "Final" /
  league header, and steps down a row if it would still collide. A home spread
  of 0.0 is kept; a non-numeric top-level spread no longer drops the odds.
- **Saved-but-ignored settings now apply:** `display_options.show_records`,
  `show_ranking`, `show_odds` (ahead of the root duplicates), the celebration
  settings, `test_mode`, and `odds_update_interval` /
  `live_odds_update_interval` (now declared in the schema).
- **`other_games_divisions`** as a hand-edited string or null no longer
  filters out every game or leaves the plugin blank.
- **Vegas** rebuilds its cards when the game slate changes, reads only its own
  display, and logs per-frame at debug.
- Ported: `switch_show_date` / `switch_show_time` for the full-screen upcoming
  scorebug (#342); the lookahead cutoff and dwell reset on mode re-entry (#345);
  odds for rotated-in games (#343); bounded LRU logo caches (core #559); an
  unranked team shows its record when rankings and records are both on; a config
  `Infinity` no longer crashes manager init.

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.
- The core floor stays at 3.3.0. `sports.py` imports `src.common.sports_shared`,
  which first shipped in core v3.3.1, but that release still reports
  `__version__ = "3.3.0"`, so a 3.3.1 floor would refuse every current core.

### Fixed
- **Favorite game turns shows up in the web UI.** Also lists the root-level favorite_rotation_boost in x-propertyOrder: the previous release declared it but left it out of the order, so the web UI's config form never rendered the field (caught by scripts/test_property_order_coverage.py).

## [1.26.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [1.25.1] - 2026-09-14

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

## [1.25.0] - 2026-09-11

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

## [1.24.1] - 2026-09-11

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

## [1.24.0] - 2026-09-10

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
## [1.17.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.
