#!/usr/bin/env python3
"""
Masters Tournament Asset Downloader

Downloads REAL assets:
- Player headshots from ESPN CDN
- Creates accurate Augusta National hole layouts based on real course topology
- Creates pixel-perfect Masters branding for LED matrix displays
- Creates high-quality icons and backgrounds
"""

import math
import os
import random
import sys
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# Asset directories
PLUGIN_DIR = Path(__file__).parent
ASSETS_DIR = PLUGIN_DIR / "assets" / "masters"
LOGOS_DIR = ASSETS_DIR / "logos"
COURSES_DIR = ASSETS_DIR / "courses"
ICONS_DIR = ASSETS_DIR / "icons"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
PLAYERS_DIR = ASSETS_DIR / "players"
FLAGS_DIR = ASSETS_DIR / "flags"

for directory in [LOGOS_DIR, COURSES_DIR, ICONS_DIR, BACKGROUNDS_DIR, PLAYERS_DIR, FLAGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


def get_font(size=16, bold=True):
    """Get best available font."""
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/google-droid-sans-fonts/DroidSans-Bold.ttf",
    ]
    if not bold:
        paths = [p.replace("-Bold", "") for p in paths] + paths
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════════
# REAL PLAYER HEADSHOTS FROM ESPN
# ═══════════════════════════════════════════════════════════════

ESPN_PLAYERS = {
    "Scottie Scheffler": "9478",
    "Rory McIlroy": "3470",
    "Jon Rahm": "9780",
    "Brooks Koepka": "6798",
    "Xander Schauffele": "10138",
    "Jordan Spieth": "5765",
    "Patrick Cantlay": "10134",
    "Tiger Woods": "462",
    "Phil Mickelson": "308",
    "Dustin Johnson": "3702",
    "Hideki Matsuyama": "5860",
    "Collin Morikawa": "10592",
    "Viktor Hovland": "10591",
    "Tony Finau": "5548",
    "Shane Lowry": "3448",
    "Tommy Fleetwood": "9035",
    "Adam Scott": "367",
    "Bubba Watson": "780",
    "Matt Fitzpatrick": "9037",
    "Wyndham Clark": "4686082",
    "Max Homa": "10140",
    "Cameron Smith": "9131",
    "Justin Thomas": "4686084",
    "Ludvig Aberg": "4686087",
    "Sahith Theegala": "4375306",
}


def download_player_headshots():
    """Download real player headshots from ESPN CDN."""
    print("\nDownloading real player headshots from ESPN...")
    count = 0
    for name, pid in ESPN_PLAYERS.items():
        save_path = PLAYERS_DIR / f"{pid}.png"
        if save_path.exists():
            print(f"  [cached] {name}")
            count += 1
            continue

        url = f"https://a.espncdn.com/combiner/i?img=/i/headshots/golf/players/full/{pid}.png&w=350&h=254"
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            img.save(save_path, "PNG")
            print(f"  [downloaded] {name} ({img.size[0]}x{img.size[1]})")
            count += 1
        except Exception as e:
            print(f"  [FAILED] {name}: {e}")

    print(f"  Total: {count}/{len(ESPN_PLAYERS)} headshots")


# ═══════════════════════════════════════════════════════════════
# MASTERS LOGO - Authentic pixel-art recreation
# ═══════════════════════════════════════════════════════════════

