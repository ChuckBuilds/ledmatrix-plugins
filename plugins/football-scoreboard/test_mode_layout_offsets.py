#!/usr/bin/env python3
"""
Per-card layout offsets reach the card on cores with the style system.

customization.modes.<live|upcoming|recent>.layout lets one card sit an element
somewhere different from the others. _get_layout_offset had two paths: the
fallback read the mode-merged customization, but the path every current core
takes built an ElementStyleResolver straight from self.config -- which never
contains the merged layout -- so a live-only offset was silently ignored on
every install new enough to have the feature.

The fix hands the resolver the mode-merged customization. It deliberately does
not pass ElementStyleResolver(mode=...): the oldest core this plugin supports
(ledmatrix_min_version 3.3.0) ships a resolver whose constructor takes only
(config, defaults), and a mode keyword there raises TypeError on every offset
lookup. test_the_oldest_resolver_contract_still_works pins that.

Exercised against a stand-in ``self`` that borrows the two real methods: no
display, no fonts, no network.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix <core-venv>/bin/python \
         plugins/football-scoreboard/test_mode_layout_offsets.py
"""

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

import sports  # noqa: E402

BASE_Y = 1
LIVE_Y = 5


def _config():
    return {"customization": {
        "layout": {"score": {"x_offset": 0, "y_offset": BASE_Y}},
        # x_offset None means "inherit the base value", not zero.
        "modes": {"live": {"layout": {"score": {"x_offset": None,
                                                 "y_offset": LIVE_Y}}}},
    }}


class _Card:
    _get_layout_offset = sports.SportsCore._get_layout_offset
    _mode_customization = sports.SportsCore._mode_customization

    def __init__(self, mode, config=None):
        self.SKIN_MODE = mode
        self.config = config if config is not None else _config()
        self.logger = logging.getLogger("mode_layout_offsets_probe")


def _requires_style_system():
    if not sports.STYLE_AVAILABLE:
        print("  SKIP: no core element-style system on the path "
              "(set LEDMATRIX_CORE); the fallback path is covered below")
        return True
    return False


def test_a_live_only_offset_reaches_the_live_card():
    if _requires_style_system():
        return
    assert _Card("live")._get_layout_offset("score", "y_offset") == LIVE_Y


def test_other_cards_keep_the_base_offset():
    if _requires_style_system():
        return
    for mode in ("upcoming", "recent"):
        assert _Card(mode)._get_layout_offset("score", "y_offset") == BASE_Y, mode


def test_a_blank_mode_axis_inherits_rather_than_zeroing():
    if _requires_style_system():
        return
    config = _config()
    config["customization"]["layout"]["score"]["x_offset"] = 3
    assert _Card("live", config)._get_layout_offset("score", "x_offset") == 3


def test_a_swapped_config_is_picked_up():
    """on_config_change replaces self.config; the cached resolver must follow."""
    if _requires_style_system():
        return
    card = _Card("live")
    assert card._get_layout_offset("score", "y_offset") == LIVE_Y
    new = _config()
    new["customization"]["modes"]["live"]["layout"]["score"]["y_offset"] = 9
    card.config = new
    assert card._get_layout_offset("score", "y_offset") == 9


def test_the_oldest_resolver_contract_still_works():
    """A 3.3.0-era resolver: (config, defaults) only, no mode keyword."""
    if _requires_style_system():
        return
    modern = sports.ElementStyleResolver

    class OldResolver(modern):
        def __init__(self, config, defaults):  # no mode parameter
            super().__init__(config, defaults)

        def offset_value(self, element_key, axis, default=0):  # no mode parameter
            return super().offset_value(element_key, axis, default)

    sports.ElementStyleResolver = OldResolver
    try:
        assert _Card("live")._get_layout_offset("score", "y_offset") == LIVE_Y
        assert _Card("upcoming")._get_layout_offset("score", "y_offset") == BASE_Y
    finally:
        sports.ElementStyleResolver = modern


def test_the_fallback_path_agrees():
    """Cores without the style system read the merged customization directly."""
    saved = sports.STYLE_AVAILABLE
    sports.STYLE_AVAILABLE = False
    try:
        assert _Card("live")._get_layout_offset("score", "y_offset") == LIVE_Y
        assert _Card("recent")._get_layout_offset("score", "y_offset") == BASE_Y
    finally:
        sports.STYLE_AVAILABLE = saved


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as e:  # noqa: BLE001 - report every failure
            failed += 1
            print(f"FAIL {test.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
