# Plugin Submission Guidelines

Want to add your plugin to the official registry? Follow these steps!

## Requirements

Before submitting, ensure your plugin:

- ✅ Has a complete `manifest.json` with all required fields
- ✅ Follows the plugin architecture specification
- ✅ Has comprehensive README documentation
- ✅ Includes example configuration
- ✅ Has been tested on Raspberry Pi hardware
- ✅ Follows coding standards (PEP 8)
- ✅ Has proper error handling
- ✅ Uses logging appropriately
- ✅ Has no hardcoded API keys or secrets

## Submission Options

### Option A: Add to the Monorepo (Preferred)

Submit a PR to add your plugin directly to this repository:

1. **Fork This Repo**
   Fork [ledmatrix-plugins](https://github.com/ChuckBuilds/ledmatrix-plugins)

2. **Add Your Plugin Directory**
   ```
   plugins/your-plugin-id/
     manifest.json
     manager.py
     config_schema.json
     requirements.txt
     README.md
   ```

3. **Submit Pull Request**
   Create PR with title: "Add plugin: your-plugin-name"

After approval, your plugin will be added to `plugins.json` and available in the Plugin Store.

### Option B: Keep Your Own Repository (3rd-Party)

If you prefer to maintain your own repo:

1. **Test Your Plugin**
   ```bash
   # Install via URL on your Pi
   curl -X POST http://your-pi:5050/api/plugins/install-from-url \
     -d '{"repo_url": "https://github.com/you/ledmatrix-your-plugin"}'
   ```

2. **Open an Issue**
   Open an issue on this repository with your repo URL, description, and screenshots.

3. **After Review**
   We'll add a registry entry in `plugins.json` pointing to your repo.

## Review Process

1. **Automated Checks**: Manifest validation, structure check
2. **Code Review**: Manual review of plugin code
3. **Testing**: Test installation and basic functionality
4. **Approval**: If accepted, merged and marked as verified

## After Approval

- Plugin appears in official store
- `verified: true` badge shown
- Included in plugin count
- Featured in README

## Updating Your Plugin

### Monorepo Plugins (Option A)
1. Submit a PR with your code changes
2. Bump `version` in your plugin's `manifest.json`
3. The pre-commit hook will automatically update `plugins.json`

### 3rd-Party Plugins (Option B)
1. Push updates to your repository
2. Open a PR or issue to update the version in `plugins.json`

## Questions?

Open an issue in this repo or the main [LEDMatrix repo](https://github.com/ChuckBuilds/LEDMatrix).
