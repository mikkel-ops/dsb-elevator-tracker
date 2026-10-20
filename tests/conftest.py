from pathlib import Path

import pytest
from moto import mock_aws

from elevator_tracker import db

FIXTURE = Path(__file__).parent / "fixtures" / "2026-10-20.html"


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def table(monkeypatch):
    for k, v in {"AWS_DEFAULT_REGION": "eu-north-1", "AWS_ACCESS_KEY_ID": "test",
                 "AWS_SECRET_ACCESS_KEY": "test", "TABLE_NAME": "test"}.items():
        monkeypatch.setenv(k, v)
    for k in ("RAW_BUCKET", "ALERT_TOPIC_ARN", "SCREENSHOT_FUNCTION"):
        monkeypatch.delenv(k, raising=False)
    with mock_aws():
        yield db.create_table("test")
