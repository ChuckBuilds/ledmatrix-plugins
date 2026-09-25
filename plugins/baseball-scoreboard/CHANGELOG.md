# Changelog

## [1.50.0] - 2026-09-25

### Added
- **Game Activity — a running pitch-by-pitch commentary line for live games**,
  for the innings where the score gives the board nothing to say. A 1-0
  pitchers' duel leaves the scoreboard static for twenty minutes at a time;
  the count is the only thing moving, and ESPN has plenty to say about it.

  What it says, in three classes you can mute independently:

  | | example |
  |---|---|
  | pitches | `J. Walker Foul 0-1` |
  | at-bat outcomes | `Burleson homered to right center (395 feet).` |
  | baserunning | `Cruz stole third.` |

  Outcomes and baserunning are ESPN's own sentences, which already name the
  player. Only pitches are phrased here, because ESPN does not write prose for
  them.

  **Where it goes** — `game_activity.position`:
  - **inline** draws it along the bottom of the live scoreboard, in the gap
    between the two corner scores that share that row;
  - **screen** gives it its own card in the rotation;
  - **auto** (default) measures the panel — every 64px-tall board gets the
    inline line, every 32px one takes the screen.

  The choice is made per **panel**, not per line. Deciding per line would flip
  a 128px board between inline and its own screen from one pitch to the next —
  a mode change every few seconds, which reads as a fault. An explicit
  `inline` with no room draws nothing rather than printing over the count.

  **How much it says** — `game_activity.detail`: `terse` (`Foul`), `normal`
  (`J. Walker Foul 0-1`), or `rich`, which adds the pitch on a second line
  (`97 mph Four-seam FB`).

  **Cadence.** The scheduler polls at `live_update_interval` and the summary
  refresh is gated by `play_by_play_update_interval` — roughly 30s, while a
  pitch takes about 25s. So a poll returns *several* new plays at once.
  Showing only the newest would waste them and leave the board static between
  fetches, which is the opposite of the point; instead they are queued and
  walked through locally at `dwell_seconds` (4 by default). A slow inning
  reads as running commentary without asking ESPN for anything more — which
  matters, since the odds manager already accounts for the bulk of this
  plugin's ESPN traffic.

  Off by default, and **not offered for MiLB**: that league comes from the MLB
  Stats API and has no ESPN summary endpoint. `BaseballLive` already guards on
  `espn_summary_sport_league`, so it is inert there rather than broken.

### Fixed
Both found by reading real ESPN responses rather than assuming the shape:

- **Baserunning would have stuttered.** ESPN files a steal twice — once typed
  (`stolen-base`, "Cruz stole third.") and again as a `play-result` carrying
  the identical sentence. On a board showing one line at a time that reads as
  a repeat, so a play-result matching the entry before it is dropped.
- **The count could show a plate appearance that had already ended.** ESPN
  keeps counting past it, so a called third strike reports `strikes: 3` and a
  walk `balls: 4`. "1-3" is not a count any scoreboard has ever shown; the
  count is now blank on the pitch that ended the at-bat, where the outcome
  line says what happened anyway.

## [1.49.0] - 2026-09-24

### Added
- **The date of a finished game, on both Recent displays.** The full-screen
  (switch) Recent scoreboard has drawn one along its bottom edge since it was
  written; the scroll and Vegas Recent card never has. Five of the eight
  sibling scoreboards (afl, basketball, football, nrl, soccer) already draw one
  on that card and baseball did not, so this closes a drift gap rather than
  inventing a feature — though baseball cannot copy their placement, because
  they centre the recent score vertically and leave the bottom edge free while
  this card puts the score at `display_height - 14`. Here the free strip is
  *above* the score. Baseball is now the only lineage where this date is both
  formatted and optional; the other five draw it raw and unconditionally, the
  same two problems fixed below for the full-screen screen.
  - `scroll_card.recent_show_date` (default **false**) draws it on the scroll
    and Vegas card, written in the `date_format` already chosen there.
  - `scroll_card.recent_date_position` picks where. That card's bottom edge is
    already the score, so the date needs somewhere else to go: **own row** in
    the clear strip between the FINAL line and the score, or **top line** in
    place of FINAL — no loss on a card that is already showing a final score,
    and the only option that fits a short panel. **Auto** (the default)
    measures the fonts and panel in use rather than assuming a size, so it
    takes its own row where one fits and the top line where it does not. An
    explicit "own row" on a panel with no room draws nothing rather than
    overprinting the score.
  - `scroll_card.switch_recent_show_date` (default **true**) is the off switch
    the full-screen date never had.
