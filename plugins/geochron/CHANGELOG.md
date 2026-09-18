# Changelog

## [1.2.0] - 2026-09-18

### Changed
- **The readout is a timezone list.** Your local time comes first, then one row
  per city that has a `timezone`: a short label on the left and the time
  right-aligned, so the times read down a column. The subsolar coordinates
  and seconds are gone from it; they crowded the sidebar, and the featured
  city was cut to "New Yo". The date now heads the list (`show_date`).
- **Wide panels size the sidebar to the list** and the map gives up the width.
  When there are more cities than rows, the local row stays pinned and the
  cities page every 5 seconds, split evenly across pages.
- **Corner readouts** (non-wide panels) show the local time and the first city
  in the same label-and-time form, instead of UTC and the date.
- **The default city list is New York alone**, not eight cities. Saved
  configs keep whatever cities they already list.

### Added
- **`show_date`** (default on) heads the timezone list with your local date,
  e.g. `FRI AUG 1`, when the sidebar has a row to spare.
- **`show_date_line`** (default on) draws a dotted line on the map where it is
  midnight right now, with the weekday on each side. East of it is already
  tomorrow; it sweeps west 15 degrees an hour. **`date_line_labels`** puts
  the weekdays along the `bottom` (default) or `top` edge of the map.
- **`cities[].label`**, up to 4 characters, overrides the automatic label
  (initials for multi-word names, otherwise the first three letters).

### Deprecated
- **`show_seconds` has no effect.** It stays in the schema so saved configs
  still validate.

## [1.1.0] - 2026-09-16

### Fixed
- **`update_interval` works.** It was read and never used: the core scheduled
  `update()` at the manifest's 45 seconds, because it prefers the manifest's
  value unless the plugin answers `get_update_interval()`. The plugin now
  returns the configured interval, and a web-UI change applies without a
  restart.

### Changed
- **Requires LEDMatrix core 3.4.0**, the first with the `get_update_interval()`
  hook.

## [1.0.7] - 2026-09-15

### Fixed
- **The live renderer loads the 4x6 face at 7px**, the size 1.0.6 gave the
  preview renderer. The clock readout on the panel was still drawn at 6px, off
  the face's pixel grid.
- **A bad timezone no longer blanks the clock.** An unrecognised `timezone`
  (or city `timezone`) failed `validate_config`, and core refuses to load a
  plugin that fails validation. It now logs a warning and falls back to the
  LEDMatrix timezone, then system time.

## [1.0.6] - 2026-09-11

### Fixed
- **Preview renderer loads the 4x6 face at 7px**, its pixel grid, rather than 6.
  Off the grid FreeType anti-aliases to fake the in-between stroke widths, which
  on an LED panel is a dim lamp rather than a soft edge.

## [1.0.0] - 2026-06-10

### Added
- Initial release: real-time world map rendered from vendored Natural Earth
  110m country outlines.
- Day/night terminator computed from a NOAA simplified solar position
  algorithm, with smooth civil/nautical/astronomical twilight bands.
- Subsolar point marker, configurable lat/lon graticule, and up to 8
  configurable city markers (8 classic Geochron cities included by default).
- Digital UTC + local clock readout (12h/24h, optional seconds).
- Responsive layout that adapts to panel aspect ratio: wide sidebar on long
  panels, full-bleed map with a corner readout on near 2:1 panels, and
  longitude-cropped full-bleed map on square/tall panels.
