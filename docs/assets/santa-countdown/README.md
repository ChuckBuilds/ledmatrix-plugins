# Santa's Countdown

Santa's Countdown is a third-party plugin
([BigC07/ledmatrix-santa-countdown](https://github.com/BigC07/ledmatrix-santa-countdown)),
so it has no `plugins/santa-countdown/` here and no `shots.json`:
`render_docs_assets.py` can only render plugins inside this repo.

`hero.png` is still real plugin output. It is the sleigh scene from Santa's
Countdown 1.2.0 (commit d2c23a0), drawn at 128×32 by the plugin's own
`santa_scenes.render("sleigh", 37, 10, 128, 32)` with LEDMatrix's bundled
PressStart2P font, and upscaled 6× with nearest-neighbour.