def create_masters_logo():
    """Create an authentic-looking Masters Tournament logo.

    The real Masters logo features the text 'MASTERS' in a serif font
    with a map of the United States underneath showing Augusta's location.
    We recreate this iconic look.
    """
    width, height = 256, 128
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Masters iconic yellow/gold on dark green
    masters_green = (0, 104, 56)
    masters_yellow = (253, 218, 36)

    # Background
    draw.rounded_rectangle([(2, 2), (width - 3, height - 3)], radius=8, fill=masters_green)

    # Gold border
    draw.rounded_rectangle([(2, 2), (width - 3, height - 3)], radius=8, outline=masters_yellow, width=3)

    # "THE MASTERS" text - the real logo uses a distinctive serif font
    try:
        # Try serif fonts first for authenticity
        serif_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/google-noto-serif-fonts/NotoSerif-Bold.ttf",
        ]
        title_font = None
        for p in serif_paths:
            if os.path.exists(p):
                title_font = ImageFont.truetype(p, 38)
                break
        if not title_font:
            title_font = get_font(38)
    except Exception:
        title_font = get_font(38)

    # Shadow
    draw.text((width // 2 + 2, 18), "THE MASTERS", font=title_font,
              fill=(0, 0, 0, 120), anchor="mt")
    # Main text in Masters yellow
    draw.text((width // 2, 16), "THE MASTERS", font=title_font,
              fill=masters_yellow, anchor="mt")

    # "TOURNAMENT" subtitle
    sub_font = get_font(14)
    draw.text((width // 2, 60), "T O U R N A M E N T", font=sub_font,
              fill=masters_yellow, anchor="mt")

    # Simplified US map outline with Augusta marked
    # Draw a simplified outline of the continental US
    us_points = [
        (60, 82), (65, 78), (80, 76), (95, 78), (110, 76),
        (125, 78), (135, 80), (145, 82), (155, 78), (165, 80),
        (175, 84), (180, 88), (185, 92), (188, 98), (182, 102),
        (175, 106), (165, 108), (155, 106), (145, 108), (135, 110),
        (120, 108), (105, 110), (90, 108), (80, 110), (70, 108),
        (60, 105), (55, 98), (58, 90),
    ]
    draw.polygon(us_points, fill=(0, 85, 45), outline=masters_yellow, width=1)

    # Mark Augusta, GA with a flag pin
    augusta_x, augusta_y = 172, 100
    draw.ellipse([augusta_x - 3, augusta_y - 3, augusta_x + 3, augusta_y + 3],
                 fill=(255, 0, 0))
    draw.line([(augusta_x, augusta_y - 3), (augusta_x, augusta_y - 12)],
              fill=(255, 255, 255), width=1)
    draw.polygon([(augusta_x, augusta_y - 12), (augusta_x + 6, augusta_y - 10),
                  (augusta_x, augusta_y - 8)], fill=(255, 0, 0))

    # "AUGUSTA NATIONAL GOLF CLUB" text at bottom
    small_font = get_font(9)
    draw.text((width // 2, height - 12), "AUGUSTA NATIONAL GOLF CLUB", font=small_font,
              fill=masters_yellow, anchor="mb")

    save_path = LOGOS_DIR / "masters_logo.png"
    img.save(save_path)
    print(f"  [created] masters_logo.png ({width}x{height})")


def create_masters_logo_small():
    """Create a small pixel-perfect Masters logo for LED displays."""
    # Multiple sizes for different display resolutions
    for size_name, (w, h) in [("sm", (32, 16)), ("md", (48, 24)), ("lg", (64, 32))]:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        masters_green = (0, 104, 56)
        masters_yellow = (253, 218, 36)

        # Fill background
        draw.rectangle([(0, 0), (w - 1, h - 1)], fill=masters_green, outline=masters_yellow)

        # "M" logo for tiny sizes, "MASTERS" for larger
        if w <= 32:
            # Just draw a stylized "M" in gold
            mx = w // 2
            my = h // 2
            draw.text((mx, my), "M", fill=masters_yellow, anchor="mm",
                      font=get_font(min(h - 4, 14)))
        else:
            draw.text((w // 2, h // 2), "MASTERS", fill=masters_yellow, anchor="mm",
                      font=get_font(min(h - 6, 10)))

        save_path = LOGOS_DIR / f"masters_logo_{size_name}.png"
        img.save(save_path)
        print(f"  [created] masters_logo_{size_name}.png ({w}x{h})")


# ═══════════════════════════════════════════════════════════════
# GREEN JACKET ICON
# ═══════════════════════════════════════════════════════════════

def create_green_jacket_icon():
    """Create a detailed green jacket icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    masters_green = (0, 120, 74)
    dark_green = (0, 90, 55)
    light_green = (0, 140, 90)
    gold = (255, 215, 0)

    # Jacket body with lapels
    # Left side
    draw.polygon([
        (size * 0.15, size * 0.25),  # Left shoulder
        (size * 0.20, size * 0.95),  # Left bottom
        (size * 0.48, size * 0.95),  # Center bottom left
        (size * 0.42, size * 0.30),  # Left lapel inner
    ], fill=masters_green, outline=dark_green, width=1)

    # Right side
    draw.polygon([
        (size * 0.85, size * 0.25),  # Right shoulder
        (size * 0.80, size * 0.95),  # Right bottom
        (size * 0.52, size * 0.95),  # Center bottom right
        (size * 0.58, size * 0.30),  # Right lapel inner
    ], fill=masters_green, outline=dark_green, width=1)

    # Collar / lapels (V-shape)
    draw.polygon([
        (size * 0.35, size * 0.15),  # Left collar top
        (size * 0.50, size * 0.40),  # V bottom
        (size * 0.42, size * 0.30),  # Left lapel
    ], fill=light_green, outline=dark_green, width=1)

    draw.polygon([
        (size * 0.65, size * 0.15),  # Right collar top
        (size * 0.50, size * 0.40),  # V bottom
        (size * 0.58, size * 0.30),  # Right lapel
    ], fill=light_green, outline=dark_green, width=1)

    # Sleeves
    draw.polygon([
        (size * 0.15, size * 0.25),
        (size * 0.05, size * 0.55),
        (size * 0.15, size * 0.55),
        (size * 0.22, size * 0.35),
    ], fill=masters_green, outline=dark_green, width=1)

    draw.polygon([
        (size * 0.85, size * 0.25),
        (size * 0.95, size * 0.55),
        (size * 0.85, size * 0.55),
        (size * 0.78, size * 0.35),
    ], fill=masters_green, outline=dark_green, width=1)

    # Gold buttons
    for y_ratio in [0.45, 0.58, 0.72]:
        bx, by = int(size * 0.50), int(size * y_ratio)
        r = max(2, int(size * 0.04))
        draw.ellipse([bx - r, by - r, bx + r, by + r], fill=gold, outline=(200, 170, 0))

    # Augusta National crest on breast pocket (tiny gold circle)
    crest_x, crest_y = int(size * 0.62), int(size * 0.42)
    cr = max(2, int(size * 0.06))
    draw.ellipse([crest_x - cr, crest_y - cr, crest_x + cr, crest_y + cr],
                 outline=gold, width=1)

    save_path = LOGOS_DIR / "green_jacket.png"
    img.save(save_path)
    print(f"  [created] green_jacket.png ({size}x{size})")


# ═══════════════════════════════════════════════════════════════
# AZALEA FLOWER
# ═══════════════════════════════════════════════════════════════

def create_azalea_flower():
    """Create a beautiful azalea flower icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pink = (255, 105, 180)
    light_pink = (255, 182, 213)
    dark_pink = (200, 60, 120)
    center_yellow = (255, 255, 100)

    center_x, center_y = size // 2, size // 2

    # 5 petals with realistic petal shape
    for i in range(5):
        angle = math.radians((360 / 5) * i - 90)
        px = center_x + int(12 * math.cos(angle))
        py = center_y + int(12 * math.sin(angle))

        # Each petal is an elongated ellipse
        petal_len = 14
        petal_wid = 10

        # Draw petal as overlapping circles for organic shape
        for step in range(8):
            t = step / 7
            sx = int(center_x + (px - center_x) * (0.3 + t * 0.7) + petal_len * t * math.cos(angle))
            sy = int(center_y + (py - center_y) * (0.3 + t * 0.7) + petal_len * t * math.sin(angle))
            r = int(petal_wid * (1 - abs(t - 0.5) * 1.2))
            if r > 0:
                color = light_pink if t > 0.5 else pink
                draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=color)

    # Petal outlines
    for i in range(5):
        angle = math.radians((360 / 5) * i - 90)
        px = center_x + int(22 * math.cos(angle))
        py = center_y + int(22 * math.sin(angle))
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], outline=dark_pink, width=1)

    # Flower center
    draw.ellipse([center_x - 6, center_y - 6, center_x + 6, center_y + 6],
                 fill=center_yellow, outline=(220, 180, 50))

    # Stamens
    for i in range(6):
        angle = math.radians(60 * i)
        sx = center_x + int(4 * math.cos(angle))
        sy = center_y + int(4 * math.sin(angle))
        draw.ellipse([sx - 1, sy - 1, sx + 1, sy + 1], fill=(180, 120, 0))

    save_path = LOGOS_DIR / "azalea.png"
    img.save(save_path)
    print(f"  [created] azalea.png ({size}x{size})")


# ═══════════════════════════════════════════════════════════════
# GOLF ICONS
# ═══════════════════════════════════════════════════════════════

def create_golf_icons():
    """Create clean golf icons for LED display."""
    size = 48

    # Golf Ball with realistic dimples
    ball_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ball_img)
    center = size // 2
    r = int(size * 0.4)

    # Shadow
    draw.ellipse([center - r + 3, center - r + 3, center + r + 3, center + r + 3],
                 fill=(0, 0, 0, 60))
    # Ball body
    draw.ellipse([center - r, center - r, center + r, center + r],
                 fill=(255, 255, 255), outline=(200, 200, 200), width=2)
    # Highlight
    draw.ellipse([center - r + 4, center - r + 3, center - r + 10, center - r + 8],
                 fill=(255, 255, 255, 200))
    # Dimples
    random.seed(42)
    for _ in range(20):
        dx = random.randint(center - r + 5, center + r - 5)
        dy = random.randint(center - r + 5, center + r - 5)
        if (dx - center) ** 2 + (dy - center) ** 2 < (r - 4) ** 2:
            draw.ellipse([dx - 1, dy - 1, dx + 1, dy + 1], fill=(230, 230, 230))

    ball_img.save(ICONS_DIR / "golf_ball.png")
    print(f"  [created] golf_ball.png")

    # Masters Flag (yellow flag, not red - Masters uses yellow)
    flag_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(flag_img)
    pole_x = size // 3
    draw.line([(pole_x, 4), (pole_x, size - 4)], fill=(180, 180, 180), width=2)
    # Yellow flag (Masters signature)
    draw.polygon([(pole_x, 4), (pole_x + 20, 10), (pole_x, 16)],
                 fill=(253, 218, 36), outline=(200, 170, 0), width=1)
    # Hole
    draw.ellipse([pole_x - 5, size - 6, pole_x + 5, size - 2], fill=(40, 40, 40))

    flag_img.save(ICONS_DIR / "golf_flag.png")
    print(f"  [created] golf_flag.png")

    # Golf Tee
    tee_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tee_img)
    cx = size // 2
    draw.polygon([(cx - 3, 14), (cx - 7, size - 6), (cx + 7, size - 6), (cx + 3, 14)],
                 fill=(210, 180, 140), outline=(150, 120, 80), width=1)
    draw.ellipse([cx - 7, 10, cx + 7, 18], fill=(210, 180, 140), outline=(150, 120, 80))
    # Ball on tee
    draw.ellipse([cx - 5, 2, cx + 5, 12], fill=(255, 255, 255), outline=(200, 200, 200))

    tee_img.save(ICONS_DIR / "golf_tee.png")
    print(f"  [created] golf_tee.png")


