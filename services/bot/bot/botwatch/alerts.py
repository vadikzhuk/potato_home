"""Alerts: when a bot stops, gets stuck, crashes or is fine again, botwatch notes it,
and everyone with admin access to botwatch gets it here.

Every minute the bot asks for alerts it hasn't sent yet; it remembers the last sent
one in state.json (see state.py). On the very first run it starts from the newest
alert, so nobody gets a pile of old ones.
"""

import logging

from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from .. import state
from ..common import HTML, ApiError, has_level
from ..users.client import api as users_api
from . import texts
from .client import api

log = logging.getLogger(__name__)
SERVICE = "botwatch"
STATE_KEY = "botwatch_last_alert"


def schedule(app: Application) -> None:
    app.job_queue.run_repeating(send_alerts, interval=60, first=20)


def recipients(users: list[dict]) -> list[dict]:
    return [u for u in users if u["telegram_id"] and has_level(u, SERVICE, "admin")]


async def send_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    last_sent = state.load(STATE_KEY)
    try:
        if last_sent is None:
            newest = await api.alerts(limit=1)
            state.save(STATE_KEY, newest[-1]["id"] if newest else 0)
            return
        alerts = await api.alerts(after=last_sent, limit=100)
        if not alerts:
            return
        users = await users_api.users()
    except ApiError as error:
        log.warning("Can't check for botwatch alerts: %s", error)  # try again in a minute
        return

    text = texts.alerts_message(alerts)
    for user in recipients(users):
        try:
            await context.bot.send_message(user["telegram_id"], text, parse_mode=HTML)
        except TelegramError as error:  # e.g. they never started the bot or blocked it
            log.warning("Can't send botwatch alerts to %s: %s", user["name"], error)
    state.save(STATE_KEY, alerts[-1]["id"])
