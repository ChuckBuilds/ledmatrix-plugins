# Headshot mock (scratch branch — do not merge)

A throwaway branch for one question: what does the NFL stat ticker look like
with real player headshots instead of club crests?

`render_headshot_mock.py` fetches the live ESPN leaders feed, downloads each
leader's real headshot cutout, and renders the same row three ways — crest,
headshot, headshot plus a small crest — at four panel sizes. It subclasses the
shipped renderer rather than editing it, so nothing about the plugin changes.

    python3 tools/headshot-mock/render_headshot_mock.py \
      --core   /path/to/LEDMatrix \
      --plugin plugins/nfl-stat-leaders \
      --out    /tmp/headshot-mock

Rendered output is committed under `docs/headshot-mock/` on this branch so it
can be looked at without running anything.
