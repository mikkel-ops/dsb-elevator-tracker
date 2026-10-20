"""Precompute everything the website shows, so the API only reads one item."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Attr

from .parse import PERMANENT

CPH = ZoneInfo("Europe/Copenhagen")
# Incidents whose start or end is only known to within this are "estimated".
PRECISE = timedelta(days=1)


def load_incidents(table) -> list[dict]:
    items, kwargs = [], {"FilterExpression": Attr("SK").begins_with("INCIDENT#")}
    while True:
        resp = table.scan(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [public_incident(i) for i in items]


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def public_incident(item: dict) -> dict:
    """Strip storage keys and convert Decimals - the shape the API returns."""
    first_seen = _dt(item["first_seen"])
    prev = _dt(item.get("prev_scrape_at"))
    ended = _dt(item.get("ended_at"))
    last_seen = _dt(item["last_seen"])
    expected = [e["date"] for e in item.get("expected_dates", [])]
    estimated = (
        item.get("source") != "live"
        or (prev is not None and first_seen - prev > PRECISE)
        or (ended is not None and ended - last_seen > PRECISE)
    )
    return {
        "asset_id": item["asset_id"],
        "asset_type": item["asset_type"],
        "station": item["station"],
        "station_slug": item["station_slug"],
        "location": item.get("location", ""),
        "label": item["labels"][-1],
        "status_kind": item["status_kind"],
        "status_text": item["status_text"],
        "start": item["first_seen"],
        # Unknown start, or only known to within a wide window (e.g. after a
        # Wayback gap): either way the duration is a lower bound.
        "start_is_lower_bound": bool(item.get("start_is_lower_bound"))
        or (prev is not None and first_seen - prev > PRECISE),
        "end": item.get("ended_at"),
        "last_seen": item["last_seen"],
        "first_expected": expected[0] if expected else None,
        "latest_expected": expected[-1] if expected else None,
        "expected_changes": max(len(expected) - 1, 0),
        "expected_history": expected,
        "estimated": estimated,
        "source": item.get("source", "live"),
    }


def _days(start: str, end: str | None, now: datetime) -> float:
    e = _dt(end) or now
    return round((e - _dt(start)).total_seconds() / 86400, 1)


def _overrun_days(inc: dict, now: datetime) -> float | None:
    """Days past the first promised date (negative = fixed early)."""
    if not inc["first_expected"]:
        return None
    promised = datetime.combine(date.fromisoformat(inc["first_expected"]), datetime.max.time(), CPH)
    actual = _dt(inc["end"]) or now
    return round((actual - promised).total_seconds() / 86400, 1)


def _summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "max": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
    }


def compute(incidents: list[dict], now: datetime) -> tuple[dict, list[dict]]:
    today = now.astimezone(CPH).date()
    current = []
    for inc in incidents:
        if inc["end"]:
            continue
        overdue = bool(inc["latest_expected"]) and date.fromisoformat(inc["latest_expected"]) < today
        current.append({**inc, "days_down": _days(inc["start"], None, now), "overdue": overdue})
    current.sort(key=lambda i: -i["days_down"])

    by_type: dict[str, list[float]] = defaultdict(list)
    promise = {"closed_with_promise": 0, "late": 0, "overrun_days": [], "changed": 0}
    for inc in incidents:
        if not inc["end"] or inc["status_kind"] == PERMANENT:
            continue
        if not inc["start_is_lower_bound"] and not inc["estimated"]:
            by_type[inc["asset_type"]].append(_days(inc["start"], inc["end"], now))
        over = _overrun_days(inc, now) if not inc["estimated"] else None
        if over is not None:
            promise["closed_with_promise"] += 1
            promise["late"] += over > 0
            promise["changed"] += inc["expected_changes"] > 0
            if over > 0:
                promise["overrun_days"].append(over)

    # Currently-open incidents already past their first promise count too.
    open_late = sum(1 for i in current if (_overrun_days(i, now) or 0) > 0)

    year_ago = now - timedelta(days=365)
    stations: dict[str, dict] = {}
    for inc in incidents:
        s = stations.setdefault(
            inc["station_slug"],
            {"station": inc["station"], "station_slug": inc["station_slug"],
             "incidents": 0, "days_down_12m": 0.0, "longest_days": 0.0, "open_now": 0},
        )
        s["incidents"] += 1
        s["open_now"] += inc["end"] is None
        # Imprecise (e.g. Wayback) ends count only the time we *saw* it down.
        known_end = inc["last_seen"] if inc["end"] and inc["estimated"] else inc["end"]
        start, end = max(_dt(inc["start"]), year_ago), _dt(known_end) or now
        if end > start:
            s["days_down_12m"] = round(s["days_down_12m"] + (end - start).total_seconds() / 86400, 1)
        s["longest_days"] = max(s["longest_days"], _days(inc["start"], known_end, now))

    stats = {
        "generated_at": now.isoformat(timespec="seconds"),
        "open_now": {
            "total": len(current),
            "elevator": sum(i["asset_type"] == "elevator" for i in current),
            "escalator": sum(i["asset_type"] == "escalator" for i in current),
            "overdue": sum(i["overdue"] for i in current),
        },
        "repair_days": {t: _summary(v) for t, v in by_type.items()},
        "promises": {
            "closed_with_promise": promise["closed_with_promise"],
            "closed_late": promise["late"],
            "closed_late_share": round(promise["late"] / promise["closed_with_promise"], 3)
            if promise["closed_with_promise"] else None,
            "overrun_days": _summary(promise["overrun_days"]),
            "date_moved": promise["changed"],
            "open_past_promise": open_late,
        },
        "stations": sorted(stations.values(), key=lambda s: -s["days_down_12m"]),
        "incident_count": len(incidents),
    }
    return stats, current


def publish(table, now: datetime) -> dict:
    stats, current = compute(load_incidents(table), now)
    table.put_item(
        Item={
            "PK": "STATS",
            "SK": "LATEST",
            "stats_json": json.dumps(stats, ensure_ascii=False),
            "current_json": json.dumps(current, ensure_ascii=False),
        }
    )
    return stats
