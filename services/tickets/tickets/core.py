"""Business logic of the tickets service.

Every change to tickets goes through the functions in this file. The API and
the CLI only translate their input into calls here, so the rules (who may do
what, what gets recorded in history) live in one place.

People live in the users service. `people` (see people.py) tells who is who,
and `actor` is the person doing the action. Access levels for tickets:
  read  - see tickets
  write - create tickets; change tickets you created or are assigned to
  admin - change any ticket
"""

import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .people import People, Person

STATUSES = ("open", "in_progress", "done", "cancelled")
ACTIVE_STATUSES = ("open", "in_progress")
CLOSED_STATUSES = ("done", "cancelled")
TICKET_FIELDS = ("title", "description", "due_date", "assignee_id", "status")

LOCAL_TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Riga")


class TicketsError(Exception):
    """An error with a message meant for the person using the service."""


class NotFound(TicketsError):
    pass


class Forbidden(TicketsError):
    pass


class Invalid(TicketsError):
    pass


@dataclass
class Ticket:
    id: int
    title: str
    description: str
    status: str
    creator_id: int
    assignee_id: int | None
    due_date: str | None
    created_at: str
    resolved_at: str | None


# --- Time helpers -------------------------------------------------------------

def now() -> str:
    """Current UTC time as ISO text, e.g. '2026-10-27T09:15:00+00:00'."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> date:
    """Today's date at home (not in UTC)."""
    return datetime.now(LOCAL_TZ).date()


def local_time(iso: str | None) -> str:
    """'2026-10-27T09:15:00+00:00' -> '2026-10-27 11:15' in local time."""
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def parse_due(text: str | None) -> str | None:
    """Turn user input into a 'YYYY-MM-DD' due date.

    Accepts '2026-11-05', 'today', 'tomorrow', '+3' (days from today), or empty for no date.
    """
    if text is None or not text.strip():
        return None
    text = text.strip().lower()
    if text == "today":
        return today().isoformat()
    if text == "tomorrow":
        return (today() + timedelta(days=1)).isoformat()
    if text.startswith("+") and text[1:].isdigit():
        return (today() + timedelta(days=int(text[1:]))).isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise Invalid(f"Bad date {text!r}. Use YYYY-MM-DD, today, tomorrow or +N.") from None


# --- Access -------------------------------------------------------------------

def require(actor: Person | None, level: str) -> None:
    """Refuse unless the actor has at least `level` access to tickets."""
    if actor is None or not actor.is_active:
        raise Forbidden("Unknown or inactive user.")
    if not actor.can(level):
        raise Forbidden(f"{actor.name} has no {level} access to tickets.")


def _require_can_edit(actor: Person | None, ticket: Ticket) -> None:
    """Admins may change any ticket; writers only ones they created or are assigned to."""
    require(actor, "write")
    if not actor.can("admin") and actor.id not in (ticket.creator_id, ticket.assignee_id):
        raise Forbidden(f"You can only change tickets you created or are assigned to (#{ticket.id}).")


def _assignable(people: People, user_id: int) -> Person:
    person = people.get(user_id)
    if person is None:
        raise NotFound(f"User #{user_id} not found.")
    if not person.can("write"):
        raise Invalid(f"{person.name} can't get tickets: needs write access to tickets and to be active.")
    return person


# --- Reading ------------------------------------------------------------------

def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> Ticket:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise NotFound(f"Ticket #{ticket_id} not found.")
    return Ticket(**dict(row))


def list_tickets(conn: sqlite3.Connection, statuses: tuple | list | None = ACTIVE_STATUSES,
                 assignee_id: int | None = None) -> list[Ticket]:
    """Tickets with the given statuses (None = all), soonest due date first."""
    where, params = [], []
    if statuses:
        where.append(f"status IN ({', '.join('?' * len(statuses))})")
        params += statuses
    if assignee_id is not None:
        where.append("assignee_id = ?")
        params.append(assignee_id)
    sql = "SELECT * FROM tickets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY due_date IS NULL, due_date, id"  # tickets without a due date go last
    return [Ticket(**dict(row)) for row in conn.execute(sql, params)]


def named(ticket: Ticket, people: People) -> dict:
    """The ticket as a dict, with creator and assignee names added."""
    return {**asdict(ticket),
            "creator_name": people.name(ticket.creator_id),
            "assignee_name": people.name(ticket.assignee_id)}


def history(conn: sqlite3.Connection, people: People, ticket_id: int) -> list[dict]:
    get_ticket(conn, ticket_id)  # raises NotFound for unknown tickets
    rows = conn.execute("SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY id", (ticket_id,))
    return [{**dict(row), "actor_name": people.name(row["actor_id"])} for row in rows]


