# Plugin Store - Quick Reference Card

## For Users

### Install Plugin from Store
```bash
# Web UI: Plugin Manager tab → Plugin Store section → Search → Click Install
# API:
curl -X POST http://pi:5000/api/v3/plugins/install \
  -d '{"plugin_id": "clock-simple"}'
```

### Install Plugin from GitHub URL ⭐
```bash
# Web UI: Plugin Manager tab → "Install from GitHub" section → Paste URL
# API:
curl -X POST http://pi:5000/api/v3/plugins/install-from-url \
  -d '{"repo_url": "https://github.com/user/ledmatrix-plugin"}'
```

### Search Plugins
```bash
# Web UI: Use search bar and filters
# API:
curl "http://pi:5000/api/v3/plugins/store/search?q=hockey&category=sports"
```

### List Installed
```bash
curl "http://pi:5000/api/v3/plugins/installed"
```

### Enable/Disable
```bash
curl -X POST http://pi:5000/api/v3/plugins/toggle \
  -d '{"plugin_id": "clock-simple", "enabled": true}'
```

### Update Plugin
```bash
curl -X POST http://pi:5000/api/v3/plugins/update \
  -d '{"plugin_id": "clock-simple"}'
```

### Uninstall
```bash
curl -X POST http://pi:5000/api/v3/plugins/uninstall \
  -d '{"plugin_id": "clock-simple"}'
```

## For Developers

### Share Your Plugin
```markdown
1. Create plugin following manifest structure
2. Push to GitHub: https://github.com/you/ledmatrix-your-plugin
3. Share URL with users:
   "Install my plugin from: https://github.com/you/ledmatrix-your-plugin"
4. Users paste URL in "Install from URL" section
```

### Python Usage
```python
from src.plugin_system.store_manager import PluginStoreManager

store = PluginStoreManager()

# Install from URL
result = store.install_from_url('https://github.com/user/plugin')
if result['success']:
    print(f"Installed: {result['plugin_id']}")

# Install from registry
store.install_plugin('clock-simple')

# Search
results = store.search_plugins(query='hockey', category='sports')

# List installed
for plugin_id in store.list_installed_plugins():
    info = store.get_installed_plugin_info(plugin_id)
    print(f"{plugin_id}: {info['name']}")
```

## Required Plugin Structure

```
my-plugin/
├── manifest.json       # Required: Plugin metadata
├── manager.py          # Required: Plugin class
├── requirements.txt    # Optional: Python dependencies
├── config_schema.json  # Optional: Config validation
├── README.md          # Recommended: Documentation
└── assets/            # Optional: Logos, fonts, etc.
```

### Minimal manifest.json
```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "What it does",
  "entry_point": "manager.py",
  "class_name": "MyPlugin",
  "display_modes": ["my-plugin"],
  "category": "custom"
}
```

## Key Features

✅ **Install from Official Registry** - Curated, verified plugins  
✅ **Install from GitHub URL** - Any repo, instant install  
✅ **Search & Filter** - Find plugins by category, tags, query  
✅ **Auto Dependencies** - requirements.txt installed automatically  
✅ **Git or ZIP** - Git clone preferred, ZIP fallback  
✅ **Update System** - Keep plugins current  
✅ **Safe Uninstall** - Clean removal  

## Safety Notes

⚠️ **Verified** (✓) = Reviewed by maintainers, safe  
⚠️ **Unverified** = From custom URL, review before installing  
⚠️ **Always** review plugin code before installing from URL  
⚠️ **Only** install from sources you trust  

## Common Issues

**"Failed to clone"**  
→ Check git is installed: `which git`  
→ Verify GitHub URL is correct  
→ System will try ZIP download as fallback  

**"No manifest.json"**  
→ Plugin repo must have manifest.json in root  
→ Check repo structure  

**"Dependencies failed"**  
→ Manually install: `pip3 install -r plugins/plugin-id/requirements.txt`  

**Plugin won't load**  
→ Check enabled in config: `"enabled": true`  
→ Restart display: `sudo systemctl restart ledmatrix`  
→ Check logs: `sudo journalctl -u ledmatrix -f`  

## Documentation

- Full Guide: [`PLUGIN_STORE_USER_GUIDE.md`](./PLUGIN_STORE_USER_GUIDE.md)
- Developer Guide: [`plugin-development/`](./plugin-development/) — building plugins
- Repo-wide reference for AI assistants: [`../CLAUDE.md`](../CLAUDE.md)

## Support

- Report issues on GitHub
- Check wiki for troubleshooting
- Join community discussions

---

**Quick Tip**: To install your own plugin for testing:
1. Push to GitHub
2. Paste URL in web interface
3. Click install
4. Done!

