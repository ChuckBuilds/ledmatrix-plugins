#!/usr/bin/env python3
"""The MQTT supervisor must wait for the broker and back off on failure.

The loop checked ``mqtt_connected`` straight after ``loop_start()``, before
the broker could answer, so each pass tore down the client it had just
dialled and dialled again, with no delay: a tight connect/disconnect cycle
against the broker for as long as MQTT was enabled. A refused login did the
same.

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
logging.getLogger("test-birdnet-go").addHandler(logging.NullHandler())
logging.getLogger("test-birdnet-go").propagate = False

failures = []
PENDING = []  # clients whose CONNACK is in flight


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (("  -- " + detail) if detail and not ok else ""))
    if not ok:
        failures.append(label)


class Broker:
    """Scenario: answers each CONNECT with the next rc in ``replies``
    (None = never answers). Past the list, the last reply repeats."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.clients = []

    def live(self):
        return [c for c in self.clients if c.started and not c.stopped]


BROKER = Broker([0])


class Client:
    def __init__(self, *args, **kwargs):
        if len(BROKER.clients) >= 40:  # _connect_mqtt swallows this
            raise RuntimeError("40 clients built")
        self.started = self.stopped = False
        self.on_connect = self.on_disconnect = self.on_message = None
        BROKER.clients.append(self)

    def username_pw_set(self, *a):
        pass

    def will_set(self, *a, **k):
        pass

    def connect(self, *a, **k):
        pass

    def subscribe(self, *a, **k):
        pass

    def publish(self, *a, **k):
        pass

    def loop_start(self):
        # The broker answers over the network, i.e. not before the
        # supervisor's next wait: see FakeClock.wait.
        self.started = True
        n = len(BROKER.clients) - 1
        self.pending_rc = BROKER.replies[min(n, len(BROKER.replies) - 1)]
        PENDING.append(self)

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        pass


# The plugin refuses to construct without paho; give it this fake.
_client_mod = types.ModuleType("paho.mqtt.client")
_client_mod.Client = Client
_client_mod.CallbackAPIVersion = types.SimpleNamespace(VERSION1=1)
for name, mod in (("paho", types.ModuleType("paho")),
                  ("paho.mqtt", types.ModuleType("paho.mqtt")),
                  ("paho.mqtt.client", _client_mod)):
    sys.modules[name] = mod
sys.modules["paho"].mqtt = sys.modules["paho.mqtt"]
sys.modules["paho.mqtt"].client = _client_mod

try:
    from src.plugin_system.testing.mocks import (
        MockCacheManager, MockDisplayManager, MockPluginManager)
    import manager  # noqa: E402
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)


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


def plugin(replies, clock):
    global BROKER
    BROKER = Broker(replies)
    p = manager.BirdNetGoPlugin("birdnet-go", {"enabled": True, "mqtt": {"enabled": True, "host": "broker"}},
                            MockDisplayManager(), MockCacheManager(), MockPluginManager())
    p.logger = logging.getLogger("test-birdnet-go")
    p.mqtt_stop_event = clock
    return p


# 1. A broker that refuses every login (rc=5, bad credentials).
p = plugin([5], FakeClock(budget=12))
p._mqtt_loop()
attempts = p.mqtt_stop_event.waits.count(5.0)
check("a refused login is redialled one client per attempt",
      len(BROKER.clients) <= attempts + 1, "%d clients, %d attempts" % (len(BROKER.clients), attempts))
check("every refused client is stopped", not BROKER.live(), "%d live" % len(BROKER.live()))
backoffs = [w for w in p.mqtt_stop_event.waits if w != 5.0]
check("retries back off: 1, 2, 4, 8 ...", backoffs[:4] == [1.0, 2.0, 4.0, 8.0], str(backoffs))

# 2. A broker that never answers at all.
p = plugin([None, None, 0], FakeClock(budget=12))
p._mqtt_loop()
check("a silent broker is redialled instead of waited on forever",
      len(BROKER.clients) == 3, "%d clients" % len(BROKER.clients))
check("the silent attempts are stopped", all(c.stopped for c in BROKER.clients[:2]))

# 3. A broker that accepts: one client, kept.
p = plugin([0], FakeClock(budget=20))
p._mqtt_loop()
check("an accepted connection is kept, not redialled", len(BROKER.clients) == 1,
      "%d clients" % len(BROKER.clients))
check("shutting the loop down stops that client", BROKER.clients[0].stopped)

# 4. The connection drops mid-session and comes back.
peak = []


def drop_once(n):
    peak.append(len(BROKER.live()))
    if n == 3 and p.mqtt_client is not None:
        p._on_mqtt_disconnect(p.mqtt_client, None, 1)


p = plugin([0], FakeClock(budget=10, on_wait=drop_once))
p._mqtt_loop()
check("after a drop exactly one new client is dialled", len(BROKER.clients) == 2,
      "%d clients" % len(BROKER.clients))
check("the dropped client is stopped before the new one starts",
      BROKER.clients[0].stopped and max(peak) <= 1, "peak live clients: %s" % max(peak))

# 5. Shutdown releases a live client even with no thread running.
p = plugin([0], FakeClock(budget=1000))
p._connect_mqtt()
p.mqtt_client.loop_start()
p.on_disable()
check("shutdown releases the client", not BROKER.live() and p.mqtt_client is None)

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
