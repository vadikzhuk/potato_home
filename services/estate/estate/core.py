"""Business logic of the estate service: storing listings, filtering and scoring them.

Listings are stored as the sites show them, whatever criteria.yaml says.
Filtering and scoring happen when someone reads them, so a changed
criteria.yaml applies at once, also to listings found earlier.

Access (from the users service, as "estate"):
  read  - see listings and get the daily digest
  write - also hide and star listings
  admin - also start a fetch by hand
"""

import os
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import parse

LOCAL_TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Riga")

# What every source gives for a listing (see sources/)
LISTING_FIELDS = ("source", "source_id", "url", "title", "kind", "is_auction", "region", "province",
                  "town", "address", "price", "m2", "rooms", "bedrooms", "bedrooms_guessed",
                  "description", "features", "photo", "auction_date", "occupancy")
FLAGS = ("hidden", "starred")
SCORE_PARTS = ("price_per_m2", "price", "condition", "extras", "price_drop", "details")
MIN_SAMPLES = 5  # listings with m² a province needs for its own median price per m²


class EstateError(Exception):
    """An error with a message meant for the person using the service."""


class NotFound(EstateError):
    pass


class Forbidden(EstateError):
    pass


class Invalid(EstateError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_today() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


class Trusted:
    """The terminal, or another of our services asking with the API token alone: may do anything."""
    name = "terminal"

    def can(self, needed: str) -> bool:
        return True


TRUSTED = Trusted()


def require(person, needed: str) -> None:
    """Refuse unless the person has at least `needed` access to estate."""
    if person is None or not person.can(needed):
        raise Forbidden(f"You need {needed} access to estate for that.")


# --- Saving what the sources found ----------------------------------------------

def save_listing(conn: sqlite3.Connection, listing: dict, seen_at: str | None = None) -> bool:
    """Insert or update a listing from a source. Returns True if it is new.

    Our own marks (hidden, starred, duplicate_of) and when it was first seen
    stay as they are. Every new price goes into the price history.
    """
    seen_at = seen_at or now()
    values = {field: listing[field] for field in LISTING_FIELDS}
    values["features"] = ", ".join(listing["features"])
    values["is_auction"] = int(bool(values["is_auction"]))
    values["bedrooms_guessed"] = int(bool(values["bedrooms_guessed"]))
    row = conn.execute("SELECT id, price FROM listings WHERE source = ? AND source_id = ?",
                       (values["source"], values["source_id"])).fetchone()
    with conn:  # commits at the end
        if row is None:
            columns = ", ".join(LISTING_FIELDS)
            cur = conn.execute(
                f"INSERT INTO listings ({columns}, first_price, first_seen, last_seen)"
                f" VALUES ({', '.join(':' + f for f in LISTING_FIELDS)}, :price, :seen_at, :seen_at)",
                {**values, "seen_at": seen_at},
            )
            listing_id, old_price = cur.lastrowid, None
        else:
            # Auction details may have come from a duplicate on PVP: keep them if this site has none
            updates = ", ".join(f"{f} = COALESCE(:{f}, {f})" if f in ("auction_date", "occupancy") else f"{f} = :{f}"
                                for f in LISTING_FIELDS)
            conn.execute(f"UPDATE listings SET {updates}, last_seen = :seen_at WHERE id = :id",
                         {**values, "seen_at": seen_at, "id": row["id"]})
            listing_id, old_price = row["id"], row["price"]
        if values["price"] is not None and values["price"] != old_price:
            conn.execute("INSERT INTO prices (listing_id, price, seen_at) VALUES (?, ?, ?)",
                         (listing_id, values["price"], seen_at))
    return row is None


def _same_price(a: float, b: float) -> bool:
    return abs(a - b) <= max(2, 0.001 * max(a, b))  # sites round differently


def same_property(a: dict, b: dict) -> bool:
    """Are two listings from the same town probably one property?

    An auction on two sites has the same price: the lowest offer on both, or
    the base price on one of them (the lowest offer is 75% of it).
    Otherwise: same kind, size within 5% and price within 2%.
    """
    if a["is_auction"] and b["is_auction"] and a["source"] != b["source"]:
        pa, pb = a["price"], b["price"]
        return _same_price(pa, pb) or _same_price(pa, 0.75 * pb) or _same_price(pb, 0.75 * pa)
    if a["kind"] != b["kind"] or not a["m2"] or not b["m2"]:
        return False
    return (abs(a["m2"] - b["m2"]) <= 0.05 * max(a["m2"], b["m2"])
            and abs(a["price"] - b["price"]) <= 0.02 * max(a["price"], b["price"]))


def link_duplicates(conn: sqlite3.Connection, criteria: dict) -> int:
    """Mark listings of the same property, so each property is shown once.

    The copy with a photo (or else the older one) stays; the others point to it
    with duplicate_of. It gets the auction date and occupancy if it lacks them.
    Returns how many listings were marked.
    """
    rows = conn.execute(
        "SELECT * FROM listings WHERE duplicate_of IS NULL AND last_seen >= ?"
        " AND town IS NOT NULL AND price IS NOT NULL ORDER BY id",
        (_gone_cutoff(criteria),),
    ).fetchall()
    by_town = defaultdict(list)
    for row in rows:
        by_town[row["town"].casefold()].append(dict(row))

    linked = 0
    with conn:
        for listings in by_town.values():
            kept: list[dict] = []
            for listing in listings:
                twin = next((k for k in kept if same_property(k, listing)), None)
                if twin is None:
                    kept.append(listing)
                    continue
                main, copy = (listing, twin) if listing["photo"] and not twin["photo"] else (twin, listing)
                kept[kept.index(twin)] = main
                conn.execute("UPDATE listings SET duplicate_of = ? WHERE id = ? OR duplicate_of = ?",
                             (main["id"], copy["id"], copy["id"]))
                conn.execute("UPDATE listings SET auction_date = COALESCE(auction_date, ?),"
                             " occupancy = COALESCE(occupancy, ?), is_auction = MAX(is_auction, ?) WHERE id = ?",
                             (copy["auction_date"], copy["occupancy"], copy["is_auction"], main["id"]))
                linked += 1
    return linked


# --- Fetch runs ---------------------------------------------------------------
# Only the service itself fetches (the terminal asks it to), so it is the only
# program writing the database. On a Mac, Docker's shared folders corrupt SQLite
# when two programs write at once.

INTERRUPTED = "interrupted: the service stopped during the fetch"

def start_run(conn: sqlite3.Connection) -> int:
    with conn:
        return conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now(),)).lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, seen: int, added: int, errors: list[str]) -> dict:
    with conn:
        conn.execute("UPDATE runs SET finished_at = ?, seen = ?, added = ?, errors = ? WHERE id = ?",
                     (now(), seen, added, "\n".join(errors), run_id))
    return get_run(conn, run_id)


