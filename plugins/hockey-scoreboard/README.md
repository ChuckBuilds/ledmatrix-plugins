# Hockey Scoreboard Plugin

Display live, recent, and upcoming hockey games across NHL, NCAA Men's, and NCAA Women's hockey on your LED matrix.

## Features

- **Multi-League Support**: NHL, NCAA Men's Hockey, NCAA Women's Hockey
- **Live Game Tracking**: Real-time scores, periods, time remaining
- **Recent Games**: View recently completed game results
- **Upcoming Games**: See scheduled games with start times
- **Favorite Teams**: Prioritize your favorite teams across all leagues
- **Power Play Indicators**: Highlight power play situations
- **Shots on Goal**: Optional SOG statistics display
- **Team Logos**: Display team logos when available
- **Background Data Fetching**: Efficient API calls with caching
- **Font Customization**: Override fonts via Web UI

## Requirements

- LEDMatrix 2.0.0+
- Display: Minimum 64x32 pixels (recommended)
- No API key required (uses ESPN public API)
- Internet connection for live data

## Configuration

### Example Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": false,
    "ncaa_womens": false
  },
  "display_modes": {
    "hockey_live": true,
    "hockey_recent": true,
    "hockey_upcoming": true
  },
  "favorite_teams": {
    "nhl": ["TB", "TOR", "BOS"],
    "ncaa_mens": ["BU", "BC"],
    "ncaa_womens": []
  },
  "prioritize_favorites": true,
  "show_shots_on_goal": false,
  "show_powerplay": true,
  "update_interval": 60,
  "display_duration": 15,
  "recent_games_hours": 24,
  "upcoming_games_hours": 72
}
```

### Configuration Options

#### League Selection

- **`leagues.nhl`**: Enable NHL games (default: true)
- **`leagues.ncaa_mens`**: Enable NCAA Men's Hockey (default: false)
- **`leagues.ncaa_womens`**: Enable NCAA Women's Hockey (default: false)

Enable multiple leagues to see games from all selected leagues in rotation.

#### Display Modes

- **`display_modes.hockey_live`**: Show live games in progress (default: true)
- **`display_modes.hockey_recent`**: Show recently completed games (default: true)
- **`display_modes.hockey_upcoming`**: Show upcoming scheduled games (default: true)

#### Favorite Teams

Specify team abbreviations for each league:

```json
"favorite_teams": {
  "nhl": ["TB", "TOR", "BOS", "DET"],
  "ncaa_mens": ["BU", "BC", "MICH"],
  "ncaa_womens": ["WISC", "MINN"]
}
```

**Common NHL Team Abbreviations:**
- TB (Tampa Bay Lightning)
- TOR (Toronto Maple Leafs)
- BOS (Boston Bruins)
- DET (Detroit Red Wings)
- CHI (Chicago Blackhawks)
- NYR (New York Rangers)
- MTL (Montreal Canadiens)
- [See full list in ESPN API or team logos]

**NCAA Team Abbreviations:**
- BU (Boston University)
- BC (Boston College)
- MICH (University of Michigan)
- WISC (University of Wisconsin)
- MINN (University of Minnesota)

#### Display Settings

- **`prioritize_favorites`**: Show favorite team games first (default: true)
- **`show_shots_on_goal`**: Display SOG statistics (default: false)
- **`show_powerplay`**: Highlight power play situations (default: true)
- **`update_interval`**: Data refresh interval in seconds (15-300, default: 60)
- **`display_duration`**: How long to show each game in seconds (5-60, default: 15)

#### Time Windows

- **`recent_games_hours`**: How far back to show recent games (1-168 hours, default: 24)
- **`upcoming_games_hours`**: How far ahead to show upcoming games (1-336 hours, default: 72)

#### Background Service

```json
"background_service": {
  "enabled": true,
  "request_timeout": 30,
  "max_retries": 3,
  "priority": 2
}
```

- **`enabled`**: Use background data fetching (default: true)
- **`request_timeout`**: API timeout in seconds (default: 30)
- **`max_retries`**: Retry attempts on failure (default: 3)
- **`priority`**: Request priority 1-5, where 1 is highest (default: 2)

## Display Modes

### Live Games (`hockey_live`)

Shows games currently in progress with:
- Current score
- Period (P1, P2, P3, OT, OT2, etc.)
- Time remaining in period
- Power play indicator (if enabled)
- Shots on goal (if enabled)

### Recent Games (`hockey_recent`)

Shows completed games from the last X hours with:
- Final score
- Game status ("Final", "Final/OT", "Final/SO")
- Team logos

### Upcoming Games (`hockey_upcoming`)

Shows scheduled games for the next X hours with:
- Game start time
- Venue information
- Team matchup

## Setup Instructions

### 1. Install Plugin

Install from the Plugin Store in the LEDMatrix Web UI:

1. Go to Plugin Store tab
2. Search for "Hockey Scoreboard"
3. Click Install
4. Configure via Plugin Configuration page

### 2. Configure Leagues

Enable the leagues you want to track:

- **NHL Only**: Set `leagues.nhl: true`, others false
- **All Leagues**: Set all to true
- **NCAA Only**: Enable `ncaa_mens` and/or `ncaa_womens`

### 3. Add Favorite Teams

Add your favorite team abbreviations to the `favorite_teams` object for each league. Games involving these teams will be shown first if `prioritize_favorites` is enabled.

### 4. Adjust Display Settings

- Set `display_duration` based on how many games you expect (shorter = more games shown)
- Adjust `update_interval` based on desired freshness (60s recommended for live games)
- Enable/disable display modes based on preference

### 5. Enable Plugin

Make sure `enabled: true` in the configuration and the plugin is activated in the rotation.

## Display Layout

### 64x32 Display (Recommended)

```
┌──────────────────────────────────┐
│ [AWAY]  3  @  2  [HOME]         │
│ ▲▲▲▲▲  Score   Score  ▼▼▼▼▼    │
│         P2 - 15:30               │
│         PP: HOME (5v4)           │
└──────────────────────────────────┘
```

### With Logos

```
┌──────────────────────────────────┐
│ [LOGO] BOS  3-2  TB [LOGO]      │
│        P3 - 5:45                 │
│        SOG: 28-32                │
└──────────────────────────────────┘
```

## Usage Tips

### Optimizing for Your Screen

- **64x32**: Can show full details with logos, SOG, powerplay
- **64x64**: Can show multiple games or larger fonts
- **128x32**: Can show two games side-by-side

### Favorite Team Strategy

1. **Single Team Fan**: Add one team to favorites for focused view
2. **Multi-Team Fan**: Add multiple teams across leagues
3. **Local Teams**: Add your region's teams across all leagues
4. **Rivalry Focus**: Add division rivals to never miss matchups

### Update Interval

- **Live Games (High Activity)**: 30-60 seconds
- **Off Season (Low Activity)**: 120-300 seconds
- **Balance**: 60 seconds (recommended default)

### Display Duration

- **Many Games**: 10 seconds per game
- **Few Games**: 15-20 seconds per game
- **Single Game Focus**: 30+ seconds

## Troubleshooting

**No games showing:**
- Check that at least one league is enabled in config
- Verify the season is active for enabled leagues
- Check `recent_games_hours` and `upcoming_games_hours` settings
- Ensure internet connection is working

**Games not updating:**
- Check `update_interval` setting
- Verify API is responding (check logs)
- Try clearing cache: restart plugin or clear cache manually
- Check background service is enabled

**Favorite teams not showing:**
- Verify team abbreviations are correct (case-sensitive)
- Ensure `prioritize_favorites` is true
- Check that favorite teams have games in current time window

**Logos not displaying:**
- Verify logo assets are available in LEDMatrix installation
- Check `assets/sports/nhl_logos` and `assets/sports/ncaa_logos` directories
- Some NCAA teams may not have logos available

**Power play not showing:**
- Enable `show_powerplay` in config
- Verify ESPN API includes situation data (may not be available for all leagues)

**SOG not accurate:**
- Enable `show_shots_on_goal` in config
- ESPN API may have delayed SOG updates
- Some leagues may not provide SOG data

## Advanced Configuration

### Custom Fonts

Override default fonts via config or Web UI:

```json
"fonts": {
  "team_name": {
    "family": "press_start",
    "size": 10,
    "color": "#FFFFFF"
  },
  "score": {
    "family": "press_start",
    "size": 12,
    "color": "#FFC800"
  },
  "status": {
    "family": "four_by_six",
    "size": 6,
    "color": "#00FF00"
  }
}
```

### Multi-League Strategy

Enable all three leagues for comprehensive coverage:

```json
"leagues": {
  "nhl": true,
  "ncaa_mens": true,
  "ncaa_womens": true
}
```

Games from all leagues will be mixed and sorted by:
1. Live games first
2. Favorite teams (if enabled)
3. Start time

## Data Source

This plugin uses the **ESPN public API** for all hockey data:

- **NHL**: `https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard`
- **NCAA M**: `https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/scoreboard`
- **NCAA W**: `https://site.api.espn.com/apis/site/v2/sports/hockey/womens-college-hockey/scoreboard`

