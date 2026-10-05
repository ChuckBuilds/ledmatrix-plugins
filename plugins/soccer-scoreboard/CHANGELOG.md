# Changelog

## [2.42.0] - 2026-10-05

### Changed
- Requires LEDMatrix core 3.8.2 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/sports_favorites.py`. The store refuses to install or update
  this version onto an older core.
- Uses core's favourite matching: `SportsCore` inherits
  `SportsFavoritesMixin`, `SportsUpcoming` `SportsUpcomingFavoritesMixin` and
  `SportsRecent` `SportsRecentFavoritesMixin` (`src.common.sports_favorites`).

### Removed
- This plugin's copies of core's favourite matching:
  `SportsCore._is_favorite_game` and `_favorite_code`,
  `SportsUpcoming._select_games_for_display` and
  `SportsRecent._select_recent_games_for_display`.

No change in behaviour: every favourite-matching answer and every
safety-harness render is identical.

## [2.41.2] - 2026-10-05

### Fixed
- A favourite team entered in lower case or with spaces around it ("bos", "
  BOS ") now counts as a favourite on the Upcoming and Recent screens,
  favourites-only included, and gets the live favourite boost and dwell. The
  live screen's favourites-only filter still compares the exact abbreviation.
- Two games without an ESPN id are no longer taken for the same game, so
  favourites-only selection keeps both.
- `_is_favorite_game`, `_select_games_for_display` and
  `_select_recent_games_for_display` are now one body in all nine scoreboards.
  Each side of a game is named by `_favorite_key` and compared with
  `favorite_teams` stripped and upper-cased.

## [2.41.1] - 2026-10-05

### Fixed
- A board showing only its favourites' live matches no longer wakes for other
  teams' matches. The live loop handed every match on the scoreboard to core's
  idle back-off as a start to wake for, and each one holds the poll at the
  live update interval for 15 minutes, so on a busy slate the board fetched
  the whole scoreboard about every 30 s for matches it then filtered out. Only
  matches the live filter would show are offered now (football-scoreboard
  3.18.7 made the same change). Excluded teams' matches are never offered.
  Boards showing every live match are unchanged.
  `test_kickoff_offer_follows_the_live_filter.py` covers the filter.

## [2.41.0] - 2026-10-05

### Changed
- Schedule windows are cached under core's shared ESPN scoreboard key
  (espn_scoreboard_cache_key, fetch service stage 2), so every plugin showing
  a league shares one fetch and one cached copy. The key this plugin used
  before is still read, so an upgrade serves the copy already on disk instead
  of refetching every league at once; a window that moves on a day deletes its
  copy from the day before. Requires LEDMatrix core 3.8.1.
- The live poll's 30-second cache moves from `<sport_key>_scoreboard_current`,
  whatever the dates, to the shared key for the dates it asks, so odds-ticker
  and the scoreboard read each other's copy; the old key is read for a
  release.
- 2.39.3's single fetch per cache miss and its per-window lock are unchanged;
  the lock is now taken on the shared key.

## [2.40.0] - 2026-10-05

### Changed
- Requires LEDMatrix core 3.8.1 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/sports_game_over.py`. The store refuses to install or update
  this version onto an older core.
- `SportsLive` inherits `SportsGameOverMixin` (`src.common.sports_game_over`)
  and keeps declaring `FINAL_PERIOD` (None).

### Removed
- `SportsLive._is_game_really_over`, this plugin's copy of core's game-over
  check.

No change in behaviour: every game-over answer and every safety-harness
render is identical.

## [2.39.5] - 2026-10-05

### Changed
- No change in behaviour. `SportsLive._is_game_really_over` is now one body in
  all nine scoreboards; each declares `FINAL_PERIOD`, the period from which a
  0:00 clock ends a game (None: the clock never does). Here it is None: the
  clock counts up.

## [2.39.4] - 2026-10-04

### Fixed
- A per-league mode in switch mode (`soccer_esp.1_recent`,
  `soccer_usa.1_upcoming`, ...) showed another league's game: `display()`
  parsed the league out of the mode name and then tried every enabled
  league's manager for that mode type, drawing the first with games -- so
  La Liga's slot showed the Premier League card. Only the named league is
  consulted now; when it has nothing to show the mode returns `False` and the
  core's empty-mode handling moves on.

