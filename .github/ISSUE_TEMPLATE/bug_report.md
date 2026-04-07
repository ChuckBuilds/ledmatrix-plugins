---
name: Plugin bug report
about: Report a bug in one of the official plugins
title: '[<plugin-id>] '
labels: bug
assignees: ''

---

<!--
Before filing: please check existing issues to see if this is already
reported. For security issues, see SECURITY.md and report privately.
For bugs in the LEDMatrix core (display controller, web interface,
plugin loader), report at:
  https://github.com/ChuckBuilds/LEDMatrix/issues
-->

## Plugin

- **Plugin id**: <!-- e.g. hockey-scoreboard -->
- **Plugin version** (from `manifest.json`): <!-- e.g. 1.2.4 -->
- **Installed via**: <!-- Plugin Store / Install from GitHub URL / manual copy -->

## Describe the bug

<!-- A clear and concise description of what the bug is. -->

## Steps to reproduce

1.
2.
3.

## Expected behavior

<!-- What you expected to happen. -->

## Actual behavior

<!-- What actually happened. Include any error messages from the
LEDMatrix Logs tab or `journalctl -u ledmatrix`. -->

## Plugin configuration

<!-- Paste the relevant section from config/config.json (redact any
API keys). The plugin's tab in the web UI shows the current config. -->

```json
"<plugin-id>": {
  ...
}
```

## Logs

<!-- Run:
  sudo journalctl -u ledmatrix -n 100 --no-pager | grep <plugin-id>
or grab the relevant lines from the web UI's Logs tab. -->

```
```

## Hardware

- **Raspberry Pi model**: <!-- e.g. Pi 4 4GB -->
- **LEDMatrix version**: <!-- git commit or release tag from the LEDMatrix repo -->
- **Display panels**: <!-- e.g. 2x 64x32 -->

## Additional context

<!-- Anything else that might help: API key configured? External
service status? Anything that's different about your setup? -->
