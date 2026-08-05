"""
Chart Renderer for Stock Ticker Plugin

Handles all chart drawing functionality including mini charts
and full-screen chart displays.
"""

from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from PIL import Image, ImageDraw

# Import common utilities
from src.common import TextHelper


def _pixel_draw(image):
    """ImageDraw that renders text crisply on the LED grid.

    PIL anti-aliases by default, blending glyph edges into dim partial-lit
    pixels. On a 1:1 LED matrix those read as blur rather than smoothing, so
    every draw surface here -- including scratch canvases used only to measure
    text -- sets fontmode "1" for 1-bit glyph rendering. Measuring through the
    same helper keeps metrics and rendering in agreement.
    """
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    return draw



class StockChartRenderer:
    """Handles rendering of stock and cryptocurrency charts."""
    
    def __init__(self, config: Dict[str, Any], display_width: int, display_height: int, logger):
        """Initialize the chart renderer."""
        self.config = config
        self.display_width = display_width
        self.display_height = display_height
        self.logger = logger
        
        # Chart configuration
        self.chart_colors = {
            'background': (0, 0, 0),
            'grid': (50, 50, 50),
            'line': (0, 255, 0),
            'line_negative': (255, 0, 0),
            'text': (255, 255, 255),
            'axis': (128, 128, 128)
        }
        
        # Initialize text helper
        self.text_helper = TextHelper(logger=logger)
        
        # Cache fonts to avoid reloading every time
        self._cached_fonts = None
    
    def _get_fonts(self):
        """Get cached fonts, loading them only once."""
        if self._cached_fonts is None:
            self._cached_fonts = self.text_helper.load_fonts()
        return self._cached_fonts
    
    def draw_chart(self, symbol: str, data: Dict[str, Any]) -> None:
        """Draw a full-screen chart for a stock or cryptocurrency."""
        try:
            if 'price_history' not in data or len(data['price_history']) < 2:
                self.logger.warning("Insufficient price history for chart: %s", symbol)
                return
            
            # Create chart image
            chart_image = self._create_chart_image(symbol, data)
            
            if chart_image:
                # Display the chart (this would integrate with display manager)
                self.logger.info("Chart drawn for %s", symbol)
            
        except Exception as e:
            self.logger.error("Error drawing chart for %s: %s", symbol, e)
    
    def _create_chart_image(self, symbol: str, data: Dict[str, Any]) -> Optional[Image.Image]:
        """Create a full-screen chart image."""
        try:
            # Create image
            image = Image.new('RGB', (self.display_width, self.display_height), self.chart_colors['background'])
            draw = _pixel_draw(image)
            
            # Get price history
            price_history = data['price_history']
            if len(price_history) < 2:
                return None
            
            # Extract prices and timestamps
            prices = [point['price'] for point in price_history if 'price' in point]
            timestamps = [point['timestamp'] for point in price_history if 'timestamp' in point]
            
            if len(prices) < 2:
                return None
            
            # Calculate chart dimensions
            margin = 10
            chart_width = self.display_width - (margin * 2)
            chart_height = self.display_height - (margin * 2)
            chart_x = margin
            chart_y = margin
            
            # Normalize prices
            min_price = min(prices)
            max_price = max(prices)
            price_range = max_price - min_price
            
            if price_range == 0:
                # All prices are the same
                y = chart_y + chart_height // 2
                draw.line([(chart_x, y), (chart_x + chart_width, y)], 
                         fill=self.chart_colors['line'], width=2)
            else:
                # Draw price line
                points = []
                for i, price in enumerate(prices):
                    x = chart_x + (i * chart_width) // (len(prices) - 1)
                    y = chart_y + chart_height - int(((price - min_price) / price_range) * chart_height)
                    points.append((x, y))
                
                if len(points) > 1:
                    # Determine line color based on overall trend
                    first_price = prices[0]
                    last_price = prices[-1]
                    line_color = self.chart_colors['line_negative'] if last_price < first_price else self.chart_colors['line']
                    
                    draw.line(points, fill=line_color, width=2)
            
            # Draw title
            self._draw_chart_title(draw, symbol, data)
            
            # Draw price labels
            self._draw_price_labels(draw, min_price, max_price, chart_x, chart_y, chart_height)
            
            # Draw time labels
            self._draw_time_labels(draw, timestamps, chart_x, chart_y, chart_width, chart_height)
            
            return image
            
        except Exception as e:
            self.logger.error("Error creating chart image: %s", e)
            return None
    
    def _draw_chart_title(self, draw: ImageDraw.Draw, symbol: str, data: Dict[str, Any]) -> None:
        """Draw chart title with current price and change."""
        try:
            # Load font
            fonts = self._get_fonts()
            title_font = fonts.get('score')
            
            # Create title text
            display_symbol = symbol.replace('-USD', '') if data.get('is_crypto', False) else symbol
            price = data.get('price', 0)
            change = data.get('change', 0)
            
            title_text = f"{display_symbol} - ${price:.2f}"
            change_text = f"{change:+.2f} ({change:+.1f}%)"
            
            # Draw title
            title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (self.display_width - title_width) // 2
            draw.text((title_x, 2), title_text, font=title_font, fill=self.chart_colors['text'])
            
            # Draw change
            change_bbox = draw.textbbox((0, 0), change_text, font=title_font)
            change_width = change_bbox[2] - change_bbox[0]
            change_x = (self.display_width - change_width) // 2
            change_color = self.chart_colors['line'] if change >= 0 else self.chart_colors['line_negative']
            draw.text((change_x, 12), change_text, font=title_font, fill=change_color)
            
        except Exception as e:
            self.logger.error("Error drawing chart title: %s", e)
    
    def _draw_price_labels(self, draw: ImageDraw.Draw, min_price: float, max_price: float, 
                          chart_x: int, chart_y: int, chart_height: int) -> None:
        """Draw price labels on the Y-axis."""
        try:
            # Load font
            fonts = self._get_fonts()
            label_font = fonts.get('time')
            
            # Draw price labels
            price_range = max_price - min_price
            if price_range == 0:
                # Single price
                price_text = f"${min_price:.2f}"
                label_bbox = draw.textbbox((0, 0), price_text, font=label_font)
                label_width = label_bbox[2] - label_bbox[0]
                label_x = chart_x - label_width - 5
                label_y = chart_y + chart_height // 2
                draw.text((label_x, label_y), price_text, font=label_font, fill=self.chart_colors['text'])
            else:
                # Multiple prices
                for i in range(3):  # Show 3 price levels
                    price = min_price + (i * price_range) / 2
                    price_text = f"${price:.2f}"
                    label_bbox = draw.textbbox((0, 0), price_text, font=label_font)
                    label_width = label_bbox[2] - label_bbox[0]
                    label_x = chart_x - label_width - 5
                    label_y = chart_y + int((i * chart_height) / 2) - 5
                    draw.text((label_x, label_y), price_text, font=label_font, fill=self.chart_colors['text'])
            
        except Exception as e:
            self.logger.error("Error drawing price labels: %s", e)
    
    def _draw_time_labels(self, draw: ImageDraw.Draw, timestamps: List[datetime], 
                         chart_x: int, chart_y: int, chart_width: int, chart_height: int) -> None:
        """Draw time labels on the X-axis."""
        try:
            # Load font
            fonts = self._get_fonts()
            label_font = fonts.get('time')
            
            if not timestamps:
                return
            
            # Draw time labels
            for i in range(0, len(timestamps), max(1, len(timestamps) // 3)):  # Show up to 3 time labels
                timestamp = timestamps[i]
                time_text = timestamp.strftime("%H:%M")
                label_bbox = draw.textbbox((0, 0), time_text, font=label_font)
                label_width = label_bbox[2] - label_bbox[0]
                label_x = chart_x + (i * chart_width) // (len(timestamps) - 1) - (label_width // 2)
                label_y = chart_y + chart_height + 2
                draw.text((label_x, label_y), time_text, font=label_font, fill=self.chart_colors['text'])
            
        except Exception as e:
            self.logger.error("Error drawing time labels: %s", e)
    
    def draw_mini_chart(self, draw: ImageDraw.Draw, price_history: List[Dict], 
                       width: int, height: int, color: Tuple[int, int, int]) -> None:
        """Draw a mini price chart (used in scrolling display)."""
        if len(price_history) < 2:
            return
        
        try:
            # Chart dimensions
            chart_width = width // 4
            chart_height = height - 4
            chart_x = width - chart_width - 2
            chart_y = 2
            
            # Extract prices
            prices = [point['price'] for point in price_history if 'price' in point]
            if len(prices) < 2:
                return
            
            # Normalize prices to chart height
            min_price = min(prices)
            max_price = max(prices)
            price_range = max_price - min_price
            
            if price_range == 0:
                # All prices are the same, draw a horizontal line
                y = chart_y + chart_height // 2
                draw.line([(chart_x, y), (chart_x + chart_width, y)], fill=color, width=1)
                return
            
            # Draw chart line
            points = []
            for i, price in enumerate(prices):
                x = chart_x + (i * chart_width) // (len(prices) - 1)
                y = chart_y + chart_height - int(((price - min_price) / price_range) * chart_height)
                points.append((x, y))
            
            if len(points) > 1:
                draw.line(points, fill=color, width=1)
                
        except Exception as e:
            self.logger.error("Error drawing mini chart: %s", e)
