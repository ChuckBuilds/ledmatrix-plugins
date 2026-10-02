# Changelog

## [1.19.2] - 2026-10-02

### Changed
- The `has_live_content() returning ...` summary is logged at INFO only
  when the answer changes. The once-a-minute re-log of an unchanged answer
  is now DEBUG: at INFO it was a persistent-journal line a minute, each one
  an SD-card write, for as long as the device ran.

## [1.19.1] - 2026-10-01

### Changed
- Uses `src/common/sports_plugin_host.py`, `src/common/sports_display_rules.py` and `src/common/sports_font_path.py`,
  which LEDMatrix core 3.8.0 ships. The core floor is unchanged.

### Removed
- `UFCScoreboardPlugin`'s Vegas weighting (`get_vegas_priority_weight`,
  `_favorite_team_is_live` and its scan helpers), the off-thread switch
  refresh (`_dispatch_switch_refresh`, `_SWITCH_REFRESH_MIN_GAP_SECONDS`),
  `get_vegas_content_type` and the dynamic-duration helpers
  (`_dynamic_feature_enabled`, `_get_total_games_for_manager`,
  `_build_manager_key`): it inherits `SportsPluginHostMixin`
  (`src.common.sports_plugin_host`).
- `_filtered_or_all`: `SportsCore` inherits `SportsGameRulesMixin`
  (`src.common.sports_display_rules`).
- `_resolve_font_path` in `sports.py`, `fight_renderer.py` and `headshot_downloader.py`: imported from
  `src.common.sports_font_path` under the same name.

No behaviour change: the code is the same, and every safety-harness render,
scroll card and celebration golden is pixel-identical.

## [1.19.0] - 2026-09-30

### Added
- Live Vegas cards: in the Vegas ticker each fight is its own card, and a card already scrolling across the panel updates in place when its fight changes -- the round, the clock, the result -- instead of showing what it was when it was drawn. Only the card whose fight changed is redrawn. A fight that ends keeps its card, now showing the result, until the recent list picks it up. Nothing changes outside Vegas, and get_vegas_content() is unchanged for older cores and multi-display sync.

### Changed
- Requires LEDMatrix core 3.8.0 (`ledmatrix_min_version` and `compatible_versions`), the first release with live Vegas elements (`src.common.sports_vegas`). The store refuses to install or update this version onto an older core.

## [1.18.3] - 2026-09-30

### Fixed
- Odds load. Every UFC odds request was `.../events/<bout>/competitions/<bout>/odds`,
  which ESPN answers with 404 (recorded as "no odds" and cached), because the URL
  needs the card's id as the event: `.../events/<card>/competitions/<bout>/odds`
  returns the DraftKings line. Each extracted bout now registers its card with
  the odds manager (`register_bout`), which builds the right URL and cache key
  (`odds_espn_mma_ufc_<card>_<bout>`; the harness mock is rekeyed to match).
- Upcoming keeps a long card's headliners. ESPN lists a card's bouts main event
  last and the main card shares one start time, so the soonest `upcoming_games_to_show`
  by time alone dropped the co-main and main event of UFC 331 (10 of 12 shown).
  When the pool is full its first-listed bouts are dropped first; the sooner card
  still fills first, and the pool is shown in start order.

### Tests
- `test_odds_and_headliners.py`: the odds URL and cache key, and the pool, over
  the recorded UFC 331 scoreboard.

## [1.18.2] - 2026-09-30

### Fixed
- The live display follows the bout in the cage. ESPN's MMA scoreboard sends
  a whole fight card as ONE event whose competitions are its bouts, early
  prelims first, and the live manager read only `competitions[0]`. So
  `live_games`, the live switch view, the Vegas cards and the finished-fight
  capture all followed that one early prelim: once it was over, the card
  showed nothing live while the main card was on. The live fetch now splits
  each card into its bouts (as Recent and Upcoming already did), and each
  bout is its own fight, keyed by its competition id, with the card as its
  `event_id`.
- A bout that has not started, or ended without a result, has no clock.
  ESPN sends a scheduled bout's `displayClock` as `-`, and the shared live
  update counts any clock but `0:00` as a running one: on fight day the first
  bout sat on the live screen, claiming live priority, until the card began,
  and with the card split every scheduled bout would have joined it. A bout
  in progress keeps ESPN's clock (`-` during walkouts and round breaks), and
  a finished one keeps its finish time.
- Each bout is dated with its own start, ESPN's per-bout `date` (its
  segment: early prelims, prelims, main card), instead of the card's opening
  time. Upcoming showed the main event at the early prelims' start, hours
  early, and Recent, newest first among bouts that all tied, showed the
  first five listed (the early prelims) instead of the main card. A bout
  without a date of its own still takes the card's.

