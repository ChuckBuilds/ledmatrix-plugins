# Changelog

## [1.31.1] - 2026-09-17

### Changed
- **The bundled ESPN date helper fetches its chunks concurrently.** Since ESPN
  began rejecting `dates=YYYYMMDD-YYYYMMDD`, a season is fetched as one request
  per month, and a month over the 500-event cap becomes one per day -- about
  130 requests for a cold college-baseball season, previously issued one at a
  time. That outran the startup update budget core shares across all plugins,
  so scoreboards logged `update() timed out` on first run and were deferred
  with nothing on the panel. Measured on a Pi 4 against live ESPN, two capped
  months (63 requests, 3101 events): 11.2s before, 1.6s after. Same requests,
  same events, and merged events keep their existing order.
  Synced from LEDMatrix core ChuckBuilds/LEDMatrix#596.

## [1.31.0] - 2026-09-16

### Added
- **Live games poll at the live interval.** The plugin implements
  `get_update_interval()`: while a game is in progress the core calls `update()`
  every `live_update_interval` seconds instead of at the static interval (the
  manifest's 60s, or `update_interval_seconds` where the manifest declares
  none). With nothing live it returns no opinion, so the idle cadence is
  unchanged. The Vegas cards and modes not on screen no longer lag behind the
  score.
- **Settings saved in the web UI apply without a restart.** `on_config_change`
  rebuilds the league managers, registry, scroll manager and rotation from the
  new config, so league enables, durations, live priority, display modes and
  favorites take effect immediately. A save that omits `enabled` keeps the
  current state.

