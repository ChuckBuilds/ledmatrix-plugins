# Changelog

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
