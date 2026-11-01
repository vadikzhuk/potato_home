import threading

import pytest
from fastapi.testclient import TestClient

from botwatch import api, core, db, watcher

from helpers import SETTINGS, FakeDocker, FakeTelegram

EVENT = {"at": "2026-11-01T12:00:00+00:00", "kind": "command", "name": "/start", "user": 7, "ms": 20, "ok": True}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTWATCH_DB", str(tmp_path / "botwatch.db"))
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setenv("USAGE_TOKEN", "usage")
    monkeypatch.setattr(watcher, "start", threading.Event)  # no real checking in tests
    monkeypatch.setattr(watcher, "last_round", {"at": None, "problem": None, "every": 60})
    docker, telegram = FakeDocker("quiz"), FakeTelegram()
    conn = db.connect()
    core.check_all(conn, docker, telegram, SETTINGS)
    conn.close()
    with TestClient(api.app, headers={"X-Api-Token": "secret"}) as c:
        c.docker, c.telegram = docker, telegram
        yield c


def check_again(client):
    conn = db.connect()
    core.check_all(conn, client.docker, client.telegram, SETTINGS)
    conn.close()


def test_tokens(client):
    assert client.get("/health", headers={"X-Api-Token": ""}).status_code == 200
    assert client.get("/bots", headers={"X-Api-Token": "wrong"}).status_code == 401
    usage = {"username": "quiz_bot", "events": [EVENT]}
    # a bot has only the usage token: it can send usage, but read nothing
    assert client.post("/usage", json=usage, headers={"X-Api-Token": "", "X-Usage-Token": "usage"}).json() == {"saved": 1}
    assert client.post("/usage", json=usage, headers={"X-Api-Token": "", "X-Usage-Token": "bad"}).status_code == 401
    assert client.get("/bots", headers={"X-Api-Token": "usage"}).status_code == 401


def test_bots_usage_and_alerts(client):
    client.post("/usage", json={"username": "quiz_bot", "events": [EVENT, {**EVENT, "user": 8}]})
    [bot] = client.get("/bots").json()
    assert bot["bot"] == "quiz" and bot["username"] == "quiz_bot" and bot["problems"] == []
    usage = client.get("/bots/quiz/usage", params={"days": 30}).json()
    assert usage["total"]["users"] == 2 and usage["commands"] == [["/start", 2]]
    assert client.get("/bots/nobody/usage").status_code == 404
    first = client.get("/alerts").json()
    assert [a["text"] for a in first] == ["👀 Watching a new bot: quiz (@quiz_bot)"]
    assert client.get("/alerts", params={"after": first[-1]["id"]}).json() == []


def test_bad_usage_is_refused(client):
    assert client.post("/usage", json={"username": "quiz_bot", "events": [{"kind": "x"}]}).status_code == 422
    assert client.post("/usage", json={"events": [EVENT]}).status_code == 422


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "detail": "1 bot ok"}
    client.telegram.problem = "Telegram rejects the token (revoked or mistyped?)"
    check_again(client)
    assert client.get("/health").json() == {
        "status": "degraded", "detail": "quiz: Telegram rejects the token (revoked or mistyped?)"}
    watcher.last_round["problem"] = "Docker isn't reachable at http://docker-proxy:2375 (ConnectError)"
    assert client.get("/health").json()["detail"].startswith("Docker isn't reachable")
