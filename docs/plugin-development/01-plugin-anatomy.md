# 1. Plugin Anatomy & Lifecycle

[← Guide index](./README.md)

## Directory layout

A plugin is a directory under `plugins/<plugin-id>/`. The directory name **must**
match the `id` in `manifest.json`. At minimum you need a manifest and an
entry-point Python file; everything else is optional but recommended.

```text
plugins/<plugin-id>/
  manifest.json         # metadata (required) — see topic 6
  manager.py            # entry point; holds the plugin class (default file)
  config_schema.json    # JSON Schema Draft-07 for the web-UI config form
  requirements.txt      # plugin runtime deps (CI installs these before the harness)
  README.md             # user-facing docs
  LICENSE               # GPL-3.0 or compatible (required for submission)
  assets/               # fonts, logos, images
  test/                 # optional safety-harness fixtures (harness.json, golden/)
  test_*.py             # optional unit tests
  <helpers>.py          # optional helper modules (mind the naming rules — topic 7)
```

The entry point defaults to `manager.py`; override it with `entry_point` in the
manifest. The class inside it must match the manifest's `class_name`.

## The plugin class

Your class inherits from `BasePlugin`, which lives in the **core** repo at
`src.plugin_system.base_plugin`. It is not in this monorepo — you import it:

```python
from src.plugin_system.base_plugin import BasePlugin

class HelloWorldPlugin(BasePlugin):
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        # ... your setup
```

See [`plugins/hello-world/manager.py`](../../plugins/hello-world/manager.py) for
the complete minimal implementation this page describes.

## The constructor

The core loader instantiates every plugin with the **same 5-argument positional
signature**:

```python
def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
    super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
```

Always call `super().__init__(...)` first — it wires up the attributes described
in [topic 2](./02-core-api.md) (`self.logger`, `self.config`,
`self.display_manager`, `self.cache_manager`, `self.plugin_manager`,
`self.plugin_id`, and defaults like `self.enabled`). Do your one-time setup
after: read config values, register fonts, initialize state. Don't fetch data or
draw here.

## The lifecycle methods

The core calls six methods on your plugin. Only `__init__` is strictly
mandatory, but a useful plugin implements at least `update` and `display`.

| Method | Signature | When the core calls it | Rule |
|--------|-----------|------------------------|------|
| `__init__` | `(self, plugin_id, config, display_manager, cache_manager, plugin_manager)` | Once, at load | Call `super().__init__`; set up state; **don't** fetch or draw |
| `update` | `(self)` | Every `update_interval` seconds | Fetch/refresh data only — **never draw** |
| `display` | `(self, force_clear=False)` | Every render turn | Draw via `self.display_manager`, then call `self.display_manager.update_display()` |
| `validate_config` | `(self)` | When validating config | Call `super().validate_config()` first, then check your keys; return `bool` |
| `get_info` | `(self)` | For the web UI | `info = super().get_info()`; add keys; return the dict |
| `cleanup` | `(self)` | On unload/teardown | Release resources; call `super().cleanup()` |

### `update(self)` — fetch, don't draw

Called on the interval you set via the `update_interval` config key. This is the
**only** place you should hit the network or do expensive work. Store results on
`self` for `display()` to render. Cache network responses through
`self.cache_manager` (see [topic 2](./02-core-api.md#cache-manager)) so a restart
or a second plugin doesn't re-hit the API.

```python
def update(self):
    data = self.cache_manager.get(f"{self.plugin_id}:feed", max_age=self.update_interval)
    if data is None:
        data = self._fetch_from_api()
        self.cache_manager.set(f"{self.plugin_id}:feed", data, ttl=self.update_interval)
    self.latest = data
```

### `display(self, force_clear=False)` — draw, then push

Called each render turn. Draw onto the display and then **always** call
`self.display_manager.update_display()` to push the frame to the panel. Honor
`force_clear` by clearing first when asked. Keep this method cheap — it runs far
more often than `update()`.

```python
def display(self, force_clear=False):
    if force_clear:
        self.display_manager.clear()
    w, h = self.display_manager.width, self.display_manager.height
    self.display_manager.draw_text(self.message, x=w // 2, y=h // 2,
                                   color=self.color, font=self.bdf_font)
    self.display_manager.update_display()
```

> **Multi-mode / scoreboard variant.** Plugins that expose several screens
> (the sports scoreboards, elections, flights, …) use a wider signature that
> returns a bool and accepts the active mode:
> `def display(self, display_mode=None, force_clear=False) -> bool`. The core
> passes `force_clear` positionally and `display_mode` as an optional keyword.
> Returning `False` lets some plugins signal "nothing to show, skip me." See
> [`plugins/hockey-scoreboard/manager.py`](../../plugins/hockey-scoreboard/manager.py).

### `validate_config(self)` — fail loudly, early

Called to check the plugin's config. Convention: call the base first, then
validate your own keys, logging a clear error and returning `False` on anything
invalid.

```python
def validate_config(self):
    if not super().validate_config():
        return False
    color = self.config.get("color")
    if color is not None and (not isinstance(color, (list, tuple)) or len(color) != 3):
        self.logger.error("'color' must be an RGB array [R, G, B]")
        return False
    return True
```

### `get_info(self)` and `cleanup(self)`

`get_info` returns a dict the web UI displays — extend the base's dict rather
than replacing it. `cleanup` runs when the plugin unloads (config change,
disable, shutdown); release timers, threads, file handles, then call
`super().cleanup()`.

## Optional hooks

Beyond the six core methods, the core calls a family of **optional** hook methods
if you implement them — for dynamic on-screen duration, live-game priority,
Vegas continuous scroll, and enable/disable/config-change events. Those are the
subject of [topic 3](./03-advanced-features.md). You never have to implement any
of them; a plugin participates in a feature only by defining the relevant hook.

## Minimal skeleton

```python
from src.plugin_system.base_plugin import BasePlugin
import time

class MyPlugin(BasePlugin):
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.message = config.get("message", "Hello, World!")
        self.color = tuple(config.get("color", [255, 255, 255]))
        self.last = None

    def update(self):
        self.last = time.time()

    def display(self, force_clear=False):
        if force_clear:
            self.display_manager.clear()
        w, h = self.display_manager.width, self.display_manager.height
        self.display_manager.draw_text(self.message, x=w // 2, y=h // 2, color=self.color)
        self.display_manager.update_display()

    def validate_config(self):
        return super().validate_config()

    def get_info(self):
        info = super().get_info()
        info["message"] = self.message
        return info

    def cleanup(self):
        super().cleanup()
```

**Next:** [The core API surface →](./02-core-api.md)
