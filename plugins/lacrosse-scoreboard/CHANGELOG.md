# Changelog

## [1.36.4] - 2026-10-05

### Fixed
- A game level at 0:00 at the end of the fourth quarter (or of an overtime)
  stays on the live display through the break instead of leaving it as if
  over; it leaves when ESPN calls it final, as a game that really ends tied
  does. `SportsLive._is_game_really_over` is now one body in all nine
  scoreboards; each declares `FINAL_PERIOD`, the period from which a 0:00
  clock ends a game (None: the clock never does). Here it is 4.

## [1.36.3] - 2026-10-02

### Changed
- `defaults.game_display_duration` is hidden: nothing reads it (per-game time
  comes from each league's `display_durations`; the value only appeared in the
  plugin's status info). Kept declared so saved configs keep validating.
- README documents `defaults.game_display_duration`,
  `<league>.update_intervals.live_odds` and `scroll_card.switch_show_date` /
  `switch_show_time`.

## [1.36.2] - 2026-10-02

### Changed
- The `has_live_content() returning ...` summary is logged at INFO only
  when the answer changes. The once-a-minute re-log of an unchanged answer
  is now DEBUG: at INFO it was a persistent-journal line a minute, each one
  an SD-card write, for as long as the device ran.

## [1.36.1] - 2026-10-01

### Changed
- Uses `src/common/sports_plugin_host.py`, `src/common/sports_live_scroll.py`, `src/common/sports_display_rules.py` and `src/common/sports_font_path.py`,
  which LEDMatrix core 3.8.0 ships. The core floor is unchanged.

### Removed
- `LacrosseScoreboardPlugin`'s Vegas weighting (`get_vegas_priority_weight`,
  `_favorite_team_is_live` and its scan helpers), the off-thread switch
  refresh (`_dispatch_switch_refresh`, `_SWITCH_REFRESH_MIN_GAP_SECONDS`),
  `get_vegas_content_type` and the dynamic-duration helpers
  (`_dynamic_feature_enabled`, `_get_total_games_for_manager`,
  `_build_manager_key`): it inherits `SportsPluginHostMixin`
  (`src.common.sports_plugin_host`).
- The live scroll strip's mid-cycle rebuild (`_live_scroll_needs_rebuild`,
  `_preserving_scroll_position`, the fingerprint helpers and the two
  `LIVE_SCROLL_REBUILD_*` constants): the plugin class inherits
  `SportsLiveScrollMixin` (`src.common.sports_live_scroll`).
  `LIVE_VOLATILE_FIELDS` stays here.
- `_card_option`, `_recent_date_text`, `_filtered_or_all`, `_effective_live_duration`: `SportsCore` inherits `SportsCardOptionsMixin` and `SportsGameRulesMixin`
  (`src.common.sports_display_rules`).
- `_resolve_font_path` in `sports.py` and `game_renderer.py`: imported from
  `src.common.sports_font_path` under the same name.

No behaviour change: the code is the same, and every safety-harness render,
scroll card and celebration golden is pixel-identical.

## [1.36.0] - 2026-09-30

### Added
- Live Vegas cards: in the Vegas ticker each game is its own card, and a card already scrolling across the panel updates in place when its game changes -- the score, the clock, FINAL -- instead of showing what it was when it was drawn. Only the card whose game changed is redrawn. A game that goes final keeps its card, now showing FINAL, until the recent list picks it up. Nothing changes outside Vegas, and get_vegas_content() is unchanged for older cores and multi-display sync.

### Changed
- Requires LEDMatrix core 3.8.0 (`ledmatrix_min_version` and `compatible_versions`), the first release with live Vegas elements (`src.common.sports_vegas`). The store refuses to install or update this version onto an older core.

## [1.35.0] - 2026-09-29

