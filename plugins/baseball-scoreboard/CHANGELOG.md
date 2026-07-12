# Changelog

## [1.19.0] - 2026-07-09

### Added
- **Player Card screen**: A new dedicated full-screen card (`show_player_card`, per league; MLB & NCAA Baseball) that periodically rotates into the live display for the current batter — and optionally the pitcher — with a headshot image, jersey number, position, bat/throw hand, and season stats (AVG/HR/RBI for hitters, ERA/W-L/K for pitchers). Bio + headshot are fetched from ESPN's athlete API and cached (in-memory + on disk). On tiny panels (e.g. 64×32) the headshot is hidden and a compact text card is shown; the card degrades to text-only whenever a headshot is unavailable and is skipped entirely for MiLB (no ESPN player data). Tunable under Customization → Player Card.
- **Team-color grid tint**: The Traditional Scoreboard now paints a subtle (~12% brightness) wash of each team's real ESPN color behind its row, plus a solid team-color accent strip on the left edge (toggle `show_team_color_backgrounds`, default on; requires `use_team_colors`).

### Changed
- **Clearer Pitcher/Batter labels**: The pitcher/batter screen now spells out `Pitcher:` and `Batter:` instead of the ambiguous `P:` / `B:` (the latter clashed visually with the grid's Balls indicator).

## [1.0.4] - 2025-10-20

### Added
- **Proper Font Loading**: Load PressStart2P and 4x6 fonts matching original managers
- **Logo Loading**: Full logo path resolution with case-insensitive matching
- **Logo Sizing**: Logos properly scaled to display dimensions (width/height * 1.5)
- **Scoreboard Rendering**: Professional scoreboard layout with team logos, scores, and status
- **Text Outline**: Text rendering with black outlines for better readability

### Changed
- **Replaced Placeholder**: Removed TODO comments and placeholder text rendering
- **Visual Parity**: Now matches original baseball manager layout and appearance

## [1.0.3] - 2025-10-20

### Fixed
- **Live Priority Integration**: Implemented `has_live_content()` method to properly integrate with display controller
- **Display Logic**: Plugin now only shows "baseball_live" mode when there are actual live games
- **No More "No Live Games"**: Plugin won't be called when there are no live games to display
- **Mode Filtering**: Added `get_live_modes()` to only show live mode during live priority takeover

## [1.0.2] - 2025-10-19

### Initial
- Initial release with basic baseball scoreboard functionality

