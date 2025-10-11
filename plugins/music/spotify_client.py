import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import json
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Suppress spotipy.cache_handler warnings
logging.getLogger('spotipy.cache_handler').setLevel(logging.ERROR)

# Define paths relative to plugin directory
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SPOTIFY_AUTH_CACHE_PATH = os.path.join(PLUGIN_DIR, 'spotify_auth.json')

class SpotifyClient:
    """Spotify client for the music plugin with plugin-local authentication."""
    
    def __init__(self, client_id=None, client_secret=None, redirect_uri=None):
        """
        Initialize Spotify client.
        
        Args:
            client_id: Spotify Client ID (from environment or config)
            client_secret: Spotify Client Secret (from environment or config)
            redirect_uri: Spotify Redirect URI (from environment or config)
        """
        self.client_id = client_id or os.environ.get('SPOTIFY_CLIENT_ID')
        self.client_secret = client_secret or os.environ.get('SPOTIFY_CLIENT_SECRET')
        self.redirect_uri = redirect_uri or os.environ.get('SPOTIFY_REDIRECT_URI')
        self.scope = "user-read-currently-playing user-read-playback-state"
        self.sp = None
        
        if self.client_id and self.client_secret and self.redirect_uri:
            self._authenticate()
        else:
            logging.warning("Spotify credentials not provided. Spotify client will not be functional.")

    def _authenticate(self):
        """Initializes Spotipy with SpotifyOAuth, relying on cached token."""
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            logging.warning("Cannot authenticate Spotify: credentials missing.")
            return

        logging.info(f"SpotifyClient using cache path: {SPOTIFY_AUTH_CACHE_PATH}")
        
        if os.path.exists(SPOTIFY_AUTH_CACHE_PATH):
            logging.info(f"Cache file exists at {SPOTIFY_AUTH_CACHE_PATH}")
        else:
            logging.warning(f"Cache file does not exist at {SPOTIFY_AUTH_CACHE_PATH}")
            logging.warning("Run authenticate_spotify.py in the plugin directory to generate it.")

        try:
            auth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                cache_path=SPOTIFY_AUTH_CACHE_PATH,
                open_browser=False
            )
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            
            # Verify token is valid
            self.sp.current_user()
            logging.info("Spotify client initialized and authenticated using cached token.")
        except Exception as e:
            logging.warning(f"Spotify authentication failed: {e}")
            logging.warning("Run authenticate_spotify.py in the plugin directory if needed.")
            self.sp = None

    def is_authenticated(self):
        """Checks if the client is authenticated and usable."""
        return self.sp is not None

    def get_current_playback(self):
        """Fetches current playback information from Spotify."""
        if not self.is_authenticated():
            return None

        try:
            return self.sp.current_playback()
        except spotipy.exceptions.SpotifyException as e:
            logging.error(f"Spotify API error: {e}")
            if e.http_status in (401, 403):
                logging.warning("Spotify token may be expired or revoked.")
                logging.warning("Please re-run authenticate_spotify.py in the plugin directory.")
                self.sp = None
            return None
        except Exception as e:
            logging.error(f"Unexpected error fetching Spotify playback: {e}")
            return None

    def get_current_track(self):
        """Fetches the currently playing track from Spotify."""
        playback = self.get_current_playback()
        if playback and playback.get('item'):
            return playback
        return None

