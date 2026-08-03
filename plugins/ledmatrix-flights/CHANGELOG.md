# Changelog

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