- **`milb.sport_ids`** — which levels of the minors to fetch (Triple-A,
  Double-A, High-A, Single-A). `BaseMiLBManager` has read
  `mode_config["sport_ids"]` since it was written, but `_adapt_config_for_manager`
  is a whitelist and never carried the key, so no value a user could write ever
  arrived — which is also why the schema had never declared it. Now forwarded,
  declared, and coerced: an unset key, every box cleared, or an unusable value
  falls back to all four levels, since a MiLB board with no levels selected
  fetches nothing and reads as broken.

### Fixed
- **The full-screen Recent date ignored every date-format setting.** It drew
  `game_date` raw — the `9/23` the extractor emits — so a panel configured for
  "Sep 19" read "Sep 19" on its upcoming screen and "9/23" here. It now goes
  through `switch_date_format`, the same key the full-screen upcoming screen
  uses. Nothing changes on an untouched panel: that key defaults to `numeric`,
  and numeric returns the raw text.
- **The rankings fetch ran on leagues that have no poll.**
  `_league_has_rankings` gated the quality-filter call site but not the two
  `show_ranking` ones, so ticking it on MLB or MiLB sent two requests an hour
  to endpoints that cannot carry a poll. The gate moved to the top of
  `_fetch_team_rankings`, where it covers every caller and cannot drift apart
  again. (A previous fix had already cut this from ~450 requests a day to 24 by
  caching the empty result; this takes it to zero.)
- **NCAA Baseball fetched standings hourly by default, for a poll that 404s.**
  Its `other_games_min_quality` defaulted to `ranked`, which the shared
  `"college" in league` heuristic treats as fetchable — but college baseball is
  the one college league with no `/rankings` endpoint. The filter failed open,
  so it was not even filtering. The default is now `any`, which is what every
  board was already showing, and `_league_has_rankings` is narrowed by one
  measured exception (`_NO_POLL_COLLEGE_LEAGUES`) so a config saved with the
  old default stops requesting too. Reversible: if ESPN publishes one, drop the
  league from that set.

### Changed
- **Five settings that cannot do anything here are no longer drawn.** Each
  stays declared — `"x-display": "hidden"` — so a config that already carries
  it keeps validating and nothing is lost on upgrade.
  - `<league>.game_limits.other_games_divisions` (FBS / FCS / Other), under
    **all three** leagues. ESPN publishes division rosters for
    `college-football` alone (`_DIVISION_GROUPS_BY_LEAGUE`), so every baseball
    league resolves nothing, the filter fails open, and no combination of boxes
    could change one game on the board.
  - `<league>.game_limits.other_games_min_quality` — "ranked" needs a poll, and
    **no baseball league has one**, so it lets everything through and the
    setting has exactly one meaningful value. NCAA Baseball included: measured
    2026-09-24, `baseball/college-baseball/rankings` answers **404** while
    `/scoreboard` and `/standings` on the same slug answer 200, so the slug is
    right and the endpoint is simply absent. Out of season is not the
    explanation — men's college lacrosse and hockey are equally out of season
    and both answer 200 with real poll blocks.
  - `<league>.display_options.show_ranking` — worse than inert. The rank table
    is always empty, and a rank badge *replaces* the record outright, so
    ticking it silently erased the records `show_records` was drawing.
  - `<league>.scroll_settings.scroll_delay` — its own description has read
    "Kept so saved configs still load; ignored" for releases; it was still an
    editable number. `scroll_speed` is the only pacing control.
  - `customization.layout.ranking` — no reader anywhere. The rank badge shares
    the records row and is positioned by `customization.layout.record`, whose
    description now says so.

## [1.48.1] - 2026-09-23

