"""Local development against DynamoDB Local.

    docker run -d --rm -p 8001:8000 --name ddb-local amazon/dynamodb-local
    uv run python -m tools.dev_local [--demo]     # create table + scrape live page
    LOCAL_CORS=1 uv run uvicorn api.app:app --port 8000
    python3 -m http.server 8080 -d site

--demo also replays the test fixture 20 days back, so charts have something
to show. Never point this at the real table.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("AWS_ENDPOINT_URL_DYNAMODB", "http://localhost:8001")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-north-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
os.environ.setdefault("TABLE_NAME", "dsb-elevator-tracker")

import boto3  # noqa: E402

from scraper.handler import run  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "2026-10-20.html"


def create_table():
    ddb = boto3.client("dynamodb")
    name = os.environ["TABLE_NAME"]
    if name in ddb.list_tables()["TableNames"]:
        ddb.delete_table(TableName=name)
    cap = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
    gsi = lambda n: {
        "IndexName": n,
        "KeySchema": [{"AttributeName": f"{n}PK", "KeyType": "HASH"}, {"AttributeName": f"{n}SK", "KeyType": "RANGE"}],
        "Projection": {"ProjectionType": "ALL"},
        "ProvisionedThroughput": cap,
    }
    ddb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"]],
        GlobalSecondaryIndexes=[gsi("GSI1"), gsi("GSI2")],
        ProvisionedThroughput=cap,
    )


if __name__ == "__main__":
    create_table()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if "--demo" in sys.argv:
        html = FIXTURE.read_text(encoding="utf-8")
        demo = html.replace("<b>Sorgenfri: </b>Forventes i drift den 21.11.26", "")
        run(now=now - timedelta(days=40), html=demo)
        run(now=now - timedelta(days=20), html=html)
        run(now=now - timedelta(days=20) + timedelta(hours=1), html=html)
    print(run(now=now))
