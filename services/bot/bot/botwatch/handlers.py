"""/bots: how your other Telegram bots are doing, and how they are used.

Access ("botwatch" in the users service):
  read   see /bots
  admin  also get alerts (see alerts.py)
"""

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from ..access import known_user
from ..common import HTML, ApiError, has_level, reply
from . import alerts, texts
from .client import api

SERVICE = "botwatch"
HELP = texts.HELP
COMMANDS = [("bots", "My Telegram bots: how they are doing, or /bots name for usage")]


def require_access(me: dict) -> None:
    if not has_level(me, SERVICE, "read"):
        raise ApiError("You don't have access to the bots. Ask an admin.", 403)


@known_user
async def bots(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """/bots shows every bot; /bots quiz_bot shows how one was used."""
    require_access(me)
    if context.args:
        name = context.args[0].lstrip("@")
        await reply(update, texts.usage_message(await api.usage(name, 7), 7),
                    reply_markup=texts.usage_buttons(name, 7))
        return
    found = await api.bots()
    await reply(update, texts.status_message(found), reply_markup=texts.status_buttons(found))


@known_user
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """Handles every "bots:..." button; see texts.py for the format. Redraws the message in place."""
    require_access(me)
    query = update.callback_query
    _, action, *rest = query.data.split(":")
    if action == "usage":
        name, days = rest[0], int(rest[1])
        text, buttons = texts.usage_message(await api.usage(name, days), days), texts.usage_buttons(name, days)
    else:
        found = await api.bots()
        text, buttons = texts.status_message(found), texts.status_buttons(found)
    try:
        await query.edit_message_text(text, parse_mode=HTML, reply_markup=buttons)
    except BadRequest as error:
        if "not modified" not in str(error):  # pressing Refresh when nothing changed
            raise
    await query.answer()


def schedule(app: Application) -> None:
    alerts.schedule(app)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("bots", bots))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^bots:"))
