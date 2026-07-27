# Incoming Packages

Rotating cards on your LEDMatrix for packages headed your way — one per active
carrier, with the count **arriving today** prioritized and highlighted, plus a
lead summary card.

> **This plugin does not use the Shop app** — Shopify exposes no public API for a
> consumer's package list. Instead it reads a normalized snapshot from a pluggable
> **provider** (default: Home Assistant). The plugin only ever stores an API URL +
> token and reads data — **it never touches your email**.

## Requirements

The default (recommended) setup relies on **one Home Assistant HACS integration**:

- **[Mail and Packages](https://github.com/moralmunky/Home-Assistant-Mail-And-Packages)**
  by `moralmunky` — a HACS custom integration that scans your email **locally inside
  Home Assistant** ("no data leaves your instance") for shipping notifications and
  publishes per-carrier sensors (USPS/UPS/FedEx/DHL/Amazon/Walmart/…) plus the USPS
  Informed Delivery mail image.

This plugin reads those sensors over your LAN via Home Assistant's REST API. The
email scanning stays entirely inside Home Assistant; **the plugin itself only holds
an HA URL + token and never accesses your email**.

> Don't run Home Assistant? Use `provider: mock` to preview it, or `provider:
> aftership` with an AfterShip account (see [Providers](#providers)).

## Setup (Home Assistant)

1. **Install HACS** in Home Assistant if you haven't
   ([hacs.xyz](https://hacs.xyz)).
2. **Install "Mail and Packages"** via HACS (HACS → Integrations → search *Mail and
   Packages* → download), then **restart Home Assistant**.
3. **Configure Mail and Packages** (Settings → Devices & Services → Add Integration →
   *Mail and Packages*) with your email account. This is where your email credentials
   live — in Home Assistant, not in this plugin. Confirm you see `sensor.*_mail_*`
   entities appear.
4. **Create a Long-Lived Access Token** in Home Assistant: click your user (bottom
   left) → **Security** → *Long-Lived Access Tokens* → **Create Token** → copy it.
5. **Configure this plugin** (in the LEDMatrix web UI or config):
   - `provider`: `homeassistant`
   - `ha_base_url`: your HA URL, e.g. `http://homeassistant.local:8123`
     (use the IP, e.g. `http://192.168.1.50:8123`, if the name doesn't resolve)
   - `ha_token`: the long-lived token from step 4
6. Enable the plugin and add `incoming_packages` to your display rotation.

The provider **auto-discovers** the Mail and Packages sensors regardless of the
integration's config-entry name (e.g. `sensor.imap_gmail_com_mail_*`) — no
per-carrier or per-package setup. It reads each carrier's *delivering* (arriving
today) and *packages* (in transit) counts, the delivered totals, the USPS mail
count/image, and Home Assistant's own summary string.

## Providers

- **`homeassistant`** (default) — Mail and Packages sensors, as above.
- **`aftership`** — set `provider: aftership` and an AfterShip `api_key`; reads your
  AfterShip tracking list and aggregates it into the same per-carrier snapshot.
- **`mock`** — built-in demo data to preview the layout on the panel with no
  credentials (also used by the offline test harness).

## Display

- **Rotating cards**, `rotation_interval` seconds each:
  - a lead **dashboard** card — every active carrier at a glance (badge + count,
    green when arriving today) — or a compact text summary (`show_dashboard`);
  - an **animated USPS Informed Delivery** image card when there is mail: it plays
    through each scanned mail piece (`show_usps_mail_image`, `image_frame_seconds`);
  - a **per-carrier delivery image** card when a carrier is out for delivery today —
    the scanned delivery photo from Home Assistant's carrier cameras
    (`show_delivery_images`; Amazon/UPS/FedEx/Walmart/USPS/…);
  - a **count card** per carrier otherwise — a drawn carrier badge, the count
    arriving today (accent color when `highlight_today`), in transit, and a
    "N delivered" confirmation (`show_delivered`).
- Carriers arriving today are sorted first. Known carriers include USPS, UPS,
  FedEx, DHL, Amazon, Walmart, Deutsche Post and more.
- **Size-adaptive**: reads the panel dimensions every frame, picks a bitmap font
  tier sized to the panel, and marquee-scrolls or truncates text that would
  overflow — renders correctly from 64×32 to 256×64.
- When idle it shows Home Assistant's own summary string ("No mail today. No
  packages in transit.").
- **Resilient**: keeps showing the last-good data through a brief Home Assistant
  hiccup rather than blanking, with a small amber "Xm ago" freshness marker once
  the data is stale (`stale_after_minutes`).

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
