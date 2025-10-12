# News Ticker Plugin

A plugin for LEDMatrix that displays scrolling news headlines from RSS feeds including sports news from ESPN, NCAA updates, and custom RSS sources.

## Features

- **Multiple RSS Sources**: ESPN sports feeds, NCAA updates, and custom RSS URLs
- **Scrolling Headlines**: Continuous scrolling ticker display
- **Headline Rotation**: Cycle through headlines after multiple viewings
- **Custom Feeds**: Add your own RSS feed URLs
- **Sports Focus**: Pre-configured feeds for NFL, NBA, MLB, NCAA, and more
- **Configurable Display**: Adjustable scroll speed, colors, and timing
- **Background Data Fetching**: Efficient RSS parsing without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show the ticker (10-300 seconds, default: 30)
- `scroll_speed`: Scrolling speed multiplier (0.5-10, default: 2)
- `scroll_delay`: Delay between scroll steps (0.001-0.1 seconds, default: 0.01)
- `dynamic_duration`: Enable dynamic duration based on content width (default: true)
- `min_duration`: Minimum display duration (10-300 seconds, default: 30)
- `max_duration`: Maximum display duration (30-600 seconds, default: 300)
- `rotation_enabled`: Enable headline rotation (default: true)
- `rotation_threshold`: Cycles before rotating headlines (1-10, default: 3)
- `headlines_per_feed`: Headlines to fetch per feed (1-10, default: 2)
- `font_size`: Font size for headlines (8-20, default: 12)

### Feed Settings

#### Enabled Predefined Feeds

```json
{
  "feeds": {
    "enabled_feeds": ["NFL", "NCAA FB", "NBA", "MLB"]
  }
}
```

#### Custom RSS Feeds

```json
{
  "feeds": {
    "custom_feeds": {
      "Tech News": "https://example.com/rss.xml",
      "Local Sports": "https://local-sports.com/feed.xml"
    }
  }
}
```

#### Display Colors

```json
{
  "feeds": {
    "text_color": [255, 255, 255],
    "separator_color": [255, 0, 0]
  }
}
```

## Available Predefined Feeds

The plugin includes these predefined RSS feeds:

- **MLB**: ESPN MLB News (`http://espn.com/espn/rss/mlb/news`)
- **NFL**: ESPN NFL News (`http://espn.go.com/espn/rss/nfl/news`)
- **NCAA FB**: ESPN NCAA Football News (`https://www.espn.com/espn/rss/ncf/news`)
- **NHL**: ESPN NHL News (`https://www.espn.com/espn/rss/nhl/news`)
- **NBA**: ESPN NBA News (`https://www.espn.com/espn/rss/nba/news`)
- **TOP SPORTS**: ESPN Top Sports News (`https://www.espn.com/espn/rss/news`)
- **BIG10**: Big Ten Conference News (`https://www.espn.com/blog/feed?blog=bigten`)
- **NCAA**: ESPN NCAA News (`https://www.espn.com/espn/rss/ncaa/news`)
- **Other**: Alternative Sports News (`https://www.coveringthecorner.com/rss/current.xml`)

## Display Format

The news ticker displays information in a scrolling format showing:

- **Feed Source**: Name of the RSS feed (e.g., "NFL", "ESPN")
- **Headline**: News headline text (truncated if too long)
- **Separator**: Visual separator between headlines ("---")
- **Timestamp**: When the headline was published (if available)

## Background Service

The plugin uses background data fetching for efficient RSS parsing:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)
- Updates every 5 minutes by default (configurable)

## Adding Custom Feeds

You can add custom RSS feeds by specifying them in the configuration:

```json
{
  "feeds": {
    "custom_feeds": {
      "My Sports": "https://mysportsfeed.com/rss",
      "Local News": "https://localnews.com/sports.xml"
    }
  }
}
```

## Data Processing

- **RSS Parsing**: Uses Python's xml.etree.ElementTree for reliable parsing
- **Text Cleaning**: Removes HTML entities and extra whitespace
- **Length Limiting**: Truncates long headlines for display
- **Caching**: Stores headlines for 10 minutes to avoid excessive API calls

## Dependencies

This plugin requires the main LEDMatrix installation and uses the cache manager for data storage.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your preferred RSS feeds and display options
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No headlines showing**: Check if feeds are enabled and URLs are accessible
- **RSS parsing errors**: Verify feed URLs are valid and return proper XML
- **Slow scrolling**: Adjust scroll speed and delay settings
- **Network errors**: Check your internet connection and RSS server availability

## Advanced Features

- **Headline Rotation**: Automatically rotates through headlines after multiple cycles
- **Dynamic Duration**: Adjusts display time based on content length
- **Color Customization**: Configure text and separator colors
- **Font Sizing**: Adjustable font size for readability
- **Feed Prioritization**: Control which feeds are displayed and in what order

## Performance Notes

- The plugin is designed to be lightweight and not impact display performance
- RSS parsing happens in background to avoid blocking the display
- Configurable update intervals balance freshness vs. network load
- Caching reduces unnecessary network requests
