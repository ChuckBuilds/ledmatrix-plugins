# On Air Light

A retro broadcast tally light for your LED matrix. Publish a single MQTT message to take over the display with a pulsing red "ON AIR" sign — it holds until you send the off command, so it works as a persistent do-not-disturb signal during calls, recordings, or livestreams.

![On Air Light — pulsing red ON AIR tally light on a 192×48 LED matrix panel](preview.png)

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Quick Start](#quick-start)
3. [Plugin Configuration](#plugin-configuration)
4. [MQTT Payload Reference](#mqtt-payload-reference)
5. [Home Assistant Setup](#home-assistant-setup)
   - [Step 1 — MQTT Integration](#step-1--mqtt-integration)
   - [Step 2 — Create the Switch Entity](#step-2--create-the-switch-entity)
   - [Step 3 — Add to Your Dashboard](#step-3--add-to-your-dashboard)
   - [Step 4 — Automate It](#step-4--automate-it)
6. [Advanced: Custom Labels and Colors](#advanced-custom-labels-and-colors)
7. [Advanced: Multiple States](#advanced-multiple-states)
8. [Testing Without Home Assistant](#testing-without-home-assistant)
9. [Troubleshooting](#troubleshooting)

---

## How It Works

```text
Home Assistant  ──MQTT──►  ledmatrix/on-air/set   ──►  LED matrix lights up
LED matrix      ──MQTT──►  ledmatrix/on-air/state  ──►  Home Assistant tracks state
```

The plugin subscribes to a **command topic** and publishes back to a **state topic**. When it receives `ON`, it pins the display indefinitely — overriding whatever else is rotating — until it receives `OFF`. Home Assistant reads the state topic so its switch entity stays in sync even if you turn it off from the command line.

---

## Quick Start

1. **Install the plugin** from the LEDMatrix plugin store and navigate to its configuration tab.
2. **Set your MQTT broker host** (typically your Home Assistant IP or `homeassistant.local`).
3. **Save** — the plugin immediately connects and subscribes.
4. **Test with a quick publish:**

```bash
mosquitto_pub -h <your-broker-ip> -t ledmatrix/on-air/set -m ON
mosquitto_pub -h <your-broker-ip> -t ledmatrix/on-air/set -m OFF
```

---

## Plugin Configuration

| Field | Default | Description |
|---|---|---|
| **MQTT Broker Host** | `localhost` | IP or hostname of your MQTT broker |
| **MQTT Port** | `1883` | Broker port (use 8883 for TLS) |
| **MQTT Username** | *(blank)* | Leave blank if no auth required |
| **MQTT Password** | *(blank)* | Leave blank if no auth required |
| **Command Topic** | `ledmatrix/on-air/set` | Topic the plugin **subscribes** to |
| **State Topic** | `ledmatrix/on-air/state` | Topic the plugin **publishes** to after each state change |
| **Default Label** | `ON AIR` | Text shown when activated without a label in the payload |
| **Default Color** | `[255, 20, 20]` | RGB glow color — broadcast red by default |
| **Enable Pulsing** | `true` | Animate the glow with a slow heartbeat pulse |
| **Pulse Speed** | `1.2` Hz | How fast the glow breathes (1.2 ≈ one pulse per second) |
| **Standby Rotation Duration** | `5` s | How long the dark standby screen sits in the normal rotation before cycling away |

---

## MQTT Payload Reference

The plugin is flexible about what it accepts on the command topic.

### Simple strings

```
ON      off     1       0       true    false
```
Case-insensitive. Any of these work.

### JSON — state only

```json
{"state": "on"}
{"state": "off"}
```

### JSON — state + custom label

```json
{"state": "on", "label": "RECORDING"}
{"state": "on", "label": "IN MEETING"}
{"state": "on", "label": "LIVE"}
```

The label (max 16 chars) replaces "ON AIR" on the display. On panels 128 px wide or larger, "ON AIR" appears as the header with your label as a subtitle below it.

### JSON — state + label + color

```json
{"state": "on", "label": "IN MEETING", "color": [255, 140, 0]}
{"state": "on", "label": "RECORDING",  "color": [255, 20, 20]}
{"state": "on", "label": "LIVE",       "color": [255, 0, 80]}
```

Color is `[R, G, B]` and controls both the background glow and the tally dot. Good presets:

| Situation | Color |
|---|---|
| Recording / On Air | `[255, 20, 20]` — broadcast red |
| In a meeting / call | `[255, 140, 0]` — amber |
| Livestreaming | `[255, 0, 80]` — hot pink |
| Do Not Disturb | `[180, 0, 180]` — purple |

---

## Home Assistant Setup

### Step 1 — MQTT Integration

If you haven't already set up the MQTT integration in Home Assistant:

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **MQTT** and click it
3. Enter your broker details (host, port, credentials)
4. Click **Submit**

> If you're running the Mosquitto broker add-on, it's already installed at `core-mosquitto`. HA auto-discovers it and fills in the connection details for you.

---

### Step 2 — Create the Switch Entity

Add the following to your `configuration.yaml` (or `packages/on_air.yaml` if you use packages):

```yaml
mqtt:
  switch:
    - name: "LED On Air"
      unique_id: ledmatrix_on_air
      icon: mdi:broadcast
      command_topic: "ledmatrix/on-air/set"
      state_topic: "ledmatrix/on-air/state"
      payload_on: "ON"
      payload_off: "OFF"
      state_on: "ON"
      state_off: "OFF"
      retain: false
      optimistic: false
```

After saving and reloading your config (`Developer Tools → YAML → Reload`), the entity `switch.led_on_air` appears in Home Assistant.

> **`retain: false`** — The plugin publishes its own state back so HA always has the current value. Retained commands could cause the display to re-activate after a restart if you're not careful.

> **`optimistic: false`** — HA waits for the state topic echo before updating its own state, keeping it in sync even if the matrix is unreachable.

---

### Step 3 — Add to Your Dashboard

The simplest dashboard card:

```yaml
type: button
entity: switch.led_on_air
name: On Air
icon: mdi:broadcast
tap_action:
  action: toggle
hold_action:
  action: more-info
show_state: true
```

Or a toggle card that shows red when active:

```yaml
type: tile
entity: switch.led_on_air
name: On Air Light
icon: mdi:record-circle
color: red
```

---

### Step 4 — Automate It

#### Turn on when a calendar event starts

```yaml
alias: "On Air — Calendar"
description: "Light up the matrix when a Work Focus block starts"
trigger:
  - platform: calendar
    event: start
    entity_id: calendar.work
    offset: "0:00:00"
condition:
  - condition: template
    value_template: >
      {{ 'focus' in trigger.calendar_event.summary | lower
         or 'meeting' in trigger.calendar_event.summary | lower }}
action:
  - service: mqtt.publish
    data:
      topic: ledmatrix/on-air/set
      payload: '{"state": "on", "label": "IN MEETING"}'
  - wait_for_trigger:
      - platform: calendar
        event: end
        entity_id: calendar.work
  - service: mqtt.publish
    data:
      topic: ledmatrix/on-air/set
      payload: "OFF"
```

---

#### Turn on when a Teams / Zoom call is active

If you have the [Home Assistant Companion App](https://companion.home-assistant.io/) on your Mac or PC, it can expose sensors for active call status:

```yaml
alias: "On Air — On a call"
trigger:
  - platform: state
    entity_id: sensor.macbook_active_app    # or your call sensor
    to: "zoom.us"
  - platform: state
    entity_id: binary_sensor.teams_call_active
    to: "on"
action:
  - service: mqtt.publish
    data:
      topic: ledmatrix/on-air/set
      payload: '{"state": "on", "label": "ON A CALL"}'

---

alias: "Off Air — Call ended"
trigger:
  - platform: state
    entity_id: sensor.macbook_active_app
    from: "zoom.us"
  - platform: state
    entity_id: binary_sensor.teams_call_active
    to: "off"
action:
  - service: mqtt.publish
    data:
      topic: ledmatrix/on-air/set
      payload: "OFF"
```

---

#### Turn on from a physical button

If you have a Zigbee or Z-Wave button paired with HA:

```yaml
alias: "On Air — Button toggle"
trigger:
  - platform: device
    domain: mqtt
    device_id: <your_button_device_id>
    type: action
    subtype: single
action:
  - service: switch.toggle
    target:
      entity_id: switch.led_on_air
```

---

#### Activate with a custom label from a script

Create a script you can call from automations or the UI with a selectable mode:

```yaml
# scripts.yaml
led_on_air:
  alias: "Set LED On Air"
  fields:
    mode:
      description: "What to show (ON AIR, RECORDING, IN MEETING, LIVE)"
      default: "ON AIR"
      selector:
        select:
          options:
            - "ON AIR"
            - "RECORDING"
            - "IN MEETING"
            - "LIVE"
  sequence:
    - service: mqtt.publish
      data:
        topic: ledmatrix/on-air/set
        payload: >
          {"state": "on", "label": "{{ mode }}"}
```

Call it from a dashboard button or another automation:

```yaml
action:
  - service: script.led_on_air
    data:
      mode: "RECORDING"
```

---

## Advanced: Custom Labels and Colors

Map situations to colors in a single automation using `choose`:

```yaml
alias: "On Air — Context-aware"
trigger:
  - platform: state
    entity_id: input_select.work_mode
action:
  - service: mqtt.publish
    data:
      topic: ledmatrix/on-air/set
      payload: >
        {% set mode = trigger.to_state.state %}
        {% if mode == 'Recording' %}
          {"state": "on", "label": "RECORDING", "color": [255, 20, 20]}
        {% elif mode == 'Meeting' %}
          {"state": "on", "label": "IN MEETING", "color": [255, 140, 0]}
        {% elif mode == 'Livestream' %}
          {"state": "on", "label": "LIVE", "color": [255, 0, 80]}
        {% elif mode == 'Focus' %}
          {"state": "on", "label": "DO NOT DISTURB", "color": [180, 0, 180]}
        {% else %}
          OFF
        {% endif %}
```

---

## Advanced: Multiple States

You can drive multiple on-air states from a single `input_select` helper:

1. **Create a helper:** Settings → Helpers → Add Helper → Dropdown  
   Name: `Studio Mode`  
   Options: `Off`, `On Air`, `Recording`, `In Meeting`, `Live`

2. **Add a tile card to your dashboard:**

```yaml
type: tile
entity: input_select.studio_mode
name: Studio Mode
```

3. **Wire the automation:**

```yaml
alias: "Studio Mode → LED Matrix"
trigger:
  - platform: state
    entity_id: input_select.studio_mode
action:
  - service: mqtt.publish
    data:
      topic: ledmatrix/on-air/set
      payload: >
        {% set s = states('input_select.studio_mode') %}
        {% if s == 'Off' %}
          OFF
        {% elif s == 'On Air' %}
          {"state": "on", "label": "ON AIR", "color": [255, 20, 20]}
        {% elif s == 'Recording' %}
          {"state": "on", "label": "RECORDING", "color": [255, 20, 20]}
        {% elif s == 'In Meeting' %}
          {"state": "on", "label": "IN MEETING", "color": [255, 140, 0]}
        {% elif s == 'Live' %}
          {"state": "on", "label": "LIVE", "color": [255, 0, 80]}
        {% endif %}
```

Now one dropdown controls the whole thing from your dashboard or from any automation.

---

## Testing Without Home Assistant

You can test everything with just `mosquitto-clients`:

```bash
# Install if needed
brew install mosquitto          # macOS
sudo apt install mosquitto-clients   # Debian/Ubuntu

# Turn on
mosquitto_pub -h <broker-ip> -t ledmatrix/on-air/set -m ON

# Turn on with a label
mosquitto_pub -h <broker-ip> -t ledmatrix/on-air/set \
  -m '{"state": "on", "label": "RECORDING"}'

# Turn on with label + amber color
mosquitto_pub -h <broker-ip> -t ledmatrix/on-air/set \
  -m '{"state": "on", "label": "IN MEETING", "color": [255, 140, 0]}'

# Watch state feedback in another terminal
mosquitto_sub -h <broker-ip> -t ledmatrix/on-air/state

# Turn off
mosquitto_pub -h <broker-ip> -t ledmatrix/on-air/set -m OFF
```

---

## Troubleshooting

### Display doesn't activate when I send ON

1. **Check the plugin is installed and enabled** in the LEDMatrix plugin manager.
2. **Verify the broker host** — open the plugin config and confirm it matches your MQTT broker's IP or hostname.
3. **Check LEDMatrix logs:**
   ```bash
   ssh devpi@<your-matrix-ip> 'sudo journalctl -u ledmatrix -f'
   ```
   You should see `[on-air] MQTT connected — subscribed to ledmatrix/on-air/set` on startup.
4. **Check the broker is reachable** from the matrix device with a quick ping.

### The HA switch shows "Unavailable"

- Confirm you reloaded your config after adding the `mqtt: switch:` block.
- Check the state topic: the switch won't show a valid state until the plugin has published at least once. Toggle it once from the command line to prime the state.

### HA switch state doesn't update after sending OFF

- Make sure `optimistic: false` is set in your switch config — this tells HA to wait for the state topic echo rather than assuming the command worked.
- Confirm `state_topic` in the plugin config matches `state_topic` in your HA switch config.

### The display activates but goes away after a few minutes

- This should not happen with the default config (the plugin uses a pinned, indefinite on-demand request).
- If your LEDMatrix instance is restarting, the on-demand state won't survive a restart. Add a startup automation in HA to republish the current state on LEDMatrix boot.

### Retained ON payload keeps reactivating after restart

- Set `retain: false` in your HA switch config.
- Clear any retained messages on the command topic:
  ```bash
  mosquitto_pub -h <broker-ip> -t ledmatrix/on-air/set -m "" -r -n
  ```
