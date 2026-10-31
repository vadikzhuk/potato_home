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
    monkeypatch.setitem(main.panels, "estate", panel({"listings": [
        {"id": 12, "price": "8 950 €", "score": 69, "town": "Pontedassio", "province": "Imperia",
         "specs": "70 m² · 2 bedr. · apartment", "auction": "Auction 25 Nov · free",
         "summary": "Compendio immobiliare", "qr": "<svg viewBox='0 0 33 33'></svg>"}]}))
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
    assert "8 950 €" in text and "Auction 25 Nov · free" in text
    assert "<svg viewBox='0 0 33 33'></svg>" in page.text  # the QR code goes in as SVG, not escaped


def test_pixel_shift_walks_the_whole_grid():
    settings = {"max_rem": 0.5, "every_minutes": 3}
    spots = [main.pixel_shift(NOW.replace(hour=m // 60, minute=m % 60), settings) for m in range(0, 75, 3)]
    assert len(set(spots)) == 25                                   # every spot once in 75 minutes
    assert all(abs(x) <= 0.5 and abs(y) <= 0.5 for x, y in spots)
    steps = [max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(spots, spots[1:])]
    assert max(steps) == 0.25                                      # small moves only
    assert main.pixel_shift(NOW.replace(minute=1), settings) == main.pixel_shift(NOW.replace(minute=2), settings)
    assert main.pixel_shift(NOW, {"max_rem": 0, "every_minutes": 3}) == (0.0, 0.0)  # off


def test_page_is_moved():
    page = TestClient(main.app).get("/")
    assert "transform: translate(" in page.text
