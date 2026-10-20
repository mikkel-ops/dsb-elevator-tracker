from datetime import timedelta
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from elevator_tracker import scraper
from elevator_tracker.api import app
from test_incidents import T0, H


def test_end_to_end(table, html):
    out = scraper.run(now=T0, html=html)
    assert out["ok"] and out["open_now"]["total"] == 19

    c = TestClient(app)
    r = c.get("/api/stats")
    assert r.json()["open_now"]["total"] == 19
    assert r.headers["cache-control"] == "public, max-age=300"
    assert any(i["station"] == "Svanemøllen" for i in c.get("/api/current").json())
    st = c.get("/api/stations/bispebjerg").json()
    assert st["station"] == "Bispebjerg" and len(st["incidents"]) == 1
    assert c.get("/api/stations/findes-ikke").status_code == 404
    assert c.get("/api/incidents").status_code == 404  # removed
    assert c.get("/api/export.csv").text.count("\n") == 20


def test_no_data_yet(table):
    assert TestClient(app).get("/api/stats").status_code == 503


def test_broken_page_touches_nothing(table, html):
    scraper.run(now=T0, html=html)
    broken = html.replace("Elevatorer på følgende", "Noget andet")
    assert scraper.run(now=T0 + H, html=broken) == {"ok": False}
    assert TestClient(app).get("/api/stats").json()["open_now"]["total"] == 19


def test_evidence(table, html):
    scraper.run(now=T0, html=html)
    scraper.run(now=T0 + H, html=html)
    table.update_item(Key={"PK": "SCRAPE", "SK": T0.isoformat()},
                      UpdateExpression="SET screenshot_key = :k, raw_key = :r",
                      ExpressionAttributeValues={":k": "screenshots/a.png", ":r": "raw/a.html.gz"})
    c = TestClient(app)
    ev = c.get("/api/evidence", params={"at": (T0 + H + timedelta(minutes=5)).isoformat()}).json()
    assert ev["screenshot"] == {"at": T0.isoformat(), "url": "/screenshots/a.png", "sha256": None}
    assert ev["html"] is None  # second scrape ran without RAW_BUCKET
    assert len(c.get("/api/snapshots", params={"day": "2026-10-20"}).json()) == 2


def test_screenshot_on_change_or_daily(table, html, monkeypatch):
    invoke = MagicMock()
    monkeypatch.setenv("SCREENSHOT_FUNCTION", "shot")
    real = scraper.boto3.client
    monkeypatch.setattr(scraper.boto3, "client",
                        lambda svc, *a, **k: MagicMock(invoke=invoke) if svc == "lambda" else real(svc, *a, **k))
    assert scraper.run(now=T0, html=html)["screenshot_requested"]
    assert not scraper.run(now=T0 + H, html=html)["screenshot_requested"]
    changed = html.replace("Bispebjerg: </b>Forventes i drift den 24.10.26",
                           "Bispebjerg: </b>Forventes i drift den 30.10.26")
    assert scraper.run(now=T0 + 2 * H, html=changed)["screenshot_requested"]
    assert scraper.run(now=T0 + 26 * H, html=changed)["screenshot_requested"]  # daily
    assert invoke.call_count == 3
