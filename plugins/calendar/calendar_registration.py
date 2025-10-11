#!/usr/bin/env python3
"""
Google Calendar Registration Script for LEDMatrix Calendar Plugin

This script helps you set up OAuth2 authentication for the Google Calendar API.
It will open a browser window for you to authorize access to your calendar.

Usage:
    python calendar_registration.py

Requirements:
    - Google Cloud Project with Calendar API enabled
    - OAuth 2.0 credentials (download as credentials.json)
    - Place credentials.json in this plugin directory
"""

import os
import sys
import pickle
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("ERROR: Required Google libraries not installed!")
    print("Install them with:")
    print("  pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

# Scopes for Calendar API (read-only)
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Get plugin directory
PLUGIN_DIR = Path(__file__).parent
CREDENTIALS_FILE = PLUGIN_DIR / 'credentials.json'
TOKEN_FILE = PLUGIN_DIR / 'token.pickle'


def main():
    """Run the OAuth2 flow to authenticate with Google Calendar."""
    print("=" * 60)
    print("Google Calendar Plugin - Registration")
    print("=" * 60)
    print()
    
    # Check for credentials file
    if not CREDENTIALS_FILE.exists():
        print("ERROR: credentials.json not found!")
        print()
        print("To get credentials.json:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project (or select existing)")
        print("3. Enable the Google Calendar API")
        print("4. Create OAuth 2.0 credentials (Desktop app)")
        print("5. Download the JSON file")
        print(f"6. Save it as: {CREDENTIALS_FILE}")
        print()
        sys.exit(1)
    
    print(f"Found credentials file: {CREDENTIALS_FILE}")
    print()
    
    # Check if already authenticated
    if TOKEN_FILE.exists():
        print(f"Existing token found: {TOKEN_FILE}")
        response = input("Do you want to re-authenticate? (y/N): ").strip().lower()
        if response != 'y':
            print("Keeping existing authentication.")
            return
        print("Re-authenticating...")
        print()
    
    # Start OAuth flow
    print("Starting OAuth2 flow...")
    print("A browser window will open for authentication.")
    print()
    
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), 
            SCOPES
        )
        
        # Run local server for OAuth callback
        creds = flow.run_local_server(
            port=0,
            prompt='consent',
            success_message='Authentication successful! You can close this window.'
        )
        
        # Save the credentials
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
        
        print()
        print("=" * 60)
        print("SUCCESS! Authentication complete!")
        print("=" * 60)
        print()
        print(f"Token saved to: {TOKEN_FILE}")
        print()
        
        # Test the credentials
        print("Testing calendar access...")
        service = build('calendar', 'v3', credentials=creds)
        
        # Get calendar list
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        print(f"Found {len(calendars)} calendar(s):")
        for cal in calendars:
            cal_id = cal['id']
            cal_name = cal.get('summary', 'Unnamed Calendar')
            is_primary = ' (PRIMARY)' if cal.get('primary', False) else ''
            print(f"  - {cal_name}{is_primary}")
            print(f"    ID: {cal_id}")
        
        print()
        print("Setup complete! You can now use the calendar plugin.")
        print()
        
    except Exception as e:
        print()
        print(f"ERROR during authentication: {e}")
        print()
        sys.exit(1)


if __name__ == '__main__':
    main()