### Fixed
- **`update()` now returns inside the slot the core gives it**, instead of
  being killed and logged as an error on every cold-cache start. At startup
  the display controller hands each plugin whatever is left of a shared
  deadline, so the slot shrinks as it works down the list — measured on a
  256×64 rig, baseball's slot was 15.4s and 15.96s on two consecutive boots.
  This plugin waited **25s** on its six parallel managers, a wait it could
  never finish inside that slot, so the core cut the call and logged
  `Plugin baseball-scoreboard update() timed out` at ERROR — and this
  plugin's own timeout branch, the one that names *which* managers are slow,
  never ran. The wait is now 10s, in a named constant documented against the
  core's budget.

  Nothing was lost before and nothing is lost now: `shutdown(cancel_futures=True)`
  only cancels managers that have not started, and all six start immediately,
  so in-flight fetches run to completion and populate their caches either
  way. A plugin cut off at startup is also immediately due again. The
  difference is that returning under its own steam turns a core-level ERROR
  into a plugin WARNING that names the slow managers.

  The expensive part of a cold start is the NCAA baseball season fetch —
  5,500 events, ~10s — which the background service already runs off-thread.

## [1.48.0] - 2026-09-24

### Changed
- **The Now Batting / Now Pitching card is on by default** for MLB and NCAA
  Baseball (`display_options.show_pitcher_batter` now defaults to `true`).
  MiLB is unaffected -- it has no ESPN play-by-play. A board whose saved
  config already has `show_pitcher_batter: false` keeps it off.
- **Each card stays up for 4 seconds.** `customization.at_bat_info.dwell_seconds`
  used to be split between the batter and the pitcher, so with both on each
  card flashed for only 2 seconds. It is now per card: the batter gets its 4
  seconds, then the pitcher gets 4 of its own.
- **The cards come round every 30 seconds** (`interval_seconds`, was 25). That
  matches the default `live_game_duration`, so each live game gets one pass
  of the cards (8 seconds) and then 22 seconds of scoreboard.
- **The main settings are in the web UI form** rather than hidden under
  Advanced: *Show Now Batting / Now Pitching* under Display Options, and
  *Style*, *Show Batter Card*, *Show Pitcher Card*, *Seconds Per Card*,
  *Show Every (Seconds)* and *Favorite Teams Only* under Customization >
  Pitcher / Batter Player Card. Fonts and colours stay under Advanced.

## [1.47.0] - 2026-09-22

### Added
- **The Now Batting / Now Pitching screen is a baseball card.** It used to be
  two lines of text -- `Pitcher: G. Cole` over `Batter: J. Soto` -- which is
  all the play-by-play feed gives you. It now draws one player at a time as a
  card: their ESPN headshot framed in the team colour, a `NOW BATTING` /
  `NOW PITCHING` banner knocked out of a team-colour bar, the player's name,
  their team, number and position, this season's stats, age and bat/throw
  hand, hometown, and height/weight/seasons played. With both players enabled
  the screen's dwell is split between them, batter first, so one rotation
  shows both cards instead of making the pitcher wait for the screen to come
  round again.
- **New options under `customization.at_bat_info`:** `style`
  (`card`, the default, or `text` for the original layout), `show_batter`,
  `show_pitcher`, `show_headshot`, `show_stats`, `show_bio_details`,
  `header_bar`, and the `text_color` / `stat_color` / `detail_color` pickers
  the card's rows use.
- **A player's age, hometown, height/weight, seasons played, draft, college
  and team** are now parsed from the ESPN athlete record, alongside
  bats/throws recovered from the combined `Right/Left` display string ESPN
  fills in far more often than the structured fields the parser was reading.

### Changed
- **Season stats come from ESPN's own per-position season summary**
  (`AVG`/`HR`/`RBI`/`OPS` for a hitter, `ERA`/`K`/`WHIP`/`SV` for a pitcher),
  already ordered for display. The player-card screen had been reading the
  athlete *overview* endpoint, whose first split is **career** totals with no
  batting average in it at all -- so a card headed as season stats was showing
  386 career home runs as this season's. The overview is still the fallback
  for feeds (some NCAA athletes) that carry no season summary.
