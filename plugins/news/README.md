-----------------------------------------------------------------------------------
### Connect with ChuckBuilds

- Show support on Youtube: https://www.youtube.com/@ChuckBuilds
- Stay in touch on Instagram: https://www.instagram.com/ChuckBuilds/
- Want to chat or need support? Reach out on the ChuckBuilds Discord: https://discord.com/invite/uW36dVAtcT
- Feeling Generous? Support the project:
  - Github Sponsorship: https://github.com/sponsors/ChuckBuilds
  - Buy Me a Coffee: https://buymeacoffee.com/chuckbuilds
  - Ko-fi: https://ko-fi.com/chuckbuilds/ 

-----------------------------------------------------------------------------------

# News Ticker Plugin

A plugin for LEDMatrix that displays scrolling news headlines from RSS feeds including sports news from ESPN, NCAA updates, and custom RSS sources.

## Features

- **Multiple RSS Sources**: ESPN sports feeds, NCAA updates, and custom RSS URLs
- **Scrolling Headlines**: Continuous scrolling ticker display
- **Headline Paging**: Each turn shows as many headlines as can finish scrolling, then the next turn picks up where the last one stopped — headlines aren't cut off part-way through, and the tail of a long feed list still reaches the panel
- **News Source Logos**: Display logos for news sources (ESPN, NFL Network, MLB Network, etc.)
- **Headline Rotation**: Cycle through headlines after multiple viewings
- **Custom Feeds**: Add your own RSS feed URLs
- **Sports Focus**: Pre-configured feeds for NFL, NBA, MLB, NCAA, and more
- **Configurable Display**: Adjustable scroll speed, colors, and timing
- **Background Data Fetching**: Efficient RSS parsing without blocking display

## Configuration

### Global Settings

All scrolling/timing/font settings live under the `global.*` namespace
in [`config_schema.json`](config_schema.json) — that file is the source
of truth. The keys you'll touch most often:

- `global.display_duration`: How long to show the ticker (10–300s, default 30)
- `global.update_interval`: Seconds between RSS fetches (default 300)
- `global.display.scroll_speed`: Pixels per frame (0.5–5.0, default 1.0)
- `global.display.scroll_delay`: Sleep between scroll steps in seconds (0.001–0.1, default 0.01)
- `global.target_fps`: Target frames per second cap (30–200, default 100)
- `global.font_size`: Headline font size (8–20, default 12)
- `global.font_path`: Path to TTF/BDF font (default `assets/fonts/PressStart2P-Regular.ttf`)
- `global.dynamic_duration`: Object — `enabled` (default `true`),
  `min_duration_seconds` (default `30`), `max_duration_seconds`
  (default `300`), `buffer_ratio` (default `0.1`)
