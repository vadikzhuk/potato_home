"""Who may talk to the bot, and where.

  * private_chats_only runs before everything else: no groups or channels.
  * @known_user wraps every handler: it looks the person up in the users
    service and passes them on as `me`. Strangers get their Telegram id
    (so an admin can add them) and are logged.

What a known person may do is checked by the service they use; its "no"
(an ApiError) is shown to them as a message.
"""

import functools
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes, ConversationHandler

from .common import ApiError, esc, reply
from .users.client import api as users_api

log = logging.getLogger(__name__)


async def private_chats_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs before every other handler: the bot only works in one-to-one chats.

    In a group, the answers (ticket lists!) would be visible to everyone there,
    so if someone adds the bot to a group or channel it leaves right away.
    """
    chat = update.effective_chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return
    log.warning("Leaving %s chat %s (%r)", chat.type, chat.id, chat.title)
    try:
        await context.bot.leave_chat(chat.id)
    except TelegramError:
        pass  # already left
    raise ApplicationHandlerStop  # no other handler sees this update


def unknown_user_text(telegram_id: int) -> str:
    return (
        "Hi! I don't know you yet.\n\n"
        f"Your Telegram id is <code>{telegram_id}</code>.\n"
        "Send it to an admin, so they can add you."
    )


def log_stranger(update: Update) -> None:
    """Note who tried the bot without being a user: see it with `docker compose logs bot`."""
    who = update.effective_user
    if update.callback_query:
        what = f"button {update.callback_query.data!r}"
    else:
        what = repr((update.effective_message.text or "")[:100])
    username = f"@{who.username}" if who.username else "-"
    log.warning("Stranger: id=%s username=%s name=%r sent %s", who.id, username, who.full_name, what)


def known_user(handler):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            me = await users_api.whoami(update.effective_user.id)
            if me is None:
                log_stranger(update)
                await reply(update, unknown_user_text(update.effective_user.id))
                return ConversationHandler.END
            if not me["is_active"]:
                log.warning("Deactivated user %s tried the bot", me["name"])
                await reply(update, "Your user is deactivated. Ask an admin to activate you.")
                return ConversationHandler.END
            return await handler(update, context, me)
        except ApiError as error:
            if update.callback_query:
                await update.callback_query.answer(str(error), show_alert=True)
            else:
                await reply(update, f"⚠️ {esc(error)}")
            # Returning None keeps a dialog (like /ticket_new) at the same step, so the user can try again
    return wrapper