- **Rows built from several fields give up whole fields** when the panel is
  narrow, instead of being cut part-way through one: `Age 34` rather than
  `Age 34  B/T`, and `AVG .241  HR 18` rather than `AVG .241  H`. The season
  line already worked this way on the player-card screen; the rest of the
  card now does too.
- **The card's layout is not tiered by a hardcoded panel-size table.** The
  rows are priority-ordered and the least useful are given up until what is
  left fits, so a 128x32 keeps the banner, the name and a stat or two while a
  256x64 carries the whole card -- one layout that scales, rather than several
  that drift apart.
- **`style: "text"` also stops the ESPN athlete lookup.** The text layout has
  always run off the play-by-play roster names alone, so switching back to it
  no longer pays for a fetch it does not use.

### Fixed
- **The headshot cache had no ceiling.** Every player whose card was drawn
  left ESPN's full-size PNG on disk -- about 200 KB each, a ~600x436 image
  kept to draw a square no larger than 85 pixels -- and nothing ever deleted
  one. MLB alone has ~1200 active players and ESPN's NCAA baseball coverage
  is roughly ten times that, so a board left running through a season grew
  the directory without limit on an SD card. Headshots are now cropped and
  downscaled to a 192px square before being written (~40 KB, no visible
  difference at any panel size), and the directory is held to 200 files,
  evicting least-recently-used first -- a ceiling of roughly 8 MB. Files
  cached by an earlier version keep their original size until they are
  evicted. The in-memory cache of decoded squares is bounded too, the way
  `SportsCore._logo_cache` already bounds team logos.

### Notes
- Card style is MLB and NCAA Baseball only. On MiLB, on a brand-new at-bat, or
  for an athlete ESPN has no record for, the screen falls back to the text
  layout on its own rather than drawing an empty card.
- The banner's text flips between black and white against the team colour, so
  it stays legible for the navy teams as well as the gold ones.

## [1.46.1] - 2026-09-17

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

## [1.46.0] - 2026-09-16

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

## [1.45.3] - 2026-09-16

### Fixed
- **Scores and schedules load again after ESPN stopped accepting date
  ranges.** Since 2026-09-15 ESPN answers `dates=YYYYMMDD-YYYYMMDD` scoreboard
  queries with `400 Bad Request` for every sport. Today's games, the
  lookback/lookahead window and the season schedule are all ranges, so the
  MLB and NCAA baseball boards logged `400 Client Error` and showed nothing. A rejected
  range is now fetched by `fetch_espn_scoreboard` (`baseball_espn_dates.py`, a
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

## [1.45.2] - 2026-09-15

### Removed
- **Unused `get_dynamic_duration_floor()`.** It was a second copy of the
  dynamic-duration floor lookup that read only the league on screen. Nothing
  called it; `get_cycle_duration` uses `_get_duration_floor_for_mode` (the
  highest floor across enabled leagues), which is unchanged. No behaviour
  change. `test_duration_floor_single_source.py` pins the floors.

## [1.45.1] - 2026-09-14

### Fixed
- **Hardening: the live "looks finished" check no longer raises on a None or
  non-numeric period or period text.** `game.get("period_text", "").lower()`
  only defaults a missing key, so a `None` value raised, and
  `SportsLive.update()` does not catch it. Baseball's parsers (ESPN and MiLB)
  never set `period` or `period_text` on a game, so baseball was not affected;
  this keeps its copy in line with the other scoreboards. Such values are now
  treated as empty / period 0; the end-of-game rule is unchanged.

## [1.45.0] - 2026-09-14

### Added
- **`display_options.show_innings`, `show_bases`, `show_outs`, `show_count`**
  (advanced, per league, default on). Hide the inning, the base diamonds, the
  outs or the balls-strikes count on the live scorebug: the full-screen one,
  the scroll/Vegas live card, and (outs, count and the batting-half arrow) the
  traditional scoreboard's At Bat panel. `baseball.py` read these since the
  plugin was written, but nothing drew on them, the manager adapter never
  forwarded them and the schema never offered them. A hidden element leaves
  its space empty rather than moving the others; `FINAL` always shows.

### Fixed
- **Scroll and Vegas result cards show extra innings.** The card hard-coded
  "Final". It now shows the game's "Final/10" (or MiLB's 7-inning "Final/7")
  when that fits between the logos, the rule the full-screen Recent scorebug
  already uses.

