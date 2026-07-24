"""
Package data sources for the Incoming Packages plugin.

A `PackageProvider` fetches a normalized `Snapshot` of incoming-package activity.
The plugin is provider-agnostic; today three providers ship:

* `HomeAssistantProvider` (default) — reads the "Mail and Packages" integration's
  sensors from a Home Assistant instance over its REST API. The email scanning
  happens entirely inside the user's Home Assistant; this plugin only ever holds
  the HA base URL + a long-lived token and reads sensor states.
* `AfterShipProvider` — reads a per-package tracking list from the AfterShip API
  and aggregates it into the same per-carrier snapshot.
* `MockProvider` — built-in demo data for the offline safety harness and for a
  no-credentials preview on the panel.

Named `package_sources` (a plugin-unique module name) so it never collides with
another plugin on the loader's deferred-import path.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests


# ─── Errors ────────────────────────────────────────────────────────────────

class ProviderError(Exception):
    """A provider could not be reached or returned unusable data."""


class AuthError(ProviderError):
    """Credentials were rejected (bad/expired token or API key)."""


# ─── Carrier normalization ─────────────────────────────────────────────────

# Canonical carrier slugs we know how to badge/color. Anything else buckets
# into "other" so a stray sensor never spawns a junk card.
KNOWN_CARRIERS = {
    "usps", "ups", "fedex", "dhl", "amazon", "walmart", "deutschepost",
    "ontrac", "lasership", "dpd", "gls", "hermes", "royalmail",
    "canadapost", "auspost",
}

_CARRIER_ALIASES = {
    "fedex": "fedex", "fedexground": "fedex", "royalmail": "royalmail",
    "canadapost": "canadapost", "australiapost": "auspost", "auspost": "auspost",
    "amazonhub": "amazon", "amzl": "amazon", "zpackages": "other",
    "mail": "usps", "postde": "deutschepost", "deutschepost": "deutschepost",
    "generic": "other",
}


def normalize_carrier(raw: str) -> str:
    """Map a raw carrier token (from an entity id or API slug) to a known slug."""
    slug = re.sub(r"[^a-z0-9]+", "", (raw or "").lower())
    if slug in _CARRIER_ALIASES:
        return _CARRIER_ALIASES[slug]
    if slug in KNOWN_CARRIERS:
        return slug
    # substring fallbacks (e.g. "uspsprioritymail" -> "usps")
    for known in KNOWN_CARRIERS:
        if known in slug:
            return known
    return "other"


def _to_int(value: Any) -> int:
    """Parse an int from an HA sensor state, treating unknown/blank as 0."""
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


# ─── Normalized data model ─────────────────────────────────────────────────

# Package status buckets (best-effort; only some providers populate per-package).
STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
STATUS_IN_TRANSIT = "in_transit"
STATUS_DELIVERED = "delivered"
STATUS_INFO_RECEIVED = "info_received"
STATUS_EXCEPTION = "exception"
STATUS_PENDING = "pending"


@dataclass
class CarrierStat:
    """Per-carrier day-of counts."""
    carrier: str                      # canonical slug
    delivering_today: int = 0         # scheduled to arrive today / out for delivery
    in_transit: int = 0               # in transit, not arriving today
    delivered_today: int = 0

    @property
    def active(self) -> int:
        return self.delivering_today + self.in_transit


@dataclass
class Package:
    """A single tracked package (only some providers expose this granularity)."""
    carrier: str
    title: str = ""
    status: str = STATUS_IN_TRANSIT
    status_text: str = ""
    eta: Optional[date] = None
    tracking_number: str = ""


@dataclass
class Snapshot:
    """Everything the renderer needs for one refresh."""
    carriers: List[CarrierStat] = field(default_factory=list)
    total_in_transit: int = 0
    total_delivering_today: int = 0
    total_delivered_today: int = 0
    packages: List[Package] = field(default_factory=list)
    usps_mail_count: Optional[int] = None
    usps_image_url: Optional[str] = None
    carrier_images: Dict[str, str] = field(default_factory=dict)  # slug -> image URL
    summary_text: str = ""
    updated: Optional[datetime] = None

    def finalize(self) -> "Snapshot":
        """Derive totals from carriers when a provider didn't supply them, and
        drop empty carriers. Returns self for chaining."""
        self.carriers = [c for c in self.carriers if c.active or c.delivered_today]
        if not self.total_in_transit:
            self.total_in_transit = sum(c.in_transit for c in self.carriers)
        if not self.total_delivering_today:
            self.total_delivering_today = sum(c.delivering_today for c in self.carriers)
        return self


# ─── Provider interface ────────────────────────────────────────────────────

class PackageProvider(ABC):
    """Fetches a normalized Snapshot of incoming-package activity."""

    requires_token: bool = False

    def __init__(self, config: Dict[str, Any], logger):
        self.config = config
        self.logger = logger

    @abstractmethod
    def fetch(self) -> Snapshot:
        """Return a finalized Snapshot. Raise AuthError/ProviderError on failure."""


# ─── Home Assistant (Mail and Packages) ────────────────────────────────────

class HomeAssistantProvider(PackageProvider):
    """Reads the Mail and Packages integration's sensors via the HA REST API.

    All parsing is by entity-id suffix so it adapts to whatever carriers the
    user has enabled, with no per-entity configuration:
        <prefix><carrier>_delivering  -> delivering_today
        <prefix><carrier>_packages    -> in_transit
        <prefix><carrier>_delivered   -> delivered_today
        <prefix>packages_in_transit   -> total in transit
        <prefix>packages_delivered    -> total delivered today
        <prefix>usps_mail             -> USPS mail-piece count
        <prefix>image_url             -> USPS Informed Delivery image
    """

    requires_token = True

    def __init__(self, config, logger):
        super().__init__(config, logger)
        self.base_url = (config.get("ha_base_url") or "").strip().rstrip("/")
        self.token = (config.get("ha_token") or "").strip()
        self.prefix = (config.get("entity_prefix") or "sensor.mail_").strip()

    def fetch(self) -> Snapshot:
        if not self.base_url or not self.token:
            raise AuthError("Set HA URL/token")
        try:
            resp = requests.get(
                f"{self.base_url}/api/states",
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                timeout=10,
            )
        except requests.exceptions.RequestException as exc:
            raise ProviderError("HA unreachable") from exc
        if resp.status_code in (401, 403):
            raise AuthError("Update HA token")
        if resp.status_code >= 400:
            raise ProviderError(f"HA error {resp.status_code}")
        try:
            states = resp.json()
        except ValueError as exc:
            raise ProviderError("HA bad response") from exc
        return self._parse_states(states)

    @staticmethod
    def _mail_key(entity_id: str) -> Optional[str]:
        """Return the part of an entity id after the integration's `mail_`
        segment, independent of the config-entry name. Handles both
        `sensor.mail_usps_delivering` and `sensor.imap_gmail_com_mail_usps_delivering`.
        Returns None for non-Mail-and-Packages entities."""
        _, _, rest = entity_id.partition(".")
        if "_mail_" in rest:                       # e.g. imap_gmail_com_mail_usps_...
            return rest.rsplit("_mail_", 1)[1]
        if rest.startswith("mail_"):               # default entry name
            return rest[len("mail_"):]
        return None

    def _abs_url(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        return self.base_url + path if path.startswith("/") else path

    def _parse_states(self, states: List[Dict[str, Any]]) -> Snapshot:
        snap = Snapshot()
        stats: Dict[str, CarrierStat] = {}
        url_fallback: Optional[str] = None

        def stat(carrier_raw: str) -> CarrierStat:
            slug = normalize_carrier(carrier_raw)
            if slug not in stats:
                stats[slug] = CarrierStat(carrier=slug)
            return stats[slug]

        for entity in states:
            if not isinstance(entity, dict):
                continue
            eid = entity.get("entity_id", "")
            domain = eid.split(".", 1)[0]
            if domain not in ("sensor", "camera"):
                continue
            key = self._mail_key(eid)
            if key is None:
                continue

            if domain == "camera":
                # Each carrier camera serves that carrier's scanned delivery
                # image; its entity_picture carries a signed token we fetch
                # locally. Map e.g. amazon_delivery_camera / ups_camera -> slug.
                cam = key[:-len("_camera")] if key.endswith("_camera") else key
                if cam.endswith("_delivery"):
                    cam = cam[: -len("_delivery")]
                pic = entity.get("attributes", {}).get("entity_picture")
                abs_url = self._abs_url(pic)
                if abs_url:
                    snap.carrier_images[normalize_carrier(cam)] = abs_url
                continue

            state = entity.get("state")
            if key in ("packages_in_transit", "zpackages_transit"):
                snap.total_in_transit = _to_int(state)
            elif key in ("packages_delivered", "zpackages_delivered"):
                snap.total_delivered_today = _to_int(state)
            elif key == "usps_mail":
                snap.usps_mail_count = _to_int(state)
            elif key == "summary":
                snap.summary_text = state if isinstance(state, str) else ""
            elif key == "image_url":
                if isinstance(state, str) and state.startswith("http"):
                    url_fallback = state            # external (Nabu Casa) URL
            elif key.endswith("_delivering"):
                stat(key[: -len("_delivering")]).delivering_today = _to_int(state)
            elif key.endswith("_packages"):
                stat(key[: -len("_packages")]).in_transit = _to_int(state)
            elif key.endswith("_delivered"):
                stat(key[: -len("_delivered")]).delivered_today = _to_int(state)
            elif key in ("mail_updated", "updated"):
                snap.updated = _parse_dt(state)

        # USPS Informed Delivery mail image: prefer the local camera proxy,
        # fall back to the external image_url sensor.
        snap.usps_image_url = snap.carrier_images.get("usps") or url_fallback

        snap.carriers = list(stats.values())
        return snap.finalize()


# ─── AfterShip ─────────────────────────────────────────────────────────────

# AfterShip `tag` -> our status bucket
_AFTERSHIP_TAG = {
    "OutForDelivery": STATUS_OUT_FOR_DELIVERY,
    "InTransit": STATUS_IN_TRANSIT,
    "InfoReceived": STATUS_INFO_RECEIVED,
    "Delivered": STATUS_DELIVERED,
    "AvailableForPickup": STATUS_OUT_FOR_DELIVERY,
    "AttemptFail": STATUS_EXCEPTION,
    "Exception": STATUS_EXCEPTION,
    "Expired": STATUS_EXCEPTION,
    "Pending": STATUS_PENDING,
}


class AfterShipProvider(PackageProvider):
    """Reads a tracking list from the AfterShip API and aggregates it."""

    requires_token = True
    BASE = "https://api.aftership.com/tracking/2025-01"

    def __init__(self, config, logger):
        super().__init__(config, logger)
        self.api_key = (config.get("api_key") or "").strip()

    def fetch(self) -> Snapshot:
        if not self.api_key:
            raise AuthError("Set AfterShip key")
        try:
            resp = requests.get(
                f"{self.BASE}/trackings",
                headers={"as-api-key": self.api_key,
                         "Content-Type": "application/json"},
                timeout=10,
            )
        except requests.exceptions.RequestException as exc:
            raise ProviderError("AfterShip down") from exc
        if resp.status_code in (401, 403):
            raise AuthError("Update AfterShip key")
        if resp.status_code >= 400:
            raise ProviderError(f"AfterShip {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError("AfterShip bad JSON") from exc
        trackings = (payload.get("data", {}) or {}).get("trackings", []) or []
        return self._parse(trackings)

    def _parse(self, trackings: List[Dict[str, Any]]) -> Snapshot:
        snap = Snapshot()
        stats: Dict[str, CarrierStat] = {}
        today = date.today()
        for tr in trackings:
            status = _AFTERSHIP_TAG.get(tr.get("tag", ""), STATUS_IN_TRANSIT)
            if status == STATUS_DELIVERED:
                continue
            slug = normalize_carrier(tr.get("slug", "") or tr.get("courier", ""))
            eta = _parse_date(_aftership_eta(tr))
            is_today = status == STATUS_OUT_FOR_DELIVERY or eta == today
            cs = stats.setdefault(slug, CarrierStat(carrier=slug))
            if is_today:
                cs.delivering_today += 1
            else:
                cs.in_transit += 1
            snap.packages.append(Package(
                carrier=slug,
                title=tr.get("title") or tr.get("tracking_number", ""),
                status=status,
                status_text=(tr.get("subtag_message") or "").strip(),
                eta=eta,
                tracking_number=tr.get("tracking_number", ""),
            ))
        snap.carriers = list(stats.values())
        return snap.finalize()


def _aftership_eta(tr: Dict[str, Any]) -> Optional[str]:
    led = tr.get("latest_estimated_delivery") or {}
    return (led.get("estimated_delivery_date")
            or tr.get("expected_delivery")
            or tr.get("shipment_delivery_date"))


# ─── Mock ──────────────────────────────────────────────────────────────────

class MockProvider(PackageProvider):
    """Built-in demo data — deterministic, no network. Exercises every card
    type (summary, arriving-today accent, in-transit, USPS mail)."""

    def fetch(self) -> Snapshot:
        snap = Snapshot(
            carriers=[
                CarrierStat("ups", delivering_today=2, in_transit=3),
                CarrierStat("usps", delivering_today=1, in_transit=0),
                CarrierStat("amazon", delivering_today=0, in_transit=4),
                CarrierStat("fedex", delivering_today=0, in_transit=1, delivered_today=2),
            ],
            total_delivered_today=2,
            usps_mail_count=4,
            summary_text="3 packages arriving today.",
        )
        return snap.finalize()


# ─── Factory + small date helpers ──────────────────────────────────────────

def make_provider(name: str, config: Dict[str, Any], logger) -> PackageProvider:
    providers = {
        "homeassistant": HomeAssistantProvider,
        "aftership": AfterShipProvider,
        "mock": MockProvider,
    }
    cls = providers.get((name or "homeassistant").lower(), HomeAssistantProvider)
    return cls(config, logger)


def _parse_date(value: Any) -> Optional[date]:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _parse_dt(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for parse in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s[:10], "%Y-%m-%d"),
    ):
        try:
            return parse(text)
        except (ValueError, TypeError):
            continue
    return None
