"""The `estate` command reads the database itself, but sends every change to the service."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from estate import api, cli, core, db, fetcher, service

from helpers import criteria, family, listing

runner = CliRunner()


@pytest.fixture
def estate(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTATE_DB", str(tmp_path / "estate.db"))
    monkeypatch.setenv("API_TOKEN", "secret")
    monkeypatch.setattr(fetcher, "daily", lambda stop: None)
    monkeypatch.setattr(cli.criteria, "load", lambda: criteria())
    api.app.dependency_overrides[api.get_people] = family
    api.app.dependency_overrides[api.get_criteria] = lambda: criteria()
    monkeypatch.setattr(service, "http", lambda: TestClient(api.app, headers={"X-Api-Token": "secret"}))
    conn = db.connect()
    core.save_listing(conn, listing())
    conn.close()

    def run(*args):
        result = runner.invoke(cli.app, list(args))
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result.output
    yield run
    api.app.dependency_overrides.clear()


def test_star_and_hide_go_through_the_service(estate):
    assert "starred on" in estate("star", "1")
    assert "Asti" in estate("starred")
    assert "hidden on" in estate("hide", "1")
    assert "Nothing matches" in estate("top")
    with pytest.raises(core.NotFound):
        estate("star", "99")


def test_fetch_asks_the_service_and_waits(estate, monkeypatch):
    def fake_start(settings, sources):  # the service fetches in no time
        conn = db.connect()
        core.finish_run(conn, core.start_run(conn), 5, 2, [])
    monkeypatch.setattr(fetcher, "start", fake_start)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert "Done: 5 listings, 2 new." in estate("fetch", "--source", "pvp")


def test_the_terminal_cannot_write_the_database(tmp_path):
    conn = db.connect(str(tmp_path / "estate.db"), read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        core.save_listing(conn, listing())
