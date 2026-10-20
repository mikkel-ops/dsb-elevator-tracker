"""Read-only HTTP API. Runs in Lambda via a Function URL behind CloudFront
(which caches responses for 5 minutes); locally via `make dev`."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone

from boto3.dynamodb.conditions import Attr, Key
from fastapi import FastAPI, HTTPException, Response
from mangum import Mangum

from . import db
from .incidents import load_all, public

CACHE = {"Cache-Control": "public, max-age=300"}

app = FastAPI(title="DSB elevator tracker", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _cached(response: Response, data):
    response.headers.update(CACHE)
    return data


def _stats_item() -> dict:
    item = db.table().get_item(Key={"PK": "STATS", "SK": "LATEST"}).get("Item")
    if not item:
        raise HTTPException(503, "Ingen data endnu")
    return item


@app.get("/api/stats")
def stats(response: Response):
    return _cached(response, json.loads(_stats_item()["stats_json"]))


@app.get("/api/current")
def current(response: Response):
    return _cached(response, json.loads(_stats_item()["current_json"]))


@app.get("/api/stations/{slug}")
def station(slug: str, response: Response):
    items = db.query_all(db.table(), IndexName="GSI1",
                         KeyConditionExpression=Key("GSI1PK").eq(f"STATION#{slug}"))
    if not items:
        raise HTTPException(404, "Ukendt station")
    incidents = sorted((public(i) for i in items), key=lambda i: i["start"], reverse=True)
    return _cached(response, {"station": incidents[0]["station"], "incidents": incidents})


def _evidence(item: dict | None, key_attr: str) -> dict | None:
    if not item or not item.get(key_attr):
        return None
    out = {"at": item["SK"], "url": f"/{item[key_attr]}"}
    if key_attr == "screenshot_key":
        out["sha256"] = item.get("screenshot_sha256")
    return out


def _latest_scrape(at: str, with_screenshot: bool) -> dict | None:
    kwargs = {
        "KeyConditionExpression": Key("PK").eq("SCRAPE") & Key("SK").lte(at),
        "ScanIndexForward": False,
        "Limit": 50,
    }
    if with_screenshot:
        kwargs["FilterExpression"] = Attr("screenshot_key").exists()
    t = db.table()
    while True:
        resp = t.query(**kwargs)
        if resp["Items"]:
            return resp["Items"][0]
        if not with_screenshot or "LastEvaluatedKey" not in resp:
            return None
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


@app.get("/api/evidence")
def evidence(response: Response, at: datetime):
    """DSB's page as it was at `at`: that scrape's raw HTML, and the newest
    screenshot at or before it (screenshots are taken whenever the list
    changes, so it shows the same list)."""
    at_iso = at.astimezone(timezone.utc).isoformat(timespec="seconds")
    return _cached(response, {
        "html": _evidence(_latest_scrape(at_iso, False), "raw_key"),
        "screenshot": _evidence(_latest_scrape(at_iso, True), "screenshot_key"),
    })


@app.get("/api/snapshots")
def snapshots(response: Response, day: date):
    items = db.query_all(db.table(), KeyConditionExpression=Key("PK").eq("SCRAPE")
                         & Key("SK").begins_with(day.isoformat()))
    return _cached(response, [
        {
            "at": i["SK"],
            "rows": int(i.get("rows", 0)),
            "dsb_updated": i.get("dsb_updated"),
            "html": _evidence(i, "raw_key"),
            "screenshot": _evidence(i, "screenshot_key"),
        }
        for i in items
    ])


CSV_FIELDS = [
    "asset_id", "station", "location", "label", "start", "start_is_lower_bound", "end",
    "end_is_precise", "last_seen", "status_kind", "status_text", "first_expected",
    "latest_expected", "expected_changes",
]


@app.get("/api/export.csv")
def export_csv():
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sorted(load_all(db.table()), key=lambda i: i["start"]))
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={
        **CACHE, "Content-Disposition": 'attachment; filename="dsb-elevatorer.csv"',
    })


handler = Mangum(app, lifespan="off")
