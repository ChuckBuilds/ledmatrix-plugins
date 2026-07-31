"""
Jellyfin Now Playing Plugin for LEDMatrix

Polls a Jellyfin media server's /Sessions endpoint and shows what's currently
playing: the poster image on the left, with the title, a subtitle (series or
user name) and a playback progress bar on the right. Shows a "Nothing Playing"
screen when the server is idle and short on-panel error messages when the
server is unreachable or the API key is rejected.

API Version: 1.0.0
"""

import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

# 1 tick = 100 nanoseconds in Jellyfin's API
TICKS_PER_SECOND = 10_000_000

PAUSED_BAR_COLOR = (255, 160, 0)
ERROR_TEXT_COLOR = (255, 80, 80)
NOTHING_PLAYING_COLOR = (140, 140, 140)
PLACEHOLDER_OUTLINE = (60, 60, 60)
PLACEHOLDER_FILL = (20, 20, 20)


class JellyfinNowPlayingPlugin(BasePlugin):
    """
    Jellyfin Now Playing plugin for LEDMatrix.

    Displays the active Jellyfin session:
    - Poster art (series poster for TV episodes) fitted to the panel height
    - Title and subtitle with marquee scrolling when they don't fit
    - Playback progress bar, extrapolated between polls so it moves smoothly

    Configuration options:
        jellyfin_url (str): Base URL of the Jellyfin server (required)
        api_key (str): Jellyfin API key (stored in secrets, required)
        username (str): Only show sessions for this Jellyfin user (optional)
        content_types (list): Which media types to show (Movie/Episode/Audio)
        show_progress (bool): Draw the playback progress bar
        show_paused (bool): Treat paused sessions as playing
        update_interval (int): Session poll interval in seconds (default: 10)
        progress_bar_match_text (bool): Size the progress bar to the widest
            text line rather than the whole text area (default: True)
    """

    # Floor for the content-matched progress bar, so a very short title still
    # leaves something recognisable as a progress indicator.
    MIN_PROGRESS_BAR_WIDTH = 24

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the Jellyfin Now Playing plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Connection settings
        self.jellyfin_url = (config.get('jellyfin_url') or '').strip().rstrip('/')
        self.api_key = (config.get('api_key') or '').strip()  # From merged secrets
        self.username = (config.get('username') or '').strip()
        self.content_types = config.get('content_types', ['Movie', 'Episode', 'Audio'])
        self.show_progress = config.get('show_progress', True)
        self.show_paused = config.get('show_paused', True)
        self.update_interval_config = config.get('update_interval', 10)

        # Scrolling settings
        self.scroll_enabled = config.get('scroll_enabled', True)
        self.scroll_speed = max(1, int(config.get('scroll_speed', 5)))
        self.scroll_separator = config.get('scroll_separator', '   ')

        # Customization (fonts/colors), mirroring the schema defaults
        customization = config.get('customization', {})
        title_text = customization.get('title_text', {})
        subtitle_text = customization.get('subtitle_text', {})
        progress_bar = customization.get('progress_bar', {})

        self.title_color = self._parse_color(title_text.get('text_color'), (255, 255, 255))
        self.subtitle_color = self._parse_color(subtitle_text.get('text_color'), (170, 170, 170))
        self.bar_color = self._parse_color(progress_bar.get('bar_color'), (124, 77, 255))
        self.bar_background = self._parse_color(progress_bar.get('background_color'), (40, 40, 40))

        self._font_cache: Dict[Tuple[str, int], Any] = {}
        self.title_font = self._load_font(title_text.get('font', '5by7.regular.ttf'),
                                          int(title_text.get('font_size', 7)))
        self.subtitle_font = self._load_font(subtitle_text.get('font', '4x6-font.ttf'),
                                             int(subtitle_text.get('font_size', 6)))

        # State
        self.now_playing: Optional[Dict[str, Any]] = None
        self._error: Optional[str] = None  # Short on-panel message when we can't
        # fetch sessions (missing config, bad key, unreachable server).
        self._has_fetched = False

        # Single-slot poster cache: only one poster is ever on screen, so an
        # in-memory (item id, box size) keyed slot is all we need.
        self._poster_image: Optional[Image.Image] = None
        self._poster_key: Optional[Tuple[str, Tuple[int, int]]] = None

        # Marquee state, one slot per text field
        self._scroll_pos: Dict[str, int] = {'title': 0, 'subtitle': 0}
        self._scroll_tick: Dict[str, int] = {'title': 0, 'subtitle': 0}

        # Anti-flash guard for the static screens (error / nothing playing)
        self._last_static_signature: Optional[str] = None

        # Scratch surface for text measurement
        self._measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))

        if self.enabled:
            self.logger.info("Jellyfin Now Playing plugin initialized (server: %s)",
                             self.jellyfin_url or 'not configured')
        else:
            self.logger.info("Jellyfin Now Playing plugin disabled")

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_color(color_value, default) -> Tuple[int, int, int]:
        """Parse an RGB array from config, falling back to a default."""
        if color_value is None:
            return tuple(default)
        try:
            parsed = tuple(int(c) for c in color_value)
            if len(parsed) == 3:
                return parsed
        except (ValueError, TypeError):
            pass
        return tuple(default)

    def _load_font(self, font_name: str, font_size: int):
        """Load a font from assets/fonts, caching per (name, size).

        Tries the project root's assets/fonts directory (the plugin runs from
        the LEDMatrix core checkout) with a couple of resolution strategies,
        and falls back to PIL's default bitmap font.
        """
        cache_key = (font_name, font_size)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        font = None
        rel_path = os.path.join('assets', 'fonts', font_name)
        candidates = [
            rel_path,
            os.path.join(os.getcwd(), rel_path),
            str(Path(__file__).parent.parent.parent / rel_path),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                try:
                    font = ImageFont.truetype(candidate, font_size)
                    break
                except Exception as e:
                    self.logger.warning("Could not load font %s: %s", candidate, e)
        if font is None:
            self.logger.warning("Font %s not found, using default", font_name)
            font = ImageFont.load_default()

        self._font_cache[cache_key] = font
        return font

    def _dims(self) -> Tuple[int, int]:
        """Panel (width, height); prefers .width/.height, falls back to .matrix."""
        width = getattr(self.display_manager, 'width', None)
        height = getattr(self.display_manager, 'height', None)
        if not width or not height:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
        return int(width), int(height)

    def _text_width(self, text: str, font) -> int:
        """Measure rendered text width in pixels."""
        try:
            return int(self._measure_draw.textlength(text, font=font))
        except Exception:
            bbox = self._measure_draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]

    def _font_height(self, font) -> int:
        """Approximate line height for a font."""
        try:
            bbox = self._measure_draw.textbbox((0, 0), 'Ay', font=font)
            return max(1, bbox[3] - bbox[1])
        except Exception:
            return 8

    # ------------------------------------------------------------------
    # Jellyfin API
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        return {'Authorization': f'MediaBrowser Token="{self.api_key}"'}

    def _fetch_sessions(self) -> Optional[list]:
        """Fetch active sessions from Jellyfin, cache-first."""
        cache_key = f"{self.plugin_id}:sessions"
        cached = self.cache_manager.get(cache_key, max_age=self.update_interval_config)
        if cached is not None:
            self.logger.debug("Using cached Jellyfin sessions")
            return cached

        url = f"{self.jellyfin_url}/Sessions"
        try:
            response = requests.get(
                url,
                params={'activeWithinSeconds': 60},
                headers=self._auth_headers(),
                timeout=10,
            )
            response.raise_for_status()
            sessions = response.json()
            if not isinstance(sessions, list):
                self.logger.error("Unexpected /Sessions response type: %s", type(sessions).__name__)
                return None
            self._error = None
            self.cache_manager.set(cache_key, sessions, ttl=self.update_interval_config)
            return sessions
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (401, 403):
                self._error = "Jellyfin: Update API Key"
                self.logger.error("Jellyfin authentication failed (HTTP %s); "
                                  "update the credential in the plugin settings.", status_code)
            else:
                self._error = "Jellyfin: HTTP Error"
                self.logger.error("Error fetching Jellyfin sessions (HTTP %s)", status_code)
            return None
        except requests.exceptions.RequestException as e:
            self._error = "Jellyfin: Unreachable"
            self.logger.error("Could not reach Jellyfin at %s: %s",
                              self.jellyfin_url, type(e).__name__)
            return None
        except ValueError as e:
            self._error = "Jellyfin: Bad Response"
            self.logger.error("Error parsing Jellyfin response: %s", e)
            return None

    def _select_session(self, sessions: list) -> Optional[Dict[str, Any]]:
        """Pick the session to display and normalize it.

        Filters by username / content type / paused state, then prefers
        actively playing sessions over paused ones (stable order otherwise).
        """
        candidates = []
        for session in sessions:
            if not isinstance(session, dict):
                continue
            item = session.get('NowPlayingItem')
            if not item:
                continue
            if self.username and session.get('UserName', '').lower() != self.username.lower():
                continue
            if self.content_types and item.get('Type') not in self.content_types:
                continue
            is_paused = bool(session.get('PlayState', {}).get('IsPaused', False))
            if is_paused and not self.show_paused:
                continue
            candidates.append((is_paused, session, item))

        if not candidates:
            return None

        # Playing before paused; Python's sort is stable so server order is kept
        candidates.sort(key=lambda entry: entry[0])
        is_paused, session, item = candidates[0]

        item_type = item.get('Type', '')
        if item_type == 'Episode':
            poster_item_id = item.get('SeriesId') or item.get('Id')
            subtitle = item.get('SeriesName') or session.get('UserName', '')
        elif item_type == 'Audio':
            poster_item_id = item.get('AlbumId') or item.get('Id')
            subtitle = ', '.join(item.get('Artists', [])) or session.get('UserName', '')
        else:
            poster_item_id = item.get('Id')
            subtitle = session.get('UserName', '')

        play_state = session.get('PlayState', {})
        return {
            'item_id': item.get('Id'),
            'poster_item_id': poster_item_id,
            'title': item.get('Name', ''),
            'subtitle': subtitle,
            'type': item_type,
            'is_paused': is_paused,
            'position_s': int(play_state.get('PositionTicks', 0) or 0) // TICKS_PER_SECOND,
            'duration_s': int(item.get('RunTimeTicks', 0) or 0) // TICKS_PER_SECOND,
            'fetched_at': time.time(),
        }

    def _fetch_poster(self, poster_item_id: str, box: Tuple[int, int]) -> Optional[Image.Image]:
        """Download the item's primary image and fit it into `box`.

        Requests an oversized image from Jellyfin, thumbnails it (aspect
        preserved) and centers it on a black canvas of exactly `box`.
        """
        url = f"{self.jellyfin_url}/Items/{poster_item_id}/Images/Primary"
        try:
            response = requests.get(
                url,
                params={
                    'maxWidth': box[0] * 4,
                    'maxHeight': box[1] * 4,
                    'quality': 90,
                },
                headers=self._auth_headers(),
                timeout=5,
            )
            response.raise_for_status()
            img = Image.open(BytesIO(response.content)).convert('RGB')
            img.thumbnail(box, Image.Resampling.LANCZOS)
            canvas = Image.new('RGB', box, (0, 0, 0))
            canvas.paste(img, ((box[0] - img.width) // 2, (box[1] - img.height) // 2))
            return canvas
        except (requests.exceptions.RequestException, IOError) as e:
            self.logger.warning("Could not fetch poster for item %s: %s",
                                poster_item_id, type(e).__name__)
            return None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Poll Jellyfin for the active session and refresh the poster."""
        if not self.enabled:
            return
        self._has_fetched = True

        if not self.jellyfin_url or not self.api_key:
            self._error = "Jellyfin: Set URL/API Key"
            self.now_playing = None
            return

        sessions = self._fetch_sessions()
        if sessions is None:
            # Keep showing the last known state briefly? No — the error screen
            # is more honest than a frozen progress bar.
            self.now_playing = None
            return

        previous_item = self.now_playing.get('item_id') if self.now_playing else None
        self.now_playing = self._select_session(sessions)

        if self.now_playing is None:
            self._drop_poster()
            return

        if self.now_playing['item_id'] != previous_item:
            self._reset_scroll()

        # Fetch the poster here (never in display()) when the item or panel
        # geometry changed since the cached one.
        poster_item_id = self.now_playing.get('poster_item_id')
        if poster_item_id:
            box = self._poster_box()
            key = (poster_item_id, box)
            if key != self._poster_key:
                self._poster_image = self._fetch_poster(poster_item_id, box)
                self._poster_key = key
        else:
            self._drop_poster()

    def display(self, force_clear: bool = False) -> None:
        """Render the now-playing screen. Called by the plugin system."""
        if not self.enabled:
            return

        # First render can happen before the core's first update() tick
        if not self._has_fetched:
            self.update()

        if self._error:
            self._render_static(self._error, ERROR_TEXT_COLOR, force_clear)
            return

        if not self.now_playing:
            self._drop_poster()
            self._reset_scroll()
            self._render_static("Nothing Playing", NOTHING_PLAYING_COLOR, force_clear)
            return

        self._last_static_signature = None
        if force_clear:
            self.display_manager.clear()
        image = self._render_now_playing()
        self.display_manager.image = image
        self.display_manager.update_display()

    def validate_config(self) -> bool:
        """Validate plugin configuration.

        Missing URL/API key is reported on-panel instead of failing validation,
        so a freshly installed plugin shows a setup hint rather than nothing.
        """
        if not super().validate_config():
            return False
        if not self.jellyfin_url or not self.api_key:
            self.logger.warning("jellyfin_url and api_key are not configured yet; "
                                "the panel will show a setup message")
        return True

    def get_info(self) -> Dict[str, Any]:
        """Info for the web UI."""
        info = super().get_info()
        info.update({
            'server': self.jellyfin_url or 'not configured',
            'now_playing': self.now_playing.get('title') if self.now_playing else None,
            'state': ('error' if self._error
                      else 'paused' if self.now_playing and self.now_playing['is_paused']
                      else 'playing' if self.now_playing
                      else 'idle'),
            'error': self._error,
        })
        return info

    def cleanup(self) -> None:
        """Clean up on unload."""
        self._drop_poster()
        super().cleanup()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _poster_box(self) -> Tuple[int, int]:
        """Poster box: portrait 2:3 fitted to the full panel height."""
        _, height = self._dims()
        return (max(1, round(height * 2 / 3)), height)

    def _drop_poster(self) -> None:
        self._poster_image = None
        self._poster_key = None

    def _reset_scroll(self) -> None:
        for field in self._scroll_pos:
            self._scroll_pos[field] = 0
            self._scroll_tick[field] = 0

    def _render_static(self, message: str, color: Tuple[int, int, int],
                       force_clear: bool) -> None:
        """Draw a centered single-line message, skipping identical redraws."""
        width, height = self._dims()
        signature = f"{message}|{width}x{height}"
        if not force_clear and signature == self._last_static_signature:
            return
        self._last_static_signature = signature

        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)
        font = self.subtitle_font
        text = self._truncate_text_with_ellipsis(message, font, width - 2)
        text_w = self._text_width(text, font)
        text_h = self._font_height(font)
        draw.text(((width - text_w) // 2, (height - text_h) // 2),
                  text, font=font, fill=color)
        self.display_manager.image = image
        self.display_manager.update_display()

    def _render_now_playing(self) -> Image.Image:
        """Build the full now-playing frame."""
        width, height = self._dims()
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)
        info = self.now_playing

        # Poster on the left (or a placeholder when the fetch failed)
        poster_w, _ = self._poster_box()
        if self._poster_image is not None:
            image.paste(self._poster_image, (0, 0))
        else:
            draw.rectangle([0, 0, poster_w - 1, height - 1],
                           fill=PLACEHOLDER_FILL, outline=PLACEHOLDER_OUTLINE)

        text_x = poster_w + 2
        text_w = width - text_x - 1
        if text_w <= 0:
            return image

        title_h = self._font_height(self.title_font)
        sub_h = self._font_height(self.subtitle_font)
        bar_h = 4 if height >= 64 else 3 if width >= 128 else 2

        title_y = 2
        subtitle_y = title_y + title_h + 3

        # Paused indicator: two small vertical bars before the title
        title_text_x = text_x
        title_text_w = text_w
        if info['is_paused']:
            glyph_h = min(title_h, 6)
            draw.rectangle([text_x, title_y, text_x + 1, title_y + glyph_h - 1],
                           fill=PAUSED_BAR_COLOR)
            draw.rectangle([text_x + 3, title_y, text_x + 4, title_y + glyph_h - 1],
                           fill=PAUSED_BAR_COLOR)
            title_text_x = text_x + 7
            title_text_w = text_w - 7

        title = self._marquee(info['title'], self.title_font, title_text_w, 'title')
        draw.text((title_text_x, title_y), title, font=self.title_font, fill=self.title_color)

        # Subtitle row, with a right-aligned time readout on wide panels
        position_s, duration_s = self._current_position()
        subtitle_w = text_w
        if width >= 256 and height < 64 and duration_s > 0:
            time_str = f"{self._format_time(position_s)}/{self._format_time(duration_s)}"
            time_w = self._text_width(time_str, self.subtitle_font)
            draw.text((text_x + text_w - time_w, subtitle_y), time_str,
                      font=self.subtitle_font, fill=self.subtitle_color)
            subtitle_w = text_w - time_w - 4

        subtitle = self._marquee(info['subtitle'], self.subtitle_font, subtitle_w, 'subtitle')
        draw.text((text_x, subtitle_y), subtitle,
                  font=self.subtitle_font, fill=self.subtitle_color)

        # Dedicated time row on tall panels
        if height >= 64 and duration_s > 0:
            time_str = f"{self._format_time(position_s)} / {self._format_time(duration_s)}"
            time_str = self._truncate_text_with_ellipsis(time_str, self.subtitle_font, text_w)
            draw.text((text_x, subtitle_y + sub_h + 3), time_str,
                      font=self.subtitle_font, fill=self.subtitle_color)

        # Progress bar along the bottom of the text area, no wider than the text
        # it sits under. Spanning the whole text area made the frame full-width
        # whatever the title length: on a 512px panel a short episode name left a
        # bar stretching across the display, and because a bar is drawn pixels
        # there is nothing for a ticker to trim back. Sizing it to the content
        # keeps the block compact and lets the blank remainder be reclaimed.
        if self.show_progress and duration_s > 0:
            bar_w = self._content_width(text_w)
            bar_y = height - bar_h - 2
            bar_x2 = text_x + bar_w - 1
            draw.rectangle([text_x, bar_y, bar_x2, bar_y + bar_h - 1],
                           fill=self.bar_background)
            progress = min(1.0, max(0.0, position_s / duration_s))
            fill_w = int(round((bar_w - 1) * progress))
            if fill_w > 0:
                color = PAUSED_BAR_COLOR if info['is_paused'] else self.bar_color
                draw.rectangle([text_x, bar_y, text_x + fill_w, bar_y + bar_h - 1],
                               fill=color)

        return image

    def _content_width(self, available: int) -> int:
        """
        Width of the widest text line, capped at ``available``.

        Used to size the progress bar to its content instead of the whole text
        area. A line long enough to be marqueed measures wider than the area and
        so pins the bar to full width, which is right — that line really does
        fill it. A floor keeps a very short title from leaving a stub too small
        to read as a progress indicator.

        Set ``progress_bar_match_text`` false for the original full-width bar.
        """
        if not self.config.get('progress_bar_match_text', True):
            return available

        info = self.now_playing or {}
        widest = 0
        for text, font in (
            (info.get('title'), self.title_font),
            (info.get('subtitle'), self.subtitle_font),
        ):
            if not text:
                continue
            try:
                widest = max(widest, self._text_width(text, font))
            except Exception:
                # Measurement is best-effort; never lose the bar over it.
                return available

        if widest <= 0:
            return available
        return max(min(self.MIN_PROGRESS_BAR_WIDTH, available), min(widest, available))

    def _current_position(self) -> Tuple[int, int]:
        """Playback position extrapolated between polls, clamped to duration."""
        info = self.now_playing
        position = info['position_s']
        duration = info['duration_s']
        if not info['is_paused']:
            position += int(time.time() - info['fetched_at'])
        if duration > 0:
            position = min(position, duration)
        return max(0, position), duration

    @staticmethod
    def _format_time(seconds: int) -> str:
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    # ------------------------------------------------------------------
    # Text fitting / marquee (adapted from ledmatrix-music)
    # ------------------------------------------------------------------

    def _clip_text_to_width(self, text: str, font, max_width: int) -> str:
        """Trim trailing characters so the rendered text fits within max_width px."""
        if max_width <= 0:
            return ""
        if not text:
            return text
        if self._text_width(text, font) <= max_width:
            return text
        clipped = text
        while clipped and self._text_width(clipped, font) > max_width:
            clipped = clipped[:-1]
        return clipped

    def _truncate_text_with_ellipsis(self, text: str, font, max_width: int) -> str:
        """Truncate text to fit max_width px, appending "..." when trimmed."""
        if max_width <= 0:
            return ""
        if not text:
            return text
        if self._text_width(text, font) <= max_width:
            return text
        ellipsis = "..."
        ellipsis_width = self._text_width(ellipsis, font)
        if ellipsis_width >= max_width:
            return self._clip_text_to_width(text, font, max_width)
        clipped = self._clip_text_to_width(text, font, max_width - ellipsis_width)
        return clipped + ellipsis

    def _marquee(self, text: str, font, max_width: int, field: str) -> str:
        """Return this frame's visible text for a field, advancing the scroll.

        When the text fits, it's drawn as-is. When it doesn't and scrolling is
        enabled, the lead character rotates through `text + separator` every
        `scroll_speed` frames; the result is always clipped to the viewport.
        """
        if max_width <= 0:
            return ""
        if not text or self._text_width(text, font) <= max_width:
            self._scroll_pos[field] = 0
            self._scroll_tick[field] = 0
            return text
        if not self.scroll_enabled:
            return self._truncate_text_with_ellipsis(text, font, max_width)

        full = text + self.scroll_separator
        pos = self._scroll_pos[field] % len(full)
        rotated = full[pos:] + full[:pos]

        self._scroll_tick[field] += 1
        if self._scroll_tick[field] >= self.scroll_speed:
            self._scroll_tick[field] = 0
            self._scroll_pos[field] = (pos + 1) % len(full)

        return self._clip_text_to_width(rotated, font, max_width)
