#!/usr/bin/env python3
"""
Google Calendar Registration Script for LEDMatrix Calendar Plugin

Handles OAuth2 authentication for the Google Calendar API.
Supports both headless (web UI) and interactive (terminal) modes.

Web UI mode: outputs JSON for the two-step OAuth flow
Terminal mode: uses run_local_server() for direct browser auth
"""

import json
import os
import pickle
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print(json.dumps({
        "status": "error",
        "message": "Required Google libraries not installed. Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client"
    }))
    sys.exit(1)

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
LOOPBACK_REDIRECT = 'http://127.0.0.1'
PLUGIN_DIR = Path(__file__).parent.resolve()
CREDENTIALS_FILE = PLUGIN_DIR / 'credentials.json'
TOKEN_FILE = PLUGIN_DIR / 'token.pickle'


def _is_headless():
    """Detect if running from web UI (stdin is piped/closed)."""
    try:
        return not os.isatty(sys.stdin.fileno())
    except Exception:
        return True


def _test_credentials(creds):
    """Test credentials by listing calendars. Returns calendar list."""
    service = build('calendar', 'v3', credentials=creds)
    calendar_list = service.calendarList().list().execute()
    return calendar_list.get('items', [])


def main():
    if not CREDENTIALS_FILE.exists():
        msg = (
            "credentials.json not found. To set up:\n"
            "1. Go to https://console.cloud.google.com/\n"
            "2. Create a project and enable Google Calendar API\n"
            "3. Create OAuth 2.0 credentials (Desktop app)\n"
            "4. Download the JSON and upload it above"
        )
        if _is_headless():
            print(json.dumps({"status": "error", "message": msg}))
        else:
            print(f"ERROR: {msg}")
        sys.exit(1)

    # Check for step-2 input (web UI sends the redirect URL via stdin)
    stdin_data = ""
    if _is_headless():
        try:
            stdin_data = sys.stdin.read().strip()
        except (IOError, OSError) as e:
            print(json.dumps({"status": "error", "message": f"Failed to read stdin: {e}"}), file=sys.stderr)
            stdin_data = ""

    # If stdin contains an auth code (step 2), complete the flow
    if stdin_data and ('http' in stdin_data or 'code=' in stdin_data):
        # Try to parse as JSON first (web UI sends JSON params)
        redirect_url = stdin_data
        try:
            params = json.loads(stdin_data)
            redirect_url = params if isinstance(params, str) else params.get('redirect_url', stdin_data)
        except (json.JSONDecodeError, AttributeError):
            pass

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            flow.redirect_uri = LOOPBACK_REDIRECT
            # Extract the authorization code from the redirect URL
            if 'code=' in redirect_url:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(redirect_url)
                code = parse_qs(parsed.query).get('code', [None])[0]
                if not code:
                    code = redirect_url  # Maybe it's just the code
            else:
                code = redirect_url.strip()

            flow.fetch_token(code=code)
            creds = flow.credentials

            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)

            calendars = _test_credentials(creds)
            cal_names = [c.get('summary', c['id']) for c in calendars]

            print(json.dumps({
                "status": "success",
                "message": f"Authentication complete! Found {len(calendars)} calendar(s): {', '.join(cal_names)}"
            }))
            return
        except Exception as e:
            print(json.dumps({"status": "error", "message": f"Failed to complete authentication: {e}"}))
            sys.exit(1)

    # Step 1: Generate auth URL
    if _is_headless():
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            flow.redirect_uri = LOOPBACK_REDIRECT
            auth_url, _ = flow.authorization_url(prompt='consent')

            print(json.dumps({
                "status": "success",
                "requires_step2": True,
                "auth_url": auth_url,
                "message": "Open the link below to authorize Google Calendar access"
            }))
            return
        except Exception as e:
            print(json.dumps({"status": "error", "message": f"Failed to start authentication: {e}"}))
            sys.exit(1)

    # Interactive terminal mode
    print("=" * 60)
    print("Google Calendar Plugin - Registration")
    print("=" * 60)
    print()
    print(f"Found credentials file: {CREDENTIALS_FILE}")

    if TOKEN_FILE.exists():
        response = input("Existing token found. Re-authenticate? (y/N): ").strip().lower()
        if response != 'y':
            print("Keeping existing authentication.")
            return

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0, prompt='consent',
                                       success_message='Authentication successful! You can close this window.')
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

        print("\nSUCCESS! Authentication complete!")
        calendars = _test_credentials(creds)
        print(f"Found {len(calendars)} calendar(s):")
        for cal in calendars:
            name = cal.get('summary', 'Unnamed')
            primary = ' (PRIMARY)' if cal.get('primary') else ''
            print(f"  - {name}{primary}: {cal['id']}")
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