# ═══════════════════════════════════════════════════════════════
# ACCURATE AUGUSTA NATIONAL HOLE LAYOUTS
# Based on real Augusta National course topology
# ═══════════════════════════════════════════════════════════════

# Each hole defined with waypoints, hazards, and green shape
# Coordinates are relative (0-1 range), mapped to image dimensions
# Fairway waypoints go from tee to green

AUGUSTA_HOLE_LAYOUTS = {
    1: {  # Tea Olive - Par 4, 445y - Slight dogleg right, uphill
        "tee": (0.50, 0.90),
        "fairway": [(0.50, 0.90), (0.52, 0.70), (0.55, 0.50), (0.58, 0.30)],
        "green": (0.58, 0.18), "green_shape": "oval",
        "bunkers": [(0.50, 0.22), (0.66, 0.20)],
        "trees_left": True, "trees_right": True,
        "elevation": "uphill",
    },
    2: {  # Pink Dogwood - Par 5, 575y - Downhill, then uphill to green
        "tee": (0.25, 0.90),
        "fairway": [(0.25, 0.90), (0.30, 0.72), (0.40, 0.55), (0.55, 0.40), (0.65, 0.25)],
        "green": (0.65, 0.15), "green_shape": "kidney",
        "bunkers": [(0.55, 0.18), (0.72, 0.22)],
        "trees_left": True, "trees_right": True,
    },
    3: {  # Flowering Peach - Par 4, 350y - Short, uphill, tricky green
        "tee": (0.40, 0.88),
        "fairway": [(0.40, 0.88), (0.42, 0.65), (0.45, 0.42)],
        "green": (0.45, 0.25), "green_shape": "round",
        "bunkers": [(0.35, 0.28), (0.55, 0.22), (0.38, 0.20), (0.52, 0.30)],
        "trees_left": True,
    },
    4: {  # Flowering Crab Apple - Par 3, 240y - Long par 3, downhill
        "tee": (0.25, 0.82),
        "fairway": [],
        "green": (0.65, 0.22), "green_shape": "oval_wide",
        "bunkers": [(0.55, 0.28), (0.72, 0.18), (0.60, 0.15)],
        "trees_left": True, "trees_right": True,
    },
    5: {  # Magnolia - Par 4, 495y - Uphill dogleg left
        "tee": (0.75, 0.88),
        "fairway": [(0.75, 0.88), (0.68, 0.70), (0.55, 0.52), (0.40, 0.35)],
        "green": (0.35, 0.18), "green_shape": "oval",
        "bunkers": [(0.28, 0.22), (0.42, 0.15)],
        "trees_left": True, "trees_right": True,
        "elevation": "uphill",
    },
    6: {  # Juniper - Par 3, 180y - Dramatically downhill
        "tee": (0.35, 0.80),
        "fairway": [],
        "green": (0.60, 0.25), "green_shape": "round",
        "bunkers": [(0.52, 0.30), (0.68, 0.22), (0.55, 0.18)],
        "elevation": "steep_downhill",
    },
    7: {  # Pampas - Par 4, 450y - Uphill, tree-lined
        "tee": (0.45, 0.90),
        "fairway": [(0.45, 0.90), (0.48, 0.72), (0.50, 0.52), (0.50, 0.32)],
        "green": (0.50, 0.18), "green_shape": "oval",
        "bunkers": [(0.40, 0.22), (0.58, 0.16), (0.44, 0.14)],
        "trees_left": True, "trees_right": True,
    },
    8: {  # Yellow Jasmine - Par 5, 570y - Uphill all the way
        "tee": (0.50, 0.92),
        "fairway": [(0.50, 0.92), (0.48, 0.75), (0.42, 0.58), (0.38, 0.42), (0.35, 0.28)],
        "green": (0.35, 0.15), "green_shape": "kidney",
        "bunkers": [(0.28, 0.18), (0.42, 0.12)],
        "mounds": True,
        "elevation": "uphill",
    },
    9: {  # Carolina Cherry - Par 4, 460y - Downhill dogleg left
        "tee": (0.70, 0.88),
        "fairway": [(0.70, 0.88), (0.62, 0.70), (0.50, 0.52), (0.42, 0.35)],
        "green": (0.38, 0.18), "green_shape": "oval",
        "bunkers": [(0.30, 0.22), (0.45, 0.15)],
        "trees_left": True,
        "elevation": "downhill",
    },
    10: {  # Camellia - Par 4, 495y - Dramatic downhill dogleg left
        "tee": (0.70, 0.88),
        "fairway": [(0.70, 0.88), (0.58, 0.68), (0.42, 0.48), (0.30, 0.32)],
        "green": (0.25, 0.18), "green_shape": "oval",
        "bunkers": [(0.18, 0.22), (0.32, 0.15)],
        "trees_left": True, "trees_right": True,
        "elevation": "steep_downhill",
    },
    11: {  # White Dogwood - Par 4, 520y - Dogleg left, pond left of green
        "tee": (0.72, 0.88),
        "fairway": [(0.72, 0.88), (0.62, 0.68), (0.48, 0.50), (0.38, 0.35)],
        "green": (0.32, 0.18), "green_shape": "oval",
        "bunkers": [(0.38, 0.15)],
        "water": [(0.18, 0.15, 0.28, 0.28)],  # Pond left of green
        "trees_left": True, "trees_right": True,
        "amen_corner": True,
    },
    12: {  # Golden Bell - Par 3, 155y - THE iconic hole. Rae's Creek fronting green
        "tee": (0.20, 0.75),
        "fairway": [],
        "green": (0.60, 0.30), "green_shape": "wide_shallow",
        "bunkers": [(0.50, 0.22), (0.70, 0.22), (0.72, 0.35)],
        "water": [(0.25, 0.42, 0.80, 0.52)],  # Rae's Creek
        "trees_right": True,
        "amen_corner": True,
        "hogan_bridge": True,
    },
    13: {  # Azalea - Par 5, 510y - Sharp dogleg left, creek along left/front of green
        "tee": (0.82, 0.85),
        "fairway": [(0.82, 0.85), (0.72, 0.68), (0.55, 0.52), (0.35, 0.40), (0.25, 0.30)],
        "green": (0.20, 0.18), "green_shape": "oval",
        "bunkers": [(0.14, 0.22), (0.26, 0.12)],
        "water": [(0.08, 0.12, 0.22, 0.32)],  # Rae's Creek
        "trees_left": True, "trees_right": True,
        "amen_corner": True,
        "azaleas": True,
    },
    14: {  # Chinese Fir - Par 4, 440y - No bunkers! Only hole without them
        "tee": (0.50, 0.90),
        "fairway": [(0.50, 0.90), (0.48, 0.70), (0.45, 0.50), (0.42, 0.32)],
        "green": (0.40, 0.18), "green_shape": "oval",
        "bunkers": [],  # No bunkers - unique at Augusta
        "trees_left": True, "trees_right": True,
    },
    15: {  # Firethorn - Par 5, 550y - Pond in front of green
        "tee": (0.30, 0.90),
        "fairway": [(0.30, 0.90), (0.35, 0.72), (0.45, 0.55), (0.55, 0.40), (0.62, 0.30)],
        "green": (0.65, 0.18), "green_shape": "oval",
        "bunkers": [(0.58, 0.15), (0.72, 0.20)],
        "water": [(0.52, 0.24, 0.72, 0.34)],  # Pond
        "trees_left": True,
    },
    16: {  # Redbud - Par 3, 170y - Over water to green
        "tee": (0.20, 0.78),
        "fairway": [],
        "green": (0.65, 0.28), "green_shape": "kidney",
        "bunkers": [(0.72, 0.25), (0.58, 0.35), (0.72, 0.35)],
        "water": [(0.30, 0.35, 0.65, 0.55)],  # Large pond
        "trees_right": True,
    },
    17: {  # Nandina - Par 4, 440y - Slight uphill, Eisenhower Tree was here
        "tee": (0.50, 0.90),
        "fairway": [(0.50, 0.90), (0.48, 0.70), (0.45, 0.50), (0.42, 0.32)],
        "green": (0.40, 0.18), "green_shape": "round",
        "bunkers": [(0.32, 0.22), (0.48, 0.15)],
        "trees_left": True, "trees_right": True,
        "elevation": "uphill",
    },
    18: {  # Holly - Par 4, 465y - Dramatic uphill finish
        "tee": (0.30, 0.88),
        "fairway": [(0.30, 0.88), (0.38, 0.70), (0.48, 0.52), (0.55, 0.35)],
        "green": (0.58, 0.18), "green_shape": "oval",
        "bunkers": [(0.50, 0.22), (0.65, 0.18)],
        "trees_left": True, "trees_right": True,
        "elevation": "steep_uphill",
    },
}


