"""What the bot says about your bots: message texts and buttons. No Telegram or HTTP calls here.

Button presses come back as "callback data" strings starting with "bots:":
  bots:list                  every bot's status
  bots:usage:quiz_bot:7      how quiz_bot was used in the last 7 days
"""

from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..common import esc, local_time

MESSAGE_LIMIT = 4096
BAR_WIDTH = 10
WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

HELP = """<b>Bots</b> (your other Telegram bots)
/bots - how each bot is doing: running, memory, uptime, errors, usage today
/bots name - how one bot was used in the last 7 days
Admins get a message when a bot stops, gets stuck, crashes or is fine again."""


def number(value, suffix: str = "") -> str:
    return "?" if value is None else f"{value:g}{suffix}"


def bot_title(bot: dict) -> str:
    name = f"<b>{esc(bot['bot'])}</b>"
    return name + (f" @{esc(bot['username'])}" if bot["username"] and bot["username"] != bot["bot"] else "")


def bot_status(bot: dict) -> str:
    """🟢 quiz @quiz_bot
    running since 01.11 21:30 · 48 MB of 256 · CPU 0.3%
    up 100% today · 99.8% this week · 0 errors today
    today: 12 updates, 3 users"""
    lines = [("🔴 " if bot["problems"] else "🟢 ") + bot_title(bot)]
    if bot["state"] == "running":
        memory = f"{number(bot['memory_mb'])} MB" + (
            f" of {number(bot['memory_limit_mb'])}" if bot["memory_limit_mb"] else "")
        lines.append(f"running since {local_time(bot['started_at'])} · {memory} · CPU {number(bot['cpu_percent'], '%')}")
    lines.append(f"up {number(bot['uptime_day'], '%')} last 24 h · {number(bot['uptime_week'], '%')} last 7 days"
                 f" · {bot['errors_today']} errors today")
    if bot["today"] and bot["today"]["updates"]:
        lines.append(f"today: {bot['today']['updates']} updates, {bot['today']['users']} users")
    lines += [f"• {esc(problem)}" for problem in bot["problems"]]
    if bot["last_error"]:
        lines.append(f"last error ({local_time(bot['last_error_at'])}): <code>{esc(bot['last_error'][:200])}</code>")
    return "\n".join(lines)


def status_message(bots: list[dict]) -> str:
    if not bots:
        return ("<b>Your bots</b>\n\nNo bots yet. A bot is watched when its container has the "
                "potato.bot label: see bots/compose.yml.")
    checked = local_time(max(b["at"] for b in bots))
    text = "<b>Your bots</b>\n\n" + "\n\n".join(bot_status(b) for b in bots) + f"\n\n<i>checked {checked}</i>"
    return text[:MESSAGE_LIMIT]


def status_buttons(bots: list[dict]) -> InlineKeyboardMarkup | None:
    if not bots:
        return None
    rows = [[InlineKeyboardButton(f"📊 {b['bot']}", callback_data=f"bots:usage:{b['bot']}:7")] for b in bots]
    return InlineKeyboardMarkup(rows + [[InlineKeyboardButton("🔄 Refresh", callback_data="bots:list")]])


def day_label(iso_day: str) -> str:
    day = date.fromisoformat(iso_day)
    return f"{WEEKDAYS[day.weekday()]} {day:%d.%m}"


def usage_message(usage: dict, days: int) -> str:
    title = f"<b>📊 {esc(usage['bot'])}</b>" + (f" @{esc(usage['username'])}" if usage["username"] else "")
    total = usage["total"]
    if not total["updates"]:
        return (f"{title}, last {days} days\n\nNothing counted. Does the bot call track(app) "
                "from botstats.py? See bots/README.md.")
    lines = [f"{title}, last {days} days", "",
             f"{total['updates']} updates from {total['users']} users ({total['new_users']} new)",
             f"failed: {total['failed']} · answers in {number(total['avg_ms'])} ms on average"]
    if usage["blocked"]:
        lines.append(f"blocked the bot: {usage['blocked']}")
    # One line per day with a bar, at most the last 14 days (a message is narrow)
    shown = usage["days"][-14:]
    most = max(d["updates"] for d in shown) or 1
    bars = [f"{day_label(d['date'])} {'█' * round(d['updates'] / most * BAR_WIDTH):<{BAR_WIDTH}} "
            f"{d['updates']:>4} · {d['users']} users" for d in shown]
    lines += ["", "<pre>" + "\n".join(bars) + "</pre>"]
    if usage["commands"]:
        lines.append("Commands: " + ", ".join(f"{esc(name)} {count}" for name, count in usage["commands"]))
    if usage["other"]:
        lines.append("Other: " + ", ".join(f"{esc(name)} {count}" for name, count in usage["other"]))
    return "\n".join(lines)[:MESSAGE_LIMIT]


def usage_buttons(name: str, days: int) -> InlineKeyboardMarkup:
    other = 30 if days == 7 else 7
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{other} days", callback_data=f"bots:usage:{name}:{other}"),
        InlineKeyboardButton("⬅ All bots", callback_data="bots:list"),
    ]])


def alerts_message(alerts: list[dict]) -> str:
    """Several alerts in one message, oldest first."""
    parts, length = [], 0
    for i, alert in enumerate(alerts):
        part = f"{esc(alert['text'])}\n<i>{local_time(alert['at'])}</i>"
        if length + len(part) > MESSAGE_LIMIT - 100:
            parts.append(f"… and {len(alerts) - i} more: <code>botwatch alerts</code> on the server")
            break
        parts.append(part)
        length += len(part) + 2
    return "\n\n".join(parts)