- `global.headline_paging`: Object — `enabled` (default `true`),
  `max_headlines_per_page` (default `0` = fit as many as time allows),
  `page_hold_seconds` (default `2.0`), `duration_overrun_allowance`
  (default `0.25`). See [Headline Paging](#headline-paging).
- `global.rotation_enabled`: Enable headline rotation (default `true`; only
  used when `headline_paging.enabled` is `false`)
- `global.rotation_threshold`: Cycles before rotating headlines (1–10, default 3;
  only used when `headline_paging.enabled` is `false`)
- `global.headlines_per_feed`: Headlines to fetch per feed (1–10, default 2)
- `global.background_service.*`: Background fetch tuning —
  `enabled`, `request_timeout`, `max_retries`, `priority`

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

Custom feeds are configured as an array of feed objects, each with a name, URL, enabled status, and optional logo:

```json
{
  "feeds": {
    "custom_feeds": [
      {
        "name": "Tech News",
        "url": "https://example.com/rss.xml",
        "enabled": true,
        "logo": {
          "id": "tech-news-logo",
          "path": "plugins/ledmatrix-news/assets/logos/tech-news-logo.png",
          "uploaded_at": "2024-01-01T00:00:00Z"
        }
      },
      {
        "name": "Local Sports",
        "url": "https://local-sports.com/feed.xml",
        "enabled": true
      }
    ]
  }
}
```

- `name` (required): Feed name (1-100 characters)
- `url` (required): RSS feed URL (must be valid URI)
- `enabled` (optional, default: true): Whether this feed is enabled
- `logo` (optional): Logo file upload object (upload via web UI)

**Feed Management:**
- Enable/disable individual feeds using the `enabled` field
- Feeds are processed in the order they appear in the `custom_feeds` array
- Upload custom logos directly via the web UI (similar to static-image plugin)
- Maximum 50 custom feeds allowed

#### Display Colors

```json
{
  "feeds": {
    "text_color": [255, 255, 255],
    "separator_color": [255, 0, 0]
  }
}
```

#### News Source Logos

```json
{
  "feeds": {
    "show_logos": true,
    "logo_size": 28,
    "custom_feeds": [
      {
        "name": "Tech News",
        "url": "https://example.com/rss.xml",
        "enabled": true,
        "logo": {
          "id": "tech-news-logo",
          "path": "plugins/ledmatrix-news/assets/logos/tech-news-logo.png",
          "uploaded_at": "2024-01-01T00:00:00Z"
        }
      }
    ]
  }
}
```

- `show_logos`: Enable/disable news source logos (default: true)
- `logo_size`: Logo size in pixels (default: display height - 4 pixels)
- `logo`: Optional logo object in each custom feed (upload via web UI file upload widget)

**Logo Behavior:**
- When a logo is present: Logo replaces the "[Feed Name]: " prefix and " • " separator
  - Format: `[Logo] Title`
- When a logo is missing: Shows original format with feed name and separator
  - Format: `[Feed Name]: Title • `

**Logo Resolution Priority:**
1. Integrated logo from feed object (`logo.path` field) - **New format**
2. Predefined feed mappings (ESPN, NFL Network, MLB Network)
3. Inferred from feed name (checks for "espn", "nfl", "mlb", etc.)
4. Normalized feed name as filename (fallback)

**Logo Directory Search Order:**
1. Uploaded logo path from feed object (if present)
2. `assets/news_logos/` (primary location for news source logos)
3. `assets/broadcast_logos/` (fallback for broadcast network logos)
4. Plugin `assets/logos/` (plugin-specific logos)

**Adding Custom Logos:**
1. Upload logo via the web UI file upload widget in the feed configuration
2. The logo will be automatically associated with the feed
3. Logos are stored in the plugin's asset directory

**Default Feed Mappings (Predefined Feeds):**
- ESPN feeds (NFL, NBA, NHL, NCAA, etc.) → `espn.png`
- MLB feed → `mlbn.png`
- NFL feed → `nfln.png`
- Custom feeds → Use uploaded logo or inferred from name

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

- **Feed Source**: Name of the RSS feed (e.g., "NFL", "ESPN") — replaced by the
  feed's logo when one is available
- **Headline**: Full news headline text, never abbreviated
- **Separator**: Visual separator between headlines (shown when there's no logo)

## Headline Paging

Headlines are never shortened, so a full set of feeds can easily produce a strip
of scrolling text several minutes long — far more than the display controller
will keep any one plugin on screen. Paging solves that.

Before each turn the plugin measures how much text can actually finish scrolling
in the time it will be given, fills the strip up to that point, and defers the
rest. When the strip finishes, the next turn resumes at the first headline that
didn't fit. Nothing is drawn that can't be read to the end, and every headline
reaches the panel in a few turns instead of the list's tail never being seen.

The time budget is derived from the scroll rate and the shortest ceiling that
will be enforced — the plugin's own `dynamic_duration.max_duration_seconds` and
the core's `display.dynamic_duration.max_duration_seconds`, whichever is lower.

Tuning:

- `enabled` (default `true`) — set `false` to go back to one long strip
  containing every headline, paced by `rotation_enabled`/`rotation_threshold`
- `max_headlines_per_page` (default `0`) — cap headlines per turn regardless of
  available time; `0` fits as many as will scroll
- `page_hold_seconds` (default `2.0`) — how long the finished strip stays on
  screen before the next page starts, when the ticker isn't rotated away (for
  example when News is the only enabled display mode)
- `duration_overrun_allowance` (default `0.25`) — extra time requested from the
  controller so a scroll running behind its nominal speed still reaches the end.
  Raise it if headlines still get clipped on a heavily loaded Pi.

## Background Service

The plugin uses background data fetching for efficient RSS parsing:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)
- Updates every 5 minutes by default (configurable)

