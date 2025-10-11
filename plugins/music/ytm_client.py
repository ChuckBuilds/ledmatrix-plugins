import socketio
import logging
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

# Reduce verbosity of socketio libraries
logging.getLogger('socketio.client').setLevel(logging.WARNING)
logging.getLogger('socketio.server').setLevel(logging.WARNING)
logging.getLogger('engineio.client').setLevel(logging.WARNING)
logging.getLogger('engineio.server').setLevel(logging.WARNING)

# Define paths relative to plugin directory
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
YTM_AUTH_CONFIG_PATH = os.path.join(PLUGIN_DIR, 'ytm_auth.json')

class YTMClient:
    """YouTube Music client for the music plugin with plugin-local authentication."""
    
    def __init__(self, base_url=None, update_callback=None):
        """
        Initialize YTM client.
        
        Args:
            base_url: YTM Companion server URL (from config or environment)
            update_callback: Optional callback for state updates
        """
        self.base_url = base_url or os.environ.get('YTM_COMPANION_URL', 'http://localhost:9863')
        self.ytm_token = None
        self._load_token()
        
        self.sio = socketio.Client(
            logger=False, 
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=0,  # Infinite attempts
            reconnection_delay=1,
            reconnection_delay_max=10
        )
        
        self.last_known_track_data = None
        self.is_connected = False
        self._data_lock = threading.Lock()
        self._connection_event = threading.Event()
        self.external_update_callback = update_callback
        self._callback_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ytm_callback_worker')

        # Normalize URL scheme
        if self.base_url.startswith("ws://"):
            self.base_url = "http://" + self.base_url[5:]
        elif self.base_url.startswith("wss://"):
            self.base_url = "https://" + self.base_url[6:]

        # Setup Socket.IO event handlers
        @self.sio.event(namespace='/api/v1/realtime')
        def connect():
            logging.info(f"Connected to YTM Companion at {self.base_url}")
            self.is_connected = True
            self._connection_event.set()

        @self.sio.event(namespace='/api/v1/realtime')
        def connect_error(data):
            logging.error(f"YTM connection failed: {data}")
            self.is_connected = False
            self._connection_event.set()

        @self.sio.event(namespace='/api/v1/realtime')
        def disconnect():
            logging.info(f"Disconnected from YTM Companion")
            self.is_connected = False

        @self.sio.on('state-update', namespace='/api/v1/realtime')
        def on_state_update(data):
            with self._data_lock:
                self.last_known_track_data = data

            if self.external_update_callback:
                try:
                    self._callback_executor.submit(self.external_update_callback, data)
                except Exception as e:
                    logging.error(f"Error in YTM callback: {e}")

    def _load_token(self):
        """Load YTM authentication token from plugin directory."""
        self.ytm_token = None
        
        if os.path.exists(YTM_AUTH_CONFIG_PATH):
            try:
                with open(YTM_AUTH_CONFIG_PATH, 'r') as f:
                    auth_data = json.load(f)
                    self.ytm_token = auth_data.get("YTM_COMPANION_TOKEN")
                
                if self.ytm_token:
                    logging.info(f"YTM token loaded from {YTM_AUTH_CONFIG_PATH}")
                else:
                    logging.warning(f"YTM token not found in {YTM_AUTH_CONFIG_PATH}")
            except Exception as e:
                logging.error(f"Error loading YTM token: {e}")
        else:
            logging.warning(f"YTM auth file not found at {YTM_AUTH_CONFIG_PATH}")
            logging.warning("Run authenticate_ytm.py in the plugin directory to generate it.")

    def connect_client(self, timeout=10):
        """Connect to YTM Companion server."""
        if not self.ytm_token:
            logging.warning("No YTM token. Cannot connect. Run authenticate_ytm.py.")
            return False

        if self.is_connected:
            logging.debug("YTM client already connected.")
            return True

        logging.info(f"Connecting to YTM server: {self.base_url}")
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
            
            if not self._connection_event.wait(timeout=timeout + 5):
                logging.warning(f"YTM connection timeout")
                self.is_connected = False
                return False
            
            return self.is_connected
        except socketio.exceptions.ConnectionError as e:
            logging.error(f"YTM connection error: {e}")
            self.is_connected = False
            return False
        except Exception as e:
            logging.error(f"Unexpected YTM connection error: {e}")
            self.is_connected = False
            return False

    def is_available(self):
        """Check if YTM client is available and connected."""
        return self.ytm_token is not None and self.is_connected

    def get_current_track(self):
        """Get current track information."""
        if not self.is_connected:
            return None

        with self._data_lock:
            return self.last_known_track_data

    def disconnect_client(self):
        """Disconnect from YTM server."""
        if self.is_connected:
            self.sio.disconnect()
            logging.info("YTM client disconnected.")
            self.is_connected = False

    def shutdown(self):
        """Shutdown callback executor."""
        logging.info("Shutting down YTM client...")
        if self._callback_executor:
            self._callback_executor.shutdown(wait=True)
            self._callback_executor = None

