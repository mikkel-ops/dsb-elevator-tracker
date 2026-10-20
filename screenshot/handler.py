"""Screenshot Lambda (container image with Playwright + Chromium).

Invoked asynchronously by the scraper with {"at": "<scrape iso time>"} when the
list on DSB's page changed, and at least once a day. Stores a full-page PNG
next to the raw HTML and records its key on the SCRAPE log item, so every
incident can be backed by "this is what DSB's page looked like".
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
from datetime import datetime

import boto3
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

URL = "https://www.dsb.dk/trafikinformation/elevatorer/"
CONTENT = 'section[aria-label="Stations information"]'
# CookieInformation's banner; we decline rather than hide it.
DECLINE_BUTTON = "#declineButton, button.coi-banner__decline"
DECLINE_TEXT = re.compile("Afvis alle|Kun nødvendige")
# Chromium flags needed inside Lambda's sandbox-less, /tmp-only environment.
CHROMIUM_ARGS = [
    "--no-sandbox", "--no-zygote", "--single-process",
    "--disable-gpu", "--disable-dev-shm-usage",
]

log = logging.getLogger()
log.setLevel(logging.INFO)


def capture() -> tuple[bytes, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=CHROMIUM_ARGS)
        try:
            page = browser.new_page(
                viewport={"width": 1280, "height": 900},
                locale="da-DK",
                timezone_id="Europe/Copenhagen",
            )
            page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_selector(CONTENT, timeout=30_000)
            decline = page.locator(DECLINE_BUTTON).or_(page.get_by_role("button", name=DECLINE_TEXT))
            try:
                decline.first.click(timeout=3_000)
            except PlaywrightTimeout:
                log.warning("cookie banner not found; screenshot taken anyway")
            page.wait_for_timeout(1_000)
            png = page.screenshot(full_page=True, type="png")
            return png, page.content()
        finally:
            browser.close()


def handler(event, context):
    at = datetime.fromisoformat(event["at"])
    png, html = capture()
    bucket = os.environ["RAW_BUCKET"]
    s3 = boto3.client("s3")
    base = at.strftime("screenshots/%Y/%m/%d/%H%M%S")
    sha = hashlib.sha256(png).hexdigest()
    s3.put_object(
        Bucket=bucket, Key=f"{base}.png", Body=png, ContentType="image/png",
        Metadata={"source-url": URL, "scrape-at": event["at"], "sha256": sha},
    )
    s3.put_object(
        Bucket=bucket, Key=f"{base}.html.gz", Body=gzip.compress(html.encode("utf-8")),
        ContentType="text/html; charset=utf-8", ContentEncoding="gzip",
    )
    boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]).update_item(
        Key={"PK": "SCRAPE", "SK": event["at"]},
        UpdateExpression="SET screenshot_key = :k, screenshot_sha256 = :s",
        ExpressionAttributeValues={":k": f"{base}.png", ":s": sha},
    )
    out = {"key": f"{base}.png", "bytes": len(png), "sha256": sha}
    log.info(json.dumps(out))
    return out
