import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import json
import os
import sys

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define paths relative to plugin directory
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SPOTIFY_AUTH_CACHE_PATH = os.path.join(PLUGIN_DIR, 'spotify_auth.json')

SCOPE = "user-read-currently-playing user-read-playback-state"

def load_spotify_credentials():
    """
    Loads Spotify credentials from environment variables or prompts user.
    
    Expected environment variables:
    - SPOTIFY_CLIENT_ID
    - SPOTIFY_CLIENT_SECRET
    - SPOTIFY_REDIRECT_URI
    """
    client_id = os.environ.get('SPOTIFY_CLIENT_ID')
    client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
    redirect_uri = os.environ.get('SPOTIFY_REDIRECT_URI')
    
    # If not in environment, prompt user
    if not client_id:
        print("\n" + "="*60)
        print("SPOTIFY CREDENTIALS SETUP")
        print("="*60)
        print("You need to provide your Spotify API credentials.")
        print("Get them from: https://developer.spotify.com/dashboard")
        print("="*60 + "\n")
        
        client_id = input("Enter Spotify Client ID: ").strip()
        client_secret = input("Enter Spotify Client Secret: ").strip()
        redirect_uri = input("Enter Redirect URI (e.g., http://localhost:8888/callback): ").strip()
    
    if not all([client_id, client_secret, redirect_uri]):
        logging.error("One or more Spotify credentials missing.")
        return None, None, None
    
    return client_id, client_secret, redirect_uri

if __name__ == "__main__":
    logging.info("Starting Spotify Authentication Process...")
    logging.info(f"Plugin directory: {PLUGIN_DIR}")
    logging.info(f"Auth cache will be saved to: {SPOTIFY_AUTH_CACHE_PATH}")

    client_id, client_secret, redirect_uri = load_spotify_credentials()

    if not all([client_id, client_secret, redirect_uri]):
        logging.error("Could not load Spotify credentials. Exiting.")
        sys.exit(1)

    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_path=SPOTIFY_AUTH_CACHE_PATH,
        open_browser=False
    )

    # Step 1: Get the authorization URL
    auth_url = sp_oauth.get_authorize_url()
    print("-" * 60)
    print("SPOTIFY AUTHORIZATION NEEDED:")
    print("1. Please visit this URL in a browser (on any device):")
    print(f"   {auth_url}")
    print("2. Authorize the application.")
    print("3. You will be redirected to a URL (likely showing an error).")
    print("   Copy that FULL redirected URL.")
    print("-" * 60)

    # Step 2: Get the redirected URL from the user
    redirected_url = input("\n4. Paste the full redirected URL here and press Enter: ").strip()

    if not redirected_url:
        logging.error("No redirected URL provided. Exiting.")
        sys.exit(1)

    # Step 3: Parse the code from the redirected URL
    try:
        if "?code=" in redirected_url:
            auth_code = redirected_url.split("?code=")[1].split("&")[0]
        elif "&code=" in redirected_url:
            auth_code = redirected_url.split("&code=")[1].split("&")[0]
        else:
            logging.error("Could not find 'code=' in the redirected URL.")
            logging.error(f"Received URL: {redirected_url}")
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Error parsing authorization code: {e}")
        logging.error(f"Received URL: {redirected_url}")
        sys.exit(1)

    # Step 4: Get the access token using the code and cache it
    try:
        token_info = sp_oauth.get_access_token(auth_code, check_cache=False)
        if token_info:
            logging.info(f"✓ Spotify authentication successful!")
            logging.info(f"✓ Token cached at: {SPOTIFY_AUTH_CACHE_PATH}")
            print("\n" + "="*60)
            print("SUCCESS! Spotify is now authenticated.")
            print(f"Token saved to: {SPOTIFY_AUTH_CACHE_PATH}")
            print("="*60)
        else:
            logging.error("Failed to obtain Spotify token.")
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Error obtaining Spotify access token: {e}")
        logging.error("This can happen if the code is incorrect, expired, or already used.")
        sys.exit(1)

    logging.info("Spotify Authentication Process Finished.")

