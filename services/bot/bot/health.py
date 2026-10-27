"""A tiny health endpoint, so the info screen can show how the bot is doing:
GET http://bot:8000/health (inside Docker only, the port isn't published).

Every minute a self-check asks Telegram, the users and the tickets services
whether they answer, and remembers the problems it found. The endpoint reports:
  {"status": "ok"}
  {"status": "degraded", "detail": "what's wrong"}   e.g. Telegram unreachable,
                                                     or the self-check stopped running
"""

import asyncio
import json
import os
import time

from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from .common import ApiError
from .tickets.client import api as tickets_api
from .users.client import api as users_api

STALE_AFTER = 180  # seconds without a self-check before we call the bot stuck
last_check = {"at": None, "problems": []}
_server = None  # kept here so the server isn't garbage-collected


async def self_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    problems = []
    try:
        await context.bot.get_me()
    except TelegramError as error:
        problems.append(f"Telegram: {error}")
    for service in (users_api, tickets_api):
        try:
            await service.call("GET", "/health")
        except ApiError as error:
            problems.append(str(error))
    last_check.update(at=time.monotonic(), problems=problems)


def report() -> dict:
    if last_check["at"] is None:
        return {"status": "ok", "detail": "starting"}
    age = time.monotonic() - last_check["at"]
    if age > STALE_AFTER:
        return {"status": "degraded", "detail": f"self-check hasn't run for {int(age // 60)} min"}
    if last_check["problems"]:
        return {"status": "degraded", "detail": "; ".join(last_check["problems"])}
    return {"status": "ok"}


async def _answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Answers any request with the report: the smallest possible HTTP server."""
    await reader.read(1024)
    body = json.dumps(report()).encode()
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                 b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
    await writer.drain()
    writer.close()


async def start(app: Application) -> None:
    global _server
    app.job_queue.run_repeating(self_check, interval=60, first=1)
    _server = await asyncio.start_server(_answer, "0.0.0.0", int(os.environ.get("HEALTH_PORT", "8000")))
