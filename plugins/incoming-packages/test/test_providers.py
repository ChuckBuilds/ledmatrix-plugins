"""Offline unit tests for the package providers (no network)."""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from incoming_packages_sources import (  # noqa: E402
    AfterShipProvider,
    CarrierStat,
    HomeAssistantProvider,
    MockProvider,
    Package,
    Snapshot,
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
    # underscore aliases must resolve after the regex strip (keys are alnum)
    assert normalize_carrier("australia_post") == "auspost"
    assert normalize_carrier("aus_post") == "auspost"
    assert normalize_carrier("post_de") == "deutschepost"


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


def test_ha_prefixed_entry_name():
    """Real integrations name the config entry (e.g. imap_gmail_com), so entity
    ids look like sensor.imap_gmail_com_mail_usps_delivering. Parsing must find
    the mail_ segment regardless of the entry name (and not trip on 'gmail')."""
    states = [
        {"entity_id": "sensor.imap_gmail_com_mail_amazon_packages", "state": "3"},
        {"entity_id": "sensor.imap_gmail_com_mail_usps_delivering", "state": "1"},
        {"entity_id": "sensor.imap_gmail_com_mail_packages_in_transit", "state": "3"},
        {"entity_id": "sensor.imap_gmail_com_mail_usps_mail", "state": "0"},
        {"entity_id": "camera.imap_gmail_com_mail_usps_camera", "state": "idle",
         "attributes": {"entity_picture": "/api/camera_proxy/camera.x?token=abc"}},
    ]
    p = HomeAssistantProvider({"ha_base_url": "http://ha:8123", "ha_token": "t"}, _log())
    snap = p._parse_states(states)
    by = {c.carrier: c for c in snap.carriers}
    assert by["amazon"].in_transit == 3
    assert by["usps"].delivering_today == 1
    assert snap.total_in_transit == 3
    # camera proxy resolved to an absolute local URL with its token
    assert snap.usps_image_url == "http://ha:8123/api/camera_proxy/camera.x?token=abc"


def test_mail_key_ignores_gmail_substring():
    assert HomeAssistantProvider._mail_key(
        "sensor.imap_gmail_com_mail_usps_delivering") == "usps_delivering"
    assert HomeAssistantProvider._mail_key("sensor.mail_ups_packages") == "ups_packages"
    assert HomeAssistantProvider._mail_key("sensor.living_room_temp") is None


def test_ha_images_delivered_summary_and_new_carriers():
    pre = "sensor.imap_gmail_com_mail_"
    cpre = "camera.imap_gmail_com_mail_"
    states = [
        {"entity_id": pre + "walmart_delivering", "state": "1"},
        {"entity_id": pre + "deutschepost_packages", "state": "2"},
        {"entity_id": pre + "packages_delivered", "state": "4"},
        {"entity_id": "sensor.mail_summary", "state": "1 package arriving today."},
        {"entity_id": cpre + "amazon_delivery_camera", "state": "idle",
         "attributes": {"entity_picture": "/api/camera_proxy/camera.a?token=1"}},
        {"entity_id": cpre + "ups_camera", "state": "idle",
         "attributes": {"entity_picture": "/api/camera_proxy/camera.u?token=2"}},
        {"entity_id": cpre + "walmart_delivery_camera", "state": "idle",
         "attributes": {"entity_picture": "/api/camera_proxy/camera.w?token=3"}},
    ]
    p = HomeAssistantProvider({"ha_base_url": "http://ha:8123", "ha_token": "t"}, _log())
    snap = p._parse_states(states)
    by = {c.carrier: c for c in snap.carriers}
    # new carriers recognized (not bucketed to "other")
    assert by["walmart"].delivering_today == 1
    assert by["deutschepost"].in_transit == 2
    assert snap.total_delivered_today == 4
    assert snap.summary_text == "1 package arriving today."
    # camera keys map to carrier slugs, resolved to absolute local URLs
    assert snap.carrier_images["amazon"] == "http://ha:8123/api/camera_proxy/camera.a?token=1"
    assert snap.carrier_images["ups"].endswith("camera.u?token=2")
    assert snap.carrier_images["walmart"].endswith("camera.w?token=3")


def test_new_carrier_normalization():
    assert normalize_carrier("walmart") == "walmart"
    assert normalize_carrier("post_de") == "deutschepost"
    assert normalize_carrier("generic") == "other"


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


def test_snapshot_cache_roundtrip():
    """Snapshot -> dict -> Snapshot survives caching (used by cache_manager)."""
    from datetime import date, datetime
    snap = Snapshot(
        carriers=[CarrierStat("ups", 2, 3, 1), CarrierStat("usps", 0, 0, 4)],
        total_in_transit=3, total_delivering_today=2, total_delivered_today=5,
        packages=[Package("ups", "Cables", "in_transit", "On the way",
                          date(2026, 7, 30), "1Z9")],
        usps_mail_count=4, usps_image_url="http://ha/img",
        carrier_images={"ups": "http://ha/ups"},
        summary_text="2 arriving today.", updated=datetime(2026, 7, 27, 9, 0, 0),
    )
    back = Snapshot.from_dict(snap.to_dict())
    assert back.to_dict() == snap.to_dict()
    assert back.carriers[0].carrier == "ups" and back.carriers[0].delivered_today == 1
    assert back.packages[0].eta == date(2026, 7, 30)
    assert back.updated == datetime(2026, 7, 27, 9, 0, 0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
