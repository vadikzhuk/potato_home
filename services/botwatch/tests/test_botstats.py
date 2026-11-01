"""bots/botstats.py: the helper copied into each bot."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from telegram import Update

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bots"))
import botstats  # noqa: E402


def update(**fields) -> Update:
    user = {"id": 7, "is_bot": False, "first_name": "Anna"}
    chat = {"id": 7, "type": "private"}
    data = {"update_id": 1}
    if "text" in fields or "voice" in fields:
        message = {"message_id": 1, "date": 0, "chat": chat, "from": user}
        if "text" in fields:
            message["text"] = fields["text"]
        else:
            message["voice"] = {"file_id": "f", "file_unique_id": "u", "duration": 3}
        data["message"] = message
    elif "button" in fields:
        data["callback_query"] = {"id": "1", "from": user, "chat_instance": "c", "data": fields["button"]}
    elif "blocked" in fields:
        data["my_chat_member"] = {"chat": chat, "from": user, "date": 0,
                                  "old_chat_member": {"status": "member", "user": user},
                                  "new_chat_member": {"status": "kicked", "user": user, "until_date": 0}}
    return Update.de_json(data, None)


def test_describe():
    assert botstats.describe(update(text="/Challenge@digital_gland_bot now")) == ("command", "/challenge")
    assert botstats.describe(update(text="hello")) == ("message", "text")
    assert botstats.describe(update(voice=True)) == ("message", "voice")
    assert botstats.describe(update(button="next")) == ("button", None)
    assert botstats.describe(update(blocked=True)) == ("member", "kicked")
    record = botstats.record(update(text="/start"), 0.1234, ok=False)
    assert record | {"at": None} == {"at": None, "kind": "command", "name": "/start", "user": 7,
                                     "chat": "private", "ms": 123, "ok": False}


class FakeApp:
    """What track() uses of a python-telegram-bot Application."""

    def __init__(self, fail: bool):
        self.fail = fail
        self.error_handlers = []
        self.bot = type("Bot", (), {"username": "quiz_bot"})()

    async def process_update(self, update):
        if self.fail:  # like python-telegram-bot: the handler's error goes to the error handlers
            context = type("Context", (), {"error": ValueError("boom")})()
            for handler in self.error_handlers:
                await handler(update, context)

    def add_error_handler(self, handler):
        self.error_handlers.append(handler)


@pytest.fixture
def botwatch(monkeypatch):
    """A tiny botwatch that remembers what it got; .status sets its answer."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        status = 200

        def do_POST(self):
            received.append((self.headers["X-Usage-Token"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(Handler.status)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(botstats, "_send_forever", lambda url, token: None)  # tests call send() themselves
    monkeypatch.setattr(botstats.atexit, "register", lambda *args: None)
    botstats._waiting.clear()
    yield f"http://127.0.0.1:{server.server_port}", received, Handler
    server.shutdown()


async def test_track_and_send(botwatch, monkeypatch):
    url, received, server = botwatch
    monkeypatch.setenv("BOTWATCH_URL", url)
    monkeypatch.setenv("USAGE_TOKEN", "usage")
    app = FakeApp(fail=True)
    botstats.track(app)
    await app.process_update(update(text="/start"))
    await app.process_update("not an update")  # e.g. an error python-telegram-bot passes around: not counted

    server.status = 503  # botwatch is restarting: the records wait
    botstats.send(url, "usage")
    assert len(botstats._waiting) == 1
    server.status = 200
    botstats.send(url, "usage")
    assert not botstats._waiting
    token, body = received[-1]
    assert token == "usage" and body["username"] == "quiz_bot"
    assert [(e["kind"], e["name"], e["ok"]) for e in body["events"]] == [("command", "/start", False)]


async def test_without_botwatch_url_nothing_changes(monkeypatch):
    monkeypatch.delenv("BOTWATCH_URL", raising=False)
    app = FakeApp(fail=False)
    original = app.process_update
    botstats.track(app)
    assert app.process_update == original and app.error_handlers == []
