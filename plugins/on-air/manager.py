"""
On Air Light Plugin for LEDMatrix

Displays a customisable ON AIR sign, activated remotely via MQTT or
Home Assistant. The display latches on until explicitly turned off.

Visual: solid background colour + centred text. Font, size, text colour,
and background colour are all configurable. No animation.

MQTT topics (derived from command_topic base):
  command_topic      — subscribe: ON/OFF or JSON {"state":"on","label":"..."}
  state_topic        — publish:   ON or OFF  (HA switch state)
  <base>/label       — publish:   current label text  (HA sensor)
  <base>/available   — publish:   online / offline  (LWT + availability)

HA MQTT Auto-Discovery (enabled by default):
  Publishes device + entity configs to homeassistant/<component>/... on
  connect so HA creates the device automatically — no configuration.yaml
  entry needed.
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore

from src.plugin_system.base_plugin import BasePlugin

_PLUGIN_VERSION = "1.2.0"


def _rgb(value, default) -> Tuple[int, int, int]:
    try:
        return tuple(max(0, min(255, int(c))) for c in value)
    except (TypeError, ValueError):
        return default


class OnAirPlugin(BasePlugin):
    """ON AIR sign driven by MQTT with HA auto-discovery."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        if mqtt is None:
            raise ImportError("paho-mqtt is required: pip install paho-mqtt")

        # MQTT broker
        self.mqtt_host      = config.get('mqtt_host', 'localhost')
        self.mqtt_port      = int(config.get('mqtt_port', 1883))
        self.mqtt_username  = config.get('mqtt_username', '')
        self.mqtt_password  = config.get('mqtt_password', '')
        self.mqtt_client_id = f'ledmatrix-on-air-{plugin_id}-{uuid.uuid4().hex[:8]}'
        self.command_topic  = config.get('command_topic', 'ledmatrix/on-air/set')
        self.state_topic    = config.get('state_topic',   'ledmatrix/on-air/state')

        # HA auto-discovery
        self.ha_discovery     = bool(config.get('ha_discovery', True))
        self.discovery_prefix = config.get('discovery_prefix', 'homeassistant')
        self.device_name      = config.get('device_name', 'LED Matrix — On Air')
        self._derive_topics()

        # Display
        self.default_label      = config.get('default_label', 'ON AIR')
        self.default_text_color = _rgb(config.get('text_color',       [255, 255, 255]), (255, 255, 255))
        self.default_bg_color   = _rgb(config.get('background_color', [200,  10,  10]), (200, 10, 10))
        self.font_path          = config.get('font_path', '')
        self.font_size          = int(config.get('font_size', 0))  # 0 = auto
        self._configured_font   = self._load_configured_font()
        self._auto_font_cache: Dict[int, Any] = {}   # dh → font

        # Runtime state
        self.state_lock        = threading.Lock()
        self.on_air            = False
        self.label             = self.default_label
        self.active_text_color = self.default_text_color
        self.active_bg_color   = self.default_bg_color

        # MQTT internals
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_thread: Optional[threading.Thread] = None
        self.mqtt_connected  = False
        self.mqtt_connecting = False
        self.mqtt_reconnect_delay     = 1.0
        self.mqtt_max_reconnect_delay = 60.0
        self.mqtt_stop_event = threading.Event()

        self.logger.info("On Air plugin ready — command: %s", self.command_topic)

    # ── Font helpers ────────────────────────────────────────────────────────────

    def _load_configured_font(self) -> Optional[ImageFont.FreeTypeFont]:
        """Load font from font_path at font_size; returns None to use built-ins."""
        path = (self.font_path or '').strip()
        size = self.font_size or 8
        if not path:
            return None
        # Resolve path: absolute → cwd-relative → project-root-relative
        candidates = [path]
        if not os.path.isabs(path):
            candidates.append(os.path.join(os.getcwd(), path))
            plugin_dir   = Path(__file__).parent
            project_root = plugin_dir.parent.parent
            candidates.append(str(project_root / path))
        for candidate in candidates:
            if os.path.exists(candidate):
                try:
                    font = ImageFont.truetype(candidate, size)
                    self.logger.info("Loaded font: %s @ %dpx", candidate, size)
                    return font
                except Exception as e:
                    self.logger.warning("Could not load font %s: %s", candidate, e)
        self.logger.warning("Font not found: %s — using built-in", path)
        return None

    def _find_system_ttf(self) -> Optional[str]:
        """Search the LEDMatrix assets folder for a usable TTF font file."""
        plugin_dir   = Path(__file__).parent
        project_root = plugin_dir.parent.parent
        preferred = [
            'assets/fonts/PressStart2P-Regular.ttf',
            'assets/fonts/4x6-font.ttf',
        ]
        for rel in preferred:
            p = project_root / rel
            if p.exists():
                return str(p)
        # Fall back to any .ttf found in assets/fonts/
        fonts_dir = project_root / 'assets' / 'fonts'
        if fonts_dir.is_dir():
            for p in sorted(fonts_dir.glob('*.ttf')):
                return str(p)
        return None

    def _auto_font(self, dh: int):
        """Load (and cache) a TTF at 80% of display height, or fall back to built-in."""
        if dh in self._auto_font_cache:
            return self._auto_font_cache[dh]
        size = max(6, int(dh * 0.80))
        font = None
        ttf  = self._find_system_ttf()
        if ttf:
            try:
                font = ImageFont.truetype(ttf, size)
            except Exception as e:
                self.logger.debug("Auto-font load failed: %s", e)
        if font is None:
            font = (self.display_manager.small_font if dh > 32
                    else self.display_manager.extra_small_font)
        self._auto_font_cache[dh] = font
        return font

    def _active_font(self, dw: int, dh: int):
        """Return the font to use for rendering."""
        if self._configured_font is not None:
            return self._configured_font
        return self._auto_font(dh)

    # ── BasePlugin interface ────────────────────────────────────────────────────

    def update(self) -> None:
        pass  # event-driven only

    def display(self, force_clear: bool = False) -> bool:
        with self.state_lock:
            active     = self.on_air
            label      = self.label
            text_color = self.active_text_color
            bg_color   = self.active_bg_color

        dw = self.display_manager.matrix.width
        dh = self.display_manager.matrix.height

        # When off, render a plain black frame rather than returning False.
        # Returning False while still in on-demand mode causes the display
        # controller to fall to its "Initializing" state before the stop
        # request is processed. The 1s get_display_duration() cycles past
        # this black frame nearly instantly in normal rotation.
        fill = bg_color if active else (0, 0, 0)
        canvas = Image.new('RGB', (dw, dh), fill)
        draw   = ImageDraw.Draw(canvas)

        if active:
            self._draw_centered_text(draw, dw, dh, label, text_color)

        self.display_manager.image = canvas
        self.display_manager.draw  = draw
        self.display_manager.update_display()
        return True

    def _draw_centered_text(self, draw: ImageDraw.ImageDraw,
                            dw: int, dh: int,
                            text: str, color: Tuple[int, int, int]) -> None:
        """Draw text centred on the display, scaling down to fit width if needed."""
        font = self._active_font(dw, dh)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw   = bbox[2] - bbox[0]
            th   = bbox[3] - bbox[1]

            # Scale down if text is wider than 95% of display width
            if tw > dw * 0.95:
                font_path = getattr(font, 'path', None)
                font_size = getattr(font, 'size', None)
                if font_path and font_size:
                    new_size = max(6, int(font_size * (dw * 0.95) / tw))
                    try:
                        font = ImageFont.truetype(font_path, new_size)
                        bbox = draw.textbbox((0, 0), text, font=font)
                        tw   = bbox[2] - bbox[0]
                        th   = bbox[3] - bbox[1]
                    except Exception as e:
                        self.logger.debug("Font scale-down failed (%dpx): %s", new_size, e)

            x = max(0, (dw - tw) // 2)
            y = max(0, (dh - th) // 2)
            draw.text((x, y), text, fill=color, font=font)
        except Exception as e:
            self.logger.debug("draw text fallback: %s", e)
            self.display_manager.draw_text(
                text, x=dw // 2, y=max(0, dh // 2 - 4),
                color=color,
                font=self.display_manager.small_font,
                centered=True)

    def get_display_duration(self) -> float:
        return float(self.config.get('display_duration', 5))

    def on_enable(self) -> None:
        super().on_enable()
        if mqtt is None:
            self.logger.error("paho-mqtt not installed")
            return
        if self.mqtt_thread is None or not self.mqtt_thread.is_alive():
            self.mqtt_stop_event.clear()
            self.mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
            self.mqtt_thread.start()
            self.logger.info("MQTT thread started")

    def on_disable(self) -> None:
        super().on_disable()
        self._graceful_shutdown()

    def cleanup(self) -> None:
        self._graceful_shutdown()
        self.logger.info("On Air plugin cleaned up")

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        # Compare against current self.* values BEFORE overwriting them so that
        # credential, topic, and discovery changes also trigger a reconnect.
        broker_changed = (
            new_config.get('mqtt_host', 'localhost')        != self.mqtt_host        or
            int(new_config.get('mqtt_port', 1883))          != self.mqtt_port        or
            new_config.get('mqtt_username', '')             != self.mqtt_username     or
            new_config.get('mqtt_password', '')             != self.mqtt_password     or
            new_config.get('command_topic', 'ledmatrix/on-air/set')   != self.command_topic   or
            new_config.get('state_topic',   'ledmatrix/on-air/state') != self.state_topic     or
            new_config.get('discovery_prefix', 'homeassistant')       != self.discovery_prefix or
            bool(new_config.get('ha_discovery', True))     != self.ha_discovery
        )
        self.mqtt_host        = new_config.get('mqtt_host', 'localhost')
        self.mqtt_port        = int(new_config.get('mqtt_port', 1883))
        self.mqtt_username    = new_config.get('mqtt_username', '')
        self.mqtt_password    = new_config.get('mqtt_password', '')
        self.command_topic    = new_config.get('command_topic', 'ledmatrix/on-air/set')
        self.state_topic      = new_config.get('state_topic',   'ledmatrix/on-air/state')
        self.ha_discovery     = bool(new_config.get('ha_discovery', True))
        self.discovery_prefix = new_config.get('discovery_prefix', 'homeassistant')
        self.device_name      = new_config.get('device_name', 'LED Matrix — On Air')
        self._derive_topics()
        self.default_label      = new_config.get('default_label', 'ON AIR')
        self.default_text_color = _rgb(new_config.get('text_color',       [255, 255, 255]), (255, 255, 255))
        self.default_bg_color   = _rgb(new_config.get('background_color', [200,  10,  10]), (200, 10, 10))
        self.font_path          = new_config.get('font_path', '')
        self.font_size          = int(new_config.get('font_size', 0))
        self._configured_font   = self._load_configured_font()
        self._auto_font_cache   = {}
        if broker_changed:
            self._graceful_shutdown()
            self.on_enable()

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        with self.state_lock:
            info.update({
                'on_air':         self.on_air,
                'label':          self.label,
                'mqtt_connected': self.mqtt_connected,
                'mqtt_host':      self.mqtt_host,
                'command_topic':  self.command_topic,
                'ha_discovery':   self.ha_discovery,
            })
        return info

    # ── Topic helpers ───────────────────────────────────────────────────────────

    def _derive_topics(self) -> None:
        base = self.command_topic
        if base.endswith('/set'):
            base = base[:-4]
        self.topic_base         = base
        self.availability_topic = f"{base}/available"
        self.label_topic        = f"{base}/label"

    def _discovery_uid(self) -> str:
        return f"ledmatrix_on_air_{self.plugin_id}"

    def _discovery_device(self) -> Dict[str, Any]:
        return {
            "identifiers":  [self._discovery_uid()],
            "name":         self.device_name,
            "model":        "On Air Light",
            "manufacturer": "LEDMatrix",
            "sw_version":   _PLUGIN_VERSION,
        }

    # ── HA MQTT Auto-Discovery ──────────────────────────────────────────────────

    def _publish_discovery(self) -> None:
        if not self.ha_discovery or not self.mqtt_client:
            return
        prefix = self.discovery_prefix
        uid    = self._discovery_uid()
        device = self._discovery_device()
        avail  = [{"topic": self.availability_topic,
                   "payload_available": "online",
                   "payload_not_available": "offline"}]

        self.mqtt_client.publish(
            f"{prefix}/switch/{uid}/config",
            json.dumps({
                "name": "On Air", "unique_id": f"{uid}_switch",
                "command_topic": self.command_topic, "state_topic": self.state_topic,
                "payload_on": "ON", "payload_off": "OFF",
                "state_on": "ON", "state_off": "OFF",
                "icon": "mdi:broadcast",
                "availability": avail, "device": device,
            }), retain=True)

        self.mqtt_client.publish(
            f"{prefix}/sensor/{uid}_label/config",
            json.dumps({
                "name": "Current Label", "unique_id": f"{uid}_label",
                "state_topic": self.label_topic, "icon": "mdi:label-outline",
                "availability": avail, "device": device,
            }), retain=True)

        self.mqtt_client.publish(
            f"{prefix}/binary_sensor/{uid}_connected/config",
            json.dumps({
                "name": "MQTT Connected", "unique_id": f"{uid}_connected",
                "state_topic": self.availability_topic,
                "payload_on": "online", "payload_off": "offline",
                "device_class": "connectivity", "icon": "mdi:wifi",
                "device": device,
            }), retain=True)

        self.logger.info("Published HA MQTT discovery — device: %s", self.device_name)

    def _remove_discovery(self) -> None:
        if not self.ha_discovery or not self.mqtt_client:
            return
        prefix = self.discovery_prefix
        uid    = self._discovery_uid()
        for topic in [f"{prefix}/switch/{uid}/config",
                      f"{prefix}/sensor/{uid}_label/config",
                      f"{prefix}/binary_sensor/{uid}_connected/config"]:
            try:
                self.mqtt_client.publish(topic, "", retain=True)
            except Exception as e:
                self.logger.debug("Discovery removal failed for %s: %s", topic, e)

    def _publish_availability(self, online: bool) -> None:
        if not self.mqtt_client:
            return
        try:
            self.mqtt_client.publish(
                self.availability_topic, "online" if online else "offline", retain=True)
        except Exception as e:
            self.logger.debug("Availability publish failed: %s", e)

    def _publish_label(self, label: str) -> None:
        if not self.mqtt_client or not self.mqtt_connected:
            return
        try:
            self.mqtt_client.publish(self.label_topic, label, retain=True)
        except Exception as e:
            self.logger.debug("Label publish failed: %s", e)

    # ── MQTT payload ─────────────────────────────────────────────────────────────

    def _parse_payload(self, raw: bytes):
        """Return (on_air, label, text_color, bg_color) from raw MQTT payload.

        Returns (None, None, None, None) for unrecognized payloads so the
        caller can treat them as a no-op rather than an accidental OFF.
        """
        try:
            text = raw.decode('utf-8').strip()
        except UnicodeDecodeError:
            return None, None, None, None

        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            raw_state = data.get('state')
            if raw_state is None:
                return None, None, None, None  # no state key — ignore
            state = str(raw_state).lower()
            if state not in ('on', 'off', '1', '0', 'true', 'false'):
                return None, None, None, None  # unrecognised state value — ignore
            on_air = state in ('on', '1', 'true')
            label  = data.get('label') or None
            raw_tc = data.get('color') or data.get('text_color')
            raw_bg = data.get('bg') or data.get('background_color')
            tc     = _rgb(raw_tc, None) if raw_tc and len(raw_tc) == 3 else None
            bg     = _rgb(raw_bg, None) if raw_bg and len(raw_bg) == 3 else None
            return on_air, label, tc, bg
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Plain string: only act on explicitly recognised values
        lower = text.lower()
        if lower in ('on', '1', 'true'):
            return True, None, None, None
        if lower in ('off', '0', 'false'):
            return False, None, None, None
        return None, None, None, None  # unrecognised plain string — ignore

    def _trigger_display(self, on: bool) -> None:
        req: Dict[str, Any] = {
            'request_id': str(uuid.uuid4()),
            'plugin_id':  self.plugin_id,
            'action':     'start' if on else 'stop',
            'timestamp':  time.time(),
        }
        if on:
            req.update({'mode': 'on_air', 'duration': None, 'pinned': True})
        self.cache_manager.set('display_on_demand_request', req)

    def _publish_state(self, on: bool) -> None:
        if not self.mqtt_client or not self.mqtt_connected:
            return
        try:
            self.mqtt_client.publish(self.state_topic, 'ON' if on else 'OFF', retain=True)
        except Exception as e:
            self.logger.debug("State publish failed: %s", e)

    # ── MQTT callbacks ───────────────────────────────────────────────────────────

    def _on_mqtt_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        if rc == 0:
            self.mqtt_connected  = True
            self.mqtt_connecting = False
            self.mqtt_reconnect_delay = 1.0
            client.subscribe(self.command_topic, qos=1)
            self._publish_availability(True)
            self._publish_discovery()
            self.logger.info("MQTT connected — subscribed to %s", self.command_topic)
        else:
            self.mqtt_connecting = False
            self.mqtt_connected  = False
            self.logger.error("MQTT connect failed rc=%s", rc)

    def _on_mqtt_disconnect(self, client, userdata, rc):  # pylint: disable=unused-argument
        self.mqtt_connected  = False
        self.mqtt_connecting = False
        if rc != 0:
            self.logger.warning("MQTT disconnected unexpectedly rc=%s", rc)

    def _on_mqtt_message(self, client, userdata, msg):  # pylint: disable=unused-argument
        try:
            on_air, label, tc, bg = self._parse_payload(msg.payload)
            if on_air is None:
                self.logger.debug("Ignoring unrecognised payload on %s", msg.topic)
                return
            with self.state_lock:
                self.on_air = on_air
                self.label  = label if label else (self.default_label if on_air else self.default_label)
                self.active_text_color = tc if tc else self.default_text_color
                self.active_bg_color   = bg if bg else self.default_bg_color
                current_label = self.label
            self._trigger_display(on_air)
            self._publish_state(on_air)
            self._publish_label(current_label if on_air else '')
            self.logger.info("On Air → %s  label=%s", 'ON' if on_air else 'OFF', current_label)
        except Exception as e:
            self.logger.error("Error handling MQTT message: %s", e, exc_info=True)

    # ── MQTT connect / loop ──────────────────────────────────────────────────────

    def _connect_mqtt(self) -> bool:
        try:
            try:
                self.mqtt_client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self.mqtt_client_id, clean_session=True)
            except (TypeError, AttributeError):
                self.mqtt_client = mqtt.Client(
                    client_id=self.mqtt_client_id, clean_session=True)
            self.mqtt_client.on_connect    = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message    = self._on_mqtt_message
            if self.mqtt_username:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
            self.mqtt_client.will_set(
                self.availability_topic, payload="offline", qos=1, retain=True)
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            return True
        except Exception as e:
            self.logger.error("MQTT connect error: %s", e)
            return False

    def _mqtt_loop(self) -> None:
        while not self.mqtt_stop_event.is_set():
            try:
                if not self.mqtt_connected and not self.mqtt_connecting:
                    self.mqtt_connecting = True
                    if self._connect_mqtt():
                        self.mqtt_client.loop_start()
                        # Wait for CONNACK before looping — prevents duplicate connections
                        self.mqtt_stop_event.wait(5.0)
                    else:
                        self.mqtt_connecting = False
                        wait = min(self.mqtt_reconnect_delay, self.mqtt_max_reconnect_delay)
                        self.logger.info("Retrying MQTT in %.0fs", wait)
                        if self.mqtt_stop_event.wait(wait):
                            break
                        self.mqtt_reconnect_delay = min(
                            self.mqtt_reconnect_delay * 2, self.mqtt_max_reconnect_delay)
                else:
                    if self.mqtt_stop_event.wait(1.0):
                        break
                    self.mqtt_reconnect_delay = 1.0
            except Exception as e:
                self.logger.error("MQTT loop error: %s", e, exc_info=True)
                self.mqtt_connected  = False
                self.mqtt_connecting = False
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
                self.mqtt_reconnect_delay = min(
                    self.mqtt_reconnect_delay * 2, self.mqtt_max_reconnect_delay)

        self._publish_availability(False)
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None
        self.logger.info("MQTT loop stopped")

    def _graceful_shutdown(self) -> None:
        if self.mqtt_thread and self.mqtt_thread.is_alive():
            self.mqtt_stop_event.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
            self.mqtt_thread.join(timeout=5.0)
        self.mqtt_connected  = False
        self.mqtt_connecting = False
