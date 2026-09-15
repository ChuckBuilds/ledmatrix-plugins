# Changelog

## [1.4.3] - 2026-09-15

### Fixed
- **No network on the render thread.** `display()` still downloaded album art
  inline (5 s timeout) whenever nothing had been prefetched, and
  `activate_music_display()` called YTM `connect_client(timeout=10)`, which can
  block for 15 s. Art is now downloaded only by the polling thread, the YTM
  event thread and `update()` (retried 30 s after a failure); `display()` draws
  the placeholder until it arrives. YTM is connected by the polling thread,
  which already reconnects with backoff while the display is active.
- **Downloads no longer hold `track_info_lock`,** which `display()` takes every
  frame, so a slow cover no longer stalls the panel through the lock.
- **Prefetched art and its URL are read and written together under a lock,**
  so a frame cannot pair one track's cover with another track's URL.

### Removed
- Unused `get_current_display_info()`, and the unenforced
  `max_ledmatrix_version` manifest field.

## [1.2.0] - 2026-07-29

### Changed
- **Progress bar now matches the text width**: the bar spanned the whole text
  area regardless of how much of it the text filled, so a short track title on
  a wide panel left a bar stretching across the display. It is now sized to the
  widest of the title, artist and album lines. A line long enough to scroll
  still fills the bar, since that line genuinely fills the width. Disable with
  `progress_bar_match_text` for the original behaviour.

