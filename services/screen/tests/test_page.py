"""The page renders with data in every panel, and with no data yet."""

import html
from datetime import datetime

from fastapi.testclient import TestClient

from screen import main

NOW = datetime(2026, 10, 27, 14, 5, tzinfo=main.LOCAL_TZ)


def test_page_renders_before_any_data():
    page = TestClient(main.app).get("/")  # no `with`: background collectors don't start
    assert page.status_code == 200 and "Loading" in page.text


def test_page_renders_all_panels(monkeypatch):
    def panel(data, error=None):
        return {"data": data, "updated": NOW, "error": error, "took_ms": 120}

    monkeypatch.setitem(main.panels, "news", panel({"source": "popular", "items": [
        {"rank": 1, "title": "Headline", "time": "Вчера, 10:42"}]}))
    monkeypatch.setitem(main.panels, "weather", panel(None, error="HTTP 503"))
    monkeypatch.setitem(main.panels, "tickets", panel({"counts": {"open": 0, "in_progress": 0, "overdue": 0},
                                                       "tickets": [], "hidden": 0}))
    monkeypatch.setitem(main.panels, "health", panel({"services": [
        {"name": "Users", "state": "ok", "ms": 12, "detail": "ok", "history": ["ok", "down"], "since": None},
        {"name": "Tickets", "state": "down", "ms": None, "detail": "can't connect", "history": ["down"],
         "since": "14:01"},
    ]}))
    page = TestClient(main.app).get("/")
    text = html.unescape(page.text)
    assert page.status_code == 200
    assert "Headline" in text and "Can't load: HTTP 503" in text
    assert "can't connect · since 14:01" in text
    assert "Weather · Open-Meteo" in text
