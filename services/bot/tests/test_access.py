import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from bot import access
from bot.tickets import handlers as tickets


def fake_update(chat_type="private", text="/ticket_all"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(type=chat_type, id=-100, title="Some group"),
        effective_user=SimpleNamespace(id=999, username="stranger", full_name="Mr Stranger"),
        effective_message=SimpleNamespace(text=text, reply_text=AsyncMock()),
        callback_query=None,
    )


async def test_private_chats_pass():
    context = SimpleNamespace(bot=SimpleNamespace(leave_chat=AsyncMock()))
    await access.private_chats_only(fake_update("private"), context)
    context.bot.leave_chat.assert_not_called()


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
async def test_bot_leaves_groups_and_answers_nothing(chat_type):
    context = SimpleNamespace(bot=SimpleNamespace(leave_chat=AsyncMock()))
    with pytest.raises(ApplicationHandlerStop):
        await access.private_chats_only(fake_update(chat_type), context)
    context.bot.leave_chat.assert_awaited_once_with(-100)


async def test_strangers_are_logged_and_get_no_data(monkeypatch, caplog):
    monkeypatch.setattr(access.users_api, "whoami", AsyncMock(return_value=None))
    monkeypatch.setattr(tickets.api, "tickets", AsyncMock())
    update = fake_update(text="/ticket_all")

    with caplog.at_level(logging.WARNING):
        await tickets.ticket_all(update, SimpleNamespace())

    tickets.api.tickets.assert_not_called()
    assert "Stranger: id=999 username=@stranger name='Mr Stranger' sent '/ticket_all'" in caplog.text
    assert "999" in update.effective_message.reply_text.call_args.args[0]
