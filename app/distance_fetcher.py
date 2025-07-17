import requests
from datetime import datetime, timedelta
import re
import math

def get_voyager2_distance_from_earth():
    # Format start and stop time for Horizons API
    now = datetime.utcnow()
    now_str = now.strftime("%Y-%b-%d %H:%M").upper()
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%b-%d %H:%M").upper()

    url = "https://ssd.jpl.nasa.gov/api/horizons.api"
    params = {
        "format": "text",
        "COMMAND": "'-32'",  # Voyager 2
        "EPHEM_TYPE": "VECTORS",
        "CENTER": "'399'",  # Earth
        "START_TIME": f"'{now_str}'",
        "STOP_TIME": f"'{tomorrow_str}'",
        "STEP_SIZE": "'1 d'",
        "OUT_UNITS": "KM",
        "REF_PLANE": "ECLIPTIC",
        "VEC_TABLE": "3",
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"HTTP request failed: {e}")
        return None

    # Extract X, Y, Z coordinates using regex
    match = re.search(
        r"X =\s*(-?\d+\.\d+E[+-]?\d+)\s+Y =\s*(-?\d+\.\d+E[+-]?\d+)\s+Z =\s*(-?\d+\.\d+E[+-]?\d+)",
        response.text
    )

    if match:
        x, y, z = map(float, match.groups())
        distance_km = math.sqrt(x**2 + y**2 + z**2)
        return distance_km
    else:
        print("Coordinates not found in response.")
        return None