## [1.44.0] - 2026-09-14

### Added
- **`scroll_card.switch_show_date` / `switch_show_time`** (advanced): show or
  hide the date and time on the full-screen upcoming scoreboard. The scroll
  card's `show_date` / `show_time` used to blank it as well.
- **Per-league `odds_update_interval` and `live_odds_update_interval`**
  (advanced), and **`play_by_play_update_interval` /
  `player_bio_update_interval`** for MLB and NCAA Baseball. All four were read
  by the code but could not be set.
- **`customization.layout.date`**: the offset the recent date already read.

### Fixed
- **Settings that did nothing.** `display_options.show_series_summary` was
  never forwarded to the managers. The layout offsets the web UI saves as
  `status` and `record` were read under the names `status_text` and `records`;
  both spellings now work. Recent now honours `records.y_offset` and
  `away_x_offset` like Upcoming.
- **Upcoming showed games weeks out.** MLB fetches the whole season, and
  selection never applied `schedule_lookahead_days`. It does now.
- **The first card of a mode was skipped on re-entry.** The dwell clock kept
  running while the mode was off screen. Retaking the panel now gives the
  current card a full turn.
- **Rotated-in games had no odds** until the next hourly update. They are now
  fetched off the display path when the slice rotates.
- **A failed logo blanked the panel.** "Logo Error" was drawn onto a copy that
  was thrown away.
- **Full-screen odds overprinted "Next Game" and "Final".** An O/U with no
  favourite anchors left and steps down a row when it would collide. A home
  spread of 0.0 is no longer treated as missing, and a non-numeric spread no
  longer raises.
- **Unbounded logo caches.** Both caches now evict least-recently-used past 64
  logos. The scroll card cache is keyed by card size, so a card of another size
  is not served a wrongly scaled logo.
- **A cached "no odds" marker refetched on every call.** It is now a cache hit.
- **A failed logo download stayed a grey box forever.** Logos now load through
  the core's downloader, whose placeholders are retried; the vendored
  `logo_downloader.py` is gone.
- **One failing league blanked the others.** Each league's managers are built
  in their own try.
- **`other_games_divisions`**: a string no longer becomes a list of letters and
  null no longer breaks init. The college-football defaults (`["fbs"]`, and
  `ranked` for MLB/MiLB) are replaced with neutral ones.
- **A config `Infinity` crashed manager init.** It now falls back to the
  default.
- **Import errors inside the core were masked.** `manager.py` only falls back
  when the core module is absent.
- **Postponed and cancelled games showed as "Final 0-0" on Recent.** Final now
  needs ESPN's completed flag, and MiLB statuses come from `detailedState`.
- **Suspended games** leave the live rotation, and ESPN "Suspended" is no
  longer read as end-of-inning (it used to jump the inning, e.g. to 8th).
- **MiLB Warmup** is treated as pre-game (it used to draw inning 0). A live
  game with no inning yet shows Top 1st.
- **MiLB live dropped night games after 8 pm ET.** It now queries the Eastern
  date plus the previous day.
- **Live count font:** no longer resizes the display manager's shared 5x7 font.
- **Live run counts** honour the `score_text` colour.

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.
- Recent shows extra innings ("Final/10") where it fits between the logos.

### Removed
- Dead code: `data_manager.py`, `odds_manager.py`, the unused team-logo loaders
  in `logo_manager.py`, the MLB/Soccer API data sources and unused ESPN fetch
  methods, the unused live-status helpers, and unreachable end/mid inning
  branches. The duplicate poll-choice rule is now one shared function.

### Docs
- README: removed the per-league `background_service` settings (they do not
  exist), corrected the `mode_durations` and MiLB display-flag claims, fixed the
  table broken by a blockquote, and documented `scroll_settings.dynamic_duration`
  and the new intervals.

