"""
Google Calendar Plugin for LEDMatrix

Display upcoming events from Google Calendar with date, time, and event details.
Shows next 1-3 events with automatic rotation and timezone support.

Features:
- Google Calendar API integration
- OAuth authentication
- Multiple calendar support
- Event rotation
- All-day and timed events
- Timezone-aware formatting
- Text wrapping for long event titles

API Version: 1.0.1
"""

import os
import logging
import time
import pickle
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode

# Google Calendar imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import pytz
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    pytz = None

logger = logging.getLogger(__name__)


class CalendarPlugin(BasePlugin):
    """
    Google Calendar plugin for displaying upcoming events.
    
    Supports OAuth authentication, multiple calendars, and event rotation.
    
    Configuration options:
        credentials_file (str): Path to Google Calendar API credentials
        token_file (str): Path to store OAuth token
        max_events (int): Maximum number of events to fetch
        calendars (list): List of calendar IDs to fetch from
        update_interval (float): Seconds between API updates
        event_rotation_interval (float): Seconds between event rotations
    """
    
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the calendar plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        if not GOOGLE_AVAILABLE:
            self.logger.error("Google Calendar libraries not available. Install: google-auth-oauthlib google-auth-httplib2 google-api-python-client")
            self.enabled = False
            return
        
        # Configuration - use plugin directory for all files
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.credentials_file = os.path.join(plugin_dir, config.get('credentials_file', 'credentials.json'))
        self.token_file = os.path.join(plugin_dir, config.get('token_file', 'token.pickle'))
        self.max_events = config.get('max_events', 3)
        self.calendars = config.get('calendars', ['primary'])
        # Validate calendars is not empty
        if not self.calendars or len(self.calendars) == 0:
            self.logger.warning("No calendars configured, defaulting to 'primary'")
            self.calendars = ['primary']
        self.update_interval = config.get('update_interval', 3600)
        self.show_all_day = config.get('show_all_day_events', True)
        self.rotation_interval = config.get('event_rotation_interval', 10)
        
        # State
        self.service = None
        self.events = []
        self.current_event_index = 0
        self.last_rotation = time.time()
        
        # Colors
        self.text_color = (255, 255, 255)
        self.time_color = (255, 200, 100)
        self.date_color = (150, 150, 255)
        
        # Get timezone with better error handling
        self.timezone = self._get_timezone()
        
        # Authenticate
        if not self._authenticate():
            self.logger.warning("Calendar authentication failed - plugin may not function correctly")
        
        # Register fonts
        self._register_fonts()
        
        # Cache fonts for performance
        self.datetime_font = None
        self.title_font = None
        self._load_fonts()
        
        # Cache display dimensions
        self._display_width = None
        self._display_height = None

        self.logger.info(f"Calendar plugin initialized with {len(self.calendars)} calendar(s)")
    
    def _get_timezone(self):
        """Get timezone from config with proper error handling."""
        try:
            timezone_str = 'UTC'
            if hasattr(self.plugin_manager, 'config_manager') and self.plugin_manager.config_manager:
                try:
                    main_config = self.plugin_manager.config_manager.load_config()
                    timezone_str = main_config.get('timezone', 'UTC')
                except Exception as e:
                    self.logger.warning(f"Could not load timezone from config: {e}, using UTC")
            
            if pytz:
                return pytz.timezone(timezone_str)
            return None
        except Exception as e:
            self.logger.warning(f"Error setting timezone: {e}, using UTC")
            return pytz.utc if pytz else None
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager') or not self.plugin_manager.font_manager:
                return
            
            font_manager = self.plugin_manager.font_manager
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.datetime",
                family="four_by_six",
                size_px=8,
                color=self.time_color
            )
            
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.title",
                family="press_start",
                size_px=8,
                color=self.text_color
            )
            
            self.logger.info("Calendar fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")
    
    def _load_fonts(self):
        """Load fonts from font manager or fallback to default."""
        try:
            # Try to get fonts from font manager
            if hasattr(self.plugin_manager, 'font_manager') and self.plugin_manager.font_manager:
                font_manager = self.plugin_manager.font_manager
                try:
                    datetime_font_obj = font_manager.get_manager_font(
                        self.plugin_id, f"{self.plugin_id}.datetime"
                    )
                    title_font_obj = font_manager.get_manager_font(
                        self.plugin_id, f"{self.plugin_id}.title"
                    )
                    if datetime_font_obj and title_font_obj:
                        self.datetime_font = datetime_font_obj
                        self.title_font = title_font_obj
                        return
                except Exception:
                    pass

            # Get customization settings from config
            customization = self.config.get('customization', {})
            datetime_settings = customization.get('datetime_text', {})
            title_settings = customization.get('title_text', {})

            # Get font names and sizes from config (with defaults)
            datetime_font_name = datetime_settings.get('font', '4x6-font.ttf')
            datetime_font_size = datetime_settings.get('font_size', 8)
            title_font_name = title_settings.get('font', 'PressStart2P-Regular.ttf')
            title_font_size = title_settings.get('font_size', 8)

            # Try to load from assets directory (relative to project root)
            project_root = os.environ.get('LEDMATRIX_ROOT', os.getcwd())
            assets_fonts = os.path.join(project_root, 'assets', 'fonts')

            datetime_font_path = os.path.join(assets_fonts, datetime_font_name)
            title_font_path = os.path.join(assets_fonts, title_font_name)

            # Load datetime font
            self.datetime_font = self._load_font_by_type(
                datetime_font_path, datetime_font_size, "datetime"
            )

            # Load title font
            self.title_font = self._load_font_by_type(
                title_font_path, title_font_size, "title"
            )
        except Exception as e:
            self.logger.warning(f"Error loading fonts: {e}")
            self.datetime_font = ImageFont.load_default()
            self.title_font = ImageFont.load_default()

    def _load_font_by_type(self, font_path: str, font_size: int,
                           font_name: str) -> ImageFont.ImageFont:
        """
        Load a font based on its file extension.

        Handles both TrueType (.ttf) and bitmap (.bdf) fonts appropriately.

        Args:
            font_path: Full path to the font file
            font_size: Font size in pixels (used for TTF fonts only)
            font_name: Descriptive name for logging (e.g., "datetime", "title")

        Returns:
            Loaded ImageFont object, or default font on failure
        """
        if not os.path.exists(font_path):
            self.logger.warning(f"Font file not found for {font_name}: {font_path}")
            self.logger.info(f"Using default font for {font_name}")
            return ImageFont.load_default()

        # Get file extension to determine loader type
        _, ext = os.path.splitext(font_path.lower())

        # Try BDF bitmap font loader
        if ext == '.bdf':
            try:
                font = ImageFont.load(font_path)
                self.logger.debug(f"Loaded BDF font for {font_name}: {font_path}")
                return font
            except Exception as e:
                self.logger.warning(f"Failed to load BDF font for {font_name}: {e}")
                self.logger.info(f"Using default font for {font_name}")
                return ImageFont.load_default()

        # Try TrueType font loader (for .ttf, .otf, and other formats)
        try:
            font = ImageFont.truetype(font_path, font_size)
            self.logger.debug(f"Loaded TrueType font for {font_name}: {font_path}")
            return font
        except Exception as e:
            self.logger.warning(f"Failed to load TrueType font for {font_name}: {e}")
            self.logger.info(f"Using default font for {font_name}")
            return ImageFont.load_default()

    def _get_display_dimensions(self, width: Optional[int] = None, height: Optional[int] = None) -> tuple:
        """
        Get display dimensions dynamically.

        Supports partial overrides - if only width or height is provided,
        the missing dimension is resolved from display_manager or defaults.

        Args:
            width: Override width (optional, resolves from display_manager if None)
            height: Override height (optional, resolves from display_manager if None)

        Returns:
            Tuple of (width, height)
        """
        resolved_width = width
        resolved_height = height

        # Resolve missing dimensions from display_manager
        if resolved_width is None or resolved_height is None:
            # Try to get from display_manager.matrix first
            if hasattr(self.display_manager, 'matrix') and self.display_manager.matrix is not None:
                if resolved_width is None:
                    resolved_width = self.display_manager.matrix.width
                if resolved_height is None:
                    resolved_height = self.display_manager.matrix.height

            # Try direct attributes if still missing
            if resolved_width is None:
                resolved_width = getattr(self.display_manager, 'width', None)
            if resolved_height is None:
                resolved_height = getattr(self.display_manager, 'height', None)

        # Fall back to defaults if still missing
        if resolved_width is None:
            resolved_width = 128
        if resolved_height is None:
            resolved_height = 32

        return resolved_width, resolved_height

    def _get_font_height(self, font: ImageFont.ImageFont) -> int:
        """Get the height of a font for layout calculations."""
        try:
            # Create a temporary image to measure font
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            bbox = temp_draw.textbbox((0, 0), "Ay", font=font)
            return bbox[3] - bbox[1]
        except Exception:
            return 8  # Default fallback

    def _authenticate(self) -> bool:
        """
        Authenticate with Google Calendar API.
        
        Returns:
            True if authentication successful, False otherwise
        """
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as token:
                    creds = pickle.load(token)
                self.logger.info("Loaded existing credentials")
            except Exception as e:
                self.logger.error(f"Error loading credentials from {self.token_file}: {e}")
                creds = None
        
        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self.logger.info("Refreshed credentials")
                except Exception as e:
                    self.logger.error(f"Error refreshing credentials: {e}")
                    creds = None
            
            if not creds:
                if not os.path.exists(self.credentials_file):
                    self.logger.error(f"Credentials file not found: {self.credentials_file}")
                    self.logger.error("Please run the authentication script from the web interface or place credentials.json in the plugin directory")
                    return False
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES)
                    creds = flow.run_local_server(port=0)
                    self.logger.info("Obtained new credentials")
                except Exception as e:
                    self.logger.error(f"Error getting new credentials: {e}")
                    self.logger.error("Make sure credentials.json is valid and Google Calendar API is enabled")
                    return False
            
            # Save credentials
            try:
                with open(self.token_file, 'wb') as token:
                    pickle.dump(creds, token)
                self.logger.info("Saved credentials")
            except Exception as e:
                self.logger.error(f"Error saving credentials to {self.token_file}: {e}")
                return False
        
        # Build service
        try:
            self.service = build('calendar', 'v3', credentials=creds)
            self.logger.info("Calendar service built successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error building calendar service: {e}")
            return False

    def get_calendars(self) -> List[Dict[str, Any]]:
        """Return available Google calendars for UI selection widgets."""
        if not self.service:
            return []

        try:
            calendars = []
            page_token = None
            while True:
                response = self.service.calendarList().list(
                    pageToken=page_token
                ).execute()
                calendars.extend(response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return [
                {
                    "id": cal.get("id", ""),
                    "summary": cal.get("summary", "Unnamed Calendar"),
                    "primary": cal.get("primary", False),
                }
                for cal in calendars
                if cal.get("id")
            ]
        except Exception:
            self.logger.exception("Failed to fetch calendar list")
            return []

    def update(self) -> None:
        """
        Fetch upcoming calendar events.
        
        Uses cache_manager to cache API responses and reduce API calls.
        Plugin system handles update interval scheduling.
        """
        if not self.service:
            self.logger.warning("Calendar service not available - authentication may be required")
            return
        
        # Check cache first
        cache_key = f"{self.plugin_id}_events_{'_'.join(sorted(self.calendars))}"
        cached_events = self.cache_manager.get(cache_key, max_age=self.update_interval)
        
        if cached_events is not None:
            self.events = cached_events
            self.logger.debug(f"Using cached events: {len(self.events)} events")
            return
        
        try:
            # Fetch events from all configured calendars
            all_events = []
            
            # Compute time_min once so all calendars use the same boundary
            if self.timezone and pytz:
                local_now = datetime.now(self.timezone)
                start_of_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                time_min = start_of_today.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
            else:
                time_min = datetime.utcnow().replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).isoformat() + 'Z'

            for calendar_id in self.calendars:
                try:
                    events_result = self.service.events().list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        maxResults=self.max_events * 2,  # Fetch extra to account for filtering
                        singleEvents=True,
                        orderBy='startTime'
                    ).execute()
                    
                    events = events_result.get('items', [])
                    
                    # Filter all-day events if needed
                    if not self.show_all_day:
                        events = [e for e in events if 'dateTime' in e.get('start', {})]
                    
                    all_events.extend(events)
                    
                    self.logger.info(f"Fetched {len(events)} events from calendar: {calendar_id}")
                
                except Exception:
                    self.logger.exception(
                        "Error fetching events from calendar '%s' - verify this calendar ID is correct and accessible under your Google account",
                        calendar_id,
                    )
                    continue
            
            # Sort all events by start time
            all_events.sort(key=lambda x: x['start'].get('dateTime', x['start'].get('date', '')))
            
            # Limit to max_events
            self.events = all_events[:self.max_events]
            
            # Cache the results
            if self.events:
                self.cache_manager.set(cache_key, self.events, ttl=self.update_interval)
                self.logger.info(f"Total events fetched and cached: {len(self.events)}")
            else:
                self.logger.info("No upcoming events found")
        
        except Exception as e:
            self.logger.error(f"Error updating calendar: {e}", exc_info=True)
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display calendar events.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if force_clear:
            self.display_manager.clear()
        
        if not self.events:
            self._display_no_events()
            return
        
        try:
            # Safety check - ensure events list is not empty
            if not self.events or len(self.events) == 0:
                self._display_no_events()
                return
            
            # Rotate through events
            current_time = time.time()
            if current_time - self.last_rotation >= self.rotation_interval:
                self.current_event_index = (self.current_event_index + 1) % len(self.events)
                self.last_rotation = current_time
            
            # Ensure index is valid
            if self.current_event_index >= len(self.events):
                self.current_event_index = 0
            
            # Display current event
            event = self.events[self.current_event_index]
            self._display_event(event)
        
        except Exception as e:
            self.logger.error(f"Error displaying calendar: {e}", exc_info=True)
            self._display_error()
    
    def _display_event(self, event: Dict):
        """Display a single calendar event on the display_manager."""
        self.display_manager.clear()

        # Render to the display_manager's image
        width, height = self._get_display_dimensions()
        self._render_event_to_image(event, self.display_manager.image, width, height)

        self.display_manager.update_display()

    def _render_event_image(self, event: Dict, width: Optional[int] = None,
                            height: Optional[int] = None) -> Image.Image:
        """
        Render a single event to a standalone PIL Image.

        This method creates a new image and renders the event to it,
        useful for Vegas scroll mode and other integrations.

        Args:
            event: Calendar event dict from Google Calendar API
            width: Image width (defaults to display width)
            height: Image height (defaults to display height)

        Returns:
            PIL Image with rendered event
        """
        w, h = self._get_display_dimensions(width, height)
        image = Image.new('RGB', (w, h), (0, 0, 0))
        self._render_event_to_image(event, image, w, h)
        return image

    def _render_event_to_image(self, event: Dict, image: Image.Image,
                               width: int, height: int) -> None:
        """
        Render an event to an existing PIL Image with dynamic layout.

        Args:
            event: Calendar event dict
            image: PIL Image to draw on
            width: Width of the image
            height: Height of the image
        """
        # Ensure fonts are loaded
        if self.datetime_font is None or self.title_font is None:
            self._load_fonts()

        draw = ImageDraw.Draw(image)

        # Calculate dynamic layout based on height
        datetime_font_height = self._get_font_height(self.datetime_font)
        title_font_height = self._get_font_height(self.title_font)

        # Vertical spacing: 1px top margin, datetime, 2px gap, title lines
        top_margin = max(1, height // 16)
        datetime_y = top_margin
        title_y = datetime_y + datetime_font_height + max(2, height // 16)

        # Calculate how many title lines can fit
        available_height = height - title_y - top_margin
        max_title_lines = max(1, available_height // (title_font_height + 1))

        # Format date and time
        date_text = self._format_event_date(event)
        time_text = self._format_event_time(event)

        # Calculate total width for centering (date + space + time)
        space_text = " " if date_text and time_text else ""
        date_bbox = draw.textbbox((0, 0), date_text, font=self.datetime_font) if date_text else (0, 0, 0, 0)
        time_bbox = draw.textbbox((0, 0), time_text, font=self.datetime_font) if time_text else (0, 0, 0, 0)
        space_bbox = draw.textbbox((0, 0), space_text, font=self.datetime_font) if space_text else (0, 0, 0, 0)

        date_width = date_bbox[2] - date_bbox[0]
        space_width = space_bbox[2] - space_bbox[0]
        time_width = time_bbox[2] - time_bbox[0]
        total_datetime_width = date_width + space_width + time_width

        # Draw date and time separately with different colors, centered
        x_pos = (width - total_datetime_width) // 2
        if date_text:
            draw.text((x_pos, datetime_y), date_text, font=self.datetime_font, fill=self.date_color)
            x_pos += date_width
        if space_text:
            draw.text((x_pos, datetime_y), space_text, font=self.datetime_font, fill=self.time_color)
            x_pos += space_width
        if time_text:
            draw.text((x_pos, datetime_y), time_text, font=self.datetime_font, fill=self.time_color)

        # Draw event title (wrapped if needed)
        summary = event.get('summary', 'No Title')
        lines = self._wrap_text(summary, draw, self.title_font, width - 4)

        # Draw wrapped lines
        y_pos = title_y
        line_spacing = title_font_height + 1
        for line in lines[:max_title_lines]:
            bbox = draw.textbbox((0, 0), line, font=self.title_font)
            text_width = bbox[2] - bbox[0]
            x_pos = (width - text_width) // 2
            draw.text((x_pos, y_pos), line, font=self.title_font, fill=self.text_color)
            y_pos += line_spacing

    def _wrap_text(self, text: str, draw: ImageDraw.ImageDraw,
                   font: ImageFont.ImageFont, max_width: int) -> List[str]:
        """
        Wrap text to fit within max_width.

        Args:
            text: Text to wrap
            draw: ImageDraw instance for measuring
            font: Font to use for measuring
            max_width: Maximum width in pixels

        Returns:
            List of wrapped lines
        """
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return lines
    
    def _format_event_date(self, event: Dict) -> str:
        """Format event date."""
        start = event.get('start', {})
        
        try:
            if 'date' in start:
                # All-day event
                date_obj = datetime.fromisoformat(start['date'])
                return date_obj.strftime('%m/%d')
            elif 'dateTime' in start:
                # Timed event
                date_str = start['dateTime'].replace('Z', '+00:00')
                date_obj = datetime.fromisoformat(date_str)
                if self.timezone:
                    date_obj = date_obj.astimezone(self.timezone)
                return date_obj.strftime('%m/%d')
        except Exception as e:
            self.logger.warning(f"Error formatting event date: {e}")
        
        return ''
    
    def _format_event_time(self, event: Dict) -> str:
        """Format event time."""
        start = event.get('start', {})
        
        try:
            if 'dateTime' in start:
                date_str = start['dateTime'].replace('Z', '+00:00')
                date_obj = datetime.fromisoformat(date_str)
                if self.timezone:
                    date_obj = date_obj.astimezone(self.timezone)
                return date_obj.strftime('%I:%M%p').lower().lstrip('0')
        except Exception as e:
            self.logger.warning(f"Error formatting event time: {e}")
        
        return 'All Day'
    
    def _display_no_events(self):
        """Display message when no events are available."""
        self.display_manager.clear()
        width, height = self._get_display_dimensions()
        draw = ImageDraw.Draw(self.display_manager.image)

        # Ensure font is loaded
        if self.datetime_font is None:
            self._load_fonts()

        message = "No Events"
        bbox = draw.textbbox((0, 0), message, font=self.datetime_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Center the message
        x_pos = (width - text_width) // 2
        y_pos = (height - text_height) // 2

        draw.text((x_pos, y_pos), message, font=self.datetime_font, fill=(150, 150, 150))
        self.display_manager.update_display()

    def _display_error(self):
        """Display error message."""
        self.display_manager.clear()
        width, height = self._get_display_dimensions()
        draw = ImageDraw.Draw(self.display_manager.image)

        # Ensure font is loaded
        if self.datetime_font is None:
            self._load_fonts()

        message = "Cal Error"
        bbox = draw.textbbox((0, 0), message, font=self.datetime_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Center the message
        x_pos = (width - text_width) // 2
        y_pos = (height - text_height) // 2

        draw.text((x_pos, y_pos), message, font=self.datetime_font, fill=(255, 0, 0))
        self.display_manager.update_display()
    
    # ==================== Vegas Scroll Integration ====================

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """
        Get content for Vegas-style continuous scroll mode.

        Returns a list of PIL Images, one for each calendar event.
        Each event becomes a separate scrollable item in the Vegas ticker.

        Returns:
            List of PIL Images for each event, or None if no events
        """
        if not self.events:
            return None

        try:
            # Render each event to a separate image
            images = []
            width, height = self._get_display_dimensions()

            for event in self.events:
                img = self._render_event_image(event, width, height)
                images.append(img)

            return images if images else None

        except Exception as e:
            self.logger.error(f"Error generating Vegas content: {e}", exc_info=True)
            return None

    def get_vegas_content_type(self) -> str:
        """
        Indicate the type of content this plugin provides for Vegas scroll.

        Returns 'multi' because we have multiple calendar events to scroll.
        Returns 'none' if there are no events to display.

        Returns:
            'multi' if events exist, 'none' otherwise
        """
        if self.events:
            return 'multi'
        return 'none'

    def get_vegas_display_mode(self) -> VegasDisplayMode:
        """
        Get the display mode for Vegas scroll integration.

        Calendar events scroll continuously within the stream alongside
        other multi-item content like sports scores and odds.

        Returns:
            VegasDisplayMode.SCROLL for multi-event display
        """
        # Check for explicit config setting first
        config_mode = self.config.get("vegas_mode")
        if config_mode:
            try:
                return VegasDisplayMode(config_mode)
            except ValueError:
                self.logger.warning(
                    f"Invalid vegas_mode '{config_mode}' for {self.plugin_id}, using SCROLL"
                )

        # Default to SCROLL for multi-event content
        return VegasDisplayMode.SCROLL

    def get_supported_vegas_modes(self) -> List[VegasDisplayMode]:
        """
        Return list of Vegas display modes this plugin supports.

        Calendar supports both SCROLL (events flow with the ticker)
        and FIXED_SEGMENT (calendar shows as a static block).

        Returns:
            List of supported VegasDisplayMode values
        """
        return [VegasDisplayMode.SCROLL, VegasDisplayMode.FIXED_SEGMENT]

    # ==================== End Vegas Scroll Integration ====================

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 30.0)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'events_loaded': len(self.events),
            'calendars': self.calendars,
            'service_available': self.service is not None,
            'authenticated': self.service is not None
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.events = []
        self.service = None
        self.logger.info("Calendar plugin cleaned up")
