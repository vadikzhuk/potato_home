import pytest

from fake_people import family, make_people, user
from tickets import core, db


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def people():
    return family()


@pytest.fixture
def alex(people):
    return people.get(1)


@pytest.fixture
def anna(people):
    return people.get(2)


def test_access_levels(conn, people, alex, anna):
    kid, bob = people.get(3), people.get(4)
    core.require(kid, "read")
    with pytest.raises(core.Forbidden):
        core.create_ticket(conn, people, kid, "Kid can only read")
    with pytest.raises(core.Forbidden):
        core.require(bob, "read")
    assert core.create_ticket(conn, people, anna, "Anna can write").creator_id == anna.id


def test_create_assign_and_history(conn, people, alex, anna):
    t = core.create_ticket(conn, people, alex, "Fix tap", due_date="2026-11-05", assignee_id=anna.id)
    assert core.named(t, people)["assignee_name"] == "Anna"

    core.update_ticket(conn, people, anna, t.id, assignee_id=alex.id)
    events = core.history(conn, people, t.id)
    assert [(e["action"], e["old_value"], e["new_value"]) for e in events] == [
        ("created", None, "Fix tap"),
        ("assignee", None, "Anna"),
        ("assignee", "Anna", "Alex"),
    ]
    assert events[-1]["actor_name"] == "Anna"


def test_only_writers_can_get_tickets(conn, people, alex):
    for reader_or_inactive in (3, 5):  # Kid can only read, Old is inactive
        with pytest.raises(core.Invalid):
            core.create_ticket(conn, people, alex, "x", assignee_id=reader_or_inactive)
    with pytest.raises(core.NotFound):
        core.create_ticket(conn, people, alex, "x", assignee_id=99)


def test_writers_change_own_or_assigned_admins_any(conn, people, alex, anna):
    t = core.create_ticket(conn, people, alex, "Admin's ticket")
    with pytest.raises(core.Forbidden):
        core.update_ticket(conn, people, anna, t.id, status="done")
    core.update_ticket(conn, people, alex, t.id, assignee_id=anna.id)
    assert core.update_ticket(conn, people, anna, t.id, status="done").status == "done"

    annas = core.create_ticket(conn, people, anna, "Anna's ticket")
    assert core.update_ticket(conn, people, alex, annas.id, title="Admin may").title == "Admin may"


def test_done_sets_resolved_at_and_reopen_clears_it(conn, people, alex):
    t = core.create_ticket(conn, people, alex, "Buy milk")
    assert core.update_ticket(conn, people, alex, t.id, status="done").resolved_at
    assert core.update_ticket(conn, people, alex, t.id, status="open").resolved_at is None


def test_unchanged_fields_are_not_logged(conn, people, alex):
    t = core.create_ticket(conn, people, alex, "Buy milk")
    core.update_ticket(conn, people, alex, t.id, title="Buy milk")
    assert len(core.history(conn, people, t.id)) == 1


def test_list_and_summary_order_by_due_date(conn, people, alex, monkeypatch):
    monkeypatch.setattr(core, "today", lambda: core.date(2026, 10, 27))
    core.create_ticket(conn, people, alex, "no date")
    core.create_ticket(conn, people, alex, "later", due_date="2026-11-30")
    core.create_ticket(conn, people, alex, "late", due_date="2026-10-01")
    core.create_ticket(conn, people, alex, "today", due_date="today")
    done = core.create_ticket(conn, people, alex, "finished")
    core.update_ticket(conn, people, alex, done.id, status="done")

    s = core.summary(conn, people)
    assert [t["title"] for t in s["tickets"]] == ["late", "today", "later", "no date"]
    assert s["counts"] == {"open": 4, "in_progress": 0, "overdue": 1}
    assert s["tickets"][1]["due_today"] and s["tickets"][0]["creator_name"] == "Alex"
    assert len(core.list_tickets(conn, statuses=None)) == 5


def test_events_after(conn, people, alex, anna):
    t = core.create_ticket(conn, people, alex, "Fix tap", assignee_id=anna.id)
    core.update_ticket(conn, people, anna, t.id, status="done")
    events = core.events_after(conn, people, 0)
    assert [(e["action"], e["new_value"]) for e in events] == [
        ("created", "Fix tap"), ("assignee", "Anna"), ("status", "done")]
    assert events[2]["actor_name"] == "Anna" and events[2]["ticket_title"] == "Fix tap"
    assert core.events_after(conn, people, events[-1]["id"]) == []


def test_people_reload_when_someone_is_unknown():
    users = [user(1, "Alex", "admin")]
    people = make_people()
    people._load = lambda: users  # the users service's answer changes over time
    assert people.get(1).name == "Alex"
    users.append(user(2, "Anna", "write"))
    assert people.get(2).name == "Anna"  # not in the cached list yet: asked again


def test_parse_due(monkeypatch):
    monkeypatch.setattr(core, "today", lambda: core.date(2026, 10, 27))
    assert core.parse_due("tomorrow") == "2026-10-28"
    assert core.parse_due("+7") == "2026-11-03"
    assert core.parse_due("2026-12-24") == "2026-12-24"
    assert core.parse_due("") is None
    with pytest.raises(core.Invalid):
        core.parse_due("next week")
