# LEDMatrix Official Plugins

> Official plugin repository for [LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix) &middot; [Installation](#-quick-install) &middot; [Documentation](#-for-maintainers) &middot; [Support](#-support--community)

---

## Quick Install

**Web Interface (Recommended):**
1. Open `http://your-pi-ip:5000`
2. Go to **Plugin Store** tab
3. Browse & click **Install**

**API:**
```bash
curl -X POST http://your-pi-ip:5050/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"plugin_id": "football-scoreboard"}'
```

---

## Available Plugins

### Sports (8)

| Plugin | Description |
|--------|-------------|
| [Football Scoreboard](./plugins/football-scoreboard/) | NFL & NCAA Football live scores, down/distance, possession |
| [Hockey Scoreboard](./plugins/hockey-scoreboard/) | NHL & NCAA Hockey live scores and schedules |
| [Basketball Scoreboard](./plugins/basketball-scoreboard/) | NBA, NCAA & WNBA live scores and schedules |
| [Baseball Scoreboard](./plugins/baseball-scoreboard/) | MLB, MiLB & NCAA Baseball live scores |
| [Soccer Scoreboard](./plugins/soccer-scoreboard/) | Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS |
| [Odds Ticker](./plugins/odds-ticker/) | Betting odds & lines across NFL, NBA, MLB, NCAA |
| [Sports Leaderboard](./plugins/ledmatrix-leaderboard/) | League standings, rankings, conference records |
| [Olympics Countdown](./plugins/olympics/) | Countdown to next Olympics with live medal counts |

### Financial (2)

| Plugin | Description |
|--------|-------------|
| [Stocks Ticker](./plugins/ledmatrix-stocks/) | Real-time stock & crypto prices with charts |
| [Stock News](./plugins/stock-news/) | Financial headlines from RSS feeds |

### Time & Calendar (3)

| Plugin | Description |
|--------|-------------|
| [Simple Clock](./plugins/clock-simple/) | Time and date display |
| [7-Segment Clock](./plugins/7-segment-clock/) | Retro-style 7-segment clock with customizable colors |
| [Google Calendar](./plugins/calendar/) | Upcoming events from Google Calendar |

### Weather (1)

| Plugin | Description |
|--------|-------------|
| [Weather Display](./plugins/ledmatrix-weather/) | Current conditions, hourly & daily forecasts via OpenWeatherMap |

### Media (2)

| Plugin | Description |
|--------|-------------|
| [Music Player](./plugins/ledmatrix-music/) | Now playing with album art (Spotify & YouTube Music) |
| [Static Image Display](./plugins/static-image/) | Image display with scaling and transparency |

### Content (2)

| Plugin | Description |
|--------|-------------|
| [News Ticker](./plugins/news/) | RSS news headlines from ESPN, NCAA, custom sources |
| [Of The Day](./plugins/of-the-day/) | Daily quotes, Bible verses, word of the day |

### Integrations (1)

| Plugin | Description |
|--------|-------------|
| [MQTT Notifications](./plugins/mqtt-notifications/) | HomeAssistant notifications via MQTT |

### Custom (2)

| Plugin | Description |
|--------|-------------|
| [Flight Tracker](./plugins/ledmatrix-flights/) | Real-time ADS-B aircraft tracking with map display |
| [Countdown Display](./plugins/countdown/) | Customizable countdowns for birthdays, events, holidays |

### Holiday (1)

| Plugin | Description |
|--------|-------------|
| [Christmas Countdown](./plugins/christmas-countdown/) | Festive countdown with Christmas tree display |

### Social (1)

| Plugin | Description |
|--------|-------------|
| [YouTube Stats](./plugins/youtube-stats/) | Channel subscriber count, total views |

### Text (1)

| Plugin | Description |
|--------|-------------|
| [Scrolling Text](./plugins/text-display/) | Custom scrolling/static text with configurable fonts and colors |

### System (1)

| Plugin | Description |
|--------|-------------|
| [Web UI Info](./plugins/web-ui-info/) | Displays web UI URL for device access |

### Development (1)

| Plugin | Description |
|--------|-------------|
| [Hello World](./plugins/hello-world/) | Plugin development example and starter template |

---

## Installation & Usage

### Plugin Store (Recommended)

The **Plugin Store** in the LEDMatrix web interface automatically fetches the latest plugins from this registry:
- Browse and search plugins
- One-click installation
- Automatic updates
- Configuration management

### Manual Installation

Clone this repository and copy the plugin you want:

```bash
git clone https://github.com/ChuckBuilds/ledmatrix-plugins.git
cp -r ledmatrix-plugins/plugins/football-scoreboard /path/to/LEDMatrix/plugin-repos/
```

> **Note:** See individual plugin README files for detailed setup instructions and configuration.

---

## Installing 3rd Party Plugins

LEDMatrix supports installing plugins from any GitHub repository, not just this registry.

### Via Plugin Manager Tab

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Navigate to **Plugin Manager** tab
3. Scroll to **"Install from GitHub"** section

### Single Plugin Installation

1. Enter the GitHub repository URL (e.g., `https://github.com/user/ledmatrix-my-plugin`)
2. Optionally specify a branch
3. Click **Install**

### Registry/Monorepo Installation

1. Enter a registry repository URL (e.g., `https://github.com/user/their-plugins`)
2. Click **Load Registry** to browse available plugins
3. Click **Install** on any plugin

### Important Notes

- 3rd party plugins show a **Custom** badge in the web UI
- Review plugin code before installing from untrusted sources
- Manual updates required unless the repository is saved

---

## For Maintainers

### Repository Structure

```
ledmatrix-plugins/
  plugins.json           # Plugin registry (auto-updated from manifests)
  update_registry.py     # Sync registry versions from local manifests
  plugins/
    football-scoreboard/ # Each plugin has its own directory
      manifest.json
      manager.py
      config_schema.json
      requirements.txt
      README.md
    hockey-scoreboard/
    ...
```

### Setup

Install the git pre-commit hook so `plugins.json` stays in sync automatically:

```bash
cp scripts/pre-commit .git/hooks/pre-commit
```

### Updating Plugin Versions

After making changes to a plugin:

1. Bump `version` in the plugin's `manifest.json`
2. Commit — the pre-commit hook automatically syncs `plugins.json`

```bash
# Manual alternative (if hook isn't installed):
python update_registry.py           # Update plugins.json
python update_registry.py --dry-run # Preview changes
```

---

## 3rd Party Plugin Development

### Required Files

Your plugin repository must contain:
- **`manifest.json`** — Plugin metadata (required)
- **Entry point file** — Python file with your plugin class (default: `manager.py`)
- **Plugin class** — Must inherit from `BasePlugin` and implement `update()` and `display()`

Optional but recommended:
- `requirements.txt` — Python dependencies
- `config_schema.json` — Configuration validation schema (JSON Schema Draft-7)
- `README.md` — User documentation

### Manifest Requirements

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique plugin identifier |
| `name` | string | Human-readable name |
| `class_name` | string | Plugin class name (must match class in entry point) |
| `display_modes` | array | Display mode names |

See the [manifest schema](https://github.com/ChuckBuilds/LEDMatrix/blob/main/schema/manifest_schema.json) for complete field reference.

### Getting Started

1. Review the [Plugin Development Guide](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/PLUGIN_DEVELOPMENT_GUIDE.md)
2. Start with the [Hello World plugin](./plugins/hello-world/) as a template
3. Test with the emulator: `python run.py --emulator`

### Submitting a Plugin

To add your plugin to the official registry:

1. Open an issue on this repository or reach out on [Discord](https://discord.gg/uW36dVAtcT)
2. Include: repository URL, description, screenshots/video
3. After review, your plugin will be added to the registry

See [SUBMISSION.md](SUBMISSION.md) for full guidelines.

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

## Support & Community

- **Discord**: [Join the community](https://discord.gg/uW36dVAtcT)
- **Issues**: [Report plugin issues](https://github.com/ChuckBuilds/ledmatrix-plugins/issues)
- **LEDMatrix**: [Main repository](https://github.com/ChuckBuilds/LEDMatrix)

### Connect with ChuckBuilds

- **YouTube**: [@ChuckBuilds](https://www.youtube.com/@ChuckBuilds)
- **Instagram**: [@ChuckBuilds](https://www.instagram.com/ChuckBuilds/)
- **Support the Project**:
  - [GitHub Sponsorship](https://github.com/sponsors/ChuckBuilds)
  - [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds)
  - [Ko-fi](https://ko-fi.com/chuckbuilds/)

---

> **Note**: Plugins are actively developed. Report bugs or feature requests on the [issues page](https://github.com/ChuckBuilds/ledmatrix-plugins/issues).