### Changed
- Requires LEDMatrix core 3.7.0 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/sports_fetch.py` and `src/common/sports_card_wrappers.py`. The store refuses to
  install or update this version onto an older core.

### Removed
- `SportsCore._fetch_season_directly`, `_background_fetches_espn_ranges`,
  `_needs_previous_day` and `_wants_live_odds`: `SportsCore` inherits
  `SportsFetchMixin` (`src.common.sports_fetch`).
- The `sports_card` delegations in `game_renderer.py`: `GameRenderer`
  inherits `SportsCardWrappersMixin` (`src.common.sports_card_wrappers`).

No behaviour change: the code is the same, and every safety-harness render
and celebration golden is byte-identical.

## [1.34.0] - 2026-09-29

### Changed
- Requires LEDMatrix core 3.6.1 (`ledmatrix_min_version` and
  `compatible_versions`). 3.6.0 is the first release that ships
  `src/common/favorite_team_check.py` and `src/common/sports_timezone.py`;
  3.6.1 is the first whose favourite-team check has the finished-season fix
  this plugin shipped in 1.33.3. The store refuses to install or update this
  version onto an older core.
- `lacrosse_timezone.py` is now a thin binding: `resolve_timezone_name()` and
  `resolve_timezone()` call core's `src.common.sports_timezone` with this
  plugin's label, write-back release and logger, as they already did on a
  3.6.x core.

### Removed
- `lacrosse_favorite_check.py`, the bundled copy of core's favourite-team check.
  `manager.py` imports `src.common.favorite_team_check` plainly; on a 3.6.x
  core the plugin already ran core's copy.
- The fallback resolver in `lacrosse_timezone.py`, kept for cores without
  `src.common.sports_timezone`.

No behaviour change on a 3.6.x core: the timezone chosen and every log
message are the same, and every safety-harness render is byte-identical.

## [1.33.2] - 2026-09-29

### Fixed
- Test fixture only, no runtime change. The harness made 112 live ESPN
  requests per run and, after its frozen clock ended, fetched next season's
  schedule. freezegun gives the real clock to the SwitchRefresh thread
  display() starts, so its manager is always due and update() runs; update()
  fetched the NCAA poll (other_games_min_quality defaults to 'ranked') and the
  live manager fetched today's scoreboard, because with no live games it polls
  on its idle back-off rather than the huge update_intervals.live the fixture
  relied on. The fixture now sets other_games_min_quality 'any' and test_mode,
  so update() reads only the seeded cache and the run makes no requests.
  Rendered frames are unchanged.

## [1.33.1] - 2026-09-29

### Changed
- On a core that ships them, the favourite-team check and the timezone
  resolver run core's copies: `manager.py` imports `FavoriteTeamCheck` from
  `src.common.favorite_team_check`, and `lacrosse_timezone.py` resolves through
  `src.common.sports_timezone` with this plugin's values. Both core modules
  were promoted from this plugin's own `lacrosse_favorite_check.py` and
  `lacrosse_timezone.py`, which stay as the fallback on older cores (the floor
  stays 3.5.0).

No behaviour change: the timezone chosen and every log message are identical
on both paths, and every safety-harness render is byte-identical.

## [1.33.0] - 2026-09-28

### Changed
- Requires LEDMatrix core 3.5.0 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/espn_dates.py` and `src/common/sports_helpers.py`. The store
  refuses to install or update this version onto an older core.

### Removed
- `lacrosse_espn_dates.py`, the bundled copy of core's ESPN date-range helper.
  `src.common.espn_dates` is now imported plainly; on a 3.5.0 core the plugin
  already ran core's copy.
- `sports.py`'s private copies of the shared sports helpers: `_clamp_window`,
  `_clamp_seconds`, `_logo_needs_refresh` (imported from core under the same
  names) and `SportsCore`'s `_mode_customization`, `_setting_int`,
  `_reset_dwell_on_reentry`, `_next_switch_index`, `_spread_weighted_order`,
  `_odds_color` and `_upcoming_date_and_time_text` (inherited from core's
  `SportsHelpersMixin`). Core's bodies are identical.
