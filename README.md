# LEDMatrix Official Plugins

Official plugin registry for [LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix).


📖 See individual plugin READMEs for detailed setup instructions.

## Available Plugins

| Plugin | Description | Category | Version | Branch |
|--------|-------------|----------|---------|--------|
| [Hello World](plugins/hello-world) | A simple test plugin that displays a customizable message | Demo | 1.0.0 | main |
| [Simple Clock](plugins/clock-simple) | A simple clock display with current time and date | Time | 1.0.0 | main |
| [Weather Display](plugins/weather) | Current weather, hourly & daily forecasts from OpenWeatherMap | Weather | 1.0.0 | simple-plugins |
| [Static Image Display](plugins/static-image) | Display static images with scaling and transparency support | Media | 1.0.0 | simple-plugins |
| [Scrolling Text Display](plugins/text-display) | Display static or scrolling text with customizable fonts | Text | 1.0.0 | simple-plugins |
| [Of The Day](plugins/of-the-day) | Daily rotating content (Word, Bible Verse, etc.) | Content | 1.0.0 | simple-plugins |
| [Music Player](plugins/music) | Now Playing from Spotify or YouTube Music with album art | Media | 1.0.0 | simple-plugins |
| [Google Calendar](plugins/calendar) | Display upcoming events from Google Calendar | Time | 1.0.0 | simple-plugins |
| [Hockey Scoreboard](plugins/hockey-scoreboard) | Live, recent, and upcoming games: NHL, NCAA M/W Hockey | Sports | 1.0.0 | sports-plugins |

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
  -d '{"plugin_id": "clock-simple"}'
```

## Quick Start

### Using the Plugin Store

The easiest way to install plugins is through the built-in Plugin Store in your LEDMatrix web interface. The store automatically fetches the latest plugins from this registry.

### Manual Installation

You can also install plugins manually by cloning this repository and copying plugin folders to your LEDMatrix installation:

```bash
# Clone this repository
git clone https://github.com/ChuckBuilds/ledmatrix-plugins.git

# Copy a plugin to your LEDMatrix plugins directory
cp -r ledmatrix-plugins/plugins/clock-simple /path/to/LEDMatrix/plugins/
```

## Submitting Plugins

See [SUBMISSION.md](SUBMISSION.md) for guidelines on submitting your plugin to the official registry.

## Creating Plugins

See the main [LEDMatrix Plugin Developer Guide](https://github.com/ChuckBuilds/LEDMatrix/wiki/Plugin-Development) or check out the existing plugins in this repository as examples.

## Plugin Categories

- **Time**: Clocks, timers, countdowns, calendars
- **Weather**: Forecasts, current conditions, hourly/daily forecasts
- **Media**: Music players, images, video displays
- **Text**: Scrolling text, messages, announcements
- **Content**: Daily content, quotes, verses
- **Sports**: Scoreboards, schedules, stats *(coming in Phase 2)*
- **Finance**: Stocks, crypto, market data *(coming in Phase 3)*
- **Demo**: Example and test plugins

## Plugin Structure

Each plugin in this repository follows a standard structure:

```
plugin-name/
├── manifest.json       # Plugin metadata
├── manager.py          # Main plugin class
├── config_schema.json  # Configuration schema
├── requirements.txt    # Python dependencies
└── README.md          # Plugin documentation
```

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

## Stats

- **Total Plugins**: 9
- **Categories**: 7 (Demo, Time, Weather, Media, Text, Content, Sports)
- **Verified Plugins**: 9
- **Latest Release**: Phase 2 - Sports Plugins (Oct 2025)

---

Made with ❤️ for the LEDMatrix community
