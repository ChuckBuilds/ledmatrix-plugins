"""Offline unit tests for the package providers (no network)."""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from package_sources import (  # noqa: E402
    AfterShipProvider,
    HomeAssistantProvider,
    MockProvider,
    normalize_carrier,
)


def _log():
    class _L:
        def __getattr__(self, _):
            return lambda *a, **k: None
    return _L()


# ─── carrier normalization ─────────────────────────────────────────────────

def test_normalize_carrier():
    assert normalize_carrier("USPS") == "usps"
    assert normalize_carrier("fed_ex") == "fedex"
    assert normalize_carrier("amazon_hub") == "amazon"
    assert normalize_carrier("Royal Mail") == "royalmail"
    assert normalize_carrier("zpackages") == "other"
    assert normalize_carrier("wombat-express") == "other"
    assert normalize_carrier("uspsprioritymail") == "usps"  # substring fallback


# ─── Home Assistant provider ────────────────────────────────────────────────

HA_STATES = [
    {"entity_id": "sensor.mail_usps_delivering", "state": "1"},
    {"entity_id": "sensor.mail_usps_packages", "state": "0"},
    {"entity_id": "sensor.mail_usps_mail", "state": "4"},
    {"entity_id": "sensor.mail_ups_delivering", "state": "2"},
    {"entity_id": "sensor.mail_ups_packages", "state": "3"},
    {"entity_id": "sensor.mail_fedex_delivering", "state": "0"},
    {"entity_id": "sensor.mail_fedex_packages", "state": "1"},
    {"entity_id": "sensor.mail_amazon_packages", "state": "4"},
    {"entity_id": "sensor.mail_packages_in_transit", "state": "8"},
    {"entity_id": "sensor.mail_image_url", "state": "http://ha.local/local/mail_today.gif"},
    {"entity_id": "sensor.mail_zpackages_delivered", "state": "2"},
    {"entity_id": "sensor.mail_usps_exception", "state": "0"},
    {"entity_id": "sensor.living_room_temp", "state": "72"},  # unrelated, ignored
    {"entity_id": "sensor.mail_dhl_packages", "state": "unavailable"},  # -> 0, dropped
]


def _ha():
    p = HomeAssistantProvider(
        {"ha_base_url": "http://x", "ha_token": "t", "entity_prefix": "sensor.mail_"},
        _log())
    return p._parse_states(HA_STATES)


def test_ha_totals_and_usps():
    snap = _ha()
    assert snap.total_in_transit == 8            # from packages_in_transit
    assert snap.total_delivering_today == 3      # derived: 1 (usps) + 2 (ups)
    assert snap.usps_mail_count == 4
    assert snap.usps_image_url.endswith("mail_today.gif")


def test_ha_carrier_counts_and_drops_empty():
    by = {c.carrier: c for c in _ha().carriers}
    assert by["usps"].delivering_today == 1 and by["usps"].in_transit == 0
    assert by["ups"].delivering_today == 2 and by["ups"].in_transit == 3
    assert by["fedex"].in_transit == 1
    assert by["amazon"].in_transit == 4
    assert "dhl" not in by            # unavailable -> 0 -> dropped as empty
    assert "other" not in by          # unrelated sensor ignored


# ─── AfterShip provider ─────────────────────────────────────────────────────

def test_aftership_aggregates_and_classifies():
    today = date.today().isoformat()
    trackings = [
        {"slug": "ups", "tag": "OutForDelivery", "title": "Cables",
         "tracking_number": "1Z1"},
        {"slug": "ups", "tag": "InTransit", "tracking_number": "1Z2",
         "expected_delivery": "2099-01-01"},
        {"slug": "usps", "tag": "InTransit", "tracking_number": "94x",
         "latest_estimated_delivery": {"estimated_delivery_date": today}},
        {"slug": "fedex", "tag": "Delivered", "tracking_number": "77"},  # dropped
    ]
    snap = AfterShipProvider({"api_key": "k"}, _log())._parse(trackings)
    by = {c.carrier: c for c in snap.carriers}
    assert by["ups"].delivering_today == 1   # OutForDelivery
    assert by["ups"].in_transit == 1
    assert by["usps"].delivering_today == 1  # eta == today
    assert "fedex" not in by                 # delivered dropped
    assert len(snap.packages) == 3


# ─── Mock provider ──────────────────────────────────────────────────────────

def test_mock_provider_has_activity():
    snap = MockProvider({}, _log()).fetch()
    assert snap.total_in_transit > 0
    assert snap.total_delivering_today > 0
    assert any(c.carrier == "usps" for c in snap.carriers)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
