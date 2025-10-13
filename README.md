# LEDMatrix Official Plugins Registry

🎉 **Complete Plugin Ecosystem** - Official plugin registry for [LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix).

> **⚠️ IMPORTANT:** As of October 2025, all plugins have been migrated to **individual repositories** for better version management. See [PLUGIN_MIGRATION_NOTICE.md](PLUGIN_MIGRATION_NOTICE.md) for details.

## 🚀 What's New

**REPOSITORY MIGRATION COMPLETE!** All 18 LEDMatrix plugins are now in individual GitHub repositories, each with independent versioning and release cycles. The plugin store (`plugins.json`) has been updated to point to the new repositories.

📖 See individual plugin repositories for detailed setup instructions and to contribute.

## 🔥 Featured Plugins

### 🏆 Sports Suite (6 Plugins)
Multi-league scoreboards with live, recent, and upcoming games across all major sports.

| Plugin | Description | Leagues | Category |
|--------|-------------|---------|----------|
| **[Football Scoreboard](https://github.com/ChuckBuilds/ledmatrix-football-scoreboard)** | NFL & NCAA Football | NFL, NCAA FB | Sports |
| **[Hockey Scoreboard](https://github.com/ChuckBuilds/ledmatrix-hockey-scoreboard)** | NHL & NCAA Hockey | NHL, NCAA M/W | Sports |
| **[Basketball Scoreboard](https://github.com/ChuckBuilds/ledmatrix-basketball-scoreboard)** | NBA & NCAA Basketball | NBA, NCAA M/W, WNBA | Sports |
| **[Baseball Scoreboard](https://github.com/ChuckBuilds/ledmatrix-baseball-scoreboard)** | MLB & NCAA Baseball | MLB, MiLB, NCAA | Sports |
| **[Soccer Scoreboard](https://github.com/ChuckBuilds/ledmatrix-soccer-scoreboard)** | Global Soccer Leagues | Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS | Sports |
| **[Odds Ticker](https://github.com/ChuckBuilds/ledmatrix-odds-ticker)** | Betting Odds & Lines | NFL, NBA, MLB, NCAA | Sports |

### 💰 Financial Suite (3 Plugins)
Complete stock market and financial information display.

| Plugin | Description | Features | Category |
|--------|-------------|----------|----------|
| **[Stocks Ticker](https://github.com/ChuckBuilds/ledmatrix-stocks)** | Stock & Crypto Prices | Real-time prices, charts, volume | Financial |
| **[Stock News](https://github.com/ChuckBuilds/ledmatrix-stock-news)** | Financial Headlines | Stock-specific news, RSS feeds | Financial |
| **[Sports Leaderboard](https://github.com/ChuckBuilds/ledmatrix-leaderboard)** | League Standings | Rankings, records, conference standings | Sports |

### 📱 Content & Utility (9 Plugins)
Essential displays for time, weather, media, and daily content.

| Plugin | Description | Category |
|--------|-------------|----------|
| **[Simple Clock](https://github.com/ChuckBuilds/ledmatrix-clock-simple)** | Time and date display | Time |
| **[Weather Display](https://github.com/ChuckBuilds/ledmatrix-weather)** | Weather forecasts and conditions | Weather |
| **[Static Image Display](https://github.com/ChuckBuilds/ledmatrix-static-image)** | Image slideshow with effects | Media |
| **[Scrolling Text Display](https://github.com/ChuckBuilds/ledmatrix-text-display)** | Custom text and messages | Text |
| **[Of The Day](https://github.com/ChuckBuilds/ledmatrix-of-the-day)** | Daily quotes and verses | Content |
| **[Music Player](https://github.com/ChuckBuilds/ledmatrix-music)** | Now playing with album art | Media |
| **[Google Calendar](https://github.com/ChuckBuilds/ledmatrix-calendar)** | Event calendar display | Time |
| **[News Ticker](https://github.com/ChuckBuilds/ledmatrix-news)** | RSS news headlines | Content |
| **[Hello World](https://github.com/ChuckBuilds/ledmatrix-hello-world)** | Plugin development example | Demo |

## Installation

All plugins can be installed through the LEDMatrix web interface:

1. Open web interface (http://your-pi-ip:5050)
2. Go to Plugin Store tab
3. Browse or search for plugins
4. Click Install

Or via API:
```bash
curl -X POST http://your-pi-ip:5050/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"plugin_id": "football-scoreboard"}'
```

## Quick Start

### Using the Plugin Store

The easiest way to install plugins is through the built-in Plugin Store in your LEDMatrix web interface. The store automatically fetches the latest plugins from this registry and provides a simple one-click installation process.

### Manual Installation

You can also install plugins manually by cloning individual plugin repositories:

```bash
# Clone a specific plugin repository
git clone https://github.com/ChuckBuilds/ledmatrix-football-scoreboard.git

# Copy to your LEDMatrix plugins directory
cp -r ledmatrix-football-scoreboard /path/to/LEDMatrix/plugins/
```

**Note:** Each plugin is now in its own repository. See [PLUGIN_MIGRATION_NOTICE.md](PLUGIN_MIGRATION_NOTICE.md) for the complete list of repository URLs.

## Plugin Categories

- **🏆 Sports** (6): Multi-league scoreboards, odds, and leaderboards
- **💰 Financial** (3): Stocks, crypto, and financial news
- **⏰ Time** (2): Clocks, timers, countdowns, calendars
- **🌤️ Weather** (1): Forecasts, current conditions, hourly/daily forecasts
- **📱 Media** (2): Music players, images, video displays
- **📝 Text** (1): Scrolling text, messages, announcements
- **📖 Content** (2): Daily content, quotes, news feeds
- **🎮 Demo** (1): Example and test plugins

## Repository Structure

This repository serves as the **official plugin registry** for LEDMatrix. It contains:

- **plugins.json** - The plugin registry with metadata and download URLs
- **Documentation** - Guides for users and plugin developers
- **Submission guidelines** - How to add your plugin to the registry

**Plugin code** is now maintained in individual repositories. See the links above to access each plugin's source code.

## Key Features

### 🎛️ **Plugin System Integration**
- All plugins inherit from `BasePlugin` for consistent behavior
- Web UI integration for configuration and management
- Font manager integration with customizable fonts per plugin
- Background service integration for efficient data fetching

### ⚙️ **Configuration Management**
- JSON schema validation for all plugin configurations
- Per-plugin settings with sensible defaults
- Web interface configuration through Plugin Settings tab
- Environment variable support for sensitive settings

### 📊 **Display Modes**
- **Live**: Real-time game scores and data
- **Recent**: Recently completed games and results
- **Upcoming**: Scheduled games and events
- **Ticker**: Continuous scrolling displays

### 🔄 **Background Services**
- Non-blocking API calls for sports data, weather, stocks
- Intelligent caching to minimize network requests
- Configurable update intervals per plugin
- Retry logic and error handling

## Submitting Plugins

Want to add your plugin to the official registry? See [SUBMISSION.md](SUBMISSION.md) for guidelines.

## Creating Plugins

See the main [LEDMatrix Plugin Developer Guide](https://github.com/ChuckBuilds/LEDMatrix/wiki/Plugin-Development) or check out the [Hello World plugin](https://github.com/ChuckBuilds/ledmatrix-hello-world) as a starting template.

## Documentation

- **[Plugin Registry Setup Guide](docs/PLUGIN_REGISTRY_SETUP_GUIDE.md)** - How to maintain this registry
- **[Plugin Store User Guide](docs/PLUGIN_STORE_USER_GUIDE.md)** - Using the plugin store
- **[Plugin Store Implementation](docs/PLUGIN_STORE_IMPLEMENTATION_SUMMARY.md)** - Technical details
- **[Quick Reference](docs/PLUGIN_STORE_QUICK_REFERENCE.md)** - Quick command reference

## Contributing

Contributions are welcome! Please read [SUBMISSION.md](SUBMISSION.md) for details on how to submit plugins, and [VERIFICATION.md](VERIFICATION.md) for the review process.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Support

- Open an issue in this repository for plugin-related questions
- Visit the main [LEDMatrix repository](https://github.com/ChuckBuilds/LEDMatrix) for general support
- Check the [Wiki](https://github.com/ChuckBuilds/LEDMatrix/wiki) for documentation

## 📈 Stats

- **🏆 Total Plugins**: 18
- **📂 Categories**: 8 (Sports, Financial, Time, Weather, Media, Text, Content, Demo)
- **✅ Verified Plugins**: 18
- **🚀 Latest Release**: Complete Migration (18/18 plugins) - October 2025
- **⭐ Most Popular**: Sports plugins (6 multi-league scoreboards)

---

**Made with ❤️ for the LEDMatrix community**

*🎉 This repository represents a complete architectural transformation from monolithic managers to a modern, extensible plugin ecosystem!*
