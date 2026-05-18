"""
Webhook notifications for Olympics plugin.

Sends notifications to external services when:
- A favorite country wins a medal
- A new Olympic/World record is set
- A live final begins
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from queue import Queue, Empty as QueueEmpty


def _utcnow() -> datetime:
    """Get current UTC time as naive datetime (for internal comparisons)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from .data_models import OlympicEvent, EventResult

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    """A notification to be sent."""
    type: str  # "medal_win", "record", "live_final"
    title: str
    message: str
    data: Dict[str, Any]
    timestamp: datetime
    priority: str = "normal"  # "low", "normal", "high"


class NotificationManager:
    """
    Manages webhook notifications for Olympics events.

    Sends notifications asynchronously to avoid blocking the main thread.
    Supports multiple webhook endpoints.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the notification manager.

        Args:
            config: Plugin configuration with webhook settings
        """
        self.config = config
        self.enabled = config.get('notifications_enabled', False)
        self.webhooks = config.get('webhooks', [])
        self.favorite_countries = [c.upper() for c in config.get('favorite_countries', [])]

        self._queue: Queue = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Track sent notifications to avoid duplicates (with lock for thread safety)
        self._sent_events: Dict[str, datetime] = {}
        self._sent_events_lock = threading.Lock()

        if self.enabled and self.webhooks:
            self._start_worker()

    def _start_worker(self) -> None:
        """Start the background worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        logger.info("Notification worker started")

    def _worker(self) -> None:
        """Background worker that sends notifications."""
        cleanup_counter = 0
        cleanup_interval = 3600  # Cleanup every ~1 hour (3600 iterations at 1s timeout)

        while not self._stop_event.is_set():
            try:
                # Wait for notification with timeout
                notification = self._queue.get(timeout=1.0)
                try:
                    self._send_notification(notification)
                except Exception:
                    logger.exception("Error sending notification")
            except QueueEmpty:
                # Expected timeout - periodically cleanup old sent events
                cleanup_counter += 1
                if cleanup_counter >= cleanup_interval:
                    self.cleanup_sent_events()
                    cleanup_counter = 0
                continue

    def _send_notification(self, notification: Notification) -> None:
        """Send a notification to all configured webhooks."""
        if not REQUESTS_AVAILABLE:
            logger.warning("requests not available, cannot send notification")
            return

        payload = {
            "type": notification.type,
            "title": notification.title,
            "message": notification.message,
            "priority": notification.priority,
            "timestamp": notification.timestamp.isoformat(),
            "data": notification.data,
            "source": "olympics-plugin",
        }

        for webhook in self.webhooks:
            try:
                url = webhook.get('url')
                if not url:
                    continue

                # Add any custom headers
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'LEDMatrix-Olympics/2.0',
                }
                headers.update(webhook.get('headers', {}))

                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=10
                )
                response.raise_for_status()
                logger.debug(f"Notification sent to {url}")

            except Exception as e:
                logger.warning(f"Failed to send notification to {webhook.get('url')}: {e}")

    def notify_medal_win(self, result: EventResult) -> None:
        """
        Send notification for a medal win.

        Only sends if the country is in favorites.
        """
        if not self.enabled:
            return

        # Check if any winner is from a favorite country
        winners = [
            (result.gold_athlete, result.gold_country, "gold"),
            (result.silver_athlete, result.silver_country, "silver"),
            (result.bronze_athlete, result.bronze_country, "bronze"),
        ]

        for athlete, country, medal in winners:
            if country.upper() not in self.favorite_countries:
                continue

            # Check for duplicate (thread-safe)
            event_key = f"{result.event_id}_{country}_{medal}"
            with self._sent_events_lock:
                if event_key in self._sent_events:
                    continue
                self._sent_events[event_key] = _utcnow()

            notification = Notification(
                type="medal_win",
                title=f"{country} Wins {medal.title()}!",
                message=f"{athlete} wins {medal} in {result.sport}: {result.event_name}",
                data={
                    "country": country,
                    "athlete": athlete,
                    "medal": medal,
                    "sport": result.sport,
                    "event": result.event_name,
                },
                timestamp=_utcnow(),
                priority="high" if medal == "gold" else "normal"
            )
            self._queue.put(notification)

    def notify_live_final(self, event: OlympicEvent) -> None:
        """
        Send notification when a medal final begins.
        """
        if not self.enabled:
            return

        if not event.is_final:
            return

        # Check for duplicate (thread-safe)
        event_key = f"live_{event.event_id}"
        with self._sent_events_lock:
            if event_key in self._sent_events:
                return
            self._sent_events[event_key] = _utcnow()

        notification = Notification(
            type="live_final",
            title="Medal Final Starting!",
            message=f"{event.sport}: {event.event_name} is now LIVE",
            data={
                "sport": event.sport,
                "event": event.event_name,
                "venue": event.venue,
            },
            timestamp=_utcnow(),
            priority="high"
        )
        self._queue.put(notification)

    def notify_record(self, sport: str, event: str, athlete: str,
                     country: str, record_type: str = "OR",
                     result: str = "") -> None:
        """
        Send notification for a new record.

        Args:
            sport: Sport name
            event: Event name
            athlete: Athlete name
            country: Country code
            record_type: "OR" (Olympic) or "WR" (World)
            result: The record result/time
        """
        if not self.enabled:
            return

        # Check for duplicate (thread-safe)
        event_key = f"record_{sport}_{event}_{athlete}"
        with self._sent_events_lock:
            if event_key in self._sent_events:
                return
            self._sent_events[event_key] = _utcnow()

        title = "World Record!" if record_type == "WR" else "Olympic Record!"

        notification = Notification(
            type="record",
            title=title,
            message=f"{athlete} ({country}) sets new {record_type} in {sport}: {event}",
            data={
                "sport": sport,
                "event": event,
                "athlete": athlete,
                "country": country,
                "record_type": record_type,
                "result": result,
            },
            timestamp=_utcnow(),
            priority="high"
        )
        self._queue.put(notification)

    def stop(self) -> None:
        """Stop the notification worker and drain the queue."""
        self._stop_event.set()

        # Drain the queue to unblock the worker
        while True:
            try:
                self._queue.get_nowait()
            except QueueEmpty:
                break

        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
            logger.info("Notification worker stopped")

    def cleanup_sent_events(self, max_age_hours: int = 24) -> None:
        """Remove old entries from sent events tracker."""
        cutoff = _utcnow()
        with self._sent_events_lock:
            old_keys = [
                k for k, v in self._sent_events.items()
                if (cutoff - v).total_seconds() > max_age_hours * 3600
            ]
            for key in old_keys:
                del self._sent_events[key]
