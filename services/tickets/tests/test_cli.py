"""The `tickets` command reads the database itself, but sends every change to the service."""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from fake_people import family
from tickets import api, cli, core, db, service

runner = CliRunner()


@pytest.fixture
def tk(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETS_DB", str(tmp_path / "tickets.db"))
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setattr(cli.People, "from_service", staticmethod(family))
    api.app.dependency_overrides[api.get_people] = family
    # The "service" is the API itself, without a network in between
    monkeypatch.setattr(service, "http", lambda: TestClient(api.app, headers={"X-Api-Token": "secret"}))
    with TestClient(api.app):
        pass  # the service starts first and creates the tables, as in Docker

    def run(*args):
        result = runner.invoke(cli.app, list(args))
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result.output
    yield run
    api.app.dependency_overrides.clear()


def test_changes_go_through_the_service(tk):
    assert "Created #1 Fix tap" in tk("new", "Fix tap", "--due", "tomorrow", "--assign", "anna")
    assert "in_progress" in tk("start", "1")
    assert "Updated #1 Fix kitchen tap" in tk("edit", "1", "--title", "Fix kitchen tap")
    assert "assigned to Alex" in tk("assign", "1", "alex")
    assert "unassigned" in tk("unassign", "1")
    assert "done" in tk("done", "1")
    history = tk("show", "1")
    assert "Fix kitchen tap" in history and "status" in history and "assignee" in history


def test_refusals_come_back_as_messages(tk):
    tk("new", "Fix tap")
    with pytest.raises(core.Forbidden):
        tk("--as", "kid", "done", "1")  # Kid may only read


def test_the_terminal_cannot_write_the_database(tmp_path):
    conn = db.connect(str(tmp_path / "tickets.db"), read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO tickets (title, status, creator_id, created_at) VALUES ('x', 'open', 1, 'now')")


def test_a_stopped_service_is_explained(tk, monkeypatch):
    def refuse():
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(service, "http", refuse)
    with pytest.raises(core.TicketsError, match="doesn't answer.*docker compose up -d tickets"):
        tk("new", "Fix tap")
