# Changelog

## [1.1.0] - 2026-07-29

### Fixed
- **Took the full panel width regardless of title length**: the progress bar was
  drawn across the whole text area, so the rendered frame was always full-width —
  on a 512px panel a short episode name left a bar stretching across the display.
  Because a bar is drawn pixels, a ticker cannot trim it back. It is now sized to
  the widest of the title and subtitle, which also lets the blank remainder be
  reclaimed in Vegas scroll mode. A title long enough to scroll still fills the
  bar. Set `progress_bar_match_text` false for the original behaviour.

