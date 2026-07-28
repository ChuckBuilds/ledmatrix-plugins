#!/usr/bin/env python3
"""
Pomodoro Timer plugin tests.

Self-contained: the LEDMatrix core is stubbed out, so this runs from a plain
checkout of the plugins repo with only Pillow installed.

    python -m pytest plugins/pomodoro-timer/test_pomodoro_timer.py
    python plugins/pomodoro-timer/test_pomodoro_timer.py     # no pytest needed
"""

import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PLUGIN_DIR = Path(__file__).resolve().parent


# ── Core stubs ──────────────────────────────────────────────────────────────

class _StubBasePlugin:
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        self.plugin_id = plugin_id
        self.config = config
        self.display_manager = display_manager
        self.cache_manager = cache_manager
        self.plugin_manager = plugin_manager
        self.enabled = True
        self.global_config = {}
        self.logger = logging.getLogger(plugin_id)

    def validate_config(self):
        return True

    def get_info(self):
        return {"plugin_id": self.plugin_id}

    def on_enable(self):
        self.enabled = True

    def on_disable(self):
        self.enabled = False

    def on_config_change(self, new_config):
        self.config = new_config


def _install_core_stub():
    for name in ("src", "src.plugin_system", "src.plugin_system.base_plugin"):
        sys.modules.pop(name, None)
    src = types.ModuleType("src")
    plugin_system = types.ModuleType("src.plugin_system")
    base_plugin = types.ModuleType("src.plugin_system.base_plugin")
    base_plugin.BasePlugin = _StubBasePlugin
    plugin_system.base_plugin = base_plugin
    src.plugin_system = plugin_system
    sys.modules["src"] = src
    sys.modules["src.plugin_system"] = plugin_system
    sys.modules["src.plugin_system.base_plugin"] = base_plugin


class _Matrix:
    def __init__(self, width, height):
        self.width = width
        self.height = height


