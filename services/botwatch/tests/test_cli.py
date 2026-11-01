import pytest
from typer.testing import CliRunner

from botwatch import cli, core, db

from helpers import SETTINGS, FakeDocker, FakeTelegram

runner = CliRunner()


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTWATCH_DB", str(tmp_path / "botwatch.db"))
    monkeypatch.setenv("COLUMNS", "200")


def test_before_any_check():
    assert "No bots checked yet" in runner.invoke(cli.app, ["status"]).output


def test_status_usage_alerts():
    conn = db.connect()
    telegram = FakeTelegram()
    telegram.webhook = "https://old.example/hook"
    core.check_all(conn, FakeDocker("quiz"), telegram, SETTINGS)
    core.save_events(conn, "quiz_bot", [{"at": core.utcnow(), "kind": "command", "name": "/start", "user": 1}])
    conn.close()

    status = runner.invoke(cli.app, ["status"]).output
    assert "quiz" in status and "@quiz_bot" in status and "a webhook is set" in status
    usage = runner.invoke(cli.app, ["usage", "@quiz_bot", "--days", "3"]).output
    assert "/start 1" in usage and "New users: 1" in usage
    assert "Watching a new bot" in runner.invoke(cli.app, ["alerts"]).output
    result = runner.invoke(cli.app, ["usage", "nobody"])
    assert isinstance(result.exception, core.NotFound)


def test_the_terminal_never_writes():
    conn = db.connect()
    conn.close()
    runner.invoke(cli.app, ["status"])
    with pytest.raises(Exception, match="readonly"):
        cli.conn.execute("DELETE FROM checks")
