"""Plugin-level tests (dashboard card, resilience). Skipped where the LEDMatrix
core (src.plugin_system) isn't importable, e.g. a plugins-only checkout."""

import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from manager import IncomingPackagesPlugin
except Exception:  # pragma: no cover - core not on path
    pytest.skip("LEDMatrix core not importable", allow_module_level=True)

from package_sources import ProviderError


class FakeDM:
    def __init__(self, w=256, h=64):
        self.width, self.height = w, h
        self.image = Image.new("RGB", (w, h))

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))

    def update_display(self):
        pass


def _plugin(**cfg):
    conf = {"enabled": True, "provider": "mock"}
    conf.update(cfg)
    p = IncomingPackagesPlugin("incoming-packages", conf, FakeDM(), None, None)
    return p


def test_dashboard_is_lead_card():
    p = _plugin(show_dashboard=True)
    p.update()
    assert p._cards[0]["type"] == "dashboard"
    assert len(p._cards[0]["grid"]) > 1
    assert p._cards[0]["today"] > 0


def test_summary_when_dashboard_disabled():
    p = _plugin(show_dashboard=False)
    p.update()
    assert p._cards[0]["type"] == "summary"


def test_resilience_keeps_last_good_on_transient_error():
    p = _plugin()
    p.update()
    good = list(p._cards)
    assert good and not p._stale
    # next fetch fails; should ride out on cached cards, flagged stale
    p._last_fetch = 0.0
    p.provider.fetch = lambda: (_ for _ in ()).throw(ProviderError("HA unreachable"))
    p.update()
    assert p._cards == good        # unchanged, still showing packages
    assert p._stale is True
    assert p._error is None


def test_error_card_when_no_cached_data():
    p = _plugin()
    p.provider.fetch = lambda: (_ for _ in ()).throw(ProviderError("HA unreachable"))
    p.update()
    assert p._error == "HA unreachable"
    assert p._cards == []


def test_age_label():
    assert IncomingPackagesPlugin._age_label(10) == "just now"
    assert IncomingPackagesPlugin._age_label(5 * 60) == "5m ago"
    assert IncomingPackagesPlugin._age_label(3 * 3600) == "3h ago"


def test_fetch_frames_extracts_all_gif_frames(monkeypatch):
    """The USPS Informed Delivery image is an animated GIF; every frame (each
    scanned mail piece) must be extracted for playback."""
    import io
    import manager as m
    frames = [Image.new("RGB", (30, 15), (i * 60, 0, 0)) for i in range(4)]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    data = buf.getvalue()

    class _Resp:
        content = data

        def raise_for_status(self):
            pass

    monkeypatch.setattr(m.requests, "get", lambda *a, **k: _Resp())
    out = _plugin()._fetch_frames("http://x/mail.gif", (30, 15))
    assert len(out) == 4


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
