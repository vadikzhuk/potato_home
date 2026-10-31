"""Terminal interface. Run `tickets --help` to see all commands.

Reading opens the database directly (read-only). Changes are sent to the running
tickets service (see service.py), so the service is the only program writing it.
By default you act as the first tickets admin; use `--as NAME` to act as someone else.
People are managed in the users service (the `users` command).
"""

import sqlite3

import typer
from rich.console import Console
from rich.table import Table

from . import core, db, service
from .people import People, Person, Unavailable

app = typer.Typer(help="Home ticket tracker.", no_args_is_help=True)
console = Console()

STATUS_COLORS = {"open": "cyan", "in_progress": "yellow", "done": "green", "cancelled": "dim"}

# Filled in by main() before any command runs
conn: sqlite3.Connection
people: People
actor: Person | None


@app.callback()
def main(as_user: str = typer.Option(None, "--as", envvar="TICKETS_AS",
                                     help="Act as this user (default: the first tickets admin).")):
    global conn, people, actor
    conn = db.connect(read_only=True)
    people = People.from_service()
    if as_user:
        actor = person_named(as_user)
    else:
        actor = next((p for p in people.all() if p.can("admin")), None)


def run():
    """Entry point of the `tickets` command: shows errors as short red messages."""
    try:
        app()
    except (core.TicketsError, Unavailable) as error:
        console.print(f"[red]{error}[/red]")
        raise SystemExit(1)


def person_named(name: str) -> Person:
    person = people.by_name(name)
    if person is None:
        raise core.NotFound(f"User {name!r} not found.")
    return person


# --- Tickets ------------------------------------------------------------------

@app.command("list")
def list_tickets(
    all_: bool = typer.Option(False, "--all", "-a", help="Include done and cancelled tickets."),
    mine: bool = typer.Option(False, "--mine", "-m", help="Only tickets assigned to me."),
    assignee: str = typer.Option(None, help="Only tickets assigned to this user."),
):
    """Show tickets (active ones by default)."""
    core.require(actor, "read")
    assignee_id = None
    if mine:
        assignee_id = actor.id
    elif assignee:
        assignee_id = person_named(assignee).id
    tickets = core.list_tickets(conn, None if all_ else core.ACTIVE_STATUSES, assignee_id)

    today = core.today().isoformat()
    table = Table("#", "Status", "Title", "Assignee", "Due", "Created by")
    for t in tickets:
        late = t.due_date and t.due_date < today and t.status in core.ACTIVE_STATUSES
        table.add_row(
            str(t.id),
            f"[{STATUS_COLORS[t.status]}]{t.status}[/]",
            t.title,
            people.name(t.assignee_id) or "-",
            f"[red]{t.due_date}[/]" if late else (t.due_date or "-"),
            people.name(t.creator_id) or "?",
        )
    console.print(table if tickets else "No tickets.")


@app.command()
def show(ticket_id: int):
    """Show one ticket with its full history."""
    core.require(actor, "read")
    t = core.get_ticket(conn, ticket_id)
    console.print(f"[bold]#{t.id} {t.title}[/bold]  [{STATUS_COLORS[t.status]}]{t.status}[/]")
    if t.description:
        console.print(t.description)
    console.print(f"Assignee: {people.name(t.assignee_id) or '-'}   Due: {t.due_date or '-'}")
    console.print(f"Created:  {core.local_time(t.created_at)} by {people.name(t.creator_id)}"
                  + (f"   Resolved: {core.local_time(t.resolved_at)}" if t.resolved_at else ""))

    table = Table("When", "Who", "What", "From", "To", title="History")
    for e in core.history(conn, people, ticket_id):
        table.add_row(core.local_time(e["at"]), e["actor_name"] or "-", e["action"],
                      e["old_value"] or "", e["new_value"] or "")
    console.print(table)


@app.command()
def new(
    title: str,
    description: str = typer.Option("", "--description", "-d"),
    due: str = typer.Option(None, help="YYYY-MM-DD, today, tomorrow or +N days."),
    assign: str = typer.Option(None, help="Name of the user to assign."),
):
    """Create a ticket."""
    body = {"title": title, "description": description, "due_date": due,
            "assignee_id": person_named(assign).id if assign else None}
    t = service.call("POST", "/tickets", actor, json=body)
    console.print(f"Created [bold]#{t['id']}[/bold] {t['title']}")


@app.command()
def edit(
    ticket_id: int,
    title: str = typer.Option(None),
    description: str = typer.Option(None, "--description", "-d"),
    due: str = typer.Option(None, help="YYYY-MM-DD, today, tomorrow or +N days."),
    no_due: bool = typer.Option(False, "--no-due", help="Remove the due date."),
):
    """Change title, description or due date."""
    changes = {"title": title, "description": description, "due_date": due}
    changes = {field: value for field, value in changes.items() if value is not None}
    if no_due:
        changes["due_date"] = None
    t = service.call("PATCH", f"/tickets/{ticket_id}", actor, json=changes)
    console.print(f"Updated #{t['id']} {t['title']}")


@app.command()
def assign(ticket_id: int, user: str):
    """Assign (or reassign) a ticket to a user."""
    assignee = person_named(user)
    service.call("PATCH", f"/tickets/{ticket_id}", actor, json={"assignee_id": assignee.id})
    console.print(f"#{ticket_id} is now assigned to {assignee.name}")


@app.command()
def unassign(ticket_id: int):
    """Remove the assignee from a ticket."""
    service.call("PATCH", f"/tickets/{ticket_id}", actor, json={"assignee_id": None})
    console.print(f"#{ticket_id} is unassigned")


def _set_status(ticket_id: int, status: str) -> None:
    t = service.call("PATCH", f"/tickets/{ticket_id}", actor, json={"status": status})
    console.print(f"#{t['id']} {t['title']}: [{STATUS_COLORS[status]}]{status}[/]")


@app.command()
def start(ticket_id: int):
    """Mark a ticket as in progress."""
    _set_status(ticket_id, "in_progress")


@app.command()
def done(ticket_id: int):
    """Mark a ticket as done."""
    _set_status(ticket_id, "done")


@app.command()
def cancel(ticket_id: int):
    """Cancel a ticket (this is how tickets are removed; history stays)."""
    _set_status(ticket_id, "cancelled")


@app.command()
def reopen(ticket_id: int):
    """Open a done or cancelled ticket again."""
    _set_status(ticket_id, "open")
