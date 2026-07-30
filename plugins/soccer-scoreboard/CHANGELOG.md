# Changelog

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

