# Security Policy

This file applies to **plugin code** in the `ledmatrix-plugins`
repository. For vulnerabilities in the LEDMatrix core (display
controller, plugin loader, web interface), see the
[LEDMatrix SECURITY.md](https://github.com/ChuckBuilds/LEDMatrix/blob/main/SECURITY.md).

## Reporting a vulnerability

If you've found a security issue in one of the official plugins,
**please don't open a public GitHub issue**. Disclose it privately so
we can fix it before it's exploited.

### How to report

Use one of these channels, in order of preference:

1. **GitHub Security Advisories** (preferred) on this repo:
   <https://github.com/ChuckBuilds/ledmatrix-plugins/security/advisories/new>
2. **Discord DM** to a moderator on the
   [LEDMatrix Discord](https://discord.gg/uW36dVAtcT). Don't post in
   public channels.

Please include:

- Which plugin is affected (id and version)
- A description of the issue
- Steps to reproduce, ideally a minimal proof of concept
- The impact you can demonstrate
- Any suggested mitigation

### What to expect

- An acknowledgement within a few days (this is a hobby project, not
  a 24/7 ops team).
- A discussion of the issue's severity and a plan for the fix.
- Once fixed, the affected plugin's `manifest.json` version is
  bumped, the change is committed, and the Plugin Store delivers the
  update to users on their next refresh.
- Credit in the plugin's CHANGELOG when the fix ships, unless you'd
  prefer to remain anonymous.

## Scope

In scope for this policy:

- Code in `plugins/<plugin-id>/` for plugins maintained in this repo
- The `update_registry.py` script and the `plugins.json` registry
- The pre-commit hook in `scripts/pre-commit`

Out of scope (please report to the appropriate upstream):

- Vulnerabilities in the LEDMatrix core →
  [LEDMatrix repo](https://github.com/ChuckBuilds/LEDMatrix)
- Vulnerabilities in third-party plugins not maintained here →
  the plugin's own repository
- Vulnerabilities in Python packages a plugin depends on → the
  upstream package maintainer (e.g., `paho-mqtt`, `requests`, etc.)

## Plugin security model

Plugins shipped from this repo run inside the LEDMatrix display
service process with full file-system and network access. There is
no sandboxing. The same warning the LEDMatrix `SECURITY.md` makes
applies to every plugin here:

- **Any plugin can read and write any file the LEDMatrix process
  can reach**, including `config_secrets.json`.
- **Arbitrary outbound network requests are possible from any
  loaded plugin.**
- **Because plugins run in the same Python process as the display
  loop**, a crash in one plugin can take down the whole display.

The official plugins in this repo go through a manual review (see
[VERIFICATION.md](VERIFICATION.md)) before being added to the
`plugins.json` registry. Third-party plugins installed via "Install
from GitHub" in the LEDMatrix web UI do **not** go through this
review and are flagged as **Custom** in the Plugin Store.

## Supported versions

Each plugin is independently versioned in its `manifest.json`. There
is no LTS branch — security fixes land on `main`, the version is
bumped, and users receive the update through the Plugin Store on
their next refresh. Older versions are not patched.
