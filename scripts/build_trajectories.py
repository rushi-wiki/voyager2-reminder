"""Download real paths from JPL Horizons for the page's journey animation.

Run this by hand, from the project root, and commit the result:
    python scripts/build_trajectories.py

The data runs to 2040, including JPL's predictions, so it needs no regular update.
"""
import json
import math
import re
from datetime import datetime
from pathlib import Path

import requests

OUTPUT = Path(__file__).parent.parent / "app" / "trajectories.json"
HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
KM_PER_AU = 149597870.7
STOP = "2040-01-01"
# Fine steps for the planet flybys, then coarser once the path runs straight
FLYBYS_END = "1990-03-01"

# name: (Horizons ID, start, [(end, step), ...])
BODIES = {
    "voyager_1": ("-31", "1977-09-06", [(FLYBYS_END, "5 d"), (STOP, "30 d")]),
    "voyager_2": ("-32", "1977-08-21", [(FLYBYS_END, "5 d"), (STOP, "30 d")]),
    "Earth": ("399", "1977-08-20", [(STOP, "15 d")]),
    "Jupiter": ("599", "1977-08-20", [(STOP, "30 d")]),
    "Saturn": ("699", "1977-08-20", [(STOP, "30 d")]),
    "Uranus": ("799", "1977-08-20", [(STOP, "60 d")]),
    "Neptune": ("899", "1977-08-20", [(STOP, "60 d")]),
}

ROW = re.compile(r"^\s*(\d+\.\d+),\s*A\.D\.[^,]*,\s*(-?[\d.E+-]+),\s*(-?[\d.E+-]+),\s*(-?[\d.E+-]+),", re.M)

def fetch(horizons_id, start, stop, step):
    response = requests.get(
        HORIZONS_URL,
        params={
            "format": "text",
            "COMMAND": f"'{horizons_id}'",
            "OBJ_DATA": "'NO'",
            "EPHEM_TYPE": "VECTORS",
            "CENTER": "'500@10'",
            "START_TIME": f"'{start}'",
            "STOP_TIME": f"'{stop}'",
            "STEP_SIZE": f"'{step}'",
            "OUT_UNITS": "'KM-S'",
            "REF_PLANE": "ECLIPTIC",
            "VEC_TABLE": "1",
            "CSV_FORMAT": "'YES'",
        },
        timeout=120,
    )
    response.raise_for_status()
    rows = ROW.findall(response.text.split("$$SOE")[1].split("$$EOE")[0])
    if not rows:
        raise RuntimeError(f"No rows for {horizons_id}: {response.text[:400]}")
    points = []
    for jd, x, y, z in rows:
        x, y, z = float(x), float(y), float(z)
        # Both Voyagers climb out of the planets' plane. Flatten them onto it while
        # keeping their true distance, so the path ends where the page's map shows.
        scale = math.sqrt(x * x + y * y + z * z) / math.hypot(x, y) / KM_PER_AU
        points.append((float(jd), x * scale, y * scale))
    return points

def build():
    epoch = 2443375.5  # 1977-08-20, the day of the first launch
    bodies = {}
    for name, (horizons_id, start, segments) in BODIES.items():
        rows = []
        segment_start = start
        for stop, step in segments:
            for row in fetch(horizons_id, segment_start, stop, step):
                if not rows or row[0] > rows[-1][0]:
                    rows.append(row)
            segment_start = stop
        bodies[name] = {
            "t": [round(jd - epoch, 1) for jd, _, _ in rows],
            "x": [round(x, 3) for _, x, _ in rows],
            "y": [round(y, 3) for _, _, y in rows],
        }
        print(name, len(rows), "points, last", bodies[name]["t"][-1])
    data = {
        "epoch": "1977-08-20",
        "source": "NASA JPL Horizons, positions relative to the Sun in AU",
        "built": datetime.utcnow().strftime("%Y-%m-%d"),
        "bodies": bodies,
    }
    OUTPUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUTPUT, OUTPUT.stat().st_size // 1024, "KB")

if __name__ == "__main__":
    build()
