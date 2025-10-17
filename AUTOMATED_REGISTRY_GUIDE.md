# Automated Plugin Registry Update Guide

## Overview

The plugin registry (`plugins.json`) is now automatically updated every 6 hours using a Python script and GitHub Actions. This eliminates the need to manually update version numbers when you release new plugin versions.

## How It Works

### Automated Updates (GitHub Actions)
- **Schedule**: Runs every 6 hours automatically
- **Manual Trigger**: Can be triggered manually from GitHub Actions tab
- **Process**:
  1. Checks each plugin's GitHub repository for releases/tags
  2. Compares with current versions in `plugins.json`
  3. Updates the registry if new versions are found
  4. Automatically commits and pushes changes

### Manual Updates (Local Development)

You can also run the update script locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Dry run (preview changes without applying)
python update_registry.py --dry-run

# Update the registry
python update_registry.py

# Use with GitHub token (avoids rate limits)
python update_registry.py --token YOUR_GITHUB_TOKEN
```

## Creating New Plugin Releases

To publish a new version of a plugin:

1. **Update the plugin's `manifest.json`** with the new version number
2. **Commit and push your changes** to the plugin repository
3. **Create a Git tag** for the new version:
   ```bash
   cd plugin-repos/ledmatrix-your-plugin
   git tag -a v1.0.1 -m "Version 1.0.1 - Description of changes"
   git push origin v1.0.1
   ```
4. **Wait for the automated update** (runs every 6 hours) or trigger manually

### Creating GitHub Releases (Optional)

While tags are sufficient, you can also create formal GitHub releases:

1. Go to your plugin repository on GitHub
2. Click "Releases" → "Create a new release"
3. Choose your tag (e.g., `v1.0.1`)
4. Add release notes
5. Publish the release

The automated script will detect both tags and releases.

## Troubleshooting

### Rate Limits

GitHub's API has rate limits:
- **Without token**: 60 requests per hour
- **With token**: 5000 requests per hour

The automated GitHub Actions workflow uses a token automatically, so it won't hit rate limits.

For local testing, you can create a GitHub Personal Access Token:
1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate a new token with `public_repo` scope
3. Use it with: `python update_registry.py --token YOUR_TOKEN`

### Version Not Detected

If the script doesn't detect your new version:

1. **Verify the tag exists on GitHub**:
   ```bash
   git ls-remote --tags https://github.com/ChuckBuilds/ledmatrix-your-plugin
   ```

2. **Check tag format**: Tags should be `v1.0.0` format (with 'v' prefix)

3. **Wait a few minutes**: GitHub's API might take a moment to reflect new tags

4. **Run manually with token**: `python update_registry.py --token YOUR_TOKEN`

### Script Not Finding Updates

If you know there's a new version but the script doesn't find it:

1. Check that the repository URL in `plugins.json` is correct
2. Ensure the tag/release is published (not draft)
3. Verify the tag follows semantic versioning (e.g., `v1.0.0`)

## Files

- **`update_registry.py`** - Python script that checks GitHub and updates registry
- **`.github/workflows/update-registry.yml`** - GitHub Actions workflow
- **`requirements.txt`** - Python dependencies for the script
- **`plugins.json`** - The actual plugin registry

## Benefits

✅ **Automatic version detection** - No manual updates needed  
✅ **Consistent format** - Ensures all plugins follow the same versioning  
✅ **Always up-to-date** - Registry updates every 6 hours  
✅ **Easy releases** - Just create a git tag and push  
✅ **Version history** - All versions tracked in `plugins.json`  

## Example Workflow

Here's a typical workflow for releasing a plugin update:

```bash
# 1. Make your changes to the plugin
cd plugin-repos/ledmatrix-weather
# ... edit files ...

# 2. Update the version in manifest.json
# Change "version": "1.0.0" to "version": "2.0.0"

# 3. Commit your changes
git add -A
git commit -m "Add new features for v2.0.0"
git push

# 4. Create and push a tag
git tag -a v2.0.0 -m "Version 2.0.0 - New features"
git push origin v2.0.0

# 5. Done! The registry will automatically update within 6 hours
# Or trigger the GitHub Action manually for immediate update
```

## Notes

- The script prioritizes **releases** over **tags** when both exist
- Only **non-draft**, **non-prerelease** versions are considered
- The script preserves all existing version history
- Release dates are taken from GitHub's published date

