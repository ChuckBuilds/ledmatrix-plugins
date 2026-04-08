# Stock & Crypto Ticker Plugin

A scrolling ticker for the LEDMatrix display showing live stock and
cryptocurrency prices, percent changes, and optional inline price charts.
Data comes from Yahoo Finance — no API key required.

## Features

- Live stock and crypto prices via Yahoo Finance (no API key)
- Color-coded gain/loss with positive/negative colors
- Optional inline mini chart per symbol (`display.toggle_chart`)
- Two display modes: continuous scroll, or one symbol at a time
- Independent stock and crypto symbol lists
- Per-element font and color customization

## Installation

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Stock Ticker** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure it

## Configuration

The full schema lives in
[`config_schema.json`](config_schema.json) — what you see in the web UI is
generated from it. The most-used keys, with their actual nesting:

### Top level

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch |
| `update_interval` | `600` | Seconds between Yahoo Finance fetches for stocks |

### `display.*` — how the ticker scrolls

| Key | Default | Notes |
|---|---|---|
| `display.display_mode` | `"scroll"` | `"scroll"` or `"switch"` |
| `display.switch_duration` | `15` | Seconds per symbol in switch mode |
| `display.scroll_speed` | `1.0` | Scroll speed multiplier |
| `display.scroll_delay` | `0.02` | Per-step delay (smaller = smoother but more CPU) |
| `display.toggle_chart` | `true` | Show an inline mini-chart per symbol |
| `display.dynamic_duration` | `true` | Let the controller pick a duration based on content width |
| `display.min_duration` | `30` | Floor for dynamic duration (seconds) |
| `display.max_duration` | `300` | Ceiling for dynamic duration (seconds) |
| `display.duration_buffer` | `0.1` | Padding factor on dynamic duration |
| `display.stock_gap` | `32` | Pixels of space between symbols |

### `stocks.*`

| Key | Default | Notes |
|---|---|---|
| `stocks.enabled` | `true` | Enable the stocks list |
| `stocks.symbols` | `["ASTS","SCHD","INTC","NVDA","T","VOO","SMCI"]` | Yahoo Finance ticker symbols |
| `stocks.display_format` | `"{symbol}: ${price} ({change}%)"` | Placeholders: `{symbol}`, `{price}`, `{change}` |

### `crypto.*`

| Key | Default | Notes |
|---|---|---|
| `crypto.enabled` | `false` | Enable the crypto list |
| `crypto.update_interval` | `600` | Seconds between crypto fetches |
| `crypto.symbols` | `["BTC-USD","ETH-USD"]` | Yahoo Finance pair symbols (always end in `-USD` etc.) |
| `crypto.display_format` | `"{symbol}: ${price} ({change}%)"` | Same placeholders as stocks |

### `customization.*`

Per-element font, size, and color overrides for stocks and crypto. Each
of `symbol`, `price`, and `price_delta` has its own `font`, `font_size`,
and color settings. Defaults use `PressStart2P-Regular.ttf` at size 8,
with green for positive deltas and red for negative.

## Symbol format

The plugin uses Yahoo Finance symbols directly:

- **Stocks**: plain ticker, e.g. `AAPL`, `GOOGL`, `MSFT`, `TSLA`,
  `AMZN`, `META`, `NVDA`
- **Crypto**: pair with the quote currency, e.g. `BTC-USD`, `ETH-USD`,
  `SOL-USD`, `DOGE-USD`. Without the `-USD` suffix Yahoo returns no data.

## Pairing with the Stock News plugin

This plugin pairs naturally with the [`stock-news`](../stock-news/)
plugin: prices on one rotation slot, related headlines on another.

## Troubleshooting

**No data showing**
- Confirm the symbols are valid on
  [finance.yahoo.com](https://finance.yahoo.com) — typos return empty data.
- Check the **Logs** tab for HTTP errors. Yahoo occasionally rate-limits;
  raising `update_interval` usually fixes it.

**Scroll feels choppy**
- Lower `display.scroll_delay` (default 0.02) toward 0.01 for smoother
  motion at the cost of CPU.
- Or switch `display.display_mode` to `"switch"` to step through one
  symbol at a time instead of scrolling.

**Chart isn't drawing**
- Set `display.toggle_chart` to `true`.
- Charts need enough horizontal room next to each symbol. On a 64×32
  panel they may be cropped — try a wider chain.

## License

GPL-3.0, same as the LEDMatrix project.
