# Changelog

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
