"""The `users` command reads the database itself, but sends every change to the service."""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from users import api, cli, core, db, service

runner = CliRunner()


@pytest.fixture
def users(tmp_path, monkeypatch):
    monkeypatch.setenv("USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("USERS_SEED", str(tmp_path / "users.yaml"))
    monkeypatch.setenv("API_TOKEN", "secret")
    (tmp_path / "users.yaml").write_text("users:\n- name: Alex\n  access: {users: admin}\n")
    # The "service" is the API itself, without a network in between
    monkeypatch.setattr(service, "http", lambda: TestClient(api.app, headers={"X-Api-Token": "secret"}))
    with TestClient(api.app):
        pass  # the service starts first and creates the users from users.yaml, as in Docker

    def run(*args):
        result = runner.invoke(cli.app, list(args))
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result.output
    return run


def test_changes_go_through_the_service(users):
    users("list")  # first contact: nothing written by the terminal
    assert "Added Anna" in users("add", "Anna", "--telegram-id", "222")
    assert "tickets: write" in users("grant", "Anna", "tickets", "write")
    assert "Updated Anna Maria" in users("edit", "Anna", "--name", "Anna Maria")
    assert "deactivated" in users("deactivate", "Anna Maria")
    output = users("list", "--all")
    assert "Anna Maria" in output and "222" in output and "no" in output


def test_import_through_the_service(users, tmp_path):
    file = tmp_path / "family.yaml"
    file.write_text("users:\n- name: Kid\n  access: {tickets: read}\n")
    assert "added Kid" in users("import", str(file))
    assert "Nothing to change." in users("import", str(file))


def test_refusals_come_back_as_messages(users):
    users("add", "Anna")
    with pytest.raises(core.Forbidden, match="Only users admins"):
        users("--as", "Anna", "add", "Bob")


def test_the_terminal_cannot_write_the_database(tmp_path):
    conn = db.connect(str(tmp_path / "users.db"), read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        core.add_user(conn, None, "Alex")


def test_a_stopped_service_is_explained(users, monkeypatch):
    def refuse():
        raise httpx.ConnectError("refused")
    users("list")
    monkeypatch.setattr(service, "http", refuse)
    with pytest.raises(core.UsersError, match="doesn't answer.*docker compose up -d users"):
        users("add", "Anna")
