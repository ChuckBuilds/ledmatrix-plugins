"""
Display Renderer for Stock Ticker Plugin

Handles all display creation, layout, and rendering logic for both
scrolling and static display modes.
"""

import os
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

# Import common utilities
from src.common import ScrollHelper, LogoHelper, TextHelper


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



class StockDisplayRenderer:
    """Handles rendering of stock and cryptocurrency displays."""
    
    def __init__(self, config: Dict[str, Any], display_width: int, display_height: int, logger):
        """Initialize the display renderer."""
        self.config = config
        self.display_width = display_width
        self.display_height = display_height
        self.logger = logger
        
        # Display configuration
        self.toggle_chart = config.get('display', {}).get('toggle_chart', True)
        self.stock_gap = int(config.get('display', {}).get('stock_gap', 32))

        # Chart size is a definite pixel value in BOTH dimensions so it stays a
        # fixed, compact size no matter how large the panel is. Previously width
        # was a fraction of the (display-scaled) canvas and height a fraction of
        # the display height, so the chart ballooned on wide chains and on tall
        # 4x panels. Both are clamped to the panel so they never overflow.
        display_cfg = config.get('display', {})
        self.chart_width_px = int(min(max(int(display_cfg.get('chart_width_px', 64)), 8), 256))
        self.chart_height_px = int(min(max(int(display_cfg.get('chart_height_px', 32)), 6), 256))
        
        # Load colors from customization structure (organized by element: symbol, price, price_delta)
        # Support both new format (customization.stocks.*) and old format (top-level) for backwards compatibility
        customization = config.get('customization', {})
        stocks_custom = customization.get('stocks', {})
        crypto_custom = customization.get('crypto', {})
        
        # Stock colors - new format: customization.stocks.symbol/price/price_delta
        # Old format fallback: top-level text_color, positive_color, negative_color
        # Ensure all color values are integers (RGB values from config might be floats)
        if stocks_custom.get('symbol') and 'text_color' in stocks_custom['symbol']:
            # New format: separate colors for symbol and price
            symbol_color_list = stocks_custom['symbol'].get('text_color', [255, 255, 255])
            price_color_list = stocks_custom.get('price', {}).get('text_color', [255, 255, 255])
            self.symbol_text_color = tuple(int(c) for c in symbol_color_list)
            self.price_text_color = tuple(int(c) for c in price_color_list)
        else:
            # Old format: shared text_color for symbol and price
            old_text_color_list = config.get('text_color', [255, 255, 255])
            old_text_color = tuple(int(c) for c in old_text_color_list)
            self.symbol_text_color = old_text_color
            self.price_text_color = old_text_color
        
        price_delta_custom = stocks_custom.get('price_delta', {})
        if price_delta_custom:
            positive_color_list = price_delta_custom.get('positive_color', [0, 255, 0])
            negative_color_list = price_delta_custom.get('negative_color', [255, 0, 0])
            self.positive_color = tuple(int(c) for c in positive_color_list)
            self.negative_color = tuple(int(c) for c in negative_color_list)
        else:
            # Old format fallback
            positive_color_list = config.get('positive_color', [0, 255, 0])
            negative_color_list = config.get('negative_color', [255, 0, 0])
            self.positive_color = tuple(int(c) for c in positive_color_list)
            self.negative_color = tuple(int(c) for c in negative_color_list)
        
        # Crypto colors - new format: customization.crypto.symbol/price/price_delta
        # Old format fallback: customization.crypto.text_color, etc.
        if crypto_custom.get('symbol') and 'text_color' in crypto_custom['symbol']:
            # New format: separate colors for symbol and price
            crypto_symbol_color_list = crypto_custom['symbol'].get('text_color', [255, 215, 0])
            crypto_price_color_list = crypto_custom.get('price', {}).get('text_color', [255, 215, 0])
            self.crypto_symbol_text_color = tuple(int(c) for c in crypto_symbol_color_list)
            self.crypto_price_text_color = tuple(int(c) for c in crypto_price_color_list)
        else:
            # Old format: shared text_color for symbol and price
            old_crypto_text_color_list = crypto_custom.get('text_color', [255, 215, 0])
            old_crypto_text_color = tuple(int(c) for c in old_crypto_text_color_list)
            self.crypto_symbol_text_color = old_crypto_text_color
            self.crypto_price_text_color = old_crypto_text_color
        
        crypto_price_delta_custom = crypto_custom.get('price_delta', {})
        if crypto_price_delta_custom:
            crypto_positive_color_list = crypto_price_delta_custom.get('positive_color', [0, 255, 0])
            crypto_negative_color_list = crypto_price_delta_custom.get('negative_color', [255, 0, 0])
            self.crypto_positive_color = tuple(int(c) for c in crypto_positive_color_list)
            self.crypto_negative_color = tuple(int(c) for c in crypto_negative_color_list)
        else:
            # Old format fallback
            crypto_positive_color_list = crypto_custom.get('positive_color', [0, 255, 0])
            crypto_negative_color_list = crypto_custom.get('negative_color', [255, 0, 0])
            self.crypto_positive_color = tuple(int(c) for c in crypto_positive_color_list)
            self.crypto_negative_color = tuple(int(c) for c in crypto_negative_color_list)
        
        # Initialize helpers
        self.logo_helper = LogoHelper(display_width, display_height, logger=logger)
        self.text_helper = TextHelper(logger=self.logger)
        
        # Initialize scroll helper
        self.scroll_helper = ScrollHelper(display_width, display_height, logger)
        
        # Load custom fonts from config
        # Fonts are under customization.stocks/crypto.symbol/price/price_delta
        # For backwards compatibility, try to load from customization.fonts first
        fonts_config = customization.get('fonts', {})
        if fonts_config:
            # Old format: fonts at customization.fonts level (shared for stocks and crypto)
            self.symbol_font = self._load_custom_font_from_element_config(fonts_config.get('symbol', {}))
            self.price_font = self._load_custom_font_from_element_config(fonts_config.get('price', {}))
            self.price_delta_font = self._load_custom_font_from_element_config(fonts_config.get('price_delta', {}))
        else:
            # New format: fonts at customization.stocks/crypto.symbol/price/price_delta
            # Use stocks font config (crypto can override later if needed, but currently shares fonts)
            stocks_custom = customization.get('stocks', {})
            self.symbol_font = self._load_custom_font_from_element_config(stocks_custom.get('symbol', {}))
            self.price_font = self._load_custom_font_from_element_config(stocks_custom.get('price', {}))
            self.price_delta_font = self._load_custom_font_from_element_config(stocks_custom.get('price_delta', {}))
    
    @staticmethod
    def _bdf_pixel_size(path):
        """The pixel size a .bdf font declares, or None if it does not."""
        try:
            with open(path, "r", encoding="latin-1") as handle:
                for line in handle:
                    if line.startswith("PIXEL_SIZE"):
                        return int(line.split()[1])
                    if line.startswith("CHARS"):
                        break  # past the header; no point reading the glyphs
        except (OSError, ValueError, IndexError):
            return None
        return None

    def _load_custom_font_from_element_config(self, element_config: Dict[str, Any]) -> ImageFont.FreeTypeFont:
        """
        Load a custom font from an element configuration dictionary.
        
        Args:
            element_config: Configuration dict for a single element (symbol, price, or price_delta)
                           containing 'font' and 'font_size' keys
            
        Returns:
            PIL ImageFont object
        """
        # Get font name and size, with defaults
        font_name = element_config.get('font', 'PressStart2P-Regular.ttf')
        font_size = int(element_config.get('font_size', 8))  # Ensure integer for PIL
        
        # Build font path
        font_path = os.path.join('assets', 'fonts', font_name)
        
        # Try to load the font
        try:
            if os.path.exists(font_path):
                # Try loading as TTF first (works for both TTF and some BDF files with PIL)
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    self.logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    # A .bdf is a bitmap face that exists at exactly one pixel
                    # size; FreeType refuses every other. Retry at the size the
                    # file declares rather than dropping to the default font --
                    # otherwise picking 5x7.bdf works at size 7 and nowhere else.
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        self.logger.debug(f"Loaded BDF font: {font_name} at size {font_size}")
                        return font
                    except OSError:
                        native = self._bdf_pixel_size(font_path)
                        if native is not None and native != font_size:
                            try:
                                font = ImageFont.truetype(font_path, native)
                                self.logger.debug(
                                    "Loaded bitmap font %s at its native size %d "
                                    "(requested %d)", font_name, native, font_size)
                                return font
                            except OSError:
                                pass
                        self.logger.warning(f"Could not load BDF font {font_name} with PIL, using default")
                        # Fall through to default
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, using default")
        
        # Fall back to default font
        default_font_path = os.path.join('assets', 'fonts', 'PressStart2P-Regular.ttf')
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                self.logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()
    
    def create_stock_display(self, symbol: str, data: Dict[str, Any]) -> Image.Image:
        """Create a scrolling display image for a single stock or crypto.

        The per-entry canvas is sized to the actual content (logo + text +
        fixed-size chart) so there is no dead trailing space between entries and
        the chart sits right after the price without ever overlapping it."""
        height = int(self.display_height)
        is_crypto = data.get('is_crypto', False)

        # Use custom fonts loaded from config
        symbol_font = self.symbol_font
        price_font = self.price_font
        change_font = self.price_delta_font

        # Create text elements
        display_symbol = symbol.replace('-USD', '') if is_crypto else symbol
        symbol_text = display_symbol
        price_text = f"${data['price']:.2f}"

        # Build change text based on show_change and show_percentage flags
        # Get flags from config (stock-specific or crypto-specific)
        if is_crypto:
            show_change = self.config.get('crypto', {}).get('show_change', True)
            show_percentage = self.config.get('crypto', {}).get('show_percentage', True)
        else:
            show_change = self.config.get('show_change', True)
            show_percentage = self.config.get('show_percentage', True)

        # Build change text components
        change_parts = []
        if show_change:
            change_parts.append(f"{data['change']:+.2f}")
        if show_percentage:
            # Use change_percent if available, otherwise calculate from change and open
            if 'change_percent' in data:
                change_parts.append(f"({data['change_percent']:+.1f}%)")
            elif 'open' in data and data['open'] > 0:
                change_percent = (data['change'] / data['open']) * 100
                change_parts.append(f"({change_percent:+.1f}%)")

        change_text = " ".join(change_parts) if change_parts else ""

        # Get colors based on change
        if data['change'] >= 0:
            change_color = self.positive_color if not is_crypto else self.crypto_positive_color
        else:
            change_color = self.negative_color if not is_crypto else self.crypto_negative_color

        # Use symbol color for symbol, price color for price
        symbol_color = self.symbol_text_color if not is_crypto else self.crypto_symbol_text_color
        price_color = self.price_text_color if not is_crypto else self.crypto_price_text_color

        # Measure the text on a scratch canvas so the real canvas can be sized to
        # the content (rather than a display-scaled guess that then needs clamping).
        mdraw = _pixel_draw(Image.new('RGB', (1, 1)))
        symbol_bbox = mdraw.textbbox((0, 0), symbol_text, font=symbol_font)
        price_bbox = mdraw.textbbox((0, 0), price_text, font=price_font)
        if change_text:
            change_bbox = mdraw.textbbox((0, 0), change_text, font=change_font)
            change_height = int(change_bbox[3] - change_bbox[1])
        else:
            change_bbox = (0, 0, 0, 0)
            change_height = 0

        # Logo (load up front so its width feeds the layout)
        logo_x = 4  # Margin from left edge (used for logo_right even if logo is missing)
        logo = self._get_stock_logo(symbol, is_crypto)
        logo_right = int(logo_x + logo.width) if logo else int(logo_x)
        logo_gap = 8  # px between logo right edge and text start

        # Text column sits just right of the logo, centered on the widest line.
        symbol_width = int(symbol_bbox[2] - symbol_bbox[0])
        price_width = int(price_bbox[2] - price_bbox[0])
        change_width = int(change_bbox[2] - change_bbox[0]) if change_text else 0
        max_text_width = max(symbol_width, price_width, change_width, 1)
        column_x = logo_right + logo_gap + (max_text_width // 2)
        text_right = column_x + (max_text_width // 2)

        # Chart sits just right of the text; size the canvas to exactly fit it.
        chart_gap = 6      # px between the price text and the chart
        right_margin = 4   # px of breathing room after the content
        draw_chart = (self.toggle_chart and 'price_history' in data
                      and len(data['price_history']) >= 2)
        if draw_chart:
            chart_x = text_right + chart_gap
            content_right = chart_x + self.chart_width_px + right_margin
        else:
            content_right = text_right + 8  # small right margin
        width = int(content_right)

        # Real canvas, sized to the content
        image = Image.new('RGB', (width, height), (0, 0, 0))
        draw = _pixel_draw(image)

        # Draw the logo on the left, vertically centered
        if logo:
            logo_y = int((height - logo.height) // 2)
            image.paste(logo, (int(logo_x), logo_y), logo)

        # Vertically center the text block - adjust gaps based on chart toggle
        # Match old stock_manager: text_gap = 2 if self.toggle_chart else 1
        text_gap = 2 if self.toggle_chart else 1
        change_gap = text_gap if change_text else 0
        symbol_height = int(symbol_bbox[3] - symbol_bbox[1])
        price_height = int(price_bbox[3] - price_bbox[1])
        total_text_height = symbol_height + price_height + change_height + (text_gap + change_gap)
        start_y = int((height - total_text_height) // 2)

        # Draw symbol
        symbol_x = int(column_x - (symbol_width / 2))
        draw.text((symbol_x, start_y), symbol_text, font=symbol_font, fill=symbol_color)

        # Draw price
        price_x = int(column_x - (price_width / 2))
        price_y = int(start_y + symbol_height + text_gap)
        draw.text((price_x, price_y), price_text, font=price_font, fill=price_color)

        # Draw change with color based on value (only if change_text is not empty)
        if change_text:
            change_x = int(column_x - (change_width / 2))
            change_y = int(price_y + price_height + text_gap)
            draw.text((change_x, change_y), change_text, font=change_font, fill=change_color)

        # Draw the mini chart immediately to the right of the text column.
        if draw_chart:
            self._draw_mini_chart(draw, data['price_history'], width, height,
                                  change_color, chart_x=chart_x)

        return image
    
    def create_static_display(self, symbol: str, data: Dict[str, Any]) -> Image.Image:
        """Create a static display for one stock/crypto (no scrolling)."""
        # Ensure dimensions are integers
        image = Image.new('RGB', (int(self.display_width), int(self.display_height)), (0, 0, 0))
        draw = _pixel_draw(image)
        
        is_crypto = data.get('is_crypto', False)
        
        # Draw logo
        logo = self._get_stock_logo(symbol, is_crypto)
        if logo:
            # Ensure positions are integers
            logo_x = 5
            logo_y = int((int(self.display_height) - logo.height) // 2)
            image.paste(logo, (int(logo_x), int(logo_y)), logo)
        
        # Use custom fonts loaded from config
        symbol_font = self.symbol_font
        price_font = self.price_font
        change_font = self.price_delta_font
        
        # Create text
        display_symbol = symbol.replace('-USD', '') if is_crypto else symbol
        symbol_text = display_symbol
        price_text = f"${data['price']:.2f}"
        
        # Build change text based on show_change and show_percentage flags
        if is_crypto:
            show_change = self.config.get('crypto', {}).get('show_change', True)
            show_percentage = self.config.get('crypto', {}).get('show_percentage', True)
        else:
            show_change = self.config.get('show_change', True)
            show_percentage = self.config.get('show_percentage', True)
        
        # Build change text components
        change_parts = []
        if show_change:
            change_parts.append(f"{data['change']:+.2f}")
        if show_percentage:
            if 'change_percent' in data:
                change_parts.append(f"({data['change_percent']:+.1f}%)")
            elif 'open' in data and data['open'] > 0:
                change_percent = (data['change'] / data['open']) * 100
                change_parts.append(f"({change_percent:+.1f}%)")
        
        change_text = " ".join(change_parts) if change_parts else ""
        
        # Get colors
        if data['change'] >= 0:
            change_color = self.positive_color if not is_crypto else self.crypto_positive_color
        else:
            change_color = self.negative_color if not is_crypto else self.crypto_negative_color
        
        # Use symbol color for symbol, price color for price
        symbol_color = self.symbol_text_color if not is_crypto else self.crypto_symbol_text_color
        price_color = self.price_text_color if not is_crypto else self.crypto_price_text_color
        
        # Calculate positions
        symbol_bbox = draw.textbbox((0, 0), symbol_text, font=symbol_font)
        price_bbox = draw.textbbox((0, 0), price_text, font=price_font)
        
        # Only calculate change_bbox if change_text is not empty
        if change_text:
            change_bbox = draw.textbbox((0, 0), change_text, font=change_font)
        else:
            change_bbox = (0, 0, 0, 0)
        
        # Center everything - ensure integer
        center_x = int(self.display_width) // 2
        
        # Draw symbol
        symbol_width = int(symbol_bbox[2] - symbol_bbox[0])
        symbol_x = int(center_x - (symbol_width / 2))
        draw.text((symbol_x, 5), symbol_text, font=symbol_font, fill=symbol_color)
        
        # Draw price
        price_width = int(price_bbox[2] - price_bbox[0])
        price_x = int(center_x - (price_width / 2))
        draw.text((price_x, 15), price_text, font=price_font, fill=price_color)
        
        # Draw change (only if change_text is not empty)
        if change_text:
            change_width = int(change_bbox[2] - change_bbox[0])
            change_x = int(center_x - (change_width / 2))
            draw.text((change_x, 25), change_text, font=change_font, fill=change_color)
        
        return image
    
    def create_scrolling_display(self, all_data: Dict[str, Any]) -> Image.Image:
        """Create a wide scrolling image with all stocks/crypto - matching old stock_manager spacing."""
        if not all_data:
            return self._create_error_display()
        
        # Calculate total width needed - match old stock_manager spacing logic
        # Ensure dimensions are integers
        width = int(self.display_width)
        height = int(self.display_height)
        
        # Create individual stock displays
        stock_displays = []
        for symbol, data in all_data.items():
            display = self.create_stock_display(symbol, data)
            stock_displays.append(display)
        
        stock_gap = self.stock_gap

        # Total width: initial lead-in buffer + all stock canvases + inter-stock gaps
        total_width = int(width)  # one display-width lead-in before the first stock
        total_width += sum(int(d.width) for d in stock_displays)
        total_width += stock_gap * max(len(stock_displays) - 1, 0)

        # Create scrolling image - ensure dimensions are integers
        scrolling_image = Image.new('RGB', (int(total_width), int(height)), (0, 0, 0))

        current_x = int(width)  # start after lead-in
        for i, display in enumerate(stock_displays):
            scrolling_image.paste(display, (int(current_x), 0))
            current_x += int(display.width)
            if i < len(stock_displays) - 1:
                current_x += stock_gap
        
        return scrolling_image
    
    def _get_stock_logo(self, symbol: str, is_crypto: bool = False) -> Optional[Image.Image]:
        """Get stock or crypto logo image - matching old stock manager sizing."""
        try:
            if is_crypto:
                # Try crypto icons first
                logo_path = f"assets/stocks/crypto_icons/{symbol}.png"
            else:
                # Try stock icons
                logo_path = f"assets/stocks/ticker_icons/{symbol}.png"
            
            # Use same sizing as old stock manager (display_width/1.2, display_height/1.2)
            max_size = min(int(self.display_width / 1.2), int(self.display_height / 1.2))
            return self.logo_helper.load_logo(symbol, logo_path, max_size, max_size)
            
        except (OSError, IOError) as e:
            self.logger.warning("Error loading logo for %s: %s", symbol, e)
            return None
    
    def _get_stock_color(self, change: float) -> Tuple[int, int, int]:
        """Get color based on stock performance - matching old stock manager."""
        if change > 0:
            return (0, 255, 0)  # Green for positive
        elif change < 0:
            return (255, 0, 0)  # Red for negative
        return (255, 255, 0)  # Yellow for no change
    
    def _draw_mini_chart(self, draw: ImageDraw.Draw, price_history: List[Dict],
                        width: int, height: int, color: Tuple[int, int, int],
                        chart_x: Optional[int] = None) -> None:
        """Draw a mini price chart. By default it anchors to the right edge; pass
        chart_x to place it explicitly (e.g. right after the price text)."""
        if len(price_history) < 2:
            return

        # Chart dimensions - definite pixel sizes (self.chart_width_px /
        # self.chart_height_px), clamped so they never exceed the panel.
        # Ensure all dimensions are integers
        chart_width = int(self.chart_width_px)
        chart_height = int(min(self.chart_height_px, height))
        chart_x = int(width - chart_width - 4) if chart_x is None else int(chart_x)  # default: 4px from right edge
        chart_y = int((height - chart_height) / 2)
        
        # Extract prices - match old stock_manager exactly
        prices = [point['price'] for point in price_history if 'price' in point]
        if len(prices) < 2:
            return
        
        # Find min and max prices for scaling - match old stock_manager
        min_price = min(prices)
        max_price = max(prices)
        
        # Add padding to avoid flat lines when prices are very close - match old stock_manager
        price_range = max_price - min_price
        if price_range < 0.01:
            min_price -= 0.01
            max_price += 0.01
            price_range = 0.02
        
        if price_range == 0:
            # All prices are the same, draw a horizontal line
            y = int(chart_y + chart_height / 2)
            draw.line([(chart_x, y), (chart_x + chart_width, y)], fill=color, width=1)
            return
        
        # Calculate points for the line - match old stock_manager exactly
        # Ensure all coordinates are integers
        points = []
        for i, price in enumerate(prices):
            x = int(chart_x + (i * chart_width) / (len(prices) - 1))
            y = int(chart_y + chart_height - int(((price - min_price) / price_range) * chart_height))
            points.append((x, y))
        
        # Draw lines between points - match old stock_manager
        if len(points) > 1:
            for i in range(len(points) - 1):
                draw.line([points[i], points[i + 1]], fill=color, width=1)
    
    def _create_error_display(self) -> Image.Image:
        """Create an error display when no data is available."""
        # Ensure dimensions are integers
        image = Image.new('RGB', (int(self.display_width), int(self.display_height)), (0, 0, 0))
        draw = _pixel_draw(image)
        
        # Use symbol font for error display
        error_font = self.symbol_font
        
        # Draw error message
        error_text = "No Data Available"
        bbox = draw.textbbox((0, 0), error_text, font=error_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Ensure dimensions are integers
        x = (int(self.display_width) - text_width) // 2
        y = (int(self.display_height) - text_height) // 2
        
        draw.text((x, y), error_text, font=error_font, fill=(255, 0, 0))
        
        return image
    
    def set_toggle_chart(self, enabled: bool) -> None:
        """Set whether to show mini charts."""
        self.toggle_chart = enabled
        self.logger.debug("Chart toggle set to: %s", enabled)
    
    def get_scroll_helper(self) -> ScrollHelper:
        """Get the scroll helper instance."""
        return self.scroll_helper
