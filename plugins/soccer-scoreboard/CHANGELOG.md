# Changelog

## [2.6.0] - 2026-08-04

### Changed
- **Scroll display now runs on the core's shared implementation.** The orchestration half of `scroll_display.py` — scroll-helper configuration, frame pumping, completion, settings resolution, and native `global_config['target_fps']` support — moves to the core's `src.common.sports_scroll` (LEDMatrix 3.2.0). Only the soccer-specific content half stays here: game cards and league separator icons.
- **Nothing changes on an older core.** The import is guarded: a core without `src.common.sports_scroll` falls back to `scroll_display_legacy.py` and the plugin behaves exactly as it did. The minimum core version is unchanged at 2.0.0 — the plugin does not *require* 3.2.0, it merely prefers it.
- This lineage's scroll settings are preserved explicitly, since they differ from the shared defaults: a 24px gap rather than 48, `min_duration`/`max_duration` bounds of 30/300 (core's own default max is 600), and game cards pinned at 128px where core sizes them to the panel.
- Three unused methods (`_get_scroll_speed`, `get_scroll_duration`, `has_content`) are not carried over — nothing called them. A redundant `set_scroll_speed()` call is also gone: the previous code set it twice, once in px/s and again in px/frame, and only the second took effect.
- Verified byte-for-byte: all 24 safety-harness renders (8 panel sizes × 3 screens) are identical to 2.5.2.

## [2.5.0] - 2026-07-29

### Fixed
- **TEAMS.md listed wrong team codes**: the documented abbreviations had drifted
  from ESPN's, so following the docs produced a silently empty display. Manchester
  United was listed as `MUN` (ESPN uses `MAN`), Manchester City as `MCI` (`MNC`),
  Real Madrid as `RM` (`RMA`), and Ligue 1 had eight wrong codes including Lyon
  and Marseille. Several rosters were also a season out of date. Every table is
  now generated from ESPN's live team endpoints and verified against them.

### Added
- **A reason when a league shows nothing.** An empty screen had two very
  different causes that looked identical in the logs. Now, once per league:
  an unrecognised favorite team logs a warning naming the closest match
  (`favorite team 'MUN' is not a Premier League team code. Closest match is
  'MAN' (Manchester United).`), while codes that are correct but have no
  fixtures yet log the date the season starts, stating that an empty display
  until then is expected rather than a misconfiguration.
- **Cross-league code clashes documented.** Favourites match by abbreviation
  across every enabled league, and `MUN` is Bayern Munich in the Bundesliga —
  so the old docs could have matched the wrong club entirely. TEAMS.md now
  lists the codes that mean different clubs in different leagues.

