"""Counts how a Telegram bot is used and sends it to potato_home's botwatch service.

Copy this one file into a bot built with python-telegram-bot (version 20 or newer), then:

    from botstats import track

    app = ApplicationBuilder().token(TOKEN).build()
    track(app)

Every update the bot gets (a message, a command, a button press...) becomes one small
record: when, what kind, which command, who (Telegram user id), how long the bot took,
and whether it failed. Records are sent in one batch a minute, so the bot is never
slowed down. While botwatch is down they wait in memory (up to 10 000) for the next try.

It needs BOTWATCH_URL and USAGE_TOKEN in the environment; bots/compose.yml in
potato_home sets both. Without BOTWATCH_URL it does nothing, so the bot still runs
anywhere else (your laptop, Railway) exactly as before.

Note: track() adds an error handler that logs errors (python-telegram-bot only logs them
itself while a bot has no error handler), and marks the update as failed.

Only the standard library and python-telegram-bot are used.
"""

import atexit
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone

from telegram import Update

log = logging.getLogger("botstats")

SEND_EVERY = 60  # seconds
BATCH = 1000  # records per request at most
KEEP_AT_MOST = 10_000  # waiting records; the oldest are dropped beyond this

_waiting: deque = deque(maxlen=KEEP_AT_MOST)
_bot = {"username": None}
_send_lock = threading.Lock()


def track(app) -> None:
    """Start counting the updates `app` handles."""
    url = os.environ.get("BOTWATCH_URL")
    if not url:
        return
    original = app.process_update
    failed: set[int] = set()

    async def process_update(update):
        started = time.monotonic()
        try:
            await original(update)
        finally:
            if isinstance(update, Update):
                _bot["username"] = app.bot.username
                _waiting.append(record(update, time.monotonic() - started, update.update_id not in failed))
                failed.discard(update.update_id)

    async def on_error(update, context):
        if isinstance(update, Update):
            failed.add(update.update_id)
        log.error("Error while handling an update", exc_info=context.error)

    app.process_update = process_update
    app.add_error_handler(on_error)
    token = os.environ.get("USAGE_TOKEN", "")
    threading.Thread(target=_send_forever, args=(url, token), daemon=True, name="botstats").start()
    atexit.register(send, url, token)  # what's left when the bot stops


def record(update: Update, seconds: float, ok: bool) -> dict:
    kind, name = describe(update)
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "name": name,
        "user": update.effective_user.id if update.effective_user else None,
        "chat": update.effective_chat.type if update.effective_chat else None,
        "ms": round(seconds * 1000),
        "ok": ok,
    }


def describe(update: Update) -> tuple[str, str | None]:
    """What the update is: ("command", "/start"), ("message", "voice"), ("button", None)..."""
    if update.callback_query:
        return "button", None
    if update.inline_query:
        return "inline", None
    if update.my_chat_member:  # in a private chat: "kicked" = blocked the bot, "member" = (re)started it
        return "member", update.my_chat_member.new_chat_member.status
    message = update.message or update.edited_message
    if message is None:
        return "other", None
    text = message.text or ""
    if text.startswith("/"):
        return "command", text.split()[0].split("@")[0].lower()[:64]
    for content in ("text", "voice", "audio", "video_note", "video", "photo", "document", "sticker"):
        if getattr(message, content):
            return "message", content
    return "message", "other"


def send(url: str, token: str) -> None:
    """Send what's waiting. When botwatch doesn't answer, the records wait for the next try."""
    with _send_lock:
        while _waiting:
            batch = [_waiting.popleft() for _ in range(min(BATCH, len(_waiting)))]
            body = json.dumps({"username": _bot["username"], "events": batch}).encode()
            request = urllib.request.Request(
                url.rstrip("/") + "/usage", data=body, method="POST",
                headers={"Content-Type": "application/json", "X-Usage-Token": token},
            )
            try:
                urllib.request.urlopen(request, timeout=10).close()
            except urllib.error.HTTPError as error:
                if error.code < 500:  # botwatch refuses these records: sending them again won't help
                    log.warning("botwatch refused %d usage records: HTTP %s", len(batch), error.code)
                    continue
                _waiting.extendleft(reversed(batch))
                return
            except OSError:  # botwatch is down or restarting
                _waiting.extendleft(reversed(batch))
                return


def _send_forever(url: str, token: str) -> None:
    while True:
        time.sleep(SEND_EVERY)
        try:
            send(url, token)
        except Exception:  # never let counting stop for good
            log.exception("Can't send usage to botwatch")