- `SportsCore._get_weeks_data`. The override existed because older cores' mixin
  sent ESPN a raw date range; core 3.5.0's mixin fetches the same window
  through the same range-safe helper.

No behaviour change: every safety-harness render is byte-identical.

## [1.32.1] - 2026-09-28

### Removed
- Deleted the bundled `base_odds_manager.py` fallback. It could never run:
  core has shipped `src.base_odds_manager` since v3.0.0, below this plugin's
  3.4.0 floor, so odds already came from core's `BaseOddsManager`. The
  import is now plain.
- Deleted the bundled `logo_downloader.py` fallback for the same reason:
  logos already came from core's `src.logo_downloader`.
- Deleted the unused `MLBAPIDataSource` and `SoccerAPIDataSource`
  data source classes; nothing referenced them.

No behaviour change.

## [1.31.5] - 2026-09-28

### Changed
- Removed code that nothing called. No change in behaviour.

## [1.31.4] - 2026-09-28

### Fixed
- Each league's scroll settings apply to that league's scrolling strip: the
  scroll speed and dynamic duration came from the men's-NCAA settings
  whichever league was shown.

## [1.31.3] - 2026-09-28

### Fixed
- Scroll and Vegas cards follow each league's Display Options for records
  and rankings. They read only the shared defaults, so the cards showed
  neither, whatever the league was set to; on Vegas the shots setting was not
  read either.

## [1.31.2] - 2026-09-28

### Fixed
- Upcoming games now stay up for the configured per-game time. SportsUpcoming
  set game_display_duration = 15, so every upcoming game got 15 s whatever the
  setting said; it now reads upcoming_game_duration, as football, baseball and
  ufc do. The adapter now forwards display_durations.recent and .upcoming to
  the managers as recent_game_duration / upcoming_game_duration; they were
  never passed, so Recent and Upcoming games also got 15 s each. Only boards
  with a non-default value change: the default is 15 s, the value the code
  used.
- The league's 'Enable dynamic duration' switch now works.
  supports_dynamic_duration returned the per-mode switch whenever it was
  present, and the core fills its default (off) into every config, so the
  league switch was never read. The league switch now turns dynamic duration
  on for every mode; a mode switch still turns on just that mode.

## [1.31.1] - 2026-09-28

### Changed
- Hides config controls that do nothing. defaults.update_interval_seconds and
  each league's update_intervals.base feed update_interval_seconds, which is
  never read: every manager replaces it with its own live, recent or upcoming
  interval. defaults.season_cache_duration_seconds and each league's
  display_durations.base have no reader. No behaviour change: the keys stay
  declared, so saved configs still load. README updated to match.

## [1.31.0] - 2026-09-24

### Changed
- **4 config control(s) that cannot affect anything are no longer drawn.**
  Each stays declared — `"x-display": "hidden"` — so a config already carrying
  it keeps validating and nothing is lost on upgrade; only the form control goes
  away.

  - `other_games_divisions` (×2) — the FBS / FCS / Other checkboxes. ESPN
    publishes those group rosters for **college football and nothing else**
    (`_DIVISION_GROUPS_BY_LEAGUE`), so here the lookup resolves nothing, the
    filter fails open, and no combination of boxes could change one game.
  - `scroll_settings.scroll_delay` (×2) — its own description has read "Kept
    so saved configs still load; ignored" for releases, yet it was still an
    editable number. `scroll_speed` is the only pacing control.

  Nothing poll-related was hidden here: both `ncaa_mens` and `ncaa_womens`
  leagues publish one.

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

## [1.30.1] - 2026-09-17

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

## [1.30.0] - 2026-09-16

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
- **Scroll mode scrolls again.** The plugin never asked the core for its
  high-FPS loop, so `*_display_mode: scroll` redrew once a second and the strip
  jumped a card-width at a time. It now sets `enable_scrolling` from
  `_has_any_scroll_mode()`.
