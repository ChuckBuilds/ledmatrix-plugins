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

## Submission Process

1. **Test Your Plugin**
   ```bash
   # Install via URL on your Pi
   curl -X POST http://your-pi:5050/api/plugins/install-from-url \
     -d '{"repo_url": "https://github.com/you/ledmatrix-your-plugin"}'
   ```

2. **Create Release**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

3. **Fork This Repo**
   Fork [ledmatrix-plugins](https://github.com/ChuckBuilds/ledmatrix-plugins)

4. **Update plugins.json**
   Add your plugin entry:
   ```json
   {
     "id": "your-plugin",
     "name": "Your Plugin Name",
     "description": "What it does",
     "author": "YourName",
     "category": "custom",
     "tags": ["tag1", "tag2"],
     "repo": "https://github.com/you/ledmatrix-your-plugin",
     "branch": "main",
     "versions": [
       {
         "version": "1.0.0",
         "ledmatrix_min": "2.0.0",
         "released": "2025-10-09",
         "download_url": "https://github.com/you/ledmatrix-your-plugin/archive/refs/tags/v1.0.0.zip"
       }
     ],
     "verified": false
   }
   ```

5. **Submit Pull Request**
   Create PR with title: "Add plugin: your-plugin-name"

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

To release a new version:

1. Create new release in your repo
2. Update `versions` array in plugins.json
3. Submit PR with changes
4. We'll review and merge

## Questions?

Open an issue in this repo or the main LEDMatrix repo.

