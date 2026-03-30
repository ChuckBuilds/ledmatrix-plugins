# Masters Tournament LED Display Plugin

A high-polish Augusta National Masters Tournament display plugin for LEDMatrix with course imagery, live leaderboards, player stats, hole maps, and maximum Masters branding. Works year-round with engaging off-season content.

## Features

### 14 Display Modes

1. **Leaderboard** - Live tournament standings with scores, positions, and thru indicators (paginated)
2. **Player Cards** - Individual player spotlights with ESPN headshots, country flags, round scores, green jacket count
3. **Hole-by-Hole** - Rotating hole cards with real Augusta National overhead maps
4. **Live Action** - Real-time scoring alerts and leader updates
5. **Course Tour** - Rotating hole maps showcasing all 18 holes at Augusta National
6. **Amen Corner** - Dedicated display for the famous holes 11-13
7. **Featured Holes** - Highlight signature holes (12, 13, 15, 16)
8. **Schedule** - Daily tee times and pairings (paginated)
9. **Past Champions** - Historical Masters winners through 2025 (paginated)
10. **Tournament Stats** - Tournament records and statistics (paginated)
11. **Fun Facts** - 35 real Masters and Augusta National trivia facts with scrolling text
12. **Countdown** - Days until the next Masters Tournament
13. **Field Overview** - Under/over/even par breakdown with leader highlight
14. **Course Overview** - Augusta National front nine / back nine stats and signature holes

### Dynamic Scaling

Automatically adapts to any LED matrix size:
- **32x16**: Minimal layout with 1-2 players, abbreviated names
- **64x32**: Standard layout with 3-4 players, basic stats (recommended)
- **128x64+**: Maximum detail with 5-8 players, full statistics, photos

### Masters Branding

