"""What the bot says about tickets: message texts and buttons. No Telegram or HTTP calls here.

Button presses come back to the bot as short "callback data" strings, all
starting with "ticket:" so the bot knows they belong here:
  ticket:show:12            show ticket 12
  ticket:status:12:done     set ticket 12 to done
  ticket:assign:12          show the "assign to whom?" buttons
  ticket:assignto:12:3      assign ticket 12 to user 3 (0 = nobody)
  ticket:list:my            my active tickets (or ticket:list:all)
"""

from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from ..common import esc, local_time, today

STATUS_ICONS = {"open": "⚪", "in_progress": "🟡", "done": "✅", "cancelled": "✖️"}
STATUS_NAMES = {"open": "open", "in_progress": "in progress", "done": "done", "cancelled": "cancelled"}
NOBODY = "nobody"
NO_DATE = "no date"

HELP = """<b>Tickets</b>
/ticket - menu: my or all tickets
/ticket 12 - show ticket #12 with buttons
/ticket_my - my active tickets
/ticket_all - all active tickets
/ticket_new - create a ticket step by step (/cancel to stop)
/ticket_due 12 tomorrow - due date: today, tomorrow, +3, 2026-11-05, or - to remove"""


def due_label(due_date: str | None, today_: date) -> str:
    if not due_date:
        return ""
    days = (date.fromisoformat(due_date) - today_).days
    if days < 0:
        return f"🔴 {-days} day{'s' if days < -1 else ''} late"
    if days == 0:
        return "🟠 today"
    if days == 1:
        return "tomorrow"
    if days < 7:
        return f"in {days} days"
    return date.fromisoformat(due_date).strftime("%-d %b")


def ticket_line(t: dict, today_: date) -> str:
    """⚪ #12 Fix tap · Anna · tomorrow"""
    parts = [f"{STATUS_ICONS[t['status']]} <b>#{t['id']}</b> {esc(t['title'])}"]
    if t["assignee_name"]:
        parts.append(esc(t["assignee_name"]))
    if t["status"] in ("open", "in_progress") and t["due_date"]:
        parts.append(due_label(t["due_date"], today_))
    return " · ".join(parts)


def ticket_list(title: str, tickets: list[dict]) -> str:
    if not tickets:
        return f"<b>{esc(title)}</b>\n\nNothing here. 🎉"
    today_ = today()
    return f"<b>{esc(title)}</b> ({len(tickets)})\n\n" + "\n".join(ticket_line(t, today_) for t in tickets)


def list_buttons(tickets: list[dict]) -> InlineKeyboardMarkup | None:
    """One button per ticket (up to 20) that opens it."""
    rows = [[InlineKeyboardButton(f"#{t['id']} {t['title'][:40]}", callback_data=f"ticket:show:{t['id']}")]
            for t in tickets[:20]]
    return InlineKeyboardMarkup(rows) if rows else None


def menu_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("My tickets", callback_data="ticket:list:my"),
                                  InlineKeyboardButton("All tickets", callback_data="ticket:list:all")]])


def ticket_details(data: dict) -> str:
    """Full ticket card with the last changes from its history."""
    t = data["ticket"]
    lines = [
        f"<b>#{t['id']} {esc(t['title'])}</b>",
        f"{STATUS_ICONS[t['status']]} {STATUS_NAMES[t['status']]}",
    ]
    if t["description"]:
        lines += ["", esc(t["description"])]
    lines.append("")
    lines.append(f"👤 {esc(t['assignee_name'] or NOBODY)}")
    if t["due_date"]:
        label = due_label(t["due_date"], today()) if t["status"] in ("open", "in_progress") else ""
        lines.append(f"📅 {t['due_date']}" + (f" ({label})" if label else ""))
    lines.append(f"Created {local_time(t['created_at'])} by {esc(t['creator_name'] or '?')}")
    if t["resolved_at"]:
        lines.append(f"Resolved {local_time(t['resolved_at'])}")

    history = data["history"][-8:]
    if history:
        lines += ["", "<i>History</i>"]
        for e in history:
            change = esc(e["new_value"]) if e["action"] == "created" else \
                f"{esc(e['old_value'] or '-')} → {esc(e['new_value'] or '-')}"
            lines.append(f"{local_time(e['at'])} {esc(e['actor_name'] or '?')}: {e['action']} {change}")
    return "\n".join(lines)


def ticket_buttons(t: dict) -> InlineKeyboardMarkup:
    tid = t["id"]
    status = t["status"]
    if status == "open":
        row = [("▶️ Start", "in_progress"), ("✅ Done", "done"), ("✖️ Cancel", "cancelled")]
    elif status == "in_progress":
        row = [("⏸ Pause", "open"), ("✅ Done", "done"), ("✖️ Cancel", "cancelled")]
    else:
        row = [("↩️ Reopen", "open")]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"ticket:status:{tid}:{new}") for label, new in row],
        [InlineKeyboardButton("👤 Assign", callback_data=f"ticket:assign:{tid}"),
         InlineKeyboardButton("🔄 Refresh", callback_data=f"ticket:show:{tid}")],
    ])


def assign_buttons(ticket_id: int, users: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(u["name"], callback_data=f"ticket:assignto:{ticket_id}:{u['id']}")]
            for u in users]
    rows.append([InlineKeyboardButton("Nobody", callback_data=f"ticket:assignto:{ticket_id}:0"),
                 InlineKeyboardButton("« Back", callback_data=f"ticket:show:{ticket_id}")])
    return InlineKeyboardMarkup(rows)


# --- /ticket_new dialog keyboards (buttons that type the answer for you) -------------

def assignee_keyboard(users: list[dict]) -> ReplyKeyboardMarkup:
    names = [u["name"] for u in users] + [NOBODY]
    rows = [names[i:i + 3] for i in range(0, len(names), 3)]
    return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)


def due_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["today", "tomorrow"], ["+3", "+7"], [NO_DATE]],
                               one_time_keyboard=True, resize_keyboard=True)


# --- Notifications ------------------------------------------------------------

def assigned_message(actor_name: str | None, ticket: dict) -> str:
    lines = [f"👤 {esc(actor_name or 'Someone')} assigned you a ticket", "",
             f"<b>#{ticket['id']} {esc(ticket['title'])}</b>"]
    if ticket["due_date"]:
        lines.append(f"📅 {ticket['due_date']} ({due_label(ticket['due_date'], today())})")
    return "\n".join(lines)


def open_button(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Open #{ticket_id}", callback_data=f"ticket:show:{ticket_id}")]])


def morning_message(mine: list[dict], unassigned: list[dict]) -> str:
    today_ = today()
    lines = ["☀️ <b>Good morning!</b>"]
    if mine:
        lines += ["", "<b>Your tickets due today or late</b>"] + [ticket_line(t, today_) for t in mine]
    if unassigned:
        lines += ["", "<b>Late and nobody assigned</b>"] + [ticket_line(t, today_) for t in unassigned]
    return "\n".join(lines)
