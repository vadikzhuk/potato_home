import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import NetworkError

from bot import health
from bot.common import ApiError


def test_report(monkeypatch):
    monkeypatch.setattr(health, "last_check", {"at": None, "problems": []})
    assert health.report() == {"status": "ok", "detail": "starting"}

    health.last_check.update(at=time.monotonic(), problems=[])
    assert health.report() == {"status": "ok"}

    health.last_check.update(problems=["Telegram: timed out"])
    assert health.report() == {"status": "degraded", "detail": "Telegram: timed out"}

    health.last_check.update(at=time.monotonic() - 600, problems=[])
    assert health.report() == {"status": "degraded", "detail": "self-check hasn't run for 10 min"}


async def test_self_check_collects_problems(monkeypatch):
    monkeypatch.setattr(health, "last_check", {"at": None, "problems": []})
    monkeypatch.setattr(health.users_api, "call", AsyncMock(return_value={"status": "ok"}))
    monkeypatch.setattr(health.estate_api, "call", AsyncMock(return_value={"status": "ok"}))
    monkeypatch.setattr(health.tickets_api, "call",
                        AsyncMock(side_effect=ApiError("The tickets service is not reachable (ConnectError).", 503)))
    context = SimpleNamespace(bot=SimpleNamespace(get_me=AsyncMock(side_effect=NetworkError("timed out"))))

    await health.self_check(context)
    assert health.last_check["problems"] == [
        "Telegram: timed out", "The tickets service is not reachable (ConnectError)."]


async def test_endpoint_answers_with_the_report(monkeypatch):
    monkeypatch.setattr(health, "last_check", {"at": time.monotonic(), "problems": []})
    server = await asyncio.start_server(health._answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    response = await reader.read()
    server.close()
    assert response.startswith(b"HTTP/1.1 200 OK")
    assert json.loads(response.split(b"\r\n\r\n", 1)[1]) == {"status": "ok"}
