# Hello World Plugin

A minimal LEDMatrix plugin that displays a customizable greeting and the
current time. It's primarily here as a working starter template you can
copy when building your own plugin.

## What it does

- Displays a configurable message
- Optionally shows the current time underneath
- Lets you set the colors of both lines

## Installation

The Hello World plugin ships with the default Plugin Store, so the easiest
way to install it is from the LEDMatrix web UI:

1. Open the web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Hello World** in the **Plugin Store** section and click **Install**
4. Toggle it on, then click **Restart Display Service** on the **Overview**
   tab

If you'd rather install it from source for local development, copy this
directory into your LEDMatrix installation's configured plugins
directory (default `plugin-repos/`):

```bash
cp -r plugins/hello-world ~/LEDMatrix/plugin-repos/
sudo systemctl restart ledmatrix
```

## Configuration

Once installed, configuration lives in the plugin's tab in the web UI.
Under the hood it's stored in `config/config.json` under the `hello-world`
key.

| Option | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Enable/disable the plugin |
| `message` | string | `"Hello, World!"` | The greeting message (1–50 chars) |
| `show_time` | boolean | `true` | Show current time below message |
| `color` | `[r, g, b]` | `[255, 255, 255]` | RGB color for the message (white) |
| `time_color` | `[r, g, b]` | `[0, 255, 255]` | RGB color for the time (cyan) |
| `display_duration` | number | `10` | Seconds the plugin holds the screen (1–300) |

The full schema lives in [`config_schema.json`](config_schema.json) and is
what the web UI's form is generated from.

### Examples

**Minimal:**
```json
{
  "hello-world": {
    "enabled": true
  }
}
```

**Custom message and color:**
```json
{
  "hello-world": {
    "enabled": true,
    "message": "Go Lightning!",
    "color": [0, 128, 255],
    "display_duration": 15
  }
}
```

**Message only, no time:**
```json
{
  "hello-world": {
    "enabled": true,
    "message": "LED Matrix",
    "show_time": false,
    "color": [255, 0, 255]
  }
}
```

## Verifying the plugin loaded

The fastest way is the **Plugin Manager** tab — installed plugins show up
under **Installed Plugins** and a tab for `hello-world` appears in the
plugin row at the top.

From SSH you can also tail the display log:

```bash
sudo journalctl -u ledmatrix -f | grep hello-world
```

You should see something like:

```text
Discovered plugin: hello-world v1.0.2
Loaded plugin: hello-world
Hello World plugin initialized with message: 'Hello, World!'
```

To run the plugin once on demand instead of waiting for it in the
rotation, open its tab in the web UI and click **Run On-Demand**.

## Using this as a template

Hello World is intentionally tiny so you can read the whole thing in one
sitting.

- [`manager.py`](manager.py) — `HelloWorldPlugin` class implementing
  `update()` and `display()` from `BasePlugin`
- [`manifest.json`](manifest.json) — plugin metadata, entry point, and
  class name (must match the class in `manager.py` exactly)
- [`config_schema.json`](config_schema.json) — JSON Schema that drives
  the web UI configuration form
- [`requirements.txt`](requirements.txt) — Python dependencies the
  plugin loader will install on first run

To start a new plugin, copy this directory, rename it, update
`manifest.json` (especially `id`, `class_name`, and `entry_point`), and
replace the body of `update()` / `display()`.

For deeper details see the LEDMatrix docs:

- [Plugin Development Guide](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/PLUGIN_DEVELOPMENT_GUIDE.md)
- [Plugin API Reference](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/PLUGIN_API_REFERENCE.md)
- [Plugin Architecture Spec](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/PLUGIN_ARCHITECTURE_SPEC.md)

## Troubleshooting

**Plugin doesn't appear in the rotation**
- Make sure it's enabled in **Plugin Manager** and that you restarted the
  display service afterward.
- Check the **Logs** tab in the web UI (or `journalctl -u ledmatrix`) for
  errors mentioning `hello-world`.

**`Class HelloWorldPlugin not found in module`**
- The `class_name` field in `manifest.json` must exactly match the class
  defined in `manager.py`. They are case-sensitive and must not contain
  spaces.

**Colors look wrong**
- Each color value must be a 3-element array of integers from `0` to
  `255`. The form rejects anything else.

## License

GPL-3.0, same as the LEDMatrix project.