## [1.43.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [1.42.0] - 2026-09-11

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

## [1.41.1] - 2026-09-11

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

## [1.41.0] - 2026-09-10

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
## [1.40.7] - 2026-09-11

### Fixed
- **Placeholder team logos draw their abbreviation at PressStart2P 16, not 12.**
  That face is crisp only at multiples of 8; 12 was anti-aliased, and 16 is the
  nearest crisp size for the 64px logo tile. Panel text was already on-grid via
  `_FONT_PIXEL_GRID` and is unchanged.

## [1.35.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.

## [1.35.2] - 2026-08-31

### Changed
- **`DynamicTeamResolver` no longer takes ESPN's first ranking block on trust.** Hardening only, with no behaviour change here: this plugin's `AP_TOP_n` patterns resolve from the college baseball poll, and nothing routes to the college football endpoint its resolver also maps. In the copies where that endpoint *is* reachable, ESPN returns four blocks — AP Top 25, AFCA Coaches, FCS Coaches, AFCA Division II — and taking the first made `AP_TOP_25` resolve to 25 FCS schools the moment ESPN reordered them. The shared resolver is kept in step across all four copies, and `scripts/test_dynamic_poll_choice.py` now holds every one of them to it.

## [1.35.1] - 2026-08-30

### Fixed
- **Recent games come back when favourite teams are set.** `SportsRecent.update()` calls `self._favorites_first(...)`, but that helper — and `_other_games_window` and `_is_favorite_game` with it — was defined on `SportsUpcoming`, a sibling class rather than an ancestor, so the call raised `AttributeError`. `update()` catches it, logs `Error updating recent games` and carries on with an empty list, so the recent screen simply showed nothing. It only bites when favourite teams are configured without `show_favorite_teams_only`, which is the ordinary way to use the setting.
- `football-scoreboard` already had all three on `SportsCore` and was unaffected; this brings the rest into line. Every safety-harness render is byte-identical — this plugin's fixture sets no favourites, so the broken path was never reached there.

## [1.35.0] - 2026-08-29

### Changed
- **The score is now the headline it was always meant to be.** It was the only element on the card not sized from the panel, and it was not even bigger than its neighbours: PressStart2P renders crisply on an 8px grid, so the 10px default snapped to 8 — the same 8 the clock above it and the game date below it are drawn at. It is now sized from `display_height`, snapped to its face's pixel grid and capped at twice its design size, with the clock/date face held a grid step below it.
- **A narrower face instead of smaller logos.** Where the grown score would swamp the panel the layout reaches for a narrower *face*, which is what `football-scoreboard` has always done via `_fit_score_font` and the single reason its logos read larger than every other scoreboard's at the same panel size. Measured on 128x64: `4x6-font` at 14px reserves 28px and leaves 52x52 logos, where `PressStart2P` at 16px reserved 60px and left 36x36. The two faces are not the same shape — PressStart2P is square, 4x6-font is nearly as tall and about half as wide — so the score keeps the dimension that carries legibility and gives back the one the logos need.
- **Logos are sized against the space the score actually needs**, and only where the score grew. A panel whose score did not move keeps exactly the logos it had.
- **Score and date positions scale with their faces.** The bottom-anchored score's `-14`, the centred score's `-3`, and the date's 7px drop were all chosen for an 8px face and clipped a grown one off the card.
- **The upcoming screen is untouched at every size.** It draws no score — `fonts["score"]` appears in `SportsUpcoming` zero times, `fonts["time"]` five times — so none of the score-driven sizing applies to it and its date and time keep the face and size they always had. Measured on the live and recent screens: 64x32, 128x32 and 256x32 are byte-identical to the previous release; every taller panel gains a larger score with logos the score is no longer drawn across.
- The live card's run counts grow with the panel too: both halves of the bottom BOS:4 row were drawn in the fixed 8px display_manager.font, so the run count was the size of the abbreviation beside it. The runs now use the panel-scaled score font while the abbreviation stays small. Scroll-card logos fill the full card height instead of 0.75x it.

## [1.22.0] - 2026-08-03

