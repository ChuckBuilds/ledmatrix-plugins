# Stock News Ticker Plugin

A plugin for LEDMatrix that displays scrolling stock-specific news headlines and financial updates from RSS feeds, focused on market news and company announcements.

## Features

- **Stock Symbol Tracking**: Monitor specific stocks for relevant news
- **Financial RSS Feeds**: Aggregate news from financial sources
- **Scrolling Headlines**: Continuous ticker display of stock news
- **Custom Feeds**: Add your own financial RSS feed URLs
- **Symbol Highlighting**: Color-coded display for stock symbols
- **Configurable Display**: Adjustable scroll speed, colors, and filtering
- **Background Data Fetching**: Efficient RSS parsing without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show the ticker (10-300 seconds, default: 30)
- `scroll_speed`: Scrolling speed multiplier (0.5-5, default: 1)
- `scroll_delay`: Delay between scroll steps (0.001-0.1 seconds, default: 0.01)
- `dynamic_duration`: Enable dynamic duration based on content width (default: true)
- `min_duration`: Minimum display duration (10-300 seconds, default: 30)
- `max_duration`: Maximum display duration (30-600 seconds, default: 300)
- `max_headlines_per_symbol`: Headlines per stock symbol (1-5, default: 1)
- `headlines_per_rotation`: Headlines per rotation cycle (1-10, default: 2)
- `font_size`: Font size for headlines (8-16, default: 10)

### Feed Settings

#### Stock Symbols

```json
{
  "feeds": {
    "stock_symbols": ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
  }
}
```

#### Custom RSS Feeds

```json
{
  "feeds": {
    "custom_feeds": {
      "MarketWatch": "https://feeds.marketwatch.com/marketwatch/marketpulse/",
      "Yahoo Finance": "https://feeds.finance.yahoo.com/rss/2.0/headline"
    }
  }
}
```

#### Display Colors

```json
{
  "feeds": {
    "text_color": [0, 255, 0],
    "symbol_color": [255, 255, 0],
    "separator_color": [255, 0, 0]
  }
}
```

## Display Format

The stock news ticker displays information in a scrolling format showing:

- **Stock Symbol**: Ticker symbol in yellow (e.g., "AAPL:")
- **Headline**: News headline text in green
- **Separator**: Visual separator between items ("---")
- **Source**: RSS feed source when available

## Stock Symbol Format

Stock symbols should be in uppercase format:

- **AAPL**: Apple Inc.
- **GOOGL**: Alphabet Inc.
- **MSFT**: Microsoft Corporation
- **TSLA**: Tesla Inc.
- **AMZN**: Amazon.com Inc.
- **META**: Meta Platforms Inc.
- **NFLX**: Netflix Inc.

## Background Service

The plugin uses background data fetching for efficient RSS parsing:

- Requests timeout after 30 seconds (configurable)
- Up to 5 retries for failed requests
- Priority level 2 (medium priority)
- Updates every 5 minutes by default (configurable)

## Data Sources

The plugin can fetch from:

1. **Stock-Specific Feeds**: News APIs for individual stocks (requires API keys in practice)
2. **Financial RSS Feeds**: General financial news RSS feeds
3. **Custom URLs**: User-defined RSS feed URLs

## Dependencies

This plugin requires the main LEDMatrix installation and uses the cache manager for data storage.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your stock symbols and RSS feeds
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No headlines showing**: Check if stock symbols are valid and RSS feeds are accessible
- **RSS parsing errors**: Verify feed URLs return proper XML format
- **Slow scrolling**: Adjust scroll speed and delay settings
- **Network errors**: Check your internet connection and RSS server availability

## Advanced Features

- **Symbol Filtering**: Only show news for tracked stock symbols
- **Multiple Headlines**: Display multiple headlines per symbol
- **Rotation Cycles**: Cycle through headlines in batches
- **Color Customization**: Configure colors for symbols, text, and separators
- **Font Sizing**: Adjustable font size for readability

## Performance Notes

- The plugin is designed to be lightweight and not impact display performance
- RSS parsing happens in background to avoid blocking the display
- Configurable update intervals balance freshness vs. network load
- Caching reduces unnecessary network requests

## Example RSS Feeds

Popular financial RSS feeds you can add:

- **MarketWatch**: `https://feeds.marketwatch.com/marketwatch/marketpulse/`
- **Yahoo Finance**: `https://feeds.finance.yahoo.com/rss/2.0/headline`
- **Reuters Business**: `https://feeds.reuters.com/reuters/businessNews`
- **CNBC**: `https://www.cnbc.com/id/100003114/device/rss/rss.html`
- **Bloomberg**: `https://feeds.bloomberg.com/markets/news.rss`

## Integration Notes

This plugin is designed to work alongside the main stocks plugin for comprehensive financial display:

- **Stock News Plugin**: Headlines and company updates
- **Stocks Plugin**: Price tickers and charts
- **Combined Use**: Show news headlines while stocks cycle in background
