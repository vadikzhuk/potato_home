"""/bots and botwatch alerts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import state
from bot.botwatch import alerts, texts


def bot(**fields):
    data = {"bot": "quiz", "username": "quiz_bot", "at": "2026-11-01T12:00:00+00:00", "state": "running",
            "started_at": "2026-11-01T10:00:00+00:00", "memory_mb": 48.2, "memory_limit_mb": 256.0,
            "cpu_percent": 0.3, "uptime_day": 100.0, "uptime_week": 99.5, "errors_today": 0,
            "problems": [], "last_error": None, "last_error_at": None,
            "today": {"updates": 12, "users": 3, "failed": 0, "avg_ms": 40}}
    data.update(fields)
    return data


def user(name, telegram_id, access):
    return {"name": name, "telegram_id": telegram_id, "is_active": True, "access": access}


def test_status_message():
    old = bot(bot="old", username=None, state="exited", problems=["not running"], today=None,
              last_error="ValueError: <bad>", last_error_at="2026-11-01T11:00:00+00:00")
    text = texts.status_message([bot(), old])
    assert "🟢 <b>quiz</b> @quiz_bot\nrunning since 01.11 12:00 · 48.2 MB of 256 · CPU 0.3%" in text
    assert "today: 12 updates, 3 users" in text
    assert "🔴 <b>old</b>\nup 100% last 24 h" in text and "• not running" in text
    assert "last error (01.11 13:00): <code>ValueError: &lt;bad&gt;</code>" in text  # escaped for Telegram's HTML
    buttons = texts.status_buttons([bot()]).inline_keyboard
    assert [b[0].callback_data for b in buttons] == ["bots:usage:quiz:7", "bots:list"]
    assert "No bots yet" in texts.status_message([])


def test_usage_message():
    usage = {"bot": "quiz", "username": "quiz_bot", "blocked": 1,
             "days": [{"date": "2026-10-31", "updates": 2, "users": 1}, {"date": "2026-11-01", "updates": 10, "users": 4}],
             "total": {"updates": 12, "users": 4, "new_users": 3, "failed": 1, "avg_ms": 120},
             "commands": [["/start", 5]], "other": [["message: voice", 7]]}
    text = texts.usage_message(usage, 7)
    assert "12 updates from 4 users (3 new)" in text and "blocked the bot: 1" in text
    assert "Sa 31.10 ██            2 · 1 users\nSu 01.11 ██████████   10 · 4 users" in text
    assert "Commands: /start 5" in text and "Other: message: voice 7" in text
    usage["total"]["updates"] = 0
    assert "Nothing counted" in texts.usage_message(usage, 7)
    assert texts.usage_buttons("quiz", 7).inline_keyboard[0][0].callback_data == "bots:usage:quiz:30"


def test_long_alert_lists_are_cut():
    many = [{"text": "🔴 quiz:\n• " + "x" * 200, "at": "2026-11-01T12:00:00+00:00"}] * 40
    text = texts.alerts_message(many)
    assert len(text) <= texts.MESSAGE_LIMIT and "more: <code>botwatch alerts</code>" in text


def test_alerts_go_to_botwatch_admins():
    users = [user("Alex", 111, {"botwatch": "admin"}), user("Kid", 333, {"botwatch": "read"}),
             user("Nobody", None, {"botwatch": "admin"})]
    assert [u["name"] for u in alerts.recipients(users)] == ["Alex"]


async def test_alerts_start_from_the_newest_then_send_new_ones(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(alerts.api, "alerts", AsyncMock(return_value=[{"id": 5, "text": "old", "at": "2026-11-01T12:00:00+00:00"}]))
    monkeypatch.setattr(alerts.users_api, "users", AsyncMock(return_value=[user("Alex", 111, {"botwatch": "admin"})]))
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await alerts.send_alerts(context)  # first run: nothing sent, bookmark at the newest
    assert state.load(alerts.STATE_KEY) == 5 and not context.bot.send_message.called

    alerts.api.alerts.return_value = [{"id": 6, "text": "🔴 quiz:\n• stuck", "at": "2026-11-01T12:01:00+00:00"}]
    await alerts.send_alerts(context)
    alerts.api.alerts.assert_called_with(after=5, limit=100)
    assert context.bot.send_message.call_args.args[0] == 111
    assert "🔴 quiz:\n• stuck" in context.bot.send_message.call_args.args[1]
    assert state.load(alerts.STATE_KEY) == 6