### Changed
- **Scroll display now runs on the core's shared implementation.** The orchestration half of `scroll_display.py` — scroll-helper configuration, frame pumping, completion, settings resolution, and native `global_config['target_fps']` support — moves to the core's `src.common.sports_scroll` (LEDMatrix 3.2.0). Only the baseball-specific content half stays here: game cards and league separator icons. A fix to the shared behaviour now lands once in the core instead of being replicated across nine scoreboards.
- **Nothing changes on an older core.** The import is guarded: a core without `src.common.sports_scroll` falls back to `scroll_display_legacy.py`, the previous self-contained implementation, and the plugin behaves exactly as it did. This is why the minimum core version is unchanged at 2.0.0 — the plugin does not *require* 3.2.0, it merely prefers it. The fallback goes away in a later release, and the floor rises then.
- Verified byte-for-byte: all 24 safety-harness renders (8 panel sizes × 3 screens) are identical to 1.21.1, before and after.

## [1.21.1] - 2026-08-03

### Fixed
- **Live games no longer flood the log**: `has_live_content()` is called from the display path — once per *frame* in Vegas mode — and it emitted a per-league INFO line for MLB, MiLB and NCAA on every call where that league had any live game. Those three lines had no throttle at all; only the final summary did, and that one skipped the throttle whenever the answer was True ("always log True immediately"), which is harmless for an occasional caller and ruinous for a per-frame one. Measured on a 512x64 device with nine live MLB games: **13,871 lines a minute, 98% of the entire journal**, which both buried every other message and put needless journald writes on the render path. The three per-league lines are now folded into the single summary, which carries the same counts, and that summary is logged when the answer *changes* — a game starting or ending, a league flipping — then at most once a minute while it holds. Same device after the fix: **3 lines a minute.** A steady state is still visible in the log; a live afternoon no longer costs tens of thousands of lines.
## [1.21.0] - 2026-08-02

### Fixed
- Explain an empty screen instead of leaving the user guessing. A favorite team code that is not a real ESPN abbreviation matched no game and showed nothing, and so did a correct code before its season started - the two were indistinguishable from the logs. The plugin now says which it is, suggests the right code for a near miss (GBP -> GB), and reports when the league's next games are. The check runs in the background, once per league, and cannot affect what is displayed.

## [1.20.3] - 2026-08-02

### Fixed
- **Leftover `"timezone": "UTC"` no longer has to be removed by hand**: the write-back bug in versions before 1.20.0 persisted `"timezone": "UTC"` into the saved plugin config, where it then shadowed the real global timezone — so users who updated to 1.20.0 still saw UTC until they edited the config. That stale value is now detected and ignored automatically whenever the global or system timezone disagrees, with a warning naming what it used instead. `Etc/UTC` is the unambiguous way to ask for UTC on purpose and is always honored; it is a spelling the old bug could never have produced.
- **The core's own `"UTC"` default no longer masks a missing global setting**: `ConfigManager.get_timezone()` is `self.config.get('timezone', 'UTC')`, so it returns `"UTC"` for a config with no `timezone` key at all. 1.20.0 took that at face value and therefore never reached the host system zone. Resolution now reads the raw config dict and treats an absent key as absent, falling through to the system timezone as designed.

## [1.20.1] - 2026-07-28

### Fixed
- **Vegas scroll showed only one game**: `get_vegas_content()` returned the union
  of every scroll display's cached items, so once the standalone rotation had
  rendered a mode, Vegas inherited that mode's games — with a single live game in
  progress the whole ticker entry collapsed to one card. It now reads a dedicated
  combined slate (live + recent + upcoming, across every enabled league) that
  cannot be clobbered by the standalone displays, and a game held by two displays
  is no longer shown twice.
- **Vegas content stalled the scroll**: building the Vegas slate called `update()`,
  putting network I/O on the render path and freezing the ticker for seconds. The
  slate is now rendered from whatever data the plugin already has, and is rebuilt
  only when the games actually change (fingerprinted on scores, inning, count and
  game set) instead of on every fetch.
