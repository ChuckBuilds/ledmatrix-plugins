# Stocks Ticker Plugin

A plugin for LEDMatrix that displays scrolling stock tickers with prices, changes, and optional charts for stocks and cryptocurrencies.

## Features

- **Stock Price Tracking**: Real-time stock prices and changes
- **Cryptocurrency Support**: Bitcoin, Ethereum, and other crypto prices
- **Change Indicators**: Color-coded positive/negative changes
- **Percentage Display**: Show percentage changes alongside dollar amounts
- **Optional Charts**: Toggle chart display for visual price trends
- **Market Data**: Volume and market cap information
- **Configurable Display**: Adjustable scroll speed, colors, and timing
- **Background Data Fetching**: Efficient API calls without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show the ticker (10-300 seconds, default: 30)
- `scroll_speed`: Scrolling speed multiplier (0.5-5, default: 1)
- `scroll_delay`: Delay between scroll steps (0.001-0.1 seconds, default: 0.01)
- `dynamic_duration`: Enable dynamic duration based on content width (default: true)
- `min_duration`: Minimum display duration (10-300 seconds, default: 30)
- `max_duration`: Maximum display duration (30-600 seconds, default: 300)
- `toggle_chart`: Enable chart display toggle (default: false)
- `font_size`: Font size for stock information (8-16, default: 10)

### Stock Settings

#### Stock Symbols

```json
{
  "stocks": {
    "stock_symbols": ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN", "META"]
  }
}
```

#### Display Options

```json
{
  "stocks": {
    "show_change": true,
    "show_percentage": true,
    "show_volume": false,
    "show_market_cap": false,
    "text_color": [255, 255, 255],
    "positive_color": [0, 255, 0],
    "negative_color": [255, 0, 0]
  }
}
```

### Cryptocurrency Settings

#### Enable Crypto Tracking

```json
{
  "crypto": {
    "enabled": true,
    "crypto_symbols": ["BTC", "ETH", "ADA", "SOL", "DOT"]
  }
}
```

#### Crypto Display Options

```json
{
  "crypto": {
    "show_change": true,
    "show_percentage": true,
    "text_color": [255, 215, 0],
    "positive_color": [0, 255, 0],
    "negative_color": [255, 0, 0]
  }
}
```

## Display Format

The stocks ticker displays information in a scrolling format showing:

- **Symbol**: Stock/crypto ticker symbol
- **Price**: Current price (e.g., "$150.25")
- **Change**: Dollar change with color coding (green for positive, red for negative)
- **Percentage**: Percentage change (e.g., "+2.5%")
- **Additional Info**: Volume and market cap (if enabled)

## Stock Symbol Format

Stock symbols should be in uppercase format:

- **AAPL**: Apple Inc.
- **GOOGL**: Alphabet Inc.
- **MSFT**: Microsoft Corporation
- **TSLA**: Tesla Inc.
- **AMZN**: Amazon.com Inc.
- **META**: Meta Platforms Inc.
- **NFLX**: Netflix Inc.

## Cryptocurrency Symbols

Common cryptocurrency symbols:

- **BTC**: Bitcoin
- **ETH**: Ethereum
- **ADA**: Cardano
- **SOL**: Solana
- **DOT**: Polkadot
- **AVAX**: Avalanche
- **MATIC**: Polygon
- **LINK**: Chainlink

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable)
- Up to 5 retries for failed requests
- Priority level 2 (medium priority)
- Updates every minute by default (configurable)

## Data Sources

The plugin can fetch from:

1. **Financial APIs**: Stock and crypto price data (requires API keys in practice)
2. **Market Data Feeds**: Real-time market information
3. **Placeholder Data**: Mock data for demonstration (current implementation)

## Dependencies

This plugin requires the main LEDMatrix installation and uses the cache manager for data storage.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your stock symbols and display preferences
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No data showing**: Check if symbols are valid and APIs are accessible
- **API errors**: Verify API keys and rate limits (for real implementations)
- **Slow scrolling**: Adjust scroll speed and delay settings
- **Network errors**: Check your internet connection and API availability

## Advanced Features

- **Chart Toggle**: Option to display price charts alongside tickers
- **Color Coding**: Visual indicators for price movements
- **Volume Display**: Show trading volume information
- **Market Cap**: Display market capitalization
- **Dual Mode**: Separate display modes for stocks and crypto

## Integration Notes

This plugin is designed to work alongside the stock-news plugin for comprehensive financial display:

- **Stocks Plugin**: Price tickers and market data
- **Stock News Plugin**: Financial headlines and updates
- **Combined Use**: Show tickers while news scrolls in background

## Performance Notes

- The plugin is designed to be lightweight and not impact display performance
- Price data fetching happens in background to avoid blocking
- Configurable update intervals balance freshness vs. API load
- Caching reduces unnecessary network requests

## Chart Display (Future Feature)

When chart toggle is enabled, the plugin can display:

- **Price Charts**: Simple line charts showing price trends
- **Candlestick Charts**: OHLC candlestick representations
- **Volume Bars**: Trading volume visualization
- **Time Periods**: Multiple timeframe options

## API Integration (Future Implementation)

For production use, this plugin would integrate with:

- **Alpha Vantage API**: Stock and forex data
- **CoinGecko API**: Cryptocurrency data
- **Yahoo Finance API**: Financial market data
- **Twelve Data API**: Real-time and historical data

## Example Display

```
AAPL: $150.25 +2.50 (+1.7%)
GOOGL: $2750.80 -15.20 (-0.5%)
BTC: $43250.00 +1250.00 (+3.0%)
ETH: $2850.75 -75.25 (-2.6%)
```
