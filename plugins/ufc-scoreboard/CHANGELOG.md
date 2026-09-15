# Changelog

## [1.13.0] - 2026-09-15

### Changed
- **Requires LEDMatrix core 3.4.0.** The scroll frame hold is passed to
  `display_manager.set_scrolling_state(True, frame_hold=...)`, an argument
  older cores do not have.

### Fixed
- **`ufc.scroll_settings.scroll_speed` / `scroll_delay` set the scroll speed
  again.** The shared scroll resolver was handed the whole plugin config and
  never looks in `ufc.scroll_settings`, so every user ran at its 100 px/s
  default. The setting is now passed as pixels per second (a value under 10
  keeps meaning pixels per `scroll_delay` step) and snapped to the nearest
  speed the panel can move in whole pixels.
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
