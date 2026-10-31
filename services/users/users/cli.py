"""Terminal interface. Run `users --help` to see all commands.

Reading opens the database directly (read-only). Changes are sent to the running
users service (see service.py), so the service is the only program writing it.
By default you act as the first users admin; use `--as NAME` to act as someone else.
"""

import sqlite3
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import core, db
from . import service as users_service  # not just `service`: `grant` has an argument of that name

app = typer.Typer(help="Users and their access to home services.", no_args_is_help=True)
console = Console()

# Filled in by main() before any command runs
conn: sqlite3.Connection
actor: core.User | None


@app.callback()
def main(as_user: str = typer.Option(None, "--as", envvar="USERS_AS",
                                     help="Act as this user (default: the first users admin).")):
    global conn, actor
    conn = db.connect(read_only=True)  # users.yaml is applied by the service when it starts
    actor = core.get_user_by_name(conn, as_user) if as_user else core.first_admin(conn)


def run():
    """Entry point of the `users` command: shows core errors as short red messages."""
    try:
        app()
    except core.UsersError as error:
        console.print(f"[red]{error}[/red]")
        raise SystemExit(1)


def access_text(access: dict[str, str]) -> str:
    return ", ".join(f"{service}: {level}" for service, level in access.items()) or "-"


@app.command("list")
def list_users(all_: bool = typer.Option(False, "--all", "-a", help="Include inactive users.")):
    """Show users and their access."""
    table = Table("#", "Name", "Telegram id", "Active", "Access")
    for u in core.list_users(conn, include_inactive=all_):
        table.add_row(str(u.id), u.name, str(u.telegram_id or "-"), "yes" if u.is_active else "no",
                      access_text(u.access))
    console.print(table)


@app.command()
def add(name: str, telegram_id: int = typer.Option(None, help="Telegram user id, to use the bot.")):
    """Add a user (without access; use `grant` next)."""
    u = users_service.call("POST", "/users", actor, json={"name": name, "telegram_id": telegram_id})
    console.print(f"Added {u['name']}. Access: {access_text(u['access'])}")


@app.command()
def edit(name: str, new_name: str = typer.Option(None, "--name"),
         telegram_id: int = typer.Option(None)):
    """Rename a user or change their Telegram id."""
    user = core.get_user_by_name(conn, name)
    changes = {field: value for field, value in {"name": new_name, "telegram_id": telegram_id}.items()
               if value is not None}
    u = users_service.call("PATCH", f"/users/{user.id}", actor, json=changes)
    console.print(f"Updated {u['name']}")


@app.command()
def grant(name: str, service: str, level: str = typer.Argument(..., help="read, write or admin")):
    """Give a user access to a service, e.g. `users grant Anna tickets write`."""
    user = core.get_user_by_name(conn, name)
    u = users_service.call("PUT", f"/users/{user.id}/access/{service}", actor, json={"level": level})
    console.print(f"{u['name']}: {access_text(u['access'])}")


@app.command()
def revoke(name: str, service: str):
    """Take away a user's access to a service."""
    user = core.get_user_by_name(conn, name)
    u = users_service.call("DELETE", f"/users/{user.id}/access/{service}", actor)
    console.print(f"{u['name']}: {access_text(u['access'])}")


@app.command()
def deactivate(name: str):
    """Deactivate a user (they keep their history but can't use anything)."""
    user = core.get_user_by_name(conn, name)
    users_service.call("PATCH", f"/users/{user.id}", actor, json={"is_active": False})
    console.print(f"{user.name} is deactivated")


@app.command()
def activate(name: str):
    """Activate a user again."""
    user = core.get_user_by_name(conn, name)
    users_service.call("PATCH", f"/users/{user.id}", actor, json={"is_active": True})
    console.print(f"{user.name} is active")


@app.command("export")
def export_users(file: Path = typer.Argument(None, help="Default: users.yaml of the service.")):
    """Write all users and their access to a YAML file."""
    file = file or db.seed_path()
    db.write_users_file(file, core.export_users(conn))
    console.print(f"Wrote users to {file}")


@app.command("import")
def import_users(file: Path = typer.Argument(None, help="Default: users.yaml of the service.")):
    """Apply a YAML file: add missing users, update changed ones and their access."""
    records = db.read_users_file(file or db.seed_path())
    changes = users_service.call("POST", "/users/import", actor, json={"users": records})
    console.print("\n".join(changes) if changes else "Nothing to change.")
