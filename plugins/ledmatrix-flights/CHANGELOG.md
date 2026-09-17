# Changelog

## [1.14.1] - 2026-09-16

### Fixed
- **Paid FlightAware calls follow `flightaware.enabled`.** The enrichment
  factory built the paid AeroAPI provider whenever `enrichment_provider` was
  `flightaware` and a key was saved, so switching "Enable paid FlightAware API
  calls" off kept every tracked-flight route lookup billing. It now also needs
  `flightaware.enabled`, and falls back to the free adsb.lol lookup otherwise.
- **A key saved as `flightaware_api_key` works again.** Start-up copied every
  nested `flightaware.*` value over its flat key, and the core merges the
  section's defaults into every config, so the empty `flightaware.api_key`
  replaced a key saved under the old flat name, which the README's
  `config_secrets.json` example used. The flat key is now used when the
  section's key is blank.

### Changed
- **`flight_plan_enabled` is not read.** It has been overridden by the section's
  default since the section was added. Honouring it now would restart paid calls
  on boards whose settings page shows FlightAware off, so paid calls need
  `flightaware.enabled`. The other flat FlightAware keys are not read either; a
  flat value that differs from its default and from the section logs a warning
  naming it.
- **`live_update_interval` defaults to 5**, not 2. The core runs a plugin's
  `update()` at most every 5 seconds, so a 2-second live fetch never happened.
  Values below 5 act as 5 for both intervals, and the descriptions say so.

## [1.14.0] - 2026-09-15

### Changed
- **`flight_tracker_live` is registered whenever the plugin has another slot.**
  The core reads a plugin's display modes once, when the plugin loads.
  `flight_tracker_live` was listed only while live priority was already on, so
  a board started with it off never registered the slot; enabling it from the
  web UI rebuilt `self.modes`, but the core's live scan ignores slots it has not
  registered and nothing preempted until the display restarted. The slot is now
  registered next to the legacy `flight_tracker` slot or the selected rotation
  views, and skipped while live priority is off or nothing is overhead, so
  turning live priority on takes effect without a restart.
- **Expected log line.** While the live slot is skipped the core logs
  `Plugin ledmatrix-flights display() returned False for mode flight_tracker_live`
  at INFO once per rotation. It is harmless.
- **No views selected: unchanged.** With `rotation_views: []` the live slot is
  still listed only while live priority is on. The core falls back to the
  manifest's `flight_tracker` slot when a plugin lists no modes, and configs
  saved with no view ticked rely on that to keep the legacy screen. The
  remaining edge: on such a board, turning live priority on needs a restart.

### Fixed
- **Code defaults match `config_schema.json`.** `tile_provider`,
  `fade_intensity`, `custom_tile_server`, `show_trails`, `header_color`,
  `show_aircraft_icon` and `max_api_calls_per_hour` fell back to different
  values in code than the schema declares. That only mattered when a key was
  missing from the saved config, where the board then disagreed with the web UI.

### Removed
- **`max_ledmatrix_version` from the manifest.** The core never reads it, and a
  core that started honouring `"3.0.0"` would lock the plugin out. Added a
  manifest `category` so the registry can sync it.

## [1.13.4] - 2026-09-12

### Removed
- **`convert_to_plugin.py`.** A one-off migration script that opened
  `flight_manager_original.py` at import time, with no `__main__` guard, and
  that file exists nowhere -- so any tool that imported or collected it failed
  with `FileNotFoundError`. Nothing referenced it; plugin behaviour is unchanged.

## [1.13.3] - 2026-09-11

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

  Every rung of the font ladder is now on its face's grid. Between 5px and 12px
  the whole palette has only two crisp sizes — 4x6 at 7 and PressStart2P at 8 —
  so the small and medium rungs now coincide. That is not a lost hierarchy: of
  the old 6/8/10 and 8/10/12 ladders only the 8s were ever crisp, so the tiers
  differed by blur as much as by size. On 64-tall panels the large rungs move up
  to PressStart2P 16 and 4x6 14. A finer re-tier needs layout work, not just a
  font size.

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

