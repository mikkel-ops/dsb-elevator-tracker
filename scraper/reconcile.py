"""Turn a sequence of page snapshots into outage incidents in DynamoDB.

Table layout (single table, PK/SK strings):
  ASSET#<asset_id> / INCIDENT#<start_iso>  one outage of one elevator/escalator
  OPEN             / <asset_id>            pointer to the open incident
  SCRAPE           / <iso>                 log of each successful scrape
  META             / LAST_SCRAPE           time of the latest successful scrape

Timing is only known to scrape resolution, so every incident keeps both ends
of its uncertainty window:
  start window = [prev_scrape_at, first_seen]   (prev None => "at least")
  end window   = [last_seen, ended_at]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key

from .normalize import normalize
from .parse import ELEVATOR, ESCALATOR, Row

ABSENCES_TO_CLOSE = 2
MERGE_WINDOW = timedelta(hours=24)


@dataclass
class Summary:
    opened: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    updated: int = 0


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def incident_sk(start: str) -> str:
    return f"INCIDENT#{start}"


def reconcile(
    table,
    rows: list[Row],
    sections_found: set[str],
    now: datetime,
    source: str = "live",
    raw_key: str | None = None,
    dsb_updated: str | None = None,
) -> Summary:
    """Apply one successful snapshot. Caller must have checked rows is non-empty."""
    now_iso = _iso(now)
    summary = Summary()
    prev_scrape = _get(table, "META", "LAST_SCRAPE")
    prev_scrape_at = prev_scrape["at"] if prev_scrape else None

    # Collapse to one row per asset (different raw labels can normalise equally).
    current: dict[str, tuple[Row, object]] = {}
    for row in rows:
        asset = normalize(row.asset_type, row.raw_label)
        current.setdefault(asset.asset_id, (row, asset))

    open_ptrs = {
        item["SK"]: item
        for item in _query_all(table, Key("PK").eq("OPEN"))
    }

    for asset_id, (row, asset) in current.items():
        ptr = open_ptrs.get(asset_id)
        if ptr:
            _touch(table, asset_id, ptr["incident_sk"], row, now_iso)
            summary.updated += 1
            continue
        last = _latest_incident(table, asset_id)
        if (
            last
            and last.get("ended_at")
            and now - datetime.fromisoformat(last["ended_at"]) <= MERGE_WINDOW
        ):
            _reopen(table, asset_id, last, row, now_iso)
            summary.reopened.append(asset_id)
        else:
            _open(table, asset, row, now_iso, prev_scrape_at, source)
            summary.opened.append(asset_id)

    for asset_id, ptr in open_ptrs.items():
        if asset_id in current:
            continue
        asset_type = asset_id.split(":", 1)[0]
        if asset_type not in sections_found:
            # Whole section missing: could be a layout change, don't close.
            continue
        if _mark_absent(table, asset_id, ptr["incident_sk"], now_iso):
            summary.closed.append(asset_id)

    table.update_item(
        Key={"PK": "META", "SK": "LAST_SCRAPE"},
        UpdateExpression="SET #at = :now",
        ExpressionAttributeNames={"#at": "at"},
        ExpressionAttributeValues={":now": now_iso},
    )
    table.put_item(
        Item={
            "PK": "SCRAPE",
            "SK": now_iso,
            "source": source,
            "rows": len(rows),
            "raw_key": raw_key,
            "dsb_updated": dsb_updated,
            "opened": len(summary.opened) + len(summary.reopened),
            "closed": len(summary.closed),
        }
    )
    return summary


def _get(table, pk: str, sk: str) -> dict | None:
    return table.get_item(Key={"PK": pk, "SK": sk}).get("Item")


def _query_all(table, cond, **kw) -> list[dict]:
    items, kwargs = [], {"KeyConditionExpression": cond, **kw}
    while True:
        resp = table.query(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _latest_incident(table, asset_id: str) -> dict | None:
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"ASSET#{asset_id}")
        & Key("SK").begins_with("INCIDENT#"),
        ScanIndexForward=False,
        Limit=1,
    )
    return resp["Items"][0] if resp["Items"] else None


def _open(table, asset, row: Row, now_iso: str, prev_scrape_at, source: str):
    sk = incident_sk(now_iso)
    item = {
        "PK": f"ASSET#{asset.asset_id}",
        "SK": sk,
        "asset_id": asset.asset_id,
        "asset_type": row.asset_type,
        "station": asset.station,
        "station_slug": asset.station_slug,
        "location": asset.location,
        "labels": [row.raw_label],
        "first_seen": now_iso,
        "prev_scrape_at": prev_scrape_at,
        "start_is_lower_bound": prev_scrape_at is None,
        "last_seen": now_iso,
        "missing_count": 0,
        "status_kind": row.status_kind,
        "status_text": row.status_text,
        "expected_dates": _expected_entry(row, now_iso),
        "source": source,
        "GSI1PK": f"STATION#{asset.station_slug}",
        "GSI1SK": now_iso,
        "GSI2PK": f"YEAR#{now_iso[:4]}",
        "GSI2SK": now_iso,
    }
    table.put_item(Item=item)
    table.put_item(Item={"PK": "OPEN", "SK": asset.asset_id, "incident_sk": sk})


def _expected_entry(row: Row, now_iso: str) -> list[dict]:
    if not row.expected_date:
        return []
    return [{"date": row.expected_date, "first_seen": now_iso}]


def _touch(table, asset_id: str, sk: str, row: Row, now_iso: str):
    key = {"PK": f"ASSET#{asset_id}", "SK": sk}
    inc = _get(table, *key.values())
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
        values[":exp"] = _expected_entry(row, now_iso)
    table.update_item(
        Key=key,
        UpdateExpression="SET " + ", ".join(sets) + " REMOVE first_absent_at",
        ExpressionAttributeValues=values,
    )


def _reopen(table, asset_id: str, inc: dict, row: Row, now_iso: str):
    table.update_item(
        Key={"PK": inc["PK"], "SK": inc["SK"]},
        UpdateExpression="REMOVE ended_at, first_absent_at SET merged_gaps = list_append(if_not_exists(merged_gaps, :empty), :gap)",
        ExpressionAttributeValues={
            ":empty": [],
            ":gap": [{"from": inc["ended_at"], "to": now_iso}],
        },
    )
    table.put_item(Item={"PK": "OPEN", "SK": asset_id, "incident_sk": inc["SK"]})
    _touch(table, asset_id, inc["SK"], row, now_iso)


def _mark_absent(table, asset_id: str, sk: str, now_iso: str) -> bool:
    """Count one absence; close the incident on the Nth. Returns True if closed."""
    key = {"PK": f"ASSET#{asset_id}", "SK": sk}
    resp = table.update_item(
        Key=key,
        UpdateExpression="SET missing_count = missing_count + :one, first_absent_at = if_not_exists(first_absent_at, :now)",
        ExpressionAttributeValues={":one": 1, ":now": now_iso},
        ReturnValues="ALL_NEW",
    )
    inc = resp["Attributes"]
    if inc["missing_count"] < ABSENCES_TO_CLOSE:
        return False
    table.update_item(
        Key=key,
        UpdateExpression="SET ended_at = first_absent_at",
    )
    table.delete_item(Key={"PK": "OPEN", "SK": asset_id})
    return True


__all__ = ["reconcile", "Summary", "ELEVATOR", "ESCALATOR"]