## Adding Custom Feeds

You can add custom RSS feeds by specifying them in the configuration using the array format:

```json
{
  "feeds": {
    "custom_feeds": [
      {
        "name": "My Sports",
        "url": "https://mysportsfeed.com/rss",
        "enabled": true
      },
      {
        "name": "Local News",
        "url": "https://localnews.com/sports.xml",
        "enabled": true
      }
    ]
  }
}
```

**Note:** The old dictionary format (`{"Feed Name": "URL"}`) is deprecated but still supported for backward compatibility. It will be automatically migrated to the new array format on first load. We recommend using the new array format for new configurations.

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
- **Headlines still cut off mid-word**: The scroll is running behind its nominal
  speed. Raise `global.headline_paging.duration_overrun_allowance`, or lower
  `global.display.scroll_speed` so less content is packed into each turn.
- **Only ever seeing the same first few headlines**: Confirm
  `global.headline_paging.enabled` is `true` — with paging off, the legacy
  rotation only advances one headline every `rotation_threshold` cycles.
- **Fewer headlines per turn than expected**: Each turn is sized to the shortest
  enforced duration cap. Raise `global.dynamic_duration.max_duration_seconds`
  *and* the core's `display.dynamic_duration.max_duration_seconds` (default
  180s) — the lower of the two wins.

## Advanced Features

- **Headline Paging**: Sizes each turn to what can actually finish scrolling, then resumes where it left off
- **Headline Rotation**: Legacy fallback that rotates headlines after multiple cycles when paging is disabled
- **Dynamic Duration**: Holds the display until the strip has scrolled to the end, rather than cutting at a fixed time
- **Color Customization**: Configure text and separator colors
- **Font Sizing**: Adjustable font size for readability
- **Feed Prioritization**: Control which feeds are displayed and in what order

## Performance Notes

- The plugin uses the **ScrollHelper API** for high-performance scrolling with numpy array optimization
- **Frame-based scrolling** provides smooth, consistent scrolling at 100+ FPS
- **Dynamic duration** automatically calculates display time based on content width and scroll speed
- RSS parsing happens in background to avoid blocking the display
- Configurable update intervals balance freshness vs. network load
- Caching reduces unnecessary network requests

## Scrolling Implementation

This plugin uses the LEDMatrix **ScrollHelper** API for optimized scrolling:

- **High-FPS Mode**: Automatically enables high frame rate (100+ FPS) for smooth scrolling
- **Frame-Based Scrolling**: Uses `display.scroll_speed` (pixels per frame) and `display.scroll_delay` (seconds per frame) for precise control
- **Dynamic Duration**: Automatically calculates display duration based on content width, ensuring all headlines are shown
- **Numpy Optimization**: Uses fast numpy array slicing for minimal CPU usage
- **Smooth Animation**: Pre-allocated buffers and optimized rendering for consistent performance

### Recommended Configuration

For best performance, use the frame-based scrolling format:

```json
{
  "global": {
    "display": {
      "scroll_speed": 1.0,
      "scroll_delay": 0.01
    },
    "target_fps": 100,
    "dynamic_duration": {
      "enabled": true,
      "min_duration_seconds": 30,
      "max_duration_seconds": 300,
      "buffer_ratio": 0.1
    },
    "headline_paging": {
      "enabled": true,
      "max_headlines_per_page": 0,
      "page_hold_seconds": 2.0,
      "duration_overrun_allowance": 0.25
    }
  }
}
```

This configuration provides:
- 1 pixel per frame scrolling
- 0.01 second delay = 100 FPS effective rate
- Dynamic duration that adjusts to content length
- Smooth, consistent scrolling performance
