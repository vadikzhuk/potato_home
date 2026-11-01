"""Terminal interface. Run `botwatch --help` to see all commands.

It only reads: the database is opened read-only, the running service is the only
program writing it.
"""

import sqlite3

import typer
from rich.console import Console
from rich.table import Table

from . import core, db
from .core import LOCAL_TZ, parse

app = typer.Typer(help="Your Telegram bots: how they are doing and how they are used.", no_args_is_help=True)
console = Console()

# Filled in by main() before any command runs
conn: sqlite3.Connection


@app.callback()
def main():
    global conn
    conn = db.connect(read_only=True)


def run():
    """Entry point of the `botwatch` command: shows errors as short red messages."""
    try:
        app()
    except core.BotwatchError as error:
        console.print(f"[red]{error}[/red]")
        raise SystemExit(1)


def local(iso: str | None) -> str:
    return parse(iso).astimezone(LOCAL_TZ).strftime("%d.%m %H:%M") if iso else "-"


def number(value, suffix: str = "") -> str:
    return "-" if value is None else f"{value:g}{suffix}"


@app.command()
def status():
    """Every bot as last checked (once a minute)."""
    bots = core.status(conn)
    if not bots:
        console.print("No bots checked yet. Bots need the potato.bot label: see bots/compose.yml.")
        return
    table = Table("Bot", "State", "Since", "Memory", "CPU", "Up 24h / 7d", "Errors today", "Today")
    for b in bots:
        name = b["bot"] + (f"\n@{b['username']}" if b["username"] else "")
        state = ("[red]" if b["problems"] else "[green]") + b["state"] + "[/]"
        memory = f"{number(b['memory_mb'])} / {number(b['memory_limit_mb'])} MB" if b["memory_mb"] else "-"
        today = f"{b['today']['updates']} updates, {b['today']['users']} users" if b["today"] else "-"
        table.add_row(name, state, local(b["started_at"]), memory, number(b["cpu_percent"], "%"),
                      f"{number(b['uptime_day'], '%')} / {number(b['uptime_week'], '%')}",
                      str(b["errors_today"]), today)
    console.print(table)
    for b in bots:
        for problem in b["problems"]:
            console.print(f"[red]{b['bot']}: {problem}[/red]")
        if b["last_error"]:
            console.print(f"[yellow]{b['bot']}, last error in its log ({local(b['last_error_at'])}): "
                          f"{b['last_error']}[/yellow]")
    console.print(f"[dim]Checked {local(max(b['at'] for b in bots))}[/dim]")


@app.command()
def usage(bot: str = typer.Argument(..., help="Its name in bots/compose.yml, or its @username."),
          days: int = typer.Option(7, "--days", "-d", help="How many days back, today included.")):
    """How a bot was used, day by day (counted by botstats.py inside the bot)."""
    u = core.usage(conn, bot, days)
    if not u["username"]:
        console.print("botwatch doesn't know this bot's @username yet: Telegram didn't answer so far.")
        return
    table = Table("Day", "Updates", "Users", "Failed", "Avg ms")
    for d in u["days"]:
        table.add_row(d["date"], str(d["updates"]), str(d["users"]), str(d["failed"]), number(d["avg_ms"]))
    t = u["total"]
    table.add_row("[bold]Total", f"[bold]{t['updates']}", f"[bold]{t['users']}", f"[bold]{t['failed']}",
                  f"[bold]{number(t['avg_ms'])}")
    console.print(f"[bold]{u['bot']}[/bold] @{u['username']}")
    console.print(table)
    console.print(f"New users: {t['new_users']}   Blocked the bot: {u['blocked']}")
    if u["commands"]:
        console.print("Commands: " + ", ".join(f"{name} {count}" for name, count in u["commands"]))
    if u["other"]:
        console.print("Other: " + ", ".join(f"{name} {count}" for name, count in u["other"]))
    if not t["updates"]:
        console.print("[dim]No usage counted. Does the bot call track(app) from botstats.py?[/dim]")


@app.command()
def alerts(count: int = typer.Option(20, "--count", "-n", help="How many to show.")):
    """The latest alerts (the home bot sends them to botwatch admins)."""
    rows = core.alerts(conn, limit=count)
    if not rows:
        console.print("No alerts.")
    for a in rows:
        console.print(f"[dim]{local(a['at'])}[/dim] {a['text']}")