def draw_water(draw, coords, w, h):
    """Draw a water hazard."""
    x1, y1, x2, y2 = [int(c * (w if i % 2 == 0 else h)) for i, c in enumerate(coords)]
    draw.ellipse([x1, y1, x2, y2], fill=(64, 140, 200, 180), outline=(40, 100, 160))


def draw_bunker(draw, pos, w, h, size=8):
    """Draw a sand bunker."""
    x, y = int(pos[0] * w), int(pos[1] * h)
    draw.ellipse([x - size, y - size // 2, x + size, y + size // 2],
                 fill=(238, 214, 175), outline=(200, 180, 140))


def draw_green(draw, pos, w, h, shape="oval"):
    """Draw putting green."""
    gx, gy = int(pos[0] * w), int(pos[1] * h)
    if shape == "wide_shallow":
        rx, ry = 22, 10
    elif shape == "kidney":
        rx, ry = 18, 14
    elif shape == "round":
        rx, ry = 14, 14
    elif shape == "oval_wide":
        rx, ry = 20, 12
    else:
        rx, ry = 16, 12

    # Green with slightly different shade
    draw.ellipse([gx - rx, gy - ry, gx + rx, gy + ry],
                 fill=(80, 200, 80), outline=(60, 160, 60))
    # Fringe
    draw.ellipse([gx - rx - 2, gy - ry - 2, gx + rx + 2, gy + ry + 2],
                 outline=(50, 150, 50))

    # Flag pin
    draw.line([(gx, gy), (gx, gy - 14)], fill=(255, 255, 255), width=1)
    draw.polygon([(gx, gy - 14), (gx + 7, gy - 11), (gx, gy - 8)], fill=(255, 0, 0))


def draw_tee_box(draw, pos, w, h):
    """Draw tee box."""
    tx, ty = int(pos[0] * w), int(pos[1] * h)
    draw.rectangle([tx - 6, ty - 4, tx + 6, ty + 4], fill=(45, 130, 45), outline=(30, 100, 30))
    # Tee markers
    draw.ellipse([tx - 4, ty - 1, tx - 2, ty + 1], fill=(255, 255, 255))
    draw.ellipse([tx + 2, ty - 1, tx + 4, ty + 1], fill=(255, 255, 255))


def create_hole_layout(hole_num, layout):
    """Create an accurate hole layout image."""
    w, h = 200, 150
    img = Image.new("RGBA", (w, h), (34, 120, 34, 255))
    draw = ImageDraw.Draw(img)

    # Background rough texture
    random.seed(hole_num * 17)
    for _ in range(200):
        rx, ry = random.randint(0, w), random.randint(0, h)
        shade = random.randint(-8, 8)
        draw.point((rx, ry), fill=(34 + shade, 120 + shade, 34 + shade, 255))

    # Draw trees on sides
    if layout.get("trees_left"):
        for i in range(8):
            ty = random.randint(10, h - 10)
            tx = random.randint(2, 18)
            tr = random.randint(4, 8)
            draw.ellipse([tx - tr, ty - tr, tx + tr, ty + tr], fill=(20, 80, 20))

    if layout.get("trees_right"):
        for i in range(8):
            ty = random.randint(10, h - 10)
            tx = random.randint(w - 18, w - 2)
            tr = random.randint(4, 8)
            draw.ellipse([tx - tr, ty - tr, tx + tr, ty + tr], fill=(20, 80, 20))

    # Draw azaleas for hole 13
    if layout.get("azaleas"):
        for i in range(6):
            ax = random.randint(5, 30)
            ay = random.randint(int(h * 0.3), int(h * 0.6))
            draw.ellipse([ax - 4, ay - 4, ax + 4, ay + 4], fill=(255, 105, 180))

    # Draw fairway
    fairway_pts = layout.get("fairway", [])
    if fairway_pts and len(fairway_pts) >= 2:
        fw = 24  # fairway pixel width
        for i in range(len(fairway_pts) - 1):
            x1, y1 = int(fairway_pts[i][0] * w), int(fairway_pts[i][1] * h)
            x2, y2 = int(fairway_pts[i + 1][0] * w), int(fairway_pts[i + 1][1] * h)
            draw.line([(x1, y1), (x2, y2)], fill=(60, 170, 60), width=fw)

    # Draw water hazards
    for water_coords in layout.get("water", []):
        draw_water(draw, water_coords, w, h)

    # Draw Hogan Bridge (hole 12)
    if layout.get("hogan_bridge"):
        bx = int(0.45 * w)
        by = int(0.47 * h)
        draw.rectangle([bx - 8, by - 2, bx + 8, by + 2], fill=(139, 119, 101))
        draw.rectangle([bx - 8, by - 3, bx + 8, by - 2], fill=(160, 140, 120))

    # Draw bunkers
    for bpos in layout.get("bunkers", []):
        draw_bunker(draw, bpos, w, h)

    # Draw green
    draw_green(draw, layout["green"], w, h, layout.get("green_shape", "oval"))

    # Draw tee box
    draw_tee_box(draw, layout["tee"], w, h)

    # Amen Corner badge
    if layout.get("amen_corner"):
        badge_w = 50
        draw.rounded_rectangle([(w - badge_w - 4, h - 16), (w - 4, h - 4)],
                               radius=3, fill=(0, 0, 0, 160))
        font = get_font(7)
        draw.text((w - badge_w // 2 - 4, h - 14), "AMEN CORNER", fill=(253, 218, 36),
                  font=font, anchor="mt")

    return img


def create_course_hole_images():
    """Create all 18 hole layout images."""
    print("\nCreating accurate Augusta National hole layouts...")

    from masters_helpers import AUGUSTA_HOLES

    for hole_num in range(1, 19):
        layout = AUGUSTA_HOLE_LAYOUTS[hole_num]
        hole_info = AUGUSTA_HOLES[hole_num]
        img = create_hole_layout(hole_num, layout)
        save_path = COURSES_DIR / f"hole_{hole_num:02d}.png"
        img.save(save_path)
        print(f"  [created] hole_{hole_num:02d}.png - {hole_info['name']} "
              f"(Par {hole_info['par']}, {hole_info['yardage']}y)")


# ═══════════════════════════════════════════════════════════════
# COUNTRY FLAGS (small pixel art for LED display)
# ═══════════════════════════════════════════════════════════════

FLAG_COLORS = {
    "USA": [((0, 0, 100), 0.4), ((200, 0, 0), 0.3), ((255, 255, 255), 0.3)],
    "ESP": [((200, 0, 0), 0.25), ((255, 200, 0), 0.50), ((200, 0, 0), 0.25)],
    "ENG": [((255, 255, 255), 1.0)],  # White with red cross
    "AUS": [((0, 0, 128), 1.0)],
    "JPN": [((255, 255, 255), 1.0)],  # White with red circle
    "NIR": [((255, 255, 255), 1.0)],  # Simplified
    "IRL": [((0, 155, 72), 0.33), ((255, 255, 255), 0.34), ((255, 130, 0), 0.33)],
    "NOR": [((200, 16, 32), 1.0)],
    "SWE": [((0, 106, 167), 1.0)],
    "RSA": [((0, 120, 60), 0.34), ((255, 255, 255), 0.08), ((200, 0, 0), 0.08),
            ((255, 255, 255), 0.08), ((0, 0, 128), 0.42)],
    "CAN": [((255, 0, 0), 0.25), ((255, 255, 255), 0.50), ((255, 0, 0), 0.25)],
    "GER": [((0, 0, 0), 0.33), ((220, 0, 0), 0.34), ((255, 200, 0), 0.33)],
    "ARG": [((108, 180, 230), 0.33), ((255, 255, 255), 0.34), ((108, 180, 230), 0.33)],
    "SCO": [((0, 0, 128), 1.0)],
    "WAL": [((255, 255, 255), 0.5), ((0, 128, 0), 0.5)],
    "FIJ": [((0, 0, 128), 1.0)],
}


def create_country_flags():
    """Create tiny country flag images for player cards."""
    print("\nCreating country flag icons...")
    fw, fh = 16, 10

    for country, stripes in FLAG_COLORS.items():
        img = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw horizontal stripes
        y = 0
        for color, ratio in stripes:
            stripe_h = max(1, int(fh * ratio))
            draw.rectangle([(0, y), (fw - 1, y + stripe_h - 1)], fill=color)
            y += stripe_h

        # Special overlays
        if country == "ENG":
            # Red cross on white
            draw.line([(fw // 2, 0), (fw // 2, fh)], fill=(200, 0, 0), width=2)
            draw.line([(0, fh // 2), (fw, fh // 2)], fill=(200, 0, 0), width=2)
        elif country == "JPN":
            # Red circle on white
            cx, cy = fw // 2, fh // 2
            r = min(fw, fh) // 3
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(200, 0, 0))
        elif country == "NOR":
            # Blue cross with white border on red
            draw.line([(fw // 3, 0), (fw // 3, fh)], fill=(255, 255, 255), width=3)
            draw.line([(0, fh // 2), (fw, fh // 2)], fill=(255, 255, 255), width=3)
            draw.line([(fw // 3, 0), (fw // 3, fh)], fill=(0, 32, 91), width=1)
            draw.line([(0, fh // 2), (fw, fh // 2)], fill=(0, 32, 91), width=1)
        elif country == "SWE":
            # Yellow cross on blue
            draw.line([(fw // 3, 0), (fw // 3, fh)], fill=(254, 204, 2), width=2)
            draw.line([(0, fh // 2), (fw, fh // 2)], fill=(254, 204, 2), width=2)
        elif country == "SCO":
            # White X on blue
            draw.line([(0, 0), (fw, fh)], fill=(255, 255, 255), width=1)
            draw.line([(fw, 0), (0, fh)], fill=(255, 255, 255), width=1)
        elif country == "AUS":
            # Union Jack canton + stars (simplified)
            draw.rectangle([(0, 0), (fw // 2, fh // 2)], fill=(0, 0, 128))
            draw.line([(0, 0), (fw // 2, fh // 2)], fill=(255, 0, 0), width=1)
            draw.line([(fw // 2, 0), (0, fh // 2)], fill=(255, 0, 0), width=1)
            # Southern cross (simplified)
            for sx, sy in [(fw * 3 // 4, fh // 4), (fw * 3 // 4, fh * 3 // 4)]:
                draw.point((sx, sy), fill=(255, 255, 255))

        # Border
        draw.rectangle([(0, 0), (fw - 1, fh - 1)], outline=(80, 80, 80))

        img.save(FLAGS_DIR / f"{country}.png")

    print(f"  [created] {len(FLAG_COLORS)} country flag icons")


# ═══════════════════════════════════════════════════════════════
# BACKGROUND TEXTURES
# ═══════════════════════════════════════════════════════════════

def create_background_textures():
    """Create background textures for displays."""
    print("\nCreating background textures...")

    # Masters green gradient
    for res_name, (w, h) in [("64x32", (64, 32)), ("128x64", (128, 64))]:
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        c1 = (0, 70, 40)
        c2 = (0, 110, 65)
        for y in range(h):
            ratio = y / h
            r = int(c1[0] + (c2[0] - c1[0]) * ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * ratio)
            draw.line([(0, y), (w, y)], fill=(r, g, b))
        img.save(BACKGROUNDS_DIR / f"masters_green_gradient_{res_name}.png")
        print(f"  [created] masters_green_gradient_{res_name}.png")

    # Also save a default one
    img = Image.new("RGB", (128, 64))
    draw = ImageDraw.Draw(img)
    for y in range(64):
        ratio = y / 64
        g_val = int(70 + 40 * ratio)
        draw.line([(0, y), (127, y)], fill=(0, g_val, int(40 + 25 * ratio)))
    img.save(BACKGROUNDS_DIR / "masters_green_gradient.png")

    # Augusta texture
    img2 = Image.new("RGB", (128, 64), (34, 120, 34))
    draw2 = ImageDraw.Draw(img2)
    random.seed(42)
    for _ in range(200):
        x, y = random.randint(0, 127), random.randint(0, 63)
        s = random.randint(-8, 8)
        draw2.point((x, y), fill=(max(0, 34 + s), max(0, 120 + s), max(0, 34 + s)))
    img2.save(BACKGROUNDS_DIR / "augusta_green_texture.png")
    print(f"  [created] augusta_green_texture.png")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Download and create all assets."""
    print("=" * 60)
    print("  Masters Tournament Asset Downloader v2.0")
    print("  Real headshots, accurate course layouts, authentic branding")
    print("=" * 60)

    print("\n[1/7] Creating Masters logo...")
    create_masters_logo()
    create_masters_logo_small()

    print("\n[2/7] Creating green jacket icon...")
    create_green_jacket_icon()

    print("\n[3/7] Creating azalea flower icon...")
    create_azalea_flower()

    print("\n[4/7] Creating golf icons...")
    create_golf_icons()

    print("\n[5/7] Creating accurate course hole layouts...")
    create_course_hole_images()

    print("\n[6/7] Creating country flags...")
    create_country_flags()

    print("\n[7/7] Creating background textures...")
    create_background_textures()

    # Optional: download real headshots
    try:
        print("\n[BONUS] Downloading real ESPN player headshots...")
        download_player_headshots()
    except Exception as e:
        print(f"  [skip] Headshot download failed (network?): {e}")

    # Summary
    print("\n" + "=" * 60)
    counts = {
        "Logos": len(list(LOGOS_DIR.glob("*.png"))),
        "Course Holes": len(list(COURSES_DIR.glob("*.png"))),
        "Icons": len(list(ICONS_DIR.glob("*.png"))),
        "Backgrounds": len(list(BACKGROUNDS_DIR.glob("*.png"))),
        "Country Flags": len(list(FLAGS_DIR.glob("*.png"))),
        "Player Headshots": len(list(PLAYERS_DIR.glob("*.png"))),
    }
    total = sum(counts.values())
    print("  Asset Summary:")
    for label, count in counts.items():
        print(f"    {label}: {count} files")
    print(f"    TOTAL: {total} files")
    print("=" * 60)


if __name__ == "__main__":
    main()
