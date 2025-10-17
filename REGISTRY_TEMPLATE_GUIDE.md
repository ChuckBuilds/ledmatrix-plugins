# Plugin Registry Template System

## Overview

The plugin registry now supports **download URL templates**, eliminating the need to manually update download URLs for each version.

## New Format (Simplified)

### Before (Manual URL per version)
```json
{
  "id": "weather",
  "repo": "https://github.com/ChuckBuilds/ledmatrix-weather",
  "versions": [
    {
      "version": "1.0.4",
      "download_url": "https://github.com/ChuckBuilds/ledmatrix-weather/archive/refs/tags/v1.0.4.zip"
    },
    {
      "version": "1.0.3",
      "download_url": "https://github.com/ChuckBuilds/ledmatrix-weather/archive/refs/tags/v1.0.3.zip"
    }
  ]
}
```

### After (Template with automatic URL generation)
```json
{
  "id": "weather",
  "repo": "https://github.com/ChuckBuilds/ledmatrix-weather",
  "download_url_template": "https://github.com/ChuckBuilds/ledmatrix-weather/archive/refs/tags/v{version}.zip",
  "latest_version": "1.0.4",
  "versions": [
    {
      "version": "1.0.4",
      "released": "2025-10-16"
    },
    {
      "version": "1.0.3",
      "released": "2025-10-14"
    }
  ]
}
```

## Benefits

1. **Less repetition** - No more copying download URLs
2. **Easier updates** - Only update `latest_version` and add version entry
3. **Fewer errors** - Template ensures consistent URL format
4. **Backward compatible** - Still supports individual `download_url` in version entries

## Adding a New Version

### Old Way (5 edits needed)
```json
{
  "versions": [
    {
      "version": "1.0.4",  // ← Edit 1
      "ledmatrix_min": "2.0.0",
      "released": "2025-10-16",  // ← Edit 2
      "download_url": "https://github.com/ChuckBuilds/ledmatrix-weather/archive/refs/tags/v1.0.4.zip"  // ← Edit 3
    },
    // ... previous versions
  ],
  "last_updated": "2025-10-16"  // ← Edit 4
}
```

### New Way (3 edits needed)
```json
{
  "download_url_template": "https://github.com/ChuckBuilds/ledmatrix-weather/archive/refs/tags/v{version}.zip",
  "latest_version": "1.0.4",  // ← Edit 1
  "versions": [
    {
      "version": "1.0.4",  // ← Edit 2
      "released": "2025-10-16"  // ← Edit 3
    },
    // ... previous versions  
  ],
  "last_updated": "2025-10-16"  // ← Edit 4
}
```

## Template Variables

Currently supported:
- `{version}` - Version number (e.g., "1.0.4")

Future possibilities:
- `{branch}` - Branch name
- `{repo}` - Repository name
- `{author}` - Author name

## Fallback Behavior

The store manager tries URLs in this order:

1. **Version-specific URL** (if `download_url` in version entry)
   ```json
   "versions": [{"version": "1.0.4", "download_url": "custom_url.zip"}]
   ```

2. **Plugin template** (if `download_url_template` at plugin level)
   ```json
   "download_url_template": "https://example.com/{version}.zip"
   ```

3. **Auto-constructed** (fallback pattern)
   ```
   {repo}/archive/refs/tags/v{version}.zip
   ```

## Migration Guide

### Step 1: Add Template and Latest Version

```json
{
  "id": "my-plugin",
  "download_url_template": "https://github.com/user/repo/archive/refs/tags/v{version}.zip",
  "latest_version": "1.0.5",
  "versions": [...]
}
```

### Step 2: Remove download_url from Version Entries

```json
// Before
{
  "version": "1.0.4",
  "ledmatrix_min": "2.0.0",
  "released": "2025-10-16",
  "download_url": "https://github.com/..."  // ← Remove this
}

// After
{
  "version": "1.0.4",
  "ledmatrix_min": "2.0.0",
  "released": "2025-10-16"
}
```

### Step 3: Test Installation

```bash
# Test via web interface or CLI
# The download URL will be auto-generated from template
```

## Examples

### Standard GitHub Release
```json
{
  "id": "weather",
  "repo": "https://github.com/ChuckBuilds/ledmatrix-weather",
  "download_url_template": "https://github.com/ChuckBuilds/ledmatrix-weather/archive/refs/tags/v{version}.zip",
  "latest_version": "1.0.4"
}
```

### Custom URL Pattern
```json
{
  "id": "custom-plugin",
  "repo": "https://example.com/repo",
  "download_url_template": "https://cdn.example.com/plugins/custom-{version}.zip",
  "latest_version": "2.3.1"
}
```

### Override for Specific Version
```json
{
  "download_url_template": "https://github.com/user/repo/archive/refs/tags/v{version}.zip",
  "versions": [
    {
      "version": "1.0.4",
      "released": "2025-10-16"
      // Uses template: v1.0.4.zip
    },
    {
      "version": "1.0.3-beta",
      "released": "2025-10-14",
      "download_url": "https://github.com/user/repo/releases/download/v1.0.3-beta/custom.zip"
      // Uses specific URL (overrides template)
    }
  ]
}
```

## Future Updates Process

### When releasing v1.0.5:

1. Update plugin repo (tag release as v1.0.5)
2. Update `plugins.json`:
   ```json
   {
     "latest_version": "1.0.5",  // ← Change this
     "versions": [
       {
         "version": "1.0.5",     // ← Add this
         "released": "2025-10-XX"
       },
       // ... older versions
     ]
   }
   ```
3. **Done!** Download URL is auto-generated from template

## Validation

The template system validates that:
- Template contains `{version}` placeholder
- Latest version exists in versions array
- Generated URL is valid (optional check)

## Backward Compatibility

✅ Old format still works - if `download_url` exists in version entry, it takes priority over template

