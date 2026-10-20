"""Hourly Lambda: fetch → archive raw HTML → incidents → stats → maybe screenshot."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

from . import db, dsb
from .incidents import reconcile
from .stats import publish

# Screenshot whenever the list changes, and at least this often regardless.
SCREENSHOT_MAX_AGE = timedelta(hours=23)

log = logging.getLogger()
log.setLevel(logging.INFO)


def _alert(subject: str, message: str) -> None:
    log.error("%s: %s", subject, message)
    if topic := os.environ.get("ALERT_TOPIC_ARN"):
        boto3.client("sns").publish(TopicArn=topic, Subject=subject[:100], Message=message)


def archive(html: str, now: datetime) -> str | None:
    bucket = os.environ.get("RAW_BUCKET")
    if not bucket:
        return None
    key = now.strftime("raw/%Y/%m/%d/%H%M%S.html.gz")
    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=gzip.compress(html.encode("utf-8")),
        ContentType="text/html; charset=utf-8", ContentEncoding="gzip",
    )
    return key


def process(table, html: str, now: datetime, raw_key: str | None) -> dsb.ParseResult | None:
    """Parse one snapshot and apply it. Returns None (and alerts) if it looks broken -
    in that case nothing is touched, so a layout change can't close every incident."""
    try:
        result = dsb.parse(html)
    except dsb.ParseError as e:
        _alert("DSB elevator scraper: parse error", f"{e}\nRaw snapshot: {raw_key}")
        return None
    if not result.found_section or not result.rows:
        _alert("DSB elevator scraper: no elevators parsed",
               f"Section found: {result.found_section}, rows: {len(result.rows)} - layout changed?\n"
               f"Raw snapshot: {raw_key}")
        return None
    reconcile(table, result.rows, now, raw_key=raw_key, dsb_updated=result.dsb_updated)
    return result


def content_hash(rows: list[dsb.Row]) -> str:
    payload = json.dumps(sorted((r.raw_label, r.status_text) for r in rows), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _maybe_screenshot(table, rows: list[dsb.Row], now: datetime) -> bool:
    """Ask the screenshot Lambda for evidence if the list changed or it's been a day."""
    meta = table.get_item(Key={"PK": "META", "SK": "LAST_SCRAPE"}).get("Item") or {}
    digest, last = content_hash(rows), meta.get("last_screenshot_at")
    due = digest != meta.get("content_hash") or not last \
        or now - datetime.fromisoformat(last) >= SCREENSHOT_MAX_AGE
    function = os.environ.get("SCREENSHOT_FUNCTION")
    sets, values = ["content_hash = :h"], {":h": digest}
    if due and function:
        boto3.client("lambda").invoke(
            FunctionName=function, InvocationType="Event",
            Payload=json.dumps({"at": now.isoformat(timespec="seconds")}).encode(),
        )
        sets.append("last_screenshot_at = :now")
        values[":now"] = now.isoformat(timespec="seconds")
    table.update_item(Key={"PK": "META", "SK": "LAST_SCRAPE"},
                      UpdateExpression="SET " + ", ".join(sets), ExpressionAttributeValues=values)
    return due and bool(function)


def run(now: datetime | None = None, html: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    table = db.table()
    html = html if html is not None else dsb.fetch()
    result = process(table, html, now, archive(html, now))
    if result is None:
        return {"ok": False}
    stats = publish(table, now)
    out = {
        "ok": True,
        "rows": len(result.rows),
        "open_now": stats["open_now"],
        "screenshot_requested": _maybe_screenshot(table, result.rows, now),
    }
    log.info(json.dumps(out, ensure_ascii=False))
    return out


def handler(event, context):
    try:
        return run()
    except Exception as e:  # noqa: BLE001 - we want an alert for anything
        _alert("DSB elevator scraper: crash", repr(e))
        raise