### Changed
- **Requires LEDMatrix core 3.4.0**, the first release that consults
  `get_update_interval()` (ChuckBuilds/LEDMatrix#555).
- **`scroll_settings.scroll_delay` is documented as ignored.** It never affected
  scrolling (frames are paced to the panel refresh and `scroll_speed` sets the
  speed) but was described as a smoothness knob. The key stays declared so saved
  configs keep loading.

### Fixed
- **Switch-only installs no longer run the 125 FPS loop.** `enable_scrolling`
  was true whenever the scroll manager could be built, so the default all-switch
  config re-rendered a static scorebug every 8ms. The high-FPS loop is now
  requested only when a mode is actually set to scroll
  (`_has_any_scroll_mode()`, as football/afl/nrl/soccer do).
- **Scroll mode no longer freezes while a fetch runs.** The per-frame live
  refresh ran `manager.update()` on the render thread, so when a fetch was due
  the marquee stalled for the whole ESPN request. It is handed to a worker
  thread (one per manager at a time, at least 5s apart; the manager's own
  interval still decides whether anything is fetched).
- **Switch mode refreshes its managers off the render thread.** The draw-time
  refresh in `_try_manager_display()` ran inline, freezing the panel for each
  due fetch; it now uses the same worker dispatch as afl/nrl/soccer.

## [1.30.1] - 2026-09-16

### Fixed
- **Scores and schedules load again after ESPN stopped accepting date
  ranges.** Since 2026-09-15 ESPN answers `dates=YYYYMMDD-YYYYMMDD` scoreboard
  queries with `400 Bad Request` for every sport. Today's games, the
  lookback/lookahead window and the season schedule are all ranges, so the
  NHL and NCAA hockey boards logged `400 Client Error` and showed nothing. A rejected
  range is now fetched by `fetch_espn_scoreboard` (`hockey_espn_dates.py`, a
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

## [1.30.0] - 2026-09-15

### Added
- **`show_powerplay` draws a power-play marker (#431).** ESPN's
  `situation.isPowerPlay` was parsed into `power_play` and the setting was
  resolved into the manager config, but nothing drew either. A live card now
  shows a yellow `PP` centred between the clock and the score when those rows
  can hold it (every panel 48 rows or taller). On 32-row panels, which have no
  free row, the period/clock text is drawn yellow instead. The switch scorebug
  (`hockey.py`) and the scroll/Vegas card (`game_renderer.py`) share the rule,
  and the card resolves the setting through the same
  `display_options` → league → `defaults` ladder as shots on goal. With the
  setting off, or no power play, renders are unchanged.

### Documentation
- Removed the README's stale note that scroll and Vegas cards never show shots
  on goal; `game_renderer.py` already reads `show_shots_on_goal`.

## [1.29.1] - 2026-09-14

### Fixed
- **A null period no longer stops live games updating.** The live check that
  drops games which look finished compared `game.get("period", 0) >= 3`; that
  default only covers a missing key, so a scheduled or postponed game whose ESPN `status.period`
  was null raised `TypeError` (a `None` period text likewise raised
  `AttributeError`). `SportsLive.update()` does not catch it, so that league's
  whole live refresh was abandoned: live games already on the panel kept their
  last scores, new ones never appeared, and the error repeated on every poll
  while that game stayed in the feed.
  `update()` refreshes every league inside one `try`, so it also skipped that
  cycle's Recent/Upcoming refresh and every league after the failing one. A null or non-numeric period now
  counts as 0 and a null or non-string period text as empty; thresholds and
  clock handling are unchanged. ESPN normally sends an integer, so this takes a
  malformed feed.

## [1.29.0] - 2026-09-14

Drift fixes: behaviour sibling scoreboards already had, ported here.

### Added
- `scroll_card.switch_show_date` / `switch_show_time` (football #342). The
  full-screen upcoming scorebug read the scroll card's `show_date`/`show_time`,
  so hiding the date on the ticker also blanked it on the scoreboard.
- `update_intervals.live_odds` (default 60s). `update_intervals.odds` was
  declared but never forwarded to the managers; both now reach them.

### Fixed
- **Postponed, cancelled and suspended games no longer show on Recent as
  "Final 0-0".** ESPN files them under state `post`. A game is now final only
  when `status.type.completed` is set and the status is not
  postponed/canceled/suspended/delayed/abandoned.
- **A failed logo shows "Logo Error" instead of a black panel.** The text was
  drawn on a throwaway `.convert("RGB")` copy (three sites).
- **Full-screen odds no longer overprint the period and clock, "Final" or
  "Next Game".** An O/U with no favourite sits on the left instead of the
  centre, and the odds move down a row if they would still hit the top-centre
  text. A home spread of 0.0 is a pick'em, not a missing value, and a
  non-numeric top-level spread no longer raises.
- Upcoming now stops at `schedule_lookahead_days`. Selection read the
  season-wide cache, so it could show games weeks away (football #345).
- A mode that retakes the panel gives its current card a full dwell instead
  of skipping straight past it (football #345).
- Games rotated in between hourly updates now get odds (football #343).
- Vegas: the cards are rebuilt when scores or the slate change, not only when
  the cache is empty. Vegas reads only its own 'mixed' display and no longer
  takes over the standalone scroll. The per-frame "Returning N image(s)" log
  is now debug.
- A cached "no odds" marker is a cache hit, so ESPN is no longer asked again
  on every call.
- Scroll cards: with rankings and records both on, an unranked team now shows
  its record instead of nothing.
- Logos come from the core's `src.logo_downloader`. The bundled copy saved any
  HTTP 200 body as a PNG and wrote unmarked placeholders the refresh check
  could not recognise, so one failed download left a permanent grey box.
- Decoded logo caches are bounded LRU (core #559).
- `other_games_divisions` is passed through as-is: a hand-edited `"fcs"` string
  is no longer split into letters, and a null no longer breaks the adapter.
  `test_mode` now reaches the managers.
- A config `Infinity` in the schedule window or an integer setting no longer
  crashes manager construction.

### Removed
- `data_fetcher.py`, `debug_tb_games.py` and the test that covered only
  `data_fetcher.py`. Nothing at runtime imported them.
- The vendored `logo_downloader.py`.

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.
- Behaviour change: Upcoming used to show the next games however far away
  they were. It now hides anything past `schedule_lookahead_days` (default 7),
  a favourite's game included, so in preseason or a long break the screen is
  empty until a game is inside the window. Raise the setting to see it sooner.
- The core floor stays at 3.3.0. `sports.py` imports `src.common.sports_shared`,
  which first shipped in core v3.3.1, but that release still reports
  `__version__ = "3.3.0"`, so a 3.3.1 floor would refuse every current core.

## [1.28.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [1.27.0] - 2026-09-11

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

## [1.26.1] - 2026-09-11

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

## [1.26.0] - 2026-09-10

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
  first and wrong for the second. Also fixes the rebuild-cost bookkeeping being
  keyed differently from where it is read, which left the duty-cycle cap inert
  in most plugins.
## [1.25.7] - 2026-09-11

### Fixed
- **Placeholder team logos draw their abbreviation at PressStart2P 16, not 12.**
  That face is crisp only at multiples of 8; 12 was anti-aliased, and 16 is the
  nearest crisp size for the 64px logo tile. Panel text was already on-grid via
  `_FONT_PIXEL_GRID` and is unchanged.

## [1.20.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.
