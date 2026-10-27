"""Ticket messages the bot sends on its own:

  * every minute: tell people when a ticket gets assigned to them
  * every morning: each person's tickets due today or late
    (tickets admins also get late tickets that nobody is assigned to)

To know what is new, the bot reads the tickets service's list of changes
(/events) and remembers the id of the last change it handled in a small JSON file.
"""

import json
import logging
import os
from datetime import time
from pathlib import Path

from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from ..common import HTML, LOCAL_TZ, ApiError, has_level
from ..users.client import api as users_api
from . import texts
from .client import api

log = logging.getLogger(__name__)
SERVICE = "tickets"
SERVICE_DIR = Path(__file__).resolve().parents[2]  # services/bot when run from the repo


def schedule(app: Application) -> None:
    """Start the jobs (python-telegram-bot's JobQueue runs them inside the bot)."""
    app.job_queue.run_repeating(check_new_events, interval=60, first=5)
    hour, minute = os.environ.get("MORNING_SUMMARY_TIME", "08:30").split(":")
    app.job_queue.run_daily(morning_summary, time=time(int(hour), int(minute), tzinfo=LOCAL_TZ))


def state_file() -> Path:
    """BOT_STATE from the environment, or potato_home/data/bot/state.json locally."""
    return Path(os.environ.get("BOT_STATE") or SERVICE_DIR.parent.parent / "data" / "bot" / "state.json")


def load_last_event_id() -> int | None:
    try:
        return json.loads(state_file().read_text())["last_event_id"]
    except (FileNotFoundError, KeyError, ValueError):
        return None


def save_last_event_id(event_id: int) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_event_id": event_id}))


# --- Assignments --------------------------------------------------------------

def assignments(events: list[dict], users: list[dict]) -> list[tuple[dict, dict]]:
    """(user, event) pairs for everyone who just got a ticket assigned.

    Skips people without Telegram or access to tickets, and people assigning themselves.
    """
    by_name = {u["name"].lower(): u for u in users}
    result = []
    for event in events:
        if event["action"] != "assignee" or not event["new_value"]:
            continue
        user = by_name.get(event["new_value"].lower())
        if user and user["telegram_id"] and has_level(user, SERVICE, "read") and user["name"] != event["actor_name"]:
            result.append((user, event))
    return result


async def check_new_events(context: ContextTypes.DEFAULT_TYPE) -> None:
    last_id = load_last_event_id()
    try:
        if last_id is None:
            # First start: skip everything that happened before the bot existed
            save_last_event_id(await _newest_event_id())
            return
        events = await api.events(after_id=last_id)
        if not events:
            return
        users = await users_api.users()
        for user, event in assignments(events, users):
            ticket = (await api.ticket(user["telegram_id"], event["ticket_id"]))["ticket"]
            await _send(context, user, texts.assigned_message(event["actor_name"], ticket),
                        texts.open_button(ticket["id"]))
    except ApiError as error:
        log.warning("Can't check for new events: %s", error)  # try again next minute
        return
    save_last_event_id(events[-1]["id"])


async def _newest_event_id() -> int:
    last_id = 0
    while events := await api.events(after_id=last_id, limit=500):
        last_id = events[-1]["id"]
    return last_id


# --- Morning summary ----------------------------------------------------------

def morning_lists(summary: dict, user: dict) -> tuple[list[dict], list[dict]]:
    """(this user's tickets due today or late, late tickets nobody has: tickets admins only)"""
    tickets = summary["tickets"]
    mine = [t for t in tickets if t["assignee_id"] == user["id"] and (t["overdue"] or t["due_today"])]
    unassigned = [t for t in tickets if t["assignee_id"] is None and t["overdue"]] \
        if has_level(user, SERVICE, "admin") else []
    return mine, unassigned


async def morning_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        summary = await api.summary()
        users = await users_api.users()
    except ApiError as error:
        log.warning("No morning summary today: %s", error)
        return
    for user in users:
        if not user["telegram_id"] or not has_level(user, SERVICE, "read"):
            continue
        mine, unassigned = morning_lists(summary, user)
        if mine or unassigned:  # nothing urgent: no message
            await _send(context, user, texts.morning_message(mine, unassigned),
                        texts.list_buttons(mine + unassigned))


async def _send(context: ContextTypes.DEFAULT_TYPE, user: dict, text: str, buttons) -> None:
    try:
        await context.bot.send_message(user["telegram_id"], text, parse_mode=HTML, reply_markup=buttons)
    except TelegramError as error:  # e.g. they never started the bot or blocked it
        log.warning("Can't message %s: %s", user["name"], error)
