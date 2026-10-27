import pytest
from fastapi.testclient import TestClient

from fake_people import family
from tickets import api

ALEX = {"X-Telegram-Id": "111"}
ANNA = {"X-Telegram-Id": "222"}
KID = {"X-Telegram-Id": "333"}
BOB = {"X-Telegram-Id": "444"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETS_DB", str(tmp_path / "tickets.db"))
    monkeypatch.setenv("API_TOKEN", "secret")
    api.app.dependency_overrides[api.get_people] = family
    with TestClient(api.app, headers={"X-Api-Token": "secret"}) as c:
        yield c
    api.app.dependency_overrides.clear()


def test_token_is_required(client):
    assert client.get("/health", headers={"X-Api-Token": ""}).status_code == 200
    assert client.get("/tickets", headers={"X-Api-Token": "wrong"}).status_code == 401


def test_reading_needs_read_access_services_may_always_read(client):
    assert client.get("/tickets").status_code == 200          # a service (the screen)
    assert client.get("/tickets", headers=KID).status_code == 200
    assert client.get("/tickets", headers=BOB).status_code == 403
    assert client.get("/summary", headers=BOB).status_code == 403
    assert client.get("/tickets", headers={"X-Telegram-Id": "999"}).status_code == 401


def test_ticket_lifecycle(client):
    r = client.post("/tickets", json={"title": "Fix tap", "due_date": "tomorrow", "assignee_id": 2},
                    headers=ALEX)
    assert r.status_code == 201 and r.json()["assignee_name"] == "Anna"
    ticket_id = r.json()["id"]

    assert client.patch(f"/tickets/{ticket_id}", json={"status": "done"}, headers=ANNA).json()["status"] == "done"
    assert client.get("/tickets").json() == []
    assert len(client.get("/tickets", params={"status": "all"}).json()) == 1

    history = client.get(f"/tickets/{ticket_id}").json()["history"]
    assert [e["action"] for e in history] == ["created", "assignee", "status"]
    events = client.get("/events", params={"after_id": history[0]["id"]}).json()
    assert [e["action"] for e in events] == ["assignee", "status"]


def test_errors_map_to_status_codes(client):
    assert client.post("/tickets", json={"title": "x"}).status_code == 401           # no actor
    assert client.post("/tickets", json={"title": "x"}, headers=KID).status_code == 403
    assert client.get("/tickets/99").status_code == 404
    assert client.post("/tickets", json={"title": "x", "due_date": "someday"}, headers=ALEX).status_code == 400


def test_patch_with_null_clears_assignee(client):
    t = client.post("/tickets", json={"title": "x", "assignee_id": 1}, headers=ALEX).json()
    assert client.patch(f"/tickets/{t['id']}", json={"assignee_id": None}, headers=ALEX).json()["assignee_name"] is None


def test_users_service_down_is_503_and_health_degraded(client):
    from tickets.people import People, Unavailable

    assert client.get("/health").json() == {"status": "ok"}

    def down():
        raise Unavailable("Users service is not reachable (ConnectError).")

    api.app.dependency_overrides[api.get_people] = lambda: People(load=down)
    r = client.post("/tickets", json={"title": "x"}, headers=ALEX)
    assert r.status_code == 503 and "not reachable" in r.json()["detail"]
    assert client.get("/health").json() == {"status": "degraded",
                                            "detail": "Users service is not reachable (ConnectError)."}
