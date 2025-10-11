import requests
import json
import os
import logging
import sys

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define paths relative to plugin directory
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
YTM_AUTH_CONFIG_PATH = os.path.join(PLUGIN_DIR, 'ytm_auth.json')

# YTM Companion App Constants
YTM_APP_ID = "ledmatrixcontroller"
YTM_APP_NAME = "LEDMatrixController"
YTM_APP_VERSION = "1.0.0"

def load_ytm_companion_url():
    """
    Loads YTM_COMPANION_URL from environment variable or prompts user.
    
    Expected environment variable:
    - YTM_COMPANION_URL
    """
    base_url = os.environ.get('YTM_COMPANION_URL')
    
    if not base_url:
        print("\n" + "="*60)
        print("YOUTUBE MUSIC COMPANION SETUP")
        print("="*60)
        print("You need to provide the URL to your YTM Companion server.")
        print("Default: http://localhost:9863")
        print("="*60 + "\n")
        
        base_url = input("Enter YTM Companion URL (or press Enter for default): ").strip()
        if not base_url:
            base_url = "http://localhost:9863"
    
    logging.info(f"YTM Companion URL set to: {base_url}")
    
    # Normalize URL scheme
    if base_url.startswith("ws://"):
        base_url = "http://" + base_url[5:]
    elif base_url.startswith("wss://"):
        base_url = "https://" + base_url[6:]
    
    return base_url

def _request_auth_code(base_url):
    """Requests an authentication code from the YTM Companion server."""
    url = f"{base_url}/api/v1/auth/requestcode"
    payload = {
        "appId": YTM_APP_ID,
        "appName": YTM_APP_NAME,
        "appVersion": YTM_APP_VERSION
    }
    try:
        logging.info(f"Requesting auth code from {url}")
        logging.info(f"Using appId: {YTM_APP_ID}")
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        auth_code = data.get('code')
        if auth_code:
            logging.info(f"✓ Received auth code: {auth_code}")
        else:
            logging.error("Auth code not found in response.")
        return auth_code
    except requests.exceptions.RequestException as e:
        logging.error(f"Error requesting YTM auth code: {e}")
        logging.error("Make sure YTM Companion server is running and accessible.")
        return None
    except json.JSONDecodeError:
        logging.error("Error decoding JSON response when requesting auth code.")
        return None

def _request_auth_token(base_url, code):
    """Requests an authentication token using the provided code."""
    if not code:
        return None
    url = f"{base_url}/api/v1/auth/request"
    payload = {
        "appId": YTM_APP_ID,
        "code": code
    }
    try:
        print("\n" + "="*60)
        print("APPROVAL REQUIRED IN YTM DESKTOP APP")
        print("="*60)
        print("Please check your YouTube Music Desktop App and")
        print("APPROVE the authentication request.")
        print("You have 30 seconds to approve.")
        print("="*60 + "\n")
        
        logging.info("Requesting auth token...")
        response = requests.post(url, json=payload, timeout=35)
        response.raise_for_status()
        data = response.json()
        token = data.get('token')
        if token:
            logging.info("✓ Successfully received YTM auth token.")
        else:
            logging.warning("Auth token not found in response.")
        return token
    except requests.exceptions.Timeout:
        logging.error("✗ Timeout waiting for approval. Did you approve in YTM Desktop App?")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error requesting YTM auth token: {e}")
        return None
    except json.JSONDecodeError:
        logging.error("Error decoding JSON response when requesting auth token.")
        return None

def save_ytm_token(token):
    """Saves the YTM token to ytm_auth.json in plugin directory."""
    if not token:
        logging.warning("No YTM token provided to save.")
        return False

    token_data = {"YTM_COMPANION_TOKEN": token}

    try:
        with open(YTM_AUTH_CONFIG_PATH, 'w') as f:
            json.dump(token_data, f, indent=4)
        logging.info(f"✓ YTM token saved to: {YTM_AUTH_CONFIG_PATH}")
        return True
    except Exception as e:
        logging.error(f"Error saving YTM token: {e}")
        return False

if __name__ == "__main__":
    logging.info("Starting YTM Authentication Process...")
    logging.info(f"Plugin directory: {PLUGIN_DIR}")
    logging.info(f"Auth token will be saved to: {YTM_AUTH_CONFIG_PATH}")

    ytm_url = load_ytm_companion_url()
    if not ytm_url:
        logging.error("Could not determine YTM Companion URL. Exiting.")
        sys.exit(1)

    auth_code = _request_auth_code(ytm_url)
    if not auth_code:
        logging.error("Failed to get YTM auth code. Exiting.")
        logging.error("\nTroubleshooting:")
        logging.error("1. Ensure YTM Companion server is running")
        logging.error("2. Check the URL is correct")
        logging.error("3. Verify firewall allows the connection")
        sys.exit(1)
    
    auth_token = _request_auth_token(ytm_url, auth_code)
    if auth_token:
        if save_ytm_token(auth_token):
            print("\n" + "="*60)
            print("SUCCESS! YouTube Music is now authenticated.")
            print(f"Token saved to: {YTM_AUTH_CONFIG_PATH}")
            print("="*60)
        else:
            logging.error("YTM authentication successful, but FAILED to save token.")
            sys.exit(1)
    else:
        logging.error("Failed to get YTM auth token. Authentication unsuccessful.")
        logging.error("\nTroubleshooting:")
        logging.error("1. Did you approve the request in YTM Desktop App?")
        logging.error("2. Check the approval prompt didn't time out")
        logging.error("3. Try running this script again")
        sys.exit(1)

    logging.info("YTM Authentication Process Finished.")

