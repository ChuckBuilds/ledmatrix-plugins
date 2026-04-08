-----------------------------------------------------------------------------------
### Connect with ChuckBuilds

- Show support on Youtube: https://www.youtube.com/@ChuckBuilds
- Stay in touch on Instagram: https://www.instagram.com/ChuckBuilds/
- Want to chat or need support? Reach out on the ChuckBuilds Discord: https://discord.com/invite/uW36dVAtcT
- Feeling Generous? Support the project:
  - Github Sponsorship: https://github.com/sponsors/ChuckBuilds
  - Buy Me a Coffee: https://buymeacoffee.com/chuckbuilds
  - Ko-fi: https://ko-fi.com/chuckbuilds/ 

-----------------------------------------------------------------------------------

# Static Image Display Plugin

Display static images on your LED matrix with automatic scaling, aspect ratio preservation, and transparency support.

## Features

- **Multiple Format Support**: PNG, JPG, BMP, GIF, and more
- **Automatic Scaling**: Fit images to your display dimensions
- **Aspect Ratio Preservation**: Keep images looking correct
- **Transparency Support**: Handle PNG alpha channels
- **Configurable Background**: Set custom background colors
- **High-Quality Scaling**: LANCZOS resampling for best quality

## Configuration

### Single image

```json
{
  "enabled": true,
  "images": [
    { "id": "logo", "path": "assets/static_images/my_logo.png" }
  ],
  "fit_to_display": true,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 0],
  "display_duration": 10
}
```

### Multiple images with rotation

```json
{
  "enabled": true,
  "images": [
    { "id": "logo_a", "path": "assets/static_images/logo_a.png" },
    { "id": "logo_b", "path": "assets/static_images/logo_b.png" },
    { "id": "logo_c", "path": "assets/static_images/logo_c.png" }
  ],
  "image_config": {
    "mode": "multiple",
    "rotation_mode": "sequential"
  },
  "rotation_settings": {
    "sequential_loop": true
  },
  "image_rotation_interval": 15,
  "fit_to_display": true,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 0],
  "display_duration": 30
}
```

### Configuration Options

The full schema lives in
[`config_schema.json`](config_schema.json) — the web UI form is generated
from it. Key options:

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch |
| `images` | `[]` | Array of image paths (relative to LEDMatrix root or absolute) |
| `image_config.mode` | `"single"` | How images are presented |
| `image_config.rotation_mode` | `"sequential"` | `"sequential"` or `"random"` when multiple images |
| `rotation_settings.sequential_loop` | `true` | Loop back to the first image after the last |
| `rotation_settings.random_seed` | `null` | Optional fixed seed for reproducible random order |
| `rotation_settings.time_intervals.enabled` | `false` | Tie image changes to wall-clock intervals |
| `rotation_settings.time_intervals.interval_seconds` | `3600` | Wall-clock interval when enabled |
| `image_rotation_interval` | `15` | Seconds between images during rotation |
| `fit_to_display` | `true` | Scale image to display dimensions |
| `preserve_aspect_ratio` | `true` | Don't stretch when scaling |
| `background_color` | `[0, 0, 0]` | RGB fill behind transparent pixels |
| `display_duration` | `10` | Seconds the plugin holds the screen each rotation |

## Usage

### Basic Setup

1. Place your image in a directory (e.g., `assets/static_images/`)
2. Configure the plugin with the image path
3. Enable the plugin
4. The image will display automatically during rotation

### Image Guidelines

**Recommended:**
- Use PNG format for best quality and transparency support
- Size images close to your display resolution for best performance
- For 64x32 displays: 64x32 or 128x64 images work well
- Use transparency to blend with background

**Supported Formats:**
- PNG (recommended for transparency)
- JPG/JPEG
- BMP
- GIF
- TIFF

### Tips for Best Results

1. **For Logos**: Use PNG with transparent background
2. **For Photos**: Use JPG for smaller file size
3. **For Pixel Art**: Use PNG at native resolution
4. **For Icons**: Scale to exact display size

## Advanced Usage

### Dynamic Image Updates

Change images programmatically via the Web UI or API:

```python
# Via plugin manager
plugin.set_image_path("assets/static_images/new_image.png")
plugin.reload_image()
```

### Multiple Images

Put all the images you want to cycle through into the `images` array (see
the multi-image example above) and set `image_config.mode` to
`"multiple"`.

## Troubleshooting

**Image not displaying:**
- Check that image path is correct
- Verify image file exists
- Check file permissions
- Review logs for error messages

**Image looks distorted:**
- Enable `preserve_aspect_ratio`
- Check image dimensions vs display size
- Verify image isn't corrupted

**Image appears cropped:**
- Enable `fit_to_display`
- Check image size matches display

**Transparency not working:**
- Use PNG format with alpha channel
- Verify background_color is set correctly

## Examples

### Logo Display
```json
{
  "enabled": true,
  "images": [
    { "id": "company_logo", "path": "assets/static_images/company_logo.png" }
  ],
  "fit_to_display": true,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 0]
}
```

### Pixel Art
```json
{
  "enabled": true,
  "images": [
    { "id": "pixel_art", "path": "assets/static_images/pixel_art.png" }
  ],
  "fit_to_display": false,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 50]
}
```

### Full Screen Photo
```json
{
  "enabled": true,
  "images": [
    { "id": "photo", "path": "assets/static_images/photo.jpg" }
  ],
  "fit_to_display": true,
  "preserve_aspect_ratio": false,
  "background_color": [0, 0, 0]
}
```

## License

GPL-3.0 License - see main LEDMatrix repository for details.

