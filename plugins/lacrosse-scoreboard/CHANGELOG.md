# Lacrosse Scoreboard — Changelog

## 1.1.0 (2026-04-07)

### Breaking change — display modes renamed with `lax_` prefix

The six display modes this plugin exposes previously collided with
the NCAA hockey modes shipped by `hockey-scoreboard`. LEDMatrix's
display controller keys modes in a flat dict
(`src/display_controller.py`), so installing both plugins at the
same time meant whichever loaded second silently overrode the
first one's NCAA modes.

All lacrosse modes now carry a `lax_` prefix. The six renames:

| Old                     | New                         |
|-------------------------|-----------------------------|
| `ncaa_mens_recent`      | `lax_ncaa_mens_recent`      |
| `ncaa_mens_upcoming`    | `lax_ncaa_mens_upcoming`    |
| `ncaa_mens_live`        | `lax_ncaa_mens_live`        |
| `ncaa_womens_recent`    | `lax_ncaa_womens_recent`    |
| `ncaa_womens_upcoming`  | `lax_ncaa_womens_upcoming`  |
| `ncaa_womens_live`      | `lax_ncaa_womens_live`      |

### Migration required

If you referenced any of the old names anywhere in `config.json`,
update them to the new prefixed names. Common places:

- `display_durations` overrides keyed by mode name
- `rotation_order` entries listing which modes to cycle through
- Any custom scripting or automation that pokes the REST API with
  these mode names

There is no backward-compat alias — the old names are no longer
recognized by the plugin dispatch logic.

### Why now

The collision with `hockey-scoreboard` was a silent data loss bug:
whichever plugin loaded second won, without any warning in the
logs. Renaming with a plugin-specific prefix is the only durable
fix until the display controller grows proper namespacing. The
`lax_` prefix was chosen to be short and consistent with how other
prefix-disambiguated codebases handle the same problem.

## 1.0.3 (2026-04-06)

Schema-conformance manifest cleanup.

## 1.0.2 (2026-04-06)

Initial monorepo release.
