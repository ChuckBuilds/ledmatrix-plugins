# Changelog

## [1.12.6] - 2026-07-29

### Fixed
- **Vegas scroll map was missing trails, the centre marker and the aircraft
  count**: `get_vegas_content()` reimplemented a cut-down version of the map
  view that drew only the background and the aircraft dots, so aircraft trails
  never appeared in the ticker even with `show_trails` enabled — and neither did
  the white centre-position dot or the aircraft count. Both paths now share a
  single `_render_map_image()`, so the ticker renders the same map as the normal
  rotation and cannot drift from it again.

