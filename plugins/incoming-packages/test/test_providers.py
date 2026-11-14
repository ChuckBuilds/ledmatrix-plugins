"""Offline unit tests for the package providers (no network)."""

import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from incoming_packages_sources import (  # noqa: E402
    AfterShipProvider,
    CarrierStat,
    HomeAssistantProvider,
    MockProvider,
    Package,
    ParcelProvider,
    Snapshot,
    make_provider,
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


# ─── Parcel provider ────────────────────────────────────────────────────────

def _parcel(tz=None):
    p = ParcelProvider({"parcel_api_key": "k"}, _log())
    p.tz = tz
    return p


def test_parcel_status_mapping_and_today_rules():
    today = date.today().isoformat()
    deliveries = [
        {"carrier_code": "ups", "status_code": 4, "description": "Cables",
         "tracking_number": "1Z1", "events": []},                     # out for delivery
        {"carrier_code": "ups", "status_code": 2, "tracking_number": "1Z2",
         "date_expected": "2099-01-01 12:00:00", "events": []},       # in transit
        {"carrier_code": "usps", "status_code": 2, "tracking_number": "94x",
         "date_expected": today + " 10:00:00", "events": []},         # eta today
        {"carrier_code": "fedex", "status_code": 3, "tracking_number": "7",
         "events": []},                                                # pickup -> today
        {"carrier_code": "dhl", "status_code": 8, "tracking_number": "8",
         "events": []},                                                # info only
        {"carrier_code": "dhl", "status_code": 7, "tracking_number": "9",
         "events": []},                                                # exception
        {"carrier_code": "gls", "status_code": 0, "tracking_number": "d",
         "events": []},                                                # delivered: dropped
        {"carrier_code": "gls", "status_code": 1, "tracking_number": "f",
         "events": []},                                                # frozen: excluded
        {"carrier_code": "gls", "status_code": 5, "tracking_number": "n",
         "events": []},                                                # not found: excluded
        "junk",
    ]
    snap = _parcel()._parse(deliveries)
    by = {c.carrier: c for c in snap.carriers}
    assert by["ups"].delivering_today == 1 and by["ups"].in_transit == 1
    assert by["usps"].delivering_today == 1
    assert by["fedex"].delivering_today == 1
    assert by["dhl"].in_transit == 2
    assert "gls" not in by
    assert len(snap.packages) == 6
    assert snap.packages[0].title == "Cables"
    assert snap.packages[1].title == "1Z2"          # falls back to the number
    assert snap.total_delivered_today == 0          # `active` filter: no delivered data


def test_parcel_unknown_and_missing_status_count_as_in_transit():
    snap = _parcel()._parse([
        {"carrier_code": "ups", "status_code": 99, "tracking_number": "a"},
        {"carrier_code": "ups", "tracking_number": "b"},
    ])
    assert snap.carriers[0].in_transit == 2


def test_parcel_timestamp_wins_over_date_string():
    import pytz
    tz = pytz.timezone("Pacific/Auckland")
    now = datetime.now(tz)
    snap = _parcel(tz)._parse([{
        "carrier_code": "ups", "status_code": 2, "tracking_number": "t",
        "timestamp_expected": int(now.timestamp()),
        "date_expected": "2099-01-01",
    }])
    assert snap.carriers[0].delivering_today == 1
    assert snap.packages[0].eta == now.date()


def test_parcel_bad_dates_do_not_raise():
    snap = _parcel()._parse([
        {"carrier_code": "ups", "status_code": 2, "tracking_number": "x",
         "date_expected": "sometime soon", "timestamp_expected": 10 ** 20},
    ])
    assert snap.carriers[0].in_transit == 1
    assert snap.packages[0].eta is None


def test_parcel_carrier_codes():
    from incoming_packages_sources import _parcel_carrier
    for code, slug in {
        "ups": "ups", "upsmi": "ups", "usps": "usps", "fedex": "fedex",
        "dhl": "dhl", "dhluk": "dhl", "amzlus": "amazon", "amshipuk": "amazon",
        "swiship": "amazon", "walmart": "walmart", "ont": "ontrac",
        "laser": "lasership", "rm": "royalmail", "cp": "canadapost",
        "au": "auspost", "dp": "deutschepost", "dpdat": "dpd", "gls": "gls",
        "gso": "gls", "hermes": "hermes", "nonesuch": "other", "": "other",
    }.items():
        assert _parcel_carrier(code) == slug, code


def test_parcel_real_response_shape():
    """Shape seen in a live response: no timestamp_expected, 'YYYY-MM-DD
    HH:MM:SS' dates, extra keys, and carrier codes outside our known list
    (Parcel's own 'pholder' placeholder, AliExpress 'aliex'/'speedpak')."""
    today = date.today().isoformat()
    snap = _parcel()._parse([
        {"carrier_code": "pholder", "status_code": 8, "tracking_number": "a",
         "description": "No carrier", "events": [],
         "date_expected": "2099-01-01 00:00:00", "date_expected_end": "2099-01-02 00:00:00",
         "extra_information": "12345"},
        {"carrier_code": "aliex", "status_code": 2, "tracking_number": "b",
         "events": [], "date_expected": today + " 17:00:00"},
        {"carrier_code": "speedpak", "status_code": 8, "tracking_number": "c",
         "events": []},
    ])
    assert [c.carrier for c in snap.carriers] == ["other"]     # one 'Package' bucket
    other = snap.carriers[0]
    assert other.delivering_today == 1 and other.in_transit == 2
    assert len(snap.packages) == 3


class _Resp:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code, self._body, self._bad = status, body, bad_json

    def json(self):
        if self._bad:
            raise ValueError("no json")
        return self._body


def _fetch_with(monkeypatch, resp=None, exc=None, key="k"):
    import incoming_packages_sources as src
    seen = {}

    def fake_get(url, **kw):
        seen["url"], seen["kw"] = url, kw
        if exc:
            raise exc
        return resp
    monkeypatch.setattr(src.requests, "get", fake_get)
    return ParcelProvider({"parcel_api_key": key}, _log()), seen


def test_parcel_fetch_request_shape_and_success(monkeypatch):
    body = {"success": True, "deliveries": [
        {"carrier_code": "ups", "status_code": 4, "tracking_number": "1"}]}
    p, seen = _fetch_with(monkeypatch, _Resp(200, body))
    snap = p.fetch()
    assert seen["url"] == "https://api.parcel.app/external/deliveries/"
    assert seen["kw"]["headers"] == {"api-key": "k"}
    assert seen["kw"]["params"] == {"filter_mode": "active"}
    assert snap.total_delivering_today == 1


def test_parcel_fetch_errors(monkeypatch):
    import requests
    from incoming_packages_sources import AuthError, ProviderError
    for status, exc in ((401, AuthError), (403, AuthError),
                        (429, ProviderError), (500, ProviderError)):
        p, _ = _fetch_with(monkeypatch, _Resp(status))
        with pytest.raises(exc):
            p.fetch()
    p, _ = _fetch_with(monkeypatch, _Resp(200, bad_json=True))
    with pytest.raises(ProviderError):
        p.fetch()
    p, _ = _fetch_with(monkeypatch, _Resp(200, [1, 2]))
    with pytest.raises(ProviderError):
        p.fetch()
    p, _ = _fetch_with(monkeypatch, _Resp(200, {"success": False,
                                                "error_message": "bad"}))
    with pytest.raises(ProviderError):
        p.fetch()
    p, _ = _fetch_with(monkeypatch, _Resp(200, {"success": True,
                                                "deliveries": "x"}))
    with pytest.raises(ProviderError):
        p.fetch()
    p, _ = _fetch_with(monkeypatch, exc=requests.exceptions.ConnectionError("x"))
    with pytest.raises(ProviderError):
        p.fetch()


def test_parcel_non_list_deliveries_is_an_error_not_empty(monkeypatch):
    """A malformed `deliveries` (even a falsey one) must raise so the plugin
    keeps showing its last-good cards, rather than reading as 'no packages'."""
    from incoming_packages_sources import ProviderError
    for bad in ({}, "", 0, False, "x", {"a": 1}, 5):
        p, _ = _fetch_with(monkeypatch, _Resp(200, {"success": True, "deliveries": bad}))
        with pytest.raises(ProviderError):
            p.fetch()
    # absent or null genuinely means nothing is active
    for body in ({"success": True}, {"success": True, "deliveries": None},
                 {"success": True, "deliveries": []}):
        p, _ = _fetch_with(monkeypatch, _Resp(200, body))
        snap = p.fetch()
        assert snap.carriers == [] and snap.total_in_transit == 0


def test_parcel_missing_key_makes_no_request(monkeypatch):
    from incoming_packages_sources import AuthError
    p, seen = _fetch_with(monkeypatch, _Resp(200, {}), key="  ")
    with pytest.raises(AuthError):
        p.fetch()
    assert seen == {}


def test_parcel_error_never_contains_key(monkeypatch):
    from incoming_packages_sources import ProviderError
    p, _ = _fetch_with(monkeypatch, _Resp(500), key="SECRET-KEY-123")
    with pytest.raises(ProviderError) as info:
        p.fetch()
    assert "SECRET-KEY-123" not in str(info.value)


def test_make_provider_selects_parcel():
    assert isinstance(make_provider("parcel", {}, _log()), ParcelProvider)
    assert isinstance(make_provider("PARCEL", {}, _log()), ParcelProvider)


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
