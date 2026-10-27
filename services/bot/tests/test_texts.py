from datetime import date

from bot.tickets import texts as tickets
from bot.users import texts as users

TODAY = date(2026, 10, 27)


def ticket(**overrides):
    t = {"id": 12, "title": "Fix tap", "description": "", "status": "open", "creator_id": 1,
         "creator_name": "Alex", "assignee_id": 2, "assignee_name": "Anna", "due_date": None,
         "created_at": "2026-10-27T10:03:00+00:00", "resolved_at": None}
    return {**t, **overrides}


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_due_label():
    assert tickets.due_label("2026-10-25", TODAY) == "🔴 2 days late"
    assert tickets.due_label("2026-10-27", TODAY) == "🟠 today"
    assert tickets.due_label("2026-10-28", TODAY) == "tomorrow"
    assert tickets.due_label("2026-11-20", TODAY) == "20 Nov"


def test_ticket_line_escapes_html():
    line = tickets.ticket_line(ticket(title="<b>tap</b> & sink", due_date="2026-10-28"), TODAY)
    assert line == "⚪ <b>#12</b> &lt;b&gt;tap&lt;/b&gt; &amp; sink · Anna · tomorrow"


def test_ticket_details_shows_history_in_local_time():
    data = {"ticket": ticket(), "history": [
        {"at": "2026-10-27T10:03:00+00:00", "actor_name": "Alex", "action": "created",
         "old_value": None, "new_value": "Fix tap"},
        {"at": "2026-10-27T10:05:00+00:00", "actor_name": "Anna", "action": "assignee",
         "old_value": None, "new_value": "Anna"},
    ]}
    text = tickets.ticket_details(data)
    assert "27.10 12:03 Alex: created Fix tap" in text      # Riga is UTC+2 after summer time ends
    assert "27.10 12:05 Anna: assignee - → Anna" in text


def test_all_ticket_buttons_are_prefixed_for_routing():
    assert callbacks(tickets.ticket_buttons(ticket())) == [
        "ticket:status:12:in_progress", "ticket:status:12:done", "ticket:status:12:cancelled",
        "ticket:assign:12", "ticket:show:12"]
    assert callbacks(tickets.ticket_buttons(ticket(status="done")))[0] == "ticket:status:12:open"
    assert callbacks(tickets.assign_buttons(12, [{"id": 3, "name": "Anna"}])) == [
        "ticket:assignto:12:3", "ticket:assignto:12:0", "ticket:show:12"]
    assert callbacks(tickets.menu_buttons()) == ["ticket:list:my", "ticket:list:all"]
    assert all(len(c.encode()) <= 64 for c in callbacks(tickets.list_buttons([ticket(id=99999)])))


def test_user_texts():
    assert users.access_text({"tickets": "write", "users": "read"}) == "tickets: write, users: read"
    assert users.access_text({}) == "no access"
    line = users.user_line({"name": "<Anna>", "telegram_id": None, "is_active": False, "access": {}})
    assert line == "— <b>&lt;Anna&gt;</b> <i>(inactive)</i>: no access"
