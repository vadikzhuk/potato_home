from bot import state
from bot.tickets import notifications


def person(id, name, telegram_id, tickets=None):
    return {"id": id, "name": name, "telegram_id": telegram_id, "is_active": True,
            "access": {"tickets": tickets} if tickets else {}}


ALEX = person(1, "Alex", 111, "admin")
ANNA = person(2, "Anna", 222, "write")
BOB = person(3, "Bob", None, "write")      # no Telegram
CARL = person(4, "Carl", 444)              # no access to tickets


def event(action, new_value, actor="Alex"):
    return {"id": 1, "ticket_id": 7, "action": action, "new_value": new_value, "actor_name": actor}


def test_assignments_notify_only_new_assignees_who_can_see_tickets():
    events = [
        event("created", "Fix tap"),
        event("assignee", "Anna"),                     # notify Anna
        event("assignee", "Alex", actor="Alex"),   # took it himself: no message
        event("assignee", "Bob"),                      # no Telegram
        event("assignee", "Carl"),                     # can't see tickets
        event("assignee", None),                       # unassigned
        event("status", "done"),
    ]
    targets = notifications.assignments(events, [ALEX, ANNA, BOB, CARL])
    assert [(user["name"], e["new_value"]) for user, e in targets] == [("Anna", "Anna")]


def ticket(id, assignee_id, overdue=False, due_today=False):
    return {"id": id, "assignee_id": assignee_id, "overdue": overdue, "due_today": due_today}


def test_morning_lists():
    summary = {"tickets": [
        ticket(1, 2, overdue=True),
        ticket(2, 2, due_today=True),
        ticket(3, 2),                  # due later: not in the morning message
        ticket(4, None, overdue=True),
        ticket(5, None, due_today=True),
    ]}
    mine, unassigned = notifications.morning_lists(summary, ANNA)
    assert [t["id"] for t in mine] == [1, 2] and unassigned == []
    mine, unassigned = notifications.morning_lists(summary, ALEX)   # tickets admin
    assert mine == [] and [t["id"] for t in unassigned] == [4]


def test_state_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_STATE", str(tmp_path / "bot" / "state.json"))
    assert state.load("last_event_id") is None
    state.save("last_event_id", 42)
    state.save("estate_last_run", 3)  # another key doesn't overwrite the first
    assert (state.load("last_event_id"), state.load("estate_last_run")) == (42, 3)


def test_old_state_file_still_works(tmp_path, monkeypatch):
    file = tmp_path / "state.json"
    file.write_text('{"last_event_id": 7}')  # written by the bot before state.py existed
    monkeypatch.setenv("BOT_STATE", str(file))
    assert state.load("last_event_id") == 7
