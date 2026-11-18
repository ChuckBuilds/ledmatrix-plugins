"""birdnet-go: BirdNET's non-bird sound labels never trigger a species-image
request, and a 404 is not retried for a day.

Run: pytest plugins/birdnet-go/test_non_bird_labels.py
"""
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

try:
    import manager as bn  # noqa: E402
except ImportError:  # pragma: no cover
    pytest.skip("LEDMatrix core not on PYTHONPATH", allow_module_level=True)

Plugin = next(v for v in vars(bn).values() if isinstance(v, type) and hasattr(v, "_is_species_name"))


@pytest.mark.parametrize("name,ok", [
    ("Turdus migratorius", True), ("Cardinalis cardinalis", True),
    ("Engine", False), ("Fireworks", False), ("Siren", False), ("Dog", False),
    ("Human vocal", False), ("Power tools", False), ("", False),
])
def test_species_name_rule(name, ok):
    assert Plugin._is_species_name(name) is ok


def stub():
    s = types.SimpleNamespace(api_base_url="http://bn", api_timeout=5, plugin_id="birdnet-go",
                              logger=mock.Mock(), _species_img_failed={},
                              cache_manager=types.SimpleNamespace(get=lambda *a, **k: None, set=lambda *a, **k: None))
    s._is_species_name = Plugin._is_species_name
    s._image_failed_recently = types.MethodType(Plugin._image_failed_recently, s)
    s._fetch_species_image = types.MethodType(Plugin._fetch_species_image, s)
    return s


def test_sound_labels_make_no_request():
    s = stub()
    with mock.patch.object(bn.requests, "get") as get:
        assert s._fetch_species_image("Fireworks") is None
        assert s._fetch_species_image("Engine") is None
    get.assert_not_called()


def test_missing_image_waits_a_day():
    s = stub()
    clock = [1000.0]
    with mock.patch.object(bn.time, "time", lambda: clock[0]), \
            mock.patch.object(bn.requests, "get", return_value=types.SimpleNamespace(status_code=404)) as get:
        s._fetch_species_image("Rarus avis")
        clock[0] += bn._IMAGE_RETRY_S + 1          # past the normal retry window
        s._fetch_species_image("Rarus avis")
        assert get.call_count == 1
        clock[0] += bn._IMAGE_MISSING_RETRY_S
        s._fetch_species_image("Rarus avis")
        assert get.call_count == 2
    s.logger.warning.assert_not_called()
