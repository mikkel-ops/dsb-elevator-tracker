"""Local development without AWS or Docker: an in-process moto DynamoDB,
seeded with simulated history, the API and the static site on one port
(same-origin, like CloudFront in production).

    make dev   ->  http://localhost:8000
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for k, v in {"AWS_DEFAULT_REGION": "eu-north-1", "AWS_ACCESS_KEY_ID": "dev",
             "AWS_SECRET_ACCESS_KEY": "dev", "TABLE_NAME": "dev"}.items():
    os.environ[k] = v

import uvicorn  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from moto import mock_aws  # noqa: E402

from elevator_tracker import db, dsb, stations  # noqa: E402
from elevator_tracker.api import app  # noqa: E402
from elevator_tracker.incidents import reconcile  # noqa: E402
from elevator_tracker.stats import publish  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "2026-10-20.html"


def seed(table, days: int = 45) -> None:
    """Replay the fixture's elevators every 6 hours for `days`, randomly
    breaking and fixing some, so every chart has something to show."""
    rng = random.Random(42)
    base = dsb.parse(FIXTURE.read_text(encoding="utf-8")).rows
    extra = [dsb.Row(n, "Forventes i drift den 01.12.26", "expected", "2026-12-01")
             for n in ["Valby spor 1", "Nørreport spor 3", "Hellerup spor 2", "Ballerup spor 3", "Lyngby spor 1"]]
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    t = now - timedelta(days=days)
    down = set(rng.sample(range(len(base)), 8))
    while t <= now:
        if rng.random() < 0.15:
            down ^= {rng.randrange(len(base))}
        rows = [r for i, r in enumerate(base) if i in down]
        rows += [r for j, r in enumerate(extra) if (t.toordinal() + j * 7) % 19 < 6]
        if rows:
            reconcile(table, rows, t)
        t += timedelta(hours=6)
    publish(table, now)


@app.get("/data/stations.json", include_in_schema=False)
def stations_json():
    return FileResponse(stations.STATIONS_PATH)


app.mount("/", StaticFiles(directory=ROOT / "site", html=True), name="site")

if __name__ == "__main__":
    with mock_aws():
        seed(db.create_table("dev"))
        uvicorn.run(app, port=int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