- **Vegas build hijacked the standalone scroll**: rendering the Vegas slate went
  through `prepare_and_display()`, which also repoints the manager's active
  scroll display, so the next standalone frame rendered the Vegas slate instead
  of the game type the rotation was showing. Vegas now uses a new
  `prepare_content()` that renders without switching the active display.

### Changed
- **`game_card_width` guidance**: the description advised lowering it on
  multi-panel chains, which is backwards — on a wide panel cards need to be
  *wider* to stay readable. It now suggests roughly display width / 3.

## [1.20.0] - 2026-07-28

### Fixed
- **Game start times shown in UTC**: The plugin read the LEDMatrix global timezone only from `cache_manager.config_manager`. On cores that hang `config_manager` off the plugin manager instead, that lookup came back empty and every start time was rendered in UTC — a 6:45pm Central first pitch displayed as `11:45PM` — while plugins that check the plugin manager first (clock-simple, geochron) showed the correct local time on the same device. Timezone resolution now lives in one place (`baseball_timezone.py`) shared by the switch-mode scorebug, the scroll-mode game card and the plugin manager, and tries, in order: the plugin's own `timezone` setting, `plugin_manager.config_manager`, `cache_manager.config_manager`, the host system zone (`TZ`, `/etc/timezone`, `/etc/localtime`), and only then UTC.
- **`timezone` setting was silently discarded**: The key was never declared in `config_schema.json`, which sets `additionalProperties: false`, so hand-editing it in the saved config had no effect. It is now a documented string property under Advanced Settings.
- **Plugin no longer writes a timezone back into your config**: The manager used to assign `self.config["timezone"]`, mutating the dict the core handed it and persisting a bogus `"timezone": "UTC"` into the saved plugin config. The resolved value is now kept on the instance and passed to sub-components via a copy.

### Added
- `timezone` (Advanced Settings): optional IANA zone override, e.g. `America/Chicago`. Blank (the default) follows the LEDMatrix global timezone.

## [1.19.0] - 2026-07-09

### Added
- **Player Card screen**: A new dedicated full-screen card (`show_player_card`, per league; MLB & NCAA Baseball) that periodically rotates into the live display for the current batter — and optionally the pitcher — with a headshot image, jersey number, position, bat/throw hand, and season stats (AVG/HR/RBI for hitters, ERA/W-L/K for pitchers). Bio + headshot are fetched from ESPN's athlete API and cached (in-memory + on disk). On tiny panels (e.g. 64×32) the headshot is hidden and a compact text card is shown; the card degrades to text-only whenever a headshot is unavailable and is skipped entirely for MiLB (no ESPN player data). Tunable under Customization → Player Card.
- **Team-color grid tint**: The Traditional Scoreboard now paints a subtle (~12% brightness) wash of each team's real ESPN color behind its row, plus a solid team-color accent strip on the left edge (toggle `show_team_color_backgrounds`, default on; requires `use_team_colors`).

### Changed
- **Clearer Pitcher/Batter labels**: The pitcher/batter screen now spells out `Pitcher:` and `Batter:` instead of the ambiguous `P:` / `B:` (the latter clashed visually with the grid's Balls indicator).

## [1.0.4] - 2025-10-20

### Added
- **Proper Font Loading**: Load PressStart2P and 4x6 fonts matching original managers
- **Logo Loading**: Full logo path resolution with case-insensitive matching
- **Logo Sizing**: Logos properly scaled to display dimensions (width/height * 1.5)
- **Scoreboard Rendering**: Professional scoreboard layout with team logos, scores, and status
- **Text Outline**: Text rendering with black outlines for better readability

### Changed
- **Replaced Placeholder**: Removed TODO comments and placeholder text rendering
- **Visual Parity**: Now matches original baseball manager layout and appearance

## [1.0.3] - 2025-10-20

### Fixed
- **Live Priority Integration**: Implemented `has_live_content()` method to properly integrate with display controller
- **Display Logic**: Plugin now only shows "baseball_live" mode when there are actual live games
- **No More "No Live Games"**: Plugin won't be called when there are no live games to display
- **Mode Filtering**: Added `get_live_modes()` to only show live mode during live priority takeover

## [1.0.2] - 2025-10-19

### Initial
- Initial release with basic baseball scoreboard functionality

