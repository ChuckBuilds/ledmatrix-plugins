"""
BirdNET-Go Plugin for LEDMatrix

Shows what BirdNET-Go is hearing, in two display modes:

  - ``birdnet_go``    the most recently identified bird — common name,
                      confidence, time since detection, and a species image
  - ``birdnet_stats`` today's totals — species count, detection count, and the
                      most-heard species

Data comes from BirdNET-Go's REST API by polling, which is all most setups
need. MQTT is optional and only buys sub-second latency for the interrupt
pop-up; without it, a new bird shows up on the next poll.

API Version: 1.0.0
"""

import base64
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

DETECTION_MODE = 'birdnet_go'
STATS_MODE = 'birdnet_stats'

# A frame's delta-time feeds the scroll position. Rotation can park this plugin
# for minutes at a time, so cap dt or the name jumps a screen-width on return.
_MAX_FRAME_DT = 0.25

# Image caches are bounded: a yard accumulates new species for months, and an
# unbounded cache of decoded photos would grow for as long as the service runs.
_MAX_SOURCE_IMAGES = 32
_MAX_PANEL_IMAGES = 16

# Case-insensitive fallback variants tried when a mapped field is missing.
_FIELD_VARIANTS = {
    'common_name': ['CommonName', 'commonName', 'common_name', 'Common_Name'],
    'scientific_name': ['ScientificName', 'scientificName', 'scientific_name', 'Scientific_Name'],
    'confidence': ['Confidence', 'confidence'],
    'time': ['Timestamp', 'timestamp', 'Time', 'time', 'BeginTime', 'beginTime'],
}

_MEASURE_DRAW = ImageDraw.Draw(Image.new('RGB', (1, 1)))


