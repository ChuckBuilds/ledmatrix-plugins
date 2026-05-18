#!/usr/bin/env python3
"""
Download country flags from flagcdn.com for the Olympics plugin.

Downloads low-resolution flag images suitable for LED matrix displays.
Saves to assets/country_flags/ with ISO 3166-1 alpha-3 naming.

Usage:
    python scripts/download_flags.py
"""

import sys
import time
from io import BytesIO
from pathlib import Path

try:
    import requests
    from PIL import Image
except ImportError:
    print("Required packages not installed. Run:")
    print("  pip install requests pillow")
    sys.exit(1)

# Target flag size for LED matrix (width x height)
FLAG_SIZE = (16, 10)

# Output directory
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "assets" / "country_flags"

# Countries commonly in Winter/Summer Olympics
# Format: (alpha-3 IOC code, alpha-2 ISO code for flagcdn)
OLYMPIC_COUNTRIES = [
    # Top medal winners - Winter Olympics
    ("USA", "us"),
    ("NOR", "no"),
    ("GER", "de"),
    ("CAN", "ca"),
    ("NED", "nl"),
    ("SWE", "se"),
    ("AUT", "at"),
    ("SUI", "ch"),
    ("FRA", "fr"),
    ("ITA", "it"),
    ("JPN", "jp"),
    ("CHN", "cn"),
    ("KOR", "kr"),
    ("RUS", "ru"),
    ("GBR", "gb"),
    ("AUS", "au"),
    ("FIN", "fi"),
    ("CZE", "cz"),
    ("POL", "pl"),
    ("SLO", "si"),
    ("SVK", "sk"),
    ("BEL", "be"),
    ("ESP", "es"),
    ("NZL", "nz"),
    ("BRA", "br"),
    ("UKR", "ua"),
    ("KAZ", "kz"),
    ("BLR", "by"),
    ("LAT", "lv"),
    ("EST", "ee"),
    ("LTU", "lt"),
    ("HUN", "hu"),
    ("CRO", "hr"),
    ("DEN", "dk"),
    ("IRL", "ie"),
    ("POR", "pt"),
    ("GRE", "gr"),
    ("TUR", "tr"),
    ("MEX", "mx"),
    ("ARG", "ar"),
]

# flagcdn.com URL template - provides PNG flags at various sizes
# Using w40 (40px wide) for good quality before downsampling
FLAGCDN_URL = "https://flagcdn.com/w40/{code}.png"


def download_flag(ioc_code: str, iso2_code: str) -> bool:
    """Download a single flag and save as PNG."""
    try:
        url = FLAGCDN_URL.format(code=iso2_code.lower())

        print(f"  Downloading {ioc_code} ({iso2_code})...", end=" ", flush=True)

        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'LEDMatrix-Olympics-Plugin/1.0'
        })
        response.raise_for_status()

        # Open image from response
        img = Image.open(BytesIO(response.content))

        # Convert to RGB if necessary (remove alpha)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (0, 0, 0))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1])
            img = background

        # Resize to target size
        img = img.resize(FLAG_SIZE, Image.Resampling.LANCZOS)

        # Save
        output_path = OUTPUT_DIR / f"{ioc_code.lower()}.png"
        img.save(output_path, 'PNG')

        print("OK")
        return True

    except requests.RequestException as e:
        print(f"FAILED (network: {e})")
        return False
    except Exception as e:
        print(f"FAILED ({e})")
        return False


def main():
    print("=" * 50)
    print("Olympics Plugin - Flag Downloader")
    print("=" * 50)
    print("Source: flagcdn.com")
    print(f"Target size: {FLAG_SIZE[0]}x{FLAG_SIZE[1]} pixels")
    print(f"Output: {OUTPUT_DIR}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Download flags
    success = 0
    failed = 0

    print(f"Downloading {len(OLYMPIC_COUNTRIES)} flags...")
    print()

    for ioc_code, iso2_code in OLYMPIC_COUNTRIES:
        if download_flag(ioc_code, iso2_code):
            success += 1
        else:
            failed += 1

        # Small delay to be nice to the server
        time.sleep(0.2)

    print()
    print("=" * 50)
    print(f"Complete: {success} downloaded, {failed} failed")
    print("=" * 50)

    if success > 0:
        print()
        print("Flags saved to:")
        print(f"  {OUTPUT_DIR}/")
        for f in sorted(OUTPUT_DIR.glob("*.png")):
            print(f"    {f.name}")


if __name__ == "__main__":
    main()
