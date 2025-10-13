# Plugin Migration Notice

## Important: Plugin Repository Structure Changed

As of October 2025, all LEDMatrix plugins have been migrated from a monorepo structure to individual repositories for better version management and independent development.

### What Changed?

**Before:**
```
https://github.com/ChuckBuilds/ledmatrix-plugins
├── plugins/
│   ├── hello-world/
│   ├── clock-simple/
│   ├── weather/
│   └── ...
```

**After:**
```
https://github.com/ChuckBuilds/ledmatrix-hello-world
https://github.com/ChuckBuilds/ledmatrix-clock-simple
https://github.com/ChuckBuilds/ledmatrix-weather
...
```

### Why the Change?

1. **Independent Versioning** - Each plugin can now have its own release cycle
2. **Easier Maintenance** - Contributors can focus on specific plugins
3. **Better Discovery** - Plugins are more discoverable on GitHub
4. **Flexible Development** - Different plugins can evolve at different paces

### Impact on Users

**Existing Installations:**
- ✅ Your installed plugins will continue to work
- ✅ The plugin system automatically handles the new structure
- ✅ Updates will be downloaded from individual repositories

**New Installations:**
- ✅ Plugins are now installed from individual repositories
- ✅ The plugin store (`plugins.json`) has been updated
- ✅ Installation process remains the same through the web interface

### For Developers

**Contributing to Plugins:**
- Each plugin now has its own repository
- Submit pull requests to the specific plugin repository
- See individual plugin READMEs for contribution guidelines

**Creating New Plugins:**
- Use any existing plugin as a template
- Follow the same plugin structure and manifest format
- Submit to the plugin registry when ready

### Plugin URLs

All plugin repositories follow the naming convention:
```
https://github.com/ChuckBuilds/ledmatrix-{plugin-id}
```

| Plugin ID | Repository URL |
|-----------|----------------|
| hello-world | https://github.com/ChuckBuilds/ledmatrix-hello-world |
| clock-simple | https://github.com/ChuckBuilds/ledmatrix-clock-simple |
| weather | https://github.com/ChuckBuilds/ledmatrix-weather |
| static-image | https://github.com/ChuckBuilds/ledmatrix-static-image |
| text-display | https://github.com/ChuckBuilds/ledmatrix-text-display |
| of-the-day | https://github.com/ChuckBuilds/ledmatrix-of-the-day |
| music | https://github.com/ChuckBuilds/ledmatrix-music |
| calendar | https://github.com/ChuckBuilds/ledmatrix-calendar |
| hockey-scoreboard | https://github.com/ChuckBuilds/ledmatrix-hockey-scoreboard |
| football-scoreboard | https://github.com/ChuckBuilds/ledmatrix-football-scoreboard |
| basketball-scoreboard | https://github.com/ChuckBuilds/ledmatrix-basketball-scoreboard |
| baseball-scoreboard | https://github.com/ChuckBuilds/ledmatrix-baseball-scoreboard |
| soccer-scoreboard | https://github.com/ChuckBuilds/ledmatrix-soccer-scoreboard |
| odds-ticker | https://github.com/ChuckBuilds/ledmatrix-odds-ticker |
| leaderboard | https://github.com/ChuckBuilds/ledmatrix-leaderboard |
| news | https://github.com/ChuckBuilds/ledmatrix-news |
| stock-news | https://github.com/ChuckBuilds/ledmatrix-stock-news |
| stocks | https://github.com/ChuckBuilds/ledmatrix-stocks |

### License

All plugins remain under **GPL-3.0 License**.

### Questions?

- Main project: https://github.com/ChuckBuilds/LEDMatrix
- Documentation: https://github.com/ChuckBuilds/LEDMatrix/wiki
- Issues: Report to specific plugin repositories or main LEDMatrix repo

---

**Migration Date:** October 13, 2025  
**Status:** ✅ Complete  
**Breaking Changes:** None - fully backward compatible