def get_run(conn: sqlite3.Connection, run_id: int) -> dict:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"Fetch #{run_id} not found.")
    return dict(row)


def list_runs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Newest first, including one that is still running (finished_at is null)."""
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


def latest_run(conn: sqlite3.Connection) -> dict | None:
    """The newest run that finished (not one cut off by a restart)."""
    row = conn.execute("SELECT * FROM runs WHERE finished_at IS NOT NULL AND errors NOT LIKE 'interrupted%'"
                       " ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def running_run(conn: sqlite3.Connection) -> dict | None:
    """A run that started and hasn't finished, if there is one."""
    row = conn.execute("SELECT * FROM runs WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def mark_interrupted(conn: sqlite3.Connection) -> int:
    """When the service starts, any unfinished run was cut off by the restart. Returns how many."""
    with conn:
        return conn.execute("UPDATE runs SET finished_at = ?, errors = ? WHERE finished_at IS NULL",
                            (now(), INTERRUPTED)).rowcount


# --- Filtering and scoring ----------------------------------------------------

def _gone_cutoff(criteria: dict) -> str:
    """Listings last seen before this time are gone from the sites."""
    days = criteria["fetch"]["gone_after_days"]
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def text_of(listing) -> str:
    return " ".join((listing["title"], listing["description"], listing["features"]))


def why_not(listing, criteria: dict) -> str | None:
    """Why this listing isn't shown, as "reason: details", or None if it matches the criteria."""
    search = criteria["search"]
    if listing["duplicate_of"]:
        return f"duplicate: of #{listing['duplicate_of']}"
    if listing["last_seen"] < _gone_cutoff(criteria):
        return f"gone: last seen {listing['last_seen'][:10]}"
    if listing["auction_date"] and listing["auction_date"] < local_today():
        return f"auction over: it was on {listing['auction_date']}"
    if listing["hidden"]:
        return "hidden"
    if listing["region"] not in search["regions"]:
        return f"region: {listing['region']} isn't searched"
    if listing["price"] is None:
        return "no price"
    if not search["min_price"] <= listing["price"] <= search["max_price"]:
        return f"price: {listing['price']:,.0f} €"
    if listing["kind"] not in search["kinds"]:
        return f"kind: {listing['kind']}"
    if listing["is_auction"] and not search["auctions"]:
        return "auctions are off"
    bedrooms = listing["bedrooms"]
    if bedrooms is None and not search["unknown_bedrooms"]:
        return "bedrooms: unknown"
    if bedrooms is not None and not search["bedrooms"]["min"] <= bedrooms <= search["bedrooms"]["max"]:
        return f"bedrooms: {bedrooms}"
    excluded = parse.has_any(text_of(listing), criteria["exclude_words"])
    if excluded:
        return f"excluded word: {excluded[0]}"
    return None


def province_medians(listings: list) -> dict[str, float]:
    """Median price per m² in each province, from the listings given.

    Provinces with too few listings with m² get the median of all of them.
    These are only cheap listings (we fetch up to max_price), so it says
    "cheap among cheap": good for ranking, not a market price.
    """
    per_m2 = defaultdict(list)
    for listing in listings:
        if listing["m2"] and listing["price"]:
            per_m2[listing["province"]].append(listing["price"] / listing["m2"])
    everything = [value for values in per_m2.values() for value in values]
    overall = statistics.median(everything) if everything else None
    medians = defaultdict(lambda: overall)
    medians.update({p: statistics.median(v) for p, v in per_m2.items() if len(v) >= MIN_SAMPLES})
    return medians


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score(listing, medians: dict, criteria: dict) -> tuple[int, dict]:
    """(score 0-100, details) for one listing.

    Each part is 0..1, then weighted by criteria.yaml. details has the points
    of each part and the words that counted, so you can see why.
    """
    scoring = criteria["scoring"]
    text = text_of(listing)
    price, m2 = listing["price"], listing["m2"]
    good = parse.has_any(text, scoring["good_condition"])
    bad = parse.has_any(text, scoring["bad_condition"])
    extras = parse.has_any(text, scoring["extras"])

    median = medians[listing["province"]]
    if price and m2 and median:
        ratio = price / m2 / median
        per_m2 = _clamp(1.5 - ratio)  # half the median or less: 1; the median: 0.5; 1.5 times: 0
    else:
        per_m2 = 0.5  # unknown: neither good nor bad
    condition = 0.5 + 0.25 * len(good) - 0.25 * len(bad)
    condition += {"free": 0.25, "occupied": -0.25}.get(listing["occupancy"], 0)
    first = listing["first_price"]
    drop = (first - price) / first if first and price and price < first else 0
    known = (bool(m2) + (0.5 if listing["bedrooms_guessed"] else bool(listing["bedrooms"]))
             + bool(listing["photo"])) / 3

    parts = {
        "price_per_m2": per_m2,
        "price": _clamp(1 - price / criteria["search"]["max_price"]) if price else 0,
        "condition": _clamp(condition),
        "extras": _clamp(len(extras) / 3),
        "price_drop": _clamp(drop / 0.2),
        "details": known,
    }
    weights = scoring["weights"]
    total_weight = sum(weights.get(part, 0) for part in SCORE_PARTS)
    points = {part: round(100 * weights.get(part, 0) * parts[part] / total_weight) for part in SCORE_PARTS}
    if listing["province"] in scoring["preferred_provinces"]:
        points["preferred"] = scoring["preferred_bonus"]
    total = min(100, sum(points.values()))
    return total, {"points": points, "good": good, "bad": bad, "extras": extras, "drop": round(100 * drop)}


# --- Reading ------------------------------------------------------------------

def view(listing, score_: int | None = None, details: dict | None = None, links: list | None = None) -> dict:
    """A listing as the API and CLI show it."""
    data = dict(listing)
    data["features"] = [f for f in listing["features"].split(", ") if f]
    data["is_auction"] = bool(listing["is_auction"])
    data["bedrooms_guessed"] = bool(listing["bedrooms_guessed"])
    data["hidden"] = bool(listing["hidden"])
    data["starred"] = bool(listing["starred"])
    data["score"] = score_
    data["score_details"] = details
    data["links"] = [{"source": listing["source"], "url": listing["url"]}] + (links or [])
    return data


def _current(conn: sqlite3.Connection, criteria: dict) -> list[sqlite3.Row]:
    """Listings still on the sites, one per property."""
    return conn.execute(
        "SELECT * FROM listings WHERE duplicate_of IS NULL AND last_seen >= ?", (_gone_cutoff(criteria),)
    ).fetchall()


def _links(conn: sqlite3.Connection) -> dict[int, list[dict]]:
    """Links to the duplicates of each listing: {main id: [{source, url}]}"""
    links = defaultdict(list)
    for row in conn.execute("SELECT duplicate_of, source, url FROM listings WHERE duplicate_of IS NOT NULL"):
        links[row["duplicate_of"]].append({"source": row["source"], "url": row["url"]})
    return links


def ranked(conn: sqlite3.Connection, criteria: dict, include=lambda listing: True) -> list[dict]:
    """Listings matching the criteria (and `include`), best first."""
    current = _current(conn, criteria)
    medians = province_medians(current)
    links = _links(conn)
    result = []
    for listing in current:
        if include(listing) and why_not(listing, criteria) is None:
            total, details = score(listing, medians, criteria)
            result.append(view(listing, total, details, links[listing["id"]]))
    return sorted(result, key=lambda l: (-l["score"], l["price"]))


def top(conn: sqlite3.Connection, criteria: dict, limit: int = 10, auctions: bool | None = None) -> list[dict]:
    """The best listings now. auctions: None = all, True = only auctions, False = no auctions."""
    return ranked(conn, criteria, lambda l: auctions is None or bool(l["is_auction"]) == auctions)[:limit]


def get_listing(conn: sqlite3.Connection, criteria: dict, listing_id: int) -> dict:
    """One listing with its score, price history and why it isn't shown (if it isn't)."""
    listing = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if listing is None:
        raise NotFound(f"Listing #{listing_id} not found.")
    total, details = score(listing, province_medians(_current(conn, criteria)), criteria)
    data = view(listing, total, details, _links(conn)[listing_id])
    data["why_not"] = why_not(listing, criteria)
    data["prices"] = [dict(r) for r in conn.execute(
        "SELECT price, seen_at FROM prices WHERE listing_id = ? ORDER BY seen_at", (listing_id,))]
    return data


def starred(conn: sqlite3.Connection, criteria: dict) -> list[dict]:
    """Starred listings that are still on the sites, matching the criteria or not."""
    current = _current(conn, criteria)
    medians = province_medians(current)
    links = _links(conn)
    return [view(l, *score(l, medians, criteria), links[l["id"]]) for l in current if l["starred"]]


def set_flags(conn: sqlite3.Connection, criteria: dict, person, listing_id: int, **flags) -> dict:
    """Hide or star a listing (for everyone at home). Needs write access."""
    require(person, "write")
    unknown = set(flags) - set(FLAGS)
    if unknown:
        raise Invalid(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    get_listing(conn, criteria, listing_id)  # NotFound if there is no such listing
    with conn:
        for flag, value in flags.items():
            # `flag` is safe in the SQL: only names from FLAGS get here
            conn.execute(f"UPDATE listings SET {flag} = ? WHERE id = ?", (int(bool(value)), listing_id))
    return get_listing(conn, criteria, listing_id)


def price_at(conn: sqlite3.Connection, listing_id: int, moment: str) -> float | None:
    row = conn.execute("SELECT price FROM prices WHERE listing_id = ? AND seen_at <= ?"
                       " ORDER BY seen_at DESC LIMIT 1", (listing_id, moment)).fetchone()
    return row["price"] if row else None


def digest(conn: sqlite3.Connection, criteria: dict, after_run: int | None = None) -> dict:
    """What's new for the daily message: listings first seen after run `after_run`
    finished (or during the latest run), and starred listings that got cheaper.

    {"run": latest finished run or None, "new": [...], "auctions": [...], "price_drops": [...]}
    """
    run = latest_run(conn)
    if run is None:
        return {"run": None, "new": [], "auctions": [], "price_drops": []}
    since = run["started_at"]
    if after_run is not None:
        previous = conn.execute("SELECT finished_at FROM runs WHERE id = ?", (after_run,)).fetchone()
        if previous and previous["finished_at"]:
            since = previous["finished_at"]

    settings = criteria["digest"]
    fresh = [l for l in ranked(conn, criteria, lambda l: l["first_seen"] > since)
             if l["score"] >= settings["min_score"]]
    drops = []
    for listing in starred(conn, criteria):
        before = price_at(conn, listing["id"], since)
        if before and listing["price"] and listing["price"] < before:
            drops.append({**listing, "old_price": before})
    return {
        "run": run,
        "new": [l for l in fresh if not l["is_auction"]][: settings["top"]],
        "auctions": [l for l in fresh if l["is_auction"]][: settings["auctions"]],
        "price_drops": drops,
    }
