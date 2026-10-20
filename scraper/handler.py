"""Scraper Lambda: fetch → store raw → parse → reconcile → stats.

Run locally against a real or local table:
    TABLE_NAME=... RAW_BUCKET=... python -m scraper.handler
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
import requests

from .parse import ParseError, parse
from .reconcile import reconcile
from .stats import publish

URL = "https://www.dsb.dk/trafikinformation/elevatorer/"
USER_AGENT = "dsb-elevator-tracker/0.1 (+https://github.com/mikkel-ops/dsb-elevator-tracker)"

# Screenshot whenever the list changes, and at least this often regardless.
SCREENSHOT_MAX_AGE = timedelta(hours=23)

log = logging.getLogger()
log.setLevel(logging.INFO)


def _alert(subject: str, message: str) -> None:
    log.error("%s: %s", subject, message)
    topic = os.environ.get("ALERT_TOPIC_ARN")
    if topic:
        boto3.client("sns").publish(TopicArn=topic, Subject=subject[:100], Message=message)


def run(now: datetime | None = None, html: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

    if html is None:
        resp = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        html = resp.content.decode("utf-8")

    raw_key = None
    bucket = os.environ.get("RAW_BUCKET")
    if bucket:
        raw_key = now.strftime("raw/%Y/%m/%d/%H%M%S.html.gz")
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=raw_key,
            Body=gzip.compress(html.encode("utf-8")),
            ContentType="text/html; charset=utf-8",
            ContentEncoding="gzip",
        )

    try:
        result = parse(html)
    except ParseError as e:
        _alert("DSB elevator scraper: parse error", f"{e}\nRaw snapshot: {raw_key}")
        return {"ok": False, "error": str(e)}

    if not result.rows:
        _alert("DSB elevator scraper: 0 rows", f"No rows parsed - layout changed?\nRaw snapshot: {raw_key}")
        return {"ok": False, "error": "no rows"}
    if len(result.sections_found) < 2:
        _alert(
            "DSB elevator scraper: section missing",
            f"Only found sections {sorted(result.sections_found)}. Incidents of the missing type "
            f"will not be closed until this is resolved.\nRaw snapshot: {raw_key}",
        )

    meta = table.get_item(Key={"PK": "META", "SK": "LAST_SCRAPE"}).get("Item") or {}
    summary = reconcile(
        table, result.rows, result.sections_found, now,
        raw_key=raw_key, dsb_updated=result.dsb_updated,
    )
    stats = publish(table, now)
    screenshot = _maybe_screenshot(table, meta, result.rows, now)
    out = {
        "ok": True,
        "rows": len(result.rows),
        "opened": summary.opened,
        "reopened": summary.reopened,
        "closed": summary.closed,
        "open_now": stats["open_now"],
        "screenshot_requested": screenshot,
    }
    log.info(json.dumps(out, ensure_ascii=False))
    return out


def content_hash(rows) -> str:
    payload = json.dumps(sorted((r.asset_type, r.raw_label, r.status_text) for r in rows), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _maybe_screenshot(table, meta: dict, rows, now: datetime) -> bool:
    """Ask the screenshot Lambda for evidence if the list changed or it's been a day."""
    function = os.environ.get("SCREENSHOT_FUNCTION")
    digest = content_hash(rows)
    last = meta.get("last_screenshot_at")
    due = (
        digest != meta.get("content_hash")
        or not last
        or now - datetime.fromisoformat(last) >= SCREENSHOT_MAX_AGE
    )
    updates, values = ["content_hash = :h"], {":h": digest}
    if due and function:
        boto3.client("lambda").invoke(
            FunctionName=function,
            InvocationType="Event",
            Payload=json.dumps({"at": now.isoformat(timespec="seconds")}).encode(),
        )
        updates.append("last_screenshot_at = :now")
        values[":now"] = now.isoformat(timespec="seconds")
    table.update_item(
        Key={"PK": "META", "SK": "LAST_SCRAPE"},
        UpdateExpression="SET " + ", ".join(updates),
        ExpressionAttributeValues=values,
    )
    return due and bool(function)


def lambda_handler(event, context):
    try:
        return run()
    except Exception as e:  # noqa: BLE001 - we want an alert for anything
        _alert("DSB elevator scraper: crash", repr(e))
        raise


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
