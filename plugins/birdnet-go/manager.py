"""
BirdNET-Go Plugin for LEDMatrix

Subscribes to a BirdNET-Go MQTT feed and displays the most recently identified
bird — common name, confidence, time since detection, and a species image
fetched from BirdNET-Go's media API.

Supports three display modes:
  - rotation: always shows the last-seen bird during the plugin's rotation slot
  - interrupt: pops up a new detection over the normal rotation
  - both: rotation slot plus interrupt on new detections

API Version: 1.0.0
"""

import base64
import json
import logging
import os
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


# Case-insensitive fallback variants tried when a mapped field is missing.
_FIELD_VARIANTS = {
    'common_name': ['CommonName', 'commonName', 'common_name', 'Common_Name'],
    'scientific_name': ['ScientificName', 'scientificName', 'scientific_name', 'Scientific_Name'],
    'confidence': ['Confidence', 'confidence'],
    'time': ['Time', 'time', 'Timestamp', 'timestamp', 'BeginTime', 'beginTime'],
}


class BirdNetGoPlugin(BasePlugin):
    """Display BirdNET-Go bird detections on the LED matrix."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        if mqtt is None:
            raise ImportError("paho-mqtt is required. Install with: pip install paho-mqtt")

        mqtt_config = config.get('mqtt', {})
        self.mqtt_host = mqtt_config.get('host', 'localhost')
        self.mqtt_port = int(mqtt_config.get('port', 1883))
        self.mqtt_username = mqtt_config.get('username', '')
        self.mqtt_password = mqtt_config.get('password', '')
        self.mqtt_client_id = mqtt_config.get('client_id', 'ledmatrix-birdnet-go')
        self.mqtt_keepalive = int(mqtt_config.get('keepalive', 60))
        self.mqtt_topic = mqtt_config.get('topic', 'birdnet/detections')

        api_config = config.get('birdnet_api', {})
        self.api_base_url = api_config.get('base_url', '').rstrip('/')
        self.api_timeout = float(api_config.get('request_timeout', 5.0))

        display_config = config.get('display', {})
        self.mode = display_config.get('mode', 'both')
        self.interrupt_duration = float(display_config.get('interrupt_duration', 10))
        self.rotation_duration = float(display_config.get('rotation_duration', 15))
        self.min_confidence = float(display_config.get('min_confidence', 0.5))
        self.stale_after_s = int(display_config.get('stale_after_minutes', 120)) * 60
        self.show_image = bool(display_config.get('show_image', True))
        self.show_confidence = bool(display_config.get('show_confidence', True))
        self.show_time = bool(display_config.get('show_time', True))

        text_config = config.get('text', {})
        self.font_path = text_config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        self.font_size = int(text_config.get('font_size', 8))
        self.text_color = tuple(int(c) for c in text_config.get('text_color', [255, 255, 255]))
        self.bg_color = tuple(int(c) for c in text_config.get('background_color', [0, 0, 0]))
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

        # Detection state
        self.state_lock = threading.Lock()
        self.last_detection: Optional[Dict[str, Any]] = None
        self._species_img_cache: Dict[str, Image.Image] = {}  # sci_name -> resized PIL
        self._species_img_failed: set = set()  # sci_names we already failed to fetch
        self._pending_image_fetch: Optional[str] = None
        self._scroll_pos = 0.0
        self._scroll_cache: Optional[Image.Image] = None
        self._scroll_cache_text: Optional[str] = None
        self._last_frame_time = time.time()
        self._on_demand_until = 0.0

        self.font = self._load_font()

        self.logger.info("BirdNET-Go plugin initialized (mode=%s, broker=%s:%s, topic=%s)",
                         self.mode, self.mqtt_host, self.mqtt_port, self.mqtt_topic)

    # ------------------------------------------------------------------ fonts

    def _load_font(self):
        font_path = self.font_path
        if not os.path.isabs(font_path):
            resolved = None
            if os.path.exists(font_path):
                resolved = font_path
            else:
                cwd_path = os.path.join(os.getcwd(), font_path)
                if os.path.exists(cwd_path):
                    resolved = cwd_path
                else:
                    project_root = Path(__file__).parent.parent.parent
                    project_path = project_root / font_path
                    if project_path.exists():
                        resolved = str(project_path)
            if resolved:
                font_path = resolved
            else:
                self.logger.warning("Font not found: %s, using default", self.font_path)
                return ImageFont.load_default()

        try:
            if font_path.lower().endswith('.ttf'):
                return ImageFont.truetype(font_path, self.font_size)
            return ImageFont.load_default()
        except Exception as e:
            self.logger.error("Failed to load font %s: %s", font_path, e)
            return ImageFont.load_default()

    # ----------------------------------------------------------------- MQTT

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
            self.logger.warning("MQTT payload missing common/scientific name: %s",
                                list(candidate.keys())[:10])
            return None

        try:
            conf_f = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            conf_f = 0.0
        # Some feeds publish confidence as percent (0-100) rather than 0-1
        if conf_f > 1.5:
            conf_f = conf_f / 100.0

        return {
            'common_name': str(common) if common else str(sci),
            'scientific_name': str(sci) if sci else '',
            'confidence': conf_f,
            'time_str': str(ts) if ts else '',
            'received_at': time.time(),
        }

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
            if detection is None:
                return

            if detection['confidence'] < self.min_confidence:
                self.logger.info("Dropping low-confidence detection: %s @ %.2f",
                                 detection['common_name'], detection['confidence'])
                return

            with self.state_lock:
                self.last_detection = detection
                self._pending_image_fetch = detection['scientific_name'] or detection['common_name']
                self._scroll_cache = None
                self._scroll_cache_text = None
                self._scroll_pos = 0.0

            try:
                self.cache_manager.set(f'{self.plugin_id}_last_detection', detection, max_age=86400)
            except Exception as e:
                self.logger.debug("Cache set failed: %s", e)

            self.logger.info("Detection: %s (%.0f%%)",
                             detection['common_name'], detection['confidence'] * 100)

            if self.mode in ('interrupt', 'both'):
                self._trigger_on_demand(detection)

        except Exception as e:
            self.logger.error("Error handling MQTT message: %s", e, exc_info=True)

    def _trigger_on_demand(self, detection: Dict[str, Any]) -> None:
        try:
            request_payload = {
                'request_id': str(uuid.uuid4()),
                'action': 'start',
                'plugin_id': self.plugin_id,
                'mode': 'birdnet_go',
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
                    except Exception:
                        pass
                    self.mqtt_client = None
                wait = min(self.mqtt_reconnect_delay, self.mqtt_max_reconnect_delay)
                if self.mqtt_stop_event.wait(wait):
                    break
                self.mqtt_reconnect_delay *= 2

        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None
        self.logger.info("MQTT loop thread stopped")

    # ------------------------------------------------------------- images

    def _matrix_dims(self) -> Tuple[int, int]:
        matrix = getattr(self.display_manager, 'matrix', None)
        if matrix is not None:
            return matrix.width, matrix.height
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
                                       max_age=30 * 86400)
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

    def _text_size(self, draw: ImageDraw.ImageDraw, text: str) -> Tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=self.font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _build_scroll_cache(self, text: str, height: int) -> Image.Image:
        tmp = Image.new('RGB', (1, 1))
        tmp_draw = ImageDraw.Draw(tmp)
        bbox = tmp_draw.textbbox((0, 0), text, font=self.font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        cache = Image.new('RGB', (text_w + self.scroll_gap_width, height), self.bg_color)
        draw = ImageDraw.Draw(cache)
        y = (height - text_h) // 2 - bbox[1]
        draw.text((0, y), text, font=self.font, fill=self.text_color)
        return cache

    def _render_text_line(self, text: str, box_w: int, box_h: int,
                          dt: float, allow_scroll: bool) -> Image.Image:
        frame = Image.new('RGB', (box_w, box_h), self.bg_color)
        draw = ImageDraw.Draw(frame)
        text_w, text_h = self._text_size(draw, text)

        if text_w <= box_w or not allow_scroll:
            x = max(0, (box_w - text_w) // 2)
            bbox = draw.textbbox((0, 0), text, font=self.font)
            y = (box_h - text_h) // 2 - bbox[1]
            draw.text((x, y), text, font=self.font, fill=self.text_color)
            return frame

        # Scroll
        if self._scroll_cache is None or self._scroll_cache_text != text \
                or self._scroll_cache.height != box_h:
            self._scroll_cache = self._build_scroll_cache(text, box_h)
            self._scroll_cache_text = text
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
        except Exception:
            pass
        return None

    def _render_no_detection(self, w: int, h: int) -> Image.Image:
        img = Image.new('RGB', (w, h), self.bg_color)
        draw = ImageDraw.Draw(img)
        text = "No recent birds"
        bbox = draw.textbbox((0, 0), text, font=self.font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((w - tw) // 2, (h - th) // 2 - bbox[1]), text,
                  font=self.font, fill=self.text_color)
        return img

    def _render_detection(self, det: Dict[str, Any], w: int, h: int) -> Image.Image:
        now = time.time()
        dt = max(0.0, now - self._last_frame_time)
        self._last_frame_time = now

        frame = Image.new('RGB', (w, h), self.bg_color)

        # Image on the left side
        img_box_w = 0
        if self.show_image:
            species = det.get('scientific_name') or det.get('common_name')
            pil_img = self._species_img_cache.get(species)
            if pil_img is not None:
                box = min(h, w // 3)
                img_box_w = box
                frame.paste(self._resize_image(pil_img, box, h), (0, 0))

        text_x = img_box_w + (2 if img_box_w else 0)
        text_w = w - text_x
        if text_w < 8:
            text_w = w
            text_x = 0

        # Compose lines
        name_line = det.get('common_name', '?')
        meta_parts = []
        if self.show_confidence:
            meta_parts.append(f"{int(det.get('confidence', 0) * 100)}%")
        if self.show_time and det.get('received_at'):
            meta_parts.append(self._format_age(det['received_at']))
        meta_line = "  ".join(meta_parts)

        if h >= 24 and meta_line:
            line_h = h // 2
            name_img = self._render_text_line(name_line, text_w, line_h, dt, allow_scroll=True)
            frame.paste(name_img, (text_x, 0))
            meta_img = self._render_text_line(meta_line, text_w, h - line_h, dt, allow_scroll=False)
            frame.paste(meta_img, (text_x, line_h))
        else:
            name_img = self._render_text_line(name_line, text_w, h, dt, allow_scroll=True)
            frame.paste(name_img, (text_x, 0))

        return frame

    # ------------------------------------------------------- Plugin API

    def update(self) -> None:
        # Warm up species image off the MQTT callback thread.
        species = None
        with self.state_lock:
            if self._pending_image_fetch:
                species = self._pending_image_fetch
                self._pending_image_fetch = None

        if not species or not self.show_image:
            return
        if species in self._species_img_cache or species in self._species_img_failed:
            return

        img = self._fetch_species_image(species)
        if img is not None:
            self._species_img_cache[species] = img

    def display(self, force_clear: bool = False) -> bool:
        w, h = self._matrix_dims()
        det = self._get_current_detection()

        # Honor mode semantics for rotation slot:
        if self.mode == 'interrupt' and time.time() > self._on_demand_until:
            # Nothing to show during rotation in pure interrupt mode
            return False

        if det is None or (self.stale_after_s > 0
                           and time.time() - det.get('received_at', 0) > self.stale_after_s
                           and self.mode != 'interrupt'):
            frame = self._render_no_detection(w, h)
        else:
            frame = self._render_detection(det, w, h)

        try:
            self.display_manager.image = frame
            self.display_manager.update_display()
            return True
        except Exception as e:
            self.logger.error("Error updating display: %s", e, exc_info=True)
            return False

    def get_display_duration(self) -> float:
        if time.time() <= self._on_demand_until:
            return self.interrupt_duration
        return self.rotation_duration

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        if 'mqtt' not in self.config:
            self.logger.error("Missing 'mqtt' configuration")
            return False
        if not self.config['mqtt'].get('host'):
            self.logger.error("Missing 'mqtt.host'")
            return False
        if 'port' not in self.config['mqtt']:
            self.logger.error("Missing 'mqtt.port'")
            return False
        if self.mode not in ('rotation', 'interrupt', 'both'):
            self.logger.error("Invalid display.mode: %s", self.mode)
            return False
        for name, val in (("text_color", self.text_color), ("background_color", self.bg_color)):
            if not isinstance(val, tuple) or len(val) != 3 or not all(0 <= c <= 255 for c in val):
                self.logger.error("Invalid %s", name)
                return False
        return True

    def on_enable(self) -> None:
        super().on_enable()
        if mqtt is None:
            self.logger.error("paho-mqtt not available")
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
                except Exception:
                    pass
            self.mqtt_thread.join(timeout=5.0)
            self.logger.info("MQTT client thread stopped")

    def cleanup(self) -> None:
        self.on_disable()
        self._species_img_cache.clear()
        self._species_img_failed.clear()
        self._scroll_cache = None

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        det = self._get_current_detection()
        info.update({
            'mqtt_connected': self.mqtt_connected,
            'mqtt_host': self.mqtt_host,
            'mqtt_port': self.mqtt_port,
            'mqtt_topic': self.mqtt_topic,
            'mode': self.mode,
            'last_species': det.get('common_name') if det else None,
            'last_confidence': det.get('confidence') if det else None,
            'last_received_at': det.get('received_at') if det else None,
        })
        return info
