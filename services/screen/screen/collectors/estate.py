"""The best homes in Italy right now, from our estate service.

Each one gets a QR code: point a phone's camera at the TV to open the listing.
The codes are drawn as SVG, so they stay sharp at any screen size.
"""

import os
import re
from datetime import date

import httpx
import segno

KINDS = {"apartment": "apartment", "house": "house", "other": "other"}
OCCUPANCY = {"free": "free", "occupied": "occupied", "being freed": "being freed"}
SUMMARY_LENGTH = 220  # characters; the card has room for about five lines
# Auction descriptions often start with the court's file numbers: nothing to read on a TV
COURT_PREFIX = re.compile(r"^\s*Tribunale:.*?pvp:\s*\d+\s*", re.I | re.S)


def fetch(config: dict) -> dict:
    estate = config["estate"]
    response = httpx.get(
        estate["url"].rstrip("/") + "/listings/top",
        params={"limit": estate["count"]},
        headers={"X-Api-Token": os.environ.get("API_TOKEN", "")},
        timeout=15,
    )
    response.raise_for_status()
    return {"listings": [prepare(listing) for listing in response.json()]}


def prepare(listing: dict) -> dict:
    """What one card shows."""
    specs = []
    if listing["m2"]:
        specs.append(f"{listing['m2']:.0f} m²")
    if listing["bedrooms"] is not None:
        specs.append(f"{'~' if listing['bedrooms_guessed'] else ''}{listing['bedrooms']} bedr.")
    specs.append(KINDS.get(listing["kind"], listing["kind"]))
    return {
        "id": listing["id"],
        "price": euros(listing["price"]),
        "score": listing["score"],
        "town": listing["town"] or "?",
        "province": listing["province"] or "",
        "specs": " · ".join(specs),
        "auction": auction_label(listing),
        "summary": shorten(COURT_PREFIX.sub("", listing["description"]), SUMMARY_LENGTH),
        "qr": qr_svg(listing["url"]),
    }


def euros(value: float | None) -> str:
    return f"{value:,.0f} €".replace(",", " ") if value is not None else "?"


def auction_label(listing: dict) -> str:
    """'Auction 25 Nov · free', 'Auction', or '' for a normal sale."""
    if not listing["is_auction"]:
        return ""
    parts = ["Auction"]
    if listing["auction_date"]:
        parts[0] += " " + date.fromisoformat(listing["auction_date"]).strftime("%-d %b")
    if listing["occupancy"] in OCCUPANCY:
        parts.append(OCCUPANCY[listing["occupancy"]])
    return " · ".join(parts)


def shorten(text: str, length: int) -> str:
    text = " ".join(text.split())  # one line, single spaces
    if len(text) <= length:
        return text
    return text[: length - 1].rsplit(" ", 1)[0] + "…"


def qr_svg(url: str) -> str:
    """A QR code as an SVG element, black on white, sized by the page's CSS.

    Error level L keeps the code as small (as few squares) as possible, so each
    square is bigger on the TV and easier for a phone to read from the sofa.
    """
    return segno.make(url, error="l", micro=False).svg_inline(omitsize=True, border=2, dark="#000", light="#fff")
