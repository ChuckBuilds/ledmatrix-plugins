#!/usr/bin/env python3
"""
Generate a simple Christmas tree image for the plugin.
This is a utility script to create the assets/christmas_tree.png file.
"""

from PIL import Image, ImageDraw

def create_christmas_tree(size=32):
    """Create a stylized Christmas tree image."""
    # Create image with transparent background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    center_x = size // 2
    base_y = size - size // 4  # Leave room for trunk
    
    # Tree color (green)
    tree_color = (0, 128, 0)
    
    # Draw tree layers (triangles from bottom to top)
    layer_count = 3
    for i in range(layer_count):
        layer_y = base_y - (i * size // (layer_count + 1))
        layer_width = size - (i * size // (layer_count + 2))
        layer_width = max(4, layer_width)  # Minimum width
        
        # Triangle points
        top_x = center_x
        top_y = layer_y - layer_width // 2
        left_x = center_x - layer_width // 2
        left_y = layer_y
        right_x = center_x + layer_width // 2
        right_y = layer_y
        
        # Draw filled triangle
        draw.polygon(
            [(top_x, top_y), (left_x, left_y), (right_x, right_y)],
            fill=tree_color
        )
    
    # Draw trunk (rectangle at bottom center)
    trunk_width = max(2, size // 8)
    trunk_height = size // 6
    trunk_x = center_x - trunk_width // 2
    trunk_y = size - trunk_height
    trunk_color = (101, 67, 33)  # Brown
    
    draw.rectangle(
        [trunk_x, trunk_y, trunk_x + trunk_width, size],
        fill=trunk_color
    )
    
    # Add a star on top (yellow)
    star_size = max(2, size // 12)
    star_y = top_y - star_size
    star_color = (255, 255, 0)  # Yellow
    draw.ellipse(
        [center_x - star_size, star_y - star_size,
         center_x + star_size, star_y + star_size],
        fill=star_color
    )
    
    # Add some simple ornaments (red circles)
    if size >= 24:
        ornament_color = (255, 0, 0)  # Red
        ornament_size = max(1, size // 16)
        
        # Add ornaments on middle layer
        mid_layer_y = base_y - (size // (layer_count + 1))
        mid_layer_width = size - (size // (layer_count + 2))
        
        # Left ornament
        draw.ellipse(
            [center_x - mid_layer_width // 3 - ornament_size,
             mid_layer_y - ornament_size,
             center_x - mid_layer_width // 3 + ornament_size,
             mid_layer_y + ornament_size],
            fill=ornament_color
        )
        
        # Right ornament
        draw.ellipse(
            [center_x + mid_layer_width // 3 - ornament_size,
             mid_layer_y - ornament_size,
             center_x + mid_layer_width // 3 + ornament_size,
             mid_layer_y + ornament_size],
            fill=ornament_color
        )
    
    return img

if __name__ == "__main__":
    # Create tree image
    tree_img = create_christmas_tree(32)
    
    # Save to assets directory
    from pathlib import Path
    
    script_dir = Path(__file__).parent
    assets_dir = script_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    output_path = assets_dir / "christmas_tree.png"
    tree_img.save(output_path)
    print(f"Created Christmas tree image at {output_path}")

