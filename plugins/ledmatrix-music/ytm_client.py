import socketio
import logging
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Ensure application-level logging is configured (as it is)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Reduce verbosity of socketio and engineio libraries
logging.getLogger('socketio.client').setLevel(logging.WARNING)
logging.getLogger('socketio.server').setLevel(logging.WARNING)
logging.getLogger('engineio.client').setLevel(logging.WARNING)
logging.getLogger('engineio.server').setLevel(logging.WARNING)

# Define paths - must work from plugin directory
LEDMATRIX_ROOT = os.environ.get('LEDMATRIX_ROOT')
if not LEDMATRIX_ROOT:
    # Auto-detect: plugins/ledmatrix-music/../.. = LEDMatrix root
    LEDMATRIX_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CONFIG_DIR = os.path.join(LEDMATRIX_ROOT, 'config')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')
# Resolve to an absolute path
CONFIG_PATH = os.path.abspath(CONFIG_PATH)

# Path for the separate YTM authentication token file
YTM_AUTH_CONFIG_PATH = os.path.join(CONFIG_DIR, 'ytm_auth.json')
YTM_AUTH_CONFIG_PATH = os.path.abspath(YTM_AUTH_CONFIG_PATH)

class YTMClient:
    # Reconnect backoff. The companion app not running is an ordinary state --
    # the user simply does not have YouTube Music open -- but the poll loop
    # asked for a reconnect every cycle regardless, so an unreachable server
    # was retried every ~2s forever. Measured on a live device that was 13,298
    # error lines in 12 hours, roughly 34,000 a day, which buries every other
    # error in the journal.
    _RECONNECT_BACKOFF_BASE = 5.0     # seconds, after the first failure
    _RECONNECT_BACKOFF_MAX = 300.0    # cap: retry at least every 5 minutes

    def __init__(self, update_callback=None, logger=None):
        # Default to this module's logger, never the root one. Logging through
        # `self._log.error(...)` put these records on the root logger, which is
        # why they appeared as "root" in the journal: outside the plugin's
        # logger, so a user could not lower their level to quiet them.
        self._log = logger or logging.getLogger(__name__)
        self._consecutive_failures = 0
        self._next_retry_at = 0.0
        self.base_url = None
        self.ytm_token = None
        self.load_config() # Loads URL and token
        self.sio = socketio.Client(
            logger=False, 
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=0,  # Infinite attempts
            reconnection_delay=1,     # Initial delay in seconds
            reconnection_delay_max=10 # Maximum delay in seconds
        )
        self.last_known_track_data = None
        self.is_connected = False
        self._data_lock = threading.Lock()
        self._connection_event = threading.Event()
        self.external_update_callback = update_callback
        # For offloading external_update_callback to prevent blocking socketio thread
        self._callback_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ytm_callback_worker')

        @self.sio.event(namespace='/api/v1/realtime')
        def connect():
            self._log.info(f"Successfully connected to YTM Companion Socket.IO server at {self.base_url} on namespace /api/v1/realtime")
            self.is_connected = True
            self._connection_event.set()

        @self.sio.event(namespace='/api/v1/realtime')
        def connect_error(data):
            # Debug only: connect_client() reports the failure once, with
            # backoff. Logging here as well produced two ERROR lines per
            # attempt for a condition that is usually just "app not running".
            self._log.debug("YTM Companion Socket.IO connection failed for namespace /api/v1/realtime: %s", data)
            self.is_connected = False
            self._connection_event.set()

        @self.sio.event(namespace='/api/v1/realtime')
        def disconnect():
            self._log.info(f"Disconnected from YTM Companion Socket.IO server at {self.base_url} on namespace /api/v1/realtime")
            self.is_connected = False

        @self.sio.on('state-update', namespace='/api/v1/realtime')
        def on_state_update(data):
            # --- TEMPORARY DIAGNOSTIC LOGGING ---
            # --- END TEMPORARY DIAGNOSTIC LOGGING ---

            # Always update the full last_known_track_data for polling purposes
            with self._data_lock:
                self.last_known_track_data = data

            # Rich diagnostic logging of incoming event
            try:
                title = data.get('video', {}).get('title', 'N/A') if isinstance(data, dict) else 'N/A'
                author = data.get('video', {}).get('author', 'N/A') if isinstance(data, dict) else 'N/A'
                is_playing = (data.get('player', {}).get('trackState') == 1) if isinstance(data, dict) else None
                self._log.debug(f"[YTMClient] socket event received: title='{title}', artist='{author}', is_playing={is_playing}")
            except Exception:
                pass

            if self.external_update_callback:
                self._log.debug(f"--> Submitting YTM external_update_callback for title: {title} to executor")
                try:
                    # Offload the callback to the executor
                    self._callback_executor.submit(self.external_update_callback, data)
                except Exception as cb_ex:
                    self._log.error(f"Error submitting YTMClient external_update_callback to executor: {cb_ex}")

    def load_config(self):
        default_url = "http://localhost:9863"
        self.base_url = default_url # Start with default
        
        # Load base_url from main config.json
        if not os.path.exists(CONFIG_PATH):
            self._log.warning(f"Main config file not found at {CONFIG_PATH}. Using default YTM URL: {self.base_url}")
        else:
            try:
                with open(CONFIG_PATH, 'r') as f:
                    loaded_config = json.load(f)
                    # Prefer plugin-scoped config
                    plugin_cfg = loaded_config.get("ledmatrix-music", {})
                    self.base_url = plugin_cfg.get("ytm_companion_url", default_url)
                    if not self.base_url:
                        self._log.warning("ytm_companion_url missing or empty in config.json ledmatrix-music section, using default.")
                        self.base_url = default_url
            except json.JSONDecodeError:
                self._log.error(f"Error decoding JSON from main config {CONFIG_PATH}. Using default YTM URL.")
            except Exception as e:
                self._log.error(f"Error loading ytm_companion_url from main config {CONFIG_PATH}: {e}. Using default YTM URL.")

        self._log.debug(f"YTM Companion URL set to: {self.base_url}")

        if self.base_url and self.base_url.startswith("ws://"):
            self.base_url = "http://" + self.base_url[5:]
        elif self.base_url and self.base_url.startswith("wss://"):
            self.base_url = "https://" + self.base_url[6:]

        # Load ytm_token from ytm_auth.json
        self.ytm_token = None # Reset token before trying to load
        if os.path.exists(YTM_AUTH_CONFIG_PATH):
            try:
                with open(YTM_AUTH_CONFIG_PATH, 'r') as f:
                    auth_data = json.load(f)
                    self.ytm_token = auth_data.get("YTM_COMPANION_TOKEN")
                if self.ytm_token:
                    self._log.info(f"YTM Companion token loaded from {YTM_AUTH_CONFIG_PATH}.")
                else:
                    self._log.warning(f"YTM_COMPANION_TOKEN not found in {YTM_AUTH_CONFIG_PATH}. YTM features may be limited or disabled.")
            except json.JSONDecodeError:
                self._log.error(f"Error decoding JSON from YTM auth file {YTM_AUTH_CONFIG_PATH}. YTM features may be limited or disabled.")
            except Exception as e:
                self._log.error(f"Error loading YTM auth config {YTM_AUTH_CONFIG_PATH}: {e}. YTM features may be limited or disabled.")
        else:
            self._log.warning(f"YTM auth file not found at {YTM_AUTH_CONFIG_PATH}. Run the authentication script to generate it. YTM features may be limited or disabled.")

    def _note_connect_failure(self, reason):
        """Record a failed attempt and schedule the next one.

        The first failure is worth a warning -- something the user asked for is
        not working. Repeats are not: they say nothing new, and at one every
        couple of seconds they drown the log. Subsequent failures go to debug
        and the retry interval grows, so a companion that is simply not running
        costs a handful of lines an hour instead of thousands.
        """
        self._consecutive_failures += 1
        delay = min(
            self._RECONNECT_BACKOFF_BASE * (2 ** (self._consecutive_failures - 1)),
            self._RECONNECT_BACKOFF_MAX,
        )
        self._next_retry_at = time.monotonic() + delay
        if self._consecutive_failures == 1:
            self._log.warning(
                "Could not reach the YTM Companion at %s (%s). Is YouTube Music "
                "Desktop running with the companion server enabled? Retrying in "
                "%.0fs, backing off to %.0fs while it stays unreachable.",
                self.base_url, reason, delay, self._RECONNECT_BACKOFF_MAX)
        else:
            self._log.debug(
                "YTM still unreachable (%s), attempt %d; next retry in %.0fs",
                reason, self._consecutive_failures, delay)

    def _note_connect_success(self):
        """Clear the backoff, and say so if we had been failing."""
        if self._consecutive_failures:
            self._log.info("YTM Companion reachable again after %d failed attempt(s)",
                           self._consecutive_failures)
        self._consecutive_failures = 0
        self._next_retry_at = 0.0

    def connect_client(self, timeout=10):
        if not self.ytm_token:
            self._log.warning("No YTM token loaded. Cannot connect to YTM Socket.IO. Run authentication script.")
            self.is_connected = False
            return False

        if self.is_connected:
            self._log.debug("YTM client already connected.")
            return True

        # Honour the backoff. The poll loop asks every cycle whether it can
        # reconnect; without this it would retry every couple of seconds for as
        # long as the companion stays down.
        remaining = self._next_retry_at - time.monotonic()
        if remaining > 0:
            self._log.debug("Skipping YTM reconnect for another %.0fs (backing off)",
                            remaining)
            return False

        self._log.debug("Attempting to connect to YTM Socket.IO server: %s", self.base_url)
        auth_payload = {"token": self.ytm_token}

        try:
            self._connection_event.clear()
            self.sio.connect(
                self.base_url,
                transports=['websocket'],
                wait_timeout=timeout,
                namespaces=['/api/v1/realtime'],
                auth=auth_payload
            )
            event_wait_timeout = timeout + 5
            if not self._connection_event.wait(timeout=event_wait_timeout):
                self.is_connected = False
                self._note_connect_failure(
                    f"no connection event within {event_wait_timeout}s")
                return False
            if self.is_connected:
                self._note_connect_success()
            else:
                # connect_error fired; it recorded the reason.
                self._note_connect_failure("server rejected the connection")
            return self.is_connected
        except socketio.exceptions.ConnectionError as e:
            self.is_connected = False
            self._note_connect_failure(e)
            return False
        except Exception as e:
            self.is_connected = False
            self._log.error("Unexpected error during YTM Socket.IO connection: %s",
                            e, exc_info=True)
            self._note_connect_failure(e)
            return False

    def is_available(self):
        if not self.ytm_token:
            return False
        return self.is_connected

    def get_current_track(self):
        if not self.is_connected:
            return None

        with self._data_lock:
            if self.last_known_track_data:
                return self.last_known_track_data
            else:
                return None

    def disconnect_client(self):
        if self.is_connected:
            self.sio.disconnect()
            self._log.info("YTM Socket.IO client disconnected.")
            self.is_connected = False
        else:
            self._log.debug("YTM Socket.IO client already disconnected or not connected.")

    def shutdown(self):
        """Shuts down the callback executor."""
        self._log.info("YTMClient: Shutting down callback executor...")
        if self._callback_executor:
            self._callback_executor.shutdown(wait=True) # Wait for pending tasks to complete
            self._callback_executor = None # Clear reference
            self._log.info("YTMClient: Callback executor shut down.")
        else:
            self._log.debug("YTMClient: Callback executor already None or not initialized.")

# Example Usage (for testing - needs to be adapted for Socket.IO async nature)
# if __name__ == '__main__':
# client = YTMClient()
# if client.connect_client(): 
# print("YTM Server is available (Socket.IO).")
# try:
# for _ in range(10): # Poll for a few seconds
# track = client.get_current_track()
# if track:
# print(json.dumps(track, indent=2))
# else:
# print("No track currently playing or error fetching (Socket.IO).")
# time.sleep(2)
# finally:
# client.disconnect_client()
# else:
# print(f"YTM Server not available at {client.base_url} (Socket.IO). Is YTMD running with companion server enabled and token generated?")
