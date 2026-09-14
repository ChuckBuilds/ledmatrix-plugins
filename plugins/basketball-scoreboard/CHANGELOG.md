# Changelog

## [1.33.0] - 2026-09-14

### Added
- `scroll_card.switch_show_date` / `switch_show_time` for the full-screen
  upcoming scorebug (default on), so the scroll-card toggles no longer blank it
  (port of #342).
- Advanced per-league `odds_update_interval` (default 3600) and
  `live_odds_update_interval` (default 60). The code already read them, but
  they were undeclared and never forwarded to the managers.

### Fixed
- **Postponed, cancelled and suspended games no longer show as "Final 0-0"**
  on Recent. `is_final` now requires a completed, played game, and the period
  text shows ESPN's own label for these games.
- **Full-screen odds no longer overprint the top-centre text.** With only an
  O/U, it was centred on the row holding "Final", the quarter or "Next Game".
  It is now anchored left, and the odds step down a row on collision, as the
  scroll cards already do. A home spread of 0.0 is no longer treated as
  missing, and a non-numeric top-level spread no longer drops the whole line.
- **"Logo Error" is drawn instead of a black panel** at all three fallback
  sites (live, upcoming, recent).
- **Vegas cards follow the game data.** They are rebuilt when the slate's
  signature changes (previously only when empty). They are read from the
  dedicated 'mixed' display and rendered without hijacking the active
  standalone scroll. No network on that path.
- **One failing league no longer takes the others down.** Each league is
  initialised in its own try. A failed league's managers are None, and
  update() skips them instead of raising AttributeError every tick.
- A cached "no odds" marker is a cache hit again instead of refetching.
- Decoded-logo caches in `sports.py` and `game_renderer.py` are bounded LRUs
  (port of core #559).
- Upcoming games are trimmed to `schedule_lookahead_days`, the dwell clock
  resets when a mode comes back on screen, and games the other-games rotation
  swaps in get odds (ports of #345, #343).
- `other_games_divisions` is passed through raw, so a hand-edited string no
  longer becomes a list of letters and `null` no longer blanks the plugin.
- `test_mode` is forwarded to the managers.
- A config `Infinity` no longer crashes init (`OverflowError` in
  `_clamp_window` / `_setting_int`).

### Changed
- Behaviour change: `scroll_card.show_date` / `show_time` no longer hide the
  date and time on the full-screen upcoming scorebug (they did since #336). A
  config that turned them off shows the date/time there again; turn off
  `switch_show_date` / `switch_show_time` to hide them.
- The core floor stays at 3.3.0. `sports.py` imports `src.common.sports_shared`,
  which first shipped in core v3.3.1, but that release still reports
  `__version__ = "3.3.0"`, so a 3.3.1 floor would refuse every current core.
- Removed the unused bundled `logo_downloader.py`; `sports.py` already imports
  `src.logo_downloader`.
- `test_settings_reach_the_manager.py` builds its probes from
  `config_schema.json`, with an allowlist that gives a reason for each key
  consumed outside the league managers.

## [1.32.0] - 2026-09-14

### Added
- **Favorite games get extra turns in switch mode.** New game-limit setting
  `favorite_rotation_boost` (1-5, default 1): a favorite team's recent or
  upcoming card gets that many turns per rotation for every one turn other
  cards get, its extra turns spread evenly around the loop and kept apart
  whenever enough other cards remain to separate them. Previously only live
  games could weight favorites.

  Existing configs are unaffected: at the default of 1 every card is shown
  once per rotation, in the same order as before.

## [1.31.0] - 2026-09-11

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

## [1.30.1] - 2026-09-11

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

## [1.30.0] - 2026-09-10

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
## [1.29.7] - 2026-09-11

### Fixed
- **Placeholder team logos draw their abbreviation at PressStart2P 16, not 12.**
  That face is crisp only at multiples of 8; 12 was anti-aliased, and 16 is the
  nearest crisp size for the 64px logo tile. Panel text was already on-grid via
  `_FONT_PIXEL_GRID` and is unchanged.

## [1.24.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.