**Note**: No API key required. Please use responsibly and respect ESPN's rate limits.

## Examples

### NHL Only Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": false,
    "ncaa_womens": false
  },
  "favorite_teams": {
    "nhl": ["TB", "TOR", "BOS"]
  },
  "display_modes": {
    "hockey_live": true,
    "hockey_recent": true,
    "hockey_upcoming": false
  },
  "update_interval": 60,
  "display_duration": 15
}
```

### NCAA Men's Only Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": false,
    "ncaa_mens": true,
    "ncaa_womens": false
  },
  "favorite_teams": {
    "ncaa_mens": ["BU", "BC", "MICH", "WISC"]
  },
  "display_modes": {
    "hockey_live": true,
    "hockey_recent": true,
    "hockey_upcoming": true
  },
  "upcoming_games_hours": 168,
  "update_interval": 120
}
```

### All Leagues Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": true,
    "ncaa_womens": true
  },
  "favorite_teams": {
    "nhl": ["TB", "DET"],
    "ncaa_mens": ["MICH"],
    "ncaa_womens": ["WISC"]
  },
  "prioritize_favorites": true,
  "show_shots_on_goal": true,
  "show_powerplay": true,
  "display_modes": {
    "hockey_live": true,
    "hockey_recent": true,
    "hockey_upcoming": true
  }
}
```

## Integration Notes

### Base Classes

This plugin uses LEDMatrix base classes:
- `Hockey` - Base hockey functionality
- `HockeyLive` - Live game display logic
- `SportsRecent` - Recent games display
- `SportsUpcoming` - Upcoming games display

These are imported from the main LEDMatrix installation at `src/base_classes/`.

### Caching

The plugin uses LEDMatrix's `CacheManager` to cache API responses:
- Cache duration: 5 minutes for live data
- Cache key format: `hockey_{league}_{date}`
- Automatic cache invalidation on date change

### Background Service

Uses LEDMatrix's `BackgroundDataService` for:
- Non-blocking API requests
- Automatic retries on failure
- Request prioritization
- Timeout handling

## Performance

### Resource Usage

- **CPU**: Low (background fetching, cached data)
- **Memory**: ~5-10MB for game data
- **Network**: ~1-5 KB per API call per league
- **API Calls**: 3 leagues × 12 calls/hour = 36 calls/hour (max)

### Optimization Tips

1. **Disable Unused Leagues**: Only enable leagues you follow
2. **Increase Update Interval**: Use 120-300s during off-season
3. **Reduce Time Windows**: Lower `recent_games_hours` and `upcoming_games_hours`
4. **Enable Caching**: Keep `background_service.enabled: true`

## License

MIT License - see main LEDMatrix repository for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/ChuckBuilds/ledmatrix-plugins/issues)
- **Documentation**: [LEDMatrix Wiki](https://github.com/ChuckBuilds/LEDMatrix/wiki)
- **Community**: [Discussions](https://github.com/ChuckBuilds/LEDMatrix/discussions)

---

**Version**: 1.0.0  
**Author**: ChuckBuilds  
**Category**: Sports  
**Tags**: hockey, nhl, ncaa, sports, scoreboard, live-scores

