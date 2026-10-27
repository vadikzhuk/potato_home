"""/ticket... commands, the /ticket_new dialog and ticket buttons.

The tickets service decides who may do what (read, write or admin access);
its "no" is shown to the person by @known_user.
"""

from telegram import ReplyKeyboardRemove, Update
from telegram.error import BadRequest
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)

from ..access import known_user
from ..common import HTML, ApiError, has_level, reply
from ..users.client import api as users_api
from . import notifications, texts
from .client import api

SERVICE = "tickets"
HELP = texts.HELP
COMMANDS = [  # for Telegram's command menu
    ("ticket", "Tickets menu, or /ticket 12 to show one"),
    ("ticket_my", "My active tickets"),
    ("ticket_all", "All active tickets"),
    ("ticket_new", "Create a ticket"),
]


async def assignable_users() -> list[dict]:
    """People who can get tickets: active, with write access to tickets."""
    return [u for u in await users_api.users() if has_level(u, SERVICE, "write")]


async def show_list(update: Update, me: dict, mine: bool) -> None:
    tickets = await api.tickets(me["telegram_id"], assignee_id=me["id"] if mine else None)
    title = "My tickets" if mine else "Active tickets"
    await reply(update, texts.ticket_list(title, tickets), reply_markup=texts.list_buttons(tickets))


async def send_ticket(update: Update, me: dict, ticket_id: int) -> None:
    data = await api.ticket(me["telegram_id"], ticket_id)
    await reply(update, texts.ticket_details(data), reply_markup=texts.ticket_buttons(data["ticket"]))


# --- Commands -----------------------------------------------------------------

@known_user
async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """/ticket 12 shows a ticket; /ticket alone shows a small menu."""
    if not context.args:
        await reply(update, "<b>Tickets</b>\nCreate one with /ticket_new", reply_markup=texts.menu_buttons())
        return
    if not context.args[0].lstrip("#").isdigit():
        raise ApiError("Which ticket? For example: /ticket 12", 400)
    await send_ticket(update, me, int(context.args[0].lstrip("#")))


@known_user
async def ticket_my(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    await show_list(update, me, mine=True)


@known_user
async def ticket_all(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    await show_list(update, me, mine=False)


@known_user
async def ticket_due(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    if len(context.args) < 2 or not context.args[0].lstrip("#").isdigit():
        raise ApiError("Usage: /ticket_due 12 tomorrow (or - to remove the date)", 400)
    ticket_id = int(context.args[0].lstrip("#"))
    due = None if context.args[1] in ("-", "none") else context.args[1]
    await api.update_ticket(me["telegram_id"], ticket_id, due_date=due)
    await send_ticket(update, me, ticket_id)


@known_user
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """Handles every "ticket:..." button; see texts.py for the format."""
    query = update.callback_query
    _, action, target, *rest = query.data.split(":")

    if action == "list":
        await query.answer()
        await show_list(update, me, mine=target == "my")
        return
    ticket_id = int(target)
    if action == "assign":
        await query.edit_message_reply_markup(texts.assign_buttons(ticket_id, await assignable_users()))
        await query.answer("Assign to whom?")
        return
    if action == "status":
        await api.update_ticket(me["telegram_id"], ticket_id, status=rest[0])
    elif action == "assignto":
        await api.update_ticket(me["telegram_id"], ticket_id, assignee_id=int(rest[0]) or None)

    data = await api.ticket(me["telegram_id"], ticket_id)
    try:
        await query.edit_message_text(texts.ticket_details(data), parse_mode=HTML,
                                      reply_markup=texts.ticket_buttons(data["ticket"]))
    except BadRequest as error:
        if "not modified" not in str(error):  # Refresh with nothing new is fine
            raise
    await query.answer()


# --- /ticket_new: a step-by-step dialog -------------------------------------------
# title -> description -> assignee -> due date -> created.
# The draft lives in context.user_data until the ticket is created.

TITLE, DESCRIPTION, ASSIGNEE, DUE = range(4)


@known_user
async def new_start(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    if not has_level(me, SERVICE, "write"):
        raise ApiError("You can't create tickets: you need write access to tickets.", 403)
    context.user_data["draft"] = {}
    await reply(update, "New ticket. What needs to be done? (/cancel to stop)")
    return TITLE


@known_user
async def new_title(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    context.user_data["draft"]["title"] = update.message.text
    await reply(update, "Any details? Write them, or /skip.")
    return DESCRIPTION


@known_user
async def new_description(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    is_skip = update.message.text.startswith("/skip")
    context.user_data["draft"]["description"] = "" if is_skip else update.message.text
    await reply(update, "Who should do it?", reply_markup=texts.assignee_keyboard(await assignable_users()))
    return ASSIGNEE


@known_user
async def new_assignee(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    name = update.message.text
    assignee = None if name == texts.NOBODY else await users_api.user_by_name(name)
    if assignee and not has_level(assignee, SERVICE, "write"):  # checked now, so they can pick again
        raise ApiError(f"{assignee['name']} can't get tickets (needs write access). Pick someone else.", 400)
    context.user_data["draft"]["assignee_id"] = assignee["id"] if assignee else None
    await reply(update, "When is it due? Pick one or write a date like 2026-11-05.",
                reply_markup=texts.due_keyboard())
    return DUE


@known_user
async def new_due(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    due = None if update.message.text == texts.NO_DATE else update.message.text
    draft = context.user_data["draft"]
    # A bad date or assignee makes the tickets service answer with an error: we stay at this step
    ticket = await api.create_ticket(me["telegram_id"], draft["title"], draft["description"],
                                     due, draft["assignee_id"])
    context.user_data.pop("draft", None)
    await reply(update, f"Created #{ticket['id']} ✅", reply_markup=ReplyKeyboardRemove())
    await send_ticket(update, me, ticket["id"])
    return ConversationHandler.END


async def new_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("draft", None)
    await reply(update, "Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# --- Wiring -------------------------------------------------------------------

def register(app: Application) -> None:
    text = filters.TEXT & ~filters.COMMAND
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("ticket_new", new_start)],
        states={
            TITLE: [MessageHandler(text, new_title)],
            DESCRIPTION: [MessageHandler(text, new_description), CommandHandler("skip", new_description)],
            ASSIGNEE: [MessageHandler(text, new_assignee)],
            DUE: [MessageHandler(text, new_due)],
        },
        fallbacks=[CommandHandler("cancel", new_cancel)],
    ))
    app.add_handler(CommandHandler("ticket", ticket))
    app.add_handler(CommandHandler("ticket_my", ticket_my))
    app.add_handler(CommandHandler("ticket_all", ticket_all))
    app.add_handler(CommandHandler("ticket_due", ticket_due))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^ticket:"))


def schedule(app: Application) -> None:
    notifications.schedule(app)
