# Incoming Packages

Rotating cards on your LEDMatrix for packages headed your way — one per active
carrier, with the count **arriving today** prioritized and highlighted, plus a
lead summary card.

> **Note:** this plugin does **not** use the Shop app — Shopify exposes no public
> API for a consumer's package list. Instead it reads a normalized snapshot from a
> pluggable **provider**. The plugin only ever stores an API URL + token and reads
> data; it never touches your email.

## Providers

### Home Assistant — Mail and Packages (default, recommended)

Reuses the [Mail and Packages](https://github.com/moralmunky/Home-Assistant-Mail-And-Packages)
integration you run in Home Assistant. That integration scans your email **locally
inside Home Assistant** ("no data leaves your instance") and publishes per-carrier
sensors. This plugin reads those sensors over your LAN via the HA REST API — the
email scanning stays entirely in Home Assistant.

Setup:
1. Install and configure Mail and Packages in Home Assistant (via HACS).
2. In Home Assistant, create a **Long-Lived Access Token**
   (Profile → Security → Long-Lived Access Tokens).
3. In this plugin's config: `provider: homeassistant`, set `ha_base_url`
   (e.g. `http://homeassistant.local:8123`) and `ha_token`.

The provider auto-discovers `sensor.mail_*` entities (override `entity_prefix` if
your integration uses a different name) and reads the per-carrier *delivering*
(arriving today) and *packages* (in transit) counts, the summary totals, and the
USPS mail count — no per-package configuration.

### AfterShip

`provider: aftership` + an AfterShip API key (`api_key`). Reads your AfterShip
tracking list and aggregates it into the same per-carrier snapshot.

### Demo

`provider: mock` shows built-in demo data — useful to preview the layout on the
panel before wiring up a real source. This is also what the offline test harness
uses.

## Display

- **Rotating cards**, `rotation_interval` seconds each: a summary card
  ("N incoming · M today"), then one card per carrier — a drawn carrier badge, the
  count arriving today (accent color + emphasis when `highlight_today`), and the
  count in transit. USPS cards also show the mail-piece count.
- **Size-adaptive**: reads the panel dimensions every frame, picks a bitmap font
  tier sized to the panel, and marquee-scrolls or truncates text that would
  overflow — renders correctly from 64×32 to 256×64.

Carrier badges are drawn (colored badge + abbreviation), so no trademarked logo
images are bundled. Drop a `assets/carrier_logos/<slug>.png` (e.g. `ups.png`,
`fedex.png`) to override a badge with your own image.

## Key options

| Option | Default | Notes |
|--------|---------|-------|
| `provider` | `homeassistant` | `homeassistant` \| `aftership` \| `mock` |
| `ha_base_url` / `ha_token` | — | Home Assistant URL + long-lived token |
| `highlight_today` | `true` | Prioritize + accent arriving-today |
| `accent_color` | `[0,220,120]` | RGB accent |
| `rotation_interval` | `6` | Seconds per card |
| `update_interval` | `600` | Provider refresh cadence (s) |
| `max_cards` | `8` | Cards in the rotation |

See `config_schema.json` for the full list.
