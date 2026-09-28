#!/usr/bin/env python3
"""The MQTT supervisor must hold one client at a time and back off on failure.

The loop checked ``mqtt_connected`` straight after ``loop_start()``, before the
broker could answer, so it built a second client, then a third. None was ever
stopped; each kept reconnecting under the same client id, so the broker kept
dropping one to admit another. A refused login spun with no delay at all.

The paho client is a fake that answers CONNECT the way a scenario says, and
the stop event is a fake clock, so the loop runs to completion instantly.

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python <thisfile>
"""
import logging
import os
import sys
import types

sys.path.insert(0, os.path.dirname(__file__))
try:
    import manager  # noqa: E402
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

failures = []
PENDING = []  # clients whose CONNACK is in flight


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (("  -- " + detail) if detail and not ok else ""))
    if not ok:
        failures.append(label)


class TooManyClients(Exception):
    pass


class Broker:
    """Scenario: answers each CONNECT with the next rc in ``replies``
    (None = never answers). Past the list, the last reply repeats."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.clients = []

    def live(self):
        return [c for c in self.clients if c.started and not c.stopped]


def fake_mqtt(broker):
    class Client:
        def __init__(self, *args, **kwargs):
            if len(broker.clients) >= 40:  # _connect_mqtt swallows this
                raise TooManyClients()
            self.started = self.stopped = False
            self.disconnected = False
            self.on_connect = self.on_disconnect = self.on_message = None
            broker.clients.append(self)

        def username_pw_set(self, *a):
            pass

        def connect(self, *a, **k):
            pass

        def subscribe(self, *a, **k):
            pass

        def loop_start(self):
            # The broker answers over the network, i.e. not before the
            # supervisor's next wait: see FakeClock.wait.
            self.started = True
            n = len(broker.clients) - 1
            self.pending_rc = broker.replies[min(n, len(broker.replies) - 1)]
            PENDING.append(self)

        def loop_stop(self):
            self.stopped = True

        def disconnect(self):
            self.disconnected = True

    return types.SimpleNamespace(
        Client=Client, CallbackAPIVersion=types.SimpleNamespace(VERSION1=1))


class FakeClock:
    """Stands in for mqtt_stop_event: wait() returns at once, records the
    requested sleep, and sets the event once ``budget`` waits are used."""

    def __init__(self, budget, on_wait=None):
        self.budget, self.waits, self.on_wait = budget, [], on_wait
        self._set = False

    def wait(self, seconds):
        self.waits.append(seconds)
        # Deliver the CONNACKs that arrived during this wait, to clients whose
        # network loop is still running.
        while PENDING:
            client = PENDING.pop(0)
            if not client.stopped and client.pending_rc is not None:
                client.on_connect(client, None, {}, client.pending_rc)
        if self.on_wait:
            self.on_wait(len(self.waits))
        if len(self.waits) >= self.budget:
            self._set = True
        return self._set

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def clear(self):
        self._set = False


def plugin(broker, clock):
    manager.mqtt = fake_mqtt(broker)
    p = object.__new__(manager.MQTTNotificationsPlugin)
    p.logger = logging.getLogger("test-mqtt")
    p.logger.addHandler(logging.NullHandler())
    p.logger.propagate = False
    p.mqtt_host, p.mqtt_port = "broker", 1883
    p.mqtt_username = ""  # no login, so the password is never read
    p.mqtt_client_id = "ledmatrix-mqtt-notifications"
    p.mqtt_keepalive = 60
    p.topics = ["homeassistant/ledmatrix/+"]
    p.mqtt_client = None
    p.mqtt_thread = None
    p.mqtt_connected = False
    p.mqtt_reconnect_delay = 1.0
    p.mqtt_max_reconnect_delay = 60.0
    p.mqtt_stop_event = clock
    return p


def run(p):
    try:
        p._mqtt_loop()
        return None
    except TooManyClients:
        return "built 40 clients without the loop ever waiting"


# 1. A broker that refuses every login (rc=5, bad credentials).
broker = Broker([5])
p = plugin(broker, FakeClock(budget=12))
err = run(p)
attempts = p.mqtt_stop_event.waits.count(5.0)
check("a refused login does not spin: one client per attempt",
      err is None and len(broker.clients) <= attempts + 1,
      err or "%d clients for %d attempts" % (len(broker.clients), attempts))
check("every refused client is stopped", all(c.stopped for c in broker.clients),
      "%d of %d still running" % (len(broker.live()), len(broker.clients)))
backoffs = [w for w in p.mqtt_stop_event.waits if w != 5.0]
check("retries back off: 1, 2, 4, 8 ... capped at 60",
      backoffs[:6] == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0], str(backoffs))
check("each attempt waits for the broker's answer",
      p.mqtt_stop_event.waits[0] == 5.0, str(p.mqtt_stop_event.waits[:3]))

# 2. A broker that never answers at all.
broker = Broker([None])
p = plugin(broker, FakeClock(budget=8))
err = run(p)
check("a silent broker does not pile up clients", err is None and not broker.live(),
      err or "%d live" % len(broker.live()))

# 3. A broker that accepts: one client, kept.
broker = Broker([0])
p = plugin(broker, FakeClock(budget=20))
err = run(p)
check("an accepted connection is kept, not redialled",
      err is None and len(broker.clients) == 1, err or "%d clients" % len(broker.clients))
check("shutting the loop down stops that client", broker.clients[0].stopped)

# 4. The connection drops mid-session and comes back.
broker = Broker([0])
peak = []


def drop_once(n):
    peak.append(len(broker.live()))
    if n == 3 and p.mqtt_client is not None:
        p._on_mqtt_disconnect(p.mqtt_client, None, 1)


p = plugin(broker, FakeClock(budget=10, on_wait=drop_once))
err = run(p)
check("after a drop exactly one new client is dialled", err is None and len(broker.clients) == 2,
      err or "%d clients" % len(broker.clients))
check("the dropped client is stopped before the new one starts",
      broker.clients[0].stopped and max(peak) <= 1, "peak live clients: %s" % max(peak))

# 5. on_disable / cleanup release a live client even with no thread running.
broker = Broker([0])
p = plugin(broker, FakeClock(budget=1000))
p._connect_mqtt()
p.mqtt_client.loop_start()
p._stop_mqtt()
check("stopping releases the client", not broker.live() and p.mqtt_client is None)
p._stop_mqtt()
check("stopping twice is harmless", p.mqtt_client is None)

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
