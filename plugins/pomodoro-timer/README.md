# Pomodoro Timer

A focus/break timer for your LED matrix, driven over MQTT. Set the work and
break lengths however you like, then start, pause, skip, or reset the timer from
Home Assistant, a dashboard button, a voice assistant, or a one-line
`mosquitto_pub`. The matrix shows the phase you're in, the countdown, how far
through the phase you are, and how many sessions you've banked toward the long
break.

Home Assistant MQTT auto-discovery is on by default, so the whole timer —
switch, buttons, duration boxes, and sensors — appears as a device with no YAML.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [What's On Screen](#whats-on-screen)
3. [Quick Start](#quick-start)
4. [Plugin Configuration](#plugin-configuration)
5. [MQTT Reference](#mqtt-reference)
   - [Commands](#commands)
   - [JSON Payloads](#json-payloads)
   - [Published Topics](#published-topics)
6. [Home Assistant Setup](#home-assistant-setup)
   - [Auto-Discovery](#auto-discovery-recommended)
   - [What You Get](#what-you-get)
   - [Automation Examples](#automation-examples)
   - [Manual YAML](#manual-yaml-if-you-turn-discovery-off)
7. [Testing Without Home Assistant](#testing-without-home-assistant)
8. [Troubleshooting](#troubleshooting)

---

## How It Works

```text
Home Assistant ──MQTT──► ledmatrix/pomodoro/set    ──► timer starts / pauses / skips
LED matrix     ──MQTT──► ledmatrix/pomodoro/state  ──► HA switch stays in sync
LED matrix     ──MQTT──► ledmatrix/pomodoro/event  ──► "work_complete" fires your automations
```

The timer is a classic Pomodoro cycle:

```text
work ─► short break ─► work ─► short break ─► work ─► short break ─► work ─► LONG break ─► …
                                                       (4 sessions per set, configurable)
```

It runs in its own thread, so it keeps counting and keeps publishing state
whether or not it's the screen currently on the panel. By default it **holds the
display** for as long as a session is active, then hands the panel back to your
normal rotation when the timer goes idle.

---

## What's On Screen

```text
▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▔▔▔▔▔▔▔▔   ← burndown ring: lit = time left in the phase
▏  Editing specs      ●●◉○    ▕   ← task (or phase label), and one pip per session
▏   ┌─┐ ┌─┐ ┌─┐ ┌─┐           ▕
▏   │17│:│42│                 ▕   ← countdown in seven-segment digits
▏   └─┘ └─┘                   ▕
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
```

The countdown is drawn as **seven-segment digits**, sized to whatever space the
panel has left rather than picked from a font, with a heavy stroke so it stays
readable from across a room. The phase label is held back a little so the eye
lands on the time first.

If you want the full clock-radio look, **Show Unlit Segments** faintly lights the
dark segments the way real hardware does. It's off by default because it costs
real legibility — every digit gains a faint `8` behind it, and a `15` starts to
read as an `85`.

The **task label** is whatever you're working on. Set it from Home Assistant (or
any MQTT client) and it takes the label row — the phase is already carried by the
colour, so it doesn't need the words too. Leave it empty and the phase name shows
instead.

The **burndown ring** is the default indicator: the whole border is lit when a
phase starts and drains clockwise from the top-left, with a brighter head pixel
leading the way. It costs no interior space, which is what lets the digits be as
large as they are. If you'd rather have the border back, `bar` and `segments` put
the indicator along the bottom edge instead, and `none` hides it.

Each element can be turned off, and each color can be changed. The layout adapts
to the panel: stacked on 64×32, 128×32, and 128×64; label and dots beside a large
countdown on long panels like 256×32. On short panels the session dots tuck in
beside the label rather than taking a row of their own, so the digits get the
height instead.

| Phase | Default color |
|---|---|
| Work | red |
| Short break | green |
| Long break | blue |
| Paused | amber |
| Idle | grey |

When a phase ends the panel flashes for a few seconds so you notice even if you
weren't looking — that alert length is configurable, and can be turned off.

---

## Quick Start

1. **Install the plugin** from the LEDMatrix plugin store and open its
   configuration tab.
2. **Set your MQTT broker host** (typically your Home Assistant IP or
   `homeassistant.local`).
3. **Set your durations** — work, short break, long break, and sessions per set.
4. **Save.** The plugin connects, subscribes, and announces itself to Home
   Assistant.
5. **Test it:**

```bash
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set -m START
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set -m PAUSE
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set -m RESET
```

Not using MQTT at all? Turn **Enable MQTT Control** off and turn **Start Timer
When Plugin Is Enabled** on — the timer then runs the cycle on its own from the
durations you configured.

---

## Plugin Configuration

### Timer

| Field | Default | Description |
|---|---|---|
| **Work Session (minutes)** | `25` | Length of a focus session. Also settable live from Home Assistant. |
| **Short Break (minutes)** | `5` | Break after each work session. |
| **Long Break (minutes)** | `15` | Break after a full set of work sessions. |
| **Sessions Before Long Break** | `4` | How many work sessions make a set — this is the number of dots on screen. |
| **Auto-Start Breaks** | `true` | Roll straight into the break when work ends. Off makes the break wait for a Start/Resume. |
| **Auto-Start Next Work Session** | `false` | Roll straight back into work when a break ends. Off by default so you decide when to go again. |
| **Start Timer When Plugin Is Enabled** | `false` | Begin a work session as soon as the plugin loads. Handy without MQTT. |

### MQTT

| Field | Default | Description |
|---|---|---|
| **Enable MQTT Control** | `true` | Connect to a broker so the timer can be driven remotely. |
| **Broker Address** | `localhost` | IP or hostname of your MQTT broker. |
| **Broker Port** | `1883` | Use 8883 for TLS. |
| **Username / Password** | *(blank)* | Leave blank for an anonymous broker. |
| **Command Topic** | `ledmatrix/pomodoro/set` | Everything the plugin publishes is derived from this topic's base. |
| **State Topic** | `ledmatrix/pomodoro/state` | `ON` while a session is active, `OFF` when idle. |
| **Enable Home Assistant Auto-Discovery** | `true` | Announce the device to HA over MQTT. |
| **HA Discovery Prefix** | `homeassistant` | Only change this if you changed it in HA. |
| **Device Name in Home Assistant** | `LED Matrix — Pomodoro` | How the device is labelled in HA. |
| **State Publish Interval (seconds)** | `1` | How often the countdown is published while running. Raise it to cut broker traffic — state *changes* are always published immediately. |

### Appearance

| Field | Default | Description |
|---|---|---|
| **Countdown Color** | `phase` | `phase` colors the countdown by what's running; `fixed` always uses the Countdown Text Color. |
| **Colour Theme** | `classic` | `classic` uses the individual phase colours below. `calm` overrides them with a softer palette — warm terracotta, sage, soft indigo. |
| **Work / Short Break / Long Break Color** | red / green / blue | Phase colors. |
| **Idle / Paused Color** | grey / amber | Used when nothing is running and when paused. |
| **How Paused Looks** | `amber` | `amber` switches the countdown to the Paused Colour. `desaturate` keeps the phase's own hue but drains it, so a held timer reads as halted without changing which phase you're in. |
| **Countdown Text Color** | white | Only used when Countdown Color is `fixed`. |
| **Background Color** | black | Panel background. |
| **Countdown Digits** | `seven_segment` | `seven_segment` draws clock-radio style segments sized to the panel. `pixel` uses the display's pixel font. |
| **Show Unlit Segments** | `false` | Faintly light the unlit segments, like a real LED clock. Authentic, but it costs legibility — every digit gains a faint `8` behind it. Ignored when the stroke is only one pixel wide, where the effect would just be noise. |
| **Burndown Indicator** | `perimeter` | `perimeter` drains a ring around the edge of the panel; `bar` empties a bar along the bottom; `segments` puts out a row of blocks one at a time; `none` hides it. |
| **Show Phase Label** | `true` | The phase name above the countdown. |
| **Show Session Dots** | `true` | One pip per session in the set. Completed are solid, upcoming are hollow, and the one you're in is picked out. |
| **Pulse the Current Session Dot** | `true` | Slowly blink the pip for the session you're in, so the row reads as "two done, on the third" rather than just a count. |
| **Work / Short Break / Long Break / Idle / Paused Label** | `FOCUS` / `BREAK` / `LONG BREAK` / `POMODORO` / `PAUSED` | The on-screen text for each state. Blank the Paused Label to keep showing the phase name while paused. |
| **Font** | *(blank)* | Path to a TTF relative to the LEDMatrix root, e.g. `assets/fonts/PressStart2P-Regular.ttf`. Blank uses the display's default font. |
| **Font Size (px)** | `0` | Fix the countdown height in pixels. `0` sizes it automatically to the panel. |

### Behavior

| Field | Default | Description |
|---|---|---|
| **Hold the Display While Running** | `true` | Take over the matrix while a session is active instead of rotating. Off lets the timer take a normal turn in the rotation. |
| **Phase-Change Alert (seconds)** | `8` | How long the timer grabs the display when a phase ends. `0` disables it. |
| **Flash on Phase Change** | `true` | Flash the panel during that alert. |
| **Display Duration (seconds)** | `10` | Time on screen per rotation cycle when it isn't holding the display. |

---

## MQTT Reference

All topics below are derived from the **Command Topic**. With the default
`ledmatrix/pomodoro/set`, the base is `ledmatrix/pomodoro`.

### Commands

Publish any of these as a plain string to the command topic (case-insensitive):

| Payload | Effect |
|---|---|
| `START` / `ON` | Start a work session — or resume a paused one. |
| `PAUSE` | Freeze the countdown where it is. |
| `RESUME` | Continue a paused countdown. |
| `TOGGLE` | Start, pause, or resume depending on the current state. Perfect for a single physical button. |
| `SKIP` | Abandon the current phase and move to the next one. A skipped work session doesn't count toward the set. |
| `STOP` / `OFF` | Stop and go idle, keeping the session count. |
| `RESET` | Stop, go idle, and zero the session count. |
| `WORK` | Start a work session immediately, whatever was running. |
| `SHORT_BREAK` / `BREAK` | Start a short break immediately. |
| `LONG_BREAK` | Start a long break immediately. |

Anything unrecognized is ignored, so a stray message can never be mistaken for a
stop.

### JSON Payloads

Send an object to the same topic for one-off durations, labels, and setting
changes:

```jsonc
// A 50-minute deep-work block with its own on-screen label.
// The configured Work Session length is left alone.
{"command": "start", "phase": "work", "duration_minutes": 50, "label": "DEEP WORK"}

// Change the configured durations without starting anything.
{"work_minutes": 45, "short_break_minutes": 10, "sessions_before_long_break": 3}

// Change a duration and start in one message.
{"command": "start", "work_minutes": 30}
```

| Key | Meaning |
|---|---|
| `command` (or `action`, `state`) | Any command from the table above. |
| `phase` | `work`, `short_break`, or `long_break` — which phase `start` should begin. |
| `duration_minutes` / `duration_seconds` | Length of *this* phase only. |
| `label` | On-screen text for this phase only. |
| `work_minutes`, `short_break_minutes`, `long_break_minutes`, `sessions_before_long_break` | Update the configured values. |

> Duration and label overrides last for the phase they start. Changes to
> `work_minutes` and friends apply from that moment on but are **not** written
> back to the plugin's saved configuration — set them in the web UI to make them
> permanent.

### Published Topics

| Topic | Payload |
|---|---|
| `<base>/state` | `ON` when a session is active, `OFF` when idle |
| `<base>/status` | `running`, `paused`, or `idle` |
| `<base>/phase` | `idle`, `work`, `short_break`, or `long_break` |
| `<base>/remaining` | `MM:SS` |
| `<base>/remaining_seconds` | Integer seconds |
| `<base>/session` | Completed work sessions |
| `<base>/attributes` | JSON snapshot of everything above plus `cycle_position`, `elapsed_fraction`, and the configured durations |
| `<base>/event` | JSON `{"event_type": …}` on every transition — `started`, `paused`, `resumed`, `stopped`, `reset`, `skipped`, `phase_started`, `work_complete`, `break_complete` |
| `<base>/task` | The current task label |
| `<base>/available` | `online` / `offline` (also the last-will message) |
| `<base>/work_minutes` etc. | Current value of each duration setting |

The task label is set by publishing to `<base>/task/set` (max 32 characters;
publish an empty payload to clear it). `RESET` clears it too.

Each duration also has a matching command topic — `<base>/work_minutes/set`,
`<base>/short_break_minutes/set`, `<base>/long_break_minutes/set`,
`<base>/sessions_before_long_break/set` — which is what the Home Assistant
number boxes write to.

---

## Home Assistant Setup

### Auto-Discovery (recommended)

1. Make sure the **MQTT integration** is set up in Home Assistant
   (*Settings → Devices & Services → Add Integration → MQTT*) and pointed at the
   same broker.
2. Leave **Enable Home Assistant Auto-Discovery** on in the plugin config.
3. Save. The device appears under *Settings → Devices & Services → MQTT* within
   a few seconds.

### What You Get

| Entity | Type | What it does |
|---|---|---|
| **Timer** | Switch | On starts a session, off stops it. Carries the full state as attributes. |
| **Start / Pause / Resume / Skip Phase / Reset** | Buttons | One press per command. |
| **Work Minutes / Short Break Minutes / Long Break Minutes / Sessions Before Long Break** | Numbers | Set the durations from HA — the matrix picks them up immediately. |
| **Phase** | Sensor | `idle`, `work`, `short_break`, `long_break` |
| **Status** | Sensor | `running`, `paused`, `idle` |
| **Time Remaining** | Sensor | `MM:SS` |
| **Seconds Remaining** | Sensor | Numeric, for gauges and templates |
| **Completed Sessions** | Sensor | Running count, resets on `RESET` |
| **Task** | Text | What you're working on. Type it in HA and it appears on the panel. |
| **Timer Event** | Event | Fires on every transition — the clean hook for automations |
| **MQTT Connected** | Binary sensor | Connectivity |

### Automation Examples

**Announce the end of a work session on a speaker:**

```yaml
automation:
  - alias: "Pomodoro — time for a break"
    triggers:
      - trigger: state
        entity_id: event.led_matrix_pomodoro_timer_event
        attribute: event_type
        to: work_complete
    actions:
      - action: tts.speak
        target:
          entity_id: tts.piper
        data:
          media_player_entity_id: media_player.office
          message: "Nice work. Take a break."
```

**Start a session when you sit down at your desk:**

```yaml
automation:
  - alias: "Pomodoro — start on desk occupancy"
    triggers:
      - trigger: state
        entity_id: binary_sensor.desk_occupancy
        to: "on"
        for: "00:02:00"
    conditions:
      - condition: state
        entity_id: sensor.led_matrix_pomodoro_phase
        state: idle
    actions:
      - action: button.press
        target:
          entity_id: button.led_matrix_pomodoro_start
```

**Turn on do-not-disturb for the length of a work session:**

```yaml
automation:
  - alias: "Pomodoro — focus mode"
    triggers:
      - trigger: state
        entity_id: sensor.led_matrix_pomodoro_phase
    actions:
      - action: "switch.turn_{{ 'on' if trigger.to_state.state == 'work' else 'off' }}"
        target:
          entity_id: switch.office_do_not_disturb
```

**Dashboard card:**

```yaml
type: entities
title: Pomodoro
entities:
  - entity: sensor.led_matrix_pomodoro_time_remaining
  - entity: sensor.led_matrix_pomodoro_phase
  - entity: sensor.led_matrix_pomodoro_completed_sessions
  - type: buttons
    entities:
      - entity: button.led_matrix_pomodoro_start
      - entity: button.led_matrix_pomodoro_pause
      - entity: button.led_matrix_pomodoro_skip_phase
      - entity: button.led_matrix_pomodoro_reset
  - entity: number.led_matrix_pomodoro_work_minutes
  - entity: number.led_matrix_pomodoro_short_break_minutes
```

> Entity IDs are generated from the device name — check
> *Settings → Devices & Services → MQTT → LED Matrix — Pomodoro* for the exact
> ones on your system.

### Manual YAML (if you turn discovery off)

```yaml
mqtt:
  switch:
    - name: "Pomodoro"
      command_topic: "ledmatrix/pomodoro/set"
      state_topic: "ledmatrix/pomodoro/state"
      payload_on: "START"
      payload_off: "STOP"
      state_on: "ON"
      state_off: "OFF"
      json_attributes_topic: "ledmatrix/pomodoro/attributes"
      availability_topic: "ledmatrix/pomodoro/available"
      icon: mdi:timer-play-outline

  sensor:
    - name: "Pomodoro Time Remaining"
      state_topic: "ledmatrix/pomodoro/remaining"
      availability_topic: "ledmatrix/pomodoro/available"
    - name: "Pomodoro Phase"
      state_topic: "ledmatrix/pomodoro/phase"
      availability_topic: "ledmatrix/pomodoro/available"

  button:
    - name: "Pomodoro Skip"
      command_topic: "ledmatrix/pomodoro/set"
      payload_press: "SKIP"

  number:
    - name: "Pomodoro Work Minutes"
      command_topic: "ledmatrix/pomodoro/work_minutes/set"
      state_topic: "ledmatrix/pomodoro/work_minutes"
      min: 1
      max: 180
      unit_of_measurement: "min"
```

---

## Testing Without Home Assistant

```bash
# Watch everything the plugin publishes
mosquitto_sub -h <broker-ip> -t 'ledmatrix/pomodoro/#' -v

# Drive it
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set -m START
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set -m PAUSE
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set -m SKIP

# A one-off 50-minute block
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/set \
  -m '{"command":"start","duration_minutes":50,"label":"DEEP WORK"}'

# Change the configured work length
mosquitto_pub -h <broker-ip> -t ledmatrix/pomodoro/work_minutes/set -m 45
```

The plugin's own test suite runs without a broker or a LEDMatrix checkout:

```bash
python plugins/pomodoro-timer/test_pomodoro_timer.py
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Nothing appears in Home Assistant | The MQTT integration isn't set up, or it points at a different broker. Check *Settings → Devices & Services → MQTT*, and confirm the discovery prefix matches (`homeassistant` unless you changed it). |
| Log says `paho-mqtt is not installed` | Install it on the Pi: `pip install paho-mqtt`. The plugin still renders; only remote control is unavailable. |
| Log says `MQTT connect failed rc=5` | Bad username/password, or the broker requires authentication. |
| Log says `MQTT connect error` and retries | Wrong host or port, or the broker isn't reachable from the Pi. The plugin retries with backoff, so fixing the config is enough. |
| The timer never appears on the matrix | Check the plugin is enabled and, if **Hold the Display While Running** is off, that it has a turn in your display rotation. |
| The timer takes over and won't give the panel back | That's **Hold the Display While Running**. Turn it off to keep the timer in the normal rotation, or send `STOP`. |
| The countdown looks tiny on a big panel | The seven-segment digits are sized to the space left after the label and dots. Turning off **Show Phase Label**, or switching **Burndown Indicator** to `perimeter`, frees the most room. **Font Size (px)** applies to the `pixel` digit style only. |
| The digits look squashed or the zeros read as two stacked boxes | The digits refuse to go below a readable width-to-height ratio and step down in size instead, so this should not happen — if it does on your panel shape, please open an issue with the dimensions. |
| Text is cut off | Shorten the phase labels — long labels are truncated to fit rather than drawn past the panel edge. |
| Durations changed in HA revert after a restart | Number-box changes are runtime-only by design. Set them in the plugin's web UI config to make them permanent. |
| The session count reset itself | `RESET` zeroes it (that's the difference between `STOP` and `RESET`), and so does a long break for the on-screen dots. |

---

## License

GPL-3.0 — see [LICENSE](LICENSE).
