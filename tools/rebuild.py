"""Rebuild the table from our own archive: wipe it, replay every hourly raw
snapshot in S3 (raw/YYYY/...) in order, re-attach screenshots, publish stats.
Use after changing parsing/normalisation rules - nothing is lost, since the
raw HTML is the source of truth.

    TABLE_NAME=... RAW_BUCKET=... uv run python -m tools.rebuild --yes
"""

from __future__ import annotations

import gzip
import os
import re
import sys
from datetime import datetime, timezone

import boto3

from elevator_tracker import db
from elevator_tracker.scraper import content_hash, process
from elevator_tracker.stats import publish

# raw/2026/10/20/153344.html.gz - own snapshots only (skips e.g. raw/wayback/).
KEY_RE = re.compile(r"^(?:raw|screenshots)/(\d{4})/(\d{2})/(\d{2})/(\d{6})\.(html\.gz|png)$")


def _at(key: str) -> datetime | None:
    m = KEY_RE.match(key)
    if not m:
        return None
    y, mo, d, hms, _ = m.groups()
    return datetime.strptime(f"{y}{mo}{d}{hms}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _keys(s3, bucket: str, prefix: str, suffix: str) -> list[tuple[datetime, str]]:
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(suffix) and (at := _at(obj["Key"])):
                out.append((at, obj["Key"]))
    return sorted(out)


def rebuild(table, s3, bucket: str) -> dict:
    keys = [{"PK": i["PK"], "SK": i["SK"]} for i in db.scan_all(table, ProjectionExpression="PK, SK")]
    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)

    replayed, result = 0, None
    for at, key in _keys(s3, bucket, "raw/", ".html.gz"):
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        html = gzip.decompress(body).decode("utf-8")
        if r := process(table, html, at, key):
            replayed, result = replayed + 1, r

    shots = _keys(s3, bucket, "screenshots/", ".png")
    for at, key in shots:
        scrape_key = {"PK": "SCRAPE", "SK": at.isoformat(timespec="seconds")}
        if "Item" not in table.get_item(Key=scrape_key):
            continue  # screenshot of a scrape that was rejected as broken
        sha = s3.head_object(Bucket=bucket, Key=key)["Metadata"].get("sha256")
        table.update_item(Key=scrape_key, UpdateExpression="SET screenshot_key = :k, screenshot_sha256 = :s",
                          ExpressionAttributeValues={":k": key, ":s": sha})
    if result and shots:
        table.update_item(
            Key={"PK": "META", "SK": "LAST_SCRAPE"},
            UpdateExpression="SET content_hash = :h, last_screenshot_at = :t",
            ExpressionAttributeValues={":h": content_hash(result.rows),
                                       ":t": shots[-1][0].isoformat(timespec="seconds")},
        )
    stats = publish(table, datetime.now(timezone.utc).replace(microsecond=0))
    return {"deleted": len(keys), "replayed": replayed, "screenshots": len(shots), "open_now": stats["open_now"]}


if __name__ == "__main__":
    if "--yes" not in sys.argv:
        sys.exit("This deletes every item in the table and replays S3. Re-run with --yes.")
    print(rebuild(db.table(), boto3.client("s3"), os.environ["RAW_BUCKET"]))
