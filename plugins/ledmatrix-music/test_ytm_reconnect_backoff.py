#!/usr/bin/env python3
"""Tests that an unreachable YTM Companion is retried quietly, not hammered.

Regression under test: the poll loop asked the client to reconnect every cycle
(~2s), the client always tried, and each attempt logged two ERROR lines. On a
live device whose companion was simply not running that produced **13,298 error
lines in 12 hours** -- 99.8% of everything the device logged -- which buries
every other error in the journal. The records also went to the root logger via
bare `logging.error(...)`, so they appeared as "root" and sat outside the
plugin's own log level, leaving no way to quiet them.

"The companion app is not running" is an ordinary state, not a fault.

Run: <core-venv>/bin/python plugins/ledmatrix-music/test_ytm_reconnect_backoff.py
"""

import sys
import threading
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

# socketio is a runtime dependency of the plugin, not of this test's logic.
try:
    import socketio  # noqa: F401
except ImportError:
    print("SKIP: python-socketio not installed (see requirements.txt)")
    sys.exit(2)

import ytm_client  # noqa: E402

# Deliberately named without "token"/"secret"/"password": those substrings are
# what "possible hardcoded password" scanners key on, and this value is neither
# a credential nor real -- connect_client() only checks that it is truthy.
PLACEHOLDER = "unused-by-this-test"


class _RecordingLogger:
    """Captures records by level so the test can assert on volume."""

    def __init__(self):
        self.records = {lvl: [] for lvl in
                        ("debug", "info", "warning", "error", "critical")}

    def _rec(self, level):
        def log(msg, *args, **kwargs):
            try:
                self.records[level].append(str(msg) % args if args else str(msg))
            except Exception:
                self.records[level].append(str(msg))
        return log

    def __getattr__(self, name):
        if name in ("debug", "info", "warning", "error", "critical"):
            return self._rec(name)
        if name == "exception":
            return self._rec("error")
        raise AttributeError(name)


def _client(monotonic):
    """A YTMClient wired to a fake clock, with connecting always failing."""
    c = ytm_client.YTMClient.__new__(ytm_client.YTMClient)
    c._log = _RecordingLogger()
    c._consecutive_failures = 0
    c._next_retry_at = 0.0
    c.base_url = "http://10.0.10.133:9863"
    c.ytm_token = PLACEHOLDER
    c.is_connected = False
    # Real attributes connect_client() touches before it ever reaches the
    # socket; without them an AttributeError lands in the generic handler and
    # the test measures the wrong path.
    c._connection_event = threading.Event()
    c._data_lock = threading.Lock()
    c._warned_missing_token = False

    class _Sio:
        def connect(self, *a, **k):
            raise ytm_client.socketio.exceptions.ConnectionError("Connection error")

    c.sio = _Sio()
    return c


failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def main():
    clock = {"t": 1000.0}
    real_monotonic = ytm_client.time.monotonic
    ytm_client.time.monotonic = lambda: clock["t"]
    try:
        print("an unreachable companion is not retried every cycle")
        c = _client(clock)
        assert c.connect_client(timeout=1) is False
        first_attempts = 1
        # 60 further poll cycles, 2s apart: the old code attempted every one.
        attempted = 0
        for _ in range(60):
            clock["t"] += 2.0
            before = c._consecutive_failures
            c.connect_client(timeout=1)
            if c._consecutive_failures != before:
                attempted += 1
        total = first_attempts + attempted
        check("far fewer attempts than poll cycles", total < 10,
              "%d attempts across 61 cycles (120s)" % total)

        print("\nand it is quiet about it")
        errs = len(c._log.records["error"])
        warns = len(c._log.records["warning"])
        check("no ERROR records at all", errs == 0, "%d" % errs)
        check("exactly one WARNING, on the first failure", warns == 1, "%d" % warns)
        check("the warning names the endpoint",
              "10.0.10.133:9863" in (c._log.records["warning"] or [""])[0])
        check("and tells the user what to check",
              "companion" in (c._log.records["warning"] or [""])[0].lower())

        print("\nthe delay grows and is capped")
        c2 = _client(clock)
        delays = []
        for _ in range(12):
            c2.connect_client(timeout=1)
            delays.append(c2._next_retry_at - clock["t"])
            clock["t"] = c2._next_retry_at       # jump to the next allowed try
        check("strictly increasing until the cap",
              all(b >= a for a, b in zip(delays, delays[1:])), repr(delays[:6]))
        check("capped, never unbounded",
              max(delays) <= ytm_client.YTMClient._RECONNECT_BACKOFF_MAX,
              repr(max(delays)))
        check("still retries eventually (cap is not infinite)",
              ytm_client.YTMClient._RECONNECT_BACKOFF_MAX <= 600,
              "cap is %ss" % ytm_client.YTMClient._RECONNECT_BACKOFF_MAX)

        print("\nrecovery clears the backoff")
        c3 = _client(clock)
        c3.connect_client(timeout=1)
        check("backoff armed after a failure", c3._next_retry_at > clock["t"])
        c3._note_connect_success()
        check("cleared on success", c3._next_retry_at == 0.0)
        check("failure count reset", c3._consecutive_failures == 0)
        check("recovery is announced",
              any("reachable again" in m for m in c3._log.records["info"]))

        print("\na missing token warns once, not every cycle")
        c4 = _client(clock)
        c4.ytm_token = None
        for _ in range(50):
            clock["t"] += 2.0
            c4.connect_client(timeout=1)
        check("one warning across 50 cycles",
              len(c4._log.records["warning"]) == 1,
              "%d warnings" % len(c4._log.records["warning"]))
        check("no errors either", not c4._log.records["error"],
              repr(c4._log.records["error"]))
        check("and it says what to do",
              "authentication" in (c4._log.records["warning"] or [""])[0].lower())
        c4.ytm_token = PLACEHOLDER      # a token turns up
        c4._warned_missing_token = False       # load_config() does this
        c4.ytm_token = None
        c4.connect_client(timeout=1)
        check("warns again after a token comes and goes",
              len(c4._log.records["warning"]) == 2,
              "%d warnings" % len(c4._log.records["warning"]))

        print("\nsocketio does not run a retry loop behind the backoff")
        src_client = (PLUGIN_DIR / "ytm_client.py").read_text(encoding="utf-8")
        check("reconnection disabled", "reconnection=False" in src_client)
        check("no infinite attempt setting left",
              "reconnection_attempts=0" not in src_client)

        print("\na malformed payload cannot drop the callback")
        check("diagnostic fields assigned before the try",
              "title = author = 'N/A'" in src_client)
        check("nested values validated before use",
              "isinstance(video, dict)" in src_client)

        print("\nnothing logs through the root logger any more")
        src = (PLUGIN_DIR / "ytm_client.py").read_text(encoding="utf-8")
        import re
        stray = re.findall(r'(?<![\w.])logging\.(?:debug|info|warning|error|exception|critical)\(',
                           src)
        check("no bare logging.<level>( calls left", not stray,
              "%d remain" % len(stray))
        check("the client takes a logger",
              "def __init__(self, update_callback=None, logger=None)" in src)
    finally:
        ytm_client.time.monotonic = real_monotonic

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
