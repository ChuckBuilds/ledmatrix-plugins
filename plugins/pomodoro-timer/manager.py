"""
Pomodoro Timer Plugin for LEDMatrix

A configurable focus/break (Pomodoro) timer rendered on the matrix and driven
over MQTT, with Home Assistant auto-discovery so the whole timer — start,
pause, resume, skip, reset, plus the work and break durations — appears as a
device in Home Assistant with no YAML.

The timer runs in its own thread, so it keeps counting (and keeps publishing
state) whether or not the plugin is the screen currently on the panel.

MQTT topics (all derived from the command topic's base):
  <base>/set                — subscribe: START | PAUSE | RESUME | TOGGLE | STOP |
                              RESET | SKIP | WORK | SHORT_BREAK | LONG_BREAK,
                              or a JSON object (see _parse_command)
  <base>/state              — publish:   ON / OFF                  (HA switch)
  <base>/status             — publish:   running / paused / idle
  <base>/phase              — publish:   idle | work | short_break | long_break
  <base>/remaining          — publish:   MM:SS
  <base>/remaining_seconds  — publish:   integer seconds
  <base>/session            — publish:   completed work sessions
  <base>/attributes         — publish:   JSON snapshot of the full state
  <base>/event              — publish:   JSON {"event_type": ...} on transitions
  <base>/available          — publish:   online / offline (also the LWT)
  <base>/<number>/set       — subscribe: work_minutes, short_break_minutes,
  <base>/<number>             long_break_minutes, sessions_before_long_break

HA MQTT Auto-Discovery (enabled by default) publishes device + entity configs
to homeassistant/<component>/... on connect, so Home Assistant builds the
device automatically.
"""

import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore

from src.plugin_system.base_plugin import BasePlugin

_PLUGIN_VERSION = "1.0.0"

PHASE_IDLE = "idle"
PHASE_WORK = "work"
PHASE_SHORT_BREAK = "short_break"
PHASE_LONG_BREAK = "long_break"

# attr name, HA entity name, min, max, step, icon
_NUMBER_FIELDS: Tuple[Tuple[str, str, int, int, int, str], ...] = (
    ("work_minutes",               "Work Minutes",               1, 180, 1, "mdi:briefcase-clock"),
    ("short_break_minutes",        "Short Break Minutes",        1,  60, 1, "mdi:coffee-outline"),
    ("long_break_minutes",         "Long Break Minutes",         1, 120, 1, "mdi:sofa-outline"),
    ("sessions_before_long_break", "Sessions Before Long Break", 1,  12, 1, "mdi:counter"),
)

# key suffix, HA entity name, payload published to the command topic, icon
_BUTTONS: Tuple[Tuple[str, str, str, str], ...] = (
    ("start",  "Start",      "START",  "mdi:play"),
    ("pause",  "Pause",      "PAUSE",  "mdi:pause"),
    ("resume", "Resume",     "RESUME", "mdi:play"),
    ("skip",   "Skip Phase", "SKIP",   "mdi:skip-next"),
    ("reset",  "Reset",      "RESET",  "mdi:restart"),
)

_EVENT_TYPES = [
    "started", "paused", "resumed", "stopped", "reset", "skipped",
    "phase_started", "work_complete", "break_complete",
]

_PHASE_ORDER = (PHASE_WORK, PHASE_SHORT_BREAK, PHASE_LONG_BREAK)


