#!/usr/bin/env python3
"""The plugin must never start an interactive OAuth flow, and fetches from now.

Regressions under test:

1. When credentials.json existed and the saved token could not be refreshed,
   _authenticate() -- called from __init__, i.e. at plugin load -- ran
   InstalledAppFlow.run_local_server(port=0). On a headless Pi that waits for
   a browser callback that never comes, and plugin load has no timeout. Sign-in
   belongs to the two-step web action in calendar_registration.py.
2. With no service, display() drew "No Events", indistinguishable from an
   empty calendar. It now draws an "Auth needed" state.
3. update() asked the API for events from the start of today, so events that
   had already ended used up max_events and pushed upcoming ones off.

Run: <core-venv>/bin/python plugins/calendar/test_no_interactive_auth.py
"""

import logging
import os
import pickle  # nosec B403 - writes a fake token.pickle, the format the plugin reads
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "src" / "plugin_system" / "base_plugin.py").exists():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

try:
    import pytz
    from google_auth_oauthlib.flow import InstalledAppFlow
    from PIL import Image, ImageChops, ImageDraw
    import manager as cal
except ImportError as exc:
    print("SKIP: missing dependency (%s)" % exc)
    sys.exit(2)

logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


class FakeCreds:
    """A saved token whose refresh fails (revoked / expired refresh token)."""
    valid = False
    expired = True
    refresh_token = "stale"  # nosec B105 - fake token for the test double

    def refresh(self, request):
        raise RuntimeError("invalid_grant: Token has been expired or revoked.")


class FakeDM:
    width, height = 128, 32

    def __init__(self):
        self.image = Image.new("RGB", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.image)
        self.matrix = type("M", (), {"width": self.width, "height": self.height})()

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.image)

    def update_display(self):
        pass


def _bare_plugin():
    plugin = cal.CalendarPlugin.__new__(cal.CalendarPlugin)
    plugin.display_manager = FakeDM()
    plugin.logger = logging.getLogger("test")
    plugin.plugin_id = "calendar"
    plugin.datetime_font = None
    plugin.title_font = None
    plugin._load_fonts = lambda: None
    plugin.events = []
    return plugin


def main():
    os.chdir(str(CORE))

    print("a failed token refresh does not start an interactive flow")
    flow_calls = []

    class _NoFlow:
        def run_local_server(self, *a, **kw):
            flow_calls.append("run_local_server")
            raise RuntimeError("interactive flow started")

    def _fake_from_secrets(*a, **kw):
        flow_calls.append("from_client_secrets_file")
        return _NoFlow()

    # Defined on the Flow base class; shadow it on the subclass and delete the
    # shadow afterwards.
    own = "from_client_secrets_file" in InstalledAppFlow.__dict__
    original = InstalledAppFlow.__dict__.get("from_client_secrets_file")
    InstalledAppFlow.from_client_secrets_file = staticmethod(_fake_from_secrets)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            creds_path = os.path.join(tmp, "credentials.json")
            token_path = os.path.join(tmp, "token.pickle")
            with open(creds_path, "w") as fh:
                fh.write("{}")
            with open(token_path, "wb") as fh:
                pickle.dump(FakeCreds(), fh)  # nosec B301 # nosemgrep - test double written to a temp dir
            plugin = _bare_plugin()
            plugin.credentials_file = creds_path
            plugin.token_file = token_path
            plugin.service = None
            ok = plugin._authenticate()
    finally:
        if own:
            InstalledAppFlow.from_client_secrets_file = original
        else:
            del InstalledAppFlow.from_client_secrets_file
    check("authentication reports failure", ok is False)
    check("no InstalledAppFlow was built or run (%s)" % flow_calls, flow_calls == [])

    print("\nwith no service the panel says auth is needed")
    plugin = _bare_plugin()
    plugin.service = None
    plugin._display_no_events()
    no_events = plugin.display_manager.image.copy()
    plugin.display(force_clear=False)
    shown = plugin.display_manager.image.copy()
    check("something is drawn", shown.getbbox() is not None)
    check("the frame is not the 'No Events' frame",
          ImageChops.difference(no_events, shown).getbbox() is not None)

    print("\nupdate() fetches events that have not ended yet")
    captured = {}

    class _Req:
        def execute(self):
            return {"items": []}

    class _Events:
        def list(self, **kw):
            captured.update(kw)
            return _Req()

    class _Service:
        def events(self):
            return _Events()

    class _Cache:
        def get(self, key, max_age=None):
            return None

        def set(self, *a, **kw):
            pass

    plugin = _bare_plugin()
    plugin.service = _Service()
    plugin.cache_manager = _Cache()
    plugin.calendars = ["primary"]
    plugin.max_events = 3
    plugin.show_all_day = True
    plugin.update_interval = 3600
    # A zone far from UTC, so start-of-today is hours from now.
    plugin.timezone = pytz.timezone("Pacific/Kiritimati")
    plugin.update()
    time_min = captured.get("timeMin", "")
    try:
        sent = datetime.strptime(time_min, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        delta = abs((datetime.now(timezone.utc) - sent).total_seconds())
    except ValueError:
        delta = None
    check("timeMin is now, not start of today (%r)" % time_min,
          delta is not None and delta < 120)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