## [2.39.3] - 2026-10-03

### Fixed
- A start or reload no longer floods ESPN. With eight leagues, every start
  logged ~90 `NameResolutionError`s for site.api.espn.com within a minute
  (plus `update() timed out`), and six hours made 3,812 requests. On a cache
  miss `_fetch_soccer_api_data` submitted the league's schedule window to the
  core's background service *and* fetched the same window on the spot as
  stand-in data (`_get_weeks_data`), in both the recent and the upcoming
  manager -- and ESPN's rejection of date ranges makes each window 29 day
  requests. A miss now fetches the window once on the calling thread
  (`_fetch_season_directly`, which caches it), under a lock per cache key so
  the league's other manager waits and reads the cache.
- Every manager shares the core's connection pool (`share_connection_pool`,
  on cores that have the fetch service) instead of opening its own, so a
  connection -- and its DNS lookup -- is reused across leagues.

## [2.39.2] - 2026-10-02

### Fixed
- A custom league whose `game_limits` were never opened in the web UI
  (the row editor sends them back blank) showed 5 recent games, not the `1`
  its settings page displays: `_adapt_config_for_custom_league` now falls
  back to the schema default.
- `custom_leagues[].filtering.show_all_live` defaults to `false` in the
  schema, matching the built-in leagues and what the plugin already did when
  the value was absent; the settings page showed it on while it was off.

### Documentation
- README: documents `<league>.odds_update_interval` (`3600` s),
  `<league>.live_odds_update_interval` (`60` s) and the full-screen
  `scroll_card.switch_show_date` / `switch_show_time` switches.

## [2.39.1] - 2026-10-01

### Changed
- Uses `src/common/sports_plugin_host.py`, `src/common/sports_live_scroll.py`, `src/common/sports_display_rules.py` and `src/common/sports_font_path.py`,
  which LEDMatrix core 3.8.0 ships. The core floor is unchanged.

### Removed
- `SoccerScoreboardPlugin`'s Vegas weighting (`get_vegas_priority_weight`,
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

## [2.39.0] - 2026-09-30

### Added
- Live Vegas cards: in the Vegas ticker each game is its own card, and a card already scrolling across the panel updates in place when its game changes -- the score, the clock, FINAL -- instead of showing what it was when it was drawn. Only the card whose game changed is redrawn. A game that goes final keeps its card, now showing FINAL, until the recent list picks it up. Nothing changes outside Vegas, and get_vegas_content() is unchanged for older cores and multi-display sync.

### Changed
- Requires LEDMatrix core 3.8.0 (`ledmatrix_min_version` and `compatible_versions`), the first release with live Vegas elements (`src.common.sports_vegas`). The store refuses to install or update this version onto an older core.

## [2.38.0] - 2026-09-29

