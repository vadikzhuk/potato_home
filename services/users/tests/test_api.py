import pytest
from fastapi.testclient import TestClient

from users import api, core, db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("USERS_SEED", str(tmp_path / "no-seed.yaml"))
    monkeypatch.setenv("API_TOKEN", "secret")
    conn = db.connect()
    admin = core.add_user(conn, None, "Alex", telegram_id=111)
    core.add_user(conn, admin, "Anna", telegram_id=222)
    conn.close()
    with TestClient(api.app, headers={"X-Api-Token": "secret"}) as c:
        yield c


ALEX = {"X-Telegram-Id": "111"}
ANNA = {"X-Telegram-Id": "222"}


def test_token_is_required(client):
    assert client.get("/health", headers={"X-Api-Token": ""}).status_code == 200
    assert client.get("/users", headers={"X-Api-Token": "wrong"}).status_code == 401


def test_services_may_read_people_need_access(client):
    assert len(client.get("/users").json()) == 2                       # a service asking
    assert client.get("/users", headers=ANNA).status_code == 403       # Anna has no users access
    assert client.get("/users", headers=ALEX).status_code == 200
    assert client.get("/users/by-telegram/222").json()["name"] == "Anna"  # identifying is always fine


def test_grant_and_revoke(client):
    anna = client.get("/users/by-name/anna").json()
    r = client.put(f"/users/{anna['id']}/access/tickets", json={"level": "write"}, headers=ALEX)
    assert r.json()["access"] == {"tickets": "write"}
    assert client.put(f"/users/{anna['id']}/access/users", json={"level": "admin"},
                      headers=ANNA).status_code == 403
    assert client.delete(f"/users/{anna['id']}/access/tickets", headers=ALEX).json()["access"] == {}


def test_changes_need_an_actor(client):
    assert client.post("/users", json={"name": "Bob"}).status_code == 401
    assert client.post("/users", json={"name": "Bob"}, headers=ALEX).status_code == 201
    assert client.post("/users", json={"name": "bob"}, headers=ALEX).status_code == 400
