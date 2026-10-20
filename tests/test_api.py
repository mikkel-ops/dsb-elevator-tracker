from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.app import app
from scraper.handler import run

T0 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def test_end_to_end(table, html):
    out = run(now=T0, html=html)
    assert out["ok"] and out["open_now"]["total"] == 33

    c = TestClient(app)
    stats = c.get("/api/stats").json()
    assert stats["open_now"]["elevator"] == 19
    assert c.get("/api/stats").headers["cache-control"] == "public, max-age=300"

    current = c.get("/api/current").json()
    assert any(i["station"] == "Svanemøllen" for i in current)

    st = c.get("/api/stations/bispebjerg").json()
    assert st["station"] == "Bispebjerg" and len(st["incidents"]) == 1
    assert c.get("/api/stations/findes-ikke").status_code == 404

    assert len(c.get("/api/incidents", params={"year": 2026, "type": "escalator"}).json()) == 14

    csv = c.get("/api/export.csv").text
    assert csv.startswith("asset_id,") and csv.count("\n") == 34


def test_no_data_yet(table):
    assert TestClient(app).get("/api/stats").status_code == 503


def test_zero_rows_does_not_touch_incidents(table, html):
    run(now=T0, html=html)
    broken = html.replace("Elevatorer på følgende", "Noget andet").replace("Rulletrapperne på", "Noget")
    assert run(now=T0, html=broken) == {"ok": False, "error": "no rows"}


def test_evidence(table, html):
    from datetime import timedelta
    run(now=T0, html=html)
    run(now=T0 + timedelta(hours=1), html=html)
    # Pretend the screenshot Lambda handled the first scrape.
    table.update_item(Key={"PK": "SCRAPE", "SK": T0.isoformat()},
                      UpdateExpression="SET screenshot_key = :k, raw_key = :r",
                      ExpressionAttributeValues={":k": "screenshots/a.png", ":r": "raw/a.html.gz"})
    c = TestClient(app)
    ev = c.get("/api/evidence", params={"at": (T0 + timedelta(hours=1, minutes=5)).isoformat()}).json()
    assert ev["screenshot"] == {"at": T0.isoformat(), "url": "/screenshots/a.png", "sha256": None}
    assert ev["html"] is None  # second scrape ran without RAW_BUCKET in tests
    snaps = c.get("/api/snapshots", params={"day": "2026-10-20"}).json()
    assert len(snaps) == 2


def test_screenshot_requested_on_change_only(table, html, monkeypatch):
    from datetime import timedelta
    from unittest.mock import MagicMock
    import scraper.handler as h
    invoke = MagicMock()
    monkeypatch.setenv("SCREENSHOT_FUNCTION", "shot")
    real_client = h.boto3.client
    monkeypatch.setattr(h.boto3, "client", lambda svc, *a, **k: MagicMock(invoke=invoke) if svc == "lambda" else real_client(svc, *a, **k))
    assert run(now=T0, html=html)["screenshot_requested"]
    assert not run(now=T0 + timedelta(hours=1), html=html)["screenshot_requested"]
    changed = html.replace("Bispebjerg: </b>Forventes i drift den 24.10.26", "Bispebjerg: </b>Forventes i drift den 30.10.26")
    assert run(now=T0 + timedelta(hours=2), html=changed)["screenshot_requested"]
    assert run(now=T0 + timedelta(hours=26), html=changed)["screenshot_requested"]  # daily
    assert invoke.call_count == 3
