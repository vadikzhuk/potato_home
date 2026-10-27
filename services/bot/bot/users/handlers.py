"""/user_... commands. The users service decides who may do what (users admin for changes)."""

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ..access import known_user
from ..common import ApiError, reply
from . import texts
from .client import api

SERVICE = "users"
HELP = texts.HELP
COMMANDS = [("user_list", "Users and their access")]  # for Telegram's command menu


async def _find(name_words: list[str], usage: str) -> dict:
    """Names may have several words: /user_grant Anna Maria tickets write"""
    if not name_words:
        raise ApiError(f"Usage: {usage}", 400)
    return await api.user_by_name(" ".join(name_words))


@known_user
async def user_list(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    users = await api.users(me["telegram_id"], include_inactive=True)
    await reply(update, texts.user_list(users))


@known_user
async def user_add(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """/user_add Anna Maria 123456789: the Telegram id is optional."""
    words = [w for w in context.args if not w.isdigit()]
    ids = [int(w) for w in context.args if w.isdigit()]
    if not words:
        raise ApiError("Usage: /user_add Name [telegram_id]", 400)
    user = await api.add_user(me["telegram_id"], " ".join(words), ids[0] if ids else None)
    await reply(update, f"Added {texts.user_line(user)}\n\n"
                        f"Give access, for example: /user_grant {user['name']} tickets write")


@known_user
async def user_link(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    *name, telegram_id = context.args or [""]
    if not telegram_id.isdigit():
        raise ApiError("Usage: /user_link Name telegram_id", 400)
    user = await _find(name, "/user_link Name telegram_id")
    user = await api.update_user(me["telegram_id"], user["id"], telegram_id=int(telegram_id))
    await reply(update, texts.user_line(user))


@known_user
async def user_grant(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    usage = "/user_grant Name service read|write|admin"
    if len(context.args) < 3:
        raise ApiError(f"Usage: {usage}", 400)
    *name, service, level = context.args
    user = await _find(name, usage)
    user = await api.grant(me["telegram_id"], user["id"], service.lower(), level.lower())
    await reply(update, texts.user_line(user))


@known_user
async def user_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    usage = "/user_revoke Name service"
    if len(context.args) < 2:
        raise ApiError(f"Usage: {usage}", 400)
    *name, service = context.args
    user = await _find(name, usage)
    user = await api.revoke(me["telegram_id"], user["id"], service.lower())
    await reply(update, texts.user_line(user))


@known_user
async def user_deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    user = await _find(context.args, "/user_deactivate Name")
    user = await api.update_user(me["telegram_id"], user["id"], is_active=False)
    await reply(update, texts.user_line(user))


@known_user
async def user_activate(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    user = await _find(context.args, "/user_activate Name")
    user = await api.update_user(me["telegram_id"], user["id"], is_active=True)
    await reply(update, texts.user_line(user))


def register(app: Application) -> None:
    app.add_handler(CommandHandler("user_list", user_list))
    app.add_handler(CommandHandler("user_add", user_add))
    app.add_handler(CommandHandler("user_link", user_link))
    app.add_handler(CommandHandler("user_grant", user_grant))
    app.add_handler(CommandHandler("user_revoke", user_revoke))
    app.add_handler(CommandHandler("user_deactivate", user_deactivate))
    app.add_handler(CommandHandler("user_activate", user_activate))