Authentic Augusta National visual identity:
- **Masters green** (#00784A) as primary brand color
- **Gold accents** for leaders
- **Azalea pink** decorative elements
- Masters logo placement
- Green jacket icons
- Course-specific imagery

### Year-Round Operation

- **Tournament Week**: Live leaderboards, player tracking, real-time updates
- **Practice Rounds**: Schedule displays, course tours, player preparation
- **Off-Season**: Past champions, course beauty, tournament countdown

## Installation

### Via Plugin Store (Recommended)

1. Open LEDMatrix Web UI
2. Navigate to **Plugins** → **Plugin Store**
3. Find "Masters Tournament"
4. Click **Install**
5. Configure and enable

### Manual Installation

```bash
cd ~/Github/ledmatrix-plugins/plugins
git clone <repo-url> masters-tournament
cd masters-tournament
pip install -r requirements.txt
```

## Configuration

### Basic Setup

```json
{
  "enabled": true,
  "display_duration": 20,
  "update_interval": 30,
  "mock_data": false,
  "favorite_players": [
    "Scottie Scheffler",
    "Rory McIlroy"
  ]
}
```

### Display Modes Configuration

Enable/disable specific modes and configure their settings:

```json
{
  "display_modes": {
    "leaderboard": {
      "enabled": true,
      "top_n": 10,
      "show_favorites_always": true,
      "duration": 25
    },
    "player_cards": {
      "enabled": true,
      "show_headshots": true,
      "duration_per_player": 15
    },
    "course_tour": {
      "enabled": true,
      "show_animations": true,
      "duration_per_hole": 15,
      "featured_holes": [12, 13, 16]
    }
  }
}
```

### Notifications

Configure alerts and interruptions:

```json
{
  "notifications": {
    "practice_round_alerts": {
      "enabled": true,
      "interrupt_display": true,
      "duration": 15
    },
    "favorite_player_alerts": {
      "enabled": true,
      "interrupt_display": true,
      "duration": 10
    }
  }
}
```

### Branding Options

Customize Masters visual elements:

```json
{
  "branding": {
    "show_masters_logo": true,
    "show_green_jacket": true,
    "show_azaleas": true,
    "color_scheme": "classic"
  }
}
```

## Data Source

This plugin uses the **ESPN Golf API** (free, no API key required):

- **Live Leaderboard**: Updates every 30 seconds during tournament play
- **Player Statistics**: Detailed round-by-round scores
- **Schedule**: Tee times and pairings
- **Player Photos**: Downloaded and cached locally

### Caching Strategy

- **Live tournament**: 30-second cache for leaderboard
- **Practice rounds**: 5-minute cache
- **Off-season**: 1-hour cache for historical data
- **Player photos**: Permanent local cache (download once)

### Mock Data Mode

For testing when the Masters isn't live:

```json
{
  "mock_data": true
}
```

This generates realistic mock leaderboard data with:
- 10 players with authentic names
- Scores ranging from -12 to -3
- Round scores and thru indicators
- Simulated tournament conditions

## Usage Examples

### Tournament Week Setup

Monitor your favorite players during Masters week:

```json
{
  "enabled": true,
  "favorite_players": ["Scottie Scheffler", "Jon Rahm"],
  "display_modes": {
    "leaderboard": {"enabled": true, "duration": 30},
    "player_cards": {"enabled": true, "duration_per_player": 20},
    "live_action": {"enabled": true}
  },
  "update_interval": 30,
  "notifications": {
    "favorite_player_alerts": {
      "enabled": true,
      "interrupt_display": true
    }
  }
}
```

### Off-Season Display

Celebrate Masters history year-round:

```json
{
  "enabled": true,
  "display_modes": {
    "past_champions": {"enabled": true, "duration": 25},
    "course_tour": {"enabled": true, "duration_per_hole": 20},
    "tournament_stats": {"enabled": true}
  },
  "update_interval": 3600
}
```

### Course Showcase

Focus on Augusta National's beauty:

```json
{
  "enabled": true,
  "display_modes": {
    "course_tour": {
      "enabled": true,
      "featured_holes": [11, 12, 13, 16],
      "duration_per_hole": 25
    },
    "amen_corner": {"enabled": true}
  }
}
```

## Vegas Scroll Mode

When Vegas scroll mode is active, the plugin provides:

- Individual player cards for each leaderboard entry
- Hole map cards for all 18 holes
- Past champion cards
- Smooth scrolling integration with other plugins

## Display Size Optimization

### 32x16 (Minimal)
- 1-2 players maximum
- Position, abbreviated name, score
- No country flags or round scores
- 8x8px logos

### 64x32 (Standard)
- 3-4 players
- Position, name, country, score, thru
- 16x16px logos
- Full Masters branding

### 128x64 (Maximum Detail)
- 5-8 players
- Position, name, country, scores, rounds, photos
- 24x24px player headshots
- Detailed statistics
- Enhanced visual elements

## Assets

### Bundled Assets
- Masters logo (simplified, tournament-inspired design)
- Green jacket icon
- Azalea flower icons
- 18 hole map placeholders (auto-generated)

### Downloaded Assets
- Player headshots from ESPN (cached in `assets/masters/players/`)

### Creating Custom Hole Maps

To add custom hole map images:

1. Create PNG images sized 512x512px
2. Name them `hole_01.png` through `hole_18.png`
3. Place in `assets/masters/courses/`
4. Plugin will automatically load and scale them

## Troubleshooting

### No Data Displayed

Check these common issues:

1. **Masters not currently active**: Enable `mock_data: true` for testing
2. **API timeout**: Check network connectivity
3. **Cache issues**: Clear cache via web UI or restart LEDMatrix

### Text Too Small

Adjust display size settings:

```json
{
  "display_duration": 30
}
```

Longer duration allows easier reading of small text.

### Favorite Players Not Showing

Ensure exact name match:

```json
{
  "favorite_players": ["Scottie Scheffler"]
}
```

Check ESPN leaderboard for correct spelling.

## Tournament Schedule

The Masters is typically held:

- **Practice Rounds**: Monday-Wednesday (April 6-8)
- **Tournament**: Thursday-Sunday (April 9-12)

Plugin automatically detects tournament phase and adjusts:
- Update intervals (30s live, 5m practice, 1h off-season)
- Cache duration
- Mode prioritization

## Development

### Testing with Mock Data

```bash
# Enable mock mode in config
cd ~/Github/ledmatrix-plugins/plugins/masters-tournament
# Edit config to set "mock_data": true

# Restart LEDMatrix
sudo systemctl restart ledmatrix

# Monitor logs
tail -f /var/log/ledmatrix/ledmatrix.log
```

### Adding New Display Modes

1. Add mode to `manifest.json` `display_modes` array
2. Add config schema entry in `config_schema.json`
3. Implement rendering in `masters_renderer.py`
4. Add display method in `manager.py`
5. Update `_build_enabled_modes()` mapping

## API Reference

### ESPN Golf API Endpoints

- **Leaderboard**: `https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard`
- **Schedule**: `https://site.api.espn.com/apis/site/v2/sports/golf/pga/schedule`
- **News**: `https://site.api.espn.com/apis/site/v2/sports/golf/pga/news`

No API key required. Rate limits apply (plugin respects with caching).

## Credits

- **Plugin Development**: Claude (Anthropic)
- **Masters Tournament**: Augusta National Golf Club
- **Data Provider**: ESPN Golf API
- **LED Matrix Framework**: LEDMatrix by ChuckBuilds

## License

This plugin is for personal, non-commercial use only. Masters Tournament, Augusta National, and related branding are trademarks of Augusta National, Inc.

## Version History

### 2.0.0
- 14 display modes (added fun facts, countdown, field overview, course overview)
- Real Masters logo from masters.com
- Real Augusta National overhead hole maps for all 18 holes
- 23 real ESPN player headshots
- 16 country flags for player cards
- Phase-aware mode rotation (off-season, pre-tournament, practice, live, evening)
- Paginated displays with page indicator dots
- Broadcast-quality pixel-perfect rendering
- 35 fun facts, 40 past champions through 2025, tournament records database
- Player cards with green jacket count and round-by-round scores

### 1.0.0 (Initial Release)
- 10 display modes
- ESPN API integration
- Dynamic scaling (32x16 to 128x64+)
- Mock data support
- Vegas scroll mode
- Year-round operation
- Configurable notifications
- Masters branding
