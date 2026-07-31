# Changelog

## [1.2.0] - 2026-07-29

### Changed
- **Progress bar now matches the text width**: the bar spanned the whole text
  area regardless of how much of it the text filled, so a short track title on
  a wide panel left a bar stretching across the display. It is now sized to the
  widest of the title, artist and album lines. A line long enough to scroll
  still fills the bar, since that line genuinely fills the width. Disable with
  `progress_bar_match_text` for the original behaviour.

