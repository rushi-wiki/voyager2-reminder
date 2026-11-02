import requests
from datetime import datetime, timedelta
import re
import xml.etree.ElementTree as ET

SPACECRAFT = {
    "voyager_1": {"name": "Voyager 1", "horizons_id": "-31", "dsn_code": "VGR1"},
    "voyager_2": {"name": "Voyager 2", "horizons_id": "-32", "dsn_code": "VGR2"},
}

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
DSN_URL = "https://eyes.nasa.gov/dsn/data/dsn.xml"
REQUEST_TIMEOUT_S = 30

CENTER_EARTH = "500@399"
CENTER_SUN = "500@10"

def parse_range(text):
    """Pull range (km), range rate (km/s) and X, Y (km) from a Horizons vector table."""
    position = re.search(
        r"X =\s*(-?\d+\.\d+E[+-]?\d+)\s+Y =\s*(-?\d+\.\d+E[+-]?\d+)",
        text
    )
    motion = re.search(
        r"RG=\s*(-?\d+\.\d+E[+-]?\d+)\s+RR=\s*(-?\d+\.\d+E[+-]?\d+)",
        text
    )
    if not position or not motion:
        return None
    return (
        float(motion.group(1)),
        float(motion.group(2)),
        float(position.group(1)),
        float(position.group(2)),
    )

def _fetch_range(horizons_id, center):
    # Format start and stop time for Horizons API
    now = datetime.utcnow()
    now_str = now.strftime("%Y-%b-%d %H:%M").upper()
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%b-%d %H:%M").upper()

    params = {
        "format": "text",
        "COMMAND": f"'{horizons_id}'",
        "OBJ_DATA": "'NO'",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": f"'{center}'",
        "START_TIME": f"'{now_str}'",
        "STOP_TIME": f"'{tomorrow_str}'",
        "STEP_SIZE": "'1 d'",
        "OUT_UNITS": "'KM-S'",
        "REF_PLANE": "ECLIPTIC",
        "VEC_TABLE": "3",
    }

    try:
        response = requests.get(HORIZONS_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"HTTP request failed: {e}")
        return None

    result = parse_range(response.text)
    if result is None:
        print("Range not found in response.")
    return result

def get_position(spacecraft):
    """Current distance and speed relative to Earth and to the Sun, or None."""
    horizons_id = SPACECRAFT[spacecraft]["horizons_id"]
    earth = _fetch_range(horizons_id, CENTER_EARTH)
    sun = _fetch_range(horizons_id, CENTER_SUN)
    if earth is None or sun is None:
        return None
    return {
        "earth_km": earth[0],
        "earth_km_s": earth[1],
        "sun_km": sun[0],
        "sun_km_s": sun[1],
        "sun_x_km": sun[2],
        "sun_y_km": sun[3],
    }

def parse_dsn_contact(xml_text, dsn_code):
    """Find the dish receiving this spacecraft in a DSN Now feed, if any."""
    station = None
    # The feed lists each <station> followed by that station's <dish> elements.
    for element in ET.fromstring(xml_text):
        if element.tag == "station":
            station = element.get("friendlyName")
        elif element.tag == "dish":
            for signal in element.findall("downSignal"):
                if signal.get("spacecraft") == dsn_code and signal.get("active") == "true":
                    return {
                        "station": station,
                        "dish": element.get("name"),
                        "rate_bps": float(signal.get("dataRate") or 0),
                    }
    return None

def get_dsn_contact(spacecraft):
    """Live Deep Space Network contact. Emails go out fine without it."""
    try:
        response = requests.get(DSN_URL, timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        return parse_dsn_contact(response.content, SPACECRAFT[spacecraft]["dsn_code"])
    except (requests.RequestException, ET.ParseError, ValueError) as e:
        print(f"DSN lookup failed: {e}")
        return None

def get_dsn_contacts():
    """Live contact for every spacecraft from one request, or None if the feed fails."""
    try:
        response = requests.get(DSN_URL, timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        return {
            key: parse_dsn_contact(response.content, spacecraft["dsn_code"])
            for key, spacecraft in SPACECRAFT.items()
        }
    except (requests.RequestException, ET.ParseError, ValueError) as e:
        print(f"DSN lookup failed: {e}")
        return None
