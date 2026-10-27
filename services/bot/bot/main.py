"""Starts the Telegram bot. It asks Telegram for new messages (long polling),
so it needs no public address or open ports."""

import logging
import os

from telegram import Update
from telegram.ext import Application, TypeHandler

from . import general, health
from .access import private_chats_only


async def on_start(app: Application) -> None:
    commands = general.COMMANDS + [c for service in general.SERVICES for c in service.COMMANDS]
    await app.bot.set_my_commands(commands)
    for service in general.SERVICES:
        if hasattr(service, "schedule"):
            service.schedule(app)
    await health.start(app)


def build(token: str) -> Application:
    app = Application.builder().token(token).post_init(on_start).build()
    app.add_handler(TypeHandler(Update, private_chats_only), group=-1)  # group -1 runs first
    general.register(app)
    for service in general.SERVICES:
        service.register(app)
    return app


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise every poll is logged
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # and every scheduled job run

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_TOKEN is empty. Get one from @BotFather and put it into .env")
    build(token).run_polling()


if __name__ == "__main__":
    main()