- **Scroll mode no longer freezes while a fetch runs.** The per-frame live
  refresh ran `manager.update()` on the render thread, so when a fetch was due
  the marquee stalled for the whole ESPN request. It is handed to a worker
  thread (one per manager at a time, at least 5s apart; the manager's own
  interval still decides whether anything is fetched).
- **Switch mode refreshes its managers off the render thread.** The draw-time
  refresh in `_try_manager_display()` ran inline, freezing the panel for each
  due fetch; it now uses the same worker dispatch as afl/nrl/soccer.

## [1.29.2] - 2026-09-16

### Fixed
- **Scores and schedules load again after ESPN stopped accepting date
  ranges.** Since 2026-09-15 ESPN answers `dates=YYYYMMDD-YYYYMMDD` scoreboard
  queries with `400 Bad Request` for every sport. Today's games, the
  lookback/lookahead window and the season schedule are all ranges, so the
  NCAA lacrosse boards logged `400 Client Error` and showed nothing. A rejected
  range is now fetched by `fetch_espn_scoreboard` (`lacrosse_espn_dates.py`, a
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

## [1.29.1] - 2026-09-14

### Fixed
- **A null period no longer stops live games updating.** The live check that
  drops games which look finished compared `game.get("period", 0) >= 4`; that
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

### Added
- `update_intervals.live_odds` (advanced, default 60s) is declared in the
  schema. It and `update_intervals.odds` now actually reach the managers.

### Fixed
Fixes ported from the sibling scoreboards after the drift audit:
- The full-screen upcoming scorebug reads `switch_show_date` /
  `switch_show_time`, so turning off date/time on scroll cards no longer
  blanks it (football #342).
- Upcoming drops games past `schedule_lookahead_days`, and a mode that comes
  back on screen gives its current card a full dwell (#345).
- Non-favourite games swapped in by the other-games rotation get odds (#343).
- Postponed, cancelled and suspended games are no longer "final", so they
  don't show on Recent as "Final 0-0".
- When a logo fails to load, "Logo Error" is drawn on the image that gets
  shown, instead of a black panel.
- Full-screen odds with no favourite are anchored left rather than centred on
  top of the quarter / "Final" / "Next Game". Any odds label that would still
  overlap that text steps down a row. A 0.0 home spread is treated as a real
  line, and a non-numeric spread no longer knocks the odds off the card.
- Decoded logo caches are LRU-bounded (core #559).
- Vegas rebuilds its cards when the game slate changes. It reads only its own
  combined display, and never calls `update()` on the render path.
- A cached "no odds" marker counts as a cache hit, so it no longer triggers a
  refetch on every call.
- `sports.py` uses the core logo downloader, so a failed download is retried
  instead of leaving a grey placeholder forever. The bundled fallback
  downloader won't save a non-image response.
- The scroll card shows an unranked team's record when both ranking and
  records are on.
- The top-N rankings shortcut skips tournament and lower-division polls.
- If one league fails to build, the other league still loads.
  `other_games_divisions` accepts a plain string. `test_mode` is forwarded to
  the managers.
- A config value of `Infinity` for an other-games count can no longer crash
  selection.
- The core floor stays at 3.3.0. `sports.py` imports `src.common.sports_shared`,
  which first shipped in core v3.3.1, but that release still reports
  `__version__ = "3.3.0"`, so a 3.3.1 floor would refuse every current core.

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.
- Behaviour change: Upcoming used to show the next games however far away
  they were. It now hides anything past `schedule_lookahead_days` (default 7),
  a favourite's game included, so in preseason or a long break the screen is
  empty until a game is inside the window. Raise the setting to see it sooner.

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
## [1.25.1] - 2026-09-11

### Fixed
- **Placeholder team logos draw their abbreviation at PressStart2P 16, not 12.**
  That face is crisp only at multiples of 8; 12 was anti-aliased, and 16 is the
  nearest crisp size for the 64px logo tile. Panel text was already on-grid via
  `_FONT_PIXEL_GRID` and is unchanged.

## [1.19.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.

## [1.19.2] - 2026-08-31

### Changed
- **The rank badge chooses its ranking block instead of taking ESPN's first.** That endpoint returns several blocks and the first is not promised to be a poll — men's and women's college hockey are fronted by *NCAA Tournament Seedings*, and college lacrosse publishes seedings of its own beside the Inside Lacrosse poll. The poll leads today, so this league was one reordering away from a bracket seed appearing where a viewer expects a poll position. ESPN's order is kept among genuine polls; seedings and lower divisions are stepped over. Ported from the same fix in `hockey-scoreboard`, where the wrong block was being drawn live, and held by `scripts/test_poll_choice.py`.

## [1.19.1] - 2026-08-30

### Fixed
- **Recent games come back when favourite teams are set.** `SportsRecent.update()` calls `self._favorites_first(...)`, but that helper — and `_other_games_window` and `_is_favorite_game` with it — was defined on `SportsUpcoming`, a sibling class rather than an ancestor, so the call raised `AttributeError`. `update()` catches it, logs `Error updating recent games` and carries on with an empty list, so the recent screen simply showed nothing. It only bites when favourite teams are configured without `show_favorite_teams_only`, which is the ordinary way to use the setting.
- `football-scoreboard` already had all three on `SportsCore` and was unaffected; this brings the rest into line. Every safety-harness render is byte-identical — this plugin's fixture sets no favourites, so the broken path was never reached there.

## [1.19.0] - 2026-08-29

### Changed
- **The score is now the headline it was always meant to be.** It was the only element on the card not sized from the panel, and it was not even bigger than its neighbours: PressStart2P renders crisply on an 8px grid, so the 10px default snapped to 8 — the same 8 the clock above it and the game date below it are drawn at. It is now sized from `display_height`, snapped to its face's pixel grid and capped at twice its design size, with the clock/date face held a grid step below it.
- **A narrower face instead of smaller logos.** Where the grown score would swamp the panel the layout reaches for a narrower *face*, which is what `football-scoreboard` has always done via `_fit_score_font` and the single reason its logos read larger than every other scoreboard's at the same panel size. Measured on 128x64: `4x6-font` at 14px reserves 28px and leaves 52x52 logos, where `PressStart2P` at 16px reserved 60px and left 36x36. The two faces are not the same shape — PressStart2P is square, 4x6-font is nearly as tall and about half as wide — so the score keeps the dimension that carries legibility and gives back the one the logos need.
- **Logos are sized against the space the score actually needs**, and only where the score grew. A panel whose score did not move keeps exactly the logos it had.
- **Score and date positions scale with their faces.** The bottom-anchored score's `-14`, the centred score's `-3`, and the date's 7px drop were all chosen for an 8px face and clipped a grown one off the card.
- **The upcoming screen is untouched at every size.** It draws no score — `fonts["score"]` appears in `SportsUpcoming` zero times, `fonts["time"]` five times — so none of the score-driven sizing applies to it and its date and time keep the face and size they always had. Measured on the live and recent screens: 64x32, 128x32 and 256x32 are byte-identical to the previous release; every taller panel gains a larger score with logos the score is no longer drawn across.

## [1.7.0] - 2026-08-04

### Changed
- **Scroll display now runs on the core's shared implementation.** Orchestration — scroll-helper configuration, frame pumping, completion, settings resolution, native `global_config['target_fps']` — moves to the core's `src.common.sports_scroll` (LEDMatrix 3.2.0). Only the sport-specific content half stays here.
- **Nothing changes on an older core.** The import is guarded: a core without that module falls back to `scroll_display_legacy.py` and the plugin behaves exactly as before. The minimum core version is unchanged at 2.0.0 — the plugin does not *require* 3.2.0, it prefers it.
- Verified byte-for-byte: all 16 safety-harness renders (8 panel sizes × 2 screens) are identical to 1.6.0.

## [1.6.0] - 2026-07-29

### Fixed
- Explain an empty screen instead of leaving the user guessing. A favorite team code that is not a real ESPN abbreviation matched no game and showed nothing, and so did a correct code before its season started - the two were indistinguishable from the logs. The plugin now says which it is, suggests the right code for a near miss (GBP -> GB), and reports when the league's next games are. The check runs in the background, once per league, and cannot affect what is displayed.

# Lacrosse Scoreboard — Changelog

## 1.5.1 (2026-07-30)

### Fixed
- **The core's own `"UTC"` default no longer masks a missing global setting**: `ConfigManager.get_timezone()` is `self.config.get('timezone', 'UTC')`, so it returns `"UTC"` for a config with no `timezone` key at all. 1.5.0 took that at face value and therefore never reached the host system zone. Resolution now reads the raw config dict and treats an absent key as absent, falling through to the system timezone as designed. A plugin-level `"UTC"` set by you is still honored verbatim — this plugin never wrote one back into your config.

## 1.5.0 (2026-07-29)

### Fixed
- **Game start times shown in UTC**: The plugin read the LEDMatrix global timezone only from `cache_manager.config_manager`. On cores that hang `config_manager` off the plugin manager instead, that lookup came back empty and every start time was rendered in UTC, while plugins that check the plugin manager first (clock-simple, geochron) showed the correct local time on the same device. Timezone resolution now lives in `lacrosse_timezone.py` and tries, in order: the plugin's own `timezone` setting, `plugin_manager.config_manager`, `cache_manager.config_manager`, the host system zone (`TZ`, `/etc/timezone`, `/etc/localtime`), and only then UTC.
- **`timezone` setting was not in the config schema**, so it never appeared in the web UI. It is now a documented string property under Advanced Settings.

### Added
- `timezone` (Advanced Settings): optional IANA zone override, e.g. `America/Chicago`. Blank (the default) follows the LEDMatrix global timezone.

## 1.1.0 (2026-04-07)

### Breaking change — display modes renamed with `lax_` prefix

The six display modes this plugin exposes previously collided with
the NCAA hockey modes shipped by `hockey-scoreboard`. LEDMatrix's
display controller keys modes in a flat dict
(`src/display_controller.py`), so installing both plugins at the
same time meant whichever loaded second silently overrode the
first one's NCAA modes.

All lacrosse modes now carry a `lax_` prefix. The six renames:

| Old                     | New                         |
|-------------------------|-----------------------------|
| `ncaa_mens_recent`      | `lax_ncaa_mens_recent`      |
| `ncaa_mens_upcoming`    | `lax_ncaa_mens_upcoming`    |
| `ncaa_mens_live`        | `lax_ncaa_mens_live`        |
| `ncaa_womens_recent`    | `lax_ncaa_womens_recent`    |
| `ncaa_womens_upcoming`  | `lax_ncaa_womens_upcoming`  |
| `ncaa_womens_live`      | `lax_ncaa_womens_live`      |

### Migration required

If you referenced any of the old names anywhere in `config.json`,
update them to the new prefixed names. Common places:

- `display_durations` overrides keyed by mode name
- `rotation_order` entries listing which modes to cycle through
- Any custom scripting or automation that pokes the REST API with
  these mode names

There is no backward-compat alias — the old names are no longer
recognized by the plugin dispatch logic.

### Why now

The collision with `hockey-scoreboard` was a silent data loss bug:
whichever plugin loaded second won, without any warning in the
logs. Renaming with a plugin-specific prefix is the only durable
fix until the display controller grows proper namespacing. The
`lax_` prefix was chosen to be short and consistent with how other
prefix-disambiguated codebases handle the same problem.

## 1.0.3 (2026-04-06)

Schema-conformance manifest cleanup.

## 1.0.2 (2026-04-06)

Initial monorepo release.
