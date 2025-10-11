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

### Example Configuration

```json
{
  "enabled": true,
  "image_path": "assets/static_images/my_logo.png",
  "fit_to_display": true,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 0],
  "display_duration": 10
}
```

### Configuration Options

- `enabled`: Enable/disable the plugin
- `image_path`: Path to image file (relative or absolute)
- `fit_to_display`: Automatically fit image to display dimensions
- `preserve_aspect_ratio`: Maintain image proportions when scaling
- `background_color`: RGB color for transparent areas [R, G, B]
- `display_duration`: Seconds to display the image

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

To rotate through multiple images, create multiple plugin instances with different IDs:

```json
{
  "static-image-1": {
    "enabled": true,
    "image_path": "assets/static_images/image1.png"
  },
  "static-image-2": {
    "enabled": true,
    "image_path": "assets/static_images/image2.png"
  }
}
```

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
  "image_path": "assets/static_images/company_logo.png",
  "fit_to_display": true,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 0]
}
```

### Pixel Art
```json
{
  "enabled": true,
  "image_path": "assets/static_images/pixel_art.png",
  "fit_to_display": false,
  "preserve_aspect_ratio": true,
  "background_color": [0, 0, 50]
}
```

### Full Screen Photo
```json
{
  "enabled": true,
  "image_path": "assets/static_images/photo.jpg",
  "fit_to_display": true,
  "preserve_aspect_ratio": false,
  "background_color": [0, 0, 0]
}
```

## License

MIT License - see main LEDMatrix repository for details.