### Changed
- Requires LEDMatrix core 3.7.0 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/sports_fetch.py`, `src/common/sports_celebration.py` and `src/common/sports_card_wrappers.py`. The store refuses to
  install or update this version onto an older core.

### Removed
- The score/win celebration drawing (`_draw_celebration_layout` and the
  palette, backdrop, scenery, confetti and crest steps behind it,
  `_fit_font`) and its colour helpers (`_logo_palette`, `_lift_color`,
  ...): `SportsLive` inherits `SportsCelebrationMixin`
  (`src.common.sports_celebration`). When to celebrate, the phrase and the
  scenery stay in this plugin.
- `SportsCore._fetch_season_directly`, `_background_fetches_espn_ranges`,
  `_needs_previous_day` and `_wants_live_odds`: `SportsCore` inherits
  `SportsFetchMixin` (`src.common.sports_fetch`).
- The `sports_card` delegations in `game_renderer.py`: `GameRenderer`
  inherits `SportsCardWrappersMixin` (`src.common.sports_card_wrappers`).

No behaviour change: the code is the same, and every safety-harness render
and celebration golden is byte-identical.

## [2.37.0] - 2026-09-29

### Changed
- The favourite-team check (the log lines that say why a league shows
  nothing) is now `FavoriteTeamCheck` from core's
  `src.common.favorite_team_check`, the one the other scoreboards use. It
  replaces this plugin's own older version in `manager.py`, which that module
  grew out of. Only the log changes:
  - The check runs on a background thread. The old one ran inside `update()`,
    so the first update of each league with favourites waited on up to two
    ESPN requests.
  - Between matchdays or seasons, correct codes log the date of the next
    fixture ("... look correct, but the league has nothing on until 10
    October 2026 ..."). The old check only spoke when ESPN's scoreboard came
    back empty, which it rarely does (it shows the last matchday until the
    next), so it usually just said "recognised". A finished season with no new
    fixtures published is reported as finished.
  - A wrong code's warning links to the league's ESPN team list instead of
    TEAMS.md. The link works for custom leagues too.
  - Suggestions also match part of a word and put a name's first word first.

  Every league in the registry is checked against its ESPN soccer endpoint
  (`soccer/<league code>`), custom leagues included; only enabled leagues with
  favourites are checked, with the favourites of the first of live / recent /
  upcoming that has any. A config change rebuilds the check for the new league
  list, so it reports again.

- Requires LEDMatrix core 3.6.2 (`ledmatrix_min_version`), whose check no
  longer calls a competition between rounds (e.g. the Europa League) a
  finished season (core #670).

### Removed
- The old check's helpers on the plugin class: `_abbreviates`,
  `_suggest_team_code`, `_fetch_league_teams`, `_fetch_season_start` and the
  `_favorites_checked` set. Nothing else used them.

Every safety-harness render is byte-identical: the check only logs.

## [2.36.0] - 2026-09-29

### Changed
- Requires LEDMatrix core 3.6.1 (`ledmatrix_min_version` and
  `compatible_versions`), the floor the sports scoreboards share; 3.6.0 is the
  first release that ships `src/common/sports_timezone.py`. The store refuses
  to install or update this version onto an older core.
- `soccer_timezone.py` is now a thin binding: `resolve_timezone_name()` and
  `resolve_timezone()` call core's `src.common.sports_timezone` with this
  plugin's label, write-back release and logger, as they already did on a
  3.6.x core.

### Removed
- The fallback resolver in `soccer_timezone.py`, kept for cores without
  `src.common.sports_timezone`.

No behaviour change on a 3.6.x core: the timezone chosen and every log
message are the same, and every safety-harness render is byte-identical.

## [2.35.1] - 2026-09-29

### Changed
- On a core that ships it, the timezone resolver runs core's copy:
  `soccer_timezone.py` resolves through `src.common.sports_timezone` with this
  plugin's values. The core module was promoted from this file, which stays as
  the fallback on older cores (the floor stays 3.5.0).

No behaviour change: the timezone chosen and every log message are identical
on both paths, and every safety-harness render is byte-identical.

## [2.35.0] - 2026-09-28

### Changed
- Requires LEDMatrix core 3.5.0 (`ledmatrix_min_version` and
  `compatible_versions`), the first release that ships
  `src/common/espn_dates.py` and `src/common/sports_helpers.py`. The store
  refuses to install or update this version onto an older core.

### Removed
- `soccer_espn_dates.py`, the bundled copy of core's ESPN date-range helper.
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

## [2.34.1] - 2026-09-28

### Removed
- Deleted the bundled `base_odds_manager.py` fallback. It could never run:
  core has shipped `src.base_odds_manager` since v3.0.0, below this plugin's
  3.4.0 floor, so odds already came from core's `BaseOddsManager`. The
  import is now plain.
- Deleted the unused `MLBAPIDataSource` and `SoccerAPIDataSource`
  data source classes; nothing referenced them.

No behaviour change.

## [2.33.3] - 2026-09-28

### Changed
- Removed code that nothing called. No change in behaviour.

## [2.33.2] - 2026-09-28

### Fixed
- Background Service settings (request timeout, max retries, priority) reach
  the league managers, custom leagues included; they were fixed at 30 s, 3 and
  2 whatever was set. Its Enabled switch, which was never read, is hidden.

## [2.33.1] - 2026-09-28

### Fixed
- Dynamic duration now sizes a slot from its games. get_cycle_duration read
  manager.games, which no soccer manager has, so the per-game total was always
  0; it also summed every enabled league although each display mode is one
  league. It now counts the mode's own league through _get_games_from_manager.

## [2.33.0] - 2026-09-28

### Added
- Declares the five goal-celebration settings on custom leagues
  (celebration_enabled, celebration_duration, celebrate_opponent_goals,
  celebration_team_colors, celebration_confetti), with the built-in leagues'
  defaults. The adapter already read them from a custom league, but the strict
  schema rejected them, so they could only be set by hand and then failed
  validation.

## [2.32.2] - 2026-09-28

### Fixed
- Upcoming games now stay up for the configured per-game time. SportsUpcoming
  set game_display_duration = 15, so every upcoming game got 15 s whatever the
  setting said; it now reads upcoming_game_duration, as football, baseball and
  ufc do. The adapter already forwarded it. Only boards with a non-default
  value change: the default is 15 s, the value the code used.
- The league's 'Enable dynamic duration' switch now works.
  supports_dynamic_duration returned the per-mode switch whenever it was
  present, and the core fills its default (off) into every config, so the
  league switch was never read. The league switch now turns dynamic duration
  on for every mode; a mode switch still turns on just that mode.

## [2.32.1] - 2026-09-28

### Changed
- Hides config controls that do nothing. The root, per-league and custom-
  league update_interval_seconds is never read: every manager replaces it with
  its own live, recent or upcoming interval before anything uses it, and the
  core scheduler reads update_interval, not this key. The root show_ranking is
  hidden too: this league publishes no poll, so the badge was always empty
  and, because it replaces the record, turning it on erased the records Show
  Records draws. The league-level copy was hidden in the previous release;
  this copy still reached the switch view. No behaviour change: the keys stay
  declared, so saved configs still load, and a saved show_ranking keeps its
  value. README updated to match (it already described the root show_ranking
  as hidden).

## [2.32.0] - 2026-09-24

### Changed
- **32 config control(s) that cannot affect anything are no longer drawn.**
  Each stays declared — `"x-display": "hidden"` — so a config already carrying
  it keeps validating and nothing is lost on upgrade; only the form control goes
  away.

  - `other_games_divisions` (×11) — the FBS / FCS / Other checkboxes. ESPN
    publishes those group rosters for **college football and nothing else**
    (`_DIVISION_GROUPS_BY_LEAGUE`), so here the lookup resolves nothing, the
    filter fails open, and no combination of boxes could change one game.
  - `other_games_min_quality` (×11) — "ranked" needs a poll. Without one the
    rank table stays empty and the check fails open, so the setting has
    exactly one meaningful value.
  - `display_options.show_ranking` (×10) — **worse than inert.** The rank
    table is always empty without a poll, and the badge *replaces* the record
    — so ticking it silently erased the records `show_records` was drawing.

### Fixed
- **The rankings fetch ran on leagues that publish no poll.**
  `_league_has_rankings` gated the quality-filter call site but not the
  `show_ranking` ones, so ticking Show Ranking on every league it serves sent
  two requests an hour to endpoints that cannot answer. The gate moved to the
  top of `_fetch_team_rankings`, where it covers every caller and cannot drift
  apart again.

  Which leagues have a poll is **measured, not assumed** — ESPN's `/rankings`
  was probed for every scoreboard league on 2026-09-24. college-football (125
  teams), men's and women's college basketball (50 each), college hockey (4/5)
  and college lacrosse (28/33) answer 200 with real poll blocks; every
  professional league answers 404, and so does college baseball.

## [2.31.0] - 2026-09-20

### Added
- **The goal and win celebration is drawn in the scoring team's colours.**
  Read from the team's own logo rather than from a colour table, so it covers
  every team the feed names. The screen picks two colours out of the crest:
  its largest area becomes a dark gradient behind everything, and its most
  legible saturated colour becomes the banner, the glowing score digits and
  the confetti. A sunburst sits behind a winner; a goal gets diagonal
  team-colour stripes.
- **Team-coloured confetti**, seeded from the game so the same goal always
  falls the same way.
- Two advanced settings, both `true` by default: `celebration_team_colors`
  and `celebration_confetti`.

### Fixed
- **The celebration's animation now actually animates.** The old screen
  flashed its background at 2.5 Hz and toggled the score highlight between two
  colours at 4 Hz. Unless a league is in `scroll` mode the core redraws this
  plugin once a second (its high-FPS loop is reserved for plugins that scroll
  or declare `needs_high_fps`), so both effects were sampled far below their
  rate and aliased into a colour that changed at random. The score now glows
  on a continuous ramp, and every frame across the window is a finished card.
- **The banner is no longer clipped in the opening frame.** It slid down into
  place from `y=-3`, so a board sampling once a second could catch its only
  frame with the top row of the text cut off. It fades from white into the
  team colour instead, which cannot clip.
- **The score no longer runs off the bottom of a tall panel.** Ported from
  football-scoreboard 3.9.2 (#338), which scaled the score font with the panel
  and then lifted it by the measured ink when it would clip; this lineage's
  copy of the celebration still placed it at a fixed offset sized for the old
  8px face.
- **The plugin asks the core for its high-FPS loop while a celebration is on
  screen** (`needs_high_fps`), so a goal that arrives while another plugin is
  showing gets a smooth celebration rather than a stepped one. Scrolling
  boards behave exactly as before.

## [2.30.1] - 2026-09-17

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

## [2.30.0] - 2026-09-16

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

### Fixed
- **Flags and club crests that share an abbreviation no longer swap.** One logo
  cache serves every league's cards, keyed by abbreviation and slot size, so in
  a scroll or Vegas strip carrying the World Cup and a club league ESP, POR and
  COL drew whichever logo loaded first (Spain as Espanyol's crest). The key now
  includes the logo's directory, as football does since #472.
- **Scroll mode no longer freezes while a fetch runs.** The per-frame live
  refresh ran `manager.update()` on the render thread, so when a fetch was due
  the marquee stalled for the whole ESPN request. It is handed to a worker
  thread (one per manager at a time, at least 5s apart; the manager's own
  interval still decides whether anything is fetched).

## [2.29.4] - 2026-09-16

### Fixed
- **Scores and schedules load again after ESPN stopped accepting date
  ranges.** Since 2026-09-15 ESPN answers `dates=YYYYMMDD-YYYYMMDD` scoreboard
  queries with `400 Bad Request` for every sport. Today's games, the
  lookback/lookahead window and the season schedule are all ranges, so the
  soccer boards logged `400 Client Error` and showed nothing. A rejected
  range is now fetched by `fetch_espn_scoreboard` (`soccer_espn_dates.py`, a
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

## [2.29.3] - 2026-09-15

### Documentation
- **The README lists the display modes the plugin actually registers.** It
  still described three generic modes (`soccer_live`, `soccer_recent`,
  `soccer_upcoming`) that the plugin no longer registers; the manifest has
  declared the 30 league-qualified modes since #466. The generic names
  are noted as unselectable: `display()` still has a branch for them, but the
  host only dispatches registered modes.

## [2.29.2] - 2026-09-14

### Fixed
- **Hardening: the live "looks finished" check no longer raises on a None or
  non-string period text.** `game.get("period_text", "").lower()` only
  defaults a missing key, so a `None` value raised, and `SportsLive.update()`
  does not catch it. The soccer parser never produces one today. Such values
  are now treated as empty / period 0; the end-of-game rule is unchanged.

## [2.29.1] - 2026-09-14

### Fixed
- **Plugin-level copies of league settings now apply.** Eighteen settings are
  declared both at the plugin root and in every league block
  (`show_records`/`show_ranking`/`show_odds`, the update intervals,
  `live_game_duration`, the game limits, the other-games selection and
  `show_favorite_teams_only`), and changing the root copy did nothing. A root
  value you changed now applies to every league whose own value is still at its
  default; a league value you changed still wins. Each copy is compared with
  its own default, so `live_game_duration`'s root default of 30 does not
  override the leagues' 20.
- **Disabling a league at runtime takes effect immediately.** Its managers were
  left in place, and turning off the last enabled league fell back to the
  default Premier League modes, which kept drawing them until a restart.

## [2.29.0] - 2026-09-14

Drift-audit fixes ported from the sibling scoreboards.

### Fixed
- **Celebration settings now work.** `celebration_enabled`,
  `celebration_duration` and `celebrate_opponent_goals` were declared in every
  league block but never forwarded to the managers, so celebrations were always
  on and always 8s. `test_mode` is forwarded too.
- **One failing league no longer blanks the rest.** Each league is built in its
  own try; a failed league's managers are `None`.
- **`other_games_divisions`** is passed through raw. A hand-edited `"fbs"` used
  to become `['f','b','s']` and reject every non-favourite game; `null` raised
  inside the translation.
- **Postponed, cancelled and abandoned fixtures** no longer show as
  "Final 0-0" on Recent. A final must be completed and actually played; these
  are labelled PPD/CANC/SUSP/ABD instead.
- **Full-screen odds** with only an over/under are anchored left instead of
  centred through the league header, "Final" or the live clock, and step down a
  row if they would still collide. A home spread of 0.0 is kept as a real line.
- **Full-screen upcoming scorebug** reads `scroll_card.switch_show_date` /
  `switch_show_time`, so hiding the date or time on the scroll card no longer
  blanks it here.
- **Upcoming** enforces `schedule_lookahead_days` in selection, and a mode
  retaking the panel gives its current card a full dwell.
- **Rotated-in other games** get odds without waiting for the hourly update.
- **"Logo Error"** is drawn on the image that is shown, instead of a black panel.
- **Decoded logo caches are bounded** (LRU), per manager and for the shared
  scroll cache.
- **Scroll card, rankings and records both on:** an unranked team shows its
  record instead of nothing.
- **Vegas** rebuilds its cards when the game data changes, not only when its
  cache is empty, and no longer takes over the standalone scroll display.
- A cached "no odds" marker is a cache hit, not a refetch on every call.
- A config `Infinity` can no longer crash manager construction.

### Added
- `odds_update_interval` and `live_odds_update_interval` (advanced), per league
  and per custom league.
- `scroll_card.switch_show_date` / `switch_show_time`.

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.
- The per-league `scroll_settings` block is retired. Nothing ever read it; it
  stays accepted so saved configs still validate.
- The core floor stays at 3.3.0. `sports.py` imports `src.common.sports_shared`,
  which first shipped in core v3.3.1, but that release still reports
  `__version__ = "3.3.0"`, so a 3.3.1 floor would refuse every current core.

### Fixed
- **Favorite game turns shows up in the web UI.** Also lists the root-level favorite_rotation_boost in x-propertyOrder: the previous release declared it but left it out of the order, so the web UI's config form never rendered the field (caught by scripts/test_property_order_coverage.py).

## [2.28.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [2.27.1] - 2026-09-14

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

## [2.27.0] - 2026-09-11

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

## [2.26.1] - 2026-09-11

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

## [2.26.0] - 2026-09-10

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
## [2.19.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.

## [2.19.2] - 2026-08-31

### Changed
- **`sports.py` chooses its ranking block instead of taking ESPN's first.** Hardening only, with no behaviour change here: soccer publishes no poll, so the rank badge reads nothing either way. The shared file is kept in step with the lineages where the first block is *NCAA Tournament Seedings* (college hockey) or a lower-division poll (college football), rather than left to diverge.

## [2.19.1] - 2026-08-30

### Fixed
- **Recent games come back when favourite teams are set.** `SportsRecent.update()` calls `self._favorites_first(...)`, but that helper — and `_other_games_window` and `_is_favorite_game` with it — was defined on `SportsUpcoming`, a sibling class rather than an ancestor, so the call raised `AttributeError`. `update()` catches it, logs `Error updating recent games` and carries on with an empty list, so the recent screen simply showed nothing. It only bites when favourite teams are configured without `show_favorite_teams_only`, which is the ordinary way to use the setting.
- `football-scoreboard` already had all three on `SportsCore` and was unaffected; this brings the rest into line. Every safety-harness render is byte-identical — this plugin's fixture sets no favourites, so the broken path was never reached there.

## [2.19.0] - 2026-08-29

### Changed
- **The score is now the headline it was always meant to be.** It was the only element on the card not sized from the panel, and it was not even bigger than its neighbours: PressStart2P renders crisply on an 8px grid, so the 10px default snapped to 8 — the same 8 the clock above it and the game date below it are drawn at. It is now sized from `display_height`, snapped to its face's pixel grid and capped at twice its design size, with the clock/date face held a grid step below it.
- **A narrower face instead of smaller logos.** Where the grown score would swamp the panel the layout reaches for a narrower *face*, which is what `football-scoreboard` has always done via `_fit_score_font` and the single reason its logos read larger than every other scoreboard's at the same panel size. Measured on 128x64: `4x6-font` at 14px reserves 28px and leaves 52x52 logos, where `PressStart2P` at 16px reserved 60px and left 36x36. The two faces are not the same shape — PressStart2P is square, 4x6-font is nearly as tall and about half as wide — so the score keeps the dimension that carries legibility and gives back the one the logos need.
- **Logos are sized against the space the score actually needs**, and only where the score grew. A panel whose score did not move keeps exactly the logos it had.
- **Score and date positions scale with their faces.** The bottom-anchored score's `-14`, the centred score's `-3`, and the date's 7px drop were all chosen for an 8px face and clipped a grown one off the card.
- **The upcoming screen is untouched at every size.** It draws no score — `fonts["score"]` appears in `SportsUpcoming` zero times, `fonts["time"]` five times — so none of the score-driven sizing applies to it and its date and time keep the face and size they always had. Measured on the live and recent screens: 64x32, 128x32 and 256x32 are byte-identical to the previous release; every taller panel gains a larger score with logos the score is no longer drawn across.

## [2.6.0] - 2026-08-04

### Changed
- **Scroll display now runs on the core's shared implementation.** The orchestration half of `scroll_display.py` — scroll-helper configuration, frame pumping, completion, settings resolution, and native `global_config['target_fps']` support — moves to the core's `src.common.sports_scroll` (LEDMatrix 3.2.0). Only the soccer-specific content half stays here: game cards and league separator icons.
- **Nothing changes on an older core.** The import is guarded: a core without `src.common.sports_scroll` falls back to `scroll_display_legacy.py` and the plugin behaves exactly as it did. The minimum core version is unchanged at 2.0.0 — the plugin does not *require* 3.2.0, it merely prefers it.
- This lineage's scroll settings are preserved explicitly, since they differ from the shared defaults: a 24px gap rather than 48, `min_duration`/`max_duration` bounds of 30/300 (core's own default max is 600), and game cards pinned at 128px where core sizes them to the panel.
- Three unused methods (`_get_scroll_speed`, `get_scroll_duration`, `has_content`) are not carried over — nothing called them. A redundant `set_scroll_speed()` call is also gone: the previous code set it twice, once in px/s and again in px/frame, and only the second took effect.
- Verified byte-for-byte: all 24 safety-harness renders (8 panel sizes × 3 screens) are identical to 2.5.2.

## [2.5.0] - 2026-07-29

### Fixed
- **TEAMS.md listed wrong team codes**: the documented abbreviations had drifted
  from ESPN's, so following the docs produced a silently empty display. Manchester
  United was listed as `MUN` (ESPN uses `MAN`), Manchester City as `MCI` (`MNC`),
  Real Madrid as `RM` (`RMA`), and Ligue 1 had eight wrong codes including Lyon
  and Marseille. Several rosters were also a season out of date. Every table is
  now generated from ESPN's live team endpoints and verified against them.

### Added
- **A reason when a league shows nothing.** An empty screen had two very
  different causes that looked identical in the logs. Now, once per league:
  an unrecognised favorite team logs a warning naming the closest match
  (`favorite team 'MUN' is not a Premier League team code. Closest match is
  'MAN' (Manchester United).`), while codes that are correct but have no
  fixtures yet log the date the season starts, stating that an empty display
  until then is expected rather than a misconfiguration.
- **Cross-league code clashes documented.** Favourites match by abbreviation
  across every enabled league, and `MUN` is Bayern Munich in the Bundesliga —
  so the old docs could have matched the wrong club entirely. TEAMS.md now
  lists the codes that mean different clubs in different leagues.

