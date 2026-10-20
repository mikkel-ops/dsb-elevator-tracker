"""Turn the sequence of hourly snapshots into outage incidents.

Times are only known to scrape resolution, so every incident keeps both ends
of its uncertainty window:
  start window = [prev_scrape_at, first_seen]   (prev None => "at least")
  end window   = [last_seen, ended_at]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Attr, Key

from . import db
from .dsb import Row
from .stations import Asset, normalize

ABSENCES_TO_CLOSE = 2
MERGE_WINDOW = timedelta(hours=24)
# Scraper downtime longer than this makes "two absences in a row" meaningless
# (close on the first) and the times around the gap imprecise.
GAP = timedelta(hours=24)


@dataclass
class Summary:
    opened: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    updated: int = 0


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def reconcile(table, rows: list[Row], now: datetime, raw_key: str | None = None,
              dsb_updated: str | None = None) -> Summary:
    """Apply one successful snapshot. Caller must have checked rows is non-empty."""
    now_iso = _iso(now)
    summary = Summary()
    meta = table.get_item(Key={"PK": "META", "SK": "LAST_SCRAPE"}).get("Item") or {}
    prev_at = meta.get("at")
    after_gap = prev_at is not None and now - _dt(prev_at) > GAP

    current: dict[str, tuple[Row, Asset]] = {}
    for row in rows:  # different raw labels can normalise to the same elevator
        asset = normalize(row.raw_label)
        current.setdefault(asset.asset_id, (row, asset))
    open_ptrs = {i["SK"]: i for i in db.query_all(table, KeyConditionExpression=Key("PK").eq("OPEN"))}

    for asset_id, (row, asset) in current.items():
        if ptr := open_ptrs.get(asset_id):
            _touch(table, asset_id, ptr["incident_sk"], row, now_iso)
            summary.updated += 1
        elif (last := _latest_incident(table, asset_id)) and last.get("ended_at") \
                and now - _dt(last["ended_at"]) <= MERGE_WINDOW:
            _reopen(table, asset_id, last, row, now_iso)
            summary.reopened.append(asset_id)
        else:
            _open(table, asset, row, now_iso, prev_at)
            summary.opened.append(asset_id)

    for asset_id, ptr in open_ptrs.items():
        if asset_id not in current and _mark_absent(
            table, asset_id, ptr["incident_sk"], now_iso, 1 if after_gap else ABSENCES_TO_CLOSE
        ):
            summary.closed.append(asset_id)

    table.update_item(
        Key={"PK": "META", "SK": "LAST_SCRAPE"},
        UpdateExpression="SET #at = :now",
        ExpressionAttributeNames={"#at": "at"},
        ExpressionAttributeValues={":now": now_iso},
    )
    table.put_item(Item={
        "PK": "SCRAPE", "SK": now_iso, "rows": len(rows), "raw_key": raw_key,
        "dsb_updated": dsb_updated,
        "opened": len(summary.opened) + len(summary.reopened), "closed": len(summary.closed),
    })
    return summary


def _latest_incident(table, asset_id: str) -> dict | None:
    items = table.query(
        KeyConditionExpression=Key("PK").eq(f"ASSET#{asset_id}") & Key("SK").begins_with("INCIDENT#"),
        ScanIndexForward=False,
        Limit=1,
    )["Items"]
    return items[0] if items else None


def _expected(row: Row, now_iso: str) -> list[dict]:
    return [{"date": row.expected_date, "first_seen": now_iso}] if row.expected_date else []


def _open(table, asset: Asset, row: Row, now_iso: str, prev_at: str | None):
    sk = f"INCIDENT#{now_iso}"
    table.put_item(Item={
        "PK": f"ASSET#{asset.asset_id}",
        "SK": sk,
        "asset_id": asset.asset_id,
        "station": asset.station,
        "station_slug": asset.station_slug,
        "location": asset.location,
        "labels": [row.raw_label],
        "first_seen": now_iso,
        "prev_scrape_at": prev_at,
        "last_seen": now_iso,
        "missing_count": 0,
        "status_kind": row.status_kind,
        "status_text": row.status_text,
        "expected_dates": _expected(row, now_iso),
        "GSI1PK": f"STATION#{asset.station_slug}",
        "GSI1SK": now_iso,
    })
    table.put_item(Item={"PK": "OPEN", "SK": asset.asset_id, "incident_sk": sk})


def _touch(table, asset_id: str, sk: str, row: Row, now_iso: str):
    key = {"PK": f"ASSET#{asset_id}", "SK": sk}
    inc = table.get_item(Key=key).get("Item")
    if inc is None:
        return
    sets = ["last_seen = :now", "missing_count = :zero", "status_kind = :kind", "status_text = :text"]
    values = {":now": now_iso, ":zero": 0, ":kind": row.status_kind, ":text": row.status_text}
    if row.raw_label not in inc.get("labels", []):
        sets.append("labels = list_append(labels, :label)")
        values[":label"] = [row.raw_label]
    dates = inc.get("expected_dates", [])
    if row.expected_date and (not dates or dates[-1]["date"] != row.expected_date):
        sets.append("expected_dates = list_append(expected_dates, :exp)")
        values[":exp"] = _expected(row, now_iso)
    table.update_item(Key=key, UpdateExpression="SET " + ", ".join(sets) + " REMOVE first_absent_at",
                      ExpressionAttributeValues=values)


def _reopen(table, asset_id: str, inc: dict, row: Row, now_iso: str):
    table.update_item(
        Key={"PK": inc["PK"], "SK": inc["SK"]},
        UpdateExpression="REMOVE ended_at SET merged_gaps = list_append(if_not_exists(merged_gaps, :empty), :gap)",
        ExpressionAttributeValues={":empty": [], ":gap": [{"from": inc["ended_at"], "to": now_iso}]},
    )
    table.put_item(Item={"PK": "OPEN", "SK": asset_id, "incident_sk": inc["SK"]})
    _touch(table, asset_id, inc["SK"], row, now_iso)


def _mark_absent(table, asset_id: str, sk: str, now_iso: str, needed: int) -> bool:
    """Count one absence; close the incident on the `needed`th. Returns True if closed."""
    key = {"PK": f"ASSET#{asset_id}", "SK": sk}
    inc = table.update_item(
        Key=key,
        UpdateExpression="SET missing_count = missing_count + :one, first_absent_at = if_not_exists(first_absent_at, :now)",
        ExpressionAttributeValues={":one": 1, ":now": now_iso},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    if inc["missing_count"] < needed:
        return False
    table.update_item(Key=key, UpdateExpression="SET ended_at = first_absent_at")
    table.delete_item(Key={"PK": "OPEN", "SK": asset_id})
    return True


def public(item: dict) -> dict:
    """The shape the API and CSV export use (no storage keys, no Decimals)."""
    first_seen, prev = _dt(item["first_seen"]), _dt(item.get("prev_scrape_at"))
    ended, last_seen = _dt(item.get("ended_at")), _dt(item["last_seen"])
    expected = [e["date"] for e in item.get("expected_dates", [])]
    return {
        "asset_id": item["asset_id"],
        "station": item["station"],
        "station_slug": item["station_slug"],
        "location": item.get("location", ""),
        "label": item["labels"][-1],
        "status_kind": item["status_kind"],
        "status_text": item["status_text"],
        "start": item["first_seen"],
        # Open at our first scrape, or first seen after scraper downtime:
        # the real start is earlier, so the duration is a lower bound.
        "start_is_lower_bound": prev is None or first_seen - prev > GAP,
        "end": item.get("ended_at"),
        # Closed after scraper downtime: end only known within a wide window.
        "end_is_precise": ended is None or ended - last_seen <= GAP,
        "last_seen": item["last_seen"],
        "first_expected": expected[0] if expected else None,
        "latest_expected": expected[-1] if expected else None,
        "expected_changes": max(len(expected) - 1, 0),
        "expected_history": expected,
    }


def load_all(table) -> list[dict]:
    return [public(i) for i in db.scan_all(table, FilterExpression=Attr("SK").begins_with("INCIDENT#"))]