def events_after(conn: sqlite3.Connection, people: People, after_id: int, limit: int = 100) -> list[dict]:
    """Ticket changes newer than `after_id`, oldest first.

    Lets other services follow what happens, e.g. the bot notifies new assignees.
    They remember the last id they saw and ask for everything after it.
    """
    rows = conn.execute(
        "SELECT e.*, t.title AS ticket_title FROM ticket_events e"
        " JOIN tickets t ON t.id = e.ticket_id"
        " WHERE e.id > ? ORDER BY e.id LIMIT ?",
        (after_id, limit),
    )
    return [{**dict(row), "actor_name": people.name(row["actor_id"])} for row in rows]


def summary(conn: sqlite3.Connection, people: People) -> dict:
    """Active tickets for the info screen, most urgent first."""
    day = today().isoformat()
    tickets = [
        {**named(t, people), "overdue": bool(t.due_date and t.due_date < day), "due_today": t.due_date == day}
        for t in list_tickets(conn, ACTIVE_STATUSES)
    ]
    return {
        "generated_at": now(),
        "counts": {
            "open": sum(t["status"] == "open" for t in tickets),
            "in_progress": sum(t["status"] == "in_progress" for t in tickets),
            "overdue": sum(t["overdue"] for t in tickets),
        },
        "tickets": tickets,
    }


# --- Changing -----------------------------------------------------------------

def create_ticket(conn: sqlite3.Connection, people: People, actor: Person, title: str,
                  description: str = "", due_date: str | None = None,
                  assignee_id: int | None = None) -> Ticket:
    require(actor, "write")
    title = _clean_title(title)
    due_date = parse_due(due_date)
    assignee = _assignable(people, assignee_id) if assignee_id is not None else None

    with conn:  # commits at the end, or rolls back on error
        cur = conn.execute(
            "INSERT INTO tickets (title, description, creator_id, assignee_id, due_date, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (title, description or "", actor.id, assignee_id, due_date, now()),
        )
        _log(conn, cur.lastrowid, actor, "created", None, title)
        if assignee:
            _log(conn, cur.lastrowid, actor, "assignee", None, assignee.name)
    return get_ticket(conn, cur.lastrowid)


def update_ticket(conn: sqlite3.Connection, people: People, actor: Person, ticket_id: int,
                  **changes) -> Ticket:
    """Change some of: title, description, due_date, assignee_id, status.

    Pass None to clear due_date or assignee_id. Every real change is written to history.
    """
    unknown = set(changes) - set(TICKET_FIELDS)
    if unknown:
        raise Invalid(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    ticket = get_ticket(conn, ticket_id)
    _require_can_edit(actor, ticket)

    if "title" in changes:
        changes["title"] = _clean_title(changes["title"])
    if "description" in changes:
        changes["description"] = changes["description"] or ""
    if "due_date" in changes:
        changes["due_date"] = parse_due(changes["due_date"])
    if "status" in changes and changes["status"] not in STATUSES:
        raise Invalid(f"Status must be one of: {', '.join(STATUSES)}.")
    new_assignee = None
    if changes.get("assignee_id") is not None:
        new_assignee = _assignable(people, changes["assignee_id"])

    with conn:
        for field, new in changes.items():
            old = getattr(ticket, field)
            if old == new:
                continue
            # `field` is safe in the SQL: only names from TICKET_FIELDS get here
            conn.execute(f"UPDATE tickets SET {field} = ? WHERE id = ?", (new, ticket_id))
            if field == "assignee_id":
                _log(conn, ticket_id, actor, "assignee", people.name(old),
                     new_assignee.name if new_assignee else None)
            else:
                _log(conn, ticket_id, actor, field, old, new)
            if field == "status":
                resolved_at = now() if new in CLOSED_STATUSES else None
                conn.execute("UPDATE tickets SET resolved_at = ? WHERE id = ?", (resolved_at, ticket_id))
    return get_ticket(conn, ticket_id)


def _log(conn: sqlite3.Connection, ticket_id: int, actor: Person, action: str, old, new) -> None:
    conn.execute(
        "INSERT INTO ticket_events (ticket_id, actor_id, at, action, old_value, new_value)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (ticket_id, actor.id, now(), action,
         None if old is None else str(old), None if new is None else str(new)),
    )


def _clean_title(title: str | None) -> str:
    title = (title or "").strip()
    if not title:
        raise Invalid("Title can't be empty.")
    return title
