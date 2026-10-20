"""One-off: replay archived copies of DSB's page from the Wayback Machine
into the table, so history doesn't start from zero. Incidents are marked
source="wayback" (and therefore "estimated" on the site), because snapshots
are days or weeks apart.

Must run on an empty table, before the first live scrape:
    TABLE_NAME=... RAW_BUCKET=... uv run python -m tools.backfill_wayback [--dry-run]
"""

from __future__ import annotations

import gzip
import os
import sys
import time
from datetime import datetime, timezone

import boto3
import requests

from scraper.handler import URL, USER_AGENT
from scraper.parse import ParseError, parse
from scraper.reconcile import reconcile
from scraper.stats import publish

CDX = "https://web.archive.org/cdx/search/cdx"


def snapshots() -> list[str]:
    resp = requests.get(CDX, params={
        "url": URL.removeprefix("https://"),
        "output": "json",
        "fl": "timestamp",
        "filter": "statuscode:200",
        "collapse": "timestamp:8",  # one per day
    }, timeout=60, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return sorted(row[0] for row in resp.json()[1:])


def fetch(ts: str) -> str:
    # "id_" returns the original bytes without the Wayback toolbar.
    resp = requests.get(f"https://web.archive.org/web/{ts}id_/{URL}", timeout=60,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content.decode("utf-8")


def main(dry_run: bool) -> None:
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    if not dry_run and table.get_item(Key={"PK": "META", "SK": "LAST_SCRAPE"}).get("Item"):
        sys.exit("Table already has scrapes - backfill must run first, on an empty table.")
    bucket = os.environ.get("RAW_BUCKET")
    s3 = boto3.client("s3") if bucket else None

    for ts in snapshots():
        at = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        try:
            html = fetch(ts)
            result = parse(html)
        except (requests.RequestException, ParseError, UnicodeDecodeError) as e:
            print(f"{at:%Y-%m-%d} skip: {e}")
            continue
        print(f"{at:%Y-%m-%d} {len(result.rows):3} rows, sections={sorted(result.sections_found)}")
        if dry_run or not result.rows:
            continue
        raw_key = None
        if s3:
            raw_key = at.strftime("raw/wayback/%Y/%m/%d/%H%M%S.html.gz")
            s3.put_object(Bucket=bucket, Key=raw_key, Body=gzip.compress(html.encode("utf-8")),
                          ContentType="text/html; charset=utf-8", ContentEncoding="gzip")
        s = reconcile(table, result.rows, result.sections_found, at, source="wayback",
                      raw_key=raw_key, dsb_updated=result.dsb_updated)
        print(f"           opened {len(s.opened)}, closed {len(s.closed)}")
        time.sleep(1)  # be gentle with archive.org

    if not dry_run:
        publish(table, datetime.now(timezone.utc).replace(microsecond=0))


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
