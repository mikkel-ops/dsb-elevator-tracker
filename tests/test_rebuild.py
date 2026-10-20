import gzip

import boto3

from tools.rebuild import rebuild


def test_rebuild_replays_own_snapshots_only(table, html):
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="raw", CreateBucketConfiguration={"LocationConstraint": "eu-north-1"})
    put = lambda key, body, **kw: s3.put_object(Bucket="raw", Key=key, Body=body, **kw)  # noqa: E731
    without_bis = html.replace("<b>Bispebjerg: </b>Forventes i drift den 24.10.26", "")
    put("raw/2026/10/20/150000.html.gz", gzip.compress(html.encode()))
    put("raw/2026/10/20/160000.html.gz", gzip.compress(html.encode()))
    put("raw/2026/10/20/170000.html.gz", gzip.compress(without_bis.encode()))
    put("raw/2026/10/20/180000.html.gz", gzip.compress(without_bis.encode()))
    put("raw/wayback/2025/02/13/202752.html.gz", gzip.compress(html.encode()))  # ignored
    put("screenshots/2026/10/20/150000.png", b"png", Metadata={"sha256": "abc"})
    table.put_item(Item={"PK": "ASSET#stale", "SK": "INCIDENT#2025"})  # wiped

    out = rebuild(table, s3, "raw")
    assert out["deleted"] == 1 and out["replayed"] == 4 and out["screenshots"] == 1
    assert out["open_now"]["total"] == 18  # Bispebjerg closed after two absences
    scrape = table.get_item(Key={"PK": "SCRAPE", "SK": "2026-10-20T15:00:00+00:00"})["Item"]
    assert scrape["screenshot_key"] == "screenshots/2026/10/20/150000.png"
    assert "Item" not in table.get_item(Key={"PK": "ASSET#stale", "SK": "INCIDENT#2025"})
