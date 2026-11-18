"""calendar: without Google sign-in, update() warns once, not every update.

Run: pytest plugins/calendar/test_no_service_warns_once.py
"""
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

try:
    import manager as cal  # noqa: E402
except ImportError:  # pragma: no cover
    pytest.skip("LEDMatrix core not on PYTHONPATH", allow_module_level=True)

Plugin = next(v for n, v in vars(cal).items()
              if isinstance(v, type) and v.__module__ == cal.__name__ and hasattr(v, "update"))


def test_update_without_service_warns_once():
    stub = types.SimpleNamespace(service=None, logger=mock.Mock())
    for _ in range(10):
        Plugin.update(stub)
    assert stub.logger.warning.call_count == 1
