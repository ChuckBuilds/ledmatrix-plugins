"""odds-ticker: ESPN's mixed-case network names ("Fox", "Prime Video") find
their channel logo, and a short key never matches inside another word.

Run: pytest plugins/odds-ticker/test_broadcast_logo_match.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

try:
    from manager import OddsTickerPlugin  # noqa: E402
except ImportError:  # pragma: no cover
    pytest.skip("LEDMatrix core not on PYTHONPATH", allow_module_level=True)


def match(name):
    """The lookup rule from the renderer, on the plugin's own map."""
    for key in sorted(OddsTickerPlugin.BROADCAST_LOGO_MAP, key=len, reverse=True):
        if OddsTickerPlugin._broadcast_key_matches(key, name):
            return OddsTickerPlugin.BROADCAST_LOGO_MAP[key]
    return None


@pytest.mark.parametrize("name,logo", [
    ("Fox", "fox"), ("FOX", "fox"), ("Prime Video", "prime"), ("ESPN2", "espn2"),
    ("espn", "espn"), ("KJZZ-TV", None), ("ClipperVision", None),
])
def test_broadcast_names(name, logo):
    assert match(name) == logo


def test_every_mapped_logo_ships_with_core():
    core = Path(__file__).resolve().parents[3] / "LEDMatrix" / "assets" / "broadcast_logos"
    if not core.is_dir():
        pytest.skip("core checkout not beside the plugins repo")
    missing = {v for v in OddsTickerPlugin.BROADCAST_LOGO_MAP.values() if not (core / f"{v}.png").exists()}
    assert not missing
