# F1 Live

F1 Live is a third-party plugin
([BigC07/ledmatrix-f1-live](https://github.com/BigC07/ledmatrix-f1-live)), so it
has no `plugins/f1-live/` here and no `shots.json`: `render_docs_assets.py` can
only render plugins inside this repo.

`hero.png` is still real plugin output. It is the live header card from F1 Live
1.2.1, drawn at 128×32 by the plugin's own `F1Renderer.render_live_header(
"SPANISH GP", "SC", 57)` and upscaled 6× with nearest-neighbour.
