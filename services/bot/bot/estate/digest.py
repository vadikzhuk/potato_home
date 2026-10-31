"""The daily digest: when the estate service finishes its daily fetch, everyone
with estate access gets the best new listings, new auctions and price drops
of starred listings in one message.

Every 10 minutes the bot asks whether a fetch finished that it hasn't reported
yet; it remembers the last reported one in state.json (see state.py).
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
SERVICE = "estate"
STATE_KEY = "estate_last_run"


def schedule(app: Application) -> None:
    app.job_queue.run_repeating(check_digest, interval=600, first=30)


def recipients(users: list[dict]) -> list[dict]:
    return [u for u in users if u["telegram_id"] and has_level(u, SERVICE, "read")]


async def check_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    last_reported = state.load(STATE_KEY)
    try:
        finished = [run for run in await api.runs() if run["finished_at"]]
        if not finished or finished[0]["id"] == last_reported:
            return  # nothing new (or a fetch is still running)
        digest = await api.digest(after_run=last_reported)
        users = await users_api.users()
    except ApiError as error:
        log.warning("Can't check for a new estate digest: %s", error)  # try again in 10 minutes
        return

    text = texts.digest_message(digest)
    if text:
        for user in recipients(users):
            try:
                await context.bot.send_message(user["telegram_id"], text, parse_mode=HTML,
                                               reply_markup=texts.digest_buttons(digest),
                                               link_preview_options=texts.NO_PREVIEW)
            except TelegramError as error:  # e.g. they never started the bot or blocked it
                log.warning("Can't send the estate digest to %s: %s", user["name"], error)
    state.save(STATE_KEY, digest["run"]["id"])
