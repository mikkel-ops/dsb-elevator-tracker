"""Read-only HTTP API in front of DynamoDB. Runs in Lambda via a Function URL
behind CloudFront; locally with `uvicorn api.app:app --reload`."""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from scraper.stats import load_incidents, public_incident

CACHE = "public, max-age=300"

app = FastAPI(title="DSB elevator tracker", docs_url="/api/docs", openapi_url="/api/openapi.json")
if os.environ.get("LOCAL_CORS"):
    # Only for local development (site served from another port).
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])


def _table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _json(data, response: Response):
    response.headers["Cache-Control"] = CACHE
    return data


def _stats_item() -> dict:
    item = _table().get_item(Key={"PK": "STATS", "SK": "LATEST"}).get("Item")
    if not item:
        raise HTTPException(503, "Ingen data endnu")
    return item


def _query(index: str, pk_attr: str, pk: str) -> list[dict]:
    table, items = _table(), []
    kwargs = {"IndexName": index, "KeyConditionExpression": Key(pk_attr).eq(pk)}
    while True:
        resp = table.query(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


@app.get("/api/stats")
def stats(response: Response):
    return _json(json.loads(_stats_item()["stats_json"]), response)


@app.get("/api/current")
def current(response: Response):
    return _json(json.loads(_stats_item()["current_json"]), response)


@app.get("/api/stations/{slug}")
def station(slug: str, response: Response):
    items = [public_incident(i) for i in _query("GSI1", "GSI1PK", f"STATION#{slug}")]
    if not items:
        raise HTTPException(404, "Ukendt station")
    items.sort(key=lambda i: i["start"], reverse=True)
    return _json({"station": items[0]["station"], "incidents": items}, response)


@app.get("/api/incidents")
def incidents(
    response: Response,
    year: int = Query(default_factory=lambda: datetime.now(timezone.utc).year),
    type: str | None = Query(default=None, pattern="^(elevator|escalator)$"),
):
    items = [public_incident(i) for i in _query("GSI2", "GSI2PK", f"YEAR#{year}")]
    if type:
        items = [i for i in items if i["asset_type"] == type]
    items.sort(key=lambda i: i["start"], reverse=True)
    return _json(items, response)


def _evidence(item: dict | None, kind: str) -> dict | None:
    if not item:
        return None
    key = item.get("screenshot_key") if kind == "screenshot" else item.get("raw_key")
    if not key:
        return None
    out = {"at": item["SK"], "url": f"/{key}"}
    if kind == "screenshot":
        out["sha256"] = item.get("screenshot_sha256")
    return out


def _latest_scrape_before(at: str, with_screenshot: bool) -> dict | None:
    kwargs = {
        "KeyConditionExpression": Key("PK").eq("SCRAPE") & Key("SK").lte(at),
        "ScanIndexForward": False,
        "Limit": 50,
    }
    if with_screenshot:
        kwargs["FilterExpression"] = Attr("screenshot_key").exists()
    table = _table()
    while True:
        resp = table.query(**kwargs)
        if resp["Items"]:
            return resp["Items"][0]
        if "LastEvaluatedKey" not in resp or not with_screenshot:
            return None
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


@app.get("/api/evidence")
def evidence(response: Response, at: datetime):
    """What DSB's page looked like at `at`: the scrape's raw HTML and the newest
    screenshot taken at or before it (screenshots are taken whenever the list
    changes, so it shows the same list)."""
    at_iso = at.astimezone(timezone.utc).isoformat(timespec="seconds")
    return _json(
        {
            "html": _evidence(_latest_scrape_before(at_iso, False), "html"),
            "screenshot": _evidence(_latest_scrape_before(at_iso, True), "screenshot"),
        },
        response,
    )


@app.get("/api/snapshots")
def snapshots(response: Response, day: date):
    items = _table().query(
        KeyConditionExpression=Key("PK").eq("SCRAPE") & Key("SK").begins_with(day.isoformat())
    )["Items"]
    return _json(
        [
            {
                "at": i["SK"],
                "rows": int(i.get("rows", 0)),
                "dsb_updated": i.get("dsb_updated"),
                "html": _evidence(i, "html"),
                "screenshot": _evidence(i, "screenshot"),
            }
            for i in items
        ],
        response,
    )


CSV_FIELDS = [
    "asset_id", "asset_type", "station", "location", "label", "start", "start_is_lower_bound",
    "end", "last_seen", "status_kind", "status_text", "first_expected", "latest_expected",
    "expected_changes", "estimated", "source",
]


@app.get("/api/export.csv")
def export_csv():
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for inc in sorted(load_incidents(_table()), key=lambda i: i["start"]):
        writer.writerow(inc)
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": CACHE,
            "Content-Disposition": 'attachment; filename="dsb-elevatorer.csv"',
        },
    )


handler = Mangum(app, lifespan="off")