Checked against all 103 Wayback captures of ESPN's UFC scoreboard from 2026
(1,259 bouts): the old live manager held exactly the bouts in progress in 31
of them, this one in all 103.

### Tests
- `test_every_bout_is_its_own_fight.py` replays UFC 331 from four recorded
  ESPN scoreboards of the night (`test/fixtures/espn_mma_fight_night.json`:
  fight-day morning, main card walkouts, round 3, card over) through the real
  live, recent and upcoming managers, with the network stubbed at
  `fetch_espn_scoreboard`.

## [1.18.1] - 2026-09-30

### Fixed
- The live scorebug shows ESPN's between-rounds text (`End R2`) during a break
  instead of `R2 -`. The break check looked for `STATUS_END_PERIOD`, the
  team-sport status name; ESPN's MMA feed sends `STATUS_END_OF_ROUND`
  (state `in`, displayClock `-` when the round went the distance, or the
  stoppage clock while a finish awaits its result).

### Tests
- `test_round_break_stays_live.py` runs ESPN scoreboard bouts in each state
  (recorded payloads in `test/fixtures/espn_mma_round_states.json`) through the
  real `UFCLiveManager.update()`. It pins that a five-round fight stays live
  through the round 4 break and until the result posts: the shared
  "clock `0:00` from period 4 is over" rule does not fire, because ESPN sends
  the break's clock as `-`, not `0:00`.

## [1.18.0] - 2026-09-29

### Changed
- Requires LEDMatrix core 3.7.0 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/sports_fetch.py`. The store refuses to
  install or update this version onto an older core.

### Removed
- `SportsCore._fetch_season_directly`, `_background_fetches_espn_ranges`,
  `_needs_previous_day` and `_wants_live_odds`: `SportsCore` inherits
  `SportsFetchMixin` (`src.common.sports_fetch`).

No behaviour change: the code is the same, and every safety-harness render
and celebration golden is byte-identical.

## [1.17.0] - 2026-09-29

### Changed
- Requires LEDMatrix core 3.6.1 (`ledmatrix_min_version` and
  `compatible_versions`), the floor the sports scoreboards share; 3.6.0 is the
  first release that ships `src/common/sports_timezone.py`. The store refuses
  to install or update this version onto an older core.
- `ufc_timezone.py` is now a thin binding: `resolve_timezone_name()` and
  `resolve_timezone()` call core's `src.common.sports_timezone` with this
  plugin's label, write-back release and logger, as they already did on a
  3.6.x core.

### Removed
- The fallback resolver in `ufc_timezone.py`, kept for cores without
  `src.common.sports_timezone`.

No behaviour change on a 3.6.x core: the timezone chosen and every log
message are the same, and every safety-harness render is byte-identical.

## [1.16.1] - 2026-09-29

### Changed
- On a core that ships it, the timezone resolver runs core's copy:
  `ufc_timezone.py` resolves through `src.common.sports_timezone` with this
  plugin's values. The core module was promoted from this file, which stays as
  the fallback on older cores (the floor stays 3.5.0).

No behaviour change: the timezone chosen and every log message are identical
on both paths, and every safety-harness render is byte-identical.

## [1.16.0] - 2026-09-28

### Changed
- Requires LEDMatrix core 3.5.0 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/espn_dates.py` and `src/common/sports_helpers.py`. The store
  refuses to install or update this version onto an older core.
