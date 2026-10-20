import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

FIXTURE = Path(__file__).parent / "fixtures" / "2026-10-20.html"


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-north-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("TABLE_NAME", "test")
    monkeypatch.delenv("RAW_BUCKET", raising=False)
    monkeypatch.delenv("ALERT_TOPIC_ARN", raising=False)
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        gsi = lambda n: {
            "IndexName": n,
            "KeySchema": [{"AttributeName": f"{n}PK", "KeyType": "HASH"},
                          {"AttributeName": f"{n}SK", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"},
        }
        yield ddb.create_table(
            TableName="test",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"}
                                  for a in ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"]],
            GlobalSecondaryIndexes=[gsi("GSI1"), gsi("GSI2")],
            BillingMode="PAY_PER_REQUEST",
        )
