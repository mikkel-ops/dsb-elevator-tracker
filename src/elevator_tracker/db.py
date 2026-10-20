"""DynamoDB access shared by the scraper, the API, tests and tools.

Single table, PK/SK strings:
  ASSET#<asset_id> / INCIDENT#<start_iso>  one outage of one elevator
  OPEN             / <asset_id>            pointer to its open incident
  SCRAPE           / <iso>                 log of each successful scrape
  META             / LAST_SCRAPE           state carried between scrapes
  STATS            / LATEST                precomputed numbers for the site
GSI1 (GSI1PK=STATION#<slug>, GSI1SK=<start_iso>): incidents per station.
"""

from __future__ import annotations

import os

import boto3


def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _paginate(call, **kwargs) -> list[dict]:
    items = []
    while True:
        resp = call(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def query_all(t, **kwargs) -> list[dict]:
    return _paginate(t.query, **kwargs)


def scan_all(t, **kwargs) -> list[dict]:
    return _paginate(t.scan, **kwargs)


def create_table(name: str):
    """Same schema as infra/storage.tf - used by tests and `make dev`."""
    keys = lambda pk, sk: [  # noqa: E731
        {"AttributeName": pk, "KeyType": "HASH"},
        {"AttributeName": sk, "KeyType": "RANGE"},
    ]
    cap = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
    return boto3.resource("dynamodb").create_table(
        TableName=name,
        KeySchema=keys("PK", "SK"),
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in ["PK", "SK", "GSI1PK", "GSI1SK"]
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "GSI1",
            "KeySchema": keys("GSI1PK", "GSI1SK"),
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": cap,
        }],
        ProvisionedThroughput=cap,
    )
