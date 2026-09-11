# Changelog

## [1.10.0] - 2026-09-11

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

## [1.9.1] - 2026-09-09

### Fixed
- **`has_live_content()` no longer floods the journal during a live card.** It runs on the display path — once per *frame* in Vegas mode. The summary at the end of the function was throttled by `should_log and not ufc_live`, but a second INFO line sat inside the `if live_games:` branch with no guard at all, so a live card logged on every call: roughly 50 lines a second on a rig measured at 50 fps. Because every earlier throttle fix (baseball 1.20.4, football, hockey/basketball/lacrosse #308) inspected the guard rather than the whole function body, this call survived all of them. Both branches now share one state-change plus 60-second heartbeat throttle, matching `baseball-scoreboard`. Pinned by `test_live_content_log_throttle.py`.

## [1.7.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.
