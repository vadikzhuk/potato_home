import pytest
from fastapi.testclient import TestClient

from estate import api, core, db, fetcher

from helpers import criteria, family, listing

ALEX = {"X-Telegram-Id": "111"}
ANNA = {"X-Telegram-Id": "222"}
KID = {"X-Telegram-Id": "333"}
BOB = {"X-Telegram-Id": "444"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTATE_DB", str(tmp_path / "estate.db"))
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setattr(fetcher, "daily", lambda stop: None)  # no real fetching in tests
    api.app.dependency_overrides[api.get_people] = family
    api.app.dependency_overrides[api.get_criteria] = lambda: criteria()
    conn = db.connect()
    core.save_listing(conn, listing(price=18000.0))
    core.save_listing(conn, listing(price=25000.0, is_auction=True, auction_date="2099-01-01"))
    conn.close()
    with TestClient(api.app, headers={"X-Api-Token": "secret"}) as c:
        yield c
    api.app.dependency_overrides.clear()


def test_token_and_access(client):
    assert client.get("/health", headers={"X-Api-Token": ""}).status_code == 200
    assert client.get("/listings/top", headers={"X-Api-Token": "wrong"}).status_code == 401
    assert client.get("/listings/top").status_code == 200            # a service (the bot's digest)
    assert client.get("/listings/top", headers=KID).status_code == 200
    assert client.get("/listings/top", headers=BOB).status_code == 403


def test_top_and_auctions(client):
    assert [l["price"] for l in client.get("/listings/top").json()] == [18000, 25000]
    assert [l["price"] for l in client.get("/listings/top", params={"auctions": True}).json()] == [25000]
    assert [l["price"] for l in client.get("/listings/top", params={"auctions": False}).json()] == [18000]


def test_hide_and_star(client):
    listing_id = client.get("/listings/top").json()[0]["id"]
    assert client.patch(f"/listings/{listing_id}", json={"starred": True}, headers=KID).status_code == 403
    assert client.patch(f"/listings/{listing_id}", json={"starred": True}).status_code == 401  # who?
    assert client.patch(f"/listings/{listing_id}", json={"starred": True}, headers=ANNA).json()["starred"]
    assert [l["id"] for l in client.get("/listings/starred").json()] == [listing_id]
    client.patch(f"/listings/{listing_id}", json={"hidden": True}, headers=ANNA)
    assert listing_id not in [l["id"] for l in client.get("/listings/top").json()]
    assert client.get(f"/listings/{listing_id}").json()["why_not"] == "hidden"
    assert client.get("/listings/99999").status_code == 404


def test_fetch_by_hand_needs_admin(client, monkeypatch):
    monkeypatch.setattr(fetcher, "start", lambda settings: None)
    assert client.post("/runs", headers=ANNA).status_code == 403
    assert client.post("/runs", headers=ALEX).status_code == 202


def test_digest_before_any_fetch(client):
    assert client.get("/digest").json() == {"run": None, "new": [], "auctions": [], "price_drops": []}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "detail": "no fetch yet"}