def _rgb(value, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Coerce a config/JSON colour into a clamped RGB tuple."""
    try:
        parts = [max(0, min(255, int(c))) for c in value]
    except (TypeError, ValueError):
        return default
    if len(parts) != 3:
        return default
    return (parts[0], parts[1], parts[2])


def _dim(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in color)  # type: ignore[return-value]


def _fmt_clock(seconds: float) -> str:
    """Format remaining seconds as MM:SS (minutes are not wrapped at 60)."""
    total = int(math.ceil(max(0.0, seconds) - 1e-6))
    return f"{total // 60:02d}:{total % 60:02d}"


class PomodoroTimerPlugin(BasePlugin):
    """Pomodoro focus/break timer with MQTT control and HA auto-discovery."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Runtime state (guarded by state_lock). Created before settings are
        # loaded so _load_settings can seed the idle countdown.
        self.state_lock = threading.RLock()
        self.phase = PHASE_IDLE
        self.running = False
        self.phase_total = 25 * 60.0
        self.remaining = 25 * 60.0
        self.deadline: Optional[float] = None
        self.completed_sessions = 0
        self.cycle_position = 0
        self.custom_label: Optional[str] = None
        self.alert_until = 0.0
        self.alert_color: Optional[Tuple[int, int, int]] = None

        self._load_settings(config)
        self.remaining = self.phase_total = float(self.work_minutes * 60)

        # Fonts
        self._font_cache: Dict[int, Any] = {}
        self._ttf_path_cache: Optional[str] = None
        self._ttf_path_resolved = False

        # Display pinning
        self._pinned = False

        # Timer thread
        self.timer_thread: Optional[threading.Thread] = None
        self.timer_stop_event = threading.Event()

        # MQTT internals
        self.mqtt_client_id = f"ledmatrix-pomodoro-{plugin_id}-{uuid.uuid4().hex[:8]}"
        self.mqtt_client: Optional["mqtt.Client"] = None
        self.mqtt_thread: Optional[threading.Thread] = None
        self.mqtt_connected = False
        self.mqtt_connecting = False
        self.mqtt_reconnect_delay = 1.0
        self.mqtt_max_reconnect_delay = 60.0
        self.mqtt_stop_event = threading.Event()
        self._last_publish = 0.0
        self._last_published_key: Optional[Tuple] = None

        if self.mqtt_enabled and mqtt is None:
            self.logger.error(
                "paho-mqtt is not installed — MQTT control is disabled. "
                "Install it with: pip install paho-mqtt")

        self.logger.info("Pomodoro timer ready — %d/%d/%d min, command topic: %s",
                         self.work_minutes, self.short_break_minutes,
                         self.long_break_minutes, self.command_topic)

    # ── Configuration ───────────────────────────────────────────────────────────

    def _load_settings(self, config: Dict[str, Any]) -> None:
        """Read every configurable value out of `config` onto self."""
        def _int(key: str, default: int, low: int, high: int) -> int:
            try:
                return max(low, min(high, int(config.get(key, default))))
            except (TypeError, ValueError):
                return default

        # Timer
        self.work_minutes               = _int("work_minutes", 25, 1, 180)
        self.short_break_minutes        = _int("short_break_minutes", 5, 1, 60)
        self.long_break_minutes         = _int("long_break_minutes", 15, 1, 120)
        self.sessions_before_long_break = _int("sessions_before_long_break", 4, 1, 12)
        self.auto_start_breaks = bool(config.get("auto_start_breaks", True))
        self.auto_start_work   = bool(config.get("auto_start_work", False))
        self.auto_start_on_enable = bool(config.get("auto_start_on_enable", False))

        # Labels
        self.work_label        = str(config.get("work_label", "FOCUS"))
        self.short_break_label = str(config.get("short_break_label", "BREAK"))
        self.long_break_label  = str(config.get("long_break_label", "LONG BREAK"))
        self.idle_label        = str(config.get("idle_label", "POMODORO"))
        self.paused_label      = str(config.get("paused_label", "PAUSED"))

        # Appearance
        self.color_mode        = str(config.get("color_mode", "phase"))
        self.time_color        = _rgb(config.get("time_color", [255, 255, 255]), (255, 255, 255))
        self.work_color        = _rgb(config.get("work_color", [255, 70, 50]), (255, 70, 50))
        self.short_break_color = _rgb(config.get("short_break_color", [60, 200, 110]), (60, 200, 110))
        self.long_break_color  = _rgb(config.get("long_break_color", [70, 150, 255]), (70, 150, 255))
        self.idle_color        = _rgb(config.get("idle_color", [110, 110, 110]), (110, 110, 110))
        self.paused_color      = _rgb(config.get("paused_color", [255, 176, 0]), (255, 176, 0))
        self.background_color  = _rgb(config.get("background_color", [0, 0, 0]), (0, 0, 0))
        self.show_phase_label  = bool(config.get("show_phase_label", True))
        self.show_session_dots = bool(config.get("show_session_dots", True))
        self.show_progress_bar = bool(config.get("show_progress_bar", True))
        self.font_path = str(config.get("font_path", "") or "")
        try:
            self.font_size = max(0, min(64, int(config.get("font_size", 0))))
        except (TypeError, ValueError):
            self.font_size = 0

        # Behaviour
        self.pin_while_running = bool(config.get("pin_while_running", True))
        try:
            self.alert_seconds = max(0, min(60, int(config.get("alert_seconds", 8))))
        except (TypeError, ValueError):
            self.alert_seconds = 8
        self.alert_flash = bool(config.get("alert_flash", True))

        # MQTT
        self.mqtt_enabled  = bool(config.get("mqtt_enabled", True))
        self.mqtt_host     = str(config.get("mqtt_host", "localhost"))
        try:
            self.mqtt_port = int(config.get("mqtt_port", 1883))
        except (TypeError, ValueError):
            self.mqtt_port = 1883
        self.mqtt_username = str(config.get("mqtt_username", "") or "")
        self.mqtt_password = str(config.get("mqtt_password", "") or "")
        self.command_topic = str(config.get("command_topic", "ledmatrix/pomodoro/set"))
        self.state_topic   = str(config.get("state_topic", "ledmatrix/pomodoro/state"))
        self.ha_discovery     = bool(config.get("ha_discovery", True))
        self.discovery_prefix = str(config.get("discovery_prefix", "homeassistant"))
        self.device_name      = str(config.get("device_name", "LED Matrix — Pomodoro"))
        try:
            self.publish_interval = max(1, min(60, int(config.get("publish_interval_seconds", 1))))
        except (TypeError, ValueError):
            self.publish_interval = 1

        self._derive_topics()

    def _derive_topics(self) -> None:
        base = self.command_topic
        if base.endswith("/set"):
            base = base[:-4]
        self.topic_base         = base
        self.availability_topic = f"{base}/available"
        self.status_topic       = f"{base}/status"
        self.phase_topic        = f"{base}/phase"
        self.remaining_topic    = f"{base}/remaining"
        self.remaining_secs_topic = f"{base}/remaining_seconds"
        self.session_topic      = f"{base}/session"
        self.attributes_topic   = f"{base}/attributes"
        self.event_topic        = f"{base}/event"
        self.number_state_topics = {f: f"{base}/{f}" for f, *_ in _NUMBER_FIELDS}
        self.number_set_topics   = {f"{base}/{f}/set": f for f, *_ in _NUMBER_FIELDS}

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        if self.color_mode not in ("phase", "fixed"):
            self.logger.error("Invalid color_mode: %s (expected 'phase' or 'fixed')",
                              self.color_mode)
            return False
        if not self.command_topic.strip():
            self.logger.error("command_topic must not be empty")
            return False
        if not 1 <= self.mqtt_port <= 65535:
            self.logger.error("Invalid mqtt_port: %s", self.mqtt_port)
            return False
        return True

    # ── Timer state ─────────────────────────────────────────────────────────────

    def _phase_seconds(self, phase: str) -> float:
        return {
            PHASE_WORK:        self.work_minutes * 60.0,
            PHASE_SHORT_BREAK: self.short_break_minutes * 60.0,
            PHASE_LONG_BREAK:  self.long_break_minutes * 60.0,
        }.get(phase, self.work_minutes * 60.0)

    def _remaining_locked(self) -> float:
        if self.running and self.deadline is not None:
            return max(0.0, self.deadline - time.monotonic())
        return max(0.0, self.remaining)

    def _begin_phase_locked(self, phase: str, seconds: Optional[float] = None,
                            run: bool = True, label: Optional[str] = None) -> None:
        total = float(seconds) if seconds else self._phase_seconds(phase)
        self.phase = phase
        self.phase_total = max(1.0, total)
        self.remaining = self.phase_total
        self.running = bool(run) and phase != PHASE_IDLE
        self.deadline = time.monotonic() + self.phase_total if self.running else None
        self.custom_label = label or None

    def _go_idle_locked(self, reset_counters: bool = False) -> None:
        self.phase = PHASE_IDLE
        self.running = False
        self.deadline = None
        self.phase_total = self._phase_seconds(PHASE_WORK)
        self.remaining = self.phase_total
        self.custom_label = None
        if reset_counters:
            self.completed_sessions = 0
            self.cycle_position = 0

    def _next_phase_locked(self, completed: bool = True) -> str:
        """Which phase follows the current one, without mutating counters.

        A skipped work session doesn't count toward the set, so it never earns
        the long break.
        """
        if self.phase == PHASE_WORK:
            position = self.cycle_position + (1 if completed else 0)
            return (PHASE_LONG_BREAK if position >= self.sessions_before_long_break
                    else PHASE_SHORT_BREAK)
        return PHASE_WORK

    def _advance_locked(self, completed: bool) -> List[Dict[str, Any]]:
        """Move to the next phase. `completed` distinguishes a finished phase
        from a skipped one (only finished work counts toward the cycle)."""
        events: List[Dict[str, Any]] = []
        previous = self.phase
        nxt = self._next_phase_locked(completed)

        if previous == PHASE_WORK and completed:
            self.completed_sessions += 1
            self.cycle_position = min(self.sessions_before_long_break,
                                      self.cycle_position + 1)
        elif previous == PHASE_LONG_BREAK:
            # A long break closes the set, so the session dots start over.
            self.cycle_position = 0
        auto = self.auto_start_work if nxt == PHASE_WORK else self.auto_start_breaks

        if completed:
            events.append({
                "event_type": "work_complete" if previous == PHASE_WORK else "break_complete",
                "phase": previous,
                "next_phase": nxt,
                "completed_sessions": self.completed_sessions,
            })
            if self.alert_seconds:
                self.alert_until = time.monotonic() + self.alert_seconds
                self.alert_color = self._phase_color(previous)
        else:
            events.append({"event_type": "skipped", "phase": previous, "next_phase": nxt})

        self._begin_phase_locked(nxt, run=auto)
        events.append({
            "event_type": "phase_started",
            "phase": nxt,
            "auto_started": bool(auto),
            "duration_seconds": int(self.phase_total),
        })
        return events

    def _tick(self) -> None:
        """Advance the state machine and publish. Safe to call from any thread."""
        events: List[Dict[str, Any]] = []
        with self.state_lock:
            # A phase can only roll over once per tick in practice, but loop
            # defensively in case the process was suspended for a long time.
            for _ in range(8):
                if not self.running or self.deadline is None:
                    break
                if time.monotonic() < self.deadline:
                    break
                events.extend(self._advance_locked(completed=True))
        for event in events:
            self._publish_event(event)
        if events:
            self._sync_pin()
            self._publish_state(force=True)
        else:
            self._publish_state()

    # ── Commands ────────────────────────────────────────────────────────────────

    def _apply_command(self, command: str, payload: Dict[str, Any]) -> None:
        """Apply a normalised command plus any JSON options that came with it."""
        command = (command or "").strip().upper().replace("-", "_").replace(" ", "_")
        events: List[Dict[str, Any]] = []

        with self.state_lock:
            # Duration overrides that arrive alongside the command.
            for field, *_ in _NUMBER_FIELDS:
                if field in payload:
                    self._set_number_locked(field, payload[field])
            label = payload.get("label")
            explicit = payload.get("duration_minutes") or payload.get("minutes")
            duration = None
            if explicit is not None:
                try:
                    duration = max(1.0, float(explicit)) * 60.0
                except (TypeError, ValueError):
                    duration = None
            if duration is None and payload.get("duration_seconds") is not None:
                try:
                    duration = max(1.0, float(payload["duration_seconds"]))
                except (TypeError, ValueError):
                    duration = None

            if command in ("START", "ON", "PLAY"):
                phase = str(payload.get("phase", "") or "").strip().lower()
                if phase in _PHASE_ORDER:
                    self._begin_phase_locked(phase, duration, run=True, label=label)
                elif self.phase == PHASE_IDLE or self.remaining <= 0:
                    self._begin_phase_locked(PHASE_WORK, duration, run=True, label=label)
                elif not self.running:
                    self._resume_locked()
                elif duration is not None:
                    self._begin_phase_locked(self.phase, duration, run=True, label=label)
                events.append({"event_type": "started", "phase": self.phase,
                               "duration_seconds": int(self.phase_total)})

            elif command in ("WORK", "FOCUS"):
                self._begin_phase_locked(PHASE_WORK, duration, run=True, label=label)
                events.append({"event_type": "started", "phase": PHASE_WORK,
                               "duration_seconds": int(self.phase_total)})

            elif command in ("SHORT_BREAK", "BREAK"):
                self._begin_phase_locked(PHASE_SHORT_BREAK, duration, run=True, label=label)
                events.append({"event_type": "started", "phase": PHASE_SHORT_BREAK,
                               "duration_seconds": int(self.phase_total)})

            elif command == "LONG_BREAK":
                self._begin_phase_locked(PHASE_LONG_BREAK, duration, run=True, label=label)
                events.append({"event_type": "started", "phase": PHASE_LONG_BREAK,
                               "duration_seconds": int(self.phase_total)})

            elif command == "PAUSE":
                if self.running:
                    self.remaining = self._remaining_locked()
                    self.running = False
                    self.deadline = None
                    events.append({"event_type": "paused", "phase": self.phase,
                                   "remaining_seconds": int(self.remaining)})

            elif command == "RESUME":
                if not self.running and self.phase != PHASE_IDLE:
                    self._resume_locked()
                    events.append({"event_type": "resumed", "phase": self.phase,
                                   "remaining_seconds": int(self.remaining)})

            elif command in ("TOGGLE", "PAUSE_RESUME"):
                if self.phase == PHASE_IDLE:
                    self._begin_phase_locked(PHASE_WORK, duration, run=True, label=label)
                    events.append({"event_type": "started", "phase": PHASE_WORK,
                                   "duration_seconds": int(self.phase_total)})
                elif self.running:
                    self.remaining = self._remaining_locked()
                    self.running = False
                    self.deadline = None
                    events.append({"event_type": "paused", "phase": self.phase,
                                   "remaining_seconds": int(self.remaining)})
                else:
                    self._resume_locked()
                    events.append({"event_type": "resumed", "phase": self.phase,
                                   "remaining_seconds": int(self.remaining)})

            elif command in ("STOP", "OFF"):
                self._go_idle_locked()
                self.alert_until = 0.0
                events.append({"event_type": "stopped"})

            elif command in ("RESET", "CLEAR"):
                self._go_idle_locked(reset_counters=True)
                self.alert_until = 0.0
                events.append({"event_type": "reset"})

            elif command in ("SKIP", "NEXT"):
                if self.phase != PHASE_IDLE:
                    events.extend(self._advance_locked(completed=False))

            elif command in ("SET", "CONFIGURE", ""):
                # Duration-only payload — already applied above.
                pass

            else:
                self.logger.debug("Ignoring unrecognised command: %r", command)
                return

        for event in events:
            self._publish_event(event)
        self._sync_pin()
        self._publish_state(force=True)
        with self.state_lock:
            self.logger.info("Pomodoro %s → phase=%s running=%s remaining=%s",
                             command, self.phase, self.running,
                             _fmt_clock(self._remaining_locked()))

    def _resume_locked(self) -> None:
        self.remaining = max(1.0, self.remaining)
        self.running = True
        self.deadline = time.monotonic() + self.remaining

    def _set_number_locked(self, field: str, raw: Any) -> bool:
        """Apply one of the numeric settings; returns True when it changed."""
        spec = next((s for s in _NUMBER_FIELDS if s[0] == field), None)
        if spec is None:
            return False
        _, _, low, high, _, _ = spec
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            self.logger.warning("Invalid value for %s: %r", field, raw)
            return False
        value = max(low, min(high, value))
        if getattr(self, field) == value:
            return False
        setattr(self, field, value)
        # Keep the idle screen (and a not-yet-started phase) in step with the
        # new duration so HA edits are visible immediately.
        if self.phase == PHASE_IDLE and field == "work_minutes":
            self.phase_total = self.remaining = float(value * 60)
        elif (not self.running and self.phase != PHASE_IDLE
                and abs(self.remaining - self.phase_total) < 0.5):
            phase_field = {
                PHASE_WORK: "work_minutes",
                PHASE_SHORT_BREAK: "short_break_minutes",
                PHASE_LONG_BREAK: "long_break_minutes",
            }.get(self.phase)
            if phase_field == field:
                self.phase_total = self.remaining = float(value * 60)
        if field == "sessions_before_long_break":
            self.cycle_position = min(self.cycle_position, value)
        return True

    def _parse_command(self, raw: bytes) -> Tuple[Optional[str], Dict[str, Any]]:
        """Return (command, options) for a command-topic payload.

        Accepts a bare string (``START``) or a JSON object such as
        ``{"command": "start", "phase": "work", "duration_minutes": 50}``.
        Returns (None, {}) for anything unrecognised so a stray message can
        never be mistaken for a stop.
        """
        try:
            text = raw.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            return None, {}
        if not text:
            return None, {}

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text, {}

        if isinstance(data, dict):
            command = data.get("command") or data.get("action") or data.get("state")
            if command is None:
                # A payload with only settings is a configuration update.
                if any(f in data for f in (f for f, *_ in _NUMBER_FIELDS)):
                    return "SET", data
                return None, {}
            return str(command), data
        if isinstance(data, (int, float)):
            return ("START" if data else "STOP"), {}
        return str(data), {}

    # ── BasePlugin interface ────────────────────────────────────────────────────

    def update(self) -> None:
        # No network data to fetch; just keep the state machine honest even if
        # the timer thread is not running (e.g. under the safety harness).
        self._tick()

    def display(self, force_clear: bool = False) -> bool:
        try:
            self._tick()
            snapshot = self._snapshot()
            width, height = self._panel_size()
            canvas, draw = self._frame(width, height)
            self._render(draw, width, height, snapshot)
            self.display_manager.image = canvas
            self.display_manager.draw = draw
            self.display_manager.update_display()
            return True
        except Exception as e:
            self.logger.error("Error displaying pomodoro timer: %s", e, exc_info=True)
            try:
                self.display_manager.draw_text("Pomodoro Error", x=2, y=2, color=(255, 0, 0))
                self.display_manager.update_display()
            except Exception:
                self.logger.debug("Fallback display failed", exc_info=True)
            return False

    def get_display_duration(self) -> float:
        try:
            return float(self.config.get("display_duration", 10))
        except (TypeError, ValueError):
            return 10.0

    def on_enable(self) -> None:
        super().on_enable()
        if self.timer_thread is None or not self.timer_thread.is_alive():
            self.timer_stop_event.clear()
            self.timer_thread = threading.Thread(
                target=self._timer_loop, name=f"{self.plugin_id}-timer", daemon=True)
            self.timer_thread.start()
        if self.auto_start_on_enable:
            with self.state_lock:
                idle = self.phase == PHASE_IDLE
            if idle:
                self._apply_command("START", {})
        if self.mqtt_enabled and mqtt is not None:
            if self.mqtt_thread is None or not self.mqtt_thread.is_alive():
                self.mqtt_stop_event.clear()
                self.mqtt_thread = threading.Thread(
                    target=self._mqtt_loop, name=f"{self.plugin_id}-mqtt", daemon=True)
                self.mqtt_thread.start()
                self.logger.info("MQTT thread started")

    def on_disable(self) -> None:
        super().on_disable()
        self._graceful_shutdown()

    def cleanup(self) -> None:
        self._graceful_shutdown()
        self.logger.info("Pomodoro timer cleaned up")

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        previous = (self.mqtt_enabled, self.mqtt_host, self.mqtt_port, self.mqtt_username,
                    self.mqtt_password, self.command_topic, self.state_topic,
                    self.ha_discovery, self.discovery_prefix)
        was_idle = self.phase == PHASE_IDLE

        self._load_settings(new_config)
        self._font_cache = {}
        self._ttf_path_resolved = False
        if was_idle:
            with self.state_lock:
                self._go_idle_locked()

        current = (self.mqtt_enabled, self.mqtt_host, self.mqtt_port, self.mqtt_username,
                   self.mqtt_password, self.command_topic, self.state_topic,
                   self.ha_discovery, self.discovery_prefix)
        if previous != current:
            self._graceful_shutdown()
            self.on_enable()
        else:
            self._publish_state(force=True)

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update(self._snapshot())
        info.update({
            "mqtt_enabled":   self.mqtt_enabled,
            "mqtt_connected": self.mqtt_connected,
            "mqtt_host":      self.mqtt_host,
            "command_topic":  self.command_topic,
            "ha_discovery":   self.ha_discovery,
        })
        return info

    # ── State snapshot ──────────────────────────────────────────────────────────

    def _snapshot(self) -> Dict[str, Any]:
        with self.state_lock:
            remaining = self._remaining_locked()
            return {
                "phase": self.phase,
                "status": ("idle" if self.phase == PHASE_IDLE
                           else "running" if self.running else "paused"),
                "running": self.running,
                "remaining_seconds": int(round(remaining)),
                "remaining": _fmt_clock(remaining),
                "phase_total_seconds": int(self.phase_total),
                "elapsed_fraction": (0.0 if self.phase_total <= 0
                                     else max(0.0, min(1.0, 1.0 - remaining / self.phase_total))),
                "completed_sessions": self.completed_sessions,
                "cycle_position": self.cycle_position,
                "sessions_before_long_break": self.sessions_before_long_break,
                "work_minutes": self.work_minutes,
                "short_break_minutes": self.short_break_minutes,
                "long_break_minutes": self.long_break_minutes,
                "label": self.custom_label or self._phase_label(self.phase, self.running),
                "alerting": time.monotonic() < self.alert_until,
                "alert_color": self.alert_color,
            }

    def _phase_label(self, phase: str, running: bool) -> str:
        if phase == PHASE_IDLE:
            return self.idle_label
        if not running and self.paused_label:
            return self.paused_label
        return {
            PHASE_WORK: self.work_label,
            PHASE_SHORT_BREAK: self.short_break_label,
            PHASE_LONG_BREAK: self.long_break_label,
        }.get(phase, self.work_label)

    def _phase_color(self, phase: str) -> Tuple[int, int, int]:
        return {
            PHASE_WORK: self.work_color,
            PHASE_SHORT_BREAK: self.short_break_color,
            PHASE_LONG_BREAK: self.long_break_color,
        }.get(phase, self.idle_color)

    # ── Rendering ───────────────────────────────────────────────────────────────

    def _panel_size(self) -> Tuple[int, int]:
        dm = self.display_manager
        width = getattr(dm, "width", None) or getattr(getattr(dm, "matrix", None), "width", 128)
        height = getattr(dm, "height", None) or getattr(getattr(dm, "matrix", None), "height", 32)
        return int(width), int(height)

    def _frame(self, width: int, height: int):
        """Return (image, draw) to render into.

        Reuses the display manager's own buffer when it is at least panel-sized
        so anything drawn past the edge stays visible to the safety harness's
        bounds check, instead of being silently clipped by a fresh canvas.
        """
        canvas = getattr(self.display_manager, "image", None)
        if (not isinstance(canvas, Image.Image) or canvas.mode != "RGB"
                or canvas.size[0] < width or canvas.size[1] < height):
            canvas = Image.new("RGB", (width, height), (0, 0, 0))
            return canvas, ImageDraw.Draw(canvas)
        draw = getattr(self.display_manager, "draw", None)
        if draw is None:
            draw = ImageDraw.Draw(canvas)
        return canvas, draw

    def _ttf_path(self) -> Optional[str]:
        """Best available TrueType font path, or None to use the built-ins."""
        if self._ttf_path_resolved:
            return self._ttf_path_cache
        self._ttf_path_resolved = True
        self._ttf_path_cache = None

        configured = self.font_path.strip()
        if configured:
            candidates = [configured]
            if not os.path.isabs(configured):
                candidates.append(os.path.join(os.getcwd(), configured))
                root = Path(__file__).resolve().parent.parent.parent
                candidates.append(str(root / configured))
            for candidate in candidates:
                if os.path.exists(candidate):
                    self._ttf_path_cache = candidate
                    return self._ttf_path_cache
            self.logger.warning("Font not found: %s — falling back to the default font",
                                configured)

        # Borrow whatever TTF the core already loaded (usually PressStart2P).
        # PIL's built-in bitmap font also carries a `.path`, but it is a file
        # object rather than a filename — only take real paths.
        for attr in ("small_font", "regular_font", "extra_small_font"):
            path = getattr(getattr(self.display_manager, attr, None), "path", None)
            if isinstance(path, (str, bytes, os.PathLike)) and os.path.exists(path):
                self._ttf_path_cache = os.fspath(path)
                return self._ttf_path_cache
        return None

    def _font(self, size: int):
        """A TTF at `size` px, cached; None when no TTF is available."""
        size = max(5, int(size))
        if size in self._font_cache:
            return self._font_cache[size]
        path = self._ttf_path()
        font = None
        if path:
            try:
                font = ImageFont.truetype(path, size)
            except Exception as e:
                self.logger.debug("Could not load %s @ %dpx: %s", path, size, e)
        self._font_cache[size] = font
        return font

    def _fallback_font(self, max_height: int):
        dm = self.display_manager
        if max_height >= 8:
            return getattr(dm, "small_font", None) or getattr(dm, "regular_font", None)
        return getattr(dm, "extra_small_font", None) or getattr(dm, "small_font", None)

    @staticmethod
    def _measure(draw, text: str, font) -> Tuple[int, int, int, int]:
        """(width, height, x_offset, y_offset) of `text` in `font`."""
        try:
            x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
            return x1 - x0, y1 - y0, x0, y0
        except Exception:
            approx = 6 * len(text)
            return approx, 8, 0, 0

    def _fit_font(self, draw, text: str, max_w: int, max_h: int):
        """Largest available font that renders `text` inside (max_w, max_h)."""
        if self.font_size:
            return self._font(self.font_size) or self._fallback_font(max_h)
        if self._ttf_path() is None:
            font = self._fallback_font(max_h)
            if font is not None and max_h < 8:
                return getattr(self.display_manager, "extra_small_font", font)
            return font
        best = None
        low, high = 5, max(5, min(max_h, 96))
        while low <= high:
            mid = (low + high) // 2
            font = self._font(mid)
            if font is None:
                break
            tw, th, _, _ = self._measure(draw, text, font)
            if tw <= max_w and th <= max_h:
                best = font
                low = mid + 1
            else:
                high = mid - 1
        return best or self._font(5) or self._fallback_font(max_h)

    def _draw_in_box(self, draw, text: str, font, box: Tuple[int, int, int, int],
                     color: Tuple[int, int, int], align: str = "center") -> None:
        """Draw `text` centred (or left-aligned) inside box=(x, y, w, h).

        Text that still doesn't fit at the smallest font is truncated rather
        than allowed to spill past the panel edge.
        """
        if not text or font is None:
            return
        bx, by, bw, bh = box
        tw, th, ox, oy = self._measure(draw, text, font)
        while tw > bw and len(text) > 1:
            text = text[:-1]
            tw, th, ox, oy = self._measure(draw, text, font)
        if tw > bw:
            return
        x = bx if align == "left" else bx + max(0, (bw - tw) // 2)
        y = by + max(0, (bh - th) // 2)
        draw.text((x - ox, y - oy), text, font=font, fill=color)

    def _render(self, draw, width: int, height: int, snap: Dict[str, Any]) -> None:
        phase = snap["phase"]
        accent = self._phase_color(phase)
        if snap["status"] == "paused":
            accent = self.paused_color
        background = self.background_color
        text_color = accent if self.color_mode == "phase" else self.time_color

        # Completion flash: swap foreground and background twice a second.
        if snap["alerting"] and self.alert_flash:
            if int(time.monotonic() * 2) % 2 == 0:
                flash = snap["alert_color"] or accent
                background = flash
                text_color = self.background_color
                accent = self.background_color

        draw.rectangle([0, 0, width - 1, height - 1], fill=background)

        label = snap["label"]
        bar_h = self._bar_height(height) if self.show_progress_bar else 0
        dot_h = self._dot_size(height) if self.show_session_dots else 0

        if width >= 192 and height <= 48:
            self._render_wide(draw, width, height, snap, label, text_color, accent,
                              bar_h, dot_h)
        else:
            self._render_stacked(draw, width, height, snap, label, text_color, accent,
                                 bar_h, dot_h)

        if bar_h:
            self._draw_progress_bar(draw, 0, height - bar_h, width, bar_h,
                                    snap["elapsed_fraction"], accent)

    @staticmethod
    def _bar_height(height: int) -> int:
        return 3 if height >= 64 else 2

    @staticmethod
    def _dot_size(height: int) -> int:
        return 4 if height >= 64 else 3

    def _render_stacked(self, draw, width, height, snap, label, text_color, accent,
                        bar_h, dot_h) -> None:
        label_h = (10 if height >= 64 else 7) if (self.show_phase_label and label) else 0
        top = label_h + (1 if label_h else 0)
        bottom = height - bar_h - (dot_h + 1 if dot_h else 0)
        box_h = max(6, bottom - top)

        if label_h:
            label_font = self._fit_font(draw, label, width - 2, label_h)
            self._draw_in_box(draw, label, label_font, (1, 0, width - 2, label_h), accent)

        time_text = snap["remaining"]
        time_font = self._fit_font(draw, time_text, width - 4, box_h)
        self._draw_in_box(draw, time_text, time_font, (2, top, width - 4, box_h), text_color)

        if dot_h:
            self._draw_session_dots(draw, 0, bottom + 1, width, dot_h, snap, accent,
                                    align="center")

    def _render_wide(self, draw, width, height, snap, label, text_color, accent,
                     bar_h, dot_h) -> None:
        """Side-by-side layout for very wide panels (e.g. 256x32)."""
        left_w = max(40, int(width * 0.30))
        usable_h = height - bar_h
        label_h = (min(12, usable_h // 2) if (self.show_phase_label and label) else 0)

        if label_h:
            label_font = self._fit_font(draw, label, left_w - 4, label_h)
            self._draw_in_box(draw, label, label_font, (2, 1, left_w - 4, label_h),
                              accent, align="left")
        if dot_h:
            dots_y = (label_h + 3) if label_h else max(1, (usable_h - dot_h) // 2)
            dots_y = min(dots_y, max(0, usable_h - dot_h - 1))
            self._draw_session_dots(draw, 2, dots_y, left_w - 4, dot_h, snap, accent,
                                    align="left")

        time_text = snap["remaining"]
        time_box = (left_w + 2, 0, width - left_w - 4, max(6, usable_h - 1))
        time_font = self._fit_font(draw, time_text, time_box[2], time_box[3])
        self._draw_in_box(draw, time_text, time_font, time_box, text_color)

    def _draw_session_dots(self, draw, x: int, y: int, avail_w: int, size: int,
                           snap: Dict[str, Any], accent: Tuple[int, int, int],
                           align: str = "center") -> None:
        total = max(1, int(snap["sessions_before_long_break"]))
        filled = max(0, min(total, int(snap["cycle_position"])))
        gap = 1
        while total * (size + gap) - gap > avail_w and size > 1:
            size -= 1
        span = total * (size + gap) - gap
        if span > avail_w or size < 1:
            return
        start = x if align == "left" else x + max(0, (avail_w - span) // 2)
        dim = _dim(accent, 0.28)
        for index in range(total):
            left = start + index * (size + gap)
            draw.rectangle([left, y, left + size - 1, y + size - 1],
                           fill=accent if index < filled else dim)

    def _draw_progress_bar(self, draw, x: int, y: int, width: int, height: int,
                           fraction: float, accent: Tuple[int, int, int]) -> None:
        draw.rectangle([x, y, x + width - 1, y + height - 1], fill=_dim(accent, 0.22))
        filled = int(round(max(0.0, min(1.0, fraction)) * width))
        if filled > 0:
            draw.rectangle([x, y, x + filled - 1, y + height - 1], fill=accent)

    # ── Display pinning ─────────────────────────────────────────────────────────

    def _sync_pin(self) -> None:
        """Take over (or release) the panel to match the timer's state."""
        with self.state_lock:
            active = self.phase != PHASE_IDLE
            alerting = time.monotonic() < self.alert_until
        want = (self.pin_while_running and active) or alerting
        if want == self._pinned:
            return
        self._pinned = want
        request: Dict[str, Any] = {
            "request_id": str(uuid.uuid4()),
            "plugin_id":  self.plugin_id,
            "action":     "start" if want else "stop",
            "timestamp":  time.time(),
        }
        if want:
            request.update({"mode": "pomodoro", "duration": None, "pinned": True})
        try:
            self.cache_manager.set("display_on_demand_request", request)
        except Exception as e:
            self.logger.debug("On-demand display request failed: %s", e)

    def _timer_loop(self) -> None:
        while not self.timer_stop_event.wait(0.25):
            try:
                self._tick()
                # Idempotent: releases the panel once the alert window closes
                # or the pin setting is turned off.
                self._sync_pin()
            except Exception as e:
                self.logger.error("Timer loop error: %s", e, exc_info=True)
        self.logger.info("Timer loop stopped")

    # ── MQTT publishing ─────────────────────────────────────────────────────────

    def _publish(self, topic: str, payload: str, retain: bool = True) -> None:
        if not self.mqtt_client or not self.mqtt_connected:
            return
        try:
            self.mqtt_client.publish(topic, payload, retain=retain)
        except Exception as e:
            self.logger.debug("Publish to %s failed: %s", topic, e)

    def _publish_availability(self, online: bool) -> None:
        if not self.mqtt_client:
            return
        try:
            self.mqtt_client.publish(self.availability_topic,
                                     "online" if online else "offline", retain=True)
        except Exception as e:
            self.logger.debug("Availability publish failed: %s", e)

    def _publish_event(self, event: Dict[str, Any]) -> None:
        self.logger.info("Pomodoro event: %s", event.get("event_type"))
        self._publish(self.event_topic, json.dumps(event), retain=False)

    def _publish_state(self, force: bool = False) -> None:
        """Publish the full state, throttled to publish_interval while ticking."""
        if not self.mqtt_client or not self.mqtt_connected:
            return
        now = time.monotonic()
        snap = self._snapshot()
        key = (snap["phase"], snap["status"], snap["remaining"],
               snap["completed_sessions"], snap["cycle_position"])
        if not force:
            if key == self._last_published_key:
                return
            if now - self._last_publish < self.publish_interval:
                return
        self._last_publish = now
        self._last_published_key = key

        self._publish(self.state_topic, "ON" if snap["phase"] != PHASE_IDLE else "OFF")
        self._publish(self.status_topic, snap["status"])
        self._publish(self.phase_topic, snap["phase"])
        self._publish(self.remaining_topic, snap["remaining"])
        self._publish(self.remaining_secs_topic, str(snap["remaining_seconds"]))
        self._publish(self.session_topic, str(snap["completed_sessions"]))
        self._publish(self.attributes_topic, json.dumps({
            k: v for k, v in snap.items() if k != "alert_color"
        }))
        for field, *_ in _NUMBER_FIELDS:
            self._publish(self.number_state_topics[field], str(getattr(self, field)))

    # ── HA MQTT auto-discovery ──────────────────────────────────────────────────

    def _discovery_uid(self) -> str:
        return f"ledmatrix_pomodoro_{self.plugin_id}"

    def _discovery_device(self) -> Dict[str, Any]:
        return {
            "identifiers":  [self._discovery_uid()],
            "name":         self.device_name,
            "model":        "Pomodoro Timer",
            "manufacturer": "LEDMatrix",
            "sw_version":   _PLUGIN_VERSION,
        }

    def _discovery_entities(self) -> List[Tuple[str, Dict[str, Any]]]:
        """(discovery topic, config payload) for every entity we announce."""
        uid = self._discovery_uid()
        device = self._discovery_device()
        avail = [{"topic": self.availability_topic,
                  "payload_available": "online",
                  "payload_not_available": "offline"}]
        common = {"availability": avail, "device": device}
        entities: List[Tuple[str, Dict[str, Any]]] = []

        entities.append((f"switch/{uid}/config", {
            "name": "Timer", "unique_id": f"{uid}_switch",
            "command_topic": self.command_topic, "state_topic": self.state_topic,
            "payload_on": "START", "payload_off": "STOP",
            "state_on": "ON", "state_off": "OFF",
            "json_attributes_topic": self.attributes_topic,
            "icon": "mdi:timer-play-outline", **common,
        }))

        for key, name, payload, icon in _BUTTONS:
            entities.append((f"button/{uid}_{key}/config", {
                "name": name, "unique_id": f"{uid}_{key}",
                "command_topic": self.command_topic, "payload_press": payload,
                "icon": icon, **common,
            }))

        for field, name, low, high, step, icon in _NUMBER_FIELDS:
            entities.append((f"number/{uid}_{field}/config", {
                "name": name, "unique_id": f"{uid}_{field}",
                "command_topic": f"{self.topic_base}/{field}/set",
                "state_topic": self.number_state_topics[field],
                "min": low, "max": high, "step": step, "mode": "box",
                "unit_of_measurement": None if field == "sessions_before_long_break" else "min",
                "icon": icon, "entity_category": "config", **common,
            }))

        entities.append((f"sensor/{uid}_phase/config", {
            "name": "Phase", "unique_id": f"{uid}_phase",
            "state_topic": self.phase_topic, "icon": "mdi:progress-clock", **common,
        }))
        entities.append((f"sensor/{uid}_status/config", {
            "name": "Status", "unique_id": f"{uid}_status",
            "state_topic": self.status_topic, "icon": "mdi:play-pause", **common,
        }))
        entities.append((f"sensor/{uid}_remaining/config", {
            "name": "Time Remaining", "unique_id": f"{uid}_remaining",
            "state_topic": self.remaining_topic, "icon": "mdi:timer-sand", **common,
        }))
        entities.append((f"sensor/{uid}_remaining_seconds/config", {
            "name": "Seconds Remaining", "unique_id": f"{uid}_remaining_seconds",
            "state_topic": self.remaining_secs_topic,
            "unit_of_measurement": "s", "device_class": "duration",
            "state_class": "measurement", "icon": "mdi:timer-outline", **common,
        }))
        entities.append((f"sensor/{uid}_sessions/config", {
            "name": "Completed Sessions", "unique_id": f"{uid}_sessions",
            "state_topic": self.session_topic, "state_class": "total_increasing",
            "icon": "mdi:check-circle-outline", **common,
        }))
        entities.append((f"event/{uid}_event/config", {
            "name": "Timer Event", "unique_id": f"{uid}_event",
            "state_topic": self.event_topic, "event_types": _EVENT_TYPES,
            "icon": "mdi:bell-ring-outline", **common,
        }))
        entities.append((f"binary_sensor/{uid}_connected/config", {
            "name": "MQTT Connected", "unique_id": f"{uid}_connected",
            "state_topic": self.availability_topic,
            "payload_on": "online", "payload_off": "offline",
            "device_class": "connectivity", "icon": "mdi:wifi",
            "device": device,
        }))
        return entities

    def _publish_discovery(self) -> None:
        if not self.ha_discovery or not self.mqtt_client:
            return
        for suffix, payload in self._discovery_entities():
            self._publish(f"{self.discovery_prefix}/{suffix}", json.dumps(payload))
        self.logger.info("Published HA MQTT discovery — device: %s", self.device_name)

    def _remove_discovery(self) -> None:
        if not self.ha_discovery or not self.mqtt_client:
            return
        for suffix, _ in self._discovery_entities():
            self._publish(f"{self.discovery_prefix}/{suffix}", "")

    # ── MQTT callbacks ──────────────────────────────────────────────────────────

    def _on_mqtt_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        if rc != 0:
            self.mqtt_connecting = False
            self.mqtt_connected = False
            self.logger.error("MQTT connect failed rc=%s", rc)
            return
        self.mqtt_connected = True
        self.mqtt_connecting = False
        self.mqtt_reconnect_delay = 1.0
        client.subscribe(self.command_topic, qos=1)
        for topic in self.number_set_topics:
            client.subscribe(topic, qos=1)
        self._publish_availability(True)
        self._publish_discovery()
        self._publish_state(force=True)
        self.logger.info("MQTT connected — subscribed to %s", self.command_topic)

    def _on_mqtt_disconnect(self, client, userdata, rc):  # pylint: disable=unused-argument
        self.mqtt_connected = False
        self.mqtt_connecting = False
        if rc != 0:
            self.logger.warning("MQTT disconnected unexpectedly rc=%s", rc)

    def _on_mqtt_message(self, client, userdata, msg):  # pylint: disable=unused-argument
        try:
            field = self.number_set_topics.get(msg.topic)
            if field:
                try:
                    raw = msg.payload.decode("utf-8").strip()
                except (UnicodeDecodeError, AttributeError):
                    return
                with self.state_lock:
                    changed = self._set_number_locked(field, raw)
                if changed:
                    self.logger.info("%s set to %s via MQTT", field, getattr(self, field))
                self._publish_state(force=True)
                return

            command, payload = self._parse_command(msg.payload)
            if command is None:
                self.logger.debug("Ignoring unrecognised payload on %s", msg.topic)
                return
            self._apply_command(command, payload if isinstance(payload, dict) else {})
        except Exception as e:
            self.logger.error("Error handling MQTT message: %s", e, exc_info=True)

    # ── MQTT connect / loop ─────────────────────────────────────────────────────

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
            self.mqtt_client.will_set(self.availability_topic, payload="offline",
                                      qos=1, retain=True)
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
                        # Give the broker a moment to answer CONNACK before the
                        # next pass, so we never open a second connection.
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
                self.mqtt_connected = False
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
        self.timer_stop_event.set()
        if self.timer_thread and self.timer_thread.is_alive():
            self.timer_thread.join(timeout=2.0)
        self.timer_thread = None

        if self.mqtt_thread and self.mqtt_thread.is_alive():
            self.mqtt_stop_event.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
            self.mqtt_thread.join(timeout=5.0)
        self.mqtt_thread = None
        self.mqtt_connected = False
        self.mqtt_connecting = False
