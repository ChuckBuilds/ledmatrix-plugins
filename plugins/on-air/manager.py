"""
On Air Light Plugin for LEDMatrix

Displays a retro broadcast "ON AIR" tally light, activated remotely via MQTT
or Home Assistant. The display latches on until explicitly turned off, making
it a persistent do-not-disturb signal during calls or recordings.

MQTT topics (all derived from command_topic base):
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
import math
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore

from src.plugin_system.base_plugin import BasePlugin

_PLUGIN_VERSION = "1.1.0"


class OnAirPlugin(BasePlugin):
    """Retro ON AIR tally light driven by MQTT with HA auto-discovery."""

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
        self.mqtt_client_id = f'ledmatrix-on-air-{plugin_id}'
        self.command_topic  = config.get('command_topic', 'ledmatrix/on-air/set')
        self.state_topic    = config.get('state_topic',   'ledmatrix/on-air/state')

        # HA auto-discovery
        self.ha_discovery      = bool(config.get('ha_discovery', True))
        self.discovery_prefix  = config.get('discovery_prefix', 'homeassistant')
        self.device_name       = config.get('device_name', 'LED Matrix — On Air')

        # Derived topics (availability + label live alongside command/state)
        self._derive_topics()

        # Display defaults (may be overridden per message)
        self.default_label = config.get('default_label', 'ON AIR')
        raw_color          = config.get('default_color', [255, 20, 20])
        self.default_color: Tuple[int, int, int] = tuple(int(c) for c in raw_color)
        self.pulse_enabled = bool(config.get('pulse_enabled', True))
        self.pulse_speed   = float(config.get('pulse_speed', 1.2))  # Hz

        # Runtime state (protected by lock — MQTT callback runs in another thread)
        self.state_lock   = threading.Lock()
        self.on_air       = False
        self.label        = self.default_label
        self.active_color = self.default_color

        # MQTT internals — same pattern as mqtt-notifications
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_thread: Optional[threading.Thread] = None
        self.mqtt_connected = False
        self.mqtt_reconnect_delay     = 1.0
        self.mqtt_max_reconnect_delay = 60.0
        self.mqtt_stop_event = threading.Event()

        self.logger.info("On Air plugin ready — command: %s  available: %s",
                         self.command_topic, self.availability_topic)

    # ── Topic helpers ───────────────────────────────────────────────────────────

    def _derive_topics(self) -> None:
        """Derive availability and label topics from the command topic."""
        base = self.command_topic
        if base.endswith('/set'):
            base = base[:-4]
        self.topic_base        = base
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

    # ── BasePlugin interface ────────────────────────────────────────────────────

    def update(self) -> None:
        pass  # entirely event-driven; no polling needed

    def display(self, force_clear: bool = False) -> None:
        dw = self.display_manager.matrix.width
        dh = self.display_manager.matrix.height

        canvas = Image.new('RGB', (dw, dh), (0, 0, 0))
        self.display_manager.image = canvas
        self.display_manager.draw  = ImageDraw.Draw(canvas)

        with self.state_lock:
            active = self.on_air
            label  = self.label
            color  = self.active_color

        if active:
            self._render_on_air(canvas, dw, dh, label, color)
        else:
            self._render_standby(canvas, dw, dh)

        self.display_manager.update_display()

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
        broker_changed = (
            new_config.get('mqtt_host', 'localhost') != self.mqtt_host or
            int(new_config.get('mqtt_port', 1883))   != self.mqtt_port
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
        self.default_label    = new_config.get('default_label', 'ON AIR')
        raw_color             = new_config.get('default_color', [255, 20, 20])
        self.default_color    = tuple(int(c) for c in raw_color)
        self.pulse_enabled    = bool(new_config.get('pulse_enabled', True))
        self.pulse_speed      = float(new_config.get('pulse_speed', 1.2))
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

    # ── Rendering ───────────────────────────────────────────────────────────────

    def _pulse(self) -> float:
        """Sinusoidal 0→1 pulse at self.pulse_speed Hz."""
        if not self.pulse_enabled:
            return 1.0
        return 0.5 + 0.5 * math.sin(time.time() * math.pi * 2 * self.pulse_speed)

    def _render_on_air(self, canvas: Image.Image, dw: int, dh: int,
                       label: str, color: Tuple[int, int, int]) -> None:
        draw    = ImageDraw.Draw(canvas)
        pulse   = self._pulse()
        r, g, b = color

        # ── Background: dark tinted glow ──────────────────────────────────────
        bg_r = int(r * (0.08 + 0.07 * pulse))
        bg_g = int(g * (0.08 + 0.07 * pulse))
        bg_b = int(b * (0.08 + 0.07 * pulse))
        draw.rectangle([0, 0, dw - 1, dh - 1], fill=(bg_r, bg_g, bg_b))

        # ── Border strips (top + bottom rows of dots) ─────────────────────────
        dot_r = int(r * (0.55 + 0.45 * pulse))
        dot_g = int(g * (0.55 + 0.45 * pulse))
        dot_b = int(b * (0.55 + 0.45 * pulse))
        dot_color   = (dot_r, dot_g, dot_b)
        dot_spacing = 4
        border_rows = max(1, dh // 16)
        for row_offset in range(border_rows):
            for x in range(0, dw, dot_spacing):
                draw.point((x, row_offset),           fill=dot_color)
                draw.point((x, dh - 1 - row_offset),  fill=dot_color)

        # ── Tally indicator dot (left of text zone) ───────────────────────────
        dot_r2      = int(r * (0.7 + 0.3 * pulse))
        tally_color = (dot_r2, int(g * 0.1), int(b * 0.1))
        tally_r     = max(2, dh // 10)
        tally_cx    = tally_r + 3
        tally_cy    = dh // 2
        draw.ellipse(
            [tally_cx - tally_r, tally_cy - tally_r,
             tally_cx + tally_r, tally_cy + tally_r],
            fill=tally_color,
        )
        if tally_r > 2:
            core_r = max(1, tally_r - 1)
            core_b = int(255 * pulse)
            draw.ellipse(
                [tally_cx - core_r, tally_cy - core_r,
                 tally_cx + core_r, tally_cy + core_r],
                fill=(255, core_b // 8, core_b // 8),
            )

        # ── Text ──────────────────────────────────────────────────────────────
        text_x    = dw // 2
        text_color = (255, 255, 255)
        small      = dw <= 64
        sub        = label if (label.upper() != 'ON AIR' and not small) else None

        if sub and dh >= 24:
            self.display_manager.draw_text(
                'ON AIR', x=text_x, y=dh // 2 - 10,
                color=text_color, font=self.display_manager.small_font, centered=True)
            self.display_manager.draw_text(
                sub[:16], x=text_x, y=dh // 2 + 2,
                color=(220, 220, 220), font=self.display_manager.extra_small_font, centered=True)
        else:
            font = (self.display_manager.extra_small_font if small
                    else self.display_manager.small_font)
            self.display_manager.draw_text(
                label[:16], x=text_x, y=dh // 2 - 4,
                color=text_color, font=font, centered=True)

    def _render_standby(self, canvas: Image.Image, dw: int, dh: int) -> None:
        """Near-black screen — cycles past quickly when Off."""
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, 0, dw - 1, dh - 1], fill=(4, 0, 0))
        draw.point((2, 2), fill=(30, 0, 0))

    # ── HA MQTT Auto-Discovery ──────────────────────────────────────────────────

    def _publish_discovery(self) -> None:
        """Publish HA MQTT discovery payloads — creates device + 3 entities in HA."""
        if not self.ha_discovery or not self.mqtt_client:
            return

        prefix  = self.discovery_prefix
        uid     = self._discovery_uid()
        device  = self._discovery_device()
        avail   = [{"topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline"}]

        # ── Switch (on/off control) ───────────────────────────────────────────
        self.mqtt_client.publish(
            f"{prefix}/switch/{uid}/config",
            json.dumps({
                "name":            "On Air",
                "unique_id":       f"{uid}_switch",
                "command_topic":   self.command_topic,
                "state_topic":     self.state_topic,
                "payload_on":      "ON",
                "payload_off":     "OFF",
                "state_on":        "ON",
                "state_off":       "OFF",
                "icon":            "mdi:broadcast",
                "availability":    avail,
                "device":          device,
            }),
            retain=True,
        )

        # ── Sensor — current label ────────────────────────────────────────────
        self.mqtt_client.publish(
            f"{prefix}/sensor/{uid}_label/config",
            json.dumps({
                "name":         "Current Label",
                "unique_id":    f"{uid}_label",
                "state_topic":  self.label_topic,
                "icon":         "mdi:label-outline",
                "availability": avail,
                "device":       device,
            }),
            retain=True,
        )

        # ── Binary sensor — broker connectivity ───────────────────────────────
        self.mqtt_client.publish(
            f"{prefix}/binary_sensor/{uid}_connected/config",
            json.dumps({
                "name":         "MQTT Connected",
                "unique_id":    f"{uid}_connected",
                "state_topic":  self.availability_topic,
                "payload_on":   "online",
                "payload_off":  "offline",
                "device_class": "connectivity",
                "icon":         "mdi:wifi",
                "device":       device,
            }),
            retain=True,
        )

        self.logger.info("Published HA MQTT discovery — device: %s", self.device_name)

    def _remove_discovery(self) -> None:
        """Clear HA discovery entries by publishing empty retained payloads."""
        if not self.ha_discovery or not self.mqtt_client:
            return
        prefix = self.discovery_prefix
        uid    = self._discovery_uid()
        for topic in [
            f"{prefix}/switch/{uid}/config",
            f"{prefix}/sensor/{uid}_label/config",
            f"{prefix}/binary_sensor/{uid}_connected/config",
        ]:
            try:
                self.mqtt_client.publish(topic, "", retain=True)
            except Exception:
                pass

    def _publish_availability(self, online: bool) -> None:
        if not self.mqtt_client:
            return
        try:
            self.mqtt_client.publish(
                self.availability_topic,
                "online" if online else "offline",
                retain=True,
            )
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

    def _parse_payload(self, raw: bytes) -> Tuple[bool, Optional[str], Optional[Tuple]]:
        """Return (on_air, label_override, color_override) from raw MQTT payload."""
        try:
            text = raw.decode('utf-8').strip()
        except UnicodeDecodeError:
            return False, None, None

        try:
            data   = json.loads(text)
            state  = str(data.get('state', '')).lower()
            on_air = state in ('on', '1', 'true')
            label  = data.get('label') or None
            raw_c  = data.get('color')
            color  = tuple(int(c) for c in raw_c) if raw_c and len(raw_c) == 3 else None
            return on_air, label, color
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        on_air = text.lower() in ('on', '1', 'true')
        return on_air, None, None

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
            self.mqtt_client.publish(
                self.state_topic, 'ON' if on else 'OFF', retain=True)
        except Exception as e:
            self.logger.debug("State publish failed: %s", e)

    # ── MQTT callbacks ───────────────────────────────────────────────────────────

    def _on_mqtt_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        if rc == 0:
            self.mqtt_connected = True
            self.mqtt_reconnect_delay = 1.0
            client.subscribe(self.command_topic, qos=1)
            self._publish_availability(True)
            self._publish_discovery()
            self.logger.info("MQTT connected — subscribed to %s", self.command_topic)
        else:
            self.mqtt_connected = False
            self.logger.error("MQTT connect failed rc=%s", rc)

    def _on_mqtt_disconnect(self, client, userdata, rc):  # pylint: disable=unused-argument
        self.mqtt_connected = False
        # LWT fires automatically on unexpected disconnect;
        # log only for unexpected drops
        if rc != 0:
            self.logger.warning("MQTT disconnected unexpectedly rc=%s", rc)

    def _on_mqtt_message(self, client, userdata, msg):  # pylint: disable=unused-argument
        try:
            on_air, label, color = self._parse_payload(msg.payload)
            with self.state_lock:
                self.on_air = on_air
                if label:
                    self.label = label
                elif not on_air:
                    self.label = self.default_label
                if color:
                    self.active_color = color
                elif not on_air:
                    self.active_color = self.default_color
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
                    client_id=self.mqtt_client_id,
                    clean_session=True,
                )
            except (TypeError, AttributeError):
                self.mqtt_client = mqtt.Client(
                    client_id=self.mqtt_client_id,
                    clean_session=True,
                )

            self.mqtt_client.on_connect    = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message    = self._on_mqtt_message

            if self.mqtt_username:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)

            # Last Will — HA marks device unavailable if connection drops unexpectedly
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
                if not self.mqtt_connected:
                    if self._connect_mqtt():
                        self.mqtt_client.loop_start()
                    else:
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
                self.mqtt_reconnect_delay = min(
                    self.mqtt_reconnect_delay * 2, self.mqtt_max_reconnect_delay)

        # Clean shutdown — mark offline, optionally remove discovery
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
        """Stop MQTT thread cleanly, publishing offline availability first."""
        if self.mqtt_thread and self.mqtt_thread.is_alive():
            self.mqtt_stop_event.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
            self.mqtt_thread.join(timeout=5.0)
        self.mqtt_connected = False
