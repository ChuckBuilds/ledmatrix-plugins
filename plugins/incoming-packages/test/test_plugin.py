"""Plugin-level tests (dashboard, resilience, caching). Requires the LEDMatrix
core (src.plugin_system) on the path; a genuine import error must fail loudly
rather than silently skipping the whole module."""

import os
import sys
import time

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import IncomingPackagesPlugin

from incoming_packages_sources import CarrierStat, ProviderError, Snapshot


class FakeCache:
    """cache_manager stand-in: max_age governs read expiry (as in the real
    cache); ttl is stored for compatibility."""

    def __init__(self):
        self.store = {}   # key -> (data, stored_at, ttl)

    def get(self, key, max_age=300):
        entry = self.store.get(key)
        if entry is None:
            return None
        data, stored_at, _ttl = entry
        if time.time() - stored_at > max_age:
            return None
        return data

    def set(self, key, data, ttl=None):
        self.store[key] = (data, time.time(), ttl)


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


def test_update_caches_snapshot_and_serves_from_cache():
    cache = FakeCache()
    p1 = IncomingPackagesPlugin("incoming-packages",
                                {"enabled": True, "provider": "mock"}, FakeDM(), cache, None)
    p1.update()
    assert p1._snapshot_cache_key() in cache.store        # written to cache
    # a fresh plugin sharing the cache serves from it without a network fetch
    p2 = IncomingPackagesPlugin("incoming-packages",
                                {"enabled": True, "provider": "mock"}, FakeDM(), cache, None)
    calls = []
    p2.provider.fetch = lambda: calls.append(1) or (_ for _ in ()).throw(AssertionError())
    p2.update()
    assert calls == [] and p2._cards                      # cache-first, cards built


def test_cache_key_partitioned_by_provider_config():
    """A snapshot cached for one data source must not be reused for another."""
    def key(**cfg):
        c = {"enabled": True}
        c.update(cfg)
        return IncomingPackagesPlugin("incoming-packages", c, FakeDM(), FakeCache(),
                                      None)._snapshot_cache_key()
    k_ha1 = key(provider="homeassistant", ha_base_url="http://ha1:8123")
    k_ha2 = key(provider="homeassistant", ha_base_url="http://ha2:8123")
    k_aftership = key(provider="aftership")
    assert k_ha1 != k_ha2 != k_aftership and k_ha1 != k_aftership
    # a secret change must NOT change the key (auth, not source identity)
    assert key(provider="homeassistant", ha_base_url="http://ha1:8123", ha_token="a") == k_ha1


def test_stale_cache_entry_triggers_refetch():
    """When the cached snapshot is older than update_interval, update() fetches
    again instead of serving stale data (FakeCache honors max_age)."""
    cache = FakeCache()
    cfg = {"enabled": True, "provider": "mock", "update_interval": 60}
    p1 = IncomingPackagesPlugin("incoming-packages", cfg, FakeDM(), cache, None)
    p1.update()
    # age the cached entry past update_interval
    key = p1._snapshot_cache_key()
    data, _stored, ttl = cache.store[key]
    cache.store[key] = (data, time.time() - 999, ttl)
    p2 = IncomingPackagesPlugin("incoming-packages", cfg, FakeDM(), cache, None)
    calls = []
    orig = p2.provider.fetch
    p2.provider.fetch = lambda: (calls.append(1), orig())[1]
    p2.update()
    assert calls == [1]                                   # stale -> refetched


def test_include_delivered_filters_delivered_only_carriers():
    snap = Snapshot(
        carriers=[CarrierStat("ups", 1, 0, 0), CarrierStat("fedex", 0, 0, 3)],
        total_delivering_today=1, total_delivered_today=3,
    ).finalize()

    def carrier_cards(p):
        return {c["carrier"]: c for c in p._build_cards(snap)
                if c["type"] in ("carrier", "carrier_image")}

    off = carrier_cards(_plugin(include_delivered=False, show_dashboard=False))
    assert "fedex" not in off and "ups" in off            # delivered-only dropped
    on = carrier_cards(_plugin(include_delivered=True, show_dashboard=False))
    assert on["fedex"]["delivered"] == 3                   # kept + informative


def test_dashboard_grid_excludes_delivered_only():
    """A delivered-only carrier must not appear as a zero-count grid entry, even
    when include_delivered keeps its own card."""
    snap = Snapshot(
        carriers=[CarrierStat("ups", 2, 0, 0), CarrierStat("usps", 0, 3, 0),
                  CarrierStat("fedex", 0, 0, 3)],
        total_in_transit=3, total_delivering_today=2, total_delivered_today=3,
    ).finalize()
    cards = _plugin(include_delivered=True, show_dashboard=True)._build_cards(snap)
    assert cards[0]["type"] == "dashboard"
    assert {slug for slug, _t, _tr in cards[0]["grid"]} == {"ups", "usps"}
    assert any(c.get("carrier") == "fedex" for c in cards)   # still carded


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
