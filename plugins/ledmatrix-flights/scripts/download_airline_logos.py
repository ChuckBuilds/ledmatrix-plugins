#!/usr/bin/env python3
"""
Download airline logo PNGs for the Flight Tracker plugin.

Sources (tried in order):
  1. Jxck-S/airline-logos (GitHub) — 90x90 ICAO-keyed PNGs
  2. sexym0nk3y/airline-logos (GitHub) — 90x90 ICAO-keyed PNGs
  3. Kiwi.com — 64x64 IATA-keyed PNGs

Output: assets/airline_logos/{ICAO}.png
"""

import os
import time

import requests

LOGO_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "airline_logos")

# Sources in priority order
SOURCES = [
    ("jxck-s", "https://raw.githubusercontent.com/Jxck-S/airline-logos/main/flightaware_logos/{icao}.png"),
    ("sexym0nk3y", "https://raw.githubusercontent.com/sexym0nk3y/airline-logos/master/logos/{icao}.png"),
    ("kiwi", "https://images.kiwi.com/airlines/64/{iata}.png"),
]

# Top airlines to download: (ICAO, IATA, Name)
AIRLINES = [
    # US Majors
    ("AAL", "AA", "American Airlines"),
    ("DAL", "DL", "Delta Air Lines"),
    ("UAL", "UA", "United Airlines"),
    ("SWA", "WN", "Southwest Airlines"),
    ("JBU", "B6", "JetBlue Airways"),
    ("NKS", "NK", "Spirit Airlines"),
    ("FFT", "F9", "Frontier Airlines"),
    ("ASA", "AS", "Alaska Airlines"),
    ("HAL", "HA", "Hawaiian Airlines"),
    ("AAY", "G4", "Allegiant Air"),
    # US Regional / Cargo
    ("SKW", "OO", "SkyWest Airlines"),
    ("ENY", "MQ", "Envoy Air"),
    ("RPA", "YX", "Republic Airways"),
    ("UPS", "5X", "UPS Airlines"),
    ("FDX", "FX", "FedEx Express"),
    ("GTI", "8C", "Atlas Air"),
    # Canada
    ("ACA", "AC", "Air Canada"),
    ("WJA", "WS", "WestJet"),
    # Europe
    ("BAW", "BA", "British Airways"),
    ("DLH", "LH", "Lufthansa"),
    ("AFR", "AF", "Air France"),
    ("KLM", "KL", "KLM"),
    ("EZY", "U2", "easyJet"),
    ("RYR", "FR", "Ryanair"),
    ("SAS", "SK", "SAS"),
    ("IBE", "IB", "Iberia"),
    ("AUA", "OS", "Austrian"),
    ("SWR", "LX", "Swiss"),
    ("TAP", "TP", "TAP Air Portugal"),
    ("VLG", "VY", "Vueling"),
    ("WZZ", "W6", "Wizz Air"),
    ("EIN", "EI", "Aer Lingus"),
    ("THY", "TK", "Turkish Airlines"),
    # Middle East
    ("UAE", "EK", "Emirates"),
    ("QTR", "QR", "Qatar Airways"),
    ("ETD", "EY", "Etihad Airways"),
    ("SVA", "SV", "Saudia"),
    # Asia-Pacific
    ("CPA", "CX", "Cathay Pacific"),
    ("SIA", "SQ", "Singapore Airlines"),
    ("ANA", "NH", "ANA"),
    ("JAL", "JL", "Japan Airlines"),
    ("KAL", "KE", "Korean Air"),
    ("QFA", "QF", "Qantas"),
    ("CSN", "CZ", "China Southern"),
    ("CCA", "CA", "Air China"),
    ("CES", "MU", "China Eastern"),
    # Latin America
    ("AVA", "AV", "Avianca"),
    ("GLO", "G3", "Gol"),
    ("TAM", "JJ", "LATAM Brazil"),
    ("LAN", "LA", "LATAM Chile"),
    # Africa
    ("ETH", "ET", "Ethiopian Airlines"),
    ("SAA", "SA", "South African Airways"),
]


def download_logo(icao: str, iata: str, name: str) -> bool:
    """Try each source to download a logo. Returns True on success."""
    dest = os.path.join(LOGO_DIR, f"{icao}.png")
    if os.path.exists(dest):
        print(f"  {icao} ({name}): already exists, skipping")
        return True

    for source_name, url_template in SOURCES:
        url = url_template.format(icao=icao, iata=iata)
        try:
            resp = requests.get(url, timeout=10, allow_redirects=True)
            if resp.status_code != 200:
                print(f"    {source_name}: HTTP {resp.status_code} for {url}")
            elif len(resp.content) <= 100:
                print(f"    {source_name}: too small ({len(resp.content)} bytes)")
            elif resp.content[:4] != b"\x89PNG":
                print(f"    {source_name}: not a valid PNG ({len(resp.content)} bytes)")
            else:
                try:
                    with open(dest, "wb") as f:
                        f.write(resp.content)
                except OSError as write_err:
                    print(f"    {source_name}: write failed: {write_err}")
                    continue
                size_kb = len(resp.content) / 1024
                print(f"  {icao} ({name}): OK from {source_name} ({size_kb:.1f} KB)")
                return True
        except requests.RequestException as e:
            print(f"    {source_name}: request failed: {e}")
        time.sleep(0.2)  # rate limit

    print(f"  {icao} ({name}): FAILED — no source had a valid logo")
    return False


if __name__ == "__main__":
    os.makedirs(LOGO_DIR, exist_ok=True)
    print(f"Downloading airline logos to {LOGO_DIR}")
    print(f"Airlines to fetch: {len(AIRLINES)}")
    print()

    success = 0
    for icao, iata, name in AIRLINES:
        if download_logo(icao, iata, name):
            success += 1

    print(f"\nDone: {success}/{len(AIRLINES)} logos downloaded")
