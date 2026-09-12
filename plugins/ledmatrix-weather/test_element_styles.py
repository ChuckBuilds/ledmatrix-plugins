#!/usr/bin/env python3
"""The current-conditions screen honours the user's per-element styling.

The contract worth holding is in two halves:

1. With nothing configured, every element resolves to exactly what the plugin
   shipped -- same font object, same colour, no offset. That is what let this
   plugin adopt the element-style system without a single golden image moving
   at any of the eight panel sizes.
2. A configured value reaches the draw. Colour, font, size, offset, visibility
   and (for the icon) scale.

These assert on the resolved style rather than on pixels, because the golden
images already cover the pixels; what they cannot show is *why* a render
matched -- a style helper that silently returned the classic value for
everything would pass them too.

Run with the core venv from a LEDMatrix checkout so PIL + assets/fonts resolve:
    LEDMatrix/.venv/bin/python <thisfile>
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(__file__))
from manager import WeatherPlugin  # noqa: E402

CLASSIC = {
    "condition_text": ("PressStart2P-Regular.ttf", 8, (255, 255, 255)),
    "temp_text": ("PressStart2P-Regular.ttf", 8, (255, 200, 0)),
    "high_low_text": ("PressStart2P-Regular.ttf", 8, (180, 180, 180)),
    "metric_text": ("4x6-font.ttf", 7, (255, 255, 255)),  # _detail_font grid
}


def _plugin(customization=None):
    config = {"enabled": True}
    if customization is not None:
        config["customization"] = customization
    display = MagicMock()
    display.small_font = "SMALL_FONT_SENTINEL"
    display.extra_small_font = "EXTRA_SMALL_FONT_SENTINEL"
    plugin = WeatherPlugin("ledmatrix-weather", config, display, MagicMock(),
                           MagicMock())
    return plugin


def _style(plugin, element, classic_font_obj="SMALL_FONT_SENTINEL"):
    font, size, color = CLASSIC[element] if element in CLASSIC else (
        "PressStart2P-Regular.ttf", 8, (255, 255, 255))
    return plugin._style(element, font, size, color, classic_font_obj)


def test_untouched_config_keeps_the_shipped_styling():
    plugin = _plugin()
    for element, (_font, _size, color) in CLASSIC.items():
        obj = ("EXTRA_SMALL_FONT_SENTINEL" if element == "metric_text"
               else "SMALL_FONT_SENTINEL")
        style = _style(plugin, element, obj)
        assert style.font is obj, (
            f"{element}: the display manager's own font object must be reused, "
            "so an untouched config is provably byte-identical rather than "
            "merely equivalent")
        assert style.color == color, element
        assert style.offset == (0, 0), element
        assert style.visible is True, element


def test_a_chosen_colour_reaches_the_draw():
    plugin = _plugin({"temp_text": {"text_color": [0, 255, 255]}})
    assert _style(plugin, "temp_text").color == (0, 255, 255)


def test_a_chosen_font_replaces_the_shipped_object():
    plugin = _plugin({"condition_text": {"font": "4x6-font.ttf",
                                         "font_size": 6}})
    style = _style(plugin, "condition_text")
    assert style.font != "SMALL_FONT_SENTINEL", (
        "a genuine font choice must swap the object, not just the name")


def test_an_offset_is_reported():
    plugin = _plugin({"layout": {"temp_text": {"x_offset": -4, "y_offset": 2}}})
    assert _style(plugin, "temp_text").offset == (-4, 2)


def test_an_element_can_be_hidden():
    plugin = _plugin({"high_low_text": {"visible": False}})
    assert _style(plugin, "high_low_text").visible is False


def test_the_icon_takes_a_scale():
    plugin = _plugin({"layout": {"weather_icon": {"scale": 0.5}}})
    style = plugin._style("weather_icon", "PressStart2P-Regular.ttf", 8,
                          (255, 255, 255))
    assert style.scale == 0.5


def test_the_metric_bar_reports_whether_its_colour_was_chosen():
    """Each metric carries its own colour (UV is graded by severity), so the
    bar only takes a single colour when the user actually picked one."""
    assert _style(_plugin(), "metric_text",
                  "EXTRA_SMALL_FONT_SENTINEL").color_chosen is False
    plugin = _plugin({"metric_text": {"text_color": [255, 120, 0]}})
    style = _style(plugin, "metric_text", "EXTRA_SMALL_FONT_SENTINEL")
    assert style.color_chosen is True
    assert style.color == (255, 120, 0)


def test_a_core_without_the_style_system_still_renders():
    """Older cores have no BasePlugin.styles; the shipped styling stands."""
    plugin = _plugin()
    type(plugin).styles = property(
        lambda self: (_ for _ in ()).throw(AttributeError("no styles")))
    try:
        style = _style(plugin, "temp_text")
        assert style.font == "SMALL_FONT_SENTINEL"
        assert style.color == (255, 200, 0)
        assert style.offset == (0, 0)
        assert style.visible is True
    finally:
        del type(plugin).styles


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - this is the runner
            failures += 1
            print(f"  FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
