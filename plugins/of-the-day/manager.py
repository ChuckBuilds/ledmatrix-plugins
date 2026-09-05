"""
Of The Day Plugin for LEDMatrix

Display daily featured content like Word of the Day, Bible verses, or custom items.
Supports multiple categories with automatic rotation and configurable data sources.

Features:
- Multiple category support (Word of the Day, Bible verses, etc.)
- Automatic daily updates
- Rotating display of title, definition, examples
- Configurable data sources via JSON files
- Multi-line text wrapping for long content

API Version: 1.0.0
"""

import os
import json
import logging
import time
from datetime import date
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

# Shared element-style resolver (newer cores): user-customizable per-element
# fonts/sizes/colors/offsets, declared once in config_schema.json via
# x-style-elements. Older cores don't expand the declaration (no
# customization UI is shown) and this import guard keeps the classic
# styling path untouched there.
try:
    from src.element_style import ElementStyleResolver, defaults_from_schema_file
    STYLE_AVAILABLE = True
except ImportError:
    STYLE_AVAILABLE = False

logger = logging.getLogger(__name__)


class OfTheDayPlugin(BasePlugin):
    """
    Of The Day plugin for displaying daily featured content.
    
    Supports multiple categories with rotation between title, subtitle, and content.
    
    Configuration options:
        categories (dict): Dictionary of category configurations
        category_order (list): Order to display categories
        display_rotate_interval (float): Seconds between display rotations
        subtitle_rotate_interval (float): Seconds between subtitle rotations
        update_interval (float): Seconds between checking for new day
        auto_fit_text (bool): Shrink text to fit long content on the panel
    """

    # Smallest pixel size auto-fitting will shrink a scalable font to.
    MIN_AUTO_FONT_SIZE = 5

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the of-the-day plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Configuration
        self.update_interval = config.get('update_interval', 3600)
        self.display_rotate_interval = config.get('display_rotate_interval', 20)
        self.subtitle_rotate_interval = config.get('subtitle_rotate_interval', 10)
        self.auto_fit_text = config.get('auto_fit_text', True)

        # Categories
        self.categories = config.get('categories', {})
        self.category_order = config.get('category_order', [])
        
        # State
        self.current_day = None
        self.current_items = {}
        self.current_category_index = 0
        self.rotation_state = 0  # 0 = title, 1 = content
        self.last_update = 0
        self.last_rotation_time = time.time()
        self.last_category_rotation_time = time.time()
        
        # Display state tracking (to avoid unnecessary redraws)
        self.last_displayed_category = None
        self.last_displayed_rotation_state = None
        self.display_needs_update = True  # Force initial display
        
        # Data files
        self.data_files = {}
        
        # Colors
        self.title_color = (255, 255, 255)
        self.subtitle_color = (200, 200, 200)
        self.content_color = (180, 180, 180)
        self.background_color = (0, 0, 0)
        
        # Load data files
        self._load_data_files()
        
        # Load today's items
        self._load_todays_items()
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Of The Day plugin initialized with {len(self.current_items)} categories")
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return
            
            font_manager = self.plugin_manager.font_manager
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.title",
                family="press_start",
                size_px=8,
                color=self.title_color
            )
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.content",
                family="four_by_six",
                size_px=6,
                color=self.content_color
            )
            
            self.logger.info("Of The Day fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def _element_styles(self):
        """Resolved (title, body) styles from customization config.

        Returns (title_font, title_color, title_offset,
                 body_font, body_color, body_offset).

        With an untouched config this resolves to exactly the classic fonts
        and colors (PressStart2P@8 white / 4x6@6 gray), so rendering is
        unchanged; a genuine user override in customization.title_text /
        body_text wins. On older cores (no src.element_style) the classic
        values are returned directly.
        """
        if STYLE_AVAILABLE:
            resolver = getattr(self, '_element_style_resolver', None)
            if resolver is None or resolver._config is not self.config:
                schema_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 'config_schema.json')
                resolver = ElementStyleResolver(
                    self.config, defaults_from_schema_file(schema_path))
                self._element_style_resolver = resolver
            title = resolver.style('title_text',
                                   classic_font='PressStart2P-Regular.ttf',
                                   classic_size=8,
                                   classic_color=self.title_color)
            body = resolver.style('body_text',
                                  classic_font='4x6-font.ttf',
                                  classic_size=6,
                                  classic_color=self.subtitle_color)
            return (title.font, title.color, title.offset,
                    body.font, body.color, body.offset)

        fonts = getattr(self, '_classic_fonts', None)
        if fonts is None:
            try:
                title_font = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 8)
            except Exception as e:
                self.logger.warning(f"Failed to load PressStart2P font: {e}, using fallback")
                title_font = self.display_manager.small_font if hasattr(self.display_manager, 'small_font') else ImageFont.load_default()
            try:
                body_font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 6)
            except Exception as e:
                self.logger.warning(f"Failed to load 4x6 font: {e}, using fallback")
                body_font = self.display_manager.extra_small_font if hasattr(self.display_manager, 'extra_small_font') else ImageFont.load_default()
            fonts = (title_font, body_font)
            self._classic_fonts = fonts
        return (fonts[0], self.title_color, (0, 0),
                fonts[1], self.subtitle_color, (0, 0))
    
    def _load_data_files(self):
        """Load all data files for enabled categories."""
        for category_name, category_config in self.categories.items():
            if not category_config.get('enabled', True):
                self.logger.debug(f"Skipping disabled category: {category_name}")
                continue
            
            data_file = category_config.get('data_file')
            if not data_file:
                self.logger.warning(f"No data file specified for category: {category_name}")
                continue
            
            try:
                # Try to locate the data file
                file_path = self._find_data_file(data_file)
                if not file_path:
                    self.logger.warning(f"Could not find data file: {data_file}")
                    continue
                
                # Load and parse JSON
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.data_files[category_name] = data
                self.logger.info(f"Loaded data for category '{category_name}': {len(data)} entries")
                
            except Exception as e:
                self.logger.error(f"Error loading data file for {category_name}: {e}")
    
    def _find_data_file(self, data_file: str) -> Optional[str]:
        """Find the data file in possible locations."""
        # Get plugin directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Possible paths to check (prioritize plugin directory)
        possible_paths = [
            os.path.join(plugin_dir, data_file),  # In plugin directory (preferred)
            data_file,  # Direct path (if absolute)
            os.path.join(os.getcwd(), data_file),  # Relative to cwd (fallback)
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                self.logger.info(f"Found data file at: {path}")
                return path
        
        self.logger.warning(f"Data file not found: {data_file}")
        return None
    
    def _load_todays_items(self):
        """Load items for today's date from all enabled categories."""
        today = date.today()
        
        if self.current_day == today and self.current_items:
            return  # Already loaded for today
        
        self.current_day = today
        self.current_items = {}
        self.display_needs_update = True  # Force redraw when day changes
        
        # Calculate day of year (1-365, or 1-366 for leap years)
        day_of_year = today.timetuple().tm_yday
        
        for category_name, data in self.data_files.items():
            try:
                # Find today's entry using day of year
                day_key = str(day_of_year)
                
                if day_key in data:
                    self.current_items[category_name] = data[day_key]
                    item_title = data[day_key].get('word', data[day_key].get('title', 'N/A'))
                    self.logger.info(f"Loaded item for {category_name} (day {day_of_year}): {item_title}")
                else:
                    self.logger.warning(f"No entry found for day {day_of_year} in category {category_name}")
            
            except Exception as e:
                self.logger.error(f"Error loading today's item for {category_name}: {e}")
    
    def update(self) -> None:
        """Update items if it's a new day."""
        current_time = time.time()
        
        # Check if we need to update
        if current_time - self.last_update < self.update_interval:
            return
        
        self.last_update = current_time
        
        # Check if it's a new day
        today = date.today()
        if self.current_day != today:
            self.logger.info(f"New day detected, loading items for {today}")
            self._load_todays_items()
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display of-the-day content.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if not self.current_items:
            if self.last_displayed_category != "NO_DATA":
                self.last_displayed_category = "NO_DATA"
                self._display_no_data()
            return
        
        try:
            # Get enabled categories in order
            enabled_categories = [cat for cat in self.category_order 
                                if cat in self.current_items and 
                                self.categories.get(cat, {}).get('enabled', True)]
            
            if not enabled_categories:
                if self.last_displayed_category != "NO_DATA":
                    self.last_displayed_category = "NO_DATA"
                    self._display_no_data()
                return
            
            # Rotate categories
            current_time = time.time()
            category_changed = False
            if current_time - self.last_category_rotation_time >= self.display_rotate_interval:
                self.current_category_index = (self.current_category_index + 1) % len(enabled_categories)
                self.last_category_rotation_time = current_time
                self.rotation_state = 0  # Reset rotation when changing categories
                self.last_rotation_time = current_time
                category_changed = True
                self.display_needs_update = True
            
            # Get current category
            category_name = enabled_categories[self.current_category_index]
            category_config = self.categories.get(category_name, {})
            item_data = self.current_items.get(category_name, {})
            
            # Rotate display content
            rotation_changed = False
            if current_time - self.last_rotation_time >= self.subtitle_rotate_interval:
                self.rotation_state = (self.rotation_state + 1) % 2
                self.last_rotation_time = current_time
                rotation_changed = True
                self.display_needs_update = True
            
            # Check if we need to update the display
            # Only redraw if category changed, rotation state changed, or force_clear
            if (self.display_needs_update or 
                force_clear or 
                category_changed or 
                rotation_changed or 
                self.last_displayed_category != category_name or 
                self.last_displayed_rotation_state != self.rotation_state):
                
                # Update tracking state
                self.last_displayed_category = category_name
                self.last_displayed_rotation_state = self.rotation_state
                self.display_needs_update = False
                
                # Display based on rotation state
                if self.rotation_state == 0:
                    self._display_title(category_config, item_data)
                else:
                    self._display_content(category_config, item_data)
        
        except Exception as e:
            self.logger.error(f"Error displaying of-the-day: {e}")
            if self.last_displayed_category != "ERROR":
                self.last_displayed_category = "ERROR"
                self._display_error()
    
    def _text_width(self, text: str, font) -> int:
        """Pixel width of `text` in `font` (display_manager first, PIL fallback)."""
        try:
            return self.display_manager.get_text_width(text, font)
        except Exception:
            try:
                bbox = font.getbbox(text)
                return bbox[2] - bbox[0]
            except Exception:
                return len(text) * 6

    def _get_font_height(self, font, default: int = 8) -> int:
        """Pixel height of `font`, falling back to `default` on error."""
        try:
            return self.display_manager.get_font_height(font)
        except Exception as e:
            self.logger.warning(f"Error getting font height: {e}, using default {default}")
            return default

    def _wrap_text(self, text: str, max_width: int, font, max_lines: int = 10) -> List[str]:
        """Wrap text to fit within max_width, measuring the actual font."""
        if not text:
            return [""]
        lines = []
        current_line = []
        words = text.split()
        for word in words:
            test_line = ' '.join(current_line + [word]) if current_line else word
            if self._text_width(test_line, font) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    # Word is too long - truncate it
                    truncated = word
                    while len(truncated) > 0:
                        if self._text_width(truncated + "...", font) <= max_width:
                            lines.append(truncated + "...")
                            break
                        truncated = truncated[:-1]
                    if not truncated:
                        lines.append(word[:10] + "...")
            if len(lines) >= max_lines:
                break
        if current_line and len(lines) < max_lines:
            lines.append(' '.join(current_line))
        return lines[:max_lines]

    def _ellipsize(self, text: str, font, max_width: int) -> str:
        """Trim `text` with '...' so it fits max_width; unchanged if it fits."""
        if self._text_width(text, font) <= max_width:
            return text
        ellipsis = "..."
        if self._text_width(ellipsis, font) > max_width:
            return ""
        truncated = text
        while truncated and self._text_width(truncated + ellipsis, font) > max_width:
            truncated = truncated[:-1]
        return truncated + ellipsis

    def _fit_title(self, title: str, font) -> str:
        """Ellipsize the title to the panel width.

        Titles that already fit are returned unchanged, so normal-width panels
        render exactly as before; on a narrow panel (64px) a long word is
        truncated with '...' instead of being drawn past the panel edge.
        """
        return self._ellipsize(title, font, self.display_manager.width)

    def _resized_font(self, font, size: int):
        """The same typeface as `font` at a different pixel size, or None.

        Only scalable fonts (TTF/OTF, which carry a `.path`) can be resized;
        bitmap fonts (BDF freetype.Face, PIL's built-in default) return None.
        """
        path = getattr(font, 'path', None)
        if not path or size < 1:
            return None
        cache = getattr(self, '_resized_font_cache', None)
        if cache is None:
            cache = self._resized_font_cache = {}
        key = (path, size)
        if key not in cache:
            try:
                cache[key] = ImageFont.truetype(path, size)
            except Exception as e:
                self.logger.warning(f"Could not load font {path} at {size}px: {e}")
                cache[key] = None
        return cache[key]

    def _fit_wrapped_text(self, text: str, font, max_width: int, max_height: int,
                          line_spacing: int = 1):
        """Wrap `text` to the panel, shrinking the font when it can't fit.

        Wrapping always measures the actual font, so wider fonts and larger
        user-configured sizes wrap into fewer characters per line, and the
        number of lines comes from the real font height and the available
        vertical space — not a fixed count. When the wrapped text needs more
        lines than fit and auto_fit_text is enabled, scalable fonts are
        retried at progressively smaller sizes (down to MIN_AUTO_FONT_SIZE)
        until the whole text fits (the largest size that fits wins). When no
        size fits everything — or the font is a bitmap font that can't be
        resized — the configured font is kept (crisper than a shrunken one
        that still overflows), the text is cut to the lines that fit, and
        the last line is ellipsized.

        Returns (font, lines, line_height).
        """
        candidates = [font]
        if self.auto_fit_text:
            base_size = getattr(font, 'size', None)
            if isinstance(base_size, (int, float)):
                for size in range(int(base_size) - 1, self.MIN_AUTO_FONT_SIZE - 1, -1):
                    smaller = self._resized_font(font, size)
                    if smaller is not None:
                        candidates.append(smaller)

        first = None
        for candidate in candidates:
            line_height = self._get_font_height(candidate)
            max_lines = max(1, (max_height + line_spacing) // (line_height + line_spacing))
            # Wrap with one spare line so overflow is detectable.
            lines = self._wrap_text(text, max_width, candidate, max_lines=max_lines + 1)
            if first is None:
                first = (candidate, lines, line_height, max_lines)
            # A candidate only wins when every word survived intact: a word
            # wider than max_width gets truncated by _wrap_text, and a
            # smaller size may be able to hold it whole.
            if len(lines) <= max_lines and " ".join(lines).split() == text.split():
                return candidate, lines, line_height
        # No size holds everything: keep the configured font, keep the lines
        # that fit, and mark the cut with an ellipsis.
        candidate, lines, line_height, max_lines = first
        lines = lines[:max_lines]
        if lines:
            lines[-1] = self._ellipsize(lines[-1] + "...", candidate, max_width)
        return candidate, lines, line_height

    def _draw_bdf_text(self, draw, font, text: str, x: int, y: int, color: tuple = (255, 255, 255)):
        """Draw text supporting both BDF (FreeType Face) and PIL TTF fonts, similar to old manager."""
        self.logger.debug(f"_draw_bdf_text: text='{text}', x={x}, y={y}, font={type(font).__name__}, color={color}")
        try:
            # If we have a PIL font, use native text rendering
            if isinstance(font, ImageFont.ImageFont):
                draw.text((x, y), text, fill=color, font=font)
                self.logger.debug(f"PIL text drawn: '{text}'")
                return
            
            # Try to import freetype
            try:
                import freetype
            except ImportError:
                # If freetype not available, fallback to PIL
                draw.text((x, y), text, fill=color, font=ImageFont.load_default())
                return
            
            # For BDF fonts (FreeType Face)
            if isinstance(font, freetype.Face):
                # Compute baseline from font ascender so caller can pass top-left y
                try:
                    ascender_px = font.size.ascender >> 6
                except Exception:
                    ascender_px = 0
                baseline_y = y + ascender_px
                
                # Render BDF glyphs manually
                current_x = x
                for char in text:
                    font.load_char(char)
                    bitmap = font.glyph.bitmap
                    
                    # Get glyph metrics
                    glyph_left = font.glyph.bitmap_left
                    glyph_top = font.glyph.bitmap_top
                    
                    for i in range(bitmap.rows):
                        for j in range(bitmap.width):
                            try:
                                byte_index = i * bitmap.pitch + (j // 8)
                                if byte_index < len(bitmap.buffer):
                                    byte = bitmap.buffer[byte_index]
                                    if byte & (1 << (7 - (j % 8))):
                                        # Calculate actual pixel position
                                        pixel_x = current_x + glyph_left + j
                                        pixel_y = baseline_y - glyph_top + i
                                        # Only draw if within bounds
                                        if (0 <= pixel_x < self.display_manager.width and 
                                            0 <= pixel_y < self.display_manager.height):
                                            draw.point((pixel_x, pixel_y), fill=color)
                            except IndexError:
                                continue
                    current_x += font.glyph.advance.x >> 6
        except Exception as e:
            self.logger.error(f"Error in _draw_bdf_text for text '{text}' at ({x}, {y}): {e}", exc_info=True)
            # Fallback to simple text drawing
            try:
                draw.text((x, y), text, fill=color, font=ImageFont.load_default())
            except Exception as fallback_e:
                self.logger.error(f"Fallback text drawing also failed: {fallback_e}", exc_info=True)
    
    def _fresh_frame(self):
        """Start a frame on a new in-memory buffer, without touching the panel.

        display_manager.clear() calls Clear() on the offscreen AND current
        canvases, writing black straight to the matrix, so the panel is blank
        from that call until update_display() pushes the finished frame.

        This plugin only redraws when the category or rotation state actually
        changes, so the blank was a brief blip rather than the continuous
        pulse the same pattern caused in the calendar plugin -- but there is
        no reason to blank the panel at all when the buffer can simply be
        replaced.
        """
        self.display_manager.image = Image.new(
            'RGB',
            (self.display_manager.width, self.display_manager.height),
            (0, 0, 0))
        self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
        self.display_manager.draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

    def _display_title(self, category_config: Dict, item_data: Dict):
        """Display the title/word with subtitle, matching old manager layout."""
        # Compose off-panel; see _fresh_frame.
        self._fresh_frame()
        draw = self.display_manager.draw

        # Fonts/colors/offsets honor customization.<element> (classic
        # PressStart2P@8 / 4x6@6 when untouched)
        (title_font, title_color, (title_dx, title_dy),
         body_font, body_color, (body_dx, body_dy)) = self._element_styles()

        # Get font heights
        title_height = self._get_font_height(title_font)
        body_height = self._get_font_height(body_font)

        # Layout matching old manager: margin_top = 8
        margin_top = 8
        margin_bottom = 1
        underline_space = 1

        # Get title/word (JSON uses "title" not "word")
        title = self._fit_title(item_data.get('title', item_data.get('word', 'N/A')), title_font)

        # Get subtitle (JSON uses "subtitle")
        subtitle = item_data.get('subtitle', item_data.get('pronunciation', item_data.get('type', '')))

        # Calculate title width for centering
        title_width = self._text_width(title, title_font)

        # Center the title horizontally (+ user layout offset)
        title_x = (self.display_manager.width - title_width) // 2 + title_dx
        # A user layout offset (title_dx) must not push the title off-panel.
        title_x = max(0, min(title_x, max(0, self.display_manager.width - title_width)))
        title_y = margin_top + title_dy

        # Draw title using display_manager.draw_text (proper method)
        self.logger.info(f"Drawing title '{title}' at ({title_x}, {title_y}) with font type {type(title_font).__name__}")
        try:
            self.display_manager.draw_text(
                title,
                x=title_x,
                y=title_y,
                color=title_color,
                font=title_font
            )
            self.logger.debug(f"Title '{title}' drawn using display_manager.draw_text")
        except Exception as e:
            self.logger.error(f"Error drawing title '{title}': {e}", exc_info=True)

        # Draw underline below title (like old manager)
        underline_y = title_y + title_height + 1
        underline_x_start = max(title_x, 0)
        # PIL line endpoints are inclusive: keep the underline inside the panel
        underline_x_end = min(title_x + title_width, self.display_manager.width - 1)
        draw.line([(underline_x_start, underline_y), (underline_x_end, underline_y)],
                 fill=title_color, width=1)
        
        # Draw subtitle below underline (centered, like old manager)
        if subtitle:
            # Wrap the subtitle to the panel; when the configured font can't
            # fit every line below the underline, shrink it until it does.
            available_width = self.display_manager.width - 4
            max_subtitle_height = (self.display_manager.height - underline_y
                                   - underline_space - 2 - margin_bottom)
            body_font, wrapped_subtitle_lines, body_height = self._fit_wrapped_text(
                subtitle, body_font, available_width, max_subtitle_height)
            actual_subtitle_lines = [line for line in wrapped_subtitle_lines if line.strip()]

            if actual_subtitle_lines:
                # Calculate spacing - similar to old manager's dynamic spacing
                total_subtitle_height = len(actual_subtitle_lines) * body_height
                available_space = self.display_manager.height - underline_y - margin_bottom
                space_after_underline = max(2, (available_space - total_subtitle_height) // 2)
                # Centering must not push the last line past the panel bottom.
                lines_span = total_subtitle_height + (len(actual_subtitle_lines) - 1)
                max_space_after = (self.display_manager.height - underline_y
                                   - underline_space - lines_span)
                space_after_underline = max(2, min(space_after_underline, max_space_after))

                subtitle_start_y = underline_y + space_after_underline + underline_space
                current_y = subtitle_start_y

                for line in actual_subtitle_lines:
                    if line.strip():
                        # Stop before drawing a line that would run past the
                        # panel bottom (happens on short panels like 64x32).
                        if current_y + body_dy + body_height > self.display_manager.height:
                            break
                        # Center each line of subtitle
                        line_width = self._text_width(line, body_font)
                        line_x = (self.display_manager.width - line_width) // 2 + body_dx

                        # Use display_manager.draw_text for subtitle
                        self.display_manager.draw_text(
                            line,
                            x=line_x,
                            y=current_y + body_dy,
                            color=body_color,
                            font=body_font
                        )
                        current_y += body_height + 1

        self.display_manager.update_display()

    def _display_content(self, category_config: Dict, item_data: Dict):
        """Display the definition/content, matching old manager layout."""
        # Compose off-panel; see _fresh_frame.
        self._fresh_frame()
        draw = self.display_manager.draw

        # Fonts/colors/offsets honor customization.<element> (classic
        # PressStart2P@8 / 4x6@6 when untouched)
        (title_font, title_color, (title_dx, title_dy),
         body_font, body_color, (body_dx, body_dy)) = self._element_styles()

        # Get font heights
        title_height = self._get_font_height(title_font)

        # Layout matching old manager: margin_top = 8
        margin_top = 8
        margin_bottom = 1
        underline_space = 1

        # Get title/word (JSON uses "title")
        title = self._fit_title(item_data.get('title', item_data.get('word', 'N/A')), title_font)
        self.logger.debug(f"Displaying content for title: {title}")

        # Get description (JSON uses "description")
        description = item_data.get('description', item_data.get('definition', item_data.get('content', item_data.get('text', 'No content'))))

        # Calculate title width for centering (for underline placement)
        title_width = self._text_width(title, title_font)

        # Center the title horizontally (same position as in _display_title)
        title_x = (self.display_manager.width - title_width) // 2 + title_dx
        # A user layout offset (title_dx) must not push the title off-panel.
        title_x = max(0, min(title_x, max(0, self.display_manager.width - title_width)))
        title_y = margin_top + title_dy

        # Draw title using display_manager.draw_text (same as title screen)
        self.display_manager.draw_text(
            title,
            x=title_x,
            y=title_y,
            color=title_color,
            font=title_font
        )

        # Draw underline below title (same as title screen)
        underline_y = title_y + title_height + 1
        underline_x_start = max(title_x, 0)
        # PIL line endpoints are inclusive: keep the underline inside the panel
        underline_x_end = min(title_x + title_width, self.display_manager.width - 1)
        draw.line([(underline_x_start, underline_y), (underline_x_end, underline_y)],
                 fill=title_color, width=1)
        
        # Wrap the description to the panel: line width and line count follow
        # the actual font metrics, and the font shrinks when the configured
        # size can't fit the whole text below the underline.
        available_width = self.display_manager.width - 4
        max_body_height = (self.display_manager.height - underline_y
                           - underline_space - 3)
        body_font, wrapped_lines, body_height = self._fit_wrapped_text(
            description, body_font, available_width, max_body_height)
        actual_body_lines = [line for line in wrapped_lines if line.strip()]

        if actual_body_lines:
            # Calculate dynamic spacing - similar to old manager
            num_body_lines = len(actual_body_lines)
            body_content_height = num_body_lines * body_height
            available_space = self.display_manager.height - underline_y - margin_bottom

            if body_content_height < available_space:
                # Distribute extra space: some after underline, rest between lines
                extra_space = available_space - body_content_height
                space_after_underline = max(2, int(extra_space * 0.3))
                space_between_lines = max(1, int(extra_space * 0.7 / max(1, num_body_lines - 1))) if num_body_lines > 1 else 0
            else:
                # Tight spacing
                space_after_underline = 4
                space_between_lines = 1

            # Rounding in the spread can land the last line past the panel
            # bottom; tighten the spacing back in rather than dropping it.
            if num_body_lines > 1:
                slack = (self.display_manager.height - underline_y - underline_space
                         - 1 - space_after_underline - body_content_height)
                if space_between_lines * (num_body_lines - 1) > slack:
                    space_between_lines = max(1, slack // (num_body_lines - 1))
                    overshoot = space_between_lines * (num_body_lines - 1) - slack
                    if overshoot > 0:
                        space_after_underline = max(2, space_after_underline - overshoot)

            # Draw body text with dynamic spacing
            body_start_y = underline_y + space_after_underline + underline_space + 1  # +1 to match old manager's shift
            current_y = body_start_y
            
            for i, line in enumerate(actual_body_lines):
                if line.strip():
                    # Stop before drawing a line that would run past the
                    # panel bottom (happens on short panels like 64x32).
                    if current_y + body_dy + body_height > self.display_manager.height:
                        break
                    # Center each line of body text (like old manager)
                    line_width = self._text_width(line, body_font)
                    line_x = (self.display_manager.width - line_width) // 2 + body_dx

                    # Use display_manager.draw_text for description
                    self.display_manager.draw_text(
                        line,
                        x=line_x,
                        y=current_y + body_dy,
                        color=body_color,
                        font=body_font
                    )
                    
                    # Move to next line position
                    if i < len(actual_body_lines) - 1:  # Not the last line
                        current_y += body_height + space_between_lines
        
        self.display_manager.update_display()
    
    def _display_no_data(self):
        """Display message when no data is available."""
        img = Image.new('RGB', (self.display_manager.width,
                               self.display_manager.height),
                       self.background_color)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except Exception:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "No Data", font=font, fill=(200, 200, 200))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_error(self):
        """Display error message."""
        img = Image.new('RGB', (self.display_manager.width,
                               self.display_manager.height),
                       self.background_color)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except Exception:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "Error", font=font, fill=(255, 0, 0))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 40.0)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'current_day': str(self.current_day) if self.current_day else None,
            'categories_loaded': len(self.current_items),
            'enabled_categories': [cat for cat in self.category_order 
                                  if self.categories.get(cat, {}).get('enabled', True)]
        })
        return info
    
    def on_config_change(self, config: Dict[str, Any]) -> None:
        """Handle configuration changes (called when user updates config via web UI)."""
        self.logger.info("Config changed, reloading categories")

        # Update configuration
        self.config = config
        self.update_interval = config.get('update_interval', 3600)
        self.display_rotate_interval = config.get('display_rotate_interval', 20)
        self.subtitle_rotate_interval = config.get('subtitle_rotate_interval', 10)
        self.auto_fit_text = config.get('auto_fit_text', True)
        self.categories = config.get('categories', {})
        self.category_order = config.get('category_order', [])

        # Reset state
        self.current_category_index = 0
        self.rotation_state = 0
        self.display_needs_update = True

        # Reload data files (respects enabled status)
        self.data_files = {}
        self._load_data_files()

        # Reload today's items
        self.current_day = None  # Force reload
        self._load_todays_items()

        self.logger.info(f"Config reloaded: {len(self.data_files)} categories enabled")

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_items = {}
        self.data_files = {}
        self.logger.info("Of The Day plugin cleaned up")

