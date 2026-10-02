# Changelog

## [1.5.5] - 2026-10-03

### Fixed
- Scrolling no longer stutters while YouTube Music is playing. websocket-client
  validates every text frame's UTF-8 in pure Python (unless wsaccel is
  installed), holding the GIL; the companion pushes its whole player state
  every few seconds, and on a 512x64 Pi 4 that check was ~16% of the display
  process's GIL time and stalled ~8% of scroll frames (0.6% without it). The
  socket now skips it via `websocket_extra_options`; the payload is still
  decoded and parsed as JSON, which rejects anything malformed.

## [1.5.4] - 2026-10-02

### Fixed
- Spotify: the decoded album cover is kept between polls. The previous art URL
  was read from the freshly replaced track dict, where it never exists, so
  every progress-only poll (every 2 s) dropped the cover and display()
  decoded it again.
- The `enabled` fallback is true, matching the schema and the core.

## [1.5.3] - 2026-10-02

### Fixed
- YouTube Music: a new companion URL saved in the web UI, or a new token from
  the authentication script, now applies without restarting the display
  service. Both were read only at startup, so the client kept retrying the old
  address (or the old token) and the screen stayed on "Nothing Playing". The
  files are re-checked before each connect attempt, and a change clears the
  reconnect backoff so the new settings are tried straight away.

## [1.5.2] - 2026-09-28

### Changed
- Removed code that nothing called. No change in behaviour.

## [1.5.1] - 2026-09-28

### Fixed
- Saved settings now apply without a restart. The core applies a web-UI save
  by calling on_config_change, not by reloading the plugin, and the base
  version only replaces self.config; only layout_mode was re-read, so fonts,
  text scrolling and the polling interval waited for a restart. They are re-
  read on save. Switching preferred_source still needs a restart (it means
  replacing one client and its threads with the other); the log says so
  instead of recording a source nothing listens to.

## [1.5.0] - 2026-09-28

### Added
- Declares spotify_redirect_uri (a secret, blank by default). The Spotify
  client reads it from config_secrets.json, and the core merges secrets into
  the plugin config, where the strict schema rejected it: a user who followed
  the README had the plugin flagged Degraded. Blank keeps the default,
  http://127.0.0.1:8888/callback, and the README example now matches that
  default instead of localhost:8080.

## [1.4.5] - 2026-09-27

### Fixed
- **The Spotify access token is no longer written to the log.** A startup
  diagnostic logged the first 120 characters of `config/spotify_auth.json` at
  INFO on every start, and that file begins with the live access token. It
  now logs only the file's length.

## [1.4.4] - 2026-09-16

### Fixed
- **Artist and album text use the 5x7 bitmap face by default again.** The
  element-style resolver was given Press Start 2P as the classic font for
  those rows, and it uses the classic font whenever the configured font equals
  the schema default (`5x7.bdf`). Every default config therefore drew them in
  Press Start 2P at 7px, off that face's 8px grid, and choosing `5x7.bdf` in
  the web UI changed nothing. An explicitly chosen font is still used.
- README font lists no longer offer `cozette.bdf`, which the schema rejects.

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