class _DisplayManager:
    def __init__(self, width=128, height=32):
        self.width = width
        self.height = height
        self.matrix = _Matrix(width, height)
        self.image = Image.new("RGB", (width, height), (0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)
        self.small_font = ImageFont.load_default()
        self.regular_font = self.small_font
        self.extra_small_font = self.small_font
        self.updates = 0

    def update_display(self):
        self.updates += 1

    def draw_text(self, text, x=None, y=None, color=(255, 255, 255), **kwargs):
        self.draw.text((x or 0, y or 0), text, fill=color, font=self.small_font)


class _CacheManager:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class _PluginManager:
    font_manager = None
    config_manager = None


_MISSING = object()
_STUBBED_MODULES = ("src", "src.plugin_system", "src.plugin_system.base_plugin")


def _load_module():
    """Import manager.py against the stubbed core, then put sys.modules back.

    `manager.py` binds BasePlugin at class-creation time, so the stub only has
    to be in place for the exec. Restoring afterwards keeps our fake `src` from
    shadowing the real core for any other plugin's tests in the same session.
    """
    originals = {name: sys.modules.get(name, _MISSING) for name in _STUBBED_MODULES}
    try:
        _install_core_stub()
        spec = importlib.util.spec_from_file_location(
            "pomodoro_timer_manager", PLUGIN_DIR / "manager.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


MODULE = _load_module()
DEFAULTS = {
    k: v.get("default")
    for k, v in json.loads((PLUGIN_DIR / "config_schema.json").read_text())["properties"].items()
    if "default" in v
}


def make_plugin(width=128, height=32, **overrides):
    config = {**DEFAULTS, "mqtt_enabled": False, **overrides}
    return MODULE.PomodoroTimerPlugin(
        "pomodoro-timer", config, _DisplayManager(width, height),
        _CacheManager(), _PluginManager())


# ── Tests ───────────────────────────────────────────────────────────────────

def test_defaults_start_idle():
    p = make_plugin()
    snap = p._snapshot()
    assert snap["phase"] == "idle"
    assert snap["status"] == "idle"
    assert snap["remaining"] == "25:00"
    assert snap["elapsed_fraction"] == 0.0


def test_clock_formatting():
    assert MODULE._fmt_clock(0) == "00:00"
    assert MODULE._fmt_clock(59.2) == "01:00"
    assert MODULE._fmt_clock(1500) == "25:00"
    assert MODULE._fmt_clock(-5) == "00:00"


def test_start_pause_resume():
    p = make_plugin()
    p._apply_command("START", {})
    assert p._snapshot()["status"] == "running"
    assert p._snapshot()["phase"] == "work"

    p._apply_command("PAUSE", {})
    snap = p._snapshot()
    assert snap["status"] == "paused"
    assert snap["label"] == "PAUSED"

    p._apply_command("RESUME", {})
    assert p._snapshot()["status"] == "running"

    p._apply_command("TOGGLE", {})
    assert p._snapshot()["status"] == "paused"


def test_stop_keeps_counters_reset_clears_them():
    p = make_plugin()
    p._apply_command("START", {})
    with p.state_lock:
        p.deadline = 0.0          # force the phase to be due
    p._tick()                     # work completes -> break
    assert p._snapshot()["completed_sessions"] == 1

    p._apply_command("STOP", {})
    assert p._snapshot()["phase"] == "idle"
    assert p._snapshot()["completed_sessions"] == 1

    p._apply_command("RESET", {})
    assert p._snapshot()["completed_sessions"] == 0
    assert p._snapshot()["cycle_position"] == 0


def test_full_cycle_reaches_long_break_and_wraps():
    p = make_plugin(auto_start_breaks=True, auto_start_work=True)
    p._apply_command("START", {})
    seen = []
    for _ in range(8):
        with p.state_lock:
            p.deadline = 0.0
        p._tick()
        seen.append(p._snapshot()["phase"])
    assert seen == ["short_break", "work", "short_break", "work",
                    "short_break", "work", "long_break", "work"]
    assert p._snapshot()["completed_sessions"] == 4
    # The long break closed the set, so the dots start over.
    assert p._snapshot()["cycle_position"] == 0


def test_break_waits_when_auto_start_is_off():
    p = make_plugin(auto_start_breaks=False)
    p._apply_command("START", {})
    with p.state_lock:
        p.deadline = 0.0
    p._tick()
    snap = p._snapshot()
    assert snap["phase"] == "short_break"
    assert snap["status"] == "paused"
    assert snap["remaining"] == "05:00"


def test_skipped_work_does_not_earn_a_long_break():
    p = make_plugin()
    with p.state_lock:
        p.cycle_position = 3       # one work session away from the long break
    p._apply_command("WORK", {})
    p._apply_command("SKIP", {})
    snap = p._snapshot()
    assert snap["phase"] == "short_break"
    assert snap["completed_sessions"] == 0
    assert snap["cycle_position"] == 3


def test_json_command_with_custom_duration_and_label():
    p = make_plugin()
    command, payload = p._parse_command(
        b'{"command": "start", "phase": "work", "duration_minutes": 50, "label": "DEEP"}')
    p._apply_command(command, payload)
    snap = p._snapshot()
    assert snap["phase"] == "work"
    assert snap["remaining"] == "50:00"
    assert snap["label"] == "DEEP"
    # The custom duration is per-session; the configured length is untouched.
    assert p.work_minutes == 25


def test_settings_only_payload_updates_durations():
    p = make_plugin()
    command, payload = p._parse_command(b'{"work_minutes": 45, "short_break_minutes": 10}')
    assert command == "SET"
    p._apply_command(command, payload)
    assert p.work_minutes == 45
    assert p.short_break_minutes == 10
    # Idle screen follows the new work length.
    assert p._snapshot()["remaining"] == "45:00"


def test_number_values_are_clamped():
    p = make_plugin()
    with p.state_lock:
        p._set_number_locked("work_minutes", "9999")
        p._set_number_locked("sessions_before_long_break", 0)
    assert p.work_minutes == 180
    assert p.sessions_before_long_break == 1


def test_unrecognised_payloads_are_ignored():
    p = make_plugin()
    for raw in (b"", b"gibberish-command", b'{"nothing": 1}', b"\xff\xfe"):
        command, payload = p._parse_command(raw)
        if command is not None:
            p._apply_command(command, payload)
    assert p._snapshot()["phase"] == "idle"


def test_pin_request_follows_the_timer():
    p = make_plugin(pin_while_running=True)
    p._apply_command("START", {})
    request = p.cache_manager.get("display_on_demand_request")
    assert request["action"] == "start" and request["pinned"] is True

    p._apply_command("STOP", {})
    assert p.cache_manager.get("display_on_demand_request")["action"] == "stop"


def test_pin_is_not_requested_when_disabled():
    p = make_plugin(pin_while_running=False, alert_seconds=0)
    p._apply_command("START", {})
    assert p.cache_manager.get("display_on_demand_request") is None


def test_display_renders_every_panel_size():
    for width, height in ((64, 32), (128, 32), (128, 64), (256, 32)):
        p = make_plugin(width, height)
        p._apply_command("START", {})
        assert p.display() is True
        assert p.display_manager.updates >= 1
        assert p.display_manager.image.size == (width, height)
        assert p.display_manager.image.getbbox() is not None, "rendered a blank frame"


def _ring_path(width, height):
    return ([(x, 0) for x in range(width)]
            + [(width - 1, y) for y in range(1, height)]
            + [(x, height - 1) for x in range(width - 2, -1, -1)]
            + [(0, y) for y in range(height - 2, 0, -1)])


def _lit_ring_fraction(plugin):
    width, height = plugin.display_manager.image.size
    pixels = plugin.display_manager.image.convert("RGB").load()
    path = _ring_path(width, height)
    lit = sum(1 for point in path if sum(pixels[point]) > 200)
    return lit / len(path)


def test_burndown_ring_drains_with_the_phase():
    for elapsed in (0.0, 0.25, 0.5, 0.75):
        p = make_plugin(128, 32, progress_style="perimeter")
        p._apply_command("START", {})
        with p.state_lock:
            p.deadline -= p.phase_total * elapsed
        p.display()
        got = _lit_ring_fraction(p)
        assert abs(got - (1 - elapsed)) < 0.02, \
            f"{elapsed:.0%} elapsed should leave {1 - elapsed:.0%} of the ring lit, got {got:.0%}"


def test_seven_segment_digits_keep_a_readable_shape():
    """A digit that gets too narrow for its height stops reading as a digit."""
    for width, height in ((64, 32), (128, 32), (128, 64), (256, 32)):
        p = make_plugin(width, height)
        for text in ("25:00", "05:00", "180:00"):
            metrics = p._seven_segment_metrics(text, width - 6, height - 10)
            if metrics is None:
                continue
            h, digit_w, stroke, _gap, _colon_w, total = metrics
            assert digit_w >= round(h * 0.64), f"{width}x{height} {text}: digit too narrow"
            assert digit_w >= 2 * stroke + 1, f"{width}x{height} {text}: segments would fuse"
            assert total <= width - 6, f"{width}x{height} {text}: digits overrun the box"


def test_seven_segment_gives_up_when_there_is_no_room():
    p = make_plugin()
    assert p._seven_segment_metrics("25:00", 10, 4) is None
    # ...and display() still renders, having fallen back to the pixel font.
    tiny = make_plugin(64, 16)
    tiny._apply_command("START", {})
    assert tiny.display() is True
    assert tiny.display_manager.image.getbbox() is not None


def test_every_indicator_and_digit_style_renders():
    for style in ("perimeter", "bar", "segments", "none"):
        for digits in ("seven_segment", "pixel"):
            p = make_plugin(128, 32, progress_style=style, digit_style=digits)
            p._apply_command("START", {})
            assert p.display() is True, f"{style}/{digits} failed to render"
            assert p.display_manager.image.getbbox() is not None


def test_unknown_styles_fall_back_to_the_defaults():
    p = make_plugin(progress_style="disco", digit_style="gothic")
    assert p.progress_style == "perimeter"
    assert p.digit_style == "seven_segment"


def test_rendering_never_rewrites_the_configured_style():
    """A panel too narrow for blocks falls back per-frame, not permanently."""
    p = make_plugin(24, 16, progress_style="segments")
    p._apply_command("START", {})
    p.display()
    assert p.progress_style == "segments", "the render path overwrote the user's setting"


def test_changing_the_discovery_prefix_clears_the_old_configs():
    p = make_plugin(command_topic="ledmatrix/pomodoro/set")
    client = _wire_client(p)
    p.on_config_change({**DEFAULTS, "mqtt_enabled": False, "discovery_prefix": "ha2"})
    cleared = [t for t, payload in client.published
               if t.startswith("homeassistant/") and payload == ""]
    assert len(cleared) == 17, "old prefix's retained configs would orphan HA entities"


def test_renaming_the_command_topic_clears_the_old_state_topics():
    p = make_plugin(command_topic="ledmatrix/pomodoro/set")
    client = _wire_client(p)
    old_state, old_avail = p.state_topic, p.availability_topic
    p.on_config_change({**DEFAULTS, "mqtt_enabled": False,
                        "command_topic": "desk/focus/set"})
    cleared = {t for t, payload in client.published if payload == ""}
    assert old_state in cleared and old_avail in cleared
    # The discovery configs are keyed on the prefix, so they are republished in
    # place rather than orphaned — nothing under homeassistant/ gets cleared.
    assert not any(t.startswith("homeassistant/") for t in cleared)
    assert p.topic_base == "desk/focus"


def test_discovery_payloads_are_valid_json_and_unique():
    p = make_plugin()
    entities = p._discovery_entities()
    assert len(entities) == 17
    uids = set()
    for topic, payload in entities:
        assert topic.count("/") == 2 and topic.endswith("/config")
        json.dumps(payload)
        assert payload["unique_id"] not in uids
        uids.add(payload["unique_id"])
    topics = [t for t, _ in entities]
    assert any(t.startswith("switch/") for t in topics)
    assert sum(t.startswith("button/") for t in topics) == 5
    assert sum(t.startswith("number/") for t in topics) == 4


class _RecordingClient:
    """Stands in for paho's client so the MQTT plumbing can be exercised
    without a broker (an end-to-end run against mosquitto is covered
    separately)."""

    def __init__(self):
        self.subscriptions = []
        self.published = []

    def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, retain=False, qos=0):
        self.published.append((topic, payload))


class _Message:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else payload.encode()


def _wire_client(plugin):
    client = _RecordingClient()
    plugin.mqtt_client = client
    plugin.mqtt_connected = True
    return client


def test_connect_subscribes_to_command_and_number_topics():
    p = make_plugin()
    client = _RecordingClient()
    p.mqtt_client = client
    p._on_mqtt_connect(client, None, {}, 0)
    assert p.mqtt_connected is True
    assert p.command_topic in client.subscriptions
    for topic in p.number_set_topics:
        assert topic in client.subscriptions
    published = {t for t, _ in client.published}
    assert any(t.startswith("homeassistant/") for t in published)
    assert p.state_topic in published


def test_incoming_messages_drive_the_timer():
    p = make_plugin()
    client = _wire_client(p)

    p._on_mqtt_message(client, None, _Message(p.command_topic, "START"))
    assert p._snapshot()["status"] == "running"

    p._on_mqtt_message(client, None, _Message(p.command_topic, "PAUSE"))
    assert p._snapshot()["status"] == "paused"

    p._on_mqtt_message(client, None, _Message(f"{p.topic_base}/work_minutes/set", "45"))
    assert p.work_minutes == 45

    published = dict(client.published)
    assert published[p.state_topic] == "ON"
    assert published[p.status_topic] == "paused"
    assert published[p.number_state_topics["work_minutes"]] == "45"


def test_a_failed_connection_does_not_look_connected():
    p = make_plugin()
    client = _RecordingClient()
    p.mqtt_client = client
    p._on_mqtt_connect(client, None, {}, 5)   # 5 = not authorised
    assert p.mqtt_connected is False
    assert client.subscriptions == []


def test_start_on_a_running_timer_emits_no_event():
    p = make_plugin()
    client = _wire_client(p)
    p._apply_command("START", {})
    before = [t for t, _ in client.published if t == p.event_topic]

    p._apply_command("START", {})   # e.g. the HA Start button pressed again
    after = [t for t, _ in client.published if t == p.event_topic]
    assert after == before, "a redundant START re-fired the started event"

    # Settings sent alongside a redundant START still apply and get published.
    p._apply_command("START", {"work_minutes": 30})
    assert p.work_minutes == 30
    assert dict(client.published)[p.number_state_topics["work_minutes"]] == "30"

    # A resume, by contrast, is a real transition and does emit.
    p._apply_command("PAUSE", {})
    p._apply_command("START", {})
    assert p._snapshot()["status"] == "running"
    assert len([t for t, _ in client.published if t == p.event_topic]) > len(after)


class _StubPahoClient:
    """Records the teardown calls made against a live client."""

    def __init__(self):
        self.loop_stopped = 0
        self.disconnected = 0
        self.published = []

    def loop_stop(self):
        self.loop_stopped += 1

    def disconnect(self):
        self.disconnected += 1

    def publish(self, topic, payload, retain=False, qos=0):
        self.published.append((topic, payload))


def test_teardown_releases_the_client_and_is_idempotent():
    p = make_plugin()
    client = _StubPahoClient()
    p.mqtt_client = client
    p.mqtt_connected = True
    p.mqtt_connecting = True

    p._teardown_client()
    assert p.mqtt_client is None
    assert p.mqtt_connected is False and p.mqtt_connecting is False
    assert client.loop_stopped == 1 and client.disconnected == 1

    p._teardown_client()   # no client left — must not raise or re-call
    assert client.loop_stopped == 1


def test_teardown_survives_a_client_that_raises():
    p = make_plugin()

    class _Angry(_StubPahoClient):
        def loop_stop(self):
            raise RuntimeError("loop already stopped")

        def disconnect(self):
            raise RuntimeError("socket gone")

    p.mqtt_client = _Angry()
    p._teardown_client()          # must swallow both failures
    assert p.mqtt_client is None


def test_shutdown_releases_a_client_left_by_a_dead_thread():
    p = make_plugin()
    client = _StubPahoClient()
    p.mqtt_client = client        # loop exited (or never ran) with a live client
    p.mqtt_thread = None

    p._graceful_shutdown()
    assert p.mqtt_stop_event.is_set()
    assert p.mqtt_client is None
    assert client.disconnected >= 1
    # HA must be told we're gone before the socket closes, or the device sits
    # "online" until the keepalive lapses.
    assert (p.availability_topic, "offline") in client.published


def test_pin_state_is_restored_when_the_request_fails():
    p = make_plugin()

    def _boom(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    p.cache_manager.set = _boom
    p._apply_command("START", {})
    assert p._pinned is False, "a failed request must stay retryable"


def test_derived_topics_track_the_command_topic():
    p = make_plugin(command_topic="home/focus/set")
    assert p.topic_base == "home/focus"
    assert p.remaining_topic == "home/focus/remaining"
    assert "home/focus/work_minutes/set" in p.number_set_topics
    assert p.number_state_topics["work_minutes"] == "home/focus/work_minutes"


def test_validate_config_rejects_bad_values():
    assert make_plugin().validate_config() is True
    assert make_plugin(color_mode="rainbow").validate_config() is False
    assert make_plugin(mqtt_port=0).validate_config() is False


def test_config_change_keeps_a_running_session():
    p = make_plugin()
    p._apply_command("START", {})
    before = p._snapshot()["remaining_seconds"]
    p.on_config_change({**DEFAULTS, "mqtt_enabled": False, "work_color": [1, 2, 3]})
    snap = p._snapshot()
    assert snap["phase"] == "work"
    assert abs(snap["remaining_seconds"] - before) <= 1
    assert p.work_color == (1, 2, 3)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"[ok]   {name}")
        except Exception as exc:  # noqa: BLE001 - report and keep going
            failures += 1
            print(f"[FAIL] {name}: {exc!r}")
    print(f"\n{'FAILED' if failures else 'PASSED'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
