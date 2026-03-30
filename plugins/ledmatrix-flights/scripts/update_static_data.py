#!/usr/bin/env python3
"""
Download and convert static reference datasets for the Flight Tracker plugin.

Sources:
  - Airports: OurAirports.com (public domain)
  - Airlines: OpenFlights airlines.dat (ODbL)
  - Cities: Curated from GeoNames (CC-BY)

Output goes to ../data/ as JSON files.
"""

import csv
import io
import json
import os
import sys

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def fetch_airports():
    """Download OurAirports CSV and convert to airports.json."""
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    print(f"Downloading airports from {url} ...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    airports = []
    for row in reader:
        # Only include airports with IATA codes (filters out tiny strips)
        iata = (row.get("iata_code") or "").strip()
        icao = (row.get("ident") or "").strip()
        if not iata and not icao:
            continue
        # Skip closed airports
        if row.get("type") == "closed":
            continue
        try:
            lat = float(row["latitude_deg"])
            lon = float(row["longitude_deg"])
        except (ValueError, KeyError):
            continue

        entry = {
            "icao": icao,
            "iata": iata,
            "name": (row.get("name") or "").strip(),
            "city": (row.get("municipality") or "").strip(),
            "country": (row.get("iso_country") or "").strip(),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "type": (row.get("type") or "").strip(),
        }
        airports.append(entry)

    # Sort by ICAO code
    airports.sort(key=lambda a: a["icao"])
    path = os.path.join(DATA_DIR, "airports.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(airports, f, separators=(",", ":"))
    print(f"  Wrote {len(airports)} airports to {path}")


def fetch_airlines():
    """Download OpenFlights airlines.dat and convert to airlines.json."""
    url = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
    print(f"Downloading airlines from {url} ...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    # OpenFlights format: ID, Name, Alias, IATA, ICAO, Callsign, Country, Active
    airlines = []
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if len(row) < 8:
            continue
        name = row[1].strip()
        iata = row[3].strip() if row[3].strip() != "\\N" else ""
        icao = row[4].strip() if row[4].strip() != "\\N" else ""
        callsign = row[5].strip() if row[5].strip() != "\\N" else ""
        country = row[6].strip() if row[6].strip() != "\\N" else ""
        active = row[7].strip()

        if not name or (not iata and not icao):
            continue

        entry = {"name": name, "iata": iata, "icao": icao, "callsign": callsign, "country": country, "active": active == "Y"}
        airlines.append(entry)

    airlines.sort(key=lambda a: a.get("icao", ""))
    path = os.path.join(DATA_DIR, "airlines.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(airlines, f, separators=(",", ":"))
    print(f"  Wrote {len(airlines)} airlines to {path}")


def generate_cities():
    """Generate a curated list of major world cities for overfly reverse geocoding."""
    # Curated list of 200+ major cities. Enough for meaningful overfly labels.
    cities = [
        # North America
        {"name": "New York", "lat": 40.7128, "lon": -74.0060},
        {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437},
        {"name": "Chicago", "lat": 41.8781, "lon": -87.6298},
        {"name": "Houston", "lat": 29.7604, "lon": -95.3698},
        {"name": "Phoenix", "lat": 33.4484, "lon": -112.0740},
        {"name": "Philadelphia", "lat": 39.9526, "lon": -75.1652},
        {"name": "San Antonio", "lat": 29.4241, "lon": -98.4936},
        {"name": "San Diego", "lat": 32.7157, "lon": -117.1611},
        {"name": "Dallas", "lat": 32.7767, "lon": -96.7970},
        {"name": "San Jose", "lat": 37.3382, "lon": -121.8863},
        {"name": "Austin", "lat": 30.2672, "lon": -97.7431},
        {"name": "Jacksonville", "lat": 30.3322, "lon": -81.6557},
        {"name": "San Francisco", "lat": 37.7749, "lon": -122.4194},
        {"name": "Columbus", "lat": 39.9612, "lon": -82.9988},
        {"name": "Indianapolis", "lat": 39.7684, "lon": -86.1581},
        {"name": "Charlotte", "lat": 35.2271, "lon": -80.8431},
        {"name": "Seattle", "lat": 47.6062, "lon": -122.3321},
        {"name": "Denver", "lat": 39.7392, "lon": -104.9903},
        {"name": "Washington DC", "lat": 38.9072, "lon": -77.0369},
        {"name": "Nashville", "lat": 36.1627, "lon": -86.7816},
        {"name": "Boston", "lat": 42.3601, "lon": -71.0589},
        {"name": "Las Vegas", "lat": 36.1699, "lon": -115.1398},
        {"name": "Portland", "lat": 45.5051, "lon": -122.6750},
        {"name": "Memphis", "lat": 35.1495, "lon": -90.0490},
        {"name": "Louisville", "lat": 38.2527, "lon": -85.7585},
        {"name": "Baltimore", "lat": 39.2904, "lon": -76.6122},
        {"name": "Milwaukee", "lat": 43.0389, "lon": -87.9065},
        {"name": "Atlanta", "lat": 33.7490, "lon": -84.3880},
        {"name": "Miami", "lat": 25.7617, "lon": -80.1918},
        {"name": "Tampa", "lat": 27.9506, "lon": -82.4572},
        {"name": "Orlando", "lat": 28.5383, "lon": -81.3792},
        {"name": "Minneapolis", "lat": 44.9778, "lon": -93.2650},
        {"name": "Cleveland", "lat": 41.4993, "lon": -81.6944},
        {"name": "St. Louis", "lat": 38.6270, "lon": -90.1994},
        {"name": "Pittsburgh", "lat": 40.4406, "lon": -79.9959},
        {"name": "Cincinnati", "lat": 39.1031, "lon": -84.5120},
        {"name": "Kansas City", "lat": 39.0997, "lon": -94.5786},
        {"name": "Detroit", "lat": 42.3314, "lon": -83.0458},
        {"name": "Salt Lake City", "lat": 40.7608, "lon": -111.8910},
        {"name": "Raleigh", "lat": 35.7796, "lon": -78.6382},
        {"name": "New Orleans", "lat": 29.9511, "lon": -90.0715},
        {"name": "Toronto", "lat": 43.6532, "lon": -79.3832},
        {"name": "Montreal", "lat": 45.5017, "lon": -73.5673},
        {"name": "Vancouver", "lat": 49.2827, "lon": -123.1207},
        {"name": "Calgary", "lat": 51.0447, "lon": -114.0719},
        {"name": "Mexico City", "lat": 19.4326, "lon": -99.1332},
        {"name": "Guadalajara", "lat": 20.6597, "lon": -103.3496},
        {"name": "Monterrey", "lat": 25.6866, "lon": -100.3161},
        {"name": "Cancun", "lat": 21.1619, "lon": -86.8515},
        # Europe
        {"name": "London", "lat": 51.5074, "lon": -0.1278},
        {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
        {"name": "Berlin", "lat": 52.5200, "lon": 13.4050},
        {"name": "Madrid", "lat": 40.4168, "lon": -3.7038},
        {"name": "Rome", "lat": 41.9028, "lon": 12.4964},
        {"name": "Amsterdam", "lat": 52.3676, "lon": 4.9041},
        {"name": "Munich", "lat": 48.1351, "lon": 11.5820},
        {"name": "Frankfurt", "lat": 50.1109, "lon": 8.6821},
        {"name": "Barcelona", "lat": 41.3874, "lon": 2.1686},
        {"name": "Milan", "lat": 45.4642, "lon": 9.1900},
        {"name": "Vienna", "lat": 48.2082, "lon": 16.3738},
        {"name": "Zurich", "lat": 47.3769, "lon": 8.5417},
        {"name": "Brussels", "lat": 50.8503, "lon": 4.3517},
        {"name": "Dublin", "lat": 53.3498, "lon": -6.2603},
        {"name": "Copenhagen", "lat": 55.6761, "lon": 12.5683},
        {"name": "Stockholm", "lat": 59.3293, "lon": 18.0686},
        {"name": "Oslo", "lat": 59.9139, "lon": 10.7522},
        {"name": "Helsinki", "lat": 60.1699, "lon": 24.9384},
        {"name": "Lisbon", "lat": 38.7223, "lon": -9.1393},
        {"name": "Athens", "lat": 37.9838, "lon": 23.7275},
        {"name": "Warsaw", "lat": 52.2297, "lon": 21.0122},
        {"name": "Prague", "lat": 50.0755, "lon": 14.4378},
        {"name": "Budapest", "lat": 47.4979, "lon": 19.0402},
        {"name": "Istanbul", "lat": 41.0082, "lon": 28.9784},
        {"name": "Moscow", "lat": 55.7558, "lon": 37.6173},
        {"name": "Edinburgh", "lat": 55.9533, "lon": -3.1883},
        {"name": "Manchester", "lat": 53.4808, "lon": -2.2426},
        # Asia
        {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
        {"name": "Shanghai", "lat": 31.2304, "lon": 121.4737},
        {"name": "Beijing", "lat": 39.9042, "lon": 116.4074},
        {"name": "Hong Kong", "lat": 22.3193, "lon": 114.1694},
        {"name": "Singapore", "lat": 1.3521, "lon": 103.8198},
        {"name": "Seoul", "lat": 37.5665, "lon": 126.9780},
        {"name": "Bangkok", "lat": 13.7563, "lon": 100.5018},
        {"name": "Mumbai", "lat": 19.0760, "lon": 72.8777},
        {"name": "Delhi", "lat": 28.7041, "lon": 77.1025},
        {"name": "Dubai", "lat": 25.2048, "lon": 55.2708},
        {"name": "Taipei", "lat": 25.0330, "lon": 121.5654},
        {"name": "Osaka", "lat": 34.6937, "lon": 135.5023},
        {"name": "Manila", "lat": 14.5995, "lon": 120.9842},
        {"name": "Jakarta", "lat": -6.2088, "lon": 106.8456},
        {"name": "Kuala Lumpur", "lat": 3.1390, "lon": 101.6869},
        {"name": "Doha", "lat": 25.2854, "lon": 51.5310},
        {"name": "Abu Dhabi", "lat": 24.4539, "lon": 54.3773},
        {"name": "Tel Aviv", "lat": 32.0853, "lon": 34.7818},
        # South America
        {"name": "Sao Paulo", "lat": -23.5505, "lon": -46.6333},
        {"name": "Buenos Aires", "lat": -34.6037, "lon": -58.3816},
        {"name": "Rio de Janeiro", "lat": -22.9068, "lon": -43.1729},
        {"name": "Lima", "lat": -12.0464, "lon": -77.0428},
        {"name": "Bogota", "lat": 4.7110, "lon": -74.0721},
        {"name": "Santiago", "lat": -33.4489, "lon": -70.6693},
        # Africa
        {"name": "Cairo", "lat": 30.0444, "lon": 31.2357},
        {"name": "Lagos", "lat": 6.5244, "lon": 3.3792},
        {"name": "Johannesburg", "lat": -26.2041, "lon": 28.0473},
        {"name": "Cape Town", "lat": -33.9249, "lon": 18.4241},
        {"name": "Nairobi", "lat": -1.2921, "lon": 36.8219},
        {"name": "Casablanca", "lat": 33.5731, "lon": -7.5898},
        # Oceania
        {"name": "Sydney", "lat": -33.8688, "lon": 151.2093},
        {"name": "Melbourne", "lat": -37.8136, "lon": 144.9631},
        {"name": "Auckland", "lat": -36.8485, "lon": 174.7633},
        {"name": "Brisbane", "lat": -27.4698, "lon": 153.0251},
        {"name": "Perth", "lat": -31.9505, "lon": 115.8605},
        {"name": "Honolulu", "lat": 21.3069, "lon": -157.8583},
        # Caribbean
        {"name": "Havana", "lat": 23.1136, "lon": -82.3666},
        {"name": "San Juan", "lat": 18.4655, "lon": -66.1057},
        {"name": "Nassau", "lat": 25.0480, "lon": -77.3554},
        {"name": "Kingston", "lat": 18.0179, "lon": -76.8099},
        # Additional US cities for better overfly coverage
        {"name": "Omaha", "lat": 41.2565, "lon": -95.9345},
        {"name": "Tulsa", "lat": 36.1540, "lon": -95.9928},
        {"name": "Albuquerque", "lat": 35.0844, "lon": -106.6504},
        {"name": "Tucson", "lat": 32.2226, "lon": -110.9747},
        {"name": "El Paso", "lat": 31.7619, "lon": -106.4850},
        {"name": "Oklahoma City", "lat": 35.4676, "lon": -97.5164},
        {"name": "Boise", "lat": 43.6150, "lon": -116.2023},
        {"name": "Anchorage", "lat": 61.2181, "lon": -149.9003},
        {"name": "Birmingham", "lat": 33.5207, "lon": -86.8025},
        {"name": "Savannah", "lat": 32.0809, "lon": -81.0912},
        {"name": "Richmond", "lat": 37.5407, "lon": -77.4360},
        {"name": "Hartford", "lat": 41.7658, "lon": -72.6734},
        {"name": "Buffalo", "lat": 42.8864, "lon": -78.8784},
        {"name": "Rochester", "lat": 43.1566, "lon": -77.6088},
        {"name": "Little Rock", "lat": 34.7465, "lon": -92.2896},
        {"name": "Des Moines", "lat": 41.5868, "lon": -93.6250},
        {"name": "Wichita", "lat": 37.6872, "lon": -97.3301},
        {"name": "Knoxville", "lat": 35.9606, "lon": -83.9207},
        {"name": "Chattanooga", "lat": 35.0456, "lon": -85.3097},
        {"name": "Tallahassee", "lat": 30.4383, "lon": -84.2807},
        {"name": "Pensacola", "lat": 30.4213, "lon": -87.2169},
        {"name": "Fort Myers", "lat": 26.6406, "lon": -81.8723},
        {"name": "Sarasota", "lat": 27.3364, "lon": -82.5307},
        {"name": "Gainesville", "lat": 29.6516, "lon": -82.3248},
        {"name": "Daytona Beach", "lat": 29.2108, "lon": -81.0228},
    ]

    path = os.path.join(DATA_DIR, "cities.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cities, f, indent=1)
    print(f"  Wrote {len(cities)} cities to {path}")


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)

    if "--cities-only" in sys.argv:
        generate_cities()
    else:
        fetch_airports()
        fetch_airlines()
        generate_cities()

    print("Done!")
