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

API Version: 1.0.0
"""

import os
import logging
import time
import pickle
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

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
        self.update_interval = config.get('update_interval', 300)
        self.show_all_day = config.get('show_all_day_events', True)
        self.rotation_interval = config.get('event_rotation_interval', 10)
        
        # State
        self.service = None
        self.events = []
        self.current_event_index = 0
        self.last_update = 0
        self.last_rotation = time.time()
        
        # Colors
        self.text_color = (255, 255, 255)
        self.time_color = (255, 200, 100)
        self.date_color = (150, 150, 255)
        
        # Get timezone
        try:
            timezone_str = 'UTC'
            if hasattr(self.plugin_manager, 'config_manager'):
                main_config = self.plugin_manager.config_manager.load_config()
                timezone_str = main_config.get('timezone', 'UTC')
            self.timezone = pytz.timezone(timezone_str) if pytz else None
        except:
            self.timezone = pytz.utc if pytz else None
        
        # Authenticate
        self._authenticate()
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Calendar plugin initialized with {len(self.calendars)} calendar(s)")
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
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
    
    def _authenticate(self):
        """Authenticate with Google Calendar API."""
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as token:
                    creds = pickle.load(token)
                self.logger.info("Loaded existing credentials")
            except Exception as e:
                self.logger.error(f"Error loading credentials: {e}")
        
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
                    return
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES)
                    creds = flow.run_local_server(port=0)
                    self.logger.info("Obtained new credentials")
                except Exception as e:
                    self.logger.error(f"Error getting new credentials: {e}")
                    return
            
            # Save credentials
            try:
                with open(self.token_file, 'wb') as token:
                    pickle.dump(creds, token)
                self.logger.info("Saved credentials")
            except Exception as e:
                self.logger.error(f"Error saving credentials: {e}")
        
        # Build service
        try:
            self.service = build('calendar', 'v3', credentials=creds)
            self.logger.info("Calendar service built successfully")
        except Exception as e:
            self.logger.error(f"Error building service: {e}")
    
    def update(self) -> None:
        """Fetch upcoming calendar events."""
        current_time = time.time()
        
        # Check if we need to update
        if current_time - self.last_update < self.update_interval:
            return
        
        if not self.service:
            self.logger.warning("Calendar service not available")
            return
        
        try:
            # Fetch events from all configured calendars
            all_events = []
            
            for calendar_id in self.calendars:
                try:
                    now = datetime.utcnow().isoformat() + 'Z'
                    events_result = self.service.events().list(
                        calendarId=calendar_id,
                        timeMin=now,
                        maxResults=self.max_events,
                        singleEvents=True,
                        orderBy='startTime'
                    ).execute()
                    
                    events = events_result.get('items', [])
                    all_events.extend(events)
                    
                    self.logger.info(f"Fetched {len(events)} events from calendar: {calendar_id}")
                
                except Exception as e:
                    self.logger.error(f"Error fetching events from {calendar_id}: {e}")
            
            # Sort all events by start time
            all_events.sort(key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
            
            # Limit to max_events
            self.events = all_events[:self.max_events]
            
            self.last_update = current_time
            
            if self.events:
                self.logger.info(f"Total events fetched: {len(self.events)}")
            else:
                self.logger.info("No upcoming events found")
        
        except Exception as e:
            self.logger.error(f"Error updating calendar: {e}")
    
    def display(self, force_clear: bool = False) -> None:
        """
        Display calendar events.
        
        Args:
            force_clear: If True, clear display before rendering
        """
        if not self.events:
            self._display_no_events()
            return
        
        try:
            # Rotate through events
            current_time = time.time()
            if current_time - self.last_rotation >= self.rotation_interval:
                self.current_event_index = (self.current_event_index + 1) % len(self.events)
                self.last_rotation = current_time
            
            # Display current event
            event = self.events[self.current_event_index]
            self._display_event(event)
        
        except Exception as e:
            self.logger.error(f"Error displaying calendar: {e}")
            self._display_error()
    
    def _display_event(self, event: Dict):
        """Display a single calendar event."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Load fonts
        try:
            datetime_font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
            title_font = ImageFont.truetype('assets/fonts/PressStart2P-Regular.ttf', 6)
        except:
            datetime_font = ImageFont.load_default()
            title_font = ImageFont.load_default()
        
        # Format date and time
        date_text = self._format_event_date(event)
        time_text = self._format_event_time(event)
        datetime_text = f"{date_text} {time_text}".strip()
        
        # Draw date/time centered
        bbox = draw.textbbox((0, 0), datetime_text, font=datetime_font)
        text_width = bbox[2] - bbox[0]
        x_pos = (self.display_manager.matrix.width - text_width) // 2
        draw.text((x_pos, 2), datetime_text, font=datetime_font, fill=self.time_color)
        
        # Draw event title (wrapped if needed)
        summary = event.get('summary', 'No Title')
        y_pos = 12
        
        # Simple word wrapping
        words = summary.split()
        lines = []
        current_line = []
        max_width = self.display_manager.matrix.width - 4
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=title_font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        # Draw wrapped lines (max 2 lines)
        for i, line in enumerate(lines[:2]):
            bbox = draw.textbbox((0, 0), line, font=title_font)
            text_width = bbox[2] - bbox[0]
            x_pos = (self.display_manager.matrix.width - text_width) // 2
            draw.text((x_pos, y_pos), line, font=title_font, fill=self.text_color)
            y_pos += 8
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _format_event_date(self, event: Dict) -> str:
        """Format event date."""
        start = event.get('start', {})
        
        if 'date' in start:
            # All-day event
            date_obj = datetime.fromisoformat(start['date'])
            return date_obj.strftime('%m/%d')
        elif 'dateTime' in start:
            # Timed event
            date_obj = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
            if self.timezone:
                date_obj = date_obj.astimezone(self.timezone)
            return date_obj.strftime('%m/%d')
        
        return ''
    
    def _format_event_time(self, event: Dict) -> str:
        """Format event time."""
        start = event.get('start', {})
        
        if 'dateTime' in start:
            date_obj = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
            if self.timezone:
                date_obj = date_obj.astimezone(self.timezone)
            return date_obj.strftime('%I:%M%p').lower().lstrip('0')
        
        return 'All Day'
    
    def _display_no_events(self):
        """Display message when no events are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "No Events", font=font, fill=(150, 150, 150))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def _display_error(self):
        """Display error message."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype('assets/fonts/4x6-font.ttf', 8)
        except:
            font = ImageFont.load_default()
        
        draw.text((5, 12), "Cal Error", font=font, fill=(255, 0, 0))
        
        self.display_manager.image = img.copy()
        self.display_manager.update_display()
    
    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 30.0)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'events_loaded': len(self.events),
            'calendars': self.calendars,
            'service_available': self.service is not None
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.events = []
        self.service = None
        self.logger.info("Calendar plugin cleaned up")

