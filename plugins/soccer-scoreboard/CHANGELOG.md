# Changelog

## [2.18.0] - 2026-08-29

### Changed
- **The score is now the headline it was always meant to be.** It was the only element on the card not sized from the panel, and it was not even bigger than its neighbours: PressStart2P renders crisply on an 8px grid, so the 10px default snapped to 8 — the same 8 the clock above it and the game date below it are drawn at. It is now sized from `display_height`, snapped to its face's pixel grid and capped at twice its design size, with the clock/date face held a grid step below it.
- **A narrower face instead of smaller logos.** Where the grown score would swamp the panel the layout reaches for a narrower *face*, which is what `football-scoreboard` has always done via `_fit_score_font` and the single reason its logos read larger than every other scoreboard's at the same panel size. Measured on 128x64: `4x6-font` at 14px reserves 28px and leaves 52x52 logos, where `PressStart2P` at 16px reserved 60px and left 36x36. The two faces are not the same shape — PressStart2P is square, 4x6-font is nearly as tall and about half as wide — so the score keeps the dimension that carries legibility and gives back the one the logos need.
- **Logos are sized against the space the score actually needs**, and only where the score grew. A panel whose score did not move keeps exactly the logos it had.
- **Score and date positions scale with their faces.** The bottom-anchored score's `-14`, the centred score's `-3`, and the date's 7px drop were all chosen for an 8px face and clipped a grown one off the card.
- **The upcoming screen is untouched at every size.** It draws no score — `fonts["score"]` appears in `SportsUpcoming` zero times, `fonts["time"]` five times — so none of the score-driven sizing applies to it and its date and time keep the face and size they always had. Measured on the live and recent screens: 64x32, 128x32 and 256x32 are byte-identical to the previous release; every taller panel gains a larger score with logos the score is no longer drawn across.

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

