"""Precompute everything the website shows, so the API only reads one item."""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .dsb import PERMANENT
from .incidents import load_all

CPH = ZoneInfo("Europe/Copenhagen")


def _days(start: str, end: str | None, now: datetime) -> float:
    e = datetime.fromisoformat(end) if end else now
    return round((e - datetime.fromisoformat(start)).total_seconds() / 86400, 1)


def _overrun_days(inc: dict, now: datetime) -> float | None:
    """Days past the first promised date (negative = fixed early)."""
    if not inc["first_expected"]:
        return None
    promised = datetime.combine(date.fromisoformat(inc["first_expected"]), datetime.max.time(), CPH)
    actual = datetime.fromisoformat(inc["end"]) if inc["end"] else now
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
    current = sorted(
        (
            {
                **i,
                "days_down": _days(i["start"], None, now),
                "overdue": bool(i["latest_expected"]) and date.fromisoformat(i["latest_expected"]) < today,
            }
            for i in incidents if not i["end"]
        ),
        key=lambda i: -i["days_down"],
    )

    # Only incidents we watched from start to end count towards repair times
    # and promise statistics.
    repair, late, overruns, moved, with_promise = [], 0, [], 0, 0
    for i in incidents:
        if not i["end"] or i["status_kind"] == PERMANENT or not i["end_is_precise"]:
            continue
        if not i["start_is_lower_bound"]:
            repair.append(_days(i["start"], i["end"], now))
        if (over := _overrun_days(i, now)) is not None:
            with_promise += 1
            moved += i["expected_changes"] > 0
            if over > 0:
                late += 1
                overruns.append(over)

    year_ago = now - timedelta(days=365)
    stations: dict[str, dict] = {}
    for i in incidents:
        s = stations.setdefault(i["station_slug"], {
            "station": i["station"], "station_slug": i["station_slug"],
            "incidents": 0, "days_down_12m": 0.0, "longest_days": 0.0, "open_now": 0,
        })
        s["incidents"] += 1
        s["open_now"] += i["end"] is None
        # An imprecise end only counts the time we actually saw it down.
        end = i["end"] if i["end_is_precise"] else i["last_seen"]
        start = max(datetime.fromisoformat(i["start"]), year_ago)
        stop = datetime.fromisoformat(end) if end else now
        if stop > start:
            s["days_down_12m"] = round(s["days_down_12m"] + (stop - start).total_seconds() / 86400, 1)
        s["longest_days"] = max(s["longest_days"], _days(i["start"], end, now))

    stats = {
        "generated_at": now.isoformat(timespec="seconds"),
        "open_now": {"total": len(current), "overdue": sum(i["overdue"] for i in current)},
        "repair_days": _summary(repair),
        "promises": {
            "closed_with_promise": with_promise,
            "closed_late": late,
            "closed_late_share": round(late / with_promise, 3) if with_promise else None,
            "overrun_days": _summary(overruns),
            "date_moved": moved,
            "open_past_promise": sum(1 for i in current if (_overrun_days(i, now) or 0) > 0),
        },
        "stations": sorted(stations.values(), key=lambda s: -s["days_down_12m"]),
        "incident_count": len(incidents),
    }
    return stats, current


def publish(table, now: datetime) -> dict:
    stats, current = compute(load_all(table), now)
    table.put_item(Item={
        "PK": "STATS",
        "SK": "LATEST",
        "stats_json": json.dumps(stats, ensure_ascii=False),
        "current_json": json.dumps(current, ensure_ascii=False),
    })
    return stats