class BirdNetGoPlugin(BasePlugin):
    """Display BirdNET-Go bird detections and daily stats on the LED matrix."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        mqtt_config = config.get('mqtt', {}) or {}
        self.mqtt_enabled = bool(mqtt_config.get('enabled', False))
        self.mqtt_host = mqtt_config.get('host', '')
        self.mqtt_port = int(mqtt_config.get('port', 1883))
        self.mqtt_username = mqtt_config.get('username', '')
        self.mqtt_password = mqtt_config.get('password', '')
        self.mqtt_client_id = mqtt_config.get('client_id', 'ledmatrix-birdnet-go')
        self.mqtt_keepalive = int(mqtt_config.get('keepalive', 60))
        self.mqtt_topic = mqtt_config.get('topic', 'birdnet/detections')

        if self.mqtt_enabled and mqtt is None:
            self.logger.error(
                "mqtt.enabled is set but paho-mqtt is not installed; falling back to REST "
                "polling. Install with: pip install paho-mqtt")
            self.mqtt_enabled = False

        api_config = config.get('birdnet_api', {}) or {}
        self.api_base_url = str(api_config.get('base_url', '') or '').rstrip('/')
        self.api_timeout = float(api_config.get('request_timeout', 5.0))
        self.poll_interval = float(api_config.get('poll_interval', 60))

        display_config = config.get('display', {}) or {}
        self.mode = display_config.get('mode', 'both')
        self.interrupt_duration = float(display_config.get('interrupt_duration', 10))
        self.rotation_duration = float(display_config.get('rotation_duration', 15))
        self.min_confidence = float(display_config.get('min_confidence', 0.5))
        self.stale_after_s = int(display_config.get('stale_after_minutes', 120)) * 60
        self.show_image = bool(display_config.get('show_image', True))
        self.show_confidence = bool(display_config.get('show_confidence', True))
        self.show_time = bool(display_config.get('show_time', True))
        self.unique_species = bool(display_config.get('unique_species', True))
        self.max_species = max(1, int(display_config.get('max_species', 8)))
        self.show_today_count = bool(display_config.get('show_today_count', True))
        self.species_order = display_config.get('species_order', 'recent')

        stats_config = config.get('stats', {}) or {}
        self.stats_enabled = bool(stats_config.get('enabled', True))
        self.stats_top_n = int(stats_config.get('top_n', 5))
        self.stats_duration = float(stats_config.get('rotation_duration', 15))

        text_config = config.get('text', {}) or {}
        self.font_path = text_config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        self.font_size = int(text_config.get('font_size', 8))
        self.text_color = tuple(int(c) for c in text_config.get('text_color', [255, 255, 255]))
        self.bg_color = tuple(int(c) for c in text_config.get('background_color', [0, 0, 0]))
        self.accent_color = tuple(int(c) for c in text_config.get('accent_color', [255, 190, 0]))
        self.scroll_speed = float(text_config.get('scroll_speed', 30))
        self.scroll_gap_width = int(text_config.get('scroll_gap_width', 32))

        self.field_mapping = config.get('field_mapping', {}) or {}

        # MQTT state
        self.mqtt_client: Optional["mqtt.Client"] = None
        self.mqtt_thread: Optional[threading.Thread] = None
        self.mqtt_connected = False
        self.mqtt_reconnect_delay = 1.0
        self.mqtt_max_reconnect_delay = 60.0
        self.mqtt_stop_event = threading.Event()

        # Detection / stats state
        self.state_lock = threading.Lock()
        self.last_detection: Optional[Dict[str, Any]] = None
        self._last_detection_key: Optional[str] = None
        self._recent_species: List[Dict[str, Any]] = []
        self._cycle_index = 0
        self._cycle_started = 0.0
        self._cycle_key: Optional[str] = None
        self.daily_stats: Optional[Dict[str, Any]] = None
        # species -> decoded source PIL, and (species, w, h) -> panel-sized frame.
        self._species_img_cache: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._panel_img_cache: "OrderedDict[Tuple[str, int, int], Image.Image]" = OrderedDict()
        self._species_img_failed: set = set()  # species we already failed to fetch
        self._pending_image_fetch: Optional[str] = None
        self._scroll_pos = 0.0
        self._scroll_cache: Optional[Image.Image] = None
        self._scroll_cache_key: Optional[Tuple] = None
        self._last_frame_time = time.time()
        self._on_demand_until = 0.0
        self._last_poll = 0.0
        self._last_stats_poll = 0.0
        self._last_rendered_mode = DETECTION_MODE

        self._font_cache: Dict[int, Any] = {}
        self._resolved_font_path = self._resolve_font_path()
        self.font = self._font_for(self.font_size)

        self.logger.info(
            "BirdNET-Go plugin initialized (mode=%s, api=%s, mqtt=%s, stats=%s)",
            self.mode, self.api_base_url or 'unset',
            f"{self.mqtt_host}:{self.mqtt_port}" if self.mqtt_enabled else 'disabled',
            'on' if self.stats_enabled else 'off')

    # ------------------------------------------------------------------ fonts

    def _resolve_font_path(self) -> Optional[str]:
        """Locate the configured font, searching cwd and the project root."""
        font_path = self.font_path
        if not font_path:
            return None
        if os.path.isabs(font_path):
            return font_path if os.path.exists(font_path) else None
        if os.path.exists(font_path):
            return font_path
        cwd_path = os.path.join(os.getcwd(), font_path)
        if os.path.exists(cwd_path):
            return cwd_path
        project_path = Path(__file__).parent.parent.parent / font_path
        if project_path.exists():
            return str(project_path)
        self.logger.warning("Font not found: %s, using default", self.font_path)
        return None

    def _font_for(self, size: int):
        """Return the configured font at ``size``, cached per size."""
        size = max(4, int(size))
        cached = self._font_cache.get(size)
        if cached is not None:
            return cached
        font = None
        if self._resolved_font_path and self._resolved_font_path.lower().endswith('.ttf'):
            try:
                font = ImageFont.truetype(self._resolved_font_path, size)
            except Exception as e:
                self.logger.error("Failed to load font %s: %s", self._resolved_font_path, e)
        if font is None:
            font = ImageFont.load_default()
        self._font_cache[size] = font
        return font

    @staticmethod
    def _measure(text: str, font) -> Tuple[int, int, int]:
        """Return (width, height, y_offset) for ``text`` in ``font``."""
        bbox = _MEASURE_DRAW.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[1]

    def _truncate(self, text: str, font, max_w: int) -> str:
        """Trim ``text`` (with a trailing dot) until it fits ``max_w``."""
        if max_w <= 0:
            return ''
        if self._measure(text, font)[0] <= max_w:
            return text
        while text and self._measure(text + '.', font)[0] > max_w:
            text = text[:-1]
        return (text + '.') if text else ''

    def _first_fitting(self, options: List[str], font, max_w: int) -> str:
        """Pick the richest phrasing that fits, rather than truncating the longest.

        On a narrow panel "67%  46s ago" has to give something up; dropping the
        age reads far better than chopping it to "67.".
        """
        for text in options:
            if self._measure(text, font)[0] <= max_w:
                return text
        return self._truncate(options[-1], font, max_w) if options else ''

    # ------------------------------------------------------- payload parsing

    def _extract_field(self, payload: Dict[str, Any], field: str) -> Any:
        mapped = self.field_mapping.get(field)
        candidates = []
        if mapped:
            candidates.append(mapped)
        candidates.extend(v for v in _FIELD_VARIANTS.get(field, []) if v not in candidates)
        for key in candidates:
            if key in payload:
                return payload[key]
        # Last resort: case-insensitive scan
        lower_map = {k.lower(): k for k in payload.keys()}
        for key in candidates:
            actual = lower_map.get(key.lower())
            if actual is not None:
                return payload[actual]
        return None

    @staticmethod
    def _parse_detection_time(value: Any) -> Optional[float]:
        """Parse an ISO-8601 detection timestamp into epoch seconds.

        BirdNET-Go's REST feed returns fully-qualified stamps like
        ``2026-08-05T14:36:54-04:00``. Bare clock times ("14:36:54"), which some
        MQTT payloads carry, are unparseable here and fall back to arrival time.
        """
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.timestamp()

    def _normalize_payload(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Some BirdNET-Go versions wrap detection under a sub-object.
        candidate = raw
        for wrapper in ('detection', 'Detection', 'payload', 'data'):
            inner = raw.get(wrapper)
            if isinstance(inner, dict):
                candidate = inner
                break

        common = self._extract_field(candidate, 'common_name')
        sci = self._extract_field(candidate, 'scientific_name')
        conf = self._extract_field(candidate, 'confidence')
        ts = self._extract_field(candidate, 'time')

        if common is None and sci is None:
            self.logger.warning("Detection payload missing common/scientific name: %s",
                                list(candidate.keys())[:10])
            return None

        try:
            conf_f = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            conf_f = 0.0
        # Some feeds publish confidence as percent (0-100) rather than 0-1
        if conf_f > 1.5:
            conf_f = conf_f / 100.0

        detected_at = self._parse_detection_time(ts)
        common_str = str(common) if common else str(sci)
        # Prefer the server's row id so re-polling the same bird is a no-op.
        raw_id = candidate.get('id') or candidate.get('ID')
        key = str(raw_id) if raw_id is not None else f"{common_str}|{ts}"

        return {
            'common_name': common_str,
            'scientific_name': str(sci) if sci else '',
            'confidence': conf_f,
            'time_str': str(ts) if ts else '',
            'received_at': detected_at if detected_at is not None else time.time(),
            'key': key,
        }

    def _accept_detection(self, detection: Dict[str, Any], source: str) -> bool:
        """Adopt a detection as current. Returns False if it's a duplicate."""
        if detection['confidence'] < self.min_confidence:
            self.logger.debug("Dropping low-confidence detection: %s @ %.2f",
                              detection['common_name'], detection['confidence'])
            return False

        with self.state_lock:
            if detection.get('key') and detection['key'] == self._last_detection_key:
                return False
            self._last_detection_key = detection.get('key')
            self.last_detection = detection
            self._pending_image_fetch = (detection['scientific_name']
                                         or detection['common_name'])
            self._scroll_cache = None
            self._scroll_cache_key = None
            self._scroll_pos = 0.0

        try:
            self.cache_manager.set(f'{self.plugin_id}_last_detection', detection, ttl=86400)
        except Exception as e:
            self.logger.debug("Cache set failed: %s", e)

        self.logger.info("Detection via %s: %s (%.0f%%)", source,
                         detection['common_name'], detection['confidence'] * 100)

        # Only interrupt for a bird that was just heard. Polling surfaces old
        # detections at startup, and popping those over the rotation is noise.
        fresh_window = max(60.0, self.poll_interval * 2)
        if (self.mode in ('interrupt', 'both')
                and time.time() - detection['received_at'] <= fresh_window):
            self._trigger_on_demand(detection)
        return True

    # ----------------------------------------------------------------- MQTT

    def _on_mqtt_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        if rc == 0:
            self.mqtt_connected = True
            self.mqtt_reconnect_delay = 1.0
            self.logger.info("Connected to MQTT broker")
            client.subscribe(self.mqtt_topic, qos=1)
            self.logger.info("Subscribed to topic: %s", self.mqtt_topic)
        else:
            self.mqtt_connected = False
            self.logger.error("Failed to connect to MQTT broker, rc=%s", rc)

    def _on_mqtt_disconnect(self, client, userdata, rc):  # pylint: disable=unused-argument
        self.mqtt_connected = False
        if rc != 0:
            self.logger.warning("Unexpected MQTT disconnection, rc=%s", rc)

    def _on_mqtt_message(self, client, userdata, msg):  # pylint: disable=unused-argument
        try:
            payload = msg.payload.decode('utf-8', errors='replace')
            self.logger.debug("MQTT message on %s: %s", msg.topic, payload[:200])
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError as e:
                self.logger.error("Invalid JSON in MQTT message: %s", e)
                return
            if not isinstance(raw, dict):
                self.logger.warning("Expected JSON object, got %s", type(raw).__name__)
                return

            detection = self._normalize_payload(raw)
            if detection is not None:
                self._accept_detection(detection, 'mqtt')
        except Exception as e:
            self.logger.error("Error handling MQTT message: %s", e, exc_info=True)

    def _trigger_on_demand(self, detection: Dict[str, Any]) -> None:
        try:
            request_payload = {
                'request_id': str(uuid.uuid4()),
                'action': 'start',
                'plugin_id': self.plugin_id,
                'mode': DETECTION_MODE,
                'duration': self.interrupt_duration,
                'pinned': False,
                'timestamp': time.time(),
            }
            self._on_demand_until = time.time() + self.interrupt_duration
            self.cache_manager.set('display_on_demand_request', request_payload)
            self.logger.info("Triggered on-demand display for %s", detection['common_name'])
        except Exception as e:
            self.logger.error("Error triggering on-demand display: %s", e, exc_info=True)

    def _connect_mqtt(self) -> bool:
        try:
            # A broker drop only flips mqtt_connected; the old client keeps its
            # network thread, socket and own reconnect loop. Without this
            # teardown every drop leaks a thread and can double-deliver.
            if self.mqtt_client is not None:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception as e:
                    self.logger.debug("Error stopping previous MQTT client: %s", e)
                self.mqtt_client = None
            try:
                self.mqtt_client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self.mqtt_client_id,
                    clean_session=True,
                )
            except (TypeError, AttributeError):
                self.mqtt_client = mqtt.Client(client_id=self.mqtt_client_id, clean_session=True)

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message = self._on_mqtt_message

            if self.mqtt_username:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)

            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, self.mqtt_keepalive)
            return True
        except Exception as e:
            self.logger.error("Error connecting to MQTT broker: %s", e)
            return False

    def _mqtt_loop(self) -> None:
        while not self.mqtt_stop_event.is_set():
            try:
                if not self.mqtt_connected:
                    if self._connect_mqtt():
                        self.mqtt_client.loop_start()
                    else:
                        wait = min(self.mqtt_reconnect_delay, self.mqtt_max_reconnect_delay)
                        self.logger.info("Retrying MQTT connection in %.1fs", wait)
                        if self.mqtt_stop_event.wait(wait):
                            break
                        self.mqtt_reconnect_delay *= 2
                else:
                    if self.mqtt_stop_event.wait(1.0):
                        break
                    self.mqtt_reconnect_delay = 1.0
            except Exception as e:
                self.logger.error("Error in MQTT loop: %s", e, exc_info=True)
                self.mqtt_connected = False
                if self.mqtt_client:
                    try:
                        self.mqtt_client.loop_stop()
                        self.mqtt_client.disconnect()
                    except Exception as stop_err:
                        self.logger.debug("Error stopping MQTT client: %s", stop_err)
                    self.mqtt_client = None
                wait = min(self.mqtt_reconnect_delay, self.mqtt_max_reconnect_delay)
                if self.mqtt_stop_event.wait(wait):
                    break
                self.mqtt_reconnect_delay *= 2

        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                self.logger.debug("Error stopping MQTT client on exit: %s", e)
            self.mqtt_client = None
        self.logger.info("MQTT loop thread stopped")

    # ------------------------------------------------------------ REST feed

    def _api_get(self, path: str) -> Optional[Any]:
        if not self.api_base_url:
            return None
        url = f"{self.api_base_url}{path}"
        try:
            resp = requests.get(url, timeout=self.api_timeout)
            if resp.status_code != 200:
                self.logger.warning("BirdNET-Go HTTP %s for %s", resp.status_code, path)
                return None
            return resp.json()
        except Exception as e:
            self.logger.warning("Error calling BirdNET-Go %s: %s", path, e)
            return None

    @staticmethod
    def _parse_heard_time(value: Any) -> Optional[float]:
        """Parse the analytics feed's `latest_heard`, a bare clock time for today."""
        parsed = BirdNetGoPlugin._parse_detection_time(value)
        if parsed is not None:
            return parsed
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            clock = datetime.strptime(value.strip(), '%H:%M:%S').time()
        except ValueError:
            return None
        return datetime.combine(datetime.now().date(), clock).timestamp()

    def _poll_latest_detection(self) -> None:
        """Adopt the newest detection worth showing.

        The species cycle is built from the daily analytics feed instead of this
        one: /detections/recent caps at ten rows, and on a busy feed those ten
        are often a single loud species.
        """
        data = self._api_get('/api/v2/detections/recent?numResults=10')
        if isinstance(data, dict):
            data = data.get('data')
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            detection = self._normalize_payload(item)
            if detection and detection['confidence'] >= self.min_confidence:
                self._accept_detection(detection, 'api')
                return

    def _poll_daily_stats(self) -> None:
        """Refresh today's per-species counts and rebuild the species cycle.

        This endpoint is already one row per species, which makes it both the
        stats source and a far better cycle source than the detection stream.
        """
        data = self._api_get('/api/v2/analytics/species/daily')
        if isinstance(data, dict):
            data = data.get('data')
        if not isinstance(data, list):
            return
        rows: List[Dict[str, Any]] = []
        cycle: List[Dict[str, Any]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                count = int(entry.get('count', 0))
            except (TypeError, ValueError):
                count = 0
            common = str(entry.get('common_name') or entry.get('commonName')
                         or entry.get('scientific_name') or '?')
            rows.append({'name': common, 'count': count})

            try:
                confidence = float(entry.get('max_confidence', 0) or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence > 1.5:
                confidence /= 100.0
            if confidence < self.min_confidence:
                continue
            heard_at = self._parse_heard_time(entry.get('latest_heard'))
            cycle.append({
                'common_name': common,
                'scientific_name': str(entry.get('scientific_name') or ''),
                'confidence': confidence,
                'time_str': str(entry.get('latest_heard') or ''),
                'received_at': heard_at if heard_at is not None else time.time(),
                'count': count,
                'key': common,
            })

        rows.sort(key=lambda r: r['count'], reverse=True)
        if self.species_order == 'frequency':
            cycle.sort(key=lambda c: c['count'], reverse=True)
        else:
            cycle.sort(key=lambda c: c['received_at'], reverse=True)

        stats = {
            'species_today': len(rows),
            'detections_today': sum(r['count'] for r in rows),
            'top': rows[:max(1, self.stats_top_n)],
            # Every species, not just the top slice — the detection card looks
            # up its own count here regardless of where it ranks.
            'counts': {r['name']: r['count'] for r in rows},
            'fetched_at': time.time(),
        }
        with self.state_lock:
            self.daily_stats = stats
            self._recent_species = cycle[:self.max_species]
        try:
            self.cache_manager.set(f'{self.plugin_id}_daily_stats', stats, ttl=6 * 3600)
        except Exception as e:
            self.logger.debug("Stats cache set failed: %s", e)
        self.logger.info("Daily stats: %d species, %d detections; cycling %d by %s",
                         stats['species_today'], stats['detections_today'],
                         len(cycle[:self.max_species]), self.species_order)

    # ------------------------------------------------------------- images

    def _matrix_dims(self) -> Tuple[int, int]:
        width = getattr(self.display_manager, 'width', None)
        height = getattr(self.display_manager, 'height', None)
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return width, height
        matrix = getattr(self.display_manager, 'matrix', None)
        if matrix is not None:
            return matrix.width, matrix.height
        image = getattr(self.display_manager, 'image', None)
        if image is not None:
            return image.width, image.height
        return 128, 32

    def _fetch_species_image(self, species: str) -> Optional[Image.Image]:
        if not self.api_base_url or not species:
            return None
        if species in self._species_img_failed:
            return None

        # Disk cache via cache_manager (base64 of PNG bytes)
        cache_key = f'{self.plugin_id}_img_{species}'
        try:
            cached_b64 = self.cache_manager.get(cache_key, max_age=30 * 86400)
            if cached_b64:
                img = Image.open(BytesIO(base64.b64decode(cached_b64)))
                img.load()
                return img
        except Exception as e:
            self.logger.debug("Image cache read failed: %s", e)

        url = f"{self.api_base_url}/api/v2/media/species-image?name={quote(species)}"
        try:
            self.logger.info("Fetching species image: %s", url)
            resp = requests.get(url, timeout=self.api_timeout)
            if resp.status_code != 200:
                self.logger.warning("Species image HTTP %s for %s", resp.status_code, species)
                self._species_img_failed.add(species)
                return None
            img = Image.open(BytesIO(resp.content))
            img.load()
            try:
                buf = BytesIO()
                img.convert('RGB').save(buf, format='PNG')
                self.cache_manager.set(cache_key,
                                       base64.b64encode(buf.getvalue()).decode('ascii'),
                                       ttl=30 * 86400)
            except Exception as e:
                self.logger.debug("Image cache write failed: %s", e)
            return img
        except Exception as e:
            self.logger.warning("Error fetching species image for %s: %s", species, e)
            self._species_img_failed.add(species)
            return None

    def _resize_image(self, img: Image.Image, box_w: int, box_h: int) -> Image.Image:
        scale = min(box_w / img.width, box_h / img.height)
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        frame = Image.new('RGB', (box_w, box_h), self.bg_color)
        x = (box_w - new_w) // 2
        y = (box_h - new_h) // 2
        if resized.mode == 'RGBA':
            frame.paste(resized, (x, y), resized)
        else:
            frame.paste(resized.convert('RGB'), (x, y))
        return frame

    def _cache_source_image(self, species: str, img: Image.Image) -> None:
        self._species_img_cache[species] = img
        self._species_img_cache.move_to_end(species)
        while len(self._species_img_cache) > _MAX_SOURCE_IMAGES:
            self._species_img_cache.popitem(last=False)

    def _panel_image(self, species: str, img: Image.Image,
                     box_w: int, box_h: int) -> Image.Image:
        """Panel-sized frame for a species, resized once instead of per frame.

        Keyed by size as well as species: the core can hand a plugin a smaller
        logical screen, and a frame cached at the previous size would paste wrong.
        """
        key = (species, box_w, box_h)
        cached = self._panel_img_cache.get(key)
        if cached is not None:
            self._panel_img_cache.move_to_end(key)
            return cached
        cached = self._resize_image(img, box_w, box_h)
        self._panel_img_cache[key] = cached
        while len(self._panel_img_cache) > _MAX_PANEL_IMAGES:
            self._panel_img_cache.popitem(last=False)
        return cached

    # ----------------------------------------------------------- rendering

    def _format_age(self, received_at: float) -> str:
        age = max(0, int(time.time() - received_at))
        if age < 60:
            return f"{age}s ago"
        if age < 3600:
            return f"{age // 60}m ago"
        if age < 86400:
            return f"{age // 3600}h ago"
        return f"{age // 86400}d ago"

    def _frame_dt(self) -> float:
        now = time.time()
        dt = min(_MAX_FRAME_DT, max(0.0, now - self._last_frame_time))
        self._last_frame_time = now
        return dt

    @staticmethod
    def _dim(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
        return tuple(max(0, min(255, int(c * factor))) for c in color)

    def _build_scroll_cache(self, text: str, height: int, font,
                            color: Tuple[int, int, int]) -> Image.Image:
        text_w, text_h, y_off = self._measure(text, font)
        cache = Image.new('RGB', (text_w + self.scroll_gap_width, height), self.bg_color)
        draw = ImageDraw.Draw(cache)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        draw.text((0, (height - text_h) // 2 - y_off), text, font=font, fill=color)
        return cache

    def _render_text_line(self, text: str, box_w: int, box_h: int,
                          dt: float, allow_scroll: bool, font=None,
                          align: str = 'center',
                          color: Optional[Tuple[int, int, int]] = None) -> Image.Image:
        font = font or self.font
        color = color or self.text_color
        frame = Image.new('RGB', (box_w, box_h), self.bg_color)
        draw = ImageDraw.Draw(frame)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        text_w, text_h, y_off = self._measure(text, font)

        if text_w <= box_w or not allow_scroll:
            x = 0 if align == 'left' else max(0, (box_w - text_w) // 2)
            draw.text((x, (box_h - text_h) // 2 - y_off), text, font=font, fill=color)
            return frame

        # Scroll. The cache is keyed by everything that changes its pixels, so a
        # size or species change rebuilds it instead of scrolling stale content.
        key = (text, box_h, getattr(font, 'size', 0), color)
        if self._scroll_cache is None or self._scroll_cache_key != key:
            self._scroll_cache = self._build_scroll_cache(text, box_h, font, color)
            self._scroll_cache_key = key
            self._scroll_pos = 0.0

        self._scroll_pos = (self._scroll_pos + dt * self.scroll_speed) % self._scroll_cache.width
        pos = int(self._scroll_pos)
        cache_w = self._scroll_cache.width
        if pos + box_w <= cache_w:
            frame.paste(self._scroll_cache.crop((pos, 0, pos + box_w, box_h)), (0, 0))
        else:
            first_w = cache_w - pos
            frame.paste(self._scroll_cache.crop((pos, 0, cache_w, box_h)), (0, 0))
            frame.paste(self._scroll_cache.crop((0, 0, box_w - first_w, box_h)), (first_w, 0))
        return frame

    def _get_current_detection(self) -> Optional[Dict[str, Any]]:
        with self.state_lock:
            if self.last_detection:
                return dict(self.last_detection)
        try:
            cached = self.cache_manager.get(f'{self.plugin_id}_last_detection', max_age=86400)
            if cached:
                return cached
        except Exception as e:
            self.logger.debug("Detection cache read failed: %s", e)
        return None

    def _get_daily_stats(self) -> Optional[Dict[str, Any]]:
        with self.state_lock:
            if self.daily_stats:
                return dict(self.daily_stats)
        try:
            cached = self.cache_manager.get(f'{self.plugin_id}_daily_stats', max_age=6 * 3600)
            if cached:
                return cached
        except Exception as e:
            self.logger.debug("Stats cache read failed: %s", e)
        return None

    def _today_count(self, common_name: str) -> Optional[int]:
        """How many times this species has been heard today, if stats are loaded."""
        if not common_name:
            return None
        stats = self._get_daily_stats()
        if not stats:
            return None
        return (stats.get('counts') or {}).get(common_name)

    def _cycle_detection(self, force_clear: bool) -> Optional[Dict[str, Any]]:
        """Pick this rotation slot's species, advancing one species per slot.

        force_clear marks a fresh slot; the elapsed-time check is the fallback
        for cores that don't set it, so the cycle can't stall on one bird.
        """
        with self.state_lock:
            species_list = list(self._recent_species)
        if not species_list:
            return None

        now = time.time()
        slot = max(3.0, self.rotation_duration)
        if self._cycle_started == 0.0:
            self._cycle_started = now
        elif force_clear or (now - self._cycle_started) >= slot:
            self._cycle_index += 1
            self._cycle_started = now

        detection = species_list[self._cycle_index % len(species_list)]
        key = detection['scientific_name'] or detection['common_name']
        if key != self._cycle_key:
            # New card — restart the name scroll rather than resuming mid-word.
            self._cycle_key = key
            self._scroll_cache = None
            self._scroll_cache_key = None
            self._scroll_pos = 0.0
        return detection

    def _render_centered(self, text: str, w: int, h: int) -> Image.Image:
        img = Image.new('RGB', (w, h), self.bg_color)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        font = self._font_for(min(self.font_size, max(5, h // 3)))
        text = self._truncate(text, font, w - 2)
        tw, th, y_off = self._measure(text, font)
        draw.text(((w - tw) // 2, (h - th) // 2 - y_off), text, font=font, fill=self.text_color)
        return img

    def _render_detection(self, det: Dict[str, Any], w: int, h: int) -> Image.Image:
        dt = self._frame_dt()
        frame = Image.new('RGB', (w, h), self.bg_color)

        # Image on the left side
        img_box_w = 0
        if self.show_image:
            species = det.get('scientific_name') or det.get('common_name')
            pil_img = self._species_img_cache.get(species)
            if pil_img is not None:
                box = min(h, w // 3)
                img_box_w = box
                frame.paste(self._panel_image(species, pil_img, box, h), (0, 0))

        pad = 2 if img_box_w else 1
        text_x = img_box_w + pad
        text_w = w - text_x - pad
        if text_w < 8:
            text_x, text_w = 0, w
        # Centering reads well only when the text nearly fills the panel; beside
        # a photo on a wide panel it strands the name in the middle.
        align = 'left' if img_box_w else 'center'

        name_line = det.get('common_name', '?')
        sci_line = det.get('scientific_name') or ''
        conf_str = f"{int(det.get('confidence', 0) * 100)}%" if self.show_confidence else ''
        age_str = (self._format_age(det['received_at'])
                   if self.show_time and det.get('received_at') else '')
        count_str = ''
        if self.show_today_count:
            # Cycle cards carry their own count; interrupt cards look theirs up.
            count = det.get('count') or self._today_count(det.get('common_name', ''))
            if count:
                count_str = f"x{count}"

        # Richest phrasing first; _first_fitting drops detail as width runs out.
        meta_options: List[str] = []
        for combo in ((conf_str, age_str, count_str), (conf_str, count_str),
                      (conf_str, age_str), (conf_str,), (age_str,)):
            candidate = "  ".join(part for part in combo if part)
            if candidate and candidate not in meta_options:
                meta_options.append(candidate)
        meta_line = meta_options[0] if meta_options else ''

        # Tall panels earn a third line for the scientific name. Short ones drop
        # to name-only rather than squeezing in two unreadable rows.
        if h >= 48 and sci_line and meta_line:
            rows = [('name', 0.42, 22), ('sci', 0.28, 13), ('meta', 0.30, 16)]
        elif h >= 24 and meta_line:
            rows = [('name', 0.55, 18), ('meta', 0.45, 14)]
        else:
            rows = [('name', 1.0, 18)]

        heights = [max(6, int(h * frac)) for _, frac, _ in rows]
        heights[-1] = max(6, h - sum(heights[:-1]))

        y = 0
        for (kind, _, size_cap), row_h in zip(rows, heights):
            row_h = min(row_h, h - y)
            if row_h <= 0:
                break
            font = self._font_for(max(5, min(int(row_h * 0.78), size_cap)))
            if kind == 'name':
                text, color, scroll = name_line, self.text_color, True
            elif kind == 'sci':
                text = self._truncate(sci_line, font, text_w)
                color, scroll = self._dim(self.text_color, 0.55), False
            else:
                text = self._first_fitting(meta_options, font, text_w)
                color, scroll = self.accent_color, False
            frame.paste(
                self._render_text_line(text, text_w, row_h, dt, allow_scroll=scroll,
                                       font=font, align=align, color=color),
                (text_x, y))
            y += row_h

        return frame

    def _stats_layout(self, h: int) -> Tuple[int, int, Any]:
        """Pick a row count, row height and font that fill the panel height."""
        if h >= 56:
            rows = 5
        elif h >= 40:
            rows = 4
        elif h >= 26:
            rows = 3
        else:
            rows = 2
        line_h = max(6, h // rows)
        font = self._font_for(max(5, min(int(line_h * 0.75), 16)))
        return rows, line_h, font

    def _render_stats(self, stats: Dict[str, Any], w: int, h: int) -> Image.Image:
        frame = Image.new('RGB', (w, h), self.bg_color)
        draw = ImageDraw.Draw(frame)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).
        rows, line_h, font = self._stats_layout(h)
        pad = 1 if w < 96 else 2

        # Header: species/detection totals, abbreviated when the panel is narrow.
        species = stats.get('species_today', 0)
        detections = stats.get('detections_today', 0)
        header = f"TODAY  {species} SPECIES  {detections} CALLS"
        if self._measure(header, font)[0] > w - pad * 2:
            header = f"{species} SP  {detections} CALLS"
        if self._measure(header, font)[0] > w - pad * 2:
            header = f"{species}sp {detections}"
        header = self._truncate(header, font, w - pad * 2)
        hw, hh, h_off = self._measure(header, font)
        draw.text((max(pad, (w - hw) // 2), (line_h - hh) // 2 - h_off),
                  header, font=font, fill=self.accent_color)

        # Body: most-heard species, count right-aligned.
        top = stats.get('top') or []
        for idx, entry in enumerate(top[:rows - 1]):
            y = line_h * (idx + 1)
            count_str = str(entry.get('count', 0))
            cw, ch, c_off = self._measure(count_str, font)
            name = self._truncate(str(entry.get('name', '?')), font,
                                  w - cw - pad * 3)
            _, nh, n_off = self._measure(name, font)
            draw.text((pad, y + (line_h - nh) // 2 - n_off), name,
                      font=font, fill=self.text_color)
            draw.text((w - pad - cw, y + (line_h - ch) // 2 - c_off), count_str,
                      font=font, fill=self.accent_color)

        return frame

    # ------------------------------------------------------- Plugin API

    def update(self) -> None:
        now = time.time()

        # Poll the REST feed. MQTT, when enabled, pushes detections faster, but
        # polling still runs so a broker outage can't freeze the display.
        if self.api_base_url and now - self._last_poll >= self.poll_interval:
            self._last_poll = now
            try:
                self._poll_latest_detection()
            except Exception as e:
                self.logger.error("Error polling detections: %s", e, exc_info=True)
            # Also drives the species cycle, so it runs even with stats off.
            if self.stats_enabled or self.unique_species:
                try:
                    self._poll_daily_stats()
                except Exception as e:
                    self.logger.error("Error polling stats: %s", e, exc_info=True)

        if not self.show_image:
            return

        # Warm up images off the MQTT callback thread. Every species in the
        # cycle needs one, not just the newest, or most cards render text-only.
        wanted: List[str] = []
        with self.state_lock:
            if self._pending_image_fetch:
                wanted.append(self._pending_image_fetch)
                self._pending_image_fetch = None
            wanted.extend(d['scientific_name'] or d['common_name']
                          for d in self._recent_species)

        # Cap both the count and the wall-clock. The schema allows a 30s
        # timeout, so three sequential fetches on top of two polls could
        # otherwise block update() for minutes against a host that accepts
        # connections but never answers. Whatever is missed resumes next tick.
        fetched = 0
        deadline = time.time() + max(2.0, self.api_timeout * 1.5)
        for species in wanted:
            if (not species or species in self._species_img_cache
                    or species in self._species_img_failed):
                continue
            if time.time() >= deadline:
                self.logger.debug("Image warm-up budget spent; resuming next update")
                break
            img = self._fetch_species_image(species)
            if img is not None:
                self._cache_source_image(species, img)
            fetched += 1
            if fetched >= 3:
                break

    def display(self, display_mode: Optional[str] = None, force_clear: bool = False) -> bool:
        w, h = self._matrix_dims()
        mode = (display_mode or DETECTION_MODE).strip().lower()

        if mode == STATS_MODE:
            self._last_rendered_mode = STATS_MODE
            if not self.stats_enabled:
                return False
            stats = self._get_daily_stats()
            frame = (self._render_stats(stats, w, h) if stats
                     else self._render_centered("No bird stats", w, h))
        else:
            self._last_rendered_mode = DETECTION_MODE

            # In pure interrupt mode the rotation slot stays empty.
            interrupting = time.time() <= self._on_demand_until
            if self.mode == 'interrupt' and not interrupting:
                return False

            # An interrupt is about the bird that just called, so it shows the
            # newest detection rather than wherever the cycle happens to be.
            det = None
            if self.unique_species and not interrupting:
                det = self._cycle_detection(force_clear)
            if det is None:
                det = self._get_current_detection()

            if det is None or (self.stale_after_s > 0
                               and time.time() - det.get('received_at', 0) > self.stale_after_s
                               and self.mode != 'interrupt'):
                frame = self._render_centered("No recent birds", w, h)
            else:
                frame = self._render_detection(det, w, h)

        try:
            self.display_manager.image = frame
            self.display_manager.update_display()
            return True
        except Exception as e:
            self.logger.error("Error updating display: %s", e, exc_info=True)
            return False

    def get_display_duration(self, display_mode: Optional[str] = None) -> float:
        mode = (display_mode or self._last_rendered_mode or DETECTION_MODE).strip().lower()
        if mode == STATS_MODE:
            return self.stats_duration
        if time.time() <= self._on_demand_until:
            return self.interrupt_duration
        return self.rotation_duration

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        # Either data source is enough; the REST API alone is the common case.
        if not self.api_base_url and not (self.mqtt_enabled and self.mqtt_host):
            self.logger.error(
                "Configure birdnet_api.base_url, or enable mqtt with a host — "
                "the plugin has no way to reach BirdNET-Go otherwise")
            return False
        if self.mqtt_enabled and not self.mqtt_host:
            self.logger.error("mqtt.enabled is set but mqtt.host is empty")
            return False
        if self.mode not in ('rotation', 'interrupt', 'both'):
            self.logger.error("Invalid display.mode: %s", self.mode)
            return False
        if self.species_order not in ('recent', 'frequency'):
            self.logger.error("Invalid display.species_order: %s", self.species_order)
            return False
        if self.poll_interval < 5:
            self.logger.error("birdnet_api.poll_interval must be at least 5 seconds")
            return False
        for name, val in (("text_color", self.text_color),
                          ("background_color", self.bg_color),
                          ("accent_color", self.accent_color)):
            if not isinstance(val, tuple) or len(val) != 3 or not all(0 <= c <= 255 for c in val):
                self.logger.error("Invalid %s", name)
                return False
        return True

    def on_enable(self) -> None:
        super().on_enable()
        if not self.mqtt_enabled:
            self.logger.info("MQTT disabled; using REST polling every %.0fs", self.poll_interval)
            return
        if self.mqtt_thread is None or not self.mqtt_thread.is_alive():
            self.mqtt_stop_event.clear()
            self.mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
            self.mqtt_thread.start()
            self.logger.info("MQTT client thread started")

    def on_disable(self) -> None:
        super().on_disable()
        if self.mqtt_thread and self.mqtt_thread.is_alive():
            self.mqtt_stop_event.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception as e:
                    self.logger.debug("Error stopping MQTT client on disable: %s", e)
            self.mqtt_thread.join(timeout=5.0)
            self.logger.info("MQTT client thread stopped")

    def cleanup(self) -> None:
        self.on_disable()
        self._species_img_cache.clear()
        self._panel_img_cache.clear()
        self._species_img_failed.clear()
        self._scroll_cache = None

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        det = self._get_current_detection()
        stats = self._get_daily_stats()
        info.update({
            'api_base_url': self.api_base_url,
            'poll_interval': self.poll_interval,
            'mqtt_enabled': self.mqtt_enabled,
            'mqtt_connected': self.mqtt_connected,
            'mqtt_host': self.mqtt_host,
            'mqtt_port': self.mqtt_port,
            'mqtt_topic': self.mqtt_topic,
            'mode': self.mode,
            'last_species': det.get('common_name') if det else None,
            'last_confidence': det.get('confidence') if det else None,
            'last_received_at': det.get('received_at') if det else None,
            'species_today': stats.get('species_today') if stats else None,
            'detections_today': stats.get('detections_today') if stats else None,
            'unique_species': self.unique_species,
            'species_order': self.species_order,
            'species_cycle': [d['common_name'] for d in self._recent_species],
        })
        return info
