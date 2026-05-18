"""
Simplified LogoDownloader for plugin use
"""

import logging
import requests
from typing import List
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class LogoDownloader:
    """Simplified logo downloader for team logos from ESPN API."""
    
    def __init__(self, request_timeout: int = 30, retry_attempts: int = 3):
        """Initialize the logo downloader with HTTP session and retry logic."""
        self.request_timeout = request_timeout
        self.retry_attempts = retry_attempts
        
        # Set up session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=retry_attempts,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Set up headers
        self.headers = {
            'User-Agent': 'LEDMatrix/1.0 (https://github.com/yourusername/LEDMatrix; contact@example.com)',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
    
    @staticmethod
    def normalize_abbreviation(abbr: str) -> str:
        """Normalize team abbreviation for filename."""
        return abbr.upper()
    
    @staticmethod
    def get_logo_filename_variations(abbr: str) -> List[str]:
        """Get possible filename variations for a team abbreviation."""
        normalized = LogoDownloader.normalize_abbreviation(abbr)
        variations = [f"{normalized}.png"]
        
        # Add common variations
        if normalized == "TA&M":
            variations.append("TAANDM.png")
        elif normalized == "TAMU":
            variations.append("TA&M.png")
            
        return variations

def download_missing_logo(sport_key: str, team_id: str, team_abbr: str, logo_path: Path, logo_url: str = None) -> bool:
    """
    Download missing logo for a team.
    
    Args:
        sport_key: Sport key (e.g., 'nfl', 'ncaa_fb')
        team_id: Team ID
        team_abbr: Team abbreviation
        logo_path: Path where logo should be saved
        logo_url: Optional logo URL
        
    Returns:
        True if logo was downloaded successfully, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        logo_path.parent.mkdir(parents=True, exist_ok=True)
        
        # If we have a logo URL, try to download it
        if logo_url:
            response = requests.get(logo_url, timeout=30)
            if response.status_code == 200:
                with open(logo_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"Downloaded logo for {team_abbr} from {logo_url}")
                return True
        
        # If no URL or download failed, create a placeholder
        create_placeholder_logo(team_abbr, logo_path)
        return True
        
    except Exception as e:
        logger.error(f"Failed to download logo for {team_abbr}: {e}")
        # Create placeholder as fallback
        create_placeholder_logo(team_abbr, logo_path)
        return False

def create_placeholder_logo(team_abbr: str, logo_path: Path) -> None:
    """Create a simple placeholder logo."""
    try:
        # Create a simple text-based logo
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Try to load a font
        try:
            font = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
        
        # Draw team abbreviation
        text = team_abbr[:3]  # Limit to 3 characters
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (64 - text_width) // 2
        y = (64 - text_height) // 2
        
        # Draw white text with black outline
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=(255, 255, 255))
        
        # Save the placeholder
        img.save(logo_path)
        logger.info(f"Created placeholder logo for {team_abbr}")
        
    except Exception as e:
        logger.error(f"Failed to create placeholder logo for {team_abbr}: {e}")