- New UFC cards are noticed on time. With no fight live, the live check backs
  off as empty looks mount, up to `live_idle_max_interval_seconds` (15 minutes
  by default), and the back-off had no notion of the schedule: an idle night
  reached the ceiling, and the first bout of a card could go unnoticed for up
  to 15 minutes. The idle wait is now clamped to the next card start the live
  fetch has already seen, and held at the live update interval for 15 minutes
  after that start in case ESPN is slow to flip the status. This is core's fix
  (ChuckBuilds/LEDMatrix#599), arriving with core's `_idle_live_interval`
  below. 1.14.2 described it, but it never took effect here: this plugin's own
  copy lacked the clamp. No extra request is made.

### Removed
- `sports.py`'s private copies of core's shared sports code (650 lines).
  `SportsCore`, `SportsLive` and `SportsRecent` now inherit core's
  `SportsCoreSharedMixin`, `SportsHelpersMixin`, `SportsLiveSharedMixin` and
  `SportsRecentSharedMixin`, as the eight team scoreboards do. Deleted: 20
  methods whose bodies are identical to core's; `_get_weeks_data` and
  `_round_robin_favorites`, which behave identically but are written
  differently; `_idle_live_interval` (the change above);
  `_DWELL_REENTRY_GAP_SECONDS`; and the module helpers `_clamp_window`,
  `_clamp_seconds` and `_logo_needs_refresh`, now imported from core under the
  same names. The overrides that behave differently from core's
  (`_draw_scorebug_layout`, `_get_layout_offset`, `_draw_text_with_outline`)
  are kept.
- `ufc_espn_dates.py`, the bundled copy of core's ESPN date-range helper.
  `src.common.espn_dates` is now imported plainly; on a 3.5.0 core the plugin
  already ran core's copy.

### Tests
- A safety-harness fixture (`test/harness.json`, `test/fixtures/mock.json`)
  and 16 golden renders, recent and upcoming at eight sizes, taken before this
  change. Every render is byte-identical after it.

## [1.15.1] - 2026-09-28

### Fixed
- The UFC managers no longer fail when another scoreboard is loaded.
  `sports.py` imported a `dynamic_team_resolver` this plugin does not ship, so
  it bound another plugin's copy off `sys.path` and called it with
  `cache_manager=`, which hockey's (and most others') constructor rejects:
  after a live re-enable with hockey running, all three managers failed with
  `TypeError` and the plugin showed nothing. UFC has no teams to resolve
  (favourites are fighters), so the import is gone and the configured list is
  used as given.
- The scorebug's status, detail and record text use the configured fonts
  (tom-thumb and 4x6 by default). The schema's repo-relative paths were joined
  onto `assets/fonts` a second time, which logged
  `Font file not found: assets/fonts/assets/fonts/tom-thumb.bdf` and fell back
  to PressStart2P; at 64x32 the two fighters' records ran into each other.
- A 404 from ESPN's odds endpoint, which is how it answers for a bout with no
  line, is logged at DEBUG and cached as "no odds" like an empty response,
  instead of an ERROR on every update. Other HTTP errors still log ERROR.

## [1.15.0] - 2026-09-24

### Changed
- **1 config control(s) that cannot affect anything are no longer drawn.**
  Each stays declared — `"x-display": "hidden"` — so a config already carrying
  it keeps validating and nothing is lost on upgrade; only the form control goes
  away.

  - `scroll_settings.scroll_delay` (×1) — its own description has read "Kept
    so saved configs still load; ignored" for releases, yet it was still an
    editable number. `scroll_speed` is the only pacing control.

