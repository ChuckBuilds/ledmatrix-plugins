# Changelog

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
