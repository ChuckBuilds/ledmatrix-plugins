"""Generate a placeholder UFC separator icon for scroll display.

Run this script once to create assets/sports/ufc_logos/UFC.png.
Replace with an official UFC octagon logo when available.
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont


def _resolve_font_path(path: str) -> str:
    """Resolve a bundled font path without depending on the process cwd.

    These fonts ship with the LEDMatrix core, and every call site here named
    them relative to the working directory. That holds under the packaged
    systemd unit, whose WorkingDirectory is the install root, and breaks
    everywhere else -- the plugin safety harness, a manual run from $HOME, a
    unit file written without WorkingDirectory. The failure is quiet: the
    load raises, the caller falls back, and the scoreboard renders in PIL's
    default face instead of the pixel font it was laid out for.

    Resolution order matches the core's own resolver: the path as given
    first, so behaviour is unchanged wherever it already worked and a
    configured absolute path is returned untouched, then the core install
    root, then the original string so callers still raise and fall back
    exactly as they do today.
    """
    if os.path.exists(path):
        return path
    try:
        import src.font_manager as _core_fonts

        # The core grew this resolver in ChuckBuilds/LEDMatrix#425. Use it
        # when it is there so both repos stay on one definition of "install
        # root"; older cores fall through to the equivalent derivation below.
        manager = getattr(_core_fonts, "FontManager", None)
        resolver = getattr(manager, "_resolve_asset_path", None)
        if resolver is not None:
            resolved = resolver(path)
            if resolved and os.path.exists(resolved):
                return resolved
        root = os.path.dirname(os.path.dirname(os.path.abspath(_core_fonts.__file__)))
        candidate = os.path.join(root, path)
        if os.path.exists(candidate):
            return candidate
    except (ImportError, AttributeError, OSError):
        # No core on the path (standalone tooling), a core laid out
        # differently, or an unreadable install. Returning the original keeps
        # the caller's existing fallback intact.
        return path
    return path



def create_ufc_octagon_icon(output_path: str, size: int = 64):
    """Create a simple UFC octagon icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw octagon
    center_x, center_y = size // 2, size // 2
    radius = size // 2 - 2

    # Calculate octagon vertices
    points = []
    for i in range(8):
        angle = math.pi / 8 + (i * math.pi / 4)  # Start rotated for flat top
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        points.append((x, y))

    # Draw filled octagon
    draw.polygon(points, fill=(200, 16, 16, 230), outline=(255, 255, 255, 255))

    # Draw "UFC" text
    try:
        font = ImageFont.truetype(_resolve_font_path("assets/fonts/PressStart2P-Regular.ttf"), 10)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

    text = "UFC"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) // 2
    text_y = (size - text_h) // 2

    # White text with black outline
    for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
        draw.text((text_x + dx, text_y + dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))

    img.save(output_path, "PNG")
    print(f"Created UFC icon at {output_path}")


if __name__ == "__main__":
    create_ufc_octagon_icon("assets/sports/ufc_logos/UFC.png")