### Internal
- **The rankings-fetch gate was ported for lineage consistency.**
  `_fetch_team_rankings` now consults `_league_has_rankings` at the top,
  covering every caller instead of one. This plugin serves only college leagues
  that *do* publish a poll, so nothing about its behaviour changes — it is
  carried because sports.py is copied, not shared (CLAUDE.md non-negotiable #7),
  and a fix living in eight of nine copies is how the last one gets missed.

  Which leagues have a poll is **measured, not assumed** — ESPN's `/rankings`
  was probed for every scoreboard league on 2026-09-24. college-football (125
  teams), men's and women's college basketball (50 each), college hockey (4/5)
  and college lacrosse (28/33) answer 200 with real poll blocks; every
  professional league answers 404, and so does college baseball.

## [1.14.1] - 2026-09-17

### Changed
- **The bundled ESPN date helper fetches its chunks concurrently.** Since ESPN
  began rejecting `dates=YYYYMMDD-YYYYMMDD`, a season is fetched as one request
  per month, and a month over the 500-event cap becomes one per day -- about
  130 requests for four busy months of college baseball, previously issued one
  at a time (17.7s on a Pi 4; 2.6-3.3s now). This does not change the
  `update() timed out` lines some boots log: those are core's shared 20s
  startup budget running out, and the data still lands a tick later.
  Measured on a Pi 4 against live ESPN with run order alternated: one college-baseball month 5.3s before, 1.5-1.8s after; two
  capped months (63 requests, 3101 events) 6.4-7.5s before, 1.1-2.1s after.
  Same requests, same events, and merged events keep their existing order.
  A truncated month is dropped as soon as it is seen, so peak memory during a
  cold season fetch rises about 16 MB rather than 43 MB.
  Synced from LEDMatrix core ChuckBuilds/LEDMatrix#596.

## [1.14.0] - 2026-09-16

### Added
- **Settings saved in the web UI apply without a restart.** `on_config_change`
  rebuilds the league managers, registry, scroll manager and rotation from the
  new config, so league enables, durations, live priority, display modes and
  favorites take effect immediately. A save that omits `enabled` keeps the
  current state.

### Changed
- **The `*_display_mode` "scroll" option is documented as ignored.** The schema
  and README offered a scroll display mode that `display()` never had; fights
  always rotate one at a time and scroll only in Vegas mode. The option stays
  accepted so saved configs keep loading. `scroll_settings.scroll_delay` is
  likewise documented as ignored.
- **Corrected `get_update_interval()` docstring.** It claimed the sibling
  scoreboards gained the hook in #479; only football had it.

### Fixed
- **A fighter with no ESPN headshot no longer blanks the card.** About one
  fighter in ten has no ESPN headshot (a 404). The switch cards downloaded
  missing headshots from `display()` and cached only successes, so every frame
  re-requested the image, logged an ERROR with a traceback, and drew `Image
  Error` instead of the fight. Headshots are now fetched during `update()`,
  never while drawing; a failure is retried after 15 minutes, doubling to 6
  hours, with one warning per attempt; and the card is drawn without the missing
  headshot.
- **No more 125 FPS loop for static fight cards.** `enable_scrolling` was true
  whenever the scroll manager could be built, so every install re-rendered a
  static card every 8ms. This plugin's display modes never scroll, so it no
  longer asks for the high-FPS loop.
- **Switch mode refreshes its managers off the render thread.** The draw-time
  refresh in `_try_manager_display()` ran inline, freezing the panel for each
  due fetch; it now uses the same worker dispatch as afl/nrl/soccer.

## [1.13.1] - 2026-09-16

### Fixed
- **Scores and schedules load again after ESPN stopped accepting date
  ranges.** Since 2026-09-15 ESPN answers `dates=YYYYMMDD-YYYYMMDD` scoreboard
  queries with `400 Bad Request` for every sport. Today's games, the
  lookback/lookahead window and the season schedule are all ranges, so the
  UFC boards logged `400 Client Error` and showed nothing. A rejected
  range is now fetched by `fetch_espn_scoreboard` (`ufc_espn_dates.py`, a
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

## [1.13.0] - 2026-09-15

### Changed
- **Requires LEDMatrix core 3.4.0.** The scroll frame hold is passed to
  `display_manager.set_scrolling_state(True, frame_hold=...)`, an argument
  older cores do not have.

### Fixed
- **`ufc.scroll_settings.scroll_speed` / `scroll_delay` set the scroll speed
  again.** The shared scroll resolver was handed the whole plugin config and
  never looks in `ufc.scroll_settings`, so every user ran at its 100 px/s
  default. `scroll_speed` is now passed as pixels per second, as the schema
  and README describe (every value, including those under 10), and snapped to
  the nearest speed the panel can move in whole pixels.
- **Default speed change (Vegas fight cards).** Because the setting now takes
  effect, an install at defaults scrolls at 50 px/s instead of the 100 px/s it
  actually ran at. Set `ufc.scroll_settings.scroll_speed` to `100` for the old
  speed.
- **The frame hold is applied.** It was computed and never passed to core,
  so a snapped sub-refresh speed still presented a new frame every refresh.
  It is set while a scroll frame is drawn and released when the scroll
  completes or is reset.

### Removed
- The frame-based scroll setup and `target_fps` writes that ran before the
  resolver and were overwritten by it.

## [1.12.2] - 2026-09-14

### Fixed
- **A null period no longer stops live games updating.** The live check that
  drops games which look finished compared `game.get("period", 0) >= 4`; that
  default only covers a missing key, so a bout that is not final whose ESPN `status.period`
  was null raised `TypeError` (a `None` period text likewise raised
  `AttributeError`). `SportsLive.update()` does not catch it, so that league's
  whole live refresh was abandoned: live games already on the panel kept their
  last scores, new ones never appeared, and the error repeated on every poll
  while that game stayed in the feed. A null or non-numeric period now
  counts as 0 and a null or non-string period text as empty; thresholds and
  clock handling are unchanged. ESPN normally sends an integer, so this takes a
  malformed feed.

## [1.12.1] - 2026-09-14

### Removed
- The `ufc.game_limits` settings `other_upcoming_games_to_show`,
  `other_recent_games_to_show`, `other_rotation_interval_seconds`,
  `other_games_min_quality` and `other_games_divisions`. `MMARecent` and
  `MMAUpcoming` build their own fight lists and never run the shared
  favorites-then-others selection, so no other-games slice was ever built or
  rotated and changing these did nothing. `game_limits` does not reject
  unknown keys, so a saved value still loads; the web UI drops it on the next
  save. The README's "Which fights get shown" now describes what the selection
  actually does.

## [1.12.0] - 2026-09-14

### Added
- `ufc.odds_update_interval` and `ufc.live_odds_update_interval` (advanced).
  The code already read them; the schema now offers them.

### Fixed
- **Live fights refresh at `live_update_interval`.** The plugin implements
  `get_update_interval()` (core #555), which the eight sibling scoreboards
  gained in #479; the manifest's 60s used to be the only cadence. The live
  update also no longer dies on a `KeyError` for MMA fights, which carry no
  `is_halftime` flag or team abbreviations.
- **`*_display_mode: "scroll"` no longer holds the board to the dynamic-duration
  cap.** This plugin has no display-path scroll renderer, so waiting for scroll
  completion waited forever.
- **Vegas cards follow the fights.** They were built once and never rebuilt
  (the cache the core clears is not the one this plugin uses), and building
  them called `update()` — network I/O on the render path.
- **Postponed, cancelled and suspended bouts are no longer shown as results**
  on Recent: final now requires `status.type.completed` and excludes those
  statuses.
- **Upcoming honours `schedule_lookahead_days`**, instead of every fight in the
  season-wide fetch; and a mode re-taking the panel gives its current card a
  full dwell rather than advancing immediately (#345).
- **Full-screen odds no longer print through the round clock, result or fight
  class.** With no favourite the O/U anchors left and steps down a row on
  collision; a home spread of 0.0 is no longer treated as missing.
- Decoded headshot caches are LRU-bounded (core #559).
- One manager failing to construct no longer leaves Live, Recent and Upcoming
  all blank; each is built and updated independently.
- `other_games_divisions` is passed through raw (a string was split into
  letters, a null crashed the adapter), an `Infinity` window or interval setting
  falls back to its default, and "favorite fighters only" reaches the shared
  filter it never reached.
- "Logo Error" fallback in the shared switch renderer draws on the image it
  shows instead of a discarded copy.

## [1.11.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [1.10.0] - 2026-09-11

### Added
- **Style each card separately.** The font and size of the fighter names,
  status, result and detail text, and the position of the fighter images,
  fighter names, records, status, result, fight class, date, time and odds,
  can now differ between the live, upcoming and recent cards. Set them under
  "Per-Mode Overrides" in the plugin's settings; anything left blank follows
  the settings above it, so a single change applies to one card and leaves
  the others alone. Text colour is not configurable in this plugin.

  Existing configs are unaffected: with no per-mode overrides set, every card
  renders exactly as before -- verified against the golden images at all
  eight panel sizes.

## [1.9.2] - 2026-09-11

### Fixed
- **Small text is drawn on the font's pixel grid again.** `4x6-font` and
  `PressStart2P` are pixel faces: they rasterise cleanly only at whole multiples
  of their design grid (7 and 8 respectively). Off the grid FreeType
  anti-aliases to fake the in-between stroke widths — and on an LED panel that
  is a dim lamp, not a soft edge. Worse, these plugins draw 1-bit
  (`fontmode = "1"`), and the mono rasteriser thresholds each glyph at 50%
  coverage: at ppem 6 every 4x6 glyph came out 3px wide instead of 4, so `W`/`M`
  and `0`/`8` lost the pixels that distinguish them.

  The off-grid sizes also made rendering host-dependent. At ppem 6 `getlength`
  returns a fractional advance whose value depends on the installed FreeType
  (4.28px under Pillow 12.3, 5.0px under 11.3), so two boards on the same
  config measured the same string up to 17%% apart and centred it differently.
  On-grid sizes agree across both builds.

  This ports the crisp-font fix its eight sibling scoreboards already carry.
  Fighter names, status, detail, odds and records move from 4x6 at 6 to 7;
  result and score move from PressStart2P at 10 to 8, that face's nearest
  crisp size. The `tom-thumb` BDF is a bitmap face and is unchanged.

## [1.9.1] - 2026-09-09

### Fixed
- **`has_live_content()` no longer floods the journal during a live card.** It runs on the display path — once per *frame* in Vegas mode. The summary at the end of the function was throttled by `should_log and not ufc_live`, but a second INFO line sat inside the `if live_games:` branch with no guard at all, so a live card logged on every call: roughly 50 lines a second on a rig measured at 50 fps. Because every earlier throttle fix (baseball 1.20.4, football, hockey/basketball/lacrosse #308) inspected the guard rather than the whole function body, this call survived all of them. Both branches now share one state-change plus 60-second heartbeat throttle, matching `baseball-scoreboard`. Pinned by `test_live_content_log_throttle.py`.

## [1.7.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.
