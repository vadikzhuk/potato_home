from datetime import datetime

import httpx
import pytest

from screen.collectors import health

NOW = datetime(2026, 10, 27, 14, 5)


@pytest.fixture(autouse=True)
def fresh_memory(monkeypatch):
    monkeypatch.setattr(health, "history", {})
    monkeypatch.setattr(health, "state_since", {})


def test_classify():
    assert health.classify(200, {"status": "ok"}, 40, 800) == ("ok", 40, "ok")
    assert health.classify(200, {"status": "ok"}, 1200, 800) == ("slow", 1200, "slow to answer")
    assert health.classify(200, {"status": "degraded", "detail": "users down"}, 40, 800) == ("warn", 40, "users down")
    assert health.classify(500, {}, 40, 800) == ("down", 40, "HTTP 500")
    assert health.classify(503, {"detail": "db locked"}, 40, 800) == ("down", 40, "db locked")


def test_check_explains_connection_problems(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused")

    def hang(*args, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(health.httpx, "get", refuse)
    assert health.check("http://x/health", 800, 5) == ("down", None, "can't connect")
    monkeypatch.setattr(health.httpx, "get", hang)
    assert health.check("http://x/health", 800, 5) == ("down", None, "no answer in 5 s")


def test_history_and_since():
    for state in ["ok", "ok", "down"]:
        row = health.remember("Tickets", state, None, "x", NOW)
    assert row["history"] == ["ok", "ok", "down"] and row["since"] == "14:05"

    later = datetime(2026, 10, 27, 14, 30)
    row = health.remember("Tickets", "down", None, "x", later)
    assert row["since"] == "14:05"                      # still down since the first failure
    row = health.remember("Tickets", "ok", 20, "ok", later)
    assert row["since"] is None                          # ok rows don't show "since"

    for _ in range(20):
        row = health.remember("Tickets", "ok", 20, "ok", later)
    assert len(row["history"]) == health.HISTORY


def test_source_row():
    panel = {"error": None, "updated": NOW, "took_ms": 300}
    assert health.source_row("Weather", panel, 800)["state"] == "ok"
    assert health.source_row("Weather", {**panel, "took_ms": 2000}, 800)["state"] == "slow"
    row = health.source_row("News", {**panel, "error": "HTTP 503"}, 800)
    assert (row["state"], row["detail"], row["updated"]) == ("down", "HTTP 503", "14:05")
    assert health.source_row("News", {"error": None, "updated": None, "took_ms": None}, 800)["state"] == "wait"
