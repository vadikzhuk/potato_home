"""Commands that belong to the bot itself, not to one service: /start and /help.

SERVICES lists every service the bot knows. Each one is a package with a
handlers module that has: SERVICE (its name), HELP, COMMANDS, register(app),
and optionally schedule(app) for background jobs. To add a service to the bot,
write such a package and add it here.
"""

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .access import known_user
from .common import esc, reply
from .estate import handlers as estate
from .tickets import handlers as tickets
from .users import handlers as users

SERVICES = [tickets, estate, users]
COMMANDS = [("help", "What I can do for you")]


@known_user
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, me: dict):
    """Shows help only for the services this person has access to."""
    sections = [s.HELP for s in SERVICES if s.SERVICE in me["access"]]
    if not sections:
        await reply(update, f"Hi, {esc(me['name'])}! You don't have access to anything yet. Ask an admin.")
        return
    await reply(update, f"Hi, {esc(me['name'])}!\n\n" + "\n\n".join(sections))


def register(app: Application) -> None:
    app.add_handler(CommandHandler(["start", "help"], help_command))
