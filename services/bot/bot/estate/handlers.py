"""/estate... commands and listing buttons.

The estate service decides who may do what (read, write or admin access);
its "no" is shown to the person by @known_user.
"""

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from ..access import known_user
from ..common import HTML, ApiError, reply
from . import digest, texts
from .client import api

SERVICE = "estate"
HELP = texts.HELP
COMMANDS = [  # for Telegram's command menu
    ("estate", "Homes in Italy: menu, or /estate 12 to show one"),
    ("estate_top", "Best listings now"),
    ("estate_auctions", "Best court auctions now"),
    ("estate_starred", "Listings I'm watching"),
]


async def show_list(update: Update, me: dict, kind: str) -> None:
    """kind: top, auctions or starred"""
    if kind == "starred":
        listings = await api.starred(me["telegram_id"])
    else:
        listings = await api.top(me["telegram_id"], 10, auctions=True if kind == "auctions" else None)
    await reply(update, texts.listing_list(texts.LIST_TITLES[kind], listings),
                reply_markup=texts.list_buttons(listings), link_preview_options=texts.NO_PREVIEW)


async def send_listing(update: Update, me: dict, listing_id: int) -> None:
    """The listing card, under its photo when it has one."""
    listing = await api.listing(me["telegram_id"], listing_id)
    buttons = texts.listing_buttons(listing)
    if listing["photo"]:
        try:
            await update.effective_message.reply_photo(listing["photo"], caption=texts.listing_card(listing),
                                                       parse_mode=HTML, reply_markup=buttons)
            return
        except BadRequest:
            pass  # Telegram couldn't load the photo: send the text alone
    await reply(update, texts.listing_card(listing, limit=4000), reply_markup=buttons,
                link_preview_options=texts.NO_PREVIEW)


# --- Commands -----------------------------------------------------------------

@known_user
async def estate(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """/estate 12 shows a listing; /estate alone shows a small menu."""
    if not context.args:
        await reply(update, "<b>Homes in Italy</b>", reply_markup=texts.menu_buttons())
        return
    if not context.args[0].lstrip("#").isdigit():
        raise ApiError("Which listing? For example: /estate 12", 400)
    await send_listing(update, me, int(context.args[0].lstrip("#")))


@known_user
async def estate_top(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    await show_list(update, me, "top")


@known_user
async def estate_auctions(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    await show_list(update, me, "auctions")


@known_user
async def estate_starred(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    await show_list(update, me, "starred")


@known_user
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """Handles every "estate:..." button; see texts.py for the format."""
    query = update.callback_query
    _, action, target, *rest = query.data.split(":")

    if action == "list":
        await query.answer()
        await show_list(update, me, target)
        return
    listing_id = int(target)
    if action == "show":
        await query.answer()
        await send_listing(update, me, listing_id)
        return

    on = rest[0] == "1"
    flag = {"star": "starred", "hide": "hidden"}[action]
    listing = await api.update(me["telegram_id"], listing_id, **{flag: on})
    # Redraw the card where it is: as a photo caption, or as a text message
    try:
        if query.message.photo:
            await query.edit_message_caption(texts.listing_card(listing), parse_mode=HTML,
                                             reply_markup=texts.listing_buttons(listing))
        else:
            await query.edit_message_text(texts.listing_card(listing, limit=4000), parse_mode=HTML,
                                          reply_markup=texts.listing_buttons(listing),
                                          link_preview_options=texts.NO_PREVIEW)
    except BadRequest as error:
        if "not modified" not in str(error):
            raise
    await query.answer({("starred", True): "⭐ Starred: price drops come in the daily digest",
                        ("starred", False): "Unstarred",
                        ("hidden", True): "🙈 Hidden: it won't be shown again",
                        ("hidden", False): "It's back in the lists"}[flag, on])


def schedule(app: Application) -> None:
    digest.schedule(app)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("estate", estate))
    app.add_handler(CommandHandler("estate_top", estate_top))
    app.add_handler(CommandHandler("estate_auctions", estate_auctions))
    app.add_handler(CommandHandler("estate_starred", estate_starred))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^estate:"))
