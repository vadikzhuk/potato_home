"""Terminal interface. Run `estate --help` to see all commands.

Each command reads its arguments and calls one function from core.py.
The terminal needs no user: whoever can run it can read the database file anyway.
Hidden and starred are shared by everyone at home.
"""

import sqlite3
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from . import core, criteria, db, fetcher
from .sources import SOURCES

app = typer.Typer(help="Cheap houses and apartments in Italy.", no_args_is_help=True)
console = Console()

# Filled in by main() before any command runs
conn: sqlite3.Connection


@app.callback()
def main():
    global conn
    conn = db.connect()


def run():
    """Entry point of the `estate` command: shows errors as short red messages."""
    try:
        app()
    except core.EstateError as error:
        console.print(f"[red]{error}[/red]")
        raise SystemExit(1)


class Admin:
    """The terminal acts with full access."""
    name = "terminal"

    def can(self, needed: str) -> bool:
        return True


def euros(value: float | None) -> str:
    return f"{value:,.0f} €".replace(",", " ") if value is not None else "-"


def bedrooms_text(listing: dict) -> str:
    if listing["bedrooms"] is None:
        return "?"
    return f"~{listing['bedrooms']}" if listing["bedrooms_guessed"] else str(listing["bedrooms"])


def listings_table(listings: list[dict]) -> Table:
    table = Table("#", "Score", "Price", "m²", "Beds", "Kind", "Where", "Title")
    for l in listings:
        kind = l["kind"] + (" 🔨" if l["is_auction"] else "") + (" ⭐" if l["starred"] else "")
        table.add_row(str(l["id"]), str(l["score"]), euros(l["price"]), f"{l['m2']:.0f}" if l["m2"] else "-",
                      bedrooms_text(l), kind, f"{l['town'] or '?'} ({l['province']})", l["title"][:50])
    return table


@app.command()
def top(
    count: int = typer.Option(20, "--count", "-n", help="How many to show."),
    auctions: bool = typer.Option(None, "--auctions/--no-auctions", help="Only auctions, or none."),
):
    """The best listings now, by criteria.yaml. 🔨 = auction, ⭐ = starred."""
    listings = core.top(conn, criteria.load(), count, auctions)
    console.print(listings_table(listings) if listings else "Nothing matches. Try `estate check`.")


@app.command()
def show(listing_id: int):
    """One listing: everything known, why it scored what it scored, its prices."""
    l = core.get_listing(conn, criteria.load(), listing_id)
    console.print(f"[bold]#{l['id']} {l['title']}[/bold]" + ("  ⭐" if l["starred"] else ""))
    console.print(f"{euros(l['price'])} · {l['m2'] or '?'} m² · {bedrooms_text(l)} bedrooms · {l['kind']}"
                  f" · {l['town'] or '?'}, {l['province']}, {l['region']}")
    if l["is_auction"]:
        when = f"on {l['auction_date']}" if l["auction_date"] else "(date: see the link)"
        console.print(f"Auction {when} · price is the lowest offer accepted"
                      f" · occupancy: {l['occupancy'] or 'unknown'}")
    if l["why_not"]:
        console.print(f"[yellow]Not shown: {l['why_not']}[/yellow]")
    console.print(l["description"])
    if l["features"]:
        console.print("[dim]" + ", ".join(l["features"]) + "[/dim]")

    d = l["score_details"]
    console.print(f"\n[bold]Score {l['score']}[/bold]: " + ", ".join(f"{part} {points}" for part, points in d["points"].items()))
    for label, words in (("good", d["good"]), ("bad", d["bad"]), ("extras", d["extras"])):
        if words:
            console.print(f"  {label}: {', '.join(words)}")
    console.print("\n" + "\n".join(link["url"] for link in l["links"]))
    if len(l["prices"]) > 1:
        console.print("Prices: " + " → ".join(f"{euros(p['price'])} ({p['seen_at'][:10]})" for p in l["prices"]))
    console.print(f"[dim]First seen {l['first_seen'][:10]}, last seen {l['last_seen'][:10]}[/dim]")


@app.command()
def starred():
    """Starred listings."""
    listings = core.starred(conn, criteria.load())
    console.print(listings_table(listings) if listings else "Nothing starred.")


def _flag(listing_id: int, **flags) -> None:
    l = core.set_flags(conn, criteria.load(), Admin(), listing_id, **flags)
    console.print(f"#{l['id']} {l['title']}: " + ", ".join(f"{k} {'on' if v else 'off'}" for k, v in flags.items()))


@app.command()
def star(listing_id: int):
    """Watch a listing: price drops come in the daily digest."""
    _flag(listing_id, starred=True)


@app.command()
def unstar(listing_id: int):
    _flag(listing_id, starred=False)


@app.command()
def hide(listing_id: int):
    """Never show this listing again."""
    _flag(listing_id, hidden=True)


@app.command()
def unhide(listing_id: int):
    _flag(listing_id, hidden=False)


@app.command()
def fetch(source: str = typer.Option(None, help=f"Only this one: {', '.join(SOURCES)}.")):
    """Fetch now instead of waiting for the daily time (takes a while)."""
    if source and source not in SOURCES:
        raise core.Invalid(f"Unknown source {source!r}. Known: {', '.join(SOURCES)}.")
    settings = criteria.load()
    sources = {source: SOURCES[source]} if source else None
    result = fetcher.run(conn, settings, sources, say=console.print)
    console.print(f"Done: {result['seen']} listings, {result['added']} new.")
    if result["errors"]:
        console.print(f"[red]{result['errors']}[/red]")


@app.command()
def runs(count: int = typer.Option(10, "--count", "-n")):
    """The latest fetches."""
    table = Table("#", "Started", "Took", "Seen", "New", "Errors")
    for r in core.list_runs(conn, count):
        took = "running" if not r["finished_at"] else f"{_minutes(r['started_at'], r['finished_at'])} min"
        table.add_row(str(r["id"]), r["started_at"][:16].replace("T", " "), took,
                      str(r["seen"]), str(r["added"]), f"[red]{r['errors']}[/]" if r["errors"] else "")
    console.print(table)


def _minutes(start: str, end: str) -> int:
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60)


@app.command()
def check():
    """Check criteria.yaml and show how the stored listings fare with it."""
    settings = criteria.load()
    console.print(f"[green]{criteria.path().name} is fine.[/green]")
    reasons: dict[str, int] = {}
    for listing in conn.execute("SELECT * FROM listings WHERE duplicate_of IS NULL"):
        reason = (core.why_not(listing, settings) or "shown").split(":")[0]  # "price: 35 000 €" -> "price"
        reasons[reason] = reasons.get(reason, 0) + 1
    table = Table("Listings", "Count", title="Stored listings (one per property)")
    for reason, number in sorted(reasons.items(), key=lambda item: -item[1]):
        table.add_row(reason, str(number))
    console.print(table)
