# Plugin Code Location

## 🔄 Repository Structure Changed

As of **October 2025**, all plugin code has been migrated to **individual GitHub repositories** for better version management and independent development.

## 📦 Where to Find Plugin Code

Plugin code is no longer stored in this repository. Each plugin now has its own dedicated repository:

### All Plugin Repositories

Browse all LEDMatrix plugins at: **https://github.com/ChuckBuilds?tab=repositories&q=ledmatrix-**

### Individual Plugin Links

| Plugin | Repository |
|--------|------------|
| Hello World | https://github.com/ChuckBuilds/ledmatrix-hello-world |
| Simple Clock | https://github.com/ChuckBuilds/ledmatrix-clock-simple |
| Weather Display | https://github.com/ChuckBuilds/ledmatrix-weather |
| Static Image | https://github.com/ChuckBuilds/ledmatrix-static-image |
| Text Display | https://github.com/ChuckBuilds/ledmatrix-text-display |
| Of The Day | https://github.com/ChuckBuilds/ledmatrix-of-the-day |
| Music Player | https://github.com/ChuckBuilds/ledmatrix-music |
| Calendar | https://github.com/ChuckBuilds/ledmatrix-calendar |
| Hockey Scoreboard | https://github.com/ChuckBuilds/ledmatrix-hockey-scoreboard |
| Football Scoreboard | https://github.com/ChuckBuilds/ledmatrix-football-scoreboard |
| Basketball Scoreboard | https://github.com/ChuckBuilds/ledmatrix-basketball-scoreboard |
| Baseball Scoreboard | https://github.com/ChuckBuilds/ledmatrix-baseball-scoreboard |
| Soccer Scoreboard | https://github.com/ChuckBuilds/ledmatrix-soccer-scoreboard |
| Odds Ticker | https://github.com/ChuckBuilds/ledmatrix-odds-ticker |
| Leaderboard | https://github.com/ChuckBuilds/ledmatrix-leaderboard |
| News Ticker | https://github.com/ChuckBuilds/ledmatrix-news |
| Stock News | https://github.com/ChuckBuilds/ledmatrix-stock-news |
| Stocks Ticker | https://github.com/ChuckBuilds/ledmatrix-stocks |

## 📝 What This Repository Contains

This repository (`ledmatrix-plugins`) now serves as the **official plugin registry**:

- **plugins.json** - Registry of all available plugins
- **Documentation** - Guides and references
- **Submission guidelines** - How to add your plugin

## 🚀 Installing Plugins

Plugins are automatically downloaded from their individual repositories when you:
1. Use the LEDMatrix web interface Plugin Store
2. Use the LEDMatrix API to install plugins

The system automatically fetches the latest version from each plugin's GitHub repository.

## 🛠️ Contributing to Plugins

To contribute to a plugin:
1. Visit the plugin's individual repository (links above)
2. Fork the repository
3. Make your changes
4. Submit a pull request to that plugin's repository

## 📚 More Information

- Main README: [../README.md](../README.md)
- Migration Notice: [../PLUGIN_MIGRATION_NOTICE.md](../PLUGIN_MIGRATION_NOTICE.md)
- Plugin Development Guide: https://github.com/ChuckBuilds/LEDMatrix/wiki/Plugin-Development

## ⚡ Quick Reference

**Old structure:**
```
ledmatrix-plugins/
└── plugins/
    ├── weather/
    ├── clock-simple/
    └── ...
```

**New structure:**
```
Individual repositories:
- https://github.com/ChuckBuilds/ledmatrix-weather
- https://github.com/ChuckBuilds/ledmatrix-clock-simple
- ...
```

This change enables:
- ✅ Independent versioning per plugin
- ✅ Easier contributions and maintenance
- ✅ Better discoverability
- ✅ Flexible development cycles

