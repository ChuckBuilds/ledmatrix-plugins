# Changelog

## [1.13.2] - 2026-09-09

### Fixed
- **An unreachable receiver no longer costs a connect timeout on every poll.** When `adsb-feeder.local` (or whatever `skyaware_url` points at) goes away, `_fetch_aircraft_data()` used to pay the full 5-second timeout on every single poll and log an ERROR each time — on a measured rig that was 22 of the last 24 hours' worth of errors. Failures now back off from 30 seconds, doubling to a five-minute ceiling, and drop to DEBUG once the wait stops growing, so an extended outage costs a handful of lines instead of one per poll forever. Recovery logs once at INFO. This is the same shape `_TILE_FAILURE_COOLDOWN` already uses for map tiles.
  The cost was never confined to this plugin: the core runs every plugin's `update()` on a single shared worker, so a dead host here delayed every other plugin's refresh behind it.

### Changed
- **Per-poll tracing moved to DEBUG.** `Fetching aircraft data from …`, `Received data, processing aircraft…` and `Currently tracking N aircraft` fired on every poll — the existing `is_visible` INFO/DEBUG split never narrowed anything, because a plugin in rotation is visible nearly all the time. `display(): mode=…` now logs at INFO only when the mode actually changes (627 lines an hour on the measured rig). Together these were roughly 1,100 journal lines an hour. The `Summary - …` line is untouched: it is already throttled on state change with a five-minute heartbeat.

## [1.12.7] - 2026-08-03

### Fixed
- **Map background cache could hand a render the wrong size**: the cached
  composite is already cropped to the display aspect ratio and resized to the
  panel, but it was keyed on centre and zoom alone. Vegas narrows the display
  manager while requesting content, so the rotation and the ticker ask for the
  same view at different widths — and whichever rendered second was served the
  other one's image. `_render_map_image()` copies that background, so the whole
  frame came back at the wrong size, with aircraft and trails projected for the
  size it didn't get. The cache now keys on the display size as well, holding
  one entry per size and dropping them all when the centre or zoom moves, so
  neither path re-tiles when they alternate.

## [1.12.6] - 2026-07-29

### Fixed
- **Vegas scroll map was missing trails, the centre marker and the aircraft
  count**: `get_vegas_content()` reimplemented a cut-down version of the map
  view that drew only the background and the aircraft dots, so aircraft trails
  never appeared in the ticker even with `show_trails` enabled — and neither did
  the white centre-position dot or the aircraft count. Both paths now share a
  single `_render_map_image()`, so the ticker renders the same map as the normal
  rotation and cannot drift from it again.

