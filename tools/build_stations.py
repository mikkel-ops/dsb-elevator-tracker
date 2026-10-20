"""Build src/elevator_tracker/stations.json (station slug -> name + coordinates) from
Rejseplanen's GTFS feed. Rail stations are the stops whose id is a Danish
UIC code (0000086xxxxx). Re-run when stations change:

    uv run python -m tools.build_stations [path/to/GTFS.zip]
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from elevator_tracker.stations import STATIONS_PATH, slugify

GTFS_URL = "https://www.rejseplanen.info/labs/GTFS.zip"


def main(zip_path: str | None = None) -> None:
    data = Path(zip_path).read_bytes() if zip_path else urllib.request.urlopen(GTFS_URL).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        rows = csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), encoding="utf-8-sig"))
        stations = {}
        for r in rows:
            if not r["stop_id"].startswith("0000086"):
                continue
            name = re.sub(r"\s+St\.?$", "", r["stop_name"]).strip()
            stations.setdefault(slugify(name), {
                "name": name,
                "lat": round(float(r["stop_lat"]), 5),
                "lon": round(float(r["stop_lon"]), 5),
            })
    STATIONS_PATH.write_text(json.dumps(dict(sorted(stations.items())), ensure_ascii=False, separators=(",", ":")))
    print(f"{len(stations)} stations -> {STATIONS_PATH}")


if __name__ == "__main__":
    main(*sys.argv[1:])